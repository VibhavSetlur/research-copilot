"""Progressive-disclosure tool surface for the MCP handshake.

The full Research-OS catalog is 45 tools. Advertising every one of them
in the MCP ``list_tools()`` handshake floods the client's context on the
FIRST turn — every tool's name + short description + input schema is sent
to the model before it has done anything. That is the single biggest
per-session context cost and, on small-context clients, it can crowd out
the actual work.

The fix is progressive disclosure. ``list_tools()`` advertises only a small
CORE bootstrap surface (the boot ritual + the discovery tools + file/state
plumbing). The AI uses those to ROUTE (``tool_route``), scope its working
set (``sys_active_tools``), or search the catalog — and then CALLS the
tool it needs by name. This is safe because the server's ``call_tool``
dispatcher resolves against ``_HANDLERS`` (the full registry), NOT against
the advertised ``list_tools()`` set: a tool absent from the handshake list
is still fully invocable by name. Hiding a tool from the list does not
remove it; it only defers its description until the AI actually needs it.

Surface is chosen by the ``RESEARCH_OS_TOOL_SURFACE`` env var:

* ``core`` (DEFAULT) — the ~25-tool bootstrap surface. Lean handshake;
  everything else is reachable on-demand via the discovery tools.
* ``full`` — every registered tool (the historical behaviour). Opt in
  when a client genuinely wants the whole catalog up front and has the
  context budget for it.
* ``mode`` — CORE categories + the active workspace mode's working
  categories (analysis | tool_build | exploration), resolved from the
  project config. A middle ground: broader than ``core``, narrower than
  ``full``.

Degrade-open: an unknown / empty value falls back to ``core``; any error
resolving the mode-scoped surface falls back to the full surface so the AI
is never left unable to reach a tool.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Exec-category names (used by persona read_only filtering) ────────────────
# These must match the "category" field values used in TOOL_DEFINITIONS.
_EXEC_CATEGORIES: frozenset[str] = frozenset({"execution", "exec"})


# ── CORE bootstrap surface (15 CORE tools) ───────────────────────────
# The minimum set the AI needs to (a) orient, (b) route, (c) DISCOVER and
# then CALL anything else by name. Keep this tight — every entry here is a
# fixed per-session context cost. Anything not listed is still callable;
# it's just not advertised at handshake.
_CORE_SURFACE: frozenset[str] = frozenset({
    # Orientation / boot ritual
    "sys_boot",
    # Routing + discovery — how the AI reaches the other 30 tools
    "tool_route",
    "sys_active_tools",
    # Protocol plumbing
    "sys_protocol_get",
    # State
    "sys_state_get",
    # File basics
    "sys_file_read",
    "sys_file_write",
    "sys_file_list",
    # Core execution + reasoning
    "tool_search",
    "tool_python_exec",
    "tool_bash_exec",
    "tool_plan",
    "tool_audit",
    # Memory + thought
    "mem_log",
    "tool_thought",
})

_VALID_SURFACES = ("core", "full", "mode")
_DEFAULT_SURFACE = "core"

_ENV_VAR = "RESEARCH_OS_TOOL_SURFACE"


def resolve_surface_mode() -> str:
    """Return the configured surface mode (core | full | mode).

    Reads ``RESEARCH_OS_TOOL_SURFACE``; unknown / empty ⇒ the default
    (``core``). Case-insensitive.
    """
    raw = (os.environ.get(_ENV_VAR) or "").strip().lower()
    if raw in _VALID_SURFACES:
        return raw
    return _DEFAULT_SURFACE


def _resolve_workspace_mode(root: Path) -> str | None:
    """Best-effort read of the project's workspace mode for ``mode`` surface.

    Returns the mode string (analysis | tool_build | exploration | …) or
    None when it can't be determined. Never raises.
    """
    try:
        from research_os.tools.actions.state.config import get_workspace_mode

        mode = get_workspace_mode(root)
        if isinstance(mode, str) and mode.strip():
            return mode.strip().lower()
    except Exception:
        pass
    return None


def _apply_persona_visibility(
    names: list[str],
    tool_definitions: dict[str, dict],
    root: Path,
) -> list[str]:
    """Filter ``names`` by the active persona's ``tool_visibility``.

    "all" → no change; "read_only" → remove exec-category tools.
    Fail-open: returns ``names`` unchanged on any error.
    """
    try:
        from research_os.server.personas import get_active_persona, get_persona

        active = get_active_persona(root)
        persona = get_persona(active)
        if persona.get("tool_visibility") == "read_only":
            return [
                n for n in names
                if tool_definitions.get(n, {}).get("category") not in _EXEC_CATEGORIES
            ]
    except Exception:
        pass  # degrade open — never hide tools due to a persona read error
    return names


def select_visible_tools(
    tool_definitions: dict[str, dict],
    root: Path,
) -> list[str]:
    """Return the tool names to advertise in ``list_tools()`` for ``root``.

    The order of ``tool_definitions`` is preserved for the returned names so
    the handshake list stays stable. Degrades open: any failure resolving a
    narrowed surface falls back to the full catalog rather than hiding a
    tool the AI might need.

    Persona tool_visibility is applied AFTER surface filtering so the two
    policies compose: "read_only" removes exec-category tools from whichever
    surface was chosen; "all" leaves the surface unchanged.
    """
    surface = resolve_surface_mode()

    if surface == "full":
        names = list(tool_definitions.keys())
        return _apply_persona_visibility(names, tool_definitions, root)

    if surface == "mode":
        try:
            from research_os.tools.actions.listers import list_tools_flat

            from .aliases import _ALIASES, _DEPRECATED_ALIASES

            mode = _resolve_workspace_mode(root)
            scoped = list_tools_flat(
                tool_definitions,
                _ALIASES,
                _DEPRECATED_ALIASES,
                mode=mode,
            )
            allowed = {e["name"] for e in scoped}
            # Always keep the CORE bootstrap tools so the AI can route +
            # discover even if a mode's category set happens to omit one.
            allowed |= _CORE_SURFACE
            names = [n for n in tool_definitions if n in allowed]
            if names:
                return _apply_persona_visibility(names, tool_definitions, root)
        except Exception:
            pass
        # Degrade open.
        names = list(tool_definitions.keys())
        return _apply_persona_visibility(names, tool_definitions, root)

    # surface == "core" (default).
    names = [n for n in tool_definitions if n in _CORE_SURFACE]
    # Guard: if the catalog somehow lacks every core tool (mis-load),
    # degrade open rather than advertising an empty surface.
    names = names or list(tool_definitions.keys())
    return _apply_persona_visibility(names, tool_definitions, root)
