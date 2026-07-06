"""Provenance capture — the reproducibility record for every run.

JUDGE-2 (docs/ROADMAP.md §8): a result you can't reproduce is worthless.
This module captures the context needed to re-run a computation later: the
project's git commit (and whether the tree was dirty), the active
environment (conda env, python version, selected package versions), input
file hashes, and precise timestamps.

Everything here is BEST-EFFORT and must NEVER raise into a run: a missing
git binary, a non-repo directory, or an unreadable file just omits that
field. Provenance that crashes a job is worse than provenance that's
incomplete.

stdlib only (subprocess, hashlib, os, sys, platform).
"""
from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def _run_git(args: list[str], cwd: str | Path) -> str | None:
    """Run a git command, returning stripped stdout or None on any failure."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def git_provenance(root: str | Path) -> dict:
    """Capture the project's git state. Empty dict if not a repo / no git."""
    root = Path(root)
    if not root.exists():
        return {}
    commit = _run_git(["rev-parse", "HEAD"], root)
    if commit is None:
        return {}  # not a repo or git unavailable
    prov: dict = {"commit": commit}
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    if branch:
        prov["branch"] = branch
    # Dirty if `git status --porcelain` has any output.
    status = _run_git(["status", "--porcelain"], root)
    prov["dirty"] = bool(status)
    if status:
        # Count changed files but don't dump the whole list.
        prov["dirty_files"] = len(status.splitlines())
    return prov


def env_provenance(packages: list[str] | None = None,
                   snapshot_env: bool = False) -> dict:
    """Capture the runtime environment: python, platform, conda env, pkgs.

    When ``snapshot_env`` is True, also records the COMPLETE installed-package
    set (name→version, via importlib.metadata — no network, no pip subprocess)
    so a reviewer can recreate the exact environment, not just read its name.
    This is the difference between "ran in conda env 'research-os'" and a
    reproducible manifest.
    """
    prov: dict = {
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
    }
    conda = os.environ.get("CONDA_DEFAULT_ENV")
    if conda:
        prov["conda_env"] = conda
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        prov["virtualenv"] = venv
    # Selected package versions — only those asked for, resolved via
    # importlib.metadata (no network, no pip subprocess).
    if packages:
        versions: dict = {}
        try:
            from importlib.metadata import PackageNotFoundError, version

            for pkg in packages:
                try:
                    versions[pkg] = version(pkg)
                except PackageNotFoundError:
                    versions[pkg] = None
        except Exception:  # noqa: BLE001 - metadata import must not break capture
            pass
        if versions:
            prov["packages"] = versions
    # Full environment snapshot for reproducibility (opt-in; the complete
    # installed set, not just tracked packages).
    if snapshot_env:
        try:
            from importlib.metadata import distributions

            full: dict = {}
            for dist in distributions():
                try:
                    nm = dist.metadata["Name"]
                    if nm:
                        full[nm] = dist.version
                except Exception:  # noqa: BLE001
                    continue
            if full:
                prov["env_snapshot"] = dict(sorted(full.items()))
                prov["env_snapshot_count"] = len(full)
        except Exception:  # noqa: BLE001 - snapshot must never break capture
            pass
    return prov


def hash_file(path: str | Path, *, algo: str = "sha256", chunk: int = 1 << 20) -> str | None:
    """Hash a file's contents. None if unreadable. Streams in chunks."""
    path = Path(path)
    try:
        h = hashlib.new(algo)
        with path.open("rb") as fh:
            while True:
                block = fh.read(chunk)
                if not block:
                    break
                h.update(block)
        return f"{algo}:{h.hexdigest()}"
    except (OSError, ValueError):
        return None


def hash_inputs(paths: Sequence[str | Path] | None) -> dict:
    """Hash a set of input files → {path: 'sha256:...'}. Skips unreadable."""
    if not paths:
        return {}
    out: dict = {}
    for p in paths:
        digest = hash_file(p)
        if digest is not None:
            out[str(p)] = digest
    return out


def hash_fn_for_root(root: str | Path | None):
    """Return a ``hash_file(path) -> 'sha256:...' | None`` closure that
    resolves relative paths against ``root`` before hashing current
    on-disk state.

    This is the single source of truth for how a recorded input path
    (which may be relative to the project root) gets re-hashed during a
    freshness check. Both the CLI (`daemon stale`) and the HTTP surface
    (`/v1/staleness`) use it so their verdicts can never drift apart.
    Never raises — unreadable / missing files return None.
    """
    import os

    base = str(root) if root else "."

    def _hash(path: str) -> str | None:
        try:
            p = path if os.path.isabs(path) else os.path.join(base, path)
            return hash_file(p)
        except Exception:  # noqa: BLE001 - a freshness probe must never raise
            return None

    return _hash


def capture_environment() -> dict:
    """Capture a restorable environment snapshot (schema_version 1.0).

    Best-effort; never raises.  ``pip freeze`` and ``conda env export`` are
    invoked via subprocess (timeout 30 s each) and omitted silently on any
    error (missing binary, timeout, non-zero exit, permission denied).

    Returns a dict with at least::

        {
            "schema_version": "1.0",
            "platform": "<sys.platform>-<machine>",
            "python_version": "<full sys.version>",
            # optional, present only when captured successfully:
            "pip_freeze": ["pkg==ver", ...],
            "conda_export": ["- pkg=ver=build", ...],   # lines from stdout
        }

    This is CAPTURE-ONLY (observational). No restore logic is provided here.
    The existing env_provenance / capture functions are unchanged.
    """
    snap: dict = {
        "schema_version": "1.0",
        "platform": f"{sys.platform}-{platform.machine()}",
        "python_version": sys.version,
    }

    # ── pip freeze ──────────────────────────────────────────────────────────
    try:
        out = subprocess.check_output(
            [sys.executable, "-m", "pip", "freeze"],
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL,
        )
        snap["pip_freeze"] = out.splitlines()
    except Exception:  # noqa: BLE001 - omit on any failure (binary, timeout, etc.)
        pass

    # ── conda env export --no-builds ────────────────────────────────────────
    try:
        out = subprocess.check_output(
            ["conda", "env", "export", "--no-builds"],
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL,
        )
        snap["conda_export"] = out.splitlines()
    except Exception:  # noqa: BLE001 - omit on any failure
        pass

    return snap


def capture(
    root: str | Path,
    *,
    inputs: Sequence[str | Path] | None = None,
    packages: list[str] | None = None,
    snapshot_env: bool = False,
) -> dict:
    """Capture a full provenance record for a run. Never raises.

    Args:
        root: project root (for git state).
        inputs: input files whose content hashes pin the run's inputs.
        packages: package names whose versions matter for reproducibility.
        snapshot_env: also record the complete installed-package set so the
            exact environment is reproducible (recommended for long/HPC runs).
    """
    prov: dict = {}
    try:
        git = git_provenance(root)
        if git:
            prov["git"] = git
    except Exception:  # noqa: BLE001 - best effort
        pass
    try:
        prov["env"] = env_provenance(packages, snapshot_env=snapshot_env)
    except Exception:  # noqa: BLE001
        pass
    try:
        inp = hash_inputs(inputs)
        if inp:
            prov["inputs"] = inp
    except Exception:  # noqa: BLE001
        pass
    return prov
