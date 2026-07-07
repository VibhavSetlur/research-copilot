"""Flat protocol + tool listers for routing UX.

Two public surfaces:

* ``list_protocols_flat`` — re-exported from
  ``research_os.tools.actions.protocol`` for module-locality;
  re-exposed here so callers can ``from research_os.tools.actions.listers
  import list_protocols_flat`` without crossing into the protocol
  loader.

* ``list_tools_flat`` — flat catalog of every registered MCP tool.
  Built at call time from ``TOOL_DEFINITIONS`` and the alias / deprecation
  registries in ``server.py``. The output drops the verbose per-tool
  description in favour of a short ``summary_first_line``; the AI can
  fetch the full description via ``sys_tool_describe`` when it actually
  needs it.

Both listers are read-only and side-effect free; safe to call from any
handler or test.
"""
from __future__ import annotations

from typing import Any

from research_os.tools.actions.protocol import (  # noqa: F401  — re-export
    list_protocols_flat,
)


# ---------------------------------------------------------------------------
# tool catalog
# ---------------------------------------------------------------------------


def _first_line(text: str, limit: int = 200) -> str:
    """Return the first line of ``text``, hard-capped at ``limit`` chars."""
    if not text:
        return ""
    first = str(text).strip().split("\n", 1)[0].strip()
    if len(first) > limit:
        first = first[: limit - 1].rstrip() + "…"
    return first


def _input_required_fields(schema: dict | None) -> list[str]:
    """Pull the ``required`` list out of a tool input schema."""
    if not isinstance(schema, dict):
        return []
    req = schema.get("required")
    if isinstance(req, list):
        return [str(x) for x in req]
    return []


# ---------------------------------------------------------------------------
# mode-scoped tool surface (context-bloat fix)
# ---------------------------------------------------------------------------
#
# The full tool catalog is ~16K tokens; surfacing all of it every turn is
# the single biggest per-turn context cost. A workspace runs in exactly one
# `workspace.mode` (analysis | tool_build | exploration), and most of the
# catalog is irrelevant to any one mode. Listing scoped to CORE + the active
# mode's tool set cuts the surface dramatically.
#
# The mapping is by tool CATEGORY (not name) so it stays correct as the
# catalog grows — a new analysis tool tagged category='research' is picked
# up automatically. CORE categories are the cross-cutting plumbing every
# mode needs (routing, files, state, config, the gradient on-ramps in
# `interaction`, …). Each mode adds its own working categories on top.

# ---------------------------------------------------------------------------
# Mode-scoped category views — derived from ModeMeta (single source of truth).
# _MODE_CATEGORIES and VALID_LISTING_MODES are now thin derived views of the
# mode_registry so they can never drift to a stale subset of modes.
# ---------------------------------------------------------------------------
from research_os.state.mode_registry import (  # noqa: E402
    MODE_REGISTRY as _MODE_REGISTRY,
    mode_listing_categories as _registry_mode_listing_categories,
    ALL_MODES as _ALL_MODES,
)

# Core categories constant re-exported for back-compat with any importer.
_CORE_CATEGORIES: frozenset[str] = frozenset({
    "routing", "system", "protocol", "file", "state", "config",
    "checkpoint", "workspace", "interaction", "environment", "memory",
})

# Mode → extra categories (beyond CORE).  Derived from ModeMeta so all 6 modes
# are covered; the old hard-coded dict only covered 3.
_MODE_CATEGORIES: dict[str, frozenset[str]] = {
    name: meta.listing_categories
    for name, meta in _MODE_REGISTRY.items()
}

# All 6 modes are now valid listing targets (was 3 before).
VALID_LISTING_MODES: tuple[str, ...] = _ALL_MODES


def _categories_for_mode(mode: str) -> frozenset[str]:
    """Return CORE ∪ the mode's extra categories. Unknown mode ⇒ analysis."""
    return _registry_mode_listing_categories(mode)


def _category_for_tool(tool_def: dict[str, Any]) -> str:
    """The tool's declared category (lowercased); '' when absent."""
    cat = (tool_def or {}).get("category")
    return cat.lower() if isinstance(cat, str) else ""


def _scope_for_tool(
    tool_name: str,
    tool_def: dict[str, Any],
    pack_names: set[str],
) -> str:
    """Classify a tool by namespace.

    * Pack tools follow the ``tool_<pack>_*`` convention (enforced by
      the loader). When the second underscore-separated segment matches
      a registered pack name, return that pack name.
    * Everything else is ``core``.
    """
    # Pack tool name convention is `tool_<pack>_*` — pluck the segment.
    if tool_name.startswith("tool_"):
        rest = tool_name[len("tool_"):]
        # Try longest pack name first (handles e.g. `theory_math`).
        for pack in sorted(pack_names, key=len, reverse=True):
            if rest.startswith(f"{pack}_"):
                return pack
    # Pack-supplied category is set to the pack name by the loader; use
    # it as a fallback when name-matching missed.
    cat = (tool_def or {}).get("category")
    if isinstance(cat, str) and cat in pack_names:
        return cat
    return "core"


def list_tools_flat(
    tool_definitions: dict[str, dict[str, Any]],
    aliases: dict[str, str] | None = None,
    deprecated_aliases: set[str] | None = None,
    *,
    scope: str = "all",
    include_deprecated: bool = False,
    match_substring: str | None = None,
    mode: str | None = None,
    pack_names: set[str] | None = None,
) -> list[dict]:
    """Flat tool catalog.

    Each entry::

        {
          "name": "tool_route",
          "scope": "core",                       # or pack name
          "summary_first_line": "Prompt → protocol + decomposition.",
          "input_schema_required_fields": ["prompt"],
          "deprecated": False,
          "alias_of": None,
        }

    Args:
      tool_definitions:    The live ``TOOL_DEFINITIONS`` map from
                           ``server.py``.
      aliases:             ``_ALIASES`` map. Optional; aliases NOT in
                           ``deprecated_aliases`` are surfaced as
                           secondary entries with ``alias_of`` set, so
                           the catalog is complete from a caller's view.
      deprecated_aliases:  ``_DEPRECATED_ALIASES`` set.
      scope:    ``"all"`` | ``"core"`` | a pack name. Default ``"all"``.
      include_deprecated:  When ``True``, include alias entries flagged
                           as deprecated. Default ``False`` — most
                           callers want the canonical surface.
      match_substring:     When set, restrict to tools whose
                           ``name`` OR ``summary_first_line`` contains
                           the lowercased substring.
      mode:     Optional workspace mode (``analysis`` | ``tool_build`` |
                ``exploration``). When set, restrict the surface to CORE
                categories + that mode's working categories — the
                context-bloat fix. A tool whose ``scope`` matches an
                explicitly-requested ``scope`` (a pack name) is kept even
                if its category is outside the mode, so a declared-domain
                pack stays visible. ``None`` (default) ⇒ no mode filter,
                so back-compat behaviour is unchanged.
      pack_names:          Optional set of pack names. When omitted,
                           the function looks up live pack registrations.
    """
    aliases = aliases or {}
    deprecated_aliases = deprecated_aliases or set()

    if pack_names is None:
        try:
            from research_os.plugins.loader import pack_protocol_dirs
            pack_names = set(pack_protocol_dirs().keys())
        except Exception:
            pack_names = set()

    needle = match_substring.lower().strip() if isinstance(match_substring, str) and match_substring.strip() else None

    # Mode filter (None ⇒ off, full back-compat). When a mode is set, build
    # the allowed-category set once; a tool passes if its category is in it,
    # OR it belongs to an explicitly-requested pack scope (declared domain).
    mode_norm = mode.strip().lower() if isinstance(mode, str) and mode.strip() else None
    allowed_categories = _categories_for_mode(mode_norm) if mode_norm else None
    requested_pack_scope = scope if (scope and scope not in ("all", "core")) else None

    def _passes_mode(defn: dict[str, Any], tool_scope: str) -> bool:
        if allowed_categories is None:
            return True
        if _category_for_tool(defn) in allowed_categories:
            return True
        # Keep declared-domain pack tools when the caller asked for that pack.
        return bool(requested_pack_scope) and tool_scope == requested_pack_scope

    out: list[dict] = []

    # 1) Canonical tools. A few legacy names persist in TOOL_DEFINITIONS
    # AND in _DEPRECATED_ALIASES — flag those as deprecated so callers
    # can hide them with include_deprecated=False.
    emitted: set[str] = set()
    for name, defn in sorted(tool_definitions.items()):
        defn = defn or {}
        is_deprecated_self = name in deprecated_aliases
        alias_target = aliases.get(name) if is_deprecated_self else None
        if is_deprecated_self and not include_deprecated:
            continue
        tool_scope = _scope_for_tool(name, defn, pack_names)
        if scope != "all" and tool_scope != scope:
            continue
        if not _passes_mode(defn, tool_scope):
            continue
        summary = _first_line(defn.get("short") or defn.get("description") or "")
        if needle and needle not in name.lower() and needle not in summary.lower():
            continue
        out.append({
            "name": name,
            "scope": tool_scope,
            "summary_first_line": summary,
            "input_schema_required_fields": _input_required_fields(
                defn.get("inputSchema")
            ),
            "deprecated": is_deprecated_self,
            "alias_of": alias_target if alias_target and alias_target != name else None,
        })
        emitted.add(name)

    # 2) Aliases that AREN'T already in TOOL_DEFINITIONS (nickname-only
    # entries, e.g. ``view_workspace_tree`` → ``sys_workspace_tree``).
    # Skip aliases that point at a missing target — they'd be dead
    # lookups for the AI.
    for alias_name, target in sorted(aliases.items()):
        if alias_name == target:
            continue
        if alias_name in emitted:
            # Already covered by the canonical pass above.
            continue
        is_deprecated = alias_name in deprecated_aliases
        if is_deprecated and not include_deprecated:
            continue
        target_def = tool_definitions.get(target) or {}
        if not target_def:
            continue
        tool_scope = _scope_for_tool(target, target_def, pack_names)
        if scope != "all" and tool_scope != scope:
            continue
        if not _passes_mode(target_def, tool_scope):
            continue
        summary = _first_line(target_def.get("short") or target_def.get("description") or "")
        if needle and needle not in alias_name.lower() and needle not in summary.lower():
            continue
        out.append({
            "name": alias_name,
            "scope": tool_scope,
            "summary_first_line": summary,
            "input_schema_required_fields": _input_required_fields(
                target_def.get("inputSchema")
            ),
            "deprecated": is_deprecated,
            "alias_of": target,
        })

    out.sort(key=lambda e: (e["scope"], e["name"]))
    return out
