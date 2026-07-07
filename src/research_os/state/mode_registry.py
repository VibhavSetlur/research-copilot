"""Single source of truth for all workspace-mode metadata (ModeMeta).

Every mode-aware system (config validator, router, listers, mode-health
checker, project-ops scaffold) derives its view from the registry here
instead of maintaining its own parallel list.  Downstream readers expose
the same public names they always have — they are now thin derived views.

Schema
------
ModeMeta fields (all are required unless noted):

    name          str   Canonical mode identifier (matches VALID_WORKSPACE_MODES).
    summary       str   One-line human description for docs / sys_boot.
    biased        bool  True → router applies a mode-specific score boost.
                        False → analysis is the neutral baseline; no boost entry.
    boost         int   Score boost applied to native sub-intents (0 when not biased).
    sub_intents   frozenset[str]  Protocol sub-intents native to this mode.
    shape         str | None  Workflow-shape tag used for the shape tiebreak.
    override      bool  True → strong trigger fires override semantic guess (tool_build only).
    listing_categories  frozenset[str]  Extra tool categories surfaced in sys_active_tools.
    layout_work   tuple[str, ...]  Mode-specific work-surface dirs (see project_ops.LAYOUT_SPEC).
    layout_synthesis bool   Whether synthesis/ is part of the mode's layout.
    layout_lazy   tuple[str, ...]  Dirs created lazily (on first artefact).
    health_checker  Callable[[Path], list[dict]] | None  Mode-specific health-check fn.

Transition policy (default-allow)
----------------------------------
All transitions are ALLOWED unless they appear in FORBIDDEN_TRANSITIONS.
mode_transition_spec() returns either an explicitly-declared spec dict
(with kind/protocol/guidance), a generic "augment" default spec, or None
for same-mode no-ops.  Only pairs in FORBIDDEN_TRANSITIONS return None for
different-mode pairs (which the transition executor treats as "error").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


# ---------------------------------------------------------------------------
# ModeMeta dataclass — the canonical schema
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModeMeta:
    name: str
    summary: str
    biased: bool
    boost: int
    sub_intents: frozenset
    shape: str | None
    override: bool
    listing_categories: frozenset
    layout_work: tuple
    layout_synthesis: bool
    layout_lazy: tuple
    health_checker: Callable[[Path], list[dict]] | None = field(
        default=None, compare=False, hash=False
    )


# ---------------------------------------------------------------------------
# Boost constants (match the values in router.py — single source now)
# ---------------------------------------------------------------------------

_MODE_BUILD_BOOST: int = 3   # tool_build: hard override — build vocab collides with analysis
_MODE_LIGHT_BOOST: int = 1   # exploration / notebook / multi_study / hybrid: soft nudge


# ---------------------------------------------------------------------------
# Core categories (always active in every mode)
# ---------------------------------------------------------------------------

_CORE_CATEGORIES: frozenset[str] = frozenset({
    "routing", "system", "protocol", "file", "state", "config",
    "checkpoint", "workspace", "interaction", "environment", "memory",
})


# ---------------------------------------------------------------------------
# Mode health checkers — imported lazily to avoid circular deps at module
# load time.  Each checker is injected at registry-build time.
# ---------------------------------------------------------------------------

def _import_health_checkers() -> dict[str, Callable[[Path], list[dict]]]:
    try:
        from research_os.tools.actions.state.mode_health import (
            _check_analysis,
            _check_tool_build,
            _check_notebook,
            _check_multi_study,
            _check_exploration,
            _check_hybrid,
        )
        return {
            "analysis": _check_analysis,
            "tool_build": _check_tool_build,
            "notebook": _check_notebook,
            "multi_study": _check_multi_study,
            "exploration": _check_exploration,
            "hybrid": _check_hybrid,
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Registry — 6 modes, declared once
# ---------------------------------------------------------------------------

_REGISTRY_RAW: list[dict[str, Any]] = [
    # ── analysis ─────────────────────────────────────────────────────────
    # The classic linear numbered-step model.  Neutral baseline: no boost
    # entry (everything is at baseline for this mode).
    {
        "name": "analysis",
        "summary": "Linear numbered-step analysis; synthesis/ holds the paper.",
        "biased": False,
        "boost": 0,
        "sub_intents": frozenset(),
        "shape": None,
        "override": False,
        "listing_categories": frozenset({
            "research", "methodology", "audit", "synthesis", "exec", "execution",
            "data", "intake", "search", "viz", "path", "tasks", "scratch",
        }),
        "layout_work": ("literature",),
        "layout_synthesis": True,
        "layout_lazy": ("synthesis",),
    },
    # ── tool_build ───────────────────────────────────────────────────────
    # Research OS as a governance layer over an inner software project.
    # Strong boost + override: build vocabulary ("test", "release") collides
    # with analysis vocabulary so without override the router flip-flops.
    {
        "name": "tool_build",
        "summary": "Governance layer over an inner tool repo: spec/decisions/eval.",
        "biased": True,
        "boost": _MODE_BUILD_BOOST,
        "sub_intents": frozenset({
            "build_spec", "build_implement", "build_test",
            "build_benchmark", "build_release", "build_publish",
            "build_scout", "build_spike", "build_integrate",
            "build_evaluate", "build_sample_data",
        }),
        "shape": "tool_build",
        "override": True,
        "listing_categories": frozenset({
            "exec", "execution", "audit", "search", "tasks", "scratch", "research",
        }),
        "layout_work": ("spec", "decisions", "eval"),
        "layout_synthesis": False,
        "layout_lazy": (),
    },
    # ── exploration ──────────────────────────────────────────────────────
    # Scratch-first quick probes.  Light boost — overlaps heavily with
    # ordinary analysis vocabulary.
    {
        "name": "exploration",
        "summary": "Scratch-first probing; numbered steps appear on promote.",
        "biased": True,
        "boost": _MODE_LIGHT_BOOST,
        "sub_intents": frozenset({
            "casual", "eda",
            "explore_probe", "explore_promote", "explore_triage",
        }),
        "shape": "exploration",
        "override": False,
        "listing_categories": frozenset({
            "data", "intake", "search", "execution", "exec", "scratch", "viz",
            "research",
        }),
        "layout_work": (),
        "layout_synthesis": True,
        "layout_lazy": ("workspace/logs", "synthesis"),
    },
    # ── notebook ─────────────────────────────────────────────────────────
    # Jupyter-first.  The unit of work is a notebook.
    {
        "name": "notebook",
        "summary": "Jupyter-first: notebooks/ + data/ + outputs/.",
        "biased": True,
        "boost": _MODE_LIGHT_BOOST,
        "sub_intents": frozenset({
            "notebook_run", "notebook_reproduce", "notebook_promote",
            "notebook_synthesize", "eda",
        }),
        "shape": "notebook",
        "override": False,
        "listing_categories": frozenset({
            "data", "intake", "search", "execution", "exec", "scratch", "viz",
            "research",
        }),
        "layout_work": ("notebooks", "data", "outputs"),
        "layout_synthesis": True,
        "layout_lazy": ("synthesis",),
    },
    # ── multi_study ──────────────────────────────────────────────────────
    # Portfolio / program of sub-studies sharing codebook + prereg.
    {
        "name": "multi_study",
        "summary": "Program/portfolio: studies/ + shared/ + roll_up/.",
        "biased": True,
        "boost": _MODE_LIGHT_BOOST,
        "sub_intents": frozenset({
            "program_setup", "study_register", "codebook_governance",
            "cross_study_synthesis",
        }),
        "shape": "multi_study",
        "override": False,
        "listing_categories": frozenset({
            "research", "methodology", "audit", "synthesis", "exec", "execution",
            "data", "intake", "search", "viz", "path", "tasks", "scratch",
        }),
        "layout_work": ("studies", "shared", "roll_up"),
        "layout_synthesis": True,
        "layout_lazy": ("synthesis",),
    },
    # ── hybrid ───────────────────────────────────────────────────────────
    # Build a tool AND use it for analysis in one project.  Light boost —
    # must not fight the analysis/build vocabulary, only nudge the two
    # hybrid-specific protocols when their triggers fire.
    {
        "name": "hybrid",
        "summary": "Analysis spine + lazy tool/ home for the inner software repo (also auto-detected).",
        "biased": True,
        "boost": _MODE_LIGHT_BOOST,
        "sub_intents": frozenset({
            "hybrid_run", "hybrid_handoff",
            "build_scout", "build_spike", "build_integrate",
            "build_evaluate", "build_sample_data",
        }),
        "shape": "hybrid",
        "override": False,
        "listing_categories": frozenset({
            "research", "methodology", "audit", "synthesis", "exec", "execution",
            "data", "intake", "search", "viz", "path", "tasks", "scratch",
        }),
        "layout_work": ("literature", "tool"),
        "layout_synthesis": True,
        "layout_lazy": ("tool", "synthesis"),
    },
]


def _build_registry() -> dict[str, ModeMeta]:
    checkers = _import_health_checkers()
    reg: dict[str, ModeMeta] = {}
    for raw in _REGISTRY_RAW:
        name = raw["name"]
        reg[name] = ModeMeta(
            name=name,
            summary=raw["summary"],
            biased=raw["biased"],
            boost=raw["boost"],
            sub_intents=raw["sub_intents"],
            shape=raw["shape"],
            override=raw["override"],
            listing_categories=raw["listing_categories"],
            layout_work=tuple(raw["layout_work"]),
            layout_synthesis=raw["layout_synthesis"],
            layout_lazy=tuple(raw["layout_lazy"]),
            health_checker=checkers.get(name),
        )
    return reg


# The public registry dict.  Importers use MODE_REGISTRY[name] or iterate it.
MODE_REGISTRY: dict[str, ModeMeta] = _build_registry()

# Ordered tuple of all 6 canonical mode names (mirrors VALID_WORKSPACE_MODES
# in config.py, which is now a derived thin view of this).
ALL_MODES: tuple[str, ...] = tuple(m["name"] for m in _REGISTRY_RAW)

# Modes that carry a routing boost (everything except the analysis baseline).
BIASED_MODES: tuple[str, ...] = tuple(
    m["name"] for m in _REGISTRY_RAW if m["biased"]
)


# ---------------------------------------------------------------------------
# Transition policy — default-allow
# ---------------------------------------------------------------------------
#
# DECLARED_TRANSITIONS: pairs with an explicit kind/protocol/guidance spec.
# FORBIDDEN_TRANSITIONS: pairs that are semantically unsupported and must
#   not be allowed even under default-allow.  All other cross-mode pairs
#   are allowed and receive the generic "augment" default spec.
#
# "Forbidden" means the move is structurally destructive or meaningless:
#   hybrid → multi_study : reframe of a already-split project is unsupported
#   multi_study → notebook: would flatten a multi-study program into a single
#                           notebook — data-loss risk, semantically wrong.
#   multi_study → tool_build: program governance doesn't map to a single tool
#                             inner-repo frame.
# ---------------------------------------------------------------------------

DECLARED_TRANSITIONS: dict[tuple[str, str], dict[str, str]] = {
    ("exploration", "analysis"): {
        "kind": "promote",
        "protocol": "exploration/exploration_promote",
        "guidance": (
            "Promote earned probes into numbered analysis steps, "
            "then run guidance/analysis_plan."
        ),
    },
    ("notebook", "analysis"): {
        "kind": "promote",
        "protocol": "notebook/notebook_promote",
        "guidance": (
            "Promote a trusted notebook's result into a durable numbered step."
        ),
    },
    ("exploration", "tool_build"): {
        "kind": "augment",
        "protocol": "",
        "guidance": (
            "Graduate a scratch prototype into a governed build "
            "(spec/decisions/eval + inner repo)."
        ),
    },
    ("analysis", "hybrid"): {
        "kind": "augment",
        "protocol": "",
        "guidance": (
            "Add an inner tool/ repo for software the analysis needs; "
            "keep the analysis spine."
        ),
    },
    ("tool_build", "hybrid"): {
        "kind": "augment",
        "protocol": "hybrid/tool_to_analysis_handoff",
        "guidance": (
            "Keep the built tool; add an analysis spine to USE it on real data."
        ),
    },
    ("analysis", "multi_study"): {
        "kind": "reframe",
        "protocol": "program/program_setup",
        "guidance": (
            "Wrap the current work as study 01 of a program; seed shared/ commons."
        ),
    },
}

# Every mode can always move to exploration (cheapest, additive).
_EXPLORATION_AUGMENT: dict[str, str] = {
    "kind": "augment",
    "protocol": "",
    "guidance": (
        "Open a scratch surface for cheap probing alongside the existing work."
    ),
}
for _m in ALL_MODES:
    if _m != "exploration":
        DECLARED_TRANSITIONS.setdefault((_m, "exploration"), _EXPLORATION_AUGMENT)

# Pairs that are deliberately unsupported (default-allow does NOT apply).
# Keep this small and documented.
FORBIDDEN_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    # hybrid → multi_study: a project that already merges analysis + software
    # cannot be reframed into a multi-study program without losing the tool half.
    ("hybrid", "multi_study"),
    # multi_study → notebook: flattening a program of sub-studies to a single
    # notebook frame is data-loss risk and semantically wrong.
    ("multi_study", "notebook"),
    # multi_study → tool_build: program governance doesn't fit a single inner-repo frame.
    ("multi_study", "tool_build"),
})

# The generic default spec for any allowed but un-declared pair.
_DEFAULT_AUGMENT_SPEC: dict[str, str] = {
    "kind": "augment",
    "protocol": "",
    "guidance": (
        "Additive mode augment: creates the target mode's surface without "
        "removing any existing work. Consult the target mode's scaffold profile "
        "for the directory layout."
    ),
}


def mode_transition_spec(from_mode: str, to_mode: str) -> dict | None:
    """Return the transition spec for from_mode → to_mode.

    Returns:
        None          — same-mode no-op, OR explicitly forbidden pair.
        dict          — declared spec (has kind/protocol/guidance), OR the
                        generic default augment spec for any allowed pair.
    """
    if from_mode == to_mode:
        return None
    if (from_mode, to_mode) in FORBIDDEN_TRANSITIONS:
        return None
    return DECLARED_TRANSITIONS.get((from_mode, to_mode), _DEFAULT_AUGMENT_SPEC)


def all_transitions_from(from_mode: str) -> list[tuple[tuple[str, str], dict]]:
    """Return every allowed transition from from_mode as [(pair, spec), ...].

    Includes both declared and default-allow pairs; excludes forbidden pairs
    and the same-mode no-op.
    """
    result = []
    for to_mode in ALL_MODES:
        if to_mode == from_mode:
            continue
        spec = mode_transition_spec(from_mode, to_mode)
        if spec is not None:
            result.append(((from_mode, to_mode), spec))
    return result


# ---------------------------------------------------------------------------
# Derived views — thin accessors for downstream modules
# ---------------------------------------------------------------------------

def valid_workspace_modes() -> tuple[str, ...]:
    """Tuple of all valid mode names (mirrors VALID_WORKSPACE_MODES)."""
    return ALL_MODES


def mode_listing_categories(mode: str) -> frozenset[str]:
    """CORE ∪ mode-specific extra categories for sys_active_tools scoping."""
    meta = MODE_REGISTRY.get(mode)
    extra = meta.listing_categories if meta else MODE_REGISTRY["analysis"].listing_categories
    return _CORE_CATEGORIES | extra


def mode_layout_spec(mode: str) -> dict:
    """Return the layout-spec dict (work/synthesis/lazy/summary) for a mode."""
    meta = MODE_REGISTRY.get(mode, MODE_REGISTRY["analysis"])
    return {
        "work": meta.layout_work,
        "synthesis": meta.layout_synthesis,
        "lazy": meta.layout_lazy,
        "summary": meta.summary,
    }


def mode_health_checks() -> dict[str, Callable[[Path], list[dict]]]:
    """Return {mode_name: checker_fn} for all modes that have a health checker."""
    return {
        name: meta.health_checker
        for name, meta in MODE_REGISTRY.items()
        if meta.health_checker is not None
    }


def router_mode_routing() -> dict[str, Any]:
    """Return a dict suitable for populating router.MODE_ROUTING.

    Each value is a _ModeRouting-compatible namedtuple-like object.
    Only biased modes (i.e. not 'analysis') are included, matching the
    existing MODE_ROUTING contract.
    """
    # Avoid a circular import — return raw dicts; the router builds
    # _ModeRouting from them.
    return {
        name: {
            "sub_intents": meta.sub_intents,
            "boost": meta.boost,
            "shape": meta.shape,
            "override": meta.override,
        }
        for name, meta in MODE_REGISTRY.items()
        if meta.biased
    }
