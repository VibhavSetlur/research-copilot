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
from .envelopes import TextContent, _error, _normalize_envelope, _text
from .errors import RoError, did_you_mean
from .plugin_registry import plugin_registry
from .rate_limiter import _rate_limiter


logger = logging.getLogger("research-os.server")


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
    # Path, but the daemon gateway passes daemon.root verbatim (which may be a
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
