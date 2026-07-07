"""Read-only capabilities catalog — the agent front door.

Research-OS calls no LLM and has NO chat gateway. This module is the pure,
read-only orchestration behind ``GET /v1/capabilities``: one self-describing
snapshot an AI agent (Claude Code, Cursor, Hermes, a bare client) can fetch
to learn what tools + protocols exist, the project's research field, and the
freshness of recorded work — so it can reason over the MCP tools directly.

ARCHITECTURE NOTE (strangler-fig). This module lives in ``daemon/`` and reads
the engine's public seams (``TOOL_DEFINITIONS``, ``route_request``,
``PROTOCOLS_DIR``); the engine never imports it. No network, no mutation.
"""
from __future__ import annotations

from typing import Any


# ── tool schema bridge ───────────────────────────────────────────────


def _to_openai_tool(name: str, spec: dict) -> dict:
    """Convert a Research-OS TOOL_DEFINITIONS entry to OpenAI tool form."""
    desc = spec.get("short") or spec.get("description") or name
    schema = spec.get("inputSchema") or {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {"name": name, "description": str(desc)[:1024], "parameters": schema},
    }


def research_os_tools(limit: int | None = None) -> list[dict]:
    """All Research-OS tools as OpenAI tool schemas.

    Lazy import of the registry keeps the daemon import graph light and
    preserves the invariant that ``daemon/`` reads engine seams, not the
    other way round.
    """
    from research_os.server.registry import TOOL_DEFINITIONS

    items = sorted(TOOL_DEFINITIONS.items())
    if limit is not None:
        items = items[:limit]
    return [_to_openai_tool(n, s) for n, s in items if isinstance(s, dict)]


def _tool_catalog() -> dict[str, Any]:
    """Categorized inventory of engine tools — counts + names by category.

    Lazy-imports the registry (preserves the daemon->server import arrow).
    Gives an agent a map of the toolbox without dumping full schemas.
    """
    from research_os.server.registry import TOOL_DEFINITIONS

    by_cat: dict[str, list[str]] = {}
    for name, spec in sorted(TOOL_DEFINITIONS.items()):
        if not isinstance(spec, dict):
            continue
        cat = str(spec.get("category") or "uncategorized")
        by_cat.setdefault(cat, []).append(name)
    return {
        "total": sum(len(v) for v in by_cat.values()),
        "by_category": {k: len(v) for k, v in sorted(by_cat.items())},
        "names_by_category": by_cat,
    }


def _protocol_catalog() -> dict[str, Any]:
    """Counts of available reasoning protocols, grouped by category.

    Globs the engine's protocol directory directly (pure, no router calls).
    Skips ``_``-prefixed control files; the category is the protocol's parent
    directory name. Best-effort.
    """
    from research_os.tools.actions.protocol import PROTOCOLS_DIR

    by_cat: dict[str, int] = {}
    total = 0
    try:
        for yaml_file in PROTOCOLS_DIR.rglob("*.yaml"):
            if yaml_file.name.startswith("_"):
                continue
            rel = yaml_file.relative_to(PROTOCOLS_DIR)
            cat = rel.parts[0] if len(rel.parts) > 1 else "general"
            by_cat[cat] = by_cat.get(cat, 0) + 1
            total += 1
    except Exception:  # noqa: BLE001
        pass
    return {"total": total, "by_category": dict(sorted(by_cat.items()))}


def build_capabilities(daemon: Any, *, include_tool_schemas: bool = False) -> dict[str, Any]:
    """The agent front door — one self-describing snapshot of Research-OS.

    Pure, read-only orchestration over engine + daemon public surfaces (no
    network, no mutation, no LLM). Designed so any AI agent can issue a SINGLE
    GET and learn:

      * **identity**   — what Research-OS is + version + the daemon endpoints.
      * **field**      — the project's detected research domain + how it was
        inferred (so the agent orients to chemistry vs. history vs. ML).
      * **tools**      — a categorized inventory (counts + names; full OpenAI
        schemas only when ``include_tool_schemas`` is set, to stay cheap).
      * **protocols**  — how many reasoning scaffolds exist + their categories.
      * **work_state** — freshness of recorded results + recent run count, so
        the agent knows whether it's walking into fresh or stale work.

    Every section is best-effort and degrades to ``null``/notes rather than
    raising — orientation must never 500.
    """
    from research_os import __version__

    root = getattr(daemon, "root", None)
    out: dict[str, Any] = {
        "service": "research-os",
        "version": __version__,
        "root": str(root) if root else None,
        "available": root is not None,
        "tagline": (
            "A research operating system: protocol-guided reasoning, "
            "field-awareness, and provenance-tracked execution. RO is a "
            "passive tool provider — it calls no LLM; your IDE / AI client "
            "reasons over the tools it exposes over a single localhost daemon."
        ),
        "endpoints": {
            "capabilities": "GET /v1/capabilities",
            "state": "GET /v1/state",
            "domain": "GET /v1/domain",
            "orient": "GET /v1/orient",
            "workflows": "GET /v1/workflows",
            "sandbox": "GET /v1/sandbox",
            "runs": "GET /v1/runs",
            "lineage": "GET /v1/lineage",
            "staleness": "GET /v1/staleness",
            "rebuild_plan": "GET /v1/rebuild/plan",
        },
    }

    # 1. Field / domain.
    if root is not None:
        try:
            from .domains import detect

            dr = detect(root)
            out["field"] = {
                "id": dr.profile.id,
                "label": dr.profile.label,
                "confidence": round(dr.confidence, 3),
                "source": getattr(dr, "source", None),
                "languages": list(dr.profile.languages),
                "deliverables": list(dr.profile.artifacts),
            }
        except Exception:  # noqa: BLE001
            out["field"] = None

    # 2. Tools (categorized inventory; schemas optional).
    try:
        out["tools"] = _tool_catalog()
        if include_tool_schemas:
            out["tools"]["schemas"] = research_os_tools()
    except Exception:  # noqa: BLE001
        out["tools"] = None

    # 3. Protocols (counts by category).
    try:
        from research_os.tools.actions.router import route_request  # noqa: F401

        out["protocols"] = _protocol_catalog()
    except Exception:  # noqa: BLE001
        out["protocols"] = None

    # 4. Work state — freshness + recent runs.
    store = getattr(daemon, "runstore", None)
    if store is not None:
        try:
            from . import provenance as _prov
            from . import staleness as _stale

            manifests = store.recent_manifests(limit=200)
            ws: dict[str, Any] = {"recorded_results": len(manifests)}
            if manifests:
                verdict = _stale.assess(manifests, _prov.hash_fn_for_root(root))
                ws["fresh"] = verdict["counts"].get("fresh")
                ws["stale"] = verdict["counts"].get("stale")
            out["work_state"] = ws
        except Exception:  # noqa: BLE001
            out["work_state"] = None
    else:
        out["work_state"] = {"recorded_results": 0}

    return out
