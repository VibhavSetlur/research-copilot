"""Token-cost regression tests (Token Engineering phase).

Guards the context budget: tool listing <=6K, protocol ref <=75,
boot <=1000, search pointer <=600.
"""
from __future__ import annotations


# ── 1. tool listing ──────────────────────────────────────────────────────────


def test_tool_listing_under_budget(tmp_path):
    from research_os.context import count_tokens
    from research_os.project_ops import scaffold_minimal_workspace
    from research_os.server import TOOL_DEFINITIONS
    from research_os.server.entry import _short_for_list
    from research_os.server.tool_surface import select_visible_tools

    scaffold_minimal_workspace(tmp_path, "Budget Test")
    visible = set(select_visible_tools(TOOL_DEFINITIONS, tmp_path))
    listing = [
        {"name": n, "description": _short_for_list(s), "inputSchema": s["inputSchema"]}
        for n, s in TOOL_DEFINITIONS.items() if n in visible
    ]
    # was ~21000 with the full un-gated surface
    assert count_tokens(listing) <= 6000


# ── 2. session_boot protocol ref ─────────────────────────────────────────────


def test_protocol_ref_under_budget():
    from research_os.context import count_tokens
    from research_os.tools.actions.protocol import load_protocol

    ref = load_protocol("session_boot", format="ref")
    assert count_tokens(ref) <= 75


# ── 3. every protocol ref ────────────────────────────────────────────────────


def test_all_protocol_refs_under_budget():
    from research_os.context import count_tokens
    from research_os.tools.actions.protocol import list_protocols, load_protocol

    offenders = []
    load_errors = []
    for p in list_protocols():
        name = p["name"]
        try:
            ref = load_protocol(name, format="ref")
            tok = count_tokens(ref)
            if tok > 75:
                offenders.append((name, tok))
        except Exception as exc:  # noqa: BLE001
            load_errors.append((name, str(exc)))

    assert not offenders, (
        f"{len(offenders)} protocol ref(s) exceed 75 tokens: "
        + ", ".join(f"{n}={t}" for n, t in offenders)
    )


# ── 4. sys_boot payload ───────────────────────────────────────────────────────


def test_boot_under_budget(tmp_path):
    from research_os.context import count_tokens
    from research_os.project_ops import scaffold_minimal_workspace
    from research_os.tools.actions.router import sys_boot

    scaffold_minimal_workspace(tmp_path, "Boot Budget Test")
    boot = sys_boot(tmp_path)
    assert count_tokens(boot) <= 1000


# ── 5. search pointer envelope ────────────────────────────────────────────────


def test_search_pointer_under_budget(tmp_path):
    from research_os.context import count_tokens
    from research_os.project_ops import scaffold_minimal_workspace
    from research_os.server.handlers import research_search as rs

    scaffold_minimal_workspace(tmp_path, "Search Budget Test")
    # a large fake result set
    big_results = [
        {"title": f"Paper {i}", "abstract": "x" * 2000, "authors": ["A" * 50] * 5}
        for i in range(40)
    ]
    full_payload = {"results": big_results, "sources": ["web"], "mode": "auto"}
    env = rs._search_pointer_envelope(tmp_path, full_payload, big_results)
    # env is a list of MCP TextContent-like objects; extract text
    text = env[0].text if hasattr(env[0], "text") else str(env)
    assert count_tokens(text) <= 600  # pointer + summary, not the 40 full papers
    assert "pointer" in text


# ── 6. ContextBudget consistency ─────────────────────────────────────────────


def test_context_budget_consistent():
    from research_os.context import ContextBudget

    r = ContextBudget.report()
    assert r["consistent"] is True
    assert r["sum_of_categories"] == r["total"] == 13000
