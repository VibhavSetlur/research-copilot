"""Handlers — audit_core sub-domain.

Carved out of handlers/audit.py to stay under the 600-line ceiling.
"""
from __future__ import annotations

from .._handlers_runtime import *  # noqa: F401,F403

__all__ = [
    "_handle_tool_audit",
    "_handle_tool_audit_findings",
    "_handle_tool_audit_synthesis",
    "_handle_tool_audit_power",
    "_handle_tool_audit_assumptions",
    "_handle_tool_audit_figure",
    "_handle_tool_audit_citations",
    "_handle_tool_audit_reproducibility",
    "_handle_tool_audit_script_naming",
    "_handle_tool_audit_provenance_integrity",
    "_handle_tool_audit_figure_interactivity",
    "_handle_tool_audit_dashboard_content",
    "_handle_tool_audit_cliches",
    "_handle_tool_audit_figure_coverage",
    "_handle_tool_audit_cross_deliverable_consistency",
    "_handle_tool_audit_reviewer_responses",
    "_handle_tool_audit_step_completeness",
    "_handle_tool_audit_step_literature",
    "_handle_tool_audit_findings_query",
    "_handle_tool_audit_findings_diff",
    "_handle_tool_audit_findings_explain",
    "_handle_tool_audit_findings_timeline",
    "_handle_tool_audit_active_gates",
    "_handle_tool_audit_version_coherence",
    "_handle_tool_audit_figure_full",
    "_handle_tool_audit_code_quality",
    "_handle_tool_audit_prose",
    "_handle_tool_audit_claims",
    "_handle_tool_audit_evalue",
    "_handle_tool_audit_quality_full",
    "_handle_tool_audit_coherence",
    "_handle_tool_audit_tool_tests",
    "_handle_tool_audit_tool_git_hygiene",
    "_handle_tool_audit_tool_build",
    "_handle_tool_judge_score",
]

def _handle_tool_audit(name, arguments, root):
    """Unified audit dispatcher.

    Routes (scope, dimension) → the matching per-dimension handler.
    Every legacy ``tool_audit_*`` name is aliased to this entry point and
    has its scope+dimension injected via ``_ALIAS_PARAM_INJECTION``, so
    callers (researchers, scripts, protocols) using the older per-
    dimension names keep working unchanged.

    Special scope ``active_gates`` (no dimension required) introspects
    the live armed-gate state on this project — returns the per-gate
    counts (block/warn/info) by reading the cross-audit findings ledger,
    plus the static gate vocabulary so callers can see which gates have
    NEVER fired on this project vs which are actively emitting findings.
    """
    scope = arguments.get("scope")
    dimension = arguments.get("dimension")
    if (scope is not None and not isinstance(scope, str)) or (
        dimension is not None and not isinstance(dimension, str)
    ):
        return _text(_error(
            "tool_audit: scope and dimension must be strings. "
            "Use sys_help(topic='gates') for the (scope, dimension) gate vocabulary."
        ))
    if scope == "active_gates":
        return _handle_tool_audit_active_gates(name, arguments, root)
    if not scope or not dimension:
        return _text(_error(
            "tool_audit requires scope= and dimension=. "
            "Valid scopes: step | project | synthesis | tool | active_gates. "
            "Use sys_help(topic='gates') for the full (scope, dimension) gate vocabulary."
        ))
    handler_name = _AUDIT_DISPATCH.get((scope, dimension))
    if not handler_name:
        return _text(_error(
            f"tool_audit: unknown (scope='{scope}', dimension='{dimension}'). "
            "Use sys_help(topic='gates') for every valid (scope, dimension) combination."
        ))
    handler = globals().get(handler_name)
    if not callable(handler):
        return _text(_error(
            f"tool_audit: handler '{handler_name}' is not callable."
        ))
    return handler(name, arguments, root)


def _handle_tool_audit_findings(name, arguments, root):
    """Unified findings-ledger dispatcher (query | diff).

    Replaces the two per-operation tools (tool_audit_findings_query +
    tool_audit_findings_diff). Operation defaults to 'query' when the
    diff-specific timestamps are absent and the caller did not specify
    operation explicitly.
    """
    op = arguments.get("operation")
    if not op:
        # Infer: diff if both timestamps are present, else query.
        if arguments.get("timestamp_a") and arguments.get("timestamp_b"):
            op = "diff"
        else:
            op = "query"
    if op == "query":
        return _handle_tool_audit_findings_query(name, arguments, root)
    if op == "diff":
        return _handle_tool_audit_findings_diff(name, arguments, root)
    if op == "explain":
        return _handle_tool_audit_findings_explain(name, arguments, root)
    if op == "timeline":
        return _handle_tool_audit_findings_timeline(name, arguments, root)
    return _text(_error(
        f"tool_audit_findings: unknown operation '{op}'. "
        "Use operation='query', 'diff', 'explain', or 'timeline'."
    ))


def _handle_tool_audit_synthesis(name, arguments, root):
    from research_os.tools.actions.audit import audit_synthesis
    from research_os.project_ops import log_override, validate_override_rationale

    # reject thin override_rationale before the audit runs.
    override_no_pdfs = bool(arguments.get("override_no_pdfs", False))
    raw_rationale = arguments.get("override_rationale")
    if override_no_pdfs and raw_rationale:
        thin = validate_override_rationale(raw_rationale)
        if thin is not None:
            return _text(thin)

    res = audit_synthesis(
        arguments.get("paper_path", "synthesis/paper.md"),
        root,
        override_no_pdfs=override_no_pdfs,
        override_rationale=str(arguments.get("override_rationale", "")),
    )
    # Mirror the other six override gates in this file: when the bypass
    # is actually honoured by audit_synthesis (reflected in the result
    # via report["override_no_pdfs"]=True), append it to override_log.md
    # so pre_submission_checklist can surface the bypass.
    if res.get("override_no_pdfs"):
        try:
            log_override(
                root,
                tool="tool_audit_synthesis",
                gate="audit_synthesis_no_pdfs",
                rationale=str(arguments.get("override_rationale", "")),
            )
        except Exception as exc:  # pragma: no cover - logging best effort
            logger.debug("log_override(audit_synthesis_no_pdfs) failed: %s", exc)
    if res.get("status") != "error":
        return _text(_success(res))
    return _text(_error(res.get("message", "audit failed")))


def _handle_tool_audit_power(name, arguments, root):
    from research_os.tools.actions.audit import audit_power

    # The gate VERIFIES the AI recorded a power / sample-size justification;
    # it does not solve for power. So it needs only the file to check. Legacy
    # numeric args (effect_size/alpha/n/test/k_groups) are accepted and
    # ignored for back-compat — the numbers now live in the AI's record.
    filepath = arguments.get("filepath")
    if not filepath:
        return _text(_error(
            "dimension='power' requires filepath= pointing at your power / "
            "sample-size justification (test family, effect size + its "
            "source, alpha, n, target power, conclusion)."))
    res = audit_power(filepath, root)
    if res.get("status") != "error":
        return _text(_success(res))
    return _text(_error(res.get("message", "audit failed")))


def _handle_tool_audit_assumptions(name, arguments, root):
    from research_os.tools.actions.audit import audit_assumptions

    res = audit_assumptions(arguments["filepath"], root)
    if res.get("status") != "error":
        return _text(_success(res))
    return _text(_error(res.get("message", "audit failed")))


def _handle_tool_audit_figure(name, arguments, root):
    from research_os.tools.actions.audit import audit_figure

    res = audit_figure(arguments["filepath"], root)
    if res.get("status") != "error":
        return _text(_success(res))
    return _text(_error(res.get("message", "audit failed")))


def _handle_tool_audit_citations(name, arguments, root):
    from research_os.tools.actions.audit import audit_citations

    res = audit_citations(root)
    if res.get("status") != "error":
        return _text(_success(res))
    return _text(_error(res.get("message", "audit failed")))


def _handle_tool_audit_reproducibility(name, arguments, root):
    from research_os.tools.actions.audit import audit_reproducibility_full

    res = audit_reproducibility_full(root)
    if res.get("status") != "error":
        return _text(_success(res))
    return _text(_error(res.get("message", "audit failed")))


def _handle_tool_audit_script_naming(name, arguments, root):
    """Validate analysis-step script naming (<NN>[a-z]_<snake_name>_v<k>.<ext>).

    scope='step', dimension='script_naming'. Optional step_id audits one step;
    omitted audits every numbered step. The daemon also watches this via
    structure_audit, and tool_step_complete surfaces it as a completeness warning.
    """
    from research_os.tools.actions.audit.script_naming import audit_script_naming

    step_id = arguments.get("step_id")
    res = audit_script_naming(root, step_id=step_id)
    return _text(_success(res))


def _handle_tool_audit_provenance_integrity(name, arguments, root):
    """Re-hash recorded inputs/outputs and flag stale results (provenance drift).

    scope='step', dimension='provenance_integrity'. Optional step_id audits one
    step; omitted audits every numbered step. An output built from an input that
    has since changed is STALE. The daemon also watches this via structure_audit.
    """
    from research_os.tools.actions.state.provenance import (
        verify_provenance_integrity,
    )

    step_id = arguments.get("step_id")
    res = verify_provenance_integrity(Path(root), step_id=step_id)
    return _text(_success(res))


def _handle_tool_audit_figure_interactivity(name, arguments, root):
    from research_os.tools.actions.audit.figure_interactivity import (
        audit_figure_interactivity,
    )

    res = audit_figure_interactivity(
        root,
        strictness=arguments.get("strictness"),
        autogen=arguments.get("autogen"),
    )
    if res.get("status") == "error":
        return _text(_error(res.get("message", "audit_figure_interactivity failed")))
    return _text(_success(res))


def _handle_tool_audit_dashboard_content(name, arguments, root):
    from research_os.tools.actions.audit.dashboard_content import audit_dashboard_content
    from research_os.project_ops import log_override, validate_override_rationale

    override_requested = bool(arguments.get("override_dashboard_content_gate", False))
    rationale = arguments.get("override_rationale")
    # The bypass is logged + applied regardless of quality_gate_policy, so the
    # rationale is required whenever an override is requested — not only under
    # policy=enforce (AG-11; was silently logging rationale=None otherwise).
    if override_requested and (not rationale or not str(rationale).strip()):
        return _text(_error(
            "override_dashboard_content_gate=true requires override_rationale "
            "(a bypass is logged + applied regardless of quality_gate_policy)."
        ))
    if override_requested and rationale:
        thin = validate_override_rationale(rationale)
        if thin is not None:
            return _text(thin)
    res = audit_dashboard_content(
        root,
        dashboard_path=arguments.get("dashboard_path", "synthesis/dashboard.html"),
    )
    if res.get("blockers") and override_requested:
        log_override(
            root,
            tool="tool_audit_dashboard_content",
            gate="dashboard_content",
            rationale=rationale,
            extra={"blocker_count": len(res["blockers"])},
        )
        res["override_applied"] = True
        res["status"] = "success"
    return _text(_success(res))


def _handle_tool_audit_cliches(name, arguments, root):
    from research_os.tools.actions.audit.content_depth import audit_cliches

    return _text(_success(audit_cliches(
        arguments.get("paper_path", "synthesis/paper.md"),
        root,
    )))


def _handle_tool_audit_figure_coverage(name, arguments, root):
    from research_os.tools.actions.synthesis.curate import audit_figure_coverage

    root_path = Path(root)
    res = audit_figure_coverage(root_path)
    if res.get("status") == "error" and "blockers" in res:
        # Return as success-with-blockers so the audit aggregator can
        # surface them rather than treating the audit as a tool error.
        return _text(_success(res))
    if res.get("status") == "error":
        return _text(_error(res.get("message", "audit_figure_coverage failed")))
    return _text(_success(res))


def _handle_tool_audit_cross_deliverable_consistency(name, arguments, root):
    """Cross-deliverable consistency audit: 5 dimensions, override-aware."""
    from research_os.tools.actions.audit._base import write_audit_outputs
    from research_os.tools.actions.audit.cross_deliverable import (
        CrossDeliverableConsistencyAudit,
        audit_cross_deliverable_consistency,
    )
    from research_os.project_ops import log_override, validate_override_rationale

    override_requested = bool(arguments.get("override_cross_deliverable", False))
    rationale = arguments.get("override_rationale")
    # Require a rationale whenever an override is requested — regardless of
    # quality_gate_policy — so this gate matches its six siblings (the bypass is
    # logged + applied either way; policy never silently waived the rationale).
    if override_requested and (not rationale or not str(rationale).strip()):
        return _text(_error(
            "override_cross_deliverable=true requires override_rationale "
            "(a bypass is logged + applied regardless of quality_gate_policy)."
        ))
    if override_requested and rationale:
        thin = validate_override_rationale(rationale)
        if thin is not None:
            return _text(thin)

    res = audit_cross_deliverable_consistency(root)

    # AuditBase fan-out: emit structured AuditFindings to the
    # standard {gate}_audit.md + {gate}_audit.json + .audit_findings.jsonl
    # artefacts. Failure to write the audit-outputs artefacts must not
    # mask the legacy auditor's response — wrap in a guard.
    try:
        findings = CrossDeliverableConsistencyAudit().run(Path(root))
        write_audit_outputs(
            findings, "cross_deliverable_consistency", Path(root)
        )
    except Exception:  # pragma: no cover - defensive guard
        # F2.1: don't swallow silently — a broken ledger write means
        # findings_query / active_gates go silently empty. Log it so it's
        # diagnosable instead of invisible.
        logger.warning(
            "cross_deliverable_consistency ledger write failed", exc_info=True
        )

    if res.get("blockers") and override_requested:
        log_override(
            root,
            tool="tool_audit_cross_deliverable_consistency",
            gate="cross_deliverable_consistency",
            rationale=rationale,
            extra={
                "blocker_count": len(res["blockers"]),
                "deliverables_found": res.get("deliverables_found", []),
            },
        )
        res["override_applied"] = True
        res["status"] = "success"

    return _text(_success(res))


def _handle_tool_audit_reviewer_responses(name, arguments, root):
    from research_os.tools.actions.synthesis.reviewer import (
        audit_reviewer_responses,
    )
    res = audit_reviewer_responses(root)
    return _text(_success(res))


def _handle_tool_audit_step_completeness(name, arguments, root):
    from research_os.tools.actions.audit._base import write_audit_outputs
    from research_os.tools.actions.audit.audit import (
        StepCompletenessAudit,
        audit_step_completeness,
    )

    step_id = arguments.get("step_id")
    # Legacy procedural call produces workspace/logs/step_completeness.md
    # and is the source of truth for the response body that callers
    # (tool_synthesize, tool_path_finalize, tool_dashboard_create) consume.
    result = audit_step_completeness(root, step_id=step_id)

    # AuditBase fan-out: emit structured AuditFindings to the
    # standard {gate}_audit.md + {gate}_audit.json + .audit_findings.jsonl
    # artefacts. Failure to write the audit-outputs artefacts must not
    # mask the legacy auditor's response — wrap in a guard.
    try:
        findings = StepCompletenessAudit().run(root, step_id=step_id)
        write_audit_outputs(findings, "step_completeness", root)
    except Exception:  # pragma: no cover - defensive guard
        # F2.1: surface, don't swallow — a failed ledger write makes the
        # findings ledger an unreliable source of truth.
        logger.warning("step_completeness ledger write failed", exc_info=True)

    return _text(_success(result))


def _handle_tool_audit_step_literature(name, arguments, root):
    from research_os.tools.actions.audit.step_literature import audit_step_literature

    return _text(_success(audit_step_literature(
        root, step_id=arguments.get("step_id"),
    )))


def _handle_tool_audit_findings_query(name, arguments, root):
    """Filter the cross-audit findings ledger.

    Reads ``workspace/logs/.audit_findings.jsonl`` (latest snapshot per
    stable finding id), then filters by severity / dimension / step /
    since. Returns the list — does NOT mutate the ledger.
    """
    from research_os.tools.actions.audit.findings_query import (
        audit_findings_query,
    )

    res = audit_findings_query(
        Path(root),
        severity=arguments.get("severity"),
        dimension=arguments.get("dimension"),
        step=arguments.get("step"),
        since=arguments.get("since"),
    )
    return _text(_success(res))


def _handle_tool_audit_findings_diff(name, arguments, root):
    """Diff two snapshots of the findings ledger by stable id.

    Snapshots the ledger as of ``timestamp_a`` and ``timestamp_b`` (both
    ISO-8601), then reports findings added / resolved / changed between
    them. The structural diff ignores re-emission churn (generated_at +
    ro_version) so a finding that simply reruns is NOT reported as
    changed.
    """
    from research_os.tools.actions.audit.findings_query import (
        audit_findings_diff,
    )

    ts_a = arguments.get("timestamp_a")
    ts_b = arguments.get("timestamp_b")
    if not ts_a or not ts_b:
        return _text(_error(
            "tool_audit_findings_diff requires both timestamp_a and "
            "timestamp_b (ISO-8601 strings, e.g. '2026-06-05T12:00:00Z')."
        ))
    res = audit_findings_diff(Path(root), timestamp_a=ts_a, timestamp_b=ts_b)
    if res.get("status") == "error":
        return _text(_error(res.get("message", "audit_findings_diff failed")))
    return _text(_success(res))


def _handle_tool_audit_findings_explain(name, arguments, root):
    """Return the full chronological history of one finding id.

    Reads ``workspace/logs/.audit_findings.jsonl`` and emits every
    snapshot whose id matches, with no 160-char truncation on
    ``suggested_fix``. Designed for the AI to call after a synthesize
    BLOCK so it can see WHY the finding sticks (when it was first
    raised, when overridden, when re-raised).
    """
    from research_os.tools.actions.audit.findings_query import (
        audit_findings_explain,
    )

    finding_id = arguments.get("id")
    if not finding_id or not str(finding_id).strip():
        return _text(_error(
            "tool_audit_findings(operation='explain') requires id=... "
            "(the UUID of the finding to explain — copy it from a "
            "tool_audit_findings(operation='query') result or from the "
            "synthesize BLOCK error envelope's next_recommended_call)."
        ))
    res = audit_findings_explain(Path(root), finding_id=str(finding_id))
    if res.get("status") == "error":
        return _text(_error(res.get("message", "audit_findings_explain failed")))
    return _text(_success(res))


def _handle_tool_audit_findings_timeline(name, arguments, root):
    """Return the full append-only ledger in chronological order.

    Unlike operation='query' (latest snapshot per id), 'timeline' keeps
    every emission so long-context models can spot "this finding keeps
    coming back" + "researcher keeps overriding same gate" patterns.
    Optional gate_name / scope filters.
    """
    from research_os.tools.actions.audit.findings_query import (
        audit_findings_timeline,
    )

    res = audit_findings_timeline(
        Path(root),
        gate_name=arguments.get("gate_name"),
        scope=arguments.get("scope"),
    )
    return _text(_success(res))


def _handle_tool_audit_active_gates(name, arguments, root):
    """Introspect armed gates on this project.

    Reads the cross-audit findings ledger and returns:
      * ``gates`` — every distinct ``audit_name`` seen in the ledger,
        with per-severity counts (block/warn/info) and the most recent
        emission timestamp. This is the LIVE state ("what's currently
        emitting findings on this project").
      * ``known_gate_vocabulary`` — every gate the dispatch table can
        route to (``_AUDIT_DISPATCH`` keys), so callers can see which
        gates have never fired on this project vs which are armed.
      * ``ledger_path`` — workspace-relative path to the ledger.

    Read-only. Cheap. Useful before tool_synthesize so the AI can
    answer "what gates am I about to face?" without grepping audit code.
    """
    from research_os.tools.actions.audit.findings_query import (
        FINDINGS_JSONL_RELPATH,
        _load_jsonl_lines,
    )

    rows = _load_jsonl_lines(Path(root) / FINDINGS_JSONL_RELPATH)

    # Aggregate per-gate counts + last_emission.
    per_gate: dict[str, dict] = {}
    for row in rows:
        gate = row.get("audit_name")
        if not gate:
            continue
        entry = per_gate.setdefault(
            gate,
            {
                "audit_name": gate,
                "block": 0,
                "warn": 0,
                "info": 0,
                "total": 0,
                "last_emission": None,
            },
        )
        sev = row.get("severity")
        if sev in ("block", "warn", "info"):
            entry[sev] += 1
        entry["total"] += 1
        ts = row.get("generated_at")
        if ts and (entry["last_emission"] is None or ts > entry["last_emission"]):
            entry["last_emission"] = ts

    gates = sorted(per_gate.values(), key=lambda r: r["audit_name"])

    # Static gate vocabulary from the dispatch table — every (scope,
    # dimension) the dispatcher can route to. Lets the AI see the
    # difference between "never fired" and "actively armed".
    vocabulary = [
        {"scope": scope, "dimension": dim, "handler": handler}
        for (scope, dim), handler in sorted(_AUDIT_DISPATCH.items())
    ]

    return _text(_success({
        "gates": gates,
        "armed_gate_count": len(gates),
        "known_gate_vocabulary": vocabulary,
        "vocabulary_count": len(vocabulary),
        "ledger_path": str(FINDINGS_JSONL_RELPATH),
        "hint": (
            "Call sys_help(topic='gates') for the full gate vocabulary, "
            "autopilot floor list, and bypass shapes."
        ),
    }))


def _handle_tool_audit_version_coherence(name, arguments, root):
    from research_os.tools.actions.state.iteration import audit_version_coherence

    return _text(_success(audit_version_coherence(
        root, step_id=arguments.get("step_id"),
    )))


def _handle_tool_audit_figure_full(name, arguments, root):
    from research_os.tools.actions.viz import audit_figure_quality, audit_figure_style

    figure_path = arguments["figure_path"]
    technical = audit_figure_quality(figure_path, root)
    # If the figure doesn't exist the technical audit already reports it;
    # don't double-run the style audit on a missing file.
    if technical.get("status") == "error" and "not found" in str(technical.get("message", "")).lower():
        return _text(_success(technical))

    # 3.2.8: layer the design / style audit (colour, axis labels, caption
    # framing, aspect) on top of the technical audit (DPI, caption presence,
    # overlap) so figure_full delivers ONE verdict for the figure.
    style = audit_figure_style(figure_path, root)
    merged = dict(technical)
    merged["blockers"] = list(technical.get("blockers", [])) + list(style.get("blockers", []))
    merged["warnings"] = list(technical.get("warnings", [])) + list(style.get("warnings", []))
    merged["style_report"] = style.get("report", {})
    if merged["blockers"]:
        merged["status"] = "error"
        merged["message"] = f"{len(merged['blockers'])} blocker(s): " + "; ".join(merged["blockers"])
    elif merged["warnings"]:
        merged["status"] = "warning"
        merged["message"] = f"{len(merged['warnings'])} warning(s)."
    return _text(_success(merged))


def _handle_tool_audit_code_quality(name, arguments, root):
    from research_os.tools.actions.audit._base import write_audit_outputs
    from research_os.tools.actions.audit.code_quality import (
        CodeQualityAudit,
        audit_code_quality,
    )

    # Legacy report (preserves workspace/logs/code_quality.md byte-for-byte).
    legacy = audit_code_quality(
        root,
        step_id=arguments.get("step_id"),
        run_ruff=bool(arguments.get("run_ruff", True)),
        run_mypy=bool(arguments.get("run_mypy", False)),
    )

    # Structured artefacts (JSON + JSONL ledger) alongside the
    # legacy markdown. Re-running audit_code_quality is cheap and keeps
    # the two output paths trivially consistent; if that ever shows up
    # in a profile, lift the per_step walk out into a shared helper.
    findings = CodeQualityAudit().run(
        root,
        step_id=arguments.get("step_id"),
        run_ruff=bool(arguments.get("run_ruff", True)),
        run_mypy=bool(arguments.get("run_mypy", False)),
    )
    written = write_audit_outputs(findings, "code_quality", root)
    legacy["audit_findings"] = {
        "count": len(findings),
        "block": sum(1 for f in findings if f.severity == "block"),
        "warn": sum(1 for f in findings if f.severity == "warn"),
        "info": sum(1 for f in findings if f.severity == "info"),
        "json_path": str(written["json"].relative_to(root)),
        "jsonl_path": str(written["jsonl"].relative_to(root)),
    }
    return _text(_success(legacy))


def _handle_tool_audit_prose(name, arguments, root):
    from research_os.tools.actions.audit.prose_quality import audit_prose

    return _text(_success(audit_prose(
        root,
        targets=arguments.get("targets"),
        is_observational=arguments.get("is_observational"),
    )))


def _handle_tool_audit_claims(name, arguments, root):
    from research_os.tools.actions.audit._base import write_audit_outputs
    from research_os.tools.actions.audit.claim_grounding import (
        ClaimGroundingAudit,
        audit_claims,
    )

    target_path = arguments.get("target_path")
    tolerance = float(arguments.get("tolerance", 0.01))

    # Legacy procedural call produces workspace/logs/claim_grounding.md
    # and is the source of truth for the response body callers consume.
    result = audit_claims(root, target_path=target_path, tolerance=tolerance)

    # AuditBase fan-out: emit structured AuditFindings to the
    # standard {gate}_audit.md + {gate}_audit.json + .audit_findings.jsonl
    # artefacts. Failure to write the audit-outputs artefacts must not
    # mask the legacy auditor's response — wrap in a guard.
    try:
        findings = ClaimGroundingAudit().run(
            root, target_path=target_path, tolerance=tolerance
        )
        write_audit_outputs(findings, "claim_grounding", root)
    except Exception:  # pragma: no cover - defensive guard
        # F2.1: surface, don't swallow — a failed ledger write silently empties
        # the findings ledger that findings_query / active_gates depend on.
        # (This sibling was missed in the original F2.1 sweep.)
        logger.warning("claim_grounding ledger write failed", exc_info=True)

    return _text(_success(result))


def _handle_tool_audit_evalue(name, arguments, root):
    from research_os.tools.actions.audit.audit import audit_evalue

    def _num(v):
        return float(v) if v is not None else None

    # Coerce numeric args at the handler boundary — many MCP/LLM clients
    # stringify numbers, and compute_evalue does `> 1` / `< 1` comparisons
    # on the CI bounds. Without this, a stringified ci_lower/ci_upper raises
    # a raw TypeError out of the dispatcher instead of a clean envelope.
    try:
        rr = float(arguments["risk_ratio"])
        ci_lower = _num(arguments.get("ci_lower"))
        ci_upper = _num(arguments.get("ci_upper"))
    except (TypeError, ValueError, KeyError) as e:
        return _text(_error(
            "tool_audit(dimension='evalue') needs a numeric risk_ratio "
            "(and optional numeric ci_lower/ci_upper). "
            f"Could not parse: {e}. "
            "NEXT: pass risk_ratio=<float>, e.g. risk_ratio=2.0, "
            "ci_lower=1.5, ci_upper=2.5."
        ))
    return _text(_success(audit_evalue(
        rr, root, ci_lower=ci_lower, ci_upper=ci_upper,
        effect_measure=str(arguments.get("effect_measure", "rr")),
        rare_outcome=bool(arguments.get("rare_outcome", False)),
    )))


def _handle_tool_audit_quality_full(name, arguments, root):
    from research_os.tools.actions.audit._base import write_audit_outputs
    from research_os.tools.actions.audit.audit import (
        AuditMaster,
        audit_quality_full,
    )

    # 1) Legacy aggregator — writes workspace/logs/audit_master.md and
    # returns the dict shape MCP clients (and tool_synthesize) already
    # know how to read. The markdown format is pinned by snapshot test
    # and must stay byte-for-byte stable.
    legacy = audit_quality_full(
        root,
        target_path=arguments.get("target_path"),
        skip=arguments.get("skip"),
    )

    # 2) Structured findings — fan out to the writer so the
    # JSON companion + the cross-audit .audit_findings.jsonl ledger
    # pick up this run. Failures here must NEVER take the legacy
    # result down with them; the structured writer is best-effort and
    # supplementary.
    try:
        audit = AuditMaster()
        findings = audit.run(root, legacy_result=legacy)
        paths = write_audit_outputs(findings, audit.name, root)
        legacy["audit_master_v2"] = {
            "finding_count": len(findings),
            "json_path": str(paths["json"].relative_to(root)),
            "jsonl_path": str(paths["jsonl"].relative_to(root)),
            "md_path": str(paths["md"].relative_to(root)),
        }
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("audit_master v2 writer failed")
        legacy["audit_master_v2_error"] = str(exc)

    # 3) Phase 8 — attach a tier-based progress summary so the AI can
    # see where the project sits in the lifecycle without re-routing.
    try:
        legacy["tier_progress"] = _build_tier_progress(root)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("tier_progress build failed: %s", exc)

    return _text(_success(legacy))


def _handle_tool_audit_coherence(name, arguments, root):
    from research_os.tools.actions.audit.coherence import audit_coherence
    return _text(audit_coherence(
        root,
        paper_path=str(arguments.get("paper_path") or "synthesis/paper.md"),
    ))


# ── scope='tool' audit family (tool_build mode) ──────────────────────
# The tool_build analog of the analysis figure/literature/completeness
# gates. Each is mode-aware: a clean no-op (status='success', applicable=
# false) when workspace.mode != 'tool_build', so wiring them into the
# shared dispatch never fires them on classic analysis projects.


def _handle_tool_audit_tool_tests(name, arguments, root):
    from research_os.tools.actions.audit.tool_build_audit import audit_tool_tests

    return _text(_success(audit_tool_tests(root)))


def _handle_tool_audit_tool_git_hygiene(name, arguments, root):
    from research_os.tools.actions.audit.tool_build_audit import (
        audit_tool_git_hygiene,
    )

    return _text(_success(audit_tool_git_hygiene(root)))


def _handle_tool_audit_tool_build(name, arguments, root):
    from research_os.tools.actions.audit.tool_build_audit import audit_tool_build

    return _text(_success(audit_tool_build(root)))


def _handle_tool_judge_score(name, arguments, root):
    from research_os.tools.actions.audit.judge import score_work

    res = score_work(
        root,
        subject=str(arguments.get("subject", "")),
        dimensions=arguments.get("dimensions") or [],
        limitations=arguments.get("limitations") or [],
        improvements=arguments.get("improvements") or [],
        verdict=str(arguments.get("verdict", "")),
        goal=arguments.get("goal"),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "judge_score failed")))


HANDLERS = {
    "tool_audit": _handle_tool_audit,
}
