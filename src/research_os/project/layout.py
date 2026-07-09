"""Canonical workspace directory layout — single source of truth.

Every workspace.mode used to hand-duplicate three near-identical directory
tuples (top_level / eager / lazy), restating the ~7 mode-agnostic safety
dirs in each.  That made the layout *implicit* — a change to the safety
contract meant editing a dozen copy-pasted tuples, and nothing guaranteed
the copies stayed in sync.

The layout is now DECLARED ONCE here and COMPOSED.  Each profile = a fixed
backbone (safety prefix + workspace tree + environment) plus a small,
mode-specific *work surface*.  The composer (``_compose_layout``) builds the
three tuples deterministically; ``SCAFFOLD_PROFILES`` is derived from
``LAYOUT_SPEC``, so the safety contract can never drift between modes.

Anything that needs the canonical layout — the wizard, sys_boot, the
README templates, docs — should read ``LAYOUT_SPEC`` / ``SCAFFOLD_PROFILES``
/ ``describe_layout()`` rather than re-listing directory names inline.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# The fixed backbone, declared once.
_SAFETY_PREFIX: tuple[str, ...] = (
    ".os_state",
    "docs",
    "inputs",
    "inputs/raw_data",
    "inputs/literature",
    "inputs/context",
)
_WORKSPACE_TREE: tuple[str, ...] = (
    "workspace",
    "workspace/logs",
    "workspace/scratch",
)
_ENVIRONMENT: tuple[str, ...] = ("environment",)


# Per-mode declarative spec.  Each entry declares ONLY what differs from the
# backbone:
#   work     — the mode-specific work-surface dirs (inserted after the safety
#              prefix, before the workspace tree)
#   synthesis— whether ``synthesis/`` is part of the layout at all
#   lazy     — dirs created LAZILY (only when the first artefact lands; tools
#              must call ``ensure_lazy_dir`` first). Everything else is eager.
#   summary  — one-line human description (surfaced by ``describe_layout``)
LAYOUT_SPEC: dict[str, dict] = {
    "analysis": {
        "work": ("literature",),
        "synthesis": True,
        "lazy": ("synthesis",),
        "summary": "Linear numbered-step analysis; synthesis/ holds the paper.",
    },
    "tool_build": {
        "work": ("spec", "decisions", "eval"),
        "synthesis": False,
        "lazy": (),
        "summary": "Governance layer over an inner tool repo: spec/decisions/eval.",
    },
    "exploration": {
        "work": (),
        "synthesis": True,
        "lazy": ("workspace/logs", "synthesis"),
        "summary": "Scratch-first probing; numbered steps appear on promote.",
    },
    "notebook": {
        "work": ("notebooks", "data", "outputs"),
        "synthesis": True,
        "lazy": ("synthesis",),
        "summary": "Jupyter-first: notebooks/ + data/ + outputs/.",
    },
    "multi_study": {
        "work": ("studies", "shared", "roll_up"),
        "synthesis": True,
        "lazy": ("synthesis",),
        "summary": "Program/portfolio: studies/ + shared/ + roll_up/.",
    },
    "hybrid": {
        "work": ("literature", "tool"),
        "synthesis": True,
        "lazy": ("tool", "synthesis"),
        "summary": "Analysis spine + lazy tool/ home for the inner software repo (also auto-detected).",
    },
}


def _compose_layout(spec: dict) -> dict[str, tuple[str, ...]]:
    """Build the three directory tuples for one mode from its declarative spec.

    top_level = safety prefix + work surface + workspace tree + [synthesis]
                + environment
    eager     = top_level minus the lazy dirs
    lazy      = the deferred dirs (created on first artefact)
    """
    lazy = tuple(spec.get("lazy", ()))
    top: tuple[str, ...] = (
        _SAFETY_PREFIX
        + tuple(spec.get("work", ()))
        + _WORKSPACE_TREE
        + (("synthesis",) if spec.get("synthesis") else ())
        + _ENVIRONMENT
    )
    eager = tuple(d for d in top if d not in lazy)
    return {"top_level_dirs": top, "eager_dirs": eager, "lazy_dirs": lazy}


# Derived registry — one composed profile per mode.
SCAFFOLD_PROFILES: dict[str, dict[str, tuple[str, ...]]] = {
    mode: _compose_layout(spec) for mode, spec in LAYOUT_SPEC.items()
}

# Back-compat module constants: ``analysis`` is the default profile.
TOP_LEVEL_DIRS: tuple[str, ...] = SCAFFOLD_PROFILES["analysis"]["top_level_dirs"]
EAGER_DIRS: tuple[str, ...] = SCAFFOLD_PROFILES["analysis"]["eager_dirs"]
LAZY_DIRS: tuple[str, ...] = SCAFFOLD_PROFILES["analysis"]["lazy_dirs"]


def describe_layout(mode: str = "analysis") -> str:
    """Human-readable one-paragraph description of a mode's canonical layout."""
    spec = LAYOUT_SPEC.get(mode)
    if spec is None:
        raise KeyError(f"unknown workspace mode: {mode!r}")
    profile = SCAFFOLD_PROFILES[mode]
    eager = ", ".join(profile["eager_dirs"])
    lazy = ", ".join(profile["lazy_dirs"]) or "(none)"
    return (
        f"{mode}: {spec['summary']}\n"
        f"  created at init (eager): {eager}\n"
        f"  created on first use (lazy): {lazy}"
    )


def _resolve_scaffold_profile(mode: str | None) -> tuple[str, dict[str, tuple[str, ...]]]:
    """Return ``(mode, profile)`` for *mode*, defaulting to ``analysis``."""
    resolved = mode if mode in SCAFFOLD_PROFILES else "analysis"
    return resolved, SCAFFOLD_PROFILES[resolved]


def ensure_lazy_dir(root: Path, rel: str) -> Path:
    """Create a lazy workspace directory at first write; idempotent.

    Tools call this before dropping the first artefact into a LAZY_DIRS
    path so the project surface stays minimal until real content arrives.
    Passing a path that is not in ``LAZY_DIRS`` raises so writers can't
    silently grow the lazy surface without updating the registry.
    """
    if rel not in LAZY_DIRS:
        raise ValueError(
            f"ensure_lazy_dir('{rel}') is not a registered lazy directory. "
            f"Allowed: {', '.join(LAZY_DIRS)}. Use Path.mkdir for ad-hoc dirs."
        )
    target = root / rel
    target.mkdir(parents=True, exist_ok=True)
    return target


def ensure_mode_surface(
    root: Path,
    mode: str,
    *,
    project_name: str | None = None,
    config_overrides: dict | None = None,
    plan_only: bool = False,
) -> dict:
    """Additively create the directory + governance surface a workspace ``mode``
    requires, WITHOUT touching anything that already exists.

    Shared by init (scaffold_minimal_workspace) and post-init mode transitions
    so both produce the SAME surface from one source of truth. NEVER deletes or
    overwrites — a transition augments. Returns
    {created_dirs: [...], inner_repo: <name|"">, missing_before: [...]}.
    With plan_only=True, reports what WOULD be created without writing.
    """
    # Import here to avoid circular dependency; project_ops.py implements
    # _seed_mode_extras and _read_project_name (they depend on load_state).
    from research_os.project_ops import _seed_mode_extras, _read_project_name

    root = Path(root)
    profile = SCAFFOLD_PROFILES.get(mode)
    if profile is None:
        raise KeyError(f"unknown workspace mode: {mode!r}")
    needed = profile["eager_dirs"]
    missing = [d for d in needed if not (root / d).exists()]
    if plan_only:
        return {"created_dirs": [], "missing_before": missing, "inner_repo": "", "plan_only": True}

    created: list[str] = []
    for d in missing:
        (root / d).mkdir(parents=True, exist_ok=True)
        created.append(d)
    inner = _seed_mode_extras(
        root, project_name or _read_project_name(root), mode, config_overrides
    )
    if mode in ("tool_build", "hybrid") and inner:
        inner_dir = root / inner
        if not (inner_dir / ".git").exists():
            try:
                inner_dir.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "init"], cwd=inner_dir, capture_output=True)
            except Exception:
                pass
    return {"created_dirs": created, "missing_before": missing, "inner_repo": inner or ""}


# Software-component detection helpers.
_SOFTWARE_MARKERS = {
    "pyproject.toml": "python", "setup.py": "python", "setup.cfg": "python",
    "Cargo.toml": "rust", "package.json": "node", "go.mod": "go",
    "DESCRIPTION": "r", "pom.xml": "java", "build.gradle": "java",
}
_NON_SOFTWARE_DIRS = {
    "workspace", "inputs", ".os_state", "environment", "docs", "synthesis",
    "literature", "reports", "scripts", "spec", "decisions", "eval",
}


def detect_software_components(root: Path) -> list[dict[str, str]]:
    """Find inner software components in a (hybrid) project."""
    root = Path(root)
    found: dict[str, dict[str, str]] = {}
    try:
        children = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return []
    for child in children:
        if child.name in _NON_SOFTWARE_DIRS or child.name.startswith("."):
            continue
        kind: str | None = None
        for marker, k in _SOFTWARE_MARKERS.items():
            if (child / marker).exists():
                kind = k
                break
        if kind is None and (child / ".git").exists():
            kind = "repo"
        if kind is not None:
            found[child.name] = {
                "path": child.name,
                "name": child.name,
                "kind": kind,
            }
    return list(found.values())


def _has_user_inputs(root: Path) -> bool:
    """True iff the researcher has dropped real files into inputs/."""
    for sub in ("raw_data", "literature", "context"):
        d = root / "inputs" / sub
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            if p.name.startswith(".") or p.name == ".gitkeep":
                continue
            if p.name == "README.md" and p.parent.name in {
                "raw_data", "literature", "context"
            }:
                continue
            return True
    return False
