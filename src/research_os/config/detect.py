"""Environment auto-detection for Research-OS.

Probes the host environment and returns a plain dict describing the
compute backend, Python version, inferred IDE client, git identity, and
package-manager preference.  All probing is read-only and side-effect-free:
nothing is written, no state is mutated, and a missing tool never raises.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# Ordered list of marker filenames / directory names that indicate which
# AI client is active in the project root.  The first match wins.
_CLIENT_MARKERS: list[str] = [
    "CLAUDE.md",
    ".cursorrules",
    ".cursor",
    "AGENTS.md",
    "GEMINI.md",
]


def detect_environment(root: Path | None = None) -> dict:
    """Probe the host environment and return a description dict.

    Parameters
    ----------
    root:
        Directory to search for IDE client marker files.  Defaults to
        ``Path.cwd()`` when *None* is passed.

    Returns
    -------
    dict
        A plain dictionary.  The following keys are *always* present:

        ``compute``
            ``"hpc"`` when ``sbatch`` is on PATH, ``"docker"`` when
            ``docker`` is on PATH, otherwise ``"local"``.
        ``python``
            The running interpreter version as ``"MAJOR.MINOR"``
            (e.g. ``"3.11"``).
        ``package_manager``
            ``"conda"`` when the ``conda`` executable is on PATH,
            otherwise ``"pip"``.

        The following keys are included *only* when detection succeeds:

        ``inferred_client``
            Filename of the first IDE marker found under *root*.
        ``user_name``
            Value of ``git config user.name``.
        ``user_email``
            Value of ``git config user.email``.
    """
    env: dict = {}

    # --- compute backend ---------------------------------------------------
    if shutil.which("sbatch"):
        env["compute"] = "hpc"
    elif shutil.which("docker"):
        env["compute"] = "docker"
    else:
        env["compute"] = "local"

    # --- Python version ----------------------------------------------------
    env["python"] = f"{sys.version_info.major}.{sys.version_info.minor}"

    # --- inferred IDE client -----------------------------------------------
    search_root = Path.cwd() if root is None else Path(root)
    for marker in _CLIENT_MARKERS:
        if (search_root / marker).exists():
            env["inferred_client"] = marker
            break

    # --- git identity ------------------------------------------------------
    for git_key, env_key in (
        ("user.name", "user_name"),
        ("user.email", "user_email"),
    ):
        try:
            value = subprocess.check_output(
                ["git", "config", git_key],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            if value:
                env[env_key] = value
        except (subprocess.SubprocessError, OSError, FileNotFoundError):
            pass

    # --- package manager ---------------------------------------------------
    env["package_manager"] = "conda" if shutil.which("conda") else "pip"

    return env
