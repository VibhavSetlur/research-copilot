"""Step-directory discovery helpers.

Finds numbered step folders, including those nested inside PATH
container folders (``<slug>_PATH_<k>/``).  Kept separate so the
discovery logic is a single, importable unit — ``project_ops`` is the
public facade that re-exports everything here.
"""
from __future__ import annotations

import re
from pathlib import Path


_STEP_DIR_RE = re.compile(r"^\d{2,3}_")
#: A PATH container folder: ``<descriptive_slug>_PATH_<k>``.
_PATH_CONTAINER_RE = re.compile(r"^.+_PATH_\d+$")


def is_path_container(name: str) -> bool:
    """True if *name* is a ``<slug>_PATH_<k>`` container folder name."""
    return bool(_PATH_CONTAINER_RE.match(name))


def _step_sort_key(d: Path) -> tuple[int, str]:
    try:
        return (int(d.name.split("_", 1)[0]), d.name)
    except ValueError:
        return (0, d.name)


def discover_step_dirs(workspace: Path, *, include_dead: bool = True) -> list[Path]:
    """Every numbered step directory, sorted by step number.

    Finds steps both directly under ``workspace/`` AND one level deep inside
    ``<slug>_PATH_<k>/`` container folders. ``include_dead=False`` skips
    ``__DEAD_END`` steps.
    """
    steps: list[Path] = []
    if not workspace.exists():
        return steps
    for p in workspace.iterdir():
        if not p.is_dir():
            continue
        if _STEP_DIR_RE.match(p.name):
            if include_dead or not p.name.endswith("__DEAD_END"):
                steps.append(p)
        elif is_path_container(p.name):
            for c in sorted(p.iterdir()):
                if c.is_dir() and _STEP_DIR_RE.match(c.name):
                    if include_dead or not c.name.endswith("__DEAD_END"):
                        steps.append(c)
    return sorted(steps, key=_step_sort_key)


def resolve_step_dir(workspace: Path, step_id: str) -> Path | None:
    """Locate a step folder by id, whether flat or inside a PATH container.

    Tolerates the ``__DEAD_END`` variant. Returns ``None`` if not found.
    """
    direct = workspace / step_id
    if direct.is_dir():
        return direct
    dead = workspace / f"{step_id}__DEAD_END"
    if dead.is_dir():
        return dead
    for p in workspace.iterdir():
        if p.is_dir() and is_path_container(p.name):
            cand = p / step_id
            if cand.is_dir():
                return cand
            cand_dead = p / f"{step_id}__DEAD_END"
            if cand_dead.is_dir():
                return cand_dead
    return None


def _present(p: Path) -> bool:
    """True if a path exists OR is a (possibly broken) symlink."""
    return p.is_symlink() or p.exists()


def step_input_link(exp_dir: Path) -> Path:
    """The step's upstream-input link (3.2 ``data/past_step_input``, else
    the legacy ``data/input``). Returns the 3.2 path when neither exists."""
    new = exp_dir / "data" / "past_step_input"
    legacy = exp_dir / "data" / "input"
    if _present(new) or not _present(legacy):
        return new
    return legacy


def step_output_dir(exp_dir: Path) -> Path:
    """The step's output dir (3.2 ``data/next_step_output``, else the legacy
    ``data/output``). Returns the 3.2 path when neither exists."""
    new = exp_dir / "data" / "next_step_output"
    legacy = exp_dir / "data" / "output"
    if _present(new) or not _present(legacy):
        return new
    return legacy
