"""Migrate an old Research OS project to the v5 config layout.

This module provides :func:`migrate_project_to_v5`, which reads the legacy
per-project ``inputs/researcher_config.yaml`` (old surface) and writes the two
new v5 config files:

* ``<root>/.os_state/config.yaml``   — project config (via §9.1 helpers)
* ``~/.research-os/profile.yaml``    — user profile   (via §9.1 helpers)

The function is **idempotent** and **safe** — it never removes or alters the
old config.  If the old config is absent it still produces valid v5 defaults
sourced from :func:`~research_os.config.detect.detect_environment` and the
project root's directory name.

Key mapping (old → new)
-----------------------
*Project config* (``.os_state/config.yaml``):

=================================  ===================================
Old key                            New v5 key
=================================  ===================================
``project_name``                   ``project.name``
``research_goal.output_types``     ``project.output_types``
``interaction.autonomy_level``     ``autonomy.level``
``interaction.quality_gate_policy``  ``autonomy.quality_gate``
=================================  ===================================

*User profile* (``~/.research-os/profile.yaml``):

=================================  ===================================
Old key                            New v5 key
=================================  ===================================
``researcher.name``                ``user.name``
``researcher.orcid``               ``user.orcid``
``runtime.compute_environment``    ``compute.default``
``model_profile``                  ``model.preferred``
=================================  ===================================

Only keys that are **present and non-empty** in the old config are forwarded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research_os.config.project import (
    init_project_config,
    init_user_profile,
    project_config_path,
    user_profile_path,
)

__all__ = ["migrate_project_to_v5"]


def _get_old_config(root: Path) -> dict[str, Any]:
    """Load the legacy ``inputs/researcher_config.yaml``, returning {} on absence.

    Uses the canonical loader so the call path matches every other reader in
    the codebase and benefits from any future caching or error-handling there.

    Parameters
    ----------
    root:
        Project root directory.

    Returns
    -------
    dict
        Parsed YAML or empty dict if the file is absent / unreadable.
    """
    try:
        from research_os.tools.actions.state.config import get_research_config
        return get_research_config(root)
    except Exception:
        return {}


def _nonempty(value: Any) -> bool:
    """Return True when *value* is a non-empty, non-blank scalar or non-empty list."""
    if value is None:
        return False
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, str):
        return bool(value.strip())
    # numeric / bool values are always considered "present"
    return True


def migrate_project_to_v5(root: Path) -> dict[str, Any]:
    """Migrate an existing project to the v5 config layout.

    Reads the legacy ``inputs/researcher_config.yaml`` (if present), maps
    relevant keys to the new v5 surface, and writes:

    * ``<root>/.os_state/config.yaml`` via :func:`~research_os.config.project.init_project_config`
    * ``~/.research-os/profile.yaml``  via :func:`~research_os.config.project.init_user_profile`

    The operation is **idempotent** — calling it twice on the same project is
    safe and produces the same result.  The old config is never modified or
    removed.

    Parameters
    ----------
    root:
        Project root directory (must exist; does **not** have to be a fully
        initialised Research OS workspace — migration works on partial setups).

    Returns
    -------
    dict
        Summary with keys:

        ``user_profile``
            Absolute path string to the written profile file.
        ``project_config``
            Absolute path string to the written project config file.
        ``migrated_keys``
            List of dotted old-config keys that were forwarded to the new
            surface (only keys that were present *and* non-empty).
    """
    root = Path(root).resolve()

    old = _get_old_config(root)
    migrated_keys: list[str] = []

    # ------------------------------------------------------------------
    # Build project-config overrides
    # ------------------------------------------------------------------
    project_overrides: dict[str, Any] = {}

    # project_name → project.name
    project_name = old.get("project_name", "")
    if _nonempty(project_name):
        project_overrides.setdefault("project", {})["name"] = project_name
        migrated_keys.append("project_name")

    # research_goal.output_types → project.output_types
    research_goal = old.get("research_goal") or {}
    output_types = research_goal.get("output_types")
    if _nonempty(output_types):
        project_overrides.setdefault("project", {})["output_types"] = (
            list(output_types) if isinstance(output_types, (list, tuple)) else [output_types]
        )
        migrated_keys.append("research_goal.output_types")

    # interaction.autonomy_level → autonomy.level
    interaction = old.get("interaction") or {}
    autonomy_level = interaction.get("autonomy_level", "")
    if _nonempty(autonomy_level):
        project_overrides.setdefault("autonomy", {})["level"] = autonomy_level
        migrated_keys.append("interaction.autonomy_level")

    # interaction.quality_gate_policy → autonomy.quality_gate
    quality_gate = interaction.get("quality_gate_policy", "")
    if _nonempty(quality_gate):
        project_overrides.setdefault("autonomy", {})["quality_gate"] = quality_gate
        migrated_keys.append("interaction.quality_gate_policy")

    # ------------------------------------------------------------------
    # Build user-profile overrides
    # ------------------------------------------------------------------
    profile_overrides: dict[str, Any] = {}

    researcher = old.get("researcher") or {}

    # researcher.name → user.name
    r_name = researcher.get("name", "")
    if _nonempty(r_name):
        profile_overrides.setdefault("user", {})["name"] = r_name
        migrated_keys.append("researcher.name")

    # researcher.orcid → user.orcid
    r_orcid = researcher.get("orcid", "")
    if _nonempty(r_orcid):
        profile_overrides.setdefault("user", {})["orcid"] = r_orcid
        migrated_keys.append("researcher.orcid")

    # runtime.compute_environment → compute.default
    runtime = old.get("runtime") or {}
    compute_env = runtime.get("compute_environment", "")
    if _nonempty(compute_env):
        profile_overrides.setdefault("compute", {})["default"] = compute_env
        migrated_keys.append("runtime.compute_environment")

    # model_profile → model.preferred
    model_profile = old.get("model_profile", "")
    if _nonempty(model_profile):
        profile_overrides.setdefault("model", {})["preferred"] = model_profile
        migrated_keys.append("model_profile")

    # ------------------------------------------------------------------
    # Write new v5 files via §9.1 helpers
    # ------------------------------------------------------------------
    init_project_config(root, overrides=project_overrides or None)
    init_user_profile(overrides=profile_overrides or None)

    return {
        "user_profile": str(user_profile_path()),
        "project_config": str(project_config_path(root)),
        "migrated_keys": migrated_keys,
    }
