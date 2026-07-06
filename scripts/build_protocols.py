#!/usr/bin/env python3
"""Compile every protocol into ONE bundle — the single P1 build script.

Replaces the three legacy sidecar builders:
  * build_gate_meta.py          → derived here from each protocol's
                                   ``enforcement.gates`` block.
  * build_precondition_meta.py  → derived here from ``requires.checks``.
  * the route-meta half of build_embeddings.py → the routing map (was
    ``_route_meta.json``) is now part of the bundle.

After Protocol Unification each protocol YAML is self-contained: its body
(steps, expected_outputs, gates, preconditions) AND its routing metadata
(intent_class, triggers, decomposition, …) live in one file. This script
reads all of them, validates each against the ``Protocol`` model, derives
the hierarchy view, gate list, and precondition map, and writes one
msgpack ``_protocols.bundle``.

The only extra source is ``_routing_taxonomy.yaml`` — the irreducible
human-authored L1/L2 hierarchy labels + cross-intent shortcut_intents,
which are not derivable from any protocol body.

Usage:
    python scripts/build_protocols.py            # write the bundle
    python scripts/build_protocols.py --check     # exit 1 if stale (CI)

Importable: ``build_bundle()`` returns the dict; ``source_hash()`` returns
the canonical hash of all protocol YAMLs (preflight re-derives + compares).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import msgpack
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from research_os.protocols._tiers import infer_tier, is_valid_tier  # noqa: E402
from research_os.protocols.schema import Protocol  # noqa: E402

PROTOCOLS_DIR = REPO_ROOT / "src" / "research_os" / "protocols"
TAXONOMY_PATH = PROTOCOLS_DIR / "_routing_taxonomy.yaml"
BUNDLE_PATH = PROTOCOLS_DIR / "_protocols.bundle"
SCHEMA_VERSION = "3.0"


def _iter_core_protocol_files() -> list[tuple[str, Path]]:
    """(protocol_id, yaml_path) for every core protocol (sorted, stable)."""
    out: list[tuple[str, Path]] = []
    for yaml_file in sorted(PROTOCOLS_DIR.rglob("*.yaml")):
        if "light" in yaml_file.parts or yaml_file.name.startswith("_"):
            continue
        rel = yaml_file.relative_to(PROTOCOLS_DIR).with_suffix("")
        out.append((str(rel).replace("\\", "/"), yaml_file))
    return out


def source_hash() -> str:
    """Deterministic SHA-256 of all protocol YAMLs concatenated (+ taxonomy).

    Ordered by protocol id so the hash is reproducible. The taxonomy file
    is folded in too — a hierarchy/shortcut edit must invalidate the bundle.
    """
    h = hashlib.sha256()
    h.update(SCHEMA_VERSION.encode())
    for pid, path in _iter_core_protocol_files():
        h.update(pid.encode())
        h.update(b"\x00")
        h.update(path.read_bytes())
        h.update(b"\x01")
    if TAXONOMY_PATH.exists():
        h.update(b"taxonomy\x00")
        h.update(TAXONOMY_PATH.read_bytes())
    return h.hexdigest()


def _workflow_shape(body: dict) -> list[str]:
    tags = (body.get("scope_tags") or {}).get("workflow_shape") or []
    if isinstance(tags, str):
        return [tags.strip().lower()]
    if isinstance(tags, list):
        return [str(t).strip().lower() for t in tags if t]
    return []


def build_bundle() -> dict:
    """Read + validate every protocol, derive all views, return the bundle.

    Raises SystemExit(2) with a readable message on any validation error,
    duplicate gate key, or dangling protocol_completed reference.
    """
    errors: list[str] = []
    protocols: dict[str, dict] = {}
    gates: list[dict] = []
    gate_built_from: list[str] = []
    seen_gate_keys: dict[str, str] = {}
    preconditions: dict[str, list[dict]] = {}

    files = _iter_core_protocol_files()
    all_ids = {pid for pid, _ in files}

    for pid, path in files:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            errors.append(f"{pid}: YAML parse failed: {exc}")
            continue
        try:
            model = Protocol.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{pid}: validation failed: {exc}")
            continue
        if model.schema_version != SCHEMA_VERSION:
            errors.append(
                f"{pid}: schema_version {model.schema_version!r} != "
                f"{SCHEMA_VERSION!r} (run the merge / bump the field)"
            )
            continue

        # ── routing view (was _route_meta.json protocols[*]) ──────────
        tier = raw.get("tier")
        if not is_valid_tier(tier):
            category = pid.split("/")[0] if "/" in pid else None
            tier = infer_tier(
                intent_class=model.intent_class,
                sub_intent=model.sub_intent,
                category=category,
                protocol_id=pid,
            )
        entry: dict = {
            "id": model.id,
            "intent_class": model.intent_class,
            "sub_intent": model.sub_intent,
            "summary": model.summary or (raw.get("description") or "").split("\n")[0],
            "triggers": list(model.triggers),
            "shortcut_tool": model.shortcut_tool,
            "token_estimate": model.token_estimate,
            "decomposition": [d.model_dump(exclude_none=True) for d in model.decomposition],
            "workflow_shape": _workflow_shape(raw),
        }
        if is_valid_tier(tier):
            entry["tier"] = tier
        if model.modes:
            entry["modes"] = list(model.modes)
        protocols[pid] = entry

        # ── gates view (was _gate_meta.json) ──────────────────────────
        # source_protocol is the routable pid (``guidance/autopilot``), not
        # the body's bare ``id`` — matches the legacy _gate_meta.json.
        pid_gates = model.gate_list()
        for g in pid_gates:
            g["source_protocol"] = pid
        if pid_gates:
            for g in pid_gates:
                k = g["key"]
                if k in seen_gate_keys:
                    errors.append(
                        f"duplicate gate key {k!r}: declared in "
                        f"{seen_gate_keys[k]!r} and {pid!r} — keys must be "
                        "globally unique"
                    )
                    continue
                seen_gate_keys[k] = pid
                gates.append(g)
            gate_built_from.append(pid)

        # ── preconditions view (was _precondition_meta.json) ──────────
        pid_checks = model.precondition_list()
        if pid_checks:
            for c in pid_checks:
                if c["kind"] == "protocol_completed" and c["protocol"] not in all_ids:
                    errors.append(
                        f"{pid}: protocol_completed references unknown protocol "
                        f"{c['protocol']!r}"
                    )
            preconditions[pid] = pid_checks

    if errors:
        raise SystemExit("build_protocols failed:\n  " + "\n  ".join(errors))

    # ── taxonomy (hierarchy + shortcut_intents) ───────────────────────
    taxonomy = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8")) or {}

    gates.sort(key=lambda g: g["key"])
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "source_hash": source_hash(),
        "hierarchy": taxonomy.get("hierarchy", {}) or {},
        "shortcut_intents": taxonomy.get("shortcut_intents", {}) or {},
        "protocols": dict(sorted(protocols.items())),
        "gates": gates,
        "gate_built_from": sorted(gate_built_from),
        "preconditions": dict(sorted(preconditions.items())),
    }
    return bundle


def _write_bundle(bundle: dict) -> None:
    BUNDLE_PATH.write_bytes(msgpack.packb(bundle, use_bin_type=True))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the on-disk bundle is stale (do not write)",
    )
    args = ap.parse_args(argv)

    fresh = build_bundle()
    n_gates = len(fresh["gates"])
    n_pre = sum(len(v) for v in fresh["preconditions"].values())
    n_prot = len(fresh["protocols"])

    if args.check:
        if not BUNDLE_PATH.exists():
            print("MISSING _protocols.bundle — run scripts/build_protocols.py")
            return 1
        try:
            on_disk = msgpack.unpackb(BUNDLE_PATH.read_bytes(), raw=False)
        except Exception as exc:  # noqa: BLE001
            print(f"could not parse _protocols.bundle: {exc}")
            return 1
        if on_disk.get("source_hash") != fresh.get("source_hash"):
            print("STALE _protocols.bundle — recompile: python scripts/build_protocols.py")
            return 1
        print(
            f"_protocols.bundle fresh: {n_prot} protocol(s), {n_gates} gate(s), "
            f"{n_pre} precondition check(s)"
        )
        return 0

    _write_bundle(fresh)
    print(
        f"wrote {BUNDLE_PATH.relative_to(REPO_ROOT)}: {n_prot} protocol(s), "
        f"{n_gates} gate(s) from {len(fresh['gate_built_from'])} protocol(s), "
        f"{n_pre} precondition check(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
