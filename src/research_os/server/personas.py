"""Persona records for Research-OS §13.1 — client-read context, NOT LLM injection.

A persona is a mode the researcher selects that changes:
  (a) which tools RO advertises (tool_visibility)
  (b) which execution policy RO enforces at the tool-dispatch boundary

The ``directive`` text is returned to the *client's* AI as ordinary MCP
context — it is NEVER sent to any model by Research-OS, because Research-OS
calls no model.

Active persona persists to ``.os_state/config.yaml`` under the key
``persona.active``, following the same pattern as ``workspace.mode`` in
``tools/actions/state/config.py``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("research_os.server.personas")

# ── The four persona records ──────────────────────────────────────────────────

PERSONAS: dict[str, dict[str, str]] = {
    "scruffy": {
        "directive": (
            "exploratory: creative, unconventional, tolerate ambiguity"
        ),
        "tool_visibility": "all",
        "execution_policy": "direct",
    },
    "neat": {
        "directive": (
            "formal: every claim needs evidence, every step verified"
        ),
        "tool_visibility": "all",
        "execution_policy": "verified",
    },
    "critique": {
        "directive": (
            "peer reviewer: find flaws, don't generate/run"
        ),
        "tool_visibility": "read_only",
        "execution_policy": "forbidden",
    },
    "delegation": {
        "directive": (
            "manager: decompose goal, emit runnable sub-prompts"
        ),
        "tool_visibility": "all",
        "execution_policy": "supervised",
    },
}

VALID_PERSONA_NAMES: tuple[str, ...] = tuple(PERSONAS.keys())
DEFAULT_PERSONA: str = "scruffy"

# ── Lookup helpers ────────────────────────────────────────────────────────────


def get_persona(name: str) -> dict[str, str]:
    """Return the persona record for ``name``.

    Raises ``KeyError`` when ``name`` is not a valid persona.
    """
    return PERSONAS[name]


# ── Persistence helpers (follow workspace_mode pattern exactly) ───────────────
# Active persona lives at <root>/.os_state/config.yaml under persona.active.
# .os_state/ is the cross-process on-disk contract; no daemon import.

_OS_STATE = ".os_state"
_CONFIG_FILE = "config.yaml"


def _os_state_config_path(root: Path) -> Path:
    return root / _OS_STATE / _CONFIG_FILE


def get_active_persona(root: Path | str) -> str:
    """Return the active persona name, defaulting to ``scruffy``.

    Reads ``.os_state/config.yaml``; returns ``DEFAULT_PERSONA`` on any
    failure (degrade-open: no persona configured == scruffy == direct ==
    existing behaviour unchanged).
    """
    root = Path(root)
    try:
        cfg_path = _os_state_config_path(root)
        if not cfg_path.exists():
            return DEFAULT_PERSONA
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        persona_block = raw.get("persona") or {}
        active = persona_block.get("active") if isinstance(persona_block, dict) else None
        if active in VALID_PERSONA_NAMES:
            return active
        return DEFAULT_PERSONA
    except Exception:
        return DEFAULT_PERSONA


def set_active_persona(root: Path | str, name: str) -> dict[str, Any]:
    """Persist ``name`` as the active persona to ``.os_state/config.yaml``.

    Returns a result dict ``{"status": "success"|"error", ...}``.
    """
    root = Path(root)
    if name not in VALID_PERSONA_NAMES:
        return {
            "status": "error",
            "message": (
                f"unknown persona {name!r}; valid: {list(VALID_PERSONA_NAMES)}"
            ),
        }
    try:
        cfg_path = _os_state_config_path(root)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        # Round-trip: load existing, update persona.active, write back.
        if cfg_path.exists():
            try:
                existing: dict = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            except Exception:
                existing = {}
        else:
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        persona_block = existing.get("persona")
        if not isinstance(persona_block, dict):
            persona_block = {}
        persona_block["active"] = name
        existing["persona"] = persona_block
        cfg_path.write_text(
            yaml.safe_dump(existing, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        return {
            "status": "success",
            "persona": name,
            "directive": PERSONAS[name]["directive"],
            "tool_visibility": PERSONAS[name]["tool_visibility"],
            "execution_policy": PERSONAS[name]["execution_policy"],
        }
    except Exception as exc:
        logger.exception("set_active_persona failed")
        return {"status": "error", "message": str(exc)}
