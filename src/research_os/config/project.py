"""New v5 config surface — user profile and project config.

This module introduces two **additive** config files that co-exist with the
existing per-project ``inputs/researcher_config.yaml`` and legacy
``~/.config/research-os/profile.yaml`` surfaces.  Those legacy loaders are
**not** touched here; migration is handled in later sub-tasks (§9.4/§9.5).

Public API
----------
User profile (``~/.research-os/profile.yaml`` by default)::

    user_profile_path() -> Path
    load_user_profile() -> dict
    init_user_profile(overrides=None) -> dict
    save_user_profile(profile) -> None

Project config (``<root>/.os_state/config.yaml``)::

    project_config_path(root) -> Path
    load_project_config(root) -> dict
    init_project_config(root, overrides=None) -> dict
    save_project_config(root, config) -> None
"""

from __future__ import annotations

import copy
import os
import stat
from pathlib import Path
from typing import Any

import yaml

from research_os.config.detect import detect_environment

__all__ = [
    "user_profile_path",
    "load_user_profile",
    "init_user_profile",
    "save_user_profile",
    "project_config_path",
    "load_project_config",
    "init_project_config",
    "save_project_config",
]

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_USER_PROFILE: dict[str, Any] = {
    "user": {"name": "", "orcid": ""},
    "compute": {"default": "local", "hpc_partition": ""},
    "model": {"preferred": ""},
}

_DEFAULT_PROJECT_CONFIG: dict[str, Any] = {
    "project": {"name": "", "output_types": ["paper", "figures"]},
    "autonomy": {"level": "semi", "quality_gate": "normal"},
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*, returning a new dict.

    Nested dicts are merged; all other values are replaced by the override.
    Neither *base* nor *override* is mutated.
    """
    result: dict = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _research_os_home() -> Path:
    """Return the Research-OS home directory.

    Respects the ``$RESEARCH_OS_HOME`` environment variable when set;
    falls back to ``~/.research-os``.
    """
    env_home = os.environ.get("RESEARCH_OS_HOME", "")
    if env_home:
        return Path(env_home)
    return Path.home() / ".research-os"


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------


def user_profile_path() -> Path:
    """Return the path to the user profile YAML.

    The location is ``~/.research-os/profile.yaml`` unless the
    ``$RESEARCH_OS_HOME`` environment variable is set, in which case it is
    ``$RESEARCH_OS_HOME/profile.yaml``.
    """
    return _research_os_home() / "profile.yaml"


def load_user_profile() -> dict:
    """Load and return the user profile as a plain dict.

    Returns the parsed YAML when the file exists.  When the file is missing
    (first run), returns a deep copy of the empty-but-valid default structure
    without writing anything to disk.
    """
    path = user_profile_path()
    if not path.exists():
        return copy.deepcopy(_DEFAULT_USER_PROFILE)
    raw = yaml.safe_load(path.read_text()) or {}
    return _deep_merge(copy.deepcopy(_DEFAULT_USER_PROFILE), raw)


def init_user_profile(overrides: dict | None = None) -> dict:
    """Create (or overwrite) the user profile, auto-filling from the environment.

    Detection strategy
    ------------------
    * ``user.name``      — ``user_name`` from :func:`detect_environment`.
    * ``compute.default`` — ``compute`` from :func:`detect_environment`.
    * ``model.preferred`` — ``inferred_client`` from :func:`detect_environment`
      (the IDE marker filename, e.g. ``"CLAUDE.md"``).

    Parameters
    ----------
    overrides:
        Optional dict deep-merged *on top of* the detected values.  Nested
        keys override their counterpart in the detected profile.

    Returns
    -------
    dict
        The profile that was written to disk.
    """
    env = detect_environment()

    detected: dict[str, Any] = copy.deepcopy(_DEFAULT_USER_PROFILE)
    if env.get("user_name"):
        detected["user"]["name"] = env["user_name"]
    if env.get("compute"):
        detected["compute"]["default"] = env["compute"]
    if env.get("inferred_client"):
        detected["model"]["preferred"] = env["inferred_client"]

    profile = _deep_merge(detected, overrides or {})

    path = user_profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(profile, default_flow_style=False, sort_keys=False))
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # chmod 600

    return profile


def save_user_profile(profile: dict) -> None:
    """Write *profile* to :func:`user_profile_path`, creating parent dirs.

    Parameters
    ----------
    profile:
        Plain dict to serialise.  The file is written as YAML and permissions
        are set to 600 (owner read/write only).
    """
    path = user_profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(profile, default_flow_style=False, sort_keys=False))
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # chmod 600


# ---------------------------------------------------------------------------
# Project config
# ---------------------------------------------------------------------------


def project_config_path(root: Path) -> Path:
    """Return the path to the project config YAML.

    Parameters
    ----------
    root:
        Project root directory.

    Returns
    -------
    Path
        ``<root>/.os_state/config.yaml``
    """
    return Path(root) / ".os_state" / "config.yaml"


def load_project_config(root: Path) -> dict:
    """Load and return the project config as a plain dict.

    Returns the parsed YAML when the file exists.  When the file is missing,
    returns a deep copy of the empty-but-valid default structure without
    writing anything to disk.

    Parameters
    ----------
    root:
        Project root directory.
    """
    path = project_config_path(root)
    if not path.exists():
        return copy.deepcopy(_DEFAULT_PROJECT_CONFIG)
    raw = yaml.safe_load(path.read_text()) or {}
    return _deep_merge(copy.deepcopy(_DEFAULT_PROJECT_CONFIG), raw)


def init_project_config(root: Path, overrides: dict | None = None) -> dict:
    """Create (or overwrite) the project config, auto-filling from *root*.

    Auto-fills ``project.name`` from ``root.name`` (the directory basename).
    ``overrides`` are deep-merged on top.

    Parameters
    ----------
    root:
        Project root directory.
    overrides:
        Optional dict deep-merged on top of the auto-detected values.

    Returns
    -------
    dict
        The config that was written to disk.
    """
    config: dict[str, Any] = copy.deepcopy(_DEFAULT_PROJECT_CONFIG)
    config["project"]["name"] = Path(root).name

    config = _deep_merge(config, overrides or {})

    path = project_config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, default_flow_style=False, sort_keys=False))

    return config


def save_project_config(root: Path, config: dict) -> None:
    """Write *config* to :func:`project_config_path`, creating parent dirs.

    Parameters
    ----------
    root:
        Project root directory.
    config:
        Plain dict to serialise.
    """
    path = project_config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, default_flow_style=False, sort_keys=False))
