"""Project orientation — the "standup" endpoint (v4 improvement pass).

`/v1/capabilities` answers *"what can this system do?"*. This module answers
the other half an agent (or a researcher returning tomorrow) needs before
doing anything: **"where are we, and what should I do next?"**

It is a pure, read-only *synthesis* layer over data that already exists —
the detected research field (Phase 1.16), the durable run journal
(Phase 1.x), and the staleness assessment over the lineage DAG
(Phase 1.14). It stores nothing new. The single highest-leverage
ergonomics win for cross-session / cross-agent continuity: hand any caller
a short human-readable brief plus ONE concrete recommended next action,
composed from the same primitives the CLI and HTTP surface already expose.

Like the rest of the daemon it does pure orchestration over engine +
daemon public surfaces with **no top-level imports of the reasoning
layer** — heavy/optional pieces are imported lazily inside functions so
the strangler-fig invariant (reasoning layer never depends on daemon, and
daemon never drags reasoning into import time) holds.
"""
from __future__ import annotations

from typing import Any


def _safe(fn, default):
    """Run a best-effort section; never let orientation 500."""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return default


def _field_summary(root: Any) -> dict:
    """Detected research field (best-effort)."""
    from .domains import detect

    result = detect(root)
    out = result.as_dict()
    profile = out.get("profile") or {}
    return {
        "label": profile.get("label") or profile.get("id"),
        "id": profile.get("id"),
        "confidence": out.get("confidence"),
        "source": out.get("source"),
    }


def _runs_summary(store: Any, *, limit: int) -> dict:
    """Recent run journal activity (counts + the newest few)."""
    runs = store.list_runs(limit=limit)
    by_status: dict[str, int] = {}
    for r in runs:
        st = r.get("status") or "unknown"
        by_status[st] = by_status.get(st, 0) + 1
    recent = [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "kind": r.get("kind"),
            "status": r.get("status"),
            "finished_at": r.get("finished_at"),
            "returncode": r.get("returncode"),
        }
        for r in runs[:5]
    ]
    return {"total": len(runs), "by_status": by_status, "recent": recent}


def _freshness_summary(store: Any, root: Any) -> dict:
    """Fresh/stale split + the dependency-ordered rebuild plan, if any."""
    from . import provenance as _prov
    from . import staleness as _stale
    from .lineage import build_lineage, topo_order

    manifests = store.recent_manifests(limit=200)
    hash_file = _prov.hash_fn_for_root(root)
    report = _stale.assess(manifests, hash_file)
    stale_ids = set(report.get("stale") or [])
    plan: list = []
    if stale_ids:
        plan = topo_order(build_lineage(manifests), stale_ids)
    counts = report.get("counts") or {}
    return {
        "counts": counts,
        "stale": sorted(stale_ids),
        "rebuild_plan": plan,
    }


def _recommend(field: dict, runs: dict, freshness: dict) -> dict:
    """Derive ONE concrete next action from the synthesized state.

    Deliberately a small, transparent decision tree — not a model call.
    The point is a *defensible default* the agent/researcher can act on or
    override, in priority order:

      1. Stale results exist        -> rebuild them (gives the exact plan).
      2. A run was interrupted       -> the daemon died mid-run (e.g. you
                                        walked away and the box rebooted);
                                        re-run it so the work completes.
      3. A run failed last          -> investigate the failure.
      4. No runs recorded yet       -> record the first result.
      5. Everything fresh           -> proceed with new analysis.
    """
    stale = freshness.get("stale") or []
    plan = freshness.get("rebuild_plan") or []
    if stale:
        head = plan[:5]
        return {
            "action": "rebuild_stale",
            "why": (
                f"{len(stale)} recorded result(s) were built from inputs that "
                "have since changed; downstream conclusions may be invalid."
            ),
            "how": "research-os daemon rebuild   (or POST /v1/rebuild once auth is on)",
            "targets": head,
            "priority": "high",
        }
    by_status = runs.get("by_status") or {}
    interrupted = by_status.get("interrupted", 0)
    if interrupted:
        # A run that was non-terminal when the daemon died (crash, reboot, or
        # the user closed a long job's box and walked away) is rehydrated as
        # INTERRUPTED on the next start. Surface it FIRST among run states: the
        # work never finished, so a returning researcher's most useful next
        # move is to resume/re-run it before building on a partial result.
        return {
            "action": "resume_interrupted",
            "why": (
                f"{interrupted} run(s) were interrupted (the daemon stopped "
                "mid-run \u2014 e.g. the machine rebooted while you were away). "
                "Their work did not complete and may have left partial output."
            ),
            "how": (
                "inspect: research-os runs   (GET /v1/runs?status=interrupted), "
                "then RESUME it (POST /v1/runs/<id>/resume) to continue from its "
                "recorded spec \\u2014 checkpoint-aware jobs pick up where they "
                "left off; otherwise re-run the affected step cleanly"
            ),
            "priority": "high",
        }
    failed = by_status.get("failed", 0) + by_status.get("error", 0)
    if failed:
        return {
            "action": "investigate_failure",
            "why": f"{failed} recent run(s) failed; resolve before building on them.",
            "how": "inspect logs: GET /v1/runs/<id>/log  (or research-os runs)",
            "priority": "high",
        }
    if runs.get("total", 0) == 0:
        label = field.get("label") or "this project"
        return {
            "action": "record_first_result",
            "why": (
                f"No results recorded yet for {label}. Recording results is what "
                "unlocks provenance, reproducibility, and staleness tracking."
            ),
            "how": "run an analysis (tool_python_exec / tool_bash_exec), or mem_result_record a finding",
            "priority": "normal",
        }
    return {
        "action": "proceed",
        "why": "All recorded results are fresh; no rebuilds or failures pending.",
        "how": "continue with the next analysis step for your research question",
        "priority": "normal",
    }


def _narrative(field: dict, runs: dict, freshness: dict, available: bool) -> str:
    """One short paragraph a human can read at a glance."""
    if not available:
        label = field.get("label")
        head = (
            f"This is a {label} project. " if label else ""
        )
        return (
            head
            + "No run journal is initialized yet, so there is no recorded work to "
            "summarize. Record a result to start tracking provenance and freshness."
        )
    label = field.get("label") or "research"
    total = runs.get("total", 0)
    counts = freshness.get("counts") or {}
    fresh = counts.get("fresh", 0)
    stale = counts.get("stale", 0)
    bits = [f"This is a {label} project with {total} recorded run(s)"]
    if total:
        bits.append(f"{fresh} fresh and {stale} stale by current inputs")
    sentence = "; ".join(bits) + "."
    if stale:
        sentence += (
            f" {stale} result(s) are out of date and should be rebuilt before "
            "drawing further conclusions."
        )
    elif total:
        sentence += " Everything recorded is up to date."
    return sentence


def build_orientation(daemon: Any, *, root: Any = None, limit: int = 50) -> dict:
    """Compose the project orientation brief.

    ``daemon`` is the running Daemon (or a per-root workspace). ``root``
    overrides the workspace to orient (multi-project daemon). All sections
    are best-effort: a missing journal yields ``available=False`` with the
    field + recommendation still populated, never an error.
    """
    resolved_root = root or getattr(daemon, "root", None)

    # Resolve the run journal for this root (override or daemon default).
    store = None
    if root is not None:
        reg = getattr(daemon, "registry", None)
        ws = None
        if reg is not None:
            ws = reg.get(str(root)) or reg.register(str(root))
        store = getattr(ws, "runstore", None) if ws is not None else None
    else:
        store = getattr(daemon, "runstore", None)

    field = _safe(lambda: _field_summary(resolved_root), {})
    # The execution bound the researcher declared (if any) — so the brief
    # tells the AI what compute/memory ceiling its runs sit under.
    budget = _safe(lambda: _budget_summary(resolved_root), {"configured": False})

    if store is None:
        recommendation = _recommend(field, {"total": 0, "by_status": {}}, {})
        return {
            "service": "research-os",
            "root": str(resolved_root) if resolved_root else None,
            "available": False,
            "field": field,
            "work": {"total": 0, "by_status": {}, "recent": []},
            "freshness": {"counts": {}, "stale": [], "rebuild_plan": []},
            "budget": budget,
            "narrative": _narrative(field, {"total": 0}, {}, available=False),
            "recommended_next_action": recommendation,
        }

    runs = _safe(lambda: _runs_summary(store, limit=limit),
                 {"total": 0, "by_status": {}, "recent": []})
    freshness = _safe(lambda: _freshness_summary(store, resolved_root),
                      {"counts": {}, "stale": [], "rebuild_plan": []})
    recommendation = _recommend(field, runs, freshness)

    return {
        "service": "research-os",
        "root": str(resolved_root) if resolved_root else None,
        "available": True,
        "field": field,
        "work": runs,
        "freshness": freshness,
        "budget": budget,
        "narrative": _narrative(field, runs, freshness, available=True),
        "recommended_next_action": recommendation,
    }


def _budget_summary(root: Any) -> dict:
    """The declared resource budget for this project (or 'not configured')."""
    if not root:
        return {"configured": False}
    from . import resource_budget as _budget

    return _budget.budget_summary(root)
