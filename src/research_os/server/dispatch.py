"""Tool-call dispatcher: alias resolution, deprecation logging, param injection.

This module owns the request-routing pipeline:
    name → canonical_input (dots→underscores)
         → resolved (alias lookup)
         → optional param injection (legacy alias → consolidated kwargs)
         → handler dispatch

Errors from any handler are caught and converted into an error envelope.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .aliases import (
    _ALIAS_PARAM_INJECTION,
    _ALIASES,
    _DEPRECATED_ALIASES,
    _REMOVED_TOOLS,
)
from .autopilot_gate import enforce_autopilot_gate
from .envelopes import TextContent, _error, _normalize_envelope, _success, _text
from .errors import RoError, did_you_mean
from .plugin_registry import plugin_registry
from .rate_limiter import _rate_limiter


logger = logging.getLogger("research-os.server")

# ── Exec-category set (mirrors tool_surface._EXEC_CATEGORIES) ────────────────
_EXEC_CATEGORIES: frozenset[str] = frozenset({"execution", "exec"})


def _is_exec_tool(tool_name: str) -> bool:
    """Return True when ``tool_name`` is in the execution/exec category.

    Reads the live TOOL_DEFINITIONS at call time (deferred import avoids
    circular load).  Fail-safe: returns False on any error so an exec tool
    with a missing definition is NOT blocked.
    """
    try:
        from .registry import TOOL_DEFINITIONS

        return TOOL_DEFINITIONS.get(tool_name, {}).get("category") in _EXEC_CATEGORIES
    except Exception:
        return False


def _enforce_persona_policy(
    resolved: str,
    root: "Path | None",
) -> "list | None":
    """Check the active persona's execution policy for ``resolved``.

    Returns a ``list[TextContent]`` refusal / park envelope when the policy
    blocks the tool, or ``None`` when the handler should run normally.

    Only acts on exec-category tools; all other tools are always allowed.
    Fail-open: returns ``None`` (allow) on any error.
    """
    if not _is_exec_tool(resolved):
        return None
    if root is None:
        return None

    try:
        from .personas import PERSONAS, get_active_persona

        active = get_active_persona(root)
        persona = PERSONAS.get(active, PERSONAS["scruffy"])
        policy = persona.get("execution_policy", "direct")
    except Exception:
        return None  # degrade open

    if policy == "direct":
        return None  # scruffy — run freely

    if policy == "forbidden":
        # critique persona: refuse exec tools outright.
        return _text(_error(
            what=f"tool '{resolved}' is forbidden in persona 'critique'",
            why=(
                "the active persona is 'critique' (peer reviewer), which only "
                "permits read operations; exec tools are blocked"
            ),
            next_action=(
                "switch persona with sys_mode(persona='scruffy') to run tools, "
                "or call sys_mode() to see available personas"
            ),
        ))

    if policy == "supervised":
        # delegation persona: park the execution on a HITL gate.
        # Write gate file via daemon_bridge.state_path (seam-safe).
        try:
            import uuid
            from datetime import datetime, timezone

            from .daemon_bridge import GATES_DIR, state_path

            gate_id = str(uuid.uuid4())
            created_at = (
                datetime.now(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )
            gate_payload = {
                "id": gate_id,
                "question": (
                    f"delegation persona: approve execution of '{resolved}'?"
                ),
                "status": "pending",
                "created_at": created_at,
                "root": str(root),
                "tool": resolved,
                "protocol_id": None,
                "step_id": None,
                "decision": None,
                "resolved_at": None,
            }
            gate_dir = state_path(root, GATES_DIR)
            gate_dir.mkdir(parents=True, exist_ok=True)
            gate_file = gate_dir / f"{gate_id}.json"
            gate_file.write_text(
                json.dumps(gate_payload, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug("persona gate-write failed: %s", exc)
            gate_id = "unknown"
            gate_file = None

        return _text(_success({
            "status": "parked",
            "persona": "delegation",
            "tool": resolved,
            "gate_id": gate_id,
            "message": (
                f"Tool '{resolved}' is parked on HITL gate '{gate_id}' "
                "because the active persona is 'delegation' (supervised execution). "
                "A supervisor must approve the gate before the tool runs."
            ),
            "gate_file": str(gate_file) if gate_file else None,
        }))

    if policy == "verified":
        # neat persona: allow the tool to run, but tag the run for the audit gate.
        # We return None here (handler runs) and tag after the handler call.
        # The tagging is done by _tag_verified_run called from _handle_tool_call.
        # Flag by returning a sentinel tuple so the dispatcher can distinguish.
        # Actually: we return None to let handler run; tagging is a post-hook.
        # We use a thread-local / caller-side flag instead — simplest is to
        # return a special object the dispatcher checks.
        # But to keep dispatch.py clean: return None and rely on
        # _maybe_attach_verified_tag being called after the handler.
        return None

    # Unknown policy — fail open.
    return None


def _tag_verified_run(
    resolved: str,
    root: "Path | None",
    result: list,
) -> list:
    """For the 'neat' persona: append an audit finding tagging this exec run.

    Called after the handler succeeds for exec-category tools when the active
    persona is 'neat' (verified policy). Non-blocking — any failure returns
    the original result unchanged.
    """
    if root is None:
        return result
    try:
        from .personas import PERSONAS, get_active_persona

        active = get_active_persona(root)
        persona = PERSONAS.get(active, PERSONAS["scruffy"])
        if persona.get("execution_policy") != "verified":
            return result
    except Exception:
        return result

    try:
        from research_os.tools.actions.audit._base import AuditFinding

        finding = AuditFinding.new(
            audit_name="persona_verified",
            severity="info",
            dimension="execution",
            suggested_fix=(
                f"Verify that '{resolved}' produced expected outputs "
                "and all claims are evidence-backed (neat/verified persona)."
            ),
        )
        # Append to workspace/logs/.audit_findings.jsonl
        logs_dir = root / "workspace" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = logs_dir / ".audit_findings.jsonl"
        with jsonl_path.open("a", encoding="utf-8") as fh:
            import json as _json
            fh.write(_json.dumps(finding.to_dict(), sort_keys=True) + "\n")
    except Exception as exc:
        logger.debug("persona verified-tag failed: %s", exc)

    return result


def _resolve_tool_name(name: str) -> str:
    """Normalize incoming tool name: dots→underscores, then alias lookup."""
    canonical = name.replace(".", "_")
    return _ALIASES.get(canonical, canonical)


def _inject_consolidation_param(source_name: str, arguments: dict) -> dict:
    """Inject the consolidation parameter(s) implied by a deprecated alias.

    Accepts either a single (key, value) tuple or a tuple of (key, value)
    pairs. No-op if the caller already supplied the parameter (caller wins).
    """
    spec = _ALIAS_PARAM_INJECTION.get(source_name)
    if not spec:
        return arguments
    # Multi-kwarg form: tuple of (key, value) pairs.
    if (
        isinstance(spec, tuple)
        and spec
        and all(isinstance(p, tuple) and len(p) == 2 for p in spec)
    ):
        for key, value in spec:
            arguments.setdefault(key, value)
        return arguments
    # Single-kwarg form: (key, value).
    if isinstance(spec, tuple) and len(spec) == 2 and not isinstance(spec[0], tuple):
        key, value = spec
        arguments.setdefault(key, value)
        return arguments
    return arguments


def _log_deprecation(root: Path, source: str, target: str) -> None:
    """Append an alias-invocation event to .os_state/deprecations.log."""
    try:
        log_dir = root / ".os_state"
        if not log_dir.exists():
            return
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "kind": "tool_alias",
            "source": source,
            "target": target,
        }
        with open(log_dir / "deprecations.log", "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        # Best-effort telemetry — failing here must never break the dispatch.
        logger.debug("deprecation-log append failed: %s", exc)


def _maybe_attach_drift_hint(tool, arguments, root, result):
    """Append a non-blocking off-protocol COURSE-CORRECT hint to the envelope.

    Reads `.os_state` by shape (no daemon dependency) so it works with or
    without a daemon. Fail-open: any error returns the result unchanged. Only
    APPENDS to audit_findings + fills next_recommended_call if empty — never
    touches status, so a successful write stays successful.
    """
    try:
        from research_os.server.daemon_alert import daemon_alert
        from research_os.server.drift_detect import drift_hint
        from research_os.server.quality_watch import next_action_hint, quality_hints

        hints = []
        dh = drift_hint(tool, arguments, Path(root))
        if dh:
            hints.append(dh)
        # Quality watchers (incomplete/unverified work INSIDE Research OS) —
        # conclusions-without-audit, ungrounded synthesis, stuck loop.
        hints.extend(quality_hints(tool, arguments, Path(root)))
        # The daemon's WATCH backstop: surface NEW daemon findings the AI hasn't
        # seen since the last self-check tick, on EVERY tool call. This is the
        # AI's constant "did the daemon catch me failing at something?" check —
        # it no longer has to wait for the next sys_boot to learn.
        da = daemon_alert(Path(root))
        if da:
            hints.append(da)
        # Proactive next action for high-traffic tools (better user↔AI flow).
        derived_next = next_action_hint(tool, Path(root))
        if not hints and not derived_next:
            return result
        if not result or not getattr(result[0], "text", None):
            return result
        env = json.loads(result[0].text)
        if not isinstance(env, dict):
            return result
        if hints:
            findings = env.get("audit_findings")
            if not isinstance(findings, list):
                findings = []
            findings.extend(hints)
            env["audit_findings"] = findings
        if not env.get("next_recommended_call"):
            # Promote the first hint that carries a next call; else the derived
            # proactive next action.
            promoted = None
            for h in hints:
                if h.get("next_recommended_call"):
                    promoted = h["next_recommended_call"]
                    break
            env["next_recommended_call"] = promoted or derived_next
        result[0].text = json.dumps(env)
        return result
    except Exception:
        return result

def _handle_tool_call(name: str, arguments: dict, root: Path) -> list[TextContent]:
    if not _rate_limiter.is_allowed():
        return _text(_error("Rate limit exceeded: slow down."))
    # Normalize root to Path at the dispatch boundary. The MCP entry resolves a
    # Path, but the daemon passes daemon.root verbatim (which may be a
    # str), and ~45 action functions do `root / "..."` without coercing — a str
    # root crashes them with `unsupported operand type(s) for /: 'str' and
    # 'str'`. One coercion here protects all 159 tools regardless of caller.
    if root is not None and not isinstance(root, Path):
        try:
            root = Path(root)
        except TypeError:
            pass
    canonical_input = name.replace(".", "_")
    resolved = _resolve_tool_name(name)
    logger.info(f"Tool call: {name} -> {resolved}")
    if canonical_input in _DEPRECATED_ALIASES and canonical_input != resolved:
        _log_deprecation(root, canonical_input, resolved)
        # Back-compat: inject the dispatch parameter the consolidated tool
        # expects, so a researcher (or older script) calling the legacy name
        # gets the legacy behaviour without specifying operation/kind/source.
        arguments = _inject_consolidation_param(canonical_input, dict(arguments or {}))
    if resolved in _REMOVED_TOOLS:
        return _text(_error(_REMOVED_TOOLS[resolved]))

    # Server-side autopilot floor gates. Refuses one of the 8 enumerated
    # gates in guidance/autopilot.yaml unless ``confirmed=true`` is set.
    try:
        enforce_autopilot_gate(resolved, arguments or {}, root)
    except RoError as ro:
        return _text(_error(**ro.to_envelope_kwargs()))

    # ── §13.1 Persona execution-policy enforcement ───────────────────────────
    # Applied AFTER autopilot gates, BEFORE the handler runs.
    # Only fires for exec-category tools; all other tools are unaffected.
    # Fail-open: any error reading the persona behaves exactly like today
    # (scruffy/direct — the handler runs as normal).
    try:
        _persona_policy_result = _enforce_persona_policy(resolved, root)
        if _persona_policy_result is not None:
            return _persona_policy_result
    except Exception:
        pass  # degrade open — never block a tool due to a persona read error

    # Defer import to avoid circular at module load time.
    from .registry import _HANDLERS

    handler = _HANDLERS.get(resolved)
    if handler is None:
        spec = plugin_registry().resolve_tool(resolved)
        if spec is not None:
            handler = spec.handler
    if handler is None:
        all_handlers = list(_HANDLERS.keys())
        # Namespace-aware lookup with lowered cutoff for short tool names
        # (closes FIX-16: sys_X typo prefers other sys_*).
        suggestions = did_you_mean(
            resolved, all_handlers, n=3, cutoff=0.5, namespace_aware=True
        )
        suggestion_clause = (
            f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        )
        return _text(
            _error(
                what=f"unknown tool '{name}'",
                why=(
                    "no handler is registered for that name; it may be "
                    "deprecated, removed, or a typo"
                ),
                next_action=(
                    f"call tool_tools_list to see live tools.{suggestion_clause}"
                ),
            )
        )
    try:
        result = _normalize_envelope(handler(resolved, arguments, root), resolved)
        # §13.1 neat/verified persona: tag exec runs for the audit gate.
        # Non-blocking — failure returns result unchanged.
        if _is_exec_tool(resolved):
            result = _tag_verified_run(resolved, root, result)
        # Mid-prompt drift backstop (4.0.4): if the AI just wrote step content
        # without routing/opening a step, append a non-blocking COURSE-CORRECT
        # hint to the SAME envelope it's reading, so it self-corrects this turn.
        # Fail-open + non-blocking — never alters success/failure, only appends.
        result = _maybe_attach_drift_hint(resolved, arguments, root, result)
        return result
    except RoError as ro:
        # Structured error from the handler: render its WHAT/WHY/NEXT
        # directly into the envelope.
        logger.info("RoError in %s: %s", name, ro.what)
        return _text(_error(**ro.to_envelope_kwargs()))
    except KeyError as ke:
        # KeyError(name) bubbling up from a dispatch lookup or arg
        # unpacking is almost always a missing-required-arg situation.
        missing = ke.args[0] if ke.args else "?"
        return _text(_error(
            what=f"missing required argument '{missing}' for {name}",
            why="the handler tried to read this key from arguments but it was absent",
            next_action=(
                f"call sys_tool_describe(name='{name}') to see the input schema"
            ),
        ))
    except TypeError as te:
        msg = str(te)
        # Distinguish "unexpected keyword argument" / "missing required" / other
        if "unexpected keyword argument" in msg or ("missing" in msg and "required" in msg):
            return _text(_error(
                what=f"argument shape mismatch in {name}",
                why=f"the handler rejected the arguments: {msg}",
                next_action=(
                    f"call sys_tool_describe(name='{name}') to confirm the input schema"
                ),
            ))
        logger.exception(f"Tool {name} failed")
        return _text(_error(
            what=f"{name} raised a TypeError",
            why=msg,
            next_action="check tool inputs against sys_tool_describe; report the trace if shape looks right",
        ))
    except FileNotFoundError as fe:
        return _text(_error(
            what=f"{name} could not find a required file",
            why=str(fe),
            next_action=(
                "verify the workspace path; for protocol-not-found errors, "
                "call sys_protocol_list for the current names"
            ),
        ))
    except Exception as e:
        logger.exception(f"Tool {name} failed")
        return _text(_error(
            what=f"{name} raised an unexpected exception",
            why=f"{type(e).__name__}: {e}",
            next_action="re-run with simpler arguments to isolate; report trace if reproducible",
        ))
