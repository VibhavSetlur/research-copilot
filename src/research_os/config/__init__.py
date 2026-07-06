"""research_os.config — environment detection and configuration helpers.

This sub-package provides:

* :func:`detect_environment` — probe the runtime environment (compute
  backend, Python version, IDE client, git identity, package manager).
* :data:`settings` — Pydantic ``BaseSettings`` instance carrying
  env-derived API keys and runtime knobs (previously ``research_os.config``).
* v5 config surface — user profile (``~/.research-os/profile.yaml``) and
  project config (``<root>/.os_state/config.yaml``).
"""

from __future__ import annotations

from research_os.config.detect import detect_environment
from research_os.config.project import (
    init_project_config,
    init_user_profile,
    load_project_config,
    load_user_profile,
    project_config_path,
    save_project_config,
    save_user_profile,
    user_profile_path,
)
from research_os.config.settings import Settings, settings

__all__ = [
    # existing
    "detect_environment",
    "settings",
    "Settings",
    # v5 user profile
    "user_profile_path",
    "load_user_profile",
    "init_user_profile",
    "save_user_profile",
    # v5 project config
    "project_config_path",
    "load_project_config",
    "init_project_config",
    "save_project_config",
]
