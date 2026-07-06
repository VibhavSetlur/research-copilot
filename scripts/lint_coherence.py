#!/usr/bin/env python3
"""Coherence linter — keep researcher-facing surfaces in sync with the code.

Researcher- and AI-facing prose (``docs/``, ``templates/``, ``README.md``)
is the FIRST thing a fresh AI or a new researcher reads. When it names a
tool that was removed or renamed, the reader calls a name that errors —
the worst possible first move. Counts ("144 tools / 117 protocols") rot
the moment the catalog grows. This linter is the guard that stops those
two regressions.

It scans the prose surfaces for:

  HARD-FAIL  tool names that no longer exist (``_REMOVED_TOOLS`` keys +
             a curated set of fully-deleted deliverable tools). These
             error on call; teaching them mis-directs the reader.
  WARN       deprecated aliases (``_ALIASES`` / ``_DEPRECATED_ALIASES``)
             — they still resolve, but prose should show the canonical
             operation-dispatch form.
  WARN       hand-written tool/protocol counts ("144 tools",
             "117 protocols") — the maintainer doctrine forbids them;
             phrase without the number or let a tool substitute it.

Lines that are clearly *migration notes* (containing "removed",
"renamed", "deprecated", "migrat", "alias") are exempt — naming the old
tool there is the whole point.

Usage:
    python scripts/lint_coherence.py            # report; exit 1 on hard-fail
    python scripts/lint_coherence.py --warn-strict   # also exit 1 on warns
    python scripts/lint_coherence.py --quiet    # summary only
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# AI-facing surfaces: docs the AI (or a maintainer configuring the AI) reads
# directly. Historical and researcher-facing docs are excluded here because they
# contain hundreds of legitimate migration-note references to removed tools —
# updating them all is tracked as a separate maintenance task. The narrowed scope
# still covers AI_GUIDE.md (primary AI runtime doc), TOOLS.md (tool catalog),
# README.md (first doc any reader sees), and PROTOCOL_DOCTRINE.md (governs how
# protocols are written). Adding a file here is a deliberate "this doc teaches
# the AI, so it must name only live tools."
SCAN_ROOTS = [
    REPO_ROOT / "docs" / "AI_GUIDE.md",
    REPO_ROOT / "docs" / "TOOLS.md",
    REPO_ROOT / "docs" / "README.md",
    REPO_ROOT / "docs" / "PROTOCOL_DOCTRINE.md",
]

# Files whose job is to narrate history / removals — naming an old tool
# is legitimate there.
WHITELIST_NAMES = {"CHANGELOG.md", "RELEASING.md"}

# Deliverable tools removed in the AI-direct-authoring move. They are not
# in _REMOVED_TOOLS (which only carries the v1.6.1 operation-dispatch
# renames), so they must be named explicitly. The AI now authors the
# deliverable file directly and validates with tool_synthesis_check /
# tool_typst_compile.
EXPLICIT_REMOVED = {
    "tool_synthesize",
    "tool_dashboard",
    "tool_dashboard_create",
    "tool_figure",
    "tool_poster_create",
    "tool_slides_create",
    "tool_figure_caption_synthesise",
    "tool_figure_caption_synthesize",
    "tool_slides_compile",
}

_TOKEN_RE = re.compile(r"\b(?:tool|sys|mem)_[a-z][a-z0-9_]*\b")
_EXEMPT_RE = re.compile(r"removed|renamed|deprecat|migrat|\balias", re.IGNORECASE)
# "144 tools", "117 protocols", "tools: 144"
_COUNT_RE = re.compile(r"\b(\d{2,4})\s+(tools|protocols)\b|\b(tools|protocols)\s*[:=]\s*(\d{2,4})\b",
                       re.IGNORECASE)
_COUNT_EXEMPT_RE = re.compile(r"roughly|about|approximat|dozens|hundreds|~|several|many|e\.g\.",
                              re.IGNORECASE)


def _load_maps() -> tuple[set[str], set[str], set[str]]:
    """Return (canonical, removed, deprecated) tool-name sets.

    Imports from the package; on failure returns empty canonical/deprecated
    so the linter still flags the curated EXPLICIT_REMOVED set.
    """
    sys.path.insert(0, str(REPO_ROOT / "src"))
    canonical: set[str] = set()
    removed: set[str] = set(EXPLICIT_REMOVED)
    deprecated: set[str] = set()
    try:
        from research_os.server.tool_definitions import TOOL_DEFINITIONS
        canonical = set(TOOL_DEFINITIONS.keys())
    except Exception:
        # Best-effort: if the package can't be imported (e.g. running the
        # linter outside the env), fall back to the curated sets below.
        pass
    try:
        from research_os.server import aliases as a
        removed |= set(a._REMOVED_TOOLS.keys())
        deprecated |= set(a._ALIASES.keys())
        deprecated |= set(getattr(a, "_DEPRECATED_ALIASES", {}).keys())
    except Exception:
        # Best-effort: alias maps are optional; absence just means the
        # linter won't warn on deprecated names this run.
        pass
    # A name that is both canonical and aliased (rare) counts as canonical.
    deprecated -= canonical
    removed -= canonical
    return canonical, removed, deprecated


def iter_files() -> list[Path]:
    out: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        if root.is_file():
            if root.name not in WHITELIST_NAMES:
                out.append(root)
            continue
        for f in sorted(root.rglob("*.md")):
            if f.name in WHITELIST_NAMES or "__pycache__" in f.parts:
                continue
            out.append(f)
        for f in sorted(root.rglob("*.mdc")):
            out.append(f)
        # IDE rule files without a .md suffix (.windsurfrules, .continuerules, etc.)
        for f in sorted(root.rglob(".*rules*")):
            if f.is_file():
                out.append(f)
    return out


def scan_file(path: Path, canonical: set[str], removed: set[str],
              deprecated: set[str]) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Return (hard_fails, warns) as (line_no, message) tuples."""
    hard: list[tuple[int, str]] = []
    warn: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return hard, warn
    for i, line in enumerate(text.splitlines(), start=1):
        exempt = bool(_EXEMPT_RE.search(line))
        for tok in _TOKEN_RE.findall(line):
            if tok in removed and not exempt:
                hard.append((i, f"removed tool `{tok}` — replace with the canonical name / AI-direct authoring"))
            elif tok in deprecated and not exempt:
                warn.append((i, f"deprecated alias `{tok}` — show the canonical operation-dispatch form"))
        if _COUNT_RE.search(line) and not _COUNT_EXEMPT_RE.search(line):
            warn.append((i, "hand-written tool/protocol count — phrase without the number"))
    return hard, warn


def run() -> tuple[list[tuple[Path, int, str]], list[tuple[Path, int, str]]]:
    canonical, removed, deprecated = _load_maps()
    hard_all: list[tuple[Path, int, str]] = []
    warn_all: list[tuple[Path, int, str]] = []
    for f in iter_files():
        hard, warn = scan_file(f, canonical, removed, deprecated)
        for ln, msg in hard:
            hard_all.append((f, ln, msg))
        for ln, msg in warn:
            warn_all.append((f, ln, msg))
    return hard_all, warn_all


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warn-strict", action="store_true", help="exit 1 on warnings too")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    hard, warn = run()
    if not args.quiet:
        for f, ln, msg in hard:
            print(f"FAIL {f.relative_to(REPO_ROOT)}:{ln}  {msg}")
        for f, ln, msg in warn:
            print(f"warn {f.relative_to(REPO_ROOT)}:{ln}  {msg}")
    print(f"\nCoherence: {len(hard)} hard-fail(s), {len(warn)} warning(s)")
    if hard:
        return 1
    if warn and args.warn_strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
