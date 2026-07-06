#!/usr/bin/env python
"""Build the semantic-routing embeddings for protocols + tools.

Run this every time you add / rename / substantially edit a protocol,
add a new tool, or rename a tool. The preflight gate
`check_embeddings_fresh` will tell you when the on-disk embeddings
no longer match the on-disk source documents.

Output artefacts (checked into the repo so installs don't need fastembed
at runtime when using the trigger-based fallback):

    src/research_os/protocols/_embeddings.npz
        protocol_ids      : (N_p,)   str         — protocol identifiers like "methodology/preregistration"
        protocol_embeds   : (N_p, D) float32     — L2-normalised vectors
        tool_names        : (N_t,)   str         — tool identifiers like "tool_python_exec"
        tool_embeds       : (N_t, D) float32     — L2-normalised vectors

    src/research_os/protocols/_embeddings_meta.json
        {
          "model": "BAAI/bge-small-en-v1.5",
          "dim": 384,
          "schema_version": "1",
          "built_at": "<iso>",                   # written only when --stamp is passed
          "source_hash": "<sha256>",             # hash of the SOURCE documents (deterministic)
          "n_protocols": <int>,
          "n_tools": <int>
        }

Usage:
    python scripts/build_embeddings.py             # rebuild, write .npz + meta
    python scripts/build_embeddings.py --check     # exit nonzero if embeddings stale
    python scripts/build_embeddings.py --stamp     # also record build_at timestamp
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
PROTOCOLS_DIR = ROOT / "src" / "research_os" / "protocols"
EMBEDS_NPZ = PROTOCOLS_DIR / "_embeddings.npz"
EMBEDS_META = PROTOCOLS_DIR / "_embeddings_meta.json"

MODEL_NAME = "BAAI/bge-small-en-v1.5"
SCHEMA_VERSION = "1"


# ---------------------------------------------------------------------------
# Source-document composition
# ---------------------------------------------------------------------------


_TRIGGERS_IN_DOC_CAP = 6  # cap triggers per protocol in the embedded doc


def _compose_protocol_doc(protocol_id: str, yaml_data: dict) -> str:
    """Compose the text we embed for a single protocol.

    Order: name, summary, capped-trigger list, description, step names.

    P1: summary + triggers now live IN the protocol body (merged from the
    old router index), so this reads them straight from ``yaml_data``.

    Triggers are included but CAPPED — a protocol with 17 triggers would
    otherwise dominate the embedding doc and over-score on adjacent
    prompts. The runtime boost layer still sees the full trigger list for
    exact-phrase boosting; only the embedded representation is capped.
    """
    parts: list[str] = []
    parts.append(f"Protocol: {protocol_id}")
    if name := yaml_data.get("name"):
        parts.append(f"Name: {name}")
    if summary := yaml_data.get("summary"):
        parts.append(f"Summary: {summary}")
    if triggers := yaml_data.get("triggers"):
        valid = [t for t in triggers if isinstance(t, str)]
        # Prefer multi-word triggers (more specific signal) when capping.
        valid.sort(key=lambda t: (-t.count(" "), -len(t)))
        capped = valid[:_TRIGGERS_IN_DOC_CAP]
        if capped:
            parts.append(f"User says: {'; '.join(capped)}")
    if desc := yaml_data.get("description"):
        desc_str = str(desc).strip()
        # First paragraph is usually the most semantically dense.
        first_para = desc_str.split("\n\n", 1)[0]
        parts.append(f"Description: {first_para}")
    steps = yaml_data.get("steps") or yaml_data.get("decomposition") or []
    step_names = []
    for step in steps:
        if isinstance(step, dict) and (n := step.get("name") or step.get("id")):
            step_names.append(n)
    if step_names:
        parts.append("Steps: " + " | ".join(step_names[:10]))
    return "\n".join(parts)


def _compose_tool_doc(tool_name: str, tool_def: dict) -> str:
    parts: list[str] = [f"Tool: {tool_name}"]
    if short := tool_def.get("short"):
        parts.append(f"Short: {short}")
    if desc := tool_def.get("description"):
        parts.append(f"Description: {desc}")
    if category := tool_def.get("category"):
        parts.append(f"Category: {category}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_protocols() -> list[tuple[str, str]]:
    """Return [(protocol_id, search_doc), ...] for every non-underscore YAML.

    Includes core protocols + every bundled pack's protocols (pack ids
    are prefixed with the pack name, e.g. `humanities/archival/...`).
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _emit(yaml_path: Path, protocol_id: str) -> None:
        try:
            yaml_data = yaml.safe_load(yaml_path.read_text()) or {}
        except yaml.YAMLError as exc:
            print(f"WARN: skipping {yaml_path}: {exc}", file=sys.stderr)
            return
        doc = _compose_protocol_doc(protocol_id, yaml_data)
        if protocol_id in seen:
            return
        seen.add(protocol_id)
        out.append((protocol_id, doc))

    # Core protocols.
    for yaml_path in sorted(PROTOCOLS_DIR.rglob("*.yaml")):
        if yaml_path.name.startswith("_"):
            continue
        category = yaml_path.parent.name
        slug = yaml_path.stem
        _emit(yaml_path, f"{category}/{slug}")

    # Bundled-pack protocols. Discover via the plugin loader so external
    # packs land here automatically once they're pip-installed.
    sys.path.insert(0, str(ROOT / "src"))
    try:
        # Importing any symbol from research_os.server triggers the
        # module body which calls _discover_packs_once() at import time.
        from research_os.server import TOOL_DEFINITIONS  # noqa: F401
        from research_os.plugins.loader import (
            pack_protocol_dirs as _pack_dirs,
        )
        for pack_name, pdir in _pack_dirs().items():
            for yaml_path in sorted(pdir.rglob("*.yaml")):
                if yaml_path.name.startswith("_"):
                    continue
                rel = yaml_path.relative_to(pdir).with_suffix("")
                _emit(yaml_path, f"{pack_name}/{rel}")
    except Exception as exc:  # pragma: no cover
        print(f"WARN: pack-protocol scan skipped: {exc}", file=sys.stderr)

    return out


def _load_tools() -> list[tuple[str, str]]:
    """Return [(tool_name, search_doc), ...] for every defined tool."""
    sys.path.insert(0, str(ROOT / "src"))
    from research_os.server import TOOL_DEFINITIONS  # noqa: E402

    out: list[tuple[str, str]] = []
    for tool_name, tool_def in sorted(TOOL_DEFINITIONS.items()):
        out.append((tool_name, _compose_tool_doc(tool_name, tool_def)))
    return out


def _bundle_source_hash() -> str:
    """The compiled _protocols.bundle's source hash (P1 single source of truth).

    Freshness of every protocol-derived artefact keys off this one hash
    rather than per-file mtimes. Empty string if the bundle is absent.
    """
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from research_os.tools.actions.protocol import ProtocolRegistry

        return ProtocolRegistry.source_hash()
    except Exception:  # noqa: BLE001
        return ""


def _source_hash(protocol_docs: list[tuple[str, str]], tool_docs: list[tuple[str, str]]) -> str:
    """Deterministic hash over the SOURCE documents so we know when to rebuild.

    Folds in the compiled bundle's ``source_hash`` (P1) so any protocol
    change — which invalidates the bundle — also invalidates the
    embeddings, keeping one canonical freshness signal.
    """
    h = hashlib.sha256()
    h.update(MODEL_NAME.encode())
    h.update(SCHEMA_VERSION.encode())
    h.update(_bundle_source_hash().encode())
    h.update(b"\x03")
    for pid, doc in protocol_docs:
        h.update(pid.encode())
        h.update(b"\x00")
        h.update(doc.encode())
        h.update(b"\x01")
    for tname, doc in tool_docs:
        h.update(tname.encode())
        h.update(b"\x00")
        h.update(doc.encode())
        h.update(b"\x02")
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


def _embed(texts: list[str]) -> np.ndarray:
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:  # pragma: no cover
        print(
            "ERROR: fastembed not installed. Install with: "
            "pip install 'research-os[semantic]' (or pip install fastembed).",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    model = TextEmbedding(model_name=MODEL_NAME)
    vecs = np.array(list(model.embed(texts)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _save(
    protocol_ids: list[str],
    protocol_embeds: np.ndarray,
    tool_names: list[str],
    tool_embeds: np.ndarray,
    source_hash: str,
    stamp: bool,
) -> None:
    np.savez_compressed(
        EMBEDS_NPZ,
        protocol_ids=np.array(protocol_ids, dtype=object),
        protocol_embeds=protocol_embeds,
        tool_names=np.array(tool_names, dtype=object),
        tool_embeds=tool_embeds,
    )
    meta = {
        "model": MODEL_NAME,
        "dim": int(protocol_embeds.shape[1]) if protocol_embeds.size else 0,
        "schema_version": SCHEMA_VERSION,
        "source_hash": source_hash,
        "n_protocols": len(protocol_ids),
        "n_tools": len(tool_names),
    }
    if stamp:
        meta["built_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    EMBEDS_META.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")


def _load_meta() -> dict | None:
    if not EMBEDS_META.exists():
        return None
    try:
        return json.loads(EMBEDS_META.read_text())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Build semantic-routing embeddings.")
    ap.add_argument(
        "--check",
        action="store_true",
        help="Exit nonzero if the on-disk embeddings are stale vs the source.",
    )
    ap.add_argument(
        "--stamp",
        action="store_true",
        help="Record build_at timestamp in the meta file (off by default for reproducible builds).",
    )
    args = ap.parse_args()

    print(f"Scanning protocols under {PROTOCOLS_DIR.relative_to(ROOT)} …")
    protocol_docs = _load_protocols()
    print(f"  → {len(protocol_docs)} protocols")

    print("Loading tool definitions from research_os.server …")
    tool_docs = _load_tools()
    print(f"  → {len(tool_docs)} tools")

    src_hash = _source_hash(protocol_docs, tool_docs)
    meta = _load_meta()

    if args.check:
        if meta is None:
            print("STALE: no embeddings on disk.")
            return 1
        if meta.get("source_hash") != src_hash:
            print(
                f"STALE: source hash changed.\n"
                f"  on-disk:    {meta.get('source_hash')}\n"
                f"  source-now: {src_hash}",
            )
            return 1
        if meta.get("model") != MODEL_NAME or meta.get("schema_version") != SCHEMA_VERSION:
            print("STALE: model / schema version changed.")
            return 1
        print(
            f"OK: embeddings fresh ({meta.get('n_protocols')} protocols, "
            f"{meta.get('n_tools')} tools)."
        )
        return 0

    print(f"Embedding {len(protocol_docs)} protocol docs + {len(tool_docs)} tool docs …")
    protocol_embeds = _embed([d for _, d in protocol_docs]) if protocol_docs else np.zeros(
        (0, 384), dtype=np.float32
    )
    tool_embeds = _embed([d for _, d in tool_docs]) if tool_docs else np.zeros(
        (0, 384), dtype=np.float32
    )

    print(f"Writing {EMBEDS_NPZ.relative_to(ROOT)} + {EMBEDS_META.relative_to(ROOT)} …")
    _save(
        protocol_ids=[pid for pid, _ in protocol_docs],
        protocol_embeds=protocol_embeds,
        tool_names=[t for t, _ in tool_docs],
        tool_embeds=tool_embeds,
        source_hash=src_hash,
        stamp=args.stamp,
    )
    npz_size = EMBEDS_NPZ.stat().st_size
    print(
        f"  embeddings: {protocol_embeds.shape} protocols + {tool_embeds.shape} tools, "
        f"npz size = {npz_size/1024:.1f} KiB"
    )
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
