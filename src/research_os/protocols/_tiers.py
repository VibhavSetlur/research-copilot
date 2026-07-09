"""Tier taxonomy for protocol routing.

Every protocol carries a ``tier:`` field (top-level YAML key) that places
it in the project lifecycle. ``tool_route`` echoes the resolved
protocol's tier on every successful match; ``tool_audit (scope='step', dimension='completeness')``
advances the workspace's ``current_tier`` when a step moves the project
across a tier boundary.

The tier taxonomy is intentionally narrow (7 buckets, ordered) — it's
about progress reporting + flow rules, not protocol search. The
existing ``intent_class`` (10 values) + ``sub_intent`` (60+ values)
remain the routing axes.

Tier order matters: ``TIER_INDEX`` returns 0..6 so callers can compute
forward / backward transitions cheaply (a backward transition is a
researcher pivoting, e.g. moving from ``synthesize`` back to
``execute`` to re-run a step).
"""

from __future__ import annotations

# Ordered tiers — index is the lifecycle position.
TIERS: list[str] = [
    "intake",      # bootstrap, project intake, research overview
    "plan",        # hypothesis, methodology, decomposition
    "execute",     # analysis, code, data steps
    "ground",      # literature gate, claim grounding
    "synthesize",  # paper, slides, poster, dashboard drafting
    "review",      # reviewer simulation, drafter loop, peer-review prep
    "finalize",    # cross-deliverable consistency, submission prep
]

# O(1) lookup of a tier's lifecycle position.
TIER_INDEX: dict[str, int] = {t: i for i, t in enumerate(TIERS)}


def is_valid_tier(tier: str | None) -> bool:
    """True iff ``tier`` is one of the 7 canonical tiers."""
    return isinstance(tier, str) and tier in TIER_INDEX


def tier_position(tier: str | None) -> int | None:
    """Return ``tier``'s lifecycle index, or None when unknown."""
    if not isinstance(tier, str):
        return None
    return TIER_INDEX.get(tier)


def compare_tiers(a: str | None, b: str | None) -> int | None:
    """Return ``index(b) - index(a)`` so positive = forward progress.

    Returns None when either input is not a valid tier.
    """
    pa = tier_position(a)
    pb = tier_position(b)
    if pa is None or pb is None:
        return None
    return pb - pa


# Inference table used by the backfill script + as a fallback when a
# protocol YAML hasn't been annotated yet. Maps (intent_class, sub_intent)
# tuples and bare intent_class values onto a tier. Intent_class-only
# entries match when no (class, sub_intent) override fires.
_INTENT_SUB_TIER: dict[tuple[str, str], str] = {
    # ── session — every session-management protocol lives at intake.
    ("session", "boot"): "intake",
    ("session", "resume"): "intake",
    ("session", "handoff"): "finalize",
    ("session", "collaborator"): "finalize",
    ("session", "autopilot"): "plan",
    ("session", "disagree"): "plan",
    # ── discover — project intake / mid-entry.
    ("discover", "intake"): "intake",
    ("discover", "mid_entry"): "intake",
    ("discover", "clarify"): "intake",
    # ── plan — next-step planning + casual exploration.
    ("plan", "next_step"): "plan",
    ("plan", "casual"): "plan",
    # ── execute — running steps + branching.
    ("execute", "new_experiment"): "execute",
    ("execute", "extend"): "execute",
    ("execute", "branch"): "execute",
    ("execute", "abandon"): "execute",
    # ── methodology — planning what to do.
    # All methodology sub-intents are PLAN-time decisions; even
    # methodology/consult is "advise me on a method" before commit.
    # ── literature — search vs grounding split.
    ("literature", "search"): "ground",
    ("literature", "systematic"): "ground",
    ("literature", "evidence_grade"): "ground",
    ("literature", "compare"): "ground",
    ("literature", "per_step_grounding"): "ground",
    # ── synthesize — drafting deliverables.
    # All synthesize sub-intents are SYNTHESIZE-tier except reviewer_sim
    # (which is review-tier) and venue / outline / cover_letter which sit
    # at synthesize (still drafting). end_matter + a11y also drafting.
    ("synthesize", "reviewer_sim"): "review",
    # ── audit_wrap — final-gate audits + submission prep.
    ("audit_wrap", "audit"): "review",
    ("audit_wrap", "repro"): "finalize",
    ("audit_wrap", "submission"): "finalize",
    # ── memory — hypothesis + glossary bookkeeping = plan-time scaffold.
    ("memory", "hypothesis"): "plan",
    ("memory", "glossary"): "plan",
    # ── review — review research artefacts (yours or theirs).
    ("review", "quick"): "review",
    ("review", "code"): "review",
    ("review", "respond"): "review",
    ("review", "figure"): "review",
}

# Bare intent_class fallback (used when no (class, sub) override matches).
_INTENT_TIER: dict[str, str] = {
    "session": "intake",
    "discover": "intake",
    "plan": "plan",
    "execute": "execute",
    "methodology": "plan",
    "literature": "ground",
    "synthesize": "synthesize",
    "audit_wrap": "review",
    "memory": "plan",
    "review": "review",
    "quick": "execute",
}

# Bare category fallback — when no intent_class is available we route by
# the protocol's directory category (audit/ literature/ methodology/ ...).
_CATEGORY_TIER: dict[str, str] = {
    "audit": "review",
    "domain": "intake",
    "guidance": "intake",
    "literature": "ground",
    "methodology": "plan",
    "reproducibility": "finalize",
    "synthesis": "synthesize",
    "visualization": "synthesize",
    "writing": "synthesize",
}


def infer_tier(
    *,
    intent_class: str | None = None,
    sub_intent: str | None = None,
    category: str | None = None,
    protocol_id: str | None = None,
) -> str:
    """Infer the tier for a protocol from its router-index metadata.

    Order of precedence:
      1. (intent_class, sub_intent) explicit override
      2. intent_class default
      3. category (folder) default
      4. last-resort ``plan`` (the safest default — won't trigger a
         tier_transition by itself)

    Protocol-id keyword overrides (``protocol_id``) cover the handful of
    boundary cases the (class, sub_intent) lookup can't disambiguate —
    e.g. ``research/claim_grounding`` (when added) jumps to ``ground``
    regardless of class.
    """
    # 1. Explicit (class, sub) override.
    if intent_class and sub_intent:
        hit = _INTENT_SUB_TIER.get((intent_class, sub_intent))
        if hit:
            return hit
    # 2. intent_class default.
    if intent_class and intent_class in _INTENT_TIER:
        return _INTENT_TIER[intent_class]
    # 3. category default.
    if category and category in _CATEGORY_TIER:
        return _CATEGORY_TIER[category]
    # 4. last-resort.
    return "plan"


__all__ = [
    "TIERS",
    "TIER_INDEX",
    "is_valid_tier",
    "tier_position",
    "compare_tiers",
    "infer_tier",
]
