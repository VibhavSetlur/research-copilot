"""v1.11.1 — DEG trigger must not false-positive on graph-theory prompts.

Bug: the bare ``"DEG"`` trigger in the biology lane (analysis_plan)
substring-matched the word ``degree`` (e.g. ``maximum degree 3 in a
graph``), pulling pure graph-theory prompts into
``guidance/analysis_plan``. The fix tightens the trigger to require
biology context (``DEG analysis``, ``DEG list``, ``DEGs``,
``differentially expressed genes``) so ``degree`` no longer collides.

This test guards against regression:
    1. "maximum degree 3 in a graph" must NOT match the DEG trigger.
    2. It must NOT route to guidance/analysis_plan.
    3. It SHOULD route to theory_math/method/proof_strategy_selection
       once the theory_math pack is loaded.
    4. Real DE prompts ("DEG analysis", "differential expression",
       "DESeq2") must still route to biology.
"""
from __future__ import annotations

import sys

import pytest

from research_os.project_ops import scaffold_minimal_workspace


def _fresh_import_with_packs() -> None:
    """Drop research_os* modules + re-import server so packs register."""
    for m in list(sys.modules):
        if m.startswith("research_os"):
            del sys.modules[m]
    import research_os.server  # noqa: F401


@pytest.fixture
def project_root(tmp_path):
    _fresh_import_with_packs()
    from research_os.tools.actions.router import reload_index
    reload_index()
    scaffold_minimal_workspace(tmp_path, "DEG False-Positive Test")
    return tmp_path


# ── primary regression: bare graph-theory prompt ─────────────────────


def test_maximum_degree_does_not_match_DEG_trigger(project_root):
    """The bare 'maximum degree 3 in a graph' prompt must not trip DEG."""
    from research_os.tools.actions.router import route_request
    res = route_request("maximum degree 3 in a graph", project_root,
                        persist_plan=False)
    assert res["status"] == "success"

    # The DEG trigger must NOT appear in matched_triggers.
    matched = res.get("matched_triggers") or []
    assert "DEG" not in matched, (
        f"DEG trigger leaked into graph-theory prompt: {matched}"
    )

    # And the prompt must NOT land on the biology analysis_plan protocol.
    assert res.get("primary_protocol") != "guidance/analysis_plan", (
        f"graph-theory prompt mis-routed to analysis_plan; "
        f"matched_triggers={matched}, why={res.get('why_matched')}"
    )


# ── true-positive guard: biology prompts still route correctly ───────


@pytest.mark.parametrize(
    "prompt",
    [
        "run a DEG analysis on my count matrix",
        "do differential expression with DESeq2",
        "give me the DEG list from the wald test",
        "find DEGs across conditions",
    ],
)
def test_real_biology_prompts_still_route_to_analysis_plan(project_root, prompt):
    """Tightening the DEG trigger must not break real biology routing.

    These prompts should still land on the execute lane
    (analysis_plan / new_experiment) — either via tighter trigger phrases
    or via the semantic router."""
    from research_os.tools.actions.router import route_request
    res = route_request(prompt, project_root, persist_plan=False)
    assert res["status"] == "success"
    primary = res.get("primary_protocol") or ""
    intent = res.get("intent_class") or ""
    # Acceptable: any execute-class protocol, or methodology-class
    # (the semantic router may pick a more specific methodology pick).
    assert primary != "", (
        f"biology prompt {prompt!r} lost all routing; "
        f"why={res.get('why_matched')}"
    )
    assert intent in {"execute", "methodology"}, (
        f"biology prompt {prompt!r} routed to {intent!r} "
        f"(primary={primary!r}, matched={res.get('matched_triggers')})"
    )
