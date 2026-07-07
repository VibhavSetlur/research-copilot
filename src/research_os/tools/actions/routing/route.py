"""Hyper-efficient routing — `sys_boot` + `tool_route`.

Goal: keep token cost per turn flat as the protocol + tool surface grows.

* ``sys_boot``  — one MCP call returns state + config + history tail + dep
  inventory + recommended next protocol + pause classification. Replaces 4-5
  separate calls per session boot.

* ``tool_route`` — takes a raw user prompt + optional state hint and
  returns a tight routing decision: ``primary_protocol``,
  ``shortcut_tool``, ``decomposition`` (planned tool sequence persisted to
  ``.os_state/active_plan.json``), ``alternatives``, ``why``. ~250 tokens
  out instead of the ~2-5K an AI would burn loading + scoring protocols
  itself.

* Routing data is served by ``ProtocolRegistry`` from the compiled
  ``protocols/_protocols.bundle`` (P1): trigger phrases, decompositions,
  and intent classes now live in the protocol bodies themselves.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from research_os.protocols._tiers import infer_tier, is_valid_tier
from research_os.utils.common import save_json_atomic

logger = logging.getLogger("research_os.tools.router")

# router.py lives at src/research_os/tools/actions/router.py
# protocols/ live at src/research_os/protocols/. Routing data comes from the
# compiled _protocols.bundle via ProtocolRegistry (P1) — no direct YAML/JSON
# index parsing here anymore.
_PROTOCOLS_DIR = Path(__file__).parent.parent.parent / "protocols"
_ACTIVE_PLAN_FILE = "active_plan.json"

# ---------------------------------------------------------------------------
# Routing-robustness knobs — all tunable here rather than as magic
# literals scattered through the resolver.
# ---------------------------------------------------------------------------

# CONFIDENCE-MARGIN GATE (semantic path). The semantic module already
# abstains on its own _AMBIGUOUS_GAP (0.025), but only when the two
# contenders sit in DIFFERENT intent_classes AND below its confidence
# floor. Here we add a router-level guard for the band the module passes
# through as a "medium" primary: a primary that is NOT yet clearly
# dominant (cosine below _SEMANTIC_DOMINANT_AT) but has a different-class
# runner-up within _SEMANTIC_MARGIN_ASK is too close to bet a YAML load
# on — ask one short question instead. CLEARLY-DOMINANT primaries
# (cosine ≥ _SEMANTIC_DOMINANT_AT) route silently even when a neighbour
# shares vocabulary: a high absolute cosine means we found a real topic.
# Tuned against the adversarial fixtures in test_router.py /
# test_semantic_routing.py; keep both green if you move it.
_SEMANTIC_MARGIN_ASK = 0.03
_SEMANTIC_DOMINANT_AT = 0.62

# CONFIDENCE-MARGIN GATE (trigger path). Two L3 candidates whose integer
# trigger scores differ by less than this are "too close to call". The
# existing L3 ambiguity check uses gap < 2 but ONLY fires within the
# same (L1, L2) bucket; this margin additionally catches near-ties that
# span DIFFERENT intent_classes (the real misroute risk), where the L1
# aggregate already picked a winner and the cross-class runner-up would
# otherwise be silently discarded. A 1-point gap on the raw trigger
# score (one extra single-word match) is not enough separation to bet a
# wrong protocol load on.
_TRIGGER_MARGIN_ASK = 1

# Minimum trigger length (chars) for the PARTIAL (unbounded-substring)
# match path in _score_protocols. Exact space-bounded matches always
# count; this only gates the fuzzier "trigger appears anywhere inside
# the prompt" fallback so 2-3 char acronyms ("hi", "map", "ess", "mar",
# "ipw", "uq") don't fire as accidental substrings of unrelated words
# ("this", "heatmap", "assessment", "summary"). Their exact-token form
# still routes.
_PARTIAL_MATCH_MIN_LEN = 4


def _collapse_hyphens(text: str) -> str:
    """Treat hyphens as word separators so 'agent-based' == 'agent based'.

    Hyphenated compounds dominate single-cell biology, agent-based
    modeling, fixed-effects/cross-sectional econometrics, mixed-methods
    social science, and time-series. Users freely mix the hyphenated and
    spaced forms, so trigger matching must be hyphen-insensitive on BOTH
    sides (prompt and trigger) or roughly half of such requests miss.
    """
    return re.sub(r"-+", " ", text)


# ═══════════════════════════════════════════════════════════════════════
# UNIFIED MODE REGISTRY — derived from ModeMeta (single source of truth).
# Every mode-aware code path (the trigger-score boost, the semantic-deferral
# override, the workflow-shape fallback, _MODE_TRANSITIONS) reads from this
# table. Adding a mode = one entry in state/mode_registry.py.
# ═══════════════════════════════════════════════════════════════════════

from research_os.state.mode_registry import (  # noqa: E402
    MODE_REGISTRY as _MODE_REGISTRY,
    DECLARED_TRANSITIONS as _DECLARED_TRANSITIONS,
    mode_transition_spec as _registry_mode_transition_spec,
)

# Boost constants re-exported for back-compat (numeric values live in mode_registry).
_MODE_BUILD_BOOST = _MODE_REGISTRY["tool_build"].boost   # 3 — firm thumb
_MODE_LIGHT_BOOST = _MODE_REGISTRY["exploration"].boost  # 1 — tie-break nudge
_MODE_OVERRIDE_MIN_BASE = 4    # "strong" trigger = multi-word match


class _ModeRouting(NamedTuple):
    sub_intents: frozenset
    boost: int
    shape: str | None
    override: bool


# MODE_ROUTING: only the biased modes (analysis is the baseline, no entry).
# Derived directly from ModeMeta so router.py and mode_registry.py cannot drift.
MODE_ROUTING: dict[str, _ModeRouting] = {
    name: _ModeRouting(
        sub_intents=meta.sub_intents,
        boost=meta.boost,
        shape=meta.shape,
        override=meta.override,
    )
    for name, meta in _MODE_REGISTRY.items()
    if meta.biased
}

# Back-compat aliases (external importers may reference the old names).
_BUILD_SUB_INTENTS = MODE_ROUTING["tool_build"].sub_intents
_EXPLORATION_SUB_INTENTS = MODE_ROUTING["exploration"].sub_intents
_EXPLORATION_BOOST = _MODE_LIGHT_BOOST

# Fallback map: workspace.mode → implied workflow_shape (derived from the
# registry; kept as a dict for the existing callers).
_MODE_TO_SHAPE = {m: r.shape for m, r in MODE_ROUTING.items() if r.shape}


# ── Mode lifecycle (B2) — default-allow transitions ────────────────────
# _MODE_TRANSITIONS is populated from the registry's DECLARED_TRANSITIONS.
# All non-forbidden pairs are allowed (see mode_registry.FORBIDDEN_TRANSITIONS).
# Kept as a module-level dict for back-compat with callers that import it
# directly.  DO NOT add new pairs here — add them to mode_registry.py instead.
_MODE_TRANSITIONS: dict[tuple[str, str], dict[str, str]] = dict(_DECLARED_TRANSITIONS)


def mode_transition_spec(from_mode: str, to_mode: str) -> dict | None:
    """Return the transition spec for from→to under the default-allow policy.

    Returns None for same-mode no-ops AND for explicitly forbidden pairs.
    Returns a declared spec or the generic default-augment for any other pair.
    Delegates entirely to mode_registry.mode_transition_spec so both callers
    see the same answer from one source of truth.
    """
    return _registry_mode_transition_spec(from_mode, to_mode)


def _mode_boost_for(workspace_mode: str, sub_intent: str | None) -> int:
    """Score boost a protocol earns for matching the active mode's native
    sub-intents. 0 when the mode has no registry entry (analysis) or
    the protocol isn't native to the mode. Single source for the bias."""
    entry = MODE_ROUTING.get(workspace_mode)
    if entry is None or sub_intent is None:
        return 0
    return entry.boost if sub_intent in entry.sub_intents else 0

# WORKFLOW-SHAPE TIEBREAK. A light nudge (half the size of a single
# trigger-word match, so it can only break a tie, never flip a real
# winner) applied to protocols whose scope_tags.workflow_shape overlaps
# the project's declared shape. 'any'-shaped protocols are universal and
# get no nudge (they'd otherwise drown out shape-specific matches).
_WORKFLOW_SHAPE_BOOST = 1

# Cache: protocol_id → tier (read lazily from the YAML).
_TIER_CACHE: dict[str, str] = {}

# Cache: pack domain-detector results, keyed on the inputs/ dir + its
# mtime. run_pack_domain_detectors does a full inputs/ rglob + read on
# every boot; without this, large corpora make every `sys_boot` pay a
# latency cliff. Recompute only when inputs/ changes.
_PACK_SIGNALS_CACHE: dict[str, tuple[float, list[dict]]] = {}


def _pack_signals_cached(inputs_dir: Path) -> list[dict]:
    """run_pack_domain_detectors, memoised on the inputs/ dir mtime.

    The inputs directory's own mtime changes whenever a file is added,
    removed, or renamed at its top level — a cheap staleness key that
    avoids re-walking the whole tree on every boot.
    """
    from research_os.plugins import run_pack_domain_detectors as _detect

    try:
        mtime = inputs_dir.stat().st_mtime
    except OSError:
        # No inputs/ dir yet — nothing to detect, nothing to cache.
        return []
    cache_key = str(inputs_dir.resolve())
    cached = _PACK_SIGNALS_CACHE.get(cache_key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    signals = _detect(inputs_dir)
    _PACK_SIGNALS_CACHE[cache_key] = (mtime, signals)
    return signals


def _resolve_tier(
    protocol_id: str | None,
    primary_data: dict | None = None,
) -> str | None:
    """Look up the tier for a protocol.

    Order of precedence:
      1. Cached value.
      2. Top-level ``tier:`` field on the protocol YAML (the backfill
         script writes this on every protocol).
      3. ``infer_tier`` over the router-index metadata as a fallback —
         covers pack protocols that haven't been backfilled.

    Returns None when no tier can be inferred (e.g. an unknown protocol
    id with no metadata).
    """
    if not protocol_id:
        return None
    cached = _TIER_CACHE.get(protocol_id)
    if cached:
        return cached
    # Prefer the pre-baked tier from the compiled route-meta — no body read.
    meta = primary_data or {}
    if not meta:
        try:
            meta = (_load_index().get("protocols", {}) or {}).get(protocol_id, {}) or {}
        except Exception:
            meta = {}
    baked = meta.get("tier")
    if is_valid_tier(baked):
        _TIER_CACHE[protocol_id] = baked
        return baked
    # Fallback (dev tree without a sidecar): read the protocol body YAML.
    try:
        rel = protocol_id if protocol_id.endswith(".yaml") else f"{protocol_id}.yaml"
        candidate = _PROTOCOLS_DIR / rel
        if candidate.exists():
            data = yaml.safe_load(candidate.read_text()) or {}
            tier = data.get("tier")
            if is_valid_tier(tier):
                _TIER_CACHE[protocol_id] = tier
                return tier
    except Exception as exc:
        logger.debug("tier read for %s failed: %s", protocol_id, exc)
    # Last resort: infer from router-index metadata.
    category = protocol_id.split("/")[0] if "/" in protocol_id else None
    tier = infer_tier(
        intent_class=meta.get("intent_class"),
        sub_intent=meta.get("sub_intent"),
        category=category,
        protocol_id=protocol_id,
    )
    if is_valid_tier(tier):
        _TIER_CACHE[protocol_id] = tier
        return tier
    return None


def _clear_tier_cache() -> None:
    """Test hook — drop the tier cache so re-annotating a YAML takes effect."""
    _TIER_CACHE.clear()


# ---------------------------------------------------------------------------
# Index loading (cached)
# ---------------------------------------------------------------------------


def _load_index() -> dict:
    """Routing index in the legacy shape, sourced from the bundle.

    P1: the router no longer parses YAML or a JSON sidecar — it reads the
    compiled ``_protocols.bundle`` via :class:`ProtocolRegistry`, which also
    folds in pack-contributed routing entries. The returned shape
    (``{protocols, shortcut_intents, hierarchy}``) is unchanged so the rest
    of the resolver is untouched.
    """
    from research_os.tools.actions.protocol import ProtocolRegistry

    return ProtocolRegistry.get_index()


def reload_index() -> None:
    """Force-reload the index (test hook)."""
    from research_os.tools.actions.protocol import ProtocolRegistry

    ProtocolRegistry.reload()


# ---------------------------------------------------------------------------
# Workspace-mode + workflow-shape signals (best-effort, never raise)
# ---------------------------------------------------------------------------


def _read_workspace_mode(root: Path | None) -> str:
    """Read workspace_mode ('analysis' default). Never raises out of routing."""
    if root is None:
        return "analysis"
    try:
        from research_os.tools.actions.state.config import get_workspace_mode
        return get_workspace_mode(root)
    except Exception as exc:
        logger.debug("workspace_mode read failed: %s", exc)
        return "analysis"


# Cache: protocol_id → tuple of workflow_shape tags read from the
# protocol body YAML's scope_tags. Read lazily; the maintainer owns the
# bodies but the router only reads them as a routing signal.
_WORKFLOW_SHAPE_CACHE: dict[str, tuple[str, ...]] = {}


def _protocol_workflow_shape(protocol_id: str) -> tuple[str, ...]:
    """Return the scope_tags.workflow_shape tags for a protocol body.

    Best-effort: returns () when the body is missing, malformed, or has no
    workflow_shape. Cached for process lifetime.
    """
    cached = _WORKFLOW_SHAPE_CACHE.get(protocol_id)
    if cached is not None:
        return cached
    shape: tuple[str, ...] = ()
    # Prefer the pre-baked workflow_shape from the compiled route-meta — the
    # key is always present there (a list, possibly empty), so its presence is
    # authoritative and no protocol body is opened at route time.
    try:
        meta = (_load_index().get("protocols", {}) or {}).get(protocol_id, {}) or {}
    except Exception:
        meta = {}
    if "workflow_shape" in meta:
        tags = meta.get("workflow_shape") or []
        if isinstance(tags, list):
            shape = tuple(str(t).strip().lower() for t in tags if t)
        elif isinstance(tags, str):
            shape = (tags.strip().lower(),)
        _WORKFLOW_SHAPE_CACHE[protocol_id] = shape
        return shape
    # Fallback (dev tree without a sidecar): read the protocol body YAML.
    try:
        rel = protocol_id if protocol_id.endswith(".yaml") else f"{protocol_id}.yaml"
        candidate = _PROTOCOLS_DIR / rel
        if candidate.exists():
            data = yaml.safe_load(candidate.read_text()) or {}
            tags = (data.get("scope_tags") or {}).get("workflow_shape") or []
            if isinstance(tags, list):
                shape = tuple(str(t).strip().lower() for t in tags if t)
            elif isinstance(tags, str):
                shape = (tags.strip().lower(),)
    except Exception as exc:
        logger.debug("workflow_shape read for %s failed: %s", protocol_id, exc)
    _WORKFLOW_SHAPE_CACHE[protocol_id] = shape
    return shape


def _read_project_workflow_shape(root: Path | None) -> str | None:
    """Read the project's declared workflow_shape from researcher_config.

    Looks under ``workspace.workflow_shape`` first (forward-compatible)
    then a top-level ``workflow_shape``. Returns a lowercased string or
    None when unset. Never raises out of routing.
    """
    if root is None:
        return None
    try:
        from research_os.tools.actions.state.config import get_config
        cfg_res = get_config(root)
        if cfg_res.get("status") != "success":
            return None
        cfg = cfg_res.get("config", {}) or {}
        workspace = cfg.get("workspace") or {}
        shape = None
        if isinstance(workspace, dict):
            shape = workspace.get("workflow_shape")
        if not shape:
            shape = cfg.get("workflow_shape")
        if isinstance(shape, str) and shape.strip():
            return shape.strip().lower()
        # Fallback: map workspace.mode to a workflow_shape so the boost
        # fires even when the project never declared an explicit shape.
        # (Previously the project-side shape was never written by anything,
        # so this tiebreak was permanently dead for real projects.)
        mode = workspace.get("mode") if isinstance(workspace, dict) else None
        mapped = _MODE_TO_SHAPE.get(str(mode or "").strip().lower())
        if mapped:
            return mapped
    except Exception as exc:
        logger.debug("project workflow_shape read failed: %s", exc)
    return None


def _clear_workflow_shape_cache() -> None:
    """Test hook — drop the workflow-shape cache."""
    _WORKFLOW_SHAPE_CACHE.clear()


def _normalize_prompt(prompt: str) -> str:
    """Lowercase, strip, space-pad, and collapse punctuation + hyphens.

    Single source of truth for the prompt normalization that
    ``_score_protocols`` relies on: triggers are matched as space-bounded
    substrings and hyphen-collapsed on their side, so the prompt must be
    hyphen-collapsed AND leading/trailing-space-padded for boundary +
    'agent-based' == 'agent based' matches to fire. Every _score_protocols
    call site must feed a prompt through this (3.2.9 hyphen-normalization
    was applied on the main path only)."""
    pn = " " + re.sub(r"[,.;:!?\-]+", " ", prompt.lower().strip()) + " "
    return re.sub(r"\s+", " ", pn)


# ---------------------------------------------------------------------------
# Semantic routing — primary path when fastembed + embeddings file present
# ---------------------------------------------------------------------------


def _try_semantic_route(
    prompt: str,
    protocols: dict,
    hierarchy: dict,
    shortcuts: dict,
    *,
    is_complex: bool,
    root: Path,
    persist_plan: bool,
    workspace_mode: str = "analysis",
    project_workflow_shape: str | None = None,
) -> dict[str, Any] | None:
    """Run the semantic router and shape the result like the trigger router.

    Returns None when:
      - the semantic module isn't usable (fastembed not installed OR
        embeddings file missing) — caller falls back to trigger router.
      - the semantic confidence is "low" or "none" — caller falls back so
        the trigger router can try its luck (it may find a literal match
        the semantic path missed).
      - the top semantic protocol_id is not in the router index (defensive
        — happens if embeddings + index are out of sync).
      - MODE override: in ``tool_build`` mode a build/* protocol matched a
        trigger strongly enough that we'd rather take the mode-biased
        trigger path than the semantic guess (keeps build-shaped prompts
        landing on build/* even when their vocabulary embeds near an
        analysis protocol).
    """
    try:
        from research_os.tools.actions import semantic
    except Exception:
        return None
    if not semantic.semantic_available():
        return None

    # MODE override (registry-driven): if the active mode is marked
    # override=True and one of its NATIVE-sub-intent protocols has a strong
    # trigger match, defer to the mode-biased trigger router rather than the
    # semantic guess. "Strong" = a multi-word trigger (base ≥
    # _MODE_OVERRIDE_MIN_BASE) so a single stray mode word doesn't hijack an
    # analysis prompt. Today only tool_build opts in (build vocabulary
    # collides with analysis), but any future mode can by setting override.
    _mode_entry = MODE_ROUTING.get(workspace_mode)
    if _mode_entry is not None and _mode_entry.override:
        # Normalize identically to the main path (the old inline form missed
        # the hyphen collapse, so 'agent-based' never matched 'agent based').
        prompt_norm = _normalize_prompt(prompt)
        native_scored = [
            s for s in _score_protocols(
                prompt_norm, protocols,
                workspace_mode=workspace_mode,
                project_workflow_shape=project_workflow_shape,
            )
            if (s["data"].get("sub_intent") in _mode_entry.sub_intents)
            and s.get("base_score", 0) >= _MODE_OVERRIDE_MIN_BASE
        ]
        if native_scored:
            return None

    sem = semantic.semantic_route(prompt, k=5)
    if sem is None:
        return None

    confidence = sem.get("confidence", "none")
    if confidence in ("low", "none"):
        # Let the trigger router try — it might pick up an exact phrase
        # the embedding missed. If it ALSO fails, the trigger router's
        # _fallback_response surfaces the candidates from this same set.
        return None

    primary_id = sem.get("primary_protocol")
    if not primary_id or primary_id not in protocols:
        # Embeddings + index drift. Refuse and let the trigger router
        # provide a safer answer.
        logger.warning(
            "Semantic top match '%s' not in router index — falling back.", primary_id
        )
        return None

    # ── CONFIDENCE-MARGIN GATE (semantic path) ─────────────────────────
    # Even on a confident primary, if the runner-up's cosine is within
    # _SEMANTIC_MARGIN_ASK AND it lives in a different intent_class, the
    # two are too close to silently pick one. Surface a 2-named ask_user
    # instead of loading the wrong YAML. (Same-intent-class near-ties are
    # left alone — picking the wrong sibling is cheap to recover from.)
    cands = sem.get("candidates") or []
    if len(cands) >= 2:
        try:
            s0 = float(cands[0].get("score", 0.0))
            s1 = float(cands[1].get("score", 0.0))
        except (TypeError, ValueError):
            s0, s1 = 1.0, 0.0
        id0, id1 = cands[0].get("id"), cands[1].get("id")
        cls0 = (protocols.get(id0) or {}).get("intent_class")
        cls1 = (protocols.get(id1) or {}).get("intent_class")
        if (
            id1 in protocols
            and cls0 and cls1 and cls0 != cls1
            and s0 < _SEMANTIC_DOMINANT_AT          # not clearly dominant
            and (s0 - s1) < _SEMANTIC_MARGIN_ASK
        ):
            return {
                "status": "success",
                "resolved_level": 2,
                "intent_class": None,
                "sub_intent": None,
                "primary_protocol": None,
                "shortcut_tool": None,
                "decomposition": [],
                "alternatives": [
                    {
                        "name": c.get("id"),
                        "score": round(float(c.get("score", 0.0)), 4),
                        "intent_class": (protocols.get(c.get("id")) or {}).get(
                            "intent_class"
                        ),
                        "why_matched": (
                            f"Semantic similarity {round(float(c.get('score', 0.0)), 3)}"
                        ),
                    }
                    for c in cands[:3]
                    if c.get("id") in protocols
                ],
                "ambiguous_alternatives": [id0, id1],
                "matched_triggers": [],
                "why_matched": (
                    f"Two protocols match similarly ({round(s0, 3)} vs "
                    f"{round(s1, 3)}) across different intent classes."
                ),
                "tier": None,
                "tier_transition": _compute_route_transition(root, None),
                "complexity": "high" if is_complex else "low",
                "ask_user": (
                    "Your prompt matches two different kinds of work about "
                    f"equally: (1) {id0} — {(protocols.get(id0) or {}).get('summary', id0)}; "
                    f"or (2) {id1} — {(protocols.get(id1) or {}).get('summary', id1)}. "
                    "Which did you mean?"
                ),
                "why": (
                    "Confidence-margin gate: top-2 semantic candidates within "
                    f"{_SEMANTIC_MARGIN_ASK} across intent classes."
                ),
                "advice": _route_advice_hier(2, is_complex, None, None, True),
                "token_estimate": None,
                "active_tools": list(_ESSENTIAL_TOOLS),
                "method": "semantic",
                "confidence": "low",
                "semantic_candidates": cands,
            }

    primary_data = protocols[primary_id]
    decomposition = primary_data.get("decomposition", []) or []
    shortcut_tool = primary_data.get("shortcut_tool")
    intent_class = primary_data.get("intent_class")
    sub_intent = primary_data.get("sub_intent")

    # If the prompt LOOKS complex (multi-clause) AND the semantic
    # winner is a narrow leaf with no decomposition (typical for
    # writing/* and other single-step protocols), let the trigger
    # router try — its multi-protocol scoring often picks a parent
    # (e.g. guidance/analysis_plan) whose decomposition CAN be
    # persisted as an active_plan. We only fall through when the
    # trigger router's top pick has its own decomposition and a
    # higher trigger-score than what semantic surfaced; otherwise
    # we keep the semantic primary but DOWNGRADE complexity to "low"
    # below so the response is internally consistent (no plan
    # promised, none persisted).
    fall_through = False
    if is_complex and not decomposition:
        # Feed the SAME normalized prompt the main path uses — raw
        # prompt.lower() has no space-padding/hyphen collapse, so triggers at
        # the very start/end of the prompt (e.g. 'bug' in 'fix the bug') and
        # hyphenated triggers silently failed to score here.
        scored = _score_protocols(
            _normalize_prompt(prompt), protocols,
            workspace_mode=workspace_mode,
            project_workflow_shape=project_workflow_shape,
        )
        for cand in scored[:3]:
            cand_data = cand["data"]
            if cand_data.get("decomposition"):
                fall_through = True
                break
    if fall_through:
        return None

    # No decomposition + complex but no better trigger-router pick:
    # surface the protocol, but call it complexity=low so the AI
    # doesn't look for an active_plan that was never persisted.
    effective_complexity = "high" if (is_complex and decomposition) else "low"

    # Top-3 alternatives with their semantic scores so callers can see
    # the runner-ups and re-route deliberately.
    alternatives_full = []
    for c in (sem.get("candidates") or []):
        cid = c.get("id")
        if cid == primary_id or cid not in protocols:
            continue
        cand_data = protocols.get(cid) or {}
        try:
            score_val = float(c.get("score", 0.0))
        except (TypeError, ValueError):
            score_val = 0.0
        alternatives_full.append({
            "name": cid,
            "score": round(score_val, 4),
            "intent_class": cand_data.get("intent_class"),
            "why_matched": (
                f"Semantic similarity {round(score_val, 3)} on "
                f"intent_class={cand_data.get('intent_class') or '?'}"
            ),
        })
        if len(alternatives_full) >= 3:
            break

    why_matched_primary = (
        f"Semantic similarity {round(float(sem['candidates'][0]['score']), 3)} "
        f"(confidence={confidence}) on intent_class={intent_class or '?'}"
    )

    tier = _resolve_tier(primary_id, primary_data)
    tier_transition = _compute_route_transition(root, tier)
    response: dict[str, Any] = {
        "status": "success",
        "resolved_level": 3,
        "intent_class": intent_class,
        "sub_intent": sub_intent,
        "primary_protocol": primary_id,
        "shortcut_tool": shortcut_tool,
        "decomposition": decomposition,
        "alternatives": alternatives_full,
        "ambiguous_alternatives": [],
        "matched_triggers": [],         # semantic path doesn't surface raw triggers
        "why_matched": why_matched_primary,
        "tier": tier,
        "tier_transition": tier_transition,
        "complexity": effective_complexity,
        "ask_user": None,
        "why": (
            f"Semantic match (confidence={confidence}) on protocol description + "
            f"triggers. Top candidate score "
            f"{sem['candidates'][0]['score']:.3f}."
        ),
        "advice": _route_advice_hier(
            3, effective_complexity == "high", primary_id, shortcut_tool, False
        ),
        "token_estimate": primary_data.get("token_estimate"),
        "active_tools": _active_tools_for(primary_data, shortcut_tool),
        "method": "semantic",
        "confidence": confidence,
        "semantic_candidates": sem.get("candidates") or [],
    }

    # Persist the active plan only when complex + decomposition exists,
    # same rule as the trigger path.
    if persist_plan and effective_complexity == "high" and decomposition:
        plan_path = _persist_active_plan(
            root, prompt, primary_id, decomposition, shortcut_tool,
        )
        response["active_plan_path"] = plan_path

    return response


# ---------------------------------------------------------------------------
# sys_boot — one-call session bootstrap
# ---------------------------------------------------------------------------


def sys_boot(root: Path, *, lean: bool = False) -> dict[str, Any]:
    """Return everything needed to start (or continue) a session in ONE call.

    Bundles: project / pipeline state, researcher config (autonomy +
    expertise + model_profile + runtime), recent protocol history, missing
    optional deps, recommended next protocol, pause classification, and
    any active plan from a previous turn. Cuts a typical session boot
    from 4-5 MCP calls (~5K tokens) down to one (~800 tokens).

    Pass ``lean=True`` for a ~50-token subset — only
    {active_plan, pause_classification, current_tier, root, active_packs}.
    Use for mid-session orientation when you don't need the full boot.
    """
    try:
        from research_os.project_ops import load_state
        from research_os.tools.actions.protocol import (
            get_next_protocol,
            get_protocol_history,
        )
        from research_os.tools.actions.state.config import get_config

        # Pack inventory — names only. Used by both lean + full shapes
        # so the AI always knows which packs the server has loaded.
        try:
            from research_os.plugins import installed_packs as _packs_inv

            active_packs = [p.get("name") for p in (_packs_inv() or []) if p.get("name")]
        except Exception:
            active_packs = []

        # Lean mode — minimal orientation. Skip dep_inventory,
        # protocol_history, recent_calls, freshness, paths_summary, etc.
        if lean:
            try:
                history = get_protocol_history(root, limit=5)
                entries = history.get("entries", []) or []
            except Exception:
                entries = []
            try:
                pause = _classify_pause(entries, root)
            except Exception:
                pause = "unknown"
            try:
                active_plan = _load_active_plan(root)
            except Exception:
                active_plan = None
            try:
                from research_os.tools.actions.state.tier_state import (
                    get_current_tier,
                )

                current_tier = get_current_tier(root)
            except Exception:
                current_tier = None
            return {
                "status": "success",
                "active_plan": active_plan,
                "pause_classification": pause,
                "current_tier": current_tier,
                "root": str(root),
                "active_packs": active_packs,
            }

        # State (graceful when the workspace is partially scaffolded).
        try:
            state = load_state(root)
        except Exception:
            state = {}

        # Config.
        cfg_res = get_config(root)
        cfg = cfg_res.get("config", {}) if cfg_res.get("status") == "success" else {}

        # History.
        history = get_protocol_history(root, limit=5)
        entries = history.get("entries", []) or []
        last_entry = entries[-1] if entries else None

        # Pause classification (drives whether to call session_resume next).
        pause = _classify_pause(entries, root)

        # Next protocol (cheap predicate scan).
        next_proto = get_next_protocol(root)

        # Active plan from a prior turn (set by tool_route for complex prompts).
        active_plan = _load_active_plan(root)

        # Optional-dep inventory (imported lazily — server.py owns the list).
        dep_inv = _dep_inventory()

        # Compact hypothesis view — short statements + status, never the
        # full evidence list (that bloats sys_boot when steps are deep).
        hyps_short = [
            {
                "id": h.get("id"),
                "status": h.get("status", "testing"),
                "statement": (h.get("statement") or "")[:120],
            }
            for h in (state.get("active_hypotheses") or [])
        ]

        # Paths summary — id + status + the per-step focal-figure flag
        # so the AI can spot which steps still need a figure / caption
        # before final synthesis.
        try:
            from research_os.tools.actions.state.path import list_paths
            from research_os.tools.actions.viz import step_figure_inventory

            paths_summary = []
            for p in (list_paths(root).get("paths") or []):
                pid = p.get("path_id")
                missing_focal = False
                missing_caps = 0
                try:
                    inv = step_figure_inventory(pid, root)
                    missing_focal = bool(inv.get("missing_focal_figure"))
                    missing_caps = len(inv.get("missing_captions", []))
                except Exception:
                    pass
                paths_summary.append({
                    "id": pid,
                    "status": p.get("status"),
                    "missing_focal_figure": missing_focal,
                    "missing_captions": missing_caps,
                })
        except Exception:
            paths_summary = []

        # Long-context handoff hint. Once the project has 5+
        # finalized analysis steps, the AI is recommended to suggest
        # `sys_session_handoff` + a fresh chat before the next step.
        # Prevents the "AI one-shots step 6, 7, 8 in lossy context"
        # failure mode.
        n_finalized = sum(
            1 for p in paths_summary if p.get("status") == "completed"
        )
        handoff_recommended = n_finalized >= 5
        handoff_hint = ""
        if handoff_recommended:
            handoff_hint = (
                f"This project has {n_finalized} finalized step(s). "
                "Context is getting long — strongly recommend "
                "`sys_session_handoff` + a fresh chat before the next "
                "analysis step or synthesis pass. The handoff doc + "
                "STATE.md will let the next chat resume cleanly."
            )

        # Auto-check stale-state signals. Cheap; surfaces a
        # "reconfirm?" prompt when the workspace has drifted since
        # the last active session.
        freshness = {"is_stale": False, "signals": [], "prompt_for_ai": ""}
        try:
            from research_os.tools.actions.state.freshness import (
                state_freshness_check,
            )
            res = state_freshness_check(root)
            if res.get("status") == "success":
                freshness = {
                    "is_stale": bool(res.get("is_stale", False)),
                    "signals": list(res.get("signals", []))[:5],
                    "prompt_for_ai": str(res.get("prompt_for_ai", "")),
                }
        except Exception as e:
            logger.debug("state_freshness_check skipped: %s", e)

        # Current tier — surfaced alongside packs for orientation.
        try:
            from research_os.tools.actions.state.tier_state import (
                get_current_tier,
            )

            current_tier = get_current_tier(root)
        except Exception:
            current_tier = None

        # Extension-surface visibility — the packs/adapters are invisible
        # otherwise (the AI never learns half the product exists). Surface,
        # every session: what each loaded pack offers (pack_capabilities),
        # which pack the project INPUTS actually look like (field_signals +
        # a one-line pack_nudge, via the now-wired domain detectors), and
        # which infra adapters fired (adapters_detected).
        pack_capabilities: list[dict] = []
        field_signals: list[dict] = []
        adapters_detected: list[str] = []
        pack_nudge = ""
        try:
            from research_os.plugins import installed_packs as _ip
            for p in (_ip() or []):
                pack_capabilities.append({
                    "name": p.get("name"),
                    "summary": (p.get("description") or "")[:140],
                })
            field_signals = _pack_signals_cached(root / "inputs")
            if field_signals:
                top = field_signals[0]
                sig = ", ".join(top.get("signals", [])[:2])
                pack_nudge = (
                    f"Project inputs look like '{top['pack']}' work ({sig}). "
                    f"The {top['pack']} pack adds domain tools + protocols — "
                    f"sys_help(topic='packs'). Core stays field-agnostic regardless."
                )
        except Exception as e:
            logger.debug("pack surface skipped: %s", e)
        try:
            from research_os.adapters.runner import list_adapters as _la
            adapters_detected = [
                a.get("name") for a in (_la(root).get("adapters") or [])
                if a.get("detected_in_project")
            ]
        except Exception as e:
            logger.debug("adapter detection skipped: %s", e)

        _mode_info = _boot_mode_info(root)

        # Compute these ONCE so both the boot payload and the advice line agree.
        # (C2) the durable roadmap — an in-flight autonomous loop the AI must
        # re-enter after a /compact; (H1) daemon block escalation.
        _daemon_notes = _boot_daemon_notes(root)
        _roadmap = _boot_roadmap(root, entries)

        # Active skill-pulling (first-turn): on a FRESH project, recommend the
        # capabilities (Hermes skills / the researcher's distilled ones) that
        # match this project's domain + mode, so the AI/Hermes loads them up
        # front instead of discovering them late. Only on a fresh project to
        # avoid noise once work is underway. By-shape, fail-open.
        recommended_skills: list = []
        try:
            if n_finalized == 0:
                from research_os.tools.actions.research.skills import (
                    recommend_skills as _rec_skills,
                )
                _rs = _rec_skills(
                    root,
                    domain=state.get("domain") or cfg.get("domain", ""),
                    workspace_mode=_read_workspace_mode(root),
                )
                recommended_skills = _rs.get("recommended_skills", [])
        except Exception:
            recommended_skills = []

        return {
            "status": "success",
            "project_name": state.get("project_name", "(unnamed)"),
            "pipeline_stage": state.get("pipeline_stage", "init"),
            "current_path": state.get("current_path", "main"),
            "domain": state.get("domain") or cfg.get("domain", ""),
            "research_question_set": bool(
                (state.get("research_question") or cfg.get("research_question"))
                and "(blank" not in str(state.get("research_question") or cfg.get("research_question", ""))
            ),
            "autonomy": cfg.get("interaction", {}).get("autonomy_level", "supervised"),
            "expertise": cfg.get("researcher", {}).get(
                "expertise_level", "intermediate"
            ),
            "model_profile": (
                cfg.get("ai", {}).get("model_profile")
                or cfg.get("model_profile", "medium")
            ),
            "context_class": cfg.get("ai", {}).get("context_class", "short"),
            "shared_server": cfg.get("runtime", {}).get("shared_server", False),
            "long_running_threshold": cfg.get("runtime", {}).get(
                "long_running_threshold_seconds", 60
            ),
            "active_hypotheses": hyps_short,
            "paths_summary": paths_summary,
            "history_tail": entries[-3:],
            "last_protocol_entry": last_entry,
            "pause_classification": pause,
            "next_protocol": next_proto,
            "dep_inventory": dep_inv,
            "active_plan": active_plan,
            "active_packs": active_packs,
            "pack_capabilities": pack_capabilities,
            "pack_nudge": pack_nudge,
            "recommended_skills": recommended_skills,
            "field_signals": field_signals,
            "adapters_detected": adapters_detected,
            "current_tier": current_tier,
            "handoff_recommended": handoff_recommended,
            "handoff_hint": handoff_hint,
            "n_finalized_steps": n_finalized,
            "freshness": freshness,
            # The daemon's startup self-check (if a daemon ran): structural
            # problems / interrupted runs / unframed intake it noticed and
            # wrote to .os_state/daemon_notes.json. Read by-shape (no daemon
            # import). The AI should ACT on any block/warn here before building.
            "daemon_notes": _daemon_notes,
            # The behavioural contract from researcher_config, surfaced
            # compactly so the AI FOLLOWS it every session AND keeps it in
            # sync (a secondary AGENTS.md). See config_reconcile_hint.
            "config_directives": {
                "autonomy": (cfg.get("interaction") or {}).get("autonomy_level", "supervised"),
                "quality_gate_policy": (cfg.get("interaction") or {}).get("quality_gate_policy", "enforce"),
                "ambiguity_posture": (cfg.get("interaction") or {}).get("ambiguity_posture", "ask_when_uncertain"),
                "agent_notes": (cfg.get("interaction") or {}).get("agent_notes", ""),
                "output_types": (cfg.get("research_goal") or {}).get("output_types", []),
                "target_venue": (cfg.get("research_goal") or {}).get("target_venue", ""),
                "citation_style": (cfg.get("writing_preferences") or {}).get("citation_style", ""),
                "compute_environment": (cfg.get("runtime") or {}).get("compute_environment", ""),
            },
            "config_reconcile_hint": _config_reconcile_hint(cfg),
            # Live drop-zone awareness + glossary nudge (peek only — the
            # marker is consumed by tool_route so each drop surfaces once).
            "new_context": _boot_new_context(root),
            "glossary_unfilled": _boot_glossary_unfilled(root, n_finalized),
            # Workspace mode shapes routing + scaffolds. Surface it (and a
            # one-line directive) so the AI behaves mode-appropriately and can
            # notice when the project has outgrown its mode — the mode silently
            # biases routing, so the AI must SEE it to reason about it.
            "workspace_mode": _mode_info[0],
            "mode_directive": _mode_info[1],
            # Hybrid (research + software): inner code components, so the AI
            # governs the research in workspace/ AND the code via tool_git /
            # tool_build on the inner repo.
            "software_components": _boot_software_components(root),
            # (C2) durable roadmap pointer — surfaced so an autonomous loop
            # survives a /compact and the AI re-enters it instead of the linear
            # pipeline.
            "roadmap": _roadmap,
            "advice": _boot_advice(pause, active_plan, state, cfg, _daemon_notes, _roadmap),
            # §13.1 Active persona — directive text returned as MCP context.
            # Research-OS never sends this to any model; the client's AI reads it.
            "active_persona": _boot_active_persona(root),
        }
    except Exception as e:
        logger.exception("sys_boot failed")
        return {"status": "error", "message": str(e)}


def _boot_active_persona(root: Path) -> dict:
    """Return the active persona name + directive for the sys_boot payload.

    Text only — never sent to any model by Research-OS.
    Fail-open: returns scruffy defaults on any error.
    """
    try:
        from research_os.server.personas import PERSONAS, get_active_persona

        active = get_active_persona(root)
        persona = PERSONAS.get(active, PERSONAS["scruffy"])
        return {
            "name": active,
            "directive": persona["directive"],
            "tool_visibility": persona["tool_visibility"],
            "execution_policy": persona["execution_policy"],
        }
    except Exception:
        return {
            "name": "scruffy",
            "directive": "exploratory: creative, unconventional, tolerate ambiguity",
            "tool_visibility": "all",
            "execution_policy": "direct",
        }


def _boot_new_context(root: Path) -> dict:
    """sys_boot peek at the context drop-zone (does NOT consume the marker
    — tool_route consumes it so each drop surfaces once on the next prompt)."""
    try:
        from research_os.tools.actions.state.context_watch import detect_new_context

        nc = detect_new_context(root, update_marker=False)
        return {
            "new_files": nc.get("new_files", []),
            "changed_files": nc.get("changed_files", []),
            "hint": nc.get("hint", ""),
        }
    except Exception:
        return {"new_files": [], "changed_files": [], "hint": ""}


def _boot_daemon_notes(root: Path) -> dict:
    """sys_boot peek at the daemon's startup self-check notes (by-shape, no
    daemon import). Returns a compact summary the AI acts on; empty when no
    daemon ran / no notes exist. Fail-safe."""
    try:
        from research_os.server import daemon_bridge as _bridge

        notes = _bridge.read_daemon_notes(root)
        if not isinstance(notes, dict):
            return {"present": False, "findings": [], "hint": ""}
        findings = notes.get("findings") or []
        counts = notes.get("counts") or {}
        # Surface the messages compactly; the full note lives in
        # .os_state/daemon_notes.md for the AI to read in full if needed.
        msgs = [
            f"[{f.get('severity', 'info')}] {f.get('message', '')}"
            for f in findings
        ][:8]
        # (M2) tell the AI when findings were truncated so it knows to read the
        # full note rather than assuming it saw everything.
        if len(findings) > 8:
            msgs.append(
                f"...and {len(findings) - 8} more — see .os_state/daemon_notes.md"
            )
        hint = ""
        if counts.get("block"):
            hint = (
                "The daemon found BLOCK-level integrity issues — address them "
                "(tool_workspace_repair / tool_structure_audit) before building."
            )
        elif findings:
            hint = "The daemon left notes — review and address them this turn."
        return {
            "present": True,
            "ok": notes.get("ok", True),
            "counts": counts,
            "findings": msgs,
            "hint": hint,
        }
    except Exception:
        return {"present": False, "findings": [], "hint": ""}


def _boot_software_components(root: Path) -> list:
    """Inner software components (hybrid projects) — empty for pure analysis."""
    try:
        from research_os.project_ops import detect_software_components

        return detect_software_components(root)
    except Exception:
        return []


# One-line behavioural directive per workspace mode. Kept terse — it tells the
# AI how to act in this mode and the natural transition signal, so it can both
# behave mode-appropriately and notice when the project has outgrown its mode.
_MODE_DIRECTIVES: dict[str, str] = {
    "analysis": (
        "Analysis mode: linear numbered research steps in workspace/. If you "
        "find yourself needing to BUILD a reusable tool, consider switching to "
        "hybrid (sys_config workspace.mode=hybrid)."
    ),
    "tool_build": (
        "Tool-build mode: you ship software governed from above (spec → "
        "implement → test → benchmark → evaluate → release) in the inner repo. "
        "Run build/tool_evaluation_loop to drive the evaluate→improve cycle. If "
        "the project shifts to USING the tool for research, consider hybrid."
    ),
    "hybrid": (
        "Hybrid mode: research in workspace/ AND software in the inner repo. "
        "Pivot via hybrid/hybrid_workflow; hand findings across with "
        "hybrid/tool_to_analysis_handoff; drive tool improvement with "
        "build/tool_evaluation_loop. Keep the two halves in sync."
    ),
    "exploration": (
        "Exploration mode: scratch-first quick probes with light gates. Promote "
        "a probe that proves out into a real analysis step (or switch to "
        "analysis mode) rather than letting scratch work masquerade as a result."
    ),
    "notebook": (
        "Notebook mode: the unit of work is a .ipynb. Execute notebooks as "
        "tracked runs, reproduce before trusting, promote stable cells into "
        "scripts/steps when they harden."
    ),
    "multi_study": (
        "Multi-study mode: a program of sub-studies sharing a codebook + "
        "prereg. Register each study, govern the shared codebook, synthesize "
        "across studies — don't collapse the program into a single study."
    ),
}


def _boot_mode_info(root: Path) -> tuple[str, str]:
    """Return (workspace_mode, one-line behavioural directive) for boot.

    Surfacing the mode + its directive lets the AI act mode-appropriately and
    spot when the project has outgrown its mode. Never raises out of boot.
    """
    try:
        mode = _read_workspace_mode(root)
    except Exception:
        mode = "analysis"
    return mode, _MODE_DIRECTIVES.get(mode, _MODE_DIRECTIVES["analysis"])


def _boot_glossary_unfilled(root: Path, n_finalized: int) -> dict:
    """Nudge to populate docs/glossary.md once the project has substance
    (≥1 finalized step) but the glossary is still header-only."""
    try:
        from research_os.tools.actions.state.context_watch import glossary_unfilled

        empty = glossary_unfilled(root)
    except Exception:
        empty = False
    hint = ""
    if empty and n_finalized >= 1:
        hint = (
            "docs/glossary.md is empty — add the domain terms you've used "
            "(term | definition | source) so a non-expert reader (and the "
            "synthesis) can follow the work."
        )
    return {"empty": bool(empty), "nudge": bool(hint), "hint": hint}


def _config_reconcile_hint(cfg: dict) -> str:
    """One-line nudge: researcher_config is the AI's operating contract;
    keep the behaviour-shaping fields in sync with what the researcher
    asks, and fill the blanks that matter for downstream gates."""
    goal = cfg.get("research_goal") or {}
    runtime = cfg.get("runtime") or {}
    gaps: list[str] = []
    if not (goal.get("output_types") or []):
        gaps.append(
            "research_goal.output_types is blank (exploratory — no auto "
            "paper/dashboard); set it the moment the researcher names a "
            "deliverable"
        )
    if not (runtime.get("compute_environment") or "").strip():
        gaps.append(
            "runtime.compute_environment is blank — record the env "
            "(conda/module/docker) so reproduction is right"
        )
    # Keep this terse — the actual values live in config_directives; no need
    # to re-list them here and pay for it on every boot.
    base = (
        "Follow config_directives; update via sys_config(operation='set') when "
        "intent shifts (autonomy / output / citation style / compute env). When "
        "the researcher corrects you or states a standing preference, record it "
        "with sys_config(operation='note') so the next session inherits it."
    )
    if gaps:
        base += " Fill from the conversation: " + "; ".join(gaps) + "."
    return base


def _classify_pause(entries: list[dict], root: Path) -> str:
    """Pick one of: fresh_session | mid_step | completed_step | dead_end |
    ctx_exhaustion | unknown."""
    if not entries:
        return "fresh_session"
    last = entries[-1]
    proto = (last.get("protocol") or last.get("protocol_name") or "").lower()
    status = last.get("status", "")
    # Recent handoff?
    handoffs = root / ".os_state" / "handoffs"
    if handoffs.exists():
        try:
            recent = sorted(
                handoffs.glob("handoff_*.md"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if recent:
                age = (
                    datetime.now(tz=timezone.utc).timestamp()
                    - recent[0].stat().st_mtime
                )
                if age < 7 * 24 * 3600:
                    return "ctx_exhaustion"
        except OSError:
            pass
    if status == "started":
        # (M3) distinguish a mid-roadmap pause from a mid-analysis-step pause so
        # boot advice can reconstruct the roadmap thread, not just say "resume".
        if "roadmap_execution" in proto or "deep_planning" in proto:
            return "mid_roadmap"
        return "mid_step"
    if "dead_end" in proto:
        return "dead_end"
    if status == "completed":
        return "completed_step"
    return "unknown"


def _boot_advice(
    pause: str,
    active_plan: dict | None,
    state: dict,
    cfg: dict,
    daemon_notes: dict | None = None,
    roadmap: dict | None = None,
) -> str:
    """One-line guidance the AI should follow next.

    Priority order (most urgent first):
      1. daemon BLOCK-level integrity issues — fix before anything (H1).
      2. an in-flight autonomous roadmap — re-enter it, don't restart (C2).
      3. an in-progress tactical plan.
      4. pause/resume signals, then the normal fresh/continue advice.
    """
    # (H1) Daemon found block-level problems — lead with them; the AI must not
    # build on a broken workspace just because the linear advice says "fresh".
    if daemon_notes and (daemon_notes.get("counts") or {}).get("block"):
        n = daemon_notes["counts"]["block"]
        return (
            f"\u26d4 The daemon found {n} BLOCK-level integrity issue(s). Run "
            "tool_structure_audit / tool_workspace_repair and resolve them "
            "BEFORE any other action (see sys_boot.daemon_notes)."
        )
    # (C2) An autonomous roadmap is in progress — re-enter the loop, don't let
    # the linear pipeline route the AI back to project_startup.
    if roadmap and roadmap.get("present") and roadmap.get("in_progress"):
        return (
            "An autonomous roadmap is in progress \u2014 re-load "
            "guidance/roadmap_execution and re-read inputs/research_plan.md "
            "before anything else; continue the loop from where it paused."
        )
    if active_plan and active_plan.get("status") == "in_progress":
        cur = active_plan.get("current_step", 1)
        total = len(active_plan.get("decomposition", []))
        return (
            f"Active plan from a previous turn exists "
            f"(step {cur}/{total}). Continue it before accepting a new ask."
        )
    if pause == "ctx_exhaustion":
        return "Recent handoff doc found — call tool_session_resume."
    if pause == "mid_roadmap":
        return (
            "Previous session paused mid-roadmap \u2014 re-load "
            "guidance/roadmap_execution + inputs/research_plan.md and resume."
        )
    if pause == "mid_step":
        return "Previous session left work in-flight — call tool_session_resume."
    if state.get("pipeline_stage", "init") == "init":
        return (
            "Fresh project. After the researcher's first message, call "
            "tool_route with their prompt to pick the right protocol."
        )
    return (
        "Wait for researcher's message, then call tool_route(prompt) before "
        "loading any protocol."
    )


def _boot_roadmap(root: Path, entries: list) -> dict:
    """(C2) Detect a durable autonomous roadmap (inputs/research_plan.md) and
    whether a roadmap loop is in flight, so sys_boot can point the AI back into
    it after a context reset. Fail-safe: absence → {present: False}."""
    try:
        plan_path = Path(root) / "inputs" / "research_plan.md"
        if not plan_path.exists():
            return {"present": False}
        # In-flight if the most recent protocol log entry is a plan-tier
        # protocol (deep_planning / roadmap_execution) that isn't completed.
        in_progress = False
        last_logged = None
        for e in reversed(entries or []):
            proto = (e.get("protocol") or e.get("protocol_name") or "")
            if not proto:
                continue
            last_logged = proto
            if "roadmap_execution" in proto or "deep_planning" in proto:
                in_progress = (e.get("status") or "").lower() != "completed"
            break
        return {
            "present": True,
            "path": "inputs/research_plan.md",
            "in_progress": in_progress,
            "last_logged_protocol": last_logged,
            "advice": (
                "An autonomous roadmap exists — re-read inputs/research_plan.md "
                "and re-load guidance/roadmap_execution to continue the loop."
            ),
        }
    except Exception:
        return {"present": False}



def _dep_inventory() -> dict:
    """Defer to server's missing-dep registry; degrade gracefully when isolated."""
    try:
        from research_os.server import _optional_dep_inventory  # type: ignore

        return _optional_dep_inventory()
    except Exception:
        return {"missing_count": 0, "missing": [], "advice": "unknown"}


# ---------------------------------------------------------------------------
# tool_route — prompt → routing decision
# ---------------------------------------------------------------------------

# Tools that are always available regardless of protocol — the AI's
# core navigation + bookkeeping vocabulary.
_ESSENTIAL_TOOLS = (
    "sys_boot",
    "tool_route",
    "tool_plan",
    "sys_protocol_get",
    "sys_state_get",
    "sys_file_read",
    "sys_file_list",
    "sys_notify",
    "sys_active_tools",
    "mem_log",
)


def _active_tools_for(
    primary_data: dict | None,
    shortcut_tool: str | None,
) -> list[str]:
    """Build the active tool shortlist tied to a chosen protocol.

    Returns essentials + every tool referenced in the protocol's
    decomposition + the shortcut tool (deduped, stable order).
    """
    out: list[str] = list(_ESSENTIAL_TOOLS)
    if shortcut_tool and shortcut_tool not in out:
        out.append(shortcut_tool)
    if primary_data:
        for entry in primary_data.get("decomposition", []) or []:
            if isinstance(entry, dict):
                t = entry.get("tool")
                if t and t not in out:
                    out.append(t)
    return out


def active_tools_for_protocol(protocol_name: str) -> dict[str, Any]:
    """Public lookup — given a protocol name, return its active-tool shortlist.

    Used by the standalone `sys_active_tools` MCP tool so the AI can fetch
    a protocol's tool scope without re-routing.
    """
    try:
        index = _load_index()
        protocols = index.get("protocols", {}) or {}
        data = protocols.get(protocol_name)
        if not data:
            return {
                "status": "error",
                "message": (
                    f"Unknown protocol `{protocol_name}`. "
                    "Call sys_protocol_list to browse."
                ),
            }
        tools = _active_tools_for(data, data.get("shortcut_tool"))
        return {
            "status": "success",
            "protocol": protocol_name,
            "intent_class": data.get("intent_class"),
            "sub_intent": data.get("sub_intent"),
            "shortcut_tool": data.get("shortcut_tool"),
            "active_tools": tools,
            "active_tools_count": len(tools),
            "advice": (
                "Prefer these tools while executing the protocol. Other "
                "tools remain reachable via sys_active_tools, but stay "
                "in this scope unless a step explicitly calls something "
                "outside it."
            ),
        }
    except Exception as e:
        logger.exception("active_tools_for_protocol failed")
        return {"status": "error", "message": str(e)}


_COMPLEXITY_TOKENS = (
    " and then ",
    " then ",
    " also ",
    " plus ",
    " after that ",
    " followed by ",
    " and audit ",
    " and write ",
    " and run ",
    " and check ",
    " ; ",
)


def route_request(
    prompt: str,
    root: Path,
    *,
    state_hint: dict | None = None,
    persist_plan: bool = True,
) -> dict[str, Any]:
    """Pick the right protocol via a HIERARCHICAL walk: L1 → L2 → L3.

    The router resolves to the deepest unambiguous level:
      * L1 ``intent_class`` (e.g. ``execute``, ``synthesize``)
      * L2 ``sub_intent``   (e.g. ``execute/new_experiment``,
                              ``synthesize/paper``)
      * L3 specific protocol (e.g. ``guidance/analysis_plan``)

    Resolution is greedy + ambiguity-aware. If the top L3 candidates are
    too close, the router returns ``resolved_level=2`` plus an
    ``ask_user`` line so the AI can disambiguate cheaply (a 1-sentence
    follow-up) instead of guessing wrong and loading the wrong YAML.

    Side effect (only when ``persist_plan=True`` AND complexity is high
    AND resolution made it to L3): writes ``.os_state/active_plan.json``.
    """
    try:
        if not isinstance(prompt, str):
            return {"status": "error", "message": "prompt must be a string"}
        if not prompt or not prompt.strip():
            return {"status": "error", "message": "empty prompt"}

        index = _load_index()
        protocols = index.get("protocols", {}) or {}
        shortcuts = index.get("shortcut_intents", {}) or {}
        hierarchy = index.get("hierarchy", {}) or {}

        # Normalise: lowercase, strip, pad with spaces, and turn common
        # punctuation into whitespace so triggers like " broken " can
        # still match prompts like "...broken, fix it...". Hyphens are
        # included so 'agent-based' == 'agent based' (triggers are
        # hyphen-collapsed on their side too — see _score_protocols).
        prompt_norm = _normalize_prompt(prompt)
        is_complex = _is_complex(prompt_norm)

        # Mode + shape signals — read once, used by both the semantic and
        # the trigger paths to bias scoring (build/* boost in tool_build
        # mode; workflow_shape tiebreak). Best-effort; default analysis /
        # no-shape so a missing config behaves exactly like today.
        workspace_mode = _read_workspace_mode(root)
        project_workflow_shape = _read_project_workflow_shape(root)

        # Quick-mode pre-check. If the prompt explicitly signals
        # throwaway / sanity-check / exploratory intent, short-circuit
        # the protocol load. Results write to workspace/scratch/, no
        # audits fire. Researcher can promote later via tool_promote_to_step.
        try:
            from research_os.tools.actions.state.quick_mode import quick_route
            qr = quick_route(root, prompt)
            if qr.get("is_quick"):
                quick_trigger = qr.get("matched_trigger")
                return {
                    "status": "success",
                    "resolved_level": 0,
                    "intent_class": "quick",
                    "sub_intent": None,
                    "primary_protocol": None,
                    "shortcut_tool": qr.get("recommended_tool"),
                    "decomposition": [],
                    "alternatives": [],
                    "ambiguous_alternatives": [],
                    "matched_triggers": [quick_trigger] if quick_trigger else [],
                    "why_matched": (
                        f"quick-mode trigger: {quick_trigger}"
                        if quick_trigger else "quick-mode (no explicit trigger)"
                    ),
                    "tier": None,
                    "tier_transition": _compute_route_transition(root, None),
                    "complexity": "quick",
                    "ask_user": None,
                    "why": qr.get("advice"),
                    "advice": qr.get("advice"),
                    "output_dir": qr.get("output_dir"),
                }
        except Exception:
            # Quick-mode is opt-in; fall back to normal routing on any error.
            pass

        # ── Step 0: cross-intent shortcut wins outright ───────────────
        # E.g. "what's the progress" → tool_progress_digest, no protocol
        # load needed regardless of class/sub-intent.
        shortcut_hit = _match_shortcut(prompt_norm, shortcuts)

        # ── Step 0.5: semantic route (PRIMARY path when available) ────
        # Try semantic first — much better fuzzy-intent matching than
        # trigger substrings as the catalog grows. Cross-intent shortcuts
        # still win if matched (researcher voice is more reliable than
        # embeddings for the rare "literal-trigger" path). Semantic also
        # bows out on low-confidence answers so the trigger router can
        # try a literal-phrase match.
        if not shortcut_hit:
            semantic_resp = _try_semantic_route(
                prompt, protocols, hierarchy, shortcuts,
                is_complex=is_complex, root=root, persist_plan=persist_plan,
                workspace_mode=workspace_mode,
                project_workflow_shape=project_workflow_shape,
            )
            if semantic_resp is not None:
                return semantic_resp

        # ── Step 1: score every protocol; group by (class, sub_intent) ─
        scored = _score_protocols(
            prompt_norm, protocols,
            workspace_mode=workspace_mode,
            project_workflow_shape=project_workflow_shape,
        )

        # state_hint bias: when the caller passes the AI's currently-active
        # phase (e.g. ``{"current_phase": "synthesize"}`` mid-paper), nudge
        # protocols in the matching intent_class up by 1 point. This is a
        # tie-breaker, not a winner-flipper — a real trigger match still
        # outranks a hint-only bias.
        if state_hint and isinstance(state_hint, dict) and scored:
            hint_phase = state_hint.get("current_phase")
            if isinstance(hint_phase, str) and hint_phase:
                phase_lc = hint_phase.strip().lower()
                for entry in scored:
                    cls = (entry["data"].get("intent_class") or "").lower()
                    if cls == phase_lc:
                        entry["score"] = int(entry.get("score", 0)) + 1
                scored.sort(key=lambda e: e.get("score", 0), reverse=True)

        # No matches at all and no shortcut.
        if not scored and not shortcut_hit:
            return _fallback_response(prompt_norm, hierarchy, is_complex, root)

        # ── Step 2: pick L1 winner (sum of scores per intent_class) ──
        # Threshold 1 at L1: multi-goal prompts often span classes, so
        # "strictly greater" is enough. L2 + L3 use the stricter 2.
        class_scores = _aggregate(scored, key="intent_class")
        if not class_scores and shortcut_hit:
            # Shortcut wins; package it as a degenerate L3 response.
            return _shortcut_response(shortcut_hit, root, prompt, is_complex,
                                       persist_plan)

        l1_winner, l1_alternatives = _resolve_level(class_scores, gap_threshold=1)

        # ── Step 3: pick L2 winner within the L1 class ────────────────
        subintent_scores = _aggregate(
            [s for s in scored if s["data"].get("intent_class") == l1_winner],
            key="sub_intent",
        )
        l2_winner, l2_alternatives = _resolve_level(
            subintent_scores, gap_threshold=2
        )

        # ── Step 4: pick L3 winner within (L1, L2) ────────────────────
        candidates_l3 = [
            s for s in scored
            if s["data"].get("intent_class") == l1_winner
            and s["data"].get("sub_intent") == l2_winner
        ]
        l3_winner = candidates_l3[0] if candidates_l3 else None
        l3_alternatives = candidates_l3[1:4]

        # Ambiguity check at L3: if the second candidate is within 2 of
        # the first, ask the user to disambiguate instead of guessing.
        l3_ambiguous = (
            len(candidates_l3) >= 2
            and (candidates_l3[0]["score"] - candidates_l3[1]["score"]) < 2
        )

        # ── CONFIDENCE-MARGIN GATE (cross-class, trigger path) ─────────
        # The L3 check above only catches near-ties WITHIN the chosen
        # (L1, L2) bucket. The more dangerous misroute is two protocols
        # in DIFFERENT intent_classes tying for the top — the L1
        # aggregate quietly picks one and the cross-class runner-up
        # vanishes. Detect that here on the *base* trigger score (before
        # the mode / shape thumb-on-the-scale, so an intentional build
        # boost doesn't read as an accidental tie) and surface a 2-named
        # ask_user. Only fires when the top match is NOT clearly
        # dominant: a multi-word trigger (base ≥ 4) beating a lone word
        # (base ≤ 2) is a comfortable margin and routes silently.
        cross_class_ambiguous = False
        cross_class_pair: list[dict] = []
        if not l3_ambiguous and not shortcut_hit and len(scored) >= 2:
            top0, top1 = scored[0], scored[1]
            cls0 = (top0["data"].get("intent_class") or "")
            cls1 = (top1["data"].get("intent_class") or "")
            base0 = top0.get("base_score", top0["score"])
            base1 = top1.get("base_score", top1["score"])
            if (
                cls0 and cls1 and cls0 != cls1
                and (base0 - base1) <= _TRIGGER_MARGIN_ASK
            ):
                cross_class_ambiguous = True
                cross_class_pair = [top0, top1]

        # Final resolved level.
        if not l1_winner:
            resolved_level = 0
        elif cross_class_ambiguous:
            # Genuinely split across intent_classes — drop to L2 so the AI
            # asks before loading a YAML.
            resolved_level = 2
        elif not l2_winner:
            resolved_level = 1
        elif not l3_winner or l3_ambiguous:
            resolved_level = 2
        else:
            resolved_level = 3

        # ── Build the response ────────────────────────────────────────
        primary_name = (
            l3_winner["name"]
            if l3_winner and not l3_ambiguous and not cross_class_ambiguous
            else None
        )
        primary_data = l3_winner["data"] if l3_winner else {}
        decomposition = primary_data.get("decomposition", []) or []

        # Prefer the cross-intent shortcut tool if one matched AND it's
        # consistent with the L1 winner (or stronger than the L3 match).
        shortcut_tool = None
        if shortcut_hit:
            shortcut_tool = shortcut_hit["tool"]
        elif primary_data and not cross_class_ambiguous:
            shortcut_tool = primary_data.get("shortcut_tool")

        # Ambiguity prompt for the AI to surface to the researcher.
        if cross_class_ambiguous:
            ask_user = _ask_user_cross_class(cross_class_pair)
        else:
            ask_user = _ask_user_for_level(
                resolved_level,
                hierarchy,
                l1_winner,
                l1_alternatives,
                l2_winner,
                l2_alternatives,
                candidates_l3 if l3_ambiguous else [],
            )

        # Build per-result `why_matched` for the primary + alternatives.
        primary_matched = (
            shortcut_hit["matched"] if shortcut_hit
            else (l3_winner["matched"] if l3_winner else [])
        )
        primary_why_matched = _format_why_matched(
            primary_matched, l1_winner, l3_winner["data"] if l3_winner else None,
        )
        alternatives_full = [
            {
                "name": c["name"],
                "score": int(c.get("score", 0)),
                "intent_class": (c.get("data") or {}).get("intent_class"),
                "why_matched": _format_why_matched(
                    c.get("matched", []),
                    (c.get("data") or {}).get("intent_class"),
                    c.get("data"),
                ),
            }
            for c in l3_alternatives[:3]
        ]

        tier = _resolve_tier(primary_name, primary_data) if primary_name else None
        tier_transition = _compute_route_transition(root, tier)
        response: dict[str, Any] = {
            "status": "success",
            "resolved_level": resolved_level,
            "intent_class": l1_winner,
            "sub_intent": l2_winner if resolved_level >= 2 else None,
            "primary_protocol": primary_name,
            "shortcut_tool": shortcut_tool,
            "decomposition": decomposition if resolved_level == 3 else [],
            "alternatives": alternatives_full,
            "ambiguous_alternatives": (
                [c["name"] for c in cross_class_pair]
                if cross_class_ambiguous
                else ([c["name"] for c in candidates_l3[:3]] if l3_ambiguous else [])
            ),
            "matched_triggers": primary_matched,
            "why_matched": primary_why_matched,
            "tier": tier,
            "tier_transition": tier_transition,
            "complexity": "high" if is_complex else "low",
            "ask_user": ask_user,
            "why": _why_hier(l1_winner, l2_winner, l3_winner, shortcut_hit),
            "advice": _route_advice_hier(
                resolved_level, is_complex, primary_name, shortcut_tool,
                bool(ask_user),
            ),
            "token_estimate": primary_data.get("token_estimate"),
            "active_tools": (
                _active_tools_for(primary_data, shortcut_tool)
                if resolved_level == 3
                else list(_ESSENTIAL_TOOLS)
            ),
            "method": "trigger",
        }

        # Persist plan ONLY when we resolved to L3 AND the prompt is
        # complex AND a decomposition exists. Ambiguous prompts never
        # persist a plan — the AI must disambiguate first.
        if (
            persist_plan
            and resolved_level == 3
            and is_complex
            and decomposition
        ):
            plan_path = _persist_active_plan(
                root, prompt, primary_name, decomposition, shortcut_tool,
            )
            response["active_plan_path"] = plan_path

        return response
    except Exception as e:
        logger.exception("route_request failed")
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Hierarchy helpers
# ---------------------------------------------------------------------------


def _aggregate(scored: list[dict], *, key: str) -> list[tuple[str, int]]:
    """Aggregate protocol scores by ``key`` (intent_class | sub_intent).

    Returns a list of (key_value, summed_score), sorted desc.
    """
    bag: dict[str, int] = {}
    for s in scored:
        v = s["data"].get(key)
        if not v:
            continue
        bag[v] = bag.get(v, 0) + s["score"]
    return sorted(bag.items(), key=lambda kv: kv[1], reverse=True)


def _resolve_level(
    aggregated: list[tuple[str, int]], *, gap_threshold: int = 2
) -> tuple[str | None, list[str]]:
    """Pick the winning value at a level, or report ambiguity.

    Returns (winner_or_none, top_alternatives). Winner is None when no
    entries are scored OR when the top two are within ``gap_threshold``.
    """
    if not aggregated:
        return None, []
    top, top_score = aggregated[0]
    alternatives = [k for k, _ in aggregated[1:4]]
    if len(aggregated) >= 2 and (top_score - aggregated[1][1]) < gap_threshold:
        return None, [top] + alternatives  # ambiguous — surface top + alts
    return top, alternatives


def _ask_user_for_level(
    resolved_level: int,
    hierarchy: dict,
    l1: str | None,
    l1_alts: list[str],
    l2: str | None,
    l2_alts: list[str],
    l3_candidates: list[dict],
) -> str | None:
    """When ambiguous, return a 1-sentence disambiguation prompt."""
    if resolved_level == 3:
        return None
    if resolved_level <= 1:
        # Ambiguous at intent_class.
        labels = [
            hierarchy.get(c, {}).get("label", c)
            for c in ([l1] if l1 else []) + l1_alts
            if c
        ]
        if not labels:
            return None
        return (
            "Your prompt could fit several work types: "
            f"{', '.join(labels[:3])}. Which one — pick the closest."
        )
    if resolved_level == 2:
        # L1 chosen; L2 ambiguous.
        if l3_candidates:
            opts = [c["data"].get("summary", c["name"]) for c in l3_candidates[:3]]
            return (
                f"Within `{l1}`, several protocols match: "
                + "; ".join(f"({i+1}) {o}" for i, o in enumerate(opts))
                + ". Which one?"
            )
        sub_labels = []
        if l1 and l1 in hierarchy:
            sub_map = hierarchy[l1].get("sub_intents", {}) or {}
            sub_labels = [
                f"{k} — {sub_map.get(k, '')}"
                for k in ([l2] if l2 else []) + l2_alts
                if k
            ]
        if not sub_labels:
            return None
        return (
            f"Within `{l1}`, possible sub-intents: "
            + "; ".join(sub_labels[:3])
            + ". Which one?"
        )
    return None


def _ask_user_cross_class(pair: list[dict]) -> str | None:
    """One-sentence disambiguation naming the two near-tied candidates.

    Fired by the confidence-margin gate when the top two protocols sit in
    different intent_classes within ``_TRIGGER_MARGIN_ASK`` of each other.
    Names both so the AI can ask a crisp follow-up instead of guessing.
    """
    if len(pair) < 2:
        return None
    a, b = pair[0], pair[1]
    a_sum = (a.get("data") or {}).get("summary") or a["name"]
    b_sum = (b.get("data") or {}).get("summary") or b["name"]
    return (
        "Your prompt matches two different kinds of work about equally: "
        f"(1) {a['name']} — {a_sum}; or (2) {b['name']} — {b_sum}. "
        "Which did you mean?"
    )


def _format_why_matched(
    matched: list,
    intent_class: str | None,
    protocol_data: dict | None = None,
) -> str:
    """One-line "why this matched" — trigger phrase + intent_class.

    Surfaces the *actual* trigger string that fired plus the intent class
    the protocol belongs to so the caller can decide whether to accept
    the route, ask the user, or override.
    """
    triggers = [str(t) for t in (matched or [])][:3]
    cls = intent_class or (
        (protocol_data or {}).get("intent_class") if protocol_data else None
    )
    if triggers and cls:
        return f"triggers: {', '.join(triggers)} · intent_class={cls}"
    if triggers:
        return f"triggers: {', '.join(triggers)}"
    if cls:
        return f"intent_class={cls} (no literal trigger; semantic-only)"
    return "no triggers; no intent_class"


def _why_hier(
    l1: str | None,
    l2: str | None,
    l3: dict | None,
    shortcut: dict | None,
) -> str:
    parts: list[str] = []
    if shortcut and shortcut.get("matched"):
        parts.append(
            f"Shortcut tool `{shortcut['tool']}` matched on "
            f"{', '.join(shortcut['matched'][:2])}"
        )
    if l1:
        parts.append(f"L1 intent_class=`{l1}`")
    if l2:
        parts.append(f"L2 sub_intent=`{l2}`")
    if l3:
        parts.append(
            f"L3 protocol=`{l3['name']}` (triggers: "
            f"{', '.join(l3['matched'][:2])})"
        )
    return " · ".join(parts) or "Best-effort match."


def _route_advice_hier(
    resolved_level: int,
    is_complex: bool,
    primary: str | None,
    shortcut_tool: str | None,
    has_ask_user: bool,
) -> str:
    if has_ask_user:
        return (
            "Ambiguous match — ask the researcher the `ask_user` "
            "question verbatim (one sentence), then re-call tool_route "
            "with their answer. Do NOT guess; do NOT load a YAML at "
            "format='full' to disambiguate — that's the expensive failure mode."
        )
    if is_complex and resolved_level == 3:
        return (
            "Prompt is complex — decomposition persisted to "
            ".os_state/active_plan.json. Call tool_plan(operation='turn') to "
            "size the batch to your model_profile, then walk via "
            "tool_plan(operation='advance') after each step. Never one-shot. "
            "If chat_split_recommended, sys_session_handoff + open a fresh chat."
        )
    if shortcut_tool and not primary:
        return (
            f"Single shortcut tool: `{shortcut_tool}`. Call it directly — "
            "no protocol load needed. After it returns, summarise the "
            "result to the researcher and wait for the next ask."
        )
    if primary:
        return (
            f"Load `{primary}` with sys_protocol_get format='summary' "
            "first (~300 tokens). Drill into a step with format='step' + "
            "step_id='<id>' when ready to execute. For the tool shortlist "
            f"of this protocol, call sys_active_tools(protocol_name='{primary}')."
        )
    return (
        "No clear match — call sys_protocol_next for the pipeline-recommended "
        "next protocol, sys_protocol_list to browse all 88, or sys_help "
        "(topic='categories') for a one-line summary per category."
    )


def _compute_route_transition(root: Path, new_tier: str | None) -> dict | None:
    """Best-effort tier-transition lookup; never raises out of the router."""
    try:
        from research_os.tools.actions.state.tier_state import compute_transition
        return compute_transition(root, new_tier)
    except Exception as exc:
        logger.debug("tier transition computation failed: %s", exc)
        return None


def _fallback_response(
    prompt_norm: str, hierarchy: dict, is_complex: bool, root: Path | None = None,
) -> dict:
    """When NOTHING matched, suggest the L1 classes as a menu + light heuristics.

    Adds a per-L1 short trigger hint so the researcher hears a concrete
    example of what each class accepts; cuts the AI's clarification round
    from two questions to one.
    """
    # Per-L1 short trigger hint — examples the AI can quote to the researcher.
    L1_EXAMPLES = {
        "session":     "'start session', 'pick up where we left off', 'going to lunch'",
        "discover":    "'fill the intake', 'i dropped new data', 'bringing this into RO'",
        "plan":        "'what should I do next', 'just poke at this'",
        "execute":     "'run a baseline', 'fit a model', 'dead end'",
        "methodology": "'which method should I use', 'design the evaluation', 'power analysis'",
        "literature":  "'literature search', 'systematic review', 'compare these papers'",
        "synthesize":  "'draft the paper', 'make a poster', 'build the dashboard', 'lay summary'",
        "audit_wrap":  "'audit the paper', 'is this ready to submit', 'reproducibility check'",
        "memory":      "'add hypothesis', 'add to glossary'",
        "review":      "'review this paper', 'review my code', 'critique this figure'",
    }
    menu_lines = []
    for cls, data in hierarchy.items():
        label = data.get("label", cls)
        ex = L1_EXAMPLES.get(cls, "")
        menu_lines.append(f"{cls} — {label}" + (f"  ({ex})" if ex else ""))
    # Detector-driven pack hint — the no-match case is exactly when a
    # domain pack is most likely the missing piece.
    field_signals: list[dict] = []
    field_hint = ""
    if root is not None:
        try:
            field_signals = _pack_signals_cached(root / "inputs")
        except Exception:
            field_signals = []
        if field_signals:
            top = field_signals[0]
            field_hint = (
                f"The project inputs look like '{top['pack']}' work — the "
                f"{top['pack']} pack may carry the right protocol "
                f"(sys_help(topic='packs'))."
            )
    return {
        "status": "success",
        "resolved_level": 0,
        "field_signals": field_signals,
        "intent_class": None,
        "sub_intent": None,
        "primary_protocol": None,
        "shortcut_tool": None,
        "decomposition": [],
        "alternatives": [],
        "ambiguous_alternatives": [],
        "matched_triggers": [],
        "why_matched": "No trigger or semantic match.",
        "tier": None,
        "tier_transition": (
            _compute_route_transition(root, None) if root is not None else None
        ),
        "complexity": "high" if is_complex else "low",
        "ask_user": (
            "I couldn't match your prompt to a protocol. Which best fits "
            "what you're after — start a session, intake new data, plan a "
            "next step, execute an experiment, pick a method, search the "
            "literature, write a deliverable, review someone else's work, "
            "or audit + wrap up?"
        ),
        "why": "No trigger matched any protocol or shortcut.",
        "advice": (
            "Ask the researcher the `ask_user` question, then re-call "
            "tool_route with their answer. If the prompt names a FIELD the "
            "menu doesn't obviously cover (economics, geoscience, law, a "
            "niche subfield), route to methodology/deep_domain_research — it "
            "surveys that field's canonical pipeline from the literature at "
            "any depth — or guidance/scope_clarification for a vague ask. "
            "Otherwise sys_help(topic='categories') maps the protocols and "
            "sys_protocol_next gives the pipeline-recommended next step. "
            + (field_hint + " " if field_hint else "")
            + "L1 classes (trigger hints in parens): "
            + " | ".join(menu_lines)
        ),
        "active_tools": list(_ESSENTIAL_TOOLS),
        "token_estimate": None,
    }


def _shortcut_response(
    shortcut_hit: dict,
    root: Path,
    prompt: str,
    is_complex: bool,
    persist_plan: bool,
) -> dict:
    """Wrap a clear shortcut-tool win as a degenerate L3 response."""
    decomposition = [
        {
            "tool": shortcut_hit["tool"],
            "purpose": "Shortcut intent match — no protocol load needed.",
        }
    ]
    response = {
        "status": "success",
        "resolved_level": 3,
        "intent_class": None,
        "sub_intent": None,
        "primary_protocol": None,
        "shortcut_tool": shortcut_hit["tool"],
        "decomposition": decomposition,
        "alternatives": [],
        "ambiguous_alternatives": [],
        "matched_triggers": shortcut_hit["matched"],
        "why_matched": (
            "Cross-intent shortcut on triggers: "
            f"{', '.join(str(t) for t in shortcut_hit['matched'][:3])}"
        ),
        "tier": None,
        "tier_transition": _compute_route_transition(root, None),
        "complexity": "high" if is_complex else "low",
        "ask_user": None,
        "why": (
            f"Cross-intent shortcut `{shortcut_hit['tool']}` matched on "
            f"{', '.join(shortcut_hit['matched'][:2])}"
        ),
        "advice": (
            f"Call `{shortcut_hit['tool']}` directly. No protocol load "
            "needed."
        ),
        "token_estimate": None,
        "active_tools": [*_ESSENTIAL_TOOLS, shortcut_hit["tool"]],
    }
    if persist_plan and is_complex:
        plan_path = _persist_active_plan(
            root, prompt, None, decomposition, shortcut_hit["tool"]
        )
        response["active_plan_path"] = plan_path
    return response


def _score_protocols(
    prompt_norm: str,
    protocols: dict,
    *,
    workspace_mode: str = "analysis",
    project_workflow_shape: str | None = None,
) -> list[dict]:
    """Score every protocol against the normalised prompt.

    Two additive biases on top of the raw trigger score:

      * MODE bias — when ``workspace_mode == 'tool_build'`` every build/*
        protocol gets ``_MODE_BUILD_BOOST`` so build-shaped prompts win
        over same-vocabulary analysis protocols. A thumb on the scale,
        not an override: it's only applied to protocols that ALREADY
        matched a trigger (score > 0), so an unrelated build protocol is
        never conjured out of nothing.
      * WORKFLOW-SHAPE tiebreak — a protocol whose body declares a
        ``workflow_shape`` overlapping the project's declared shape gets
        a tiny ``_WORKFLOW_SHAPE_BOOST``. Applied only to already-matched
        protocols; 'any'-shaped protocols are universal and skipped.

    Both biases are recorded on the entry (``mode_boost`` /
    ``shape_boost``) so the margin gate can reason about whether a near
    tie was created purely by a thumb-on-the-scale.
    """
    scored: list[dict] = []
    for name, data in protocols.items():
        if not isinstance(data, dict):
            continue
        score = 0
        matched: list[str] = []
        for trig in data.get("triggers", []) or []:
            # Collapse hyphens on the trigger side too so the prompt
            # (already hyphen-collapsed above) matches both spellings.
            trig_lc = _collapse_hyphens(str(trig).lower().strip())
            t = " " + trig_lc + " "
            if t in prompt_norm:
                # Multi-word triggers outrank single-word ones.
                weight = max(1, len(str(trig).split()))
                score += weight * 2
                matched.append(str(trig))
            elif len(trig_lc) >= _PARTIAL_MATCH_MIN_LEN and trig_lc in prompt_norm:
                # Partial match (substring inside a longer word). Gated by
                # a minimum length so short acronyms don't fire as
                # accidental substrings of unrelated words.
                score += 1
                matched.append(str(trig))
        if score <= 0:
            continue
        base_score = score
        # ── MODE bias (registry-driven) ───────────────────────────────
        # Each workspace mode boosts its NATIVE sub-intents (one source of
        # truth: MODE_ROUTING). analysis/hybrid have no entry → no boost.
        sub = data.get("sub_intent")
        mode_boost = _mode_boost_for(workspace_mode, sub)
        # ── WORKFLOW-SHAPE tiebreak ───────────────────────────────────
        shape_boost = 0
        if project_workflow_shape:
            shape = _protocol_workflow_shape(name)
            if shape and "any" not in shape and project_workflow_shape in shape:
                shape_boost = _WORKFLOW_SHAPE_BOOST
        score = base_score + mode_boost + shape_boost
        scored.append({
            "name": name,
            "data": data,
            "score": score,
            "base_score": base_score,
            "mode_boost": mode_boost,
            "shape_boost": shape_boost,
            "matched": matched,
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def _match_shortcut(prompt_norm: str, shortcuts: dict) -> dict | None:
    """Match cross-intent shortcuts that don't need a protocol load."""
    best = None
    best_score = 0
    for intent_id, data in shortcuts.items():
        if not isinstance(data, dict):
            continue
        matched: list[str] = []
        score = 0
        for trig in data.get("triggers", []) or []:
            t = " " + _collapse_hyphens(str(trig).lower().strip()) + " "
            if t in prompt_norm:
                score += max(1, len(str(trig).split())) * 2
                matched.append(str(trig))
        if score > best_score:
            best_score = score
            best = {
                "intent_id": intent_id,
                "tool": data.get("tool"),
                "matched": matched,
                "score": score,
            }
    return best


def _is_complex(prompt_norm: str) -> bool:
    """Decide whether a researcher prompt warrants persisted multi-step plan.

    Rules:
      * Word count > 18 (most "fit a model and write up the results"
        prompts fall just below 25, so we sit a bit lower).
      * Verb count ≥ 2 — anything with two distinct verbs should be
        planned.
      * Explicit deliverable-side phrases ("full project", "end to end",
        "from scratch", "everything", "wake me when") always trigger.
    """
    word_count = len(prompt_norm.split())
    if word_count > 18:
        return True
    if any(tok in prompt_norm for tok in _COMPLEXITY_TOKENS):
        return True
    deliverable_phrases = (
        "full project", "end to end", "end-to-end", "from scratch",
        "do everything", "do it all", "wake me when", "go autopilot",
        "ship it", "the whole thing",
    )
    if any(p in prompt_norm for p in deliverable_phrases):
        return True
    # multiple verb-style asks
    verbs = re.findall(
        r"\b(run|write|fit|audit|check|build|draft|make|render|"
        r"compile|verify|publish|generate|train|analyse|analyze|"
        r"refactor|review|design|model|simulate)\b",
        prompt_norm,
    )
    return len(verbs) >= 2


# ---------------------------------------------------------------------------
# Active plan persistence — anti one-shot
# ---------------------------------------------------------------------------


def _active_plan_path(root: Path) -> Path:
    return root / ".os_state" / _ACTIVE_PLAN_FILE


def _decomposition_removed_tool_warnings(decomposition: list) -> list[str]:
    """Return per-step warnings for decomposition entries that point at
    a hard-removed tool.

    The router is a fast-path that doesn't know the live tool catalogue;
    a stale `_router_index.yaml` decomposition or a hand-written one
    can list ``tool_synthesize`` / ``tool_dashboard`` / etc., which then
    waste a turn when the AI calls them and gets the friendly redirect.
    Logging the warning here means the AI sees it in the plan write
    result instead of the next dispatch turn.
    """
    try:
        from research_os.server.aliases import _REMOVED_TOOLS
    except Exception:  # pragma: no cover — defensive
        return []
    warnings: list[str] = []
    for idx, step in enumerate(decomposition or []):
        if not isinstance(step, dict):
            continue
        tool = step.get("tool")
        if tool and tool in _REMOVED_TOOLS:
            warnings.append(
                f"decomposition[{idx}].tool='{tool}' is hard-removed — "
                "the AI will burn a turn on the redirect. Update the "
                "router-index entry for the matched protocol."
            )
    return warnings


def _persist_active_plan(
    root: Path,
    prompt: str,
    primary_protocol: str | None,
    decomposition: list,
    shortcut_tool: str | None,
) -> str:
    plan = {
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "user_prompt": prompt,
        "primary_protocol": primary_protocol,
        "shortcut_tool": shortcut_tool,
        "decomposition": list(decomposition),
        "current_step": 1,
        "status": "in_progress",
    }
    removed_warnings = _decomposition_removed_tool_warnings(decomposition)
    if removed_warnings:
        plan["validation_warnings"] = removed_warnings
        for w in removed_warnings:
            logger.warning("active_plan write: %s", w)
    p = _active_plan_path(root)
    # Atomic write so an interrupted route can't truncate active_plan.json —
    # the very artefact that lets sys_boot recover the in-progress plan after
    # a crash.
    save_json_atomic(p, plan)
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def _load_active_plan(root: Path) -> dict | None:
    """Load the active plan, auto-archiving stale plans.

    A plan that hasn't been advanced in >7 days is almost certainly
    abandoned (researcher pivoted, AI session crashed). Auto-archive
    so it doesn't keep being surfaced in sys_boot as the active
    next-action — that bad signal misroutes fresh sessions.
    """
    p = _active_plan_path(root)
    if not p.exists():
        return None
    try:
        plan = json.loads(p.read_text())
    except Exception:
        return None
    # Staleness check.
    try:
        from datetime import datetime, timezone
        created = plan.get("created_at")
        if created:
            try:
                ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - ts).days
                if age_days > 7 and plan.get("status") == "in_progress":
                    # Move to handoffs/ as stale-N.json
                    archive_dir = root / ".os_state" / "handoffs"
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    stale_name = f"plan_stale_{age_days}d_{ts.strftime('%Y%m%d')}.json"
                    try:
                        p.rename(archive_dir / stale_name)
                    except OSError:
                        pass
                    return None
            except (ValueError, TypeError):
                pass
    except Exception:
        pass
    return plan


def advance_plan(root: Path, *, override_gate: bool = False) -> dict[str, Any]:
    """Mark the current step of the active plan complete + move to next.

    The AI calls this after finishing each decomposed step. When the plan
    runs out of steps the file is moved to ``.os_state/handoffs/`` so it's
    retrievable but stops blocking future routes.

    Anti-one-shot gate: if the step we're about to advance INTO is a
    final-deliverable tool (``tool_synthesize``, ``tool_dashboard_create``,
    ``tool_poster_create``, ``tool_latex_compile``), the per-step
    completeness audit runs first. If it returns BLOCKERS, advance_plan
    refuses unless the caller passes ``override_gate=true`` (or sets the
    plan's ``override_completeness_gate`` flag, useful when the researcher
    explicitly says "just give me the partial dashboard").
    """
    plan = _load_active_plan(root)
    if not plan:
        return {"status": "success", "message": "No active plan."}
    plan["current_step"] = int(plan.get("current_step", 1)) + 1
    decomposition = plan.get("decomposition", []) or []
    if plan["current_step"] > len(decomposition):
        plan["status"] = "completed"
        # Archive
        path = _active_plan_path(root)
        archive_dir = root / ".os_state" / "handoffs"
        archive_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        try:
            path.rename(archive_dir / f"plan_{ts}.json")
        except OSError:
            save_json_atomic(path, plan)
        return {"status": "success", "message": "Plan completed and archived."}
    next_step = decomposition[plan["current_step"] - 1]

    # ---- Anti-one-shot deliverable gate ----
    next_tool = (
        next_step.get("tool", "") if isinstance(next_step, dict) else ""
    )
    bypassed_blockers: list[str] = []
    if next_tool in DELIVERABLE_TOOLS:
        try:
            from research_os.tools.actions.audit.audit import audit_step_completeness

            gate = audit_step_completeness(root)
            # Only treat the gate as a completeness BLOCK when it returned a
            # non-empty `blockers` list (the genuine-incompleteness path).
            # audit_step_completeness ALSO returns status='error' for real
            # infrastructure failures ("workspace/ not found", "Step 'X' not
            # found") that carry no `blockers` — blocking on those would
            # report "0 blocker(s)" and "Full report: None", so let them fall
            # through to the normal advance below.
            if gate.get("status") == "error" and gate.get("blockers"):
                if override_gate or plan.get("override_completeness_gate"):
                    bypassed_blockers = list(gate.get("blockers", []))
                    if plan.get("override_completeness_gate"):
                        # Plan-persisted overrides need their own audit
                        # entry — the per-call handler only logs when it
                        # sees override_gate=true on THIS call.
                        try:
                            from research_os.project_ops import log_override
                            log_override(
                                root,
                                tool="tool_plan(operation='advance')",
                                gate="deliverable_completeness",
                                rationale="<plan-persisted override>",
                                extra={
                                    "next_tool": next_tool,
                                    "blocker_count": len(bypassed_blockers),
                                },
                            )
                        except Exception:
                            pass
                else:
                    return {
                        "status": "blocked",
                        "current_step": plan["current_step"] - 1,
                        "next_step": next_step,
                        "blockers": gate.get("blockers", []),
                        "advice": (
                            f"Cannot advance to `{next_tool}` — per-step "
                            "completeness audit found "
                            f"{len(gate.get('blockers', []))} blocker(s). "
                            "Resolve them or call advance_plan with "
                            "override_gate=true if the researcher "
                            "explicitly authorised a partial deliverable. "
                            f"Full report: {gate.get('report_path')}"
                        ),
                    }
            else:
                if gate.get("status") == "error" and not gate.get("blockers"):
                    logger.warning(
                        "plan_advance completeness gate errored (no blockers, "
                        "not a real block): %s",
                        gate.get("message"),
                    )
        except Exception as e:
            logger.warning("plan_advance gate check failed: %s", e)

    save_json_atomic(_active_plan_path(root), plan)
    result: dict[str, Any] = {
        "status": "success",
        "current_step": plan["current_step"],
        "next_step": next_step,
        "remaining": len(decomposition) - plan["current_step"] + 1,
    }
    if bypassed_blockers:
        result["bypassed_blockers"] = bypassed_blockers
    return result


def clear_active_plan(root: Path) -> dict[str, Any]:
    """Discard the active plan (researcher pivoted; old plan no longer applies)."""
    p = _active_plan_path(root)
    if not p.exists():
        return {"status": "success", "message": "No active plan to clear."}
    try:
        p.unlink()
    except OSError as e:
        return {"status": "error", "message": str(e)}
    return {"status": "success", "message": "Active plan cleared."}


# ---------------------------------------------------------------------------
# Per-turn batching — split a plan into bite-size chunks per AI turn
# ---------------------------------------------------------------------------

# How many decomposition steps a model can comfortably batch in one turn.
# Tuned to keep each turn under ~3-5K tokens of tool I/O.
_TURN_BUDGET = {
    "small":  1,   # one tool call per turn; confirm in between
    "medium": 3,   # standard
    "large":  6,   # can plan multi-step batches
}

# If a planned tool is known to be heavyweight, count it as more than 1
# step against the per-turn budget.
# Live deliverable-compile tools (drives the anti-one-shot completeness gate
# in advance_plan). Must stay free of aliases._REMOVED_TOOLS — a stale set
# naming removed deliverable tools made the gate silently never fire for
# Typst deliverables. A test guard enforces the no-drift invariant.
DELIVERABLE_TOOLS = frozenset({
    "tool_typst_compile",
    "tool_synthesis_scaffold",
})

_HEAVY_TOOLS = {
    "tool_typst_compile": 3,
    "tool_audit": 3,
    "tool_search": 2,
    "tool_synthesis_scaffold": 2,
}


def plan_turn(root: Path) -> dict[str, Any]:
    """Slice the active plan into a ``this_turn`` batch + ``next_turn`` queue.

    Reads:
      * ``.os_state/active_plan.json`` (set by tool_route)
      * researcher_config: ``model_profile`` (small | medium | large) and
        ``runtime.shared_server``.

    Returns:
      * ``this_turn``: list of decomposition entries to execute now
      * ``next_turn``: list of decomposition entries queued for later
      * ``chat_split_recommended``: True when batch size is small AND
        many turns remain — the AI should suggest the researcher start
        a fresh chat after writing a handoff.
      * ``model_profile``: which profile drove the budget
      * ``turn_budget``: budget used (steps per turn after weighting)

    When there is no active plan, returns ``status="success"`` with
    ``message="No active plan."`` (not an error — it just means the AI
    is free to act without a batched plan).
    """
    try:
        plan = _load_active_plan(root)
        if not plan:
            return {
                "status": "success",
                "message": "No active plan. tool_route a complex prompt to create one.",
                "this_turn": [],
                "next_turn": [],
            }

        decomposition = plan.get("decomposition", []) or []
        current = int(plan.get("current_step", 1))
        remaining = decomposition[current - 1:]
        if not remaining:
            return {
                "status": "success",
                "message": "Active plan exhausted — call tool_plan(operation='advance') to archive.",
                "this_turn": [],
                "next_turn": [],
            }

        # Resolve model profile from config (fallback medium).
        model_profile = _read_model_profile(root)
        budget = _TURN_BUDGET.get(model_profile, _TURN_BUDGET["medium"])

        # Greedy fill of this_turn until weighted budget is exhausted.
        this_turn: list[dict] = []
        used = 0
        idx = 0
        for entry in remaining:
            tool_name = (
                entry.get("tool") if isinstance(entry, dict) else None
            ) or ""
            weight = _HEAVY_TOOLS.get(tool_name, 1)
            if this_turn and (used + weight) > budget:
                break
            this_turn.append(entry)
            used += weight
            idx += 1

        next_turn = remaining[idx:]

        # Chat-split recommendation: heuristic
        # - small model with > 6 remaining steps → recommend
        # - any model with > 12 remaining steps → recommend
        # - any model with a heavyweight pending (synthesis / repro) AND
        #   ≥ 4 more steps after it → recommend
        chat_split = False
        chat_split_reason = ""
        if len(next_turn) > 6 and model_profile == "small":
            chat_split = True
            chat_split_reason = (
                "Small model with many planned steps remaining. Suggest "
                "a fresh chat after this batch to keep responses crisp."
            )
        elif len(next_turn) > 12:
            chat_split = True
            chat_split_reason = (
                f"{len(next_turn)} steps still queued after this batch. "
                "Suggest a fresh chat with a handoff doc to reset context."
            )
        else:
            # Heavy pending tool deep in the queue?
            for i, entry in enumerate(next_turn):
                tool_name = (
                    entry.get("tool") if isinstance(entry, dict) else None
                ) or ""
                if (
                    tool_name in _HEAVY_TOOLS
                    and _HEAVY_TOOLS[tool_name] >= 3
                    and len(next_turn) - i >= 4
                ):
                    chat_split = True
                    chat_split_reason = (
                        f"`{tool_name}` is heavyweight and there are still "
                        f"{len(next_turn) - i - 1} steps after it. Consider "
                        "a fresh chat once that step finishes."
                    )
                    break

        return {
            "status": "success",
            "this_turn": this_turn,
            "next_turn": next_turn,
            "model_profile": model_profile,
            "turn_budget": budget,
            "weighted_used": used,
            "remaining_after_this_turn": len(next_turn),
            "chat_split_recommended": chat_split,
            "chat_split_reason": chat_split_reason or None,
            "advice": (
                "Execute every entry in `this_turn` IN ORDER. After each "
                "one call tool_plan(operation='advance'). Once `this_turn` is "
                "done, either continue with tool_plan(operation='turn') (next "
                "batch) OR — if chat_split_recommended is true — call "
                "sys_session_handoff and tell the researcher to open a "
                "fresh chat with 'pick up where we left off'."
            ),
        }
    except Exception as e:
        logger.exception("plan_turn failed")
        return {"status": "error", "message": str(e)}


def _read_model_profile(root: Path) -> str:
    """Read researcher_config.model_profile; default medium on any failure."""
    try:
        from research_os.tools.actions.state.config import get_config

        cfg_res = get_config(root)
        if cfg_res.get("status") != "success":
            return "medium"
        cfg = cfg_res.get("config", {}) or {}
        # Honour the documented ai.model_profile location first (sys_boot reads
        # it there); fall back to the legacy top-level key. Without this, boot
        # could report "large" while plan batches were sized "medium".
        profile = (
            (cfg.get("ai", {}) or {}).get("model_profile")
            or cfg.get("model_profile")
            or "medium"
        )
        return profile if profile in _TURN_BUDGET else "medium"
    except Exception:
        return "medium"


__all__ = [
    "MODE_ROUTING", "_BUILD_SUB_INTENTS", "_EXPLORATION_SUB_INTENTS", "_EXPLORATION_BOOST",
    "_MODE_TO_SHAPE", "_MODE_TRANSITIONS", "mode_transition_spec", "_mode_boost_for",
    "_pack_signals_cached", "_resolve_tier", "_clear_tier_cache", "_load_index", "reload_index",
    "_read_workspace_mode", "_protocol_workflow_shape", "_read_project_workflow_shape",
    "_clear_workflow_shape_cache", "_normalize_prompt", "_try_semantic_route", "sys_boot",
    "_boot_active_persona", "_boot_new_context", "_boot_daemon_notes", "_boot_software_components",
    "_MODE_DIRECTIVES", "_boot_mode_info", "_boot_glossary_unfilled", "_config_reconcile_hint",
    "_classify_pause", "_boot_advice", "_boot_roadmap", "_dep_inventory", "_ESSENTIAL_TOOLS",
    "_active_tools_for", "active_tools_for_protocol", "_COMPLEXITY_TOKENS", "route_request",
    "_aggregate", "_resolve_level", "_ask_user_for_level", "_ask_user_cross_class",
    "_format_why_matched", "_why_hier", "_route_advice_hier", "_compute_route_transition",
    "_fallback_response", "_shortcut_response", "_score_protocols", "_match_shortcut",
    "_is_complex", "_active_plan_path", "_decomposition_removed_tool_warnings",
    "_persist_active_plan", "_load_active_plan", "advance_plan", "clear_active_plan",
    "_TURN_BUDGET", "DELIVERABLE_TOOLS", "_HEAVY_TOOLS", "plan_turn", "_read_model_profile"
]
