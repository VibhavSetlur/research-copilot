"""Reproduce-a-run — the reproducibility verdict (Phase 1.10).

This is the payoff of provenance (1.7) + artifacts (1.8) + the CLI (1.9):
take a recorded run, re-execute its exact command in its recorded working
directory, and compare what it produces now against what it produced then.

A result you can reproduce is a result you can trust. The verdict is the
single most valuable thing a research OS offers a computational scientist:

  REPRODUCED  every recorded output came back byte-for-byte (same sha256)
  DIVERGED    at least one recorded output now has a different hash
  INCOMPLETE  at least one recorded output was not regenerated (missing),
              and nothing diverged (a weaker failure than DIVERGED)

The comparison is pure and stdlib-only so it is trivially testable and
never depends on the daemon being up. ``compare_artifacts`` is the core;
the daemon wires the actual re-run around it. The verdict also carries a
compact environment diff so reproducibility regressions can be diagnosed
without dumping the full environment.
"""
from __future__ import annotations

from typing import Any

_SENSITIVE_ENV_TOKENS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")


def _redact_env_value(key: str, value: object) -> object:
    if any(token in key.upper() for token in _SENSITIVE_ENV_TOKENS):
        return "[REDACTED]"
    return value


def _env_diff(recorded: dict[str, object] | None, current: dict[str, object] | None) -> dict[str, Any]:
    recorded = recorded or {}
    current = current or {}
    added = sorted(k for k in current if k not in recorded)
    removed = sorted(k for k in recorded if k not in current)
    changed: dict[str, dict[str, object]] = {}
    for key in sorted(recorded.keys() & current.keys()):
        if recorded[key] != current[key]:
            changed[key] = {
                "expected": _redact_env_value(key, recorded[key]),
                "actual": _redact_env_value(key, current[key]),
            }
    return {"added": added, "removed": removed, "changed": changed}


def env_diff(recorded: dict[str, object] | None, current: dict[str, object] | None) -> dict[str, Any]:
    """Public env diff helper used by reproduce verdict payloads and tests."""
    return _env_diff(recorded, current)

# Verdict constants — stable strings used by the CLI, HTTP, and tests.
REPRODUCED = "reproduced"
DIVERGED = "diverged"
INCOMPLETE = "incomplete"


def _by_path(artifacts: list[dict] | None) -> dict[str, dict]:
    """Index an artifact list by relative path. Last write wins."""
    out: dict[str, dict] = {}
    for a in artifacts or []:
        p = a.get("path")
        if p:
            out[p] = a
    return out


def compare_artifacts(
    recorded: list[dict] | None,
    fresh: list[dict] | None,
) -> dict[str, Any]:
    """Compare a recorded run's artifacts against a fresh run's artifacts.

    Both are lists of ``{path, sha256, size, ...}`` dicts (the shape the
    artifact tracker records). Comparison is by relative ``path`` then by
    ``sha256``. Returns a structured report:

        {
          "verdict": reproduced | diverged | incomplete,
          "matched":   [path, ...],   # same path, same sha256
          "changed":   [{path, recorded_sha256, fresh_sha256}, ...],
          "missing":   [path, ...],   # recorded but not regenerated
          "added":     [path, ...],   # produced now, not recorded before
          "unhashed":  [path, ...],   # couldn't compare (no hash either side)
          "counts": {...},
        }

    Pure: no I/O, never raises on well-formed input.
    """
    rec = _by_path(recorded)
    new = _by_path(fresh)

    matched: list[str] = []
    changed: list[dict] = []
    missing: list[str] = []
    unhashed: list[str] = []

    for path, ra in rec.items():
        fa = new.get(path)
        if fa is None:
            missing.append(path)
            continue
        r_hash = ra.get("sha256")
        f_hash = fa.get("sha256")
        if r_hash is None or f_hash is None:
            # One side was too big to hash (or unreadable) — fall back to
            # size as a weak signal, but flag it as not byte-verified.
            if ra.get("size") == fa.get("size"):
                unhashed.append(path)
            else:
                changed.append({
                    "path": path,
                    "recorded_sha256": r_hash,
                    "fresh_sha256": f_hash,
                    "recorded_size": ra.get("size"),
                    "fresh_size": fa.get("size"),
                    "reason": "size-differs-unhashed",
                })
            continue
        if r_hash == f_hash:
            matched.append(path)
        else:
            changed.append({
                "path": path,
                "recorded_sha256": r_hash,
                "fresh_sha256": f_hash,
            })

    added = [p for p in new if p not in rec]

    matched.sort()
    missing.sort()
    added.sort()
    unhashed.sort()
    changed.sort(key=lambda c: c["path"])

    if changed:
        verdict = DIVERGED
    elif missing:
        verdict = INCOMPLETE
    else:
        verdict = REPRODUCED

    return {
        "verdict": verdict,
        "matched": matched,
        "changed": changed,
        "missing": missing,
        "added": added,
        "unhashed": unhashed,
        "env_diff": _env_diff(recorded if isinstance(recorded, dict) else None, fresh if isinstance(fresh, dict) else None),
        "counts": {
            "recorded": len(rec),
            "fresh": len(new),
            "matched": len(matched),
            "changed": len(changed),
            "missing": len(missing),
            "added": len(added),
            "unhashed": len(unhashed),
        },
    }


def verdict_glyph(verdict: str) -> str:
    """A single-char status glyph for terminal output."""
    return {REPRODUCED: "✓", DIVERGED: "✗", INCOMPLETE: "≈"}.get(verdict, "·")
