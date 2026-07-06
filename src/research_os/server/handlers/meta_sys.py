"""Handlers for the meta_sys sub-domain.

Carved out of handlers/meta.py to stay under the 600-line ceiling.
"""
from __future__ import annotations

from .._handlers_runtime import *  # noqa: F401,F403
# mem_log dispatcher delegates to a methodology handler — pull it into scope.

__all__ = [
    "_handle_sys_config_get",
    "_handle_sys_config_set",
    "_handle_sys_config_validate",
    "_handle_sys_config_note",
    "_handle_sys_notify",
    "_handle_sys_session_handoff",
    "_handle_sys_env_snapshot",
    "_handle_sys_env_docker_generate",
    "_handle_mem_citations_generate",
    "_handle_mem_intake_regenerate",
    "_handle_sys_dep_inventory",
    "_handle_sys_config",
    "_handle_sys_env",
    "_handle_tool_deprecations_summary",
    "_handle_sys_packs_installed",
    "_handle_sys_adapters_installed",
    "_handle_tool_adapter_extract",
    "_handle_tool_adapters_list",
    "_handle_tool_adapters_run_all",
]

def _handle_sys_config_get(name, arguments, root):
    res = get_config(root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "config not found")))


def _handle_sys_config_set(name, arguments, root):
    res = set_config(arguments["key"], arguments["value"], root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "set failed")))


def _handle_sys_config_validate(name, arguments, root):
    res = validate_config(root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "validate failed")))


def _handle_sys_config_note(name, arguments, root):
    """Append a learned researcher preference to interaction.agent_notes.

    The 'learn the user' write-back: APPENDS (never clobbers) so corrections
    accumulate across sessions and are inherited at the next boot.
    """
    note = (arguments or {}).get("note") or (arguments or {}).get("value") or ""
    res = append_agent_note(note, root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "note failed")))


def _handle_sys_notify(name, arguments, root):
    res = notify_researcher(arguments["message"], arguments["level"], root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "notify failed")))


def _handle_sys_session_handoff(name, arguments, root):
    res = session_handoff(root)
    if res.get("status") == "success":
        # Wrap the markdown in a conformant envelope — a bare string can't be
        # normalized (env-05).
        return _text(_success({"handoff_markdown": res["content"]}))
    return _text(_error(res.get("message", "handoff failed")))


def _handle_sys_env_snapshot(name, arguments, root):
    step_id = arguments.get("step_id") if arguments else None
    scope = arguments.get("scope") if arguments else None
    res = env_snapshot(root, step_id=step_id, scope=scope)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "snapshot failed")))


def _handle_sys_env_docker_generate(name, arguments, root):
    step_id = arguments.get("step_id") if arguments else None
    res = env_docker_generate(root, step_id=step_id)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "docker generate failed")))


def _handle_mem_citations_generate(name, arguments, root):
    from research_os.project_ops import generate_citations_md

    return _text(_success({"citations_path": generate_citations_md(root)}))


def _handle_mem_intake_regenerate(name, arguments, root):
    from research_os.project_ops import regenerate_intake

    return _text(_success({"intake_path": regenerate_intake(root)}))


def _handle_sys_dep_inventory(name, arguments, root):
    return _text(_success(_optional_dep_inventory()))


def _handle_sys_config(name, arguments, root):
    """Unified researcher-config dispatcher (get | set | validate)."""
    legacy = {
        "sys_config_get": "get",
        "sys_config_set": "set",
        "sys_config_validate": "validate",
    }
    operation = arguments.get("operation") or legacy.get(name)
    if not operation:
        return _text(_error(
            "sys_config requires operation='get'|'set'|'validate'"
        ))
    if operation == "get":
        return _handle_sys_config_get(name, arguments, root)
    if operation == "set":
        return _handle_sys_config_set(name, arguments, root)
    if operation == "validate":
        return _handle_sys_config_validate(name, arguments, root)
    if operation == "note":
        return _handle_sys_config_note(name, arguments, root)
    return _text(_error(f"Unknown sys_config operation '{operation}'"))


def _handle_sys_env(name, arguments, root):
    """Unified environment dispatcher (snapshot | docker_generate)."""
    legacy = {
        "sys_env_snapshot": "snapshot",
        "sys_env_docker_generate": "docker_generate",
    }
    operation = arguments.get("operation") or legacy.get(name)
    if not operation:
        return _text(_error(
            "sys_env requires operation='snapshot'|'docker_generate'"
        ))
    if operation == "snapshot":
        return _handle_sys_env_snapshot(name, arguments, root)
    if operation == "docker_generate":
        return _handle_sys_env_docker_generate(name, arguments, root)
    return _text(_error(f"Unknown sys_env operation '{operation}'"))


def _handle_tool_deprecations_summary(name, arguments, root):
    """Aggregate counts from .os_state/deprecations.log."""
    log_path = root / ".os_state" / "deprecations.log"
    if not log_path.exists():
        return _text(_success({
            "total": 0,
            "by_kind": {},
            "by_source": {},
            "by_target": {},
            "note": "No deprecations.log yet. Aliases / redirects haven't been invoked.",
        }))
    by_kind: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_target: dict[str, int] = {}
    total = 0
    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                total += 1
                k = e.get("kind", "unknown")
                by_kind[k] = by_kind.get(k, 0) + 1
                s = e.get("source", "")
                if s:
                    by_source[s] = by_source.get(s, 0) + 1
                t = e.get("target", "")
                if t:
                    by_target[t] = by_target.get(t, 0) + 1
    except Exception as e:
        return _text(_error(str(e)))
    return _text(_success({
        "total": total,
        "by_kind": dict(sorted(by_kind.items())),
        "by_source": dict(sorted(by_source.items(), key=lambda x: -x[1])),
        "by_target": dict(sorted(by_target.items(), key=lambda x: -x[1])),
        "log_path": ".os_state/deprecations.log",
        "advice": (
            "Replace deprecated names with their consolidated counterparts "
            "before the next major (when aliases / redirect stubs will be removed). "
            "See docs/AI_GUIDE.md (Consolidated v2 entry points) for the full old→new table."
        ),
    }))


def _handle_sys_packs_installed(name, arguments, root):
    """Return diagnostics about installed packs."""
    from research_os.plugins import installed_packs, load_pack_errors
    packs = installed_packs()
    errors = load_pack_errors()
    # Optional pack-name filter: returns one pack or did_you_mean.
    pack_name = (arguments or {}).get("pack") if isinstance(arguments, dict) else None
    if pack_name and isinstance(pack_name, str):
        names = [p.get("name") for p in packs if isinstance(p, dict) and p.get("name")]
        if pack_name not in names:
            from research_os.server.errors import did_you_mean
            suggestions = did_you_mean(pack_name, names, n=3, cutoff=0.5)
            if not suggestions and names:
                suggestions = names[:3]
            suffix = (
                f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
            )
            return _text(_error(
                what=f"Pack '{pack_name}' is not installed",
                why="no pack with that name was discovered at server startup",
                next_action=(
                    f"install the pack via pip, or call sys_packs_installed without "
                    f"a pack filter to see all installed packs.{suffix}"
                ),
            ))
        packs = [p for p in packs if p.get("name") == pack_name]
    return _text(_success({
        "packs": packs,
        "pack_count": len(packs),
        "errors": errors,
        "error_count": len(errors),
        "advice": (
            "Install third-party packs via pip; they auto-register on next "
            "server start via the `research_os.protocol_pack` entry-point group."
            if not errors else
            "One or more packs failed to register; inspect 'errors' for "
            "tracebacks. See workspace/logs/pack_errors.log for the full log."
        ),
    }))


# Register sys_packs_installed (defined here because it depends on the
# pack loader being imported; can't live in the main _HANDLERS block above).


def _handle_sys_adapters_installed(name, arguments, root):
    from research_os.adapters import installed_adapters, load_adapter_errors
    adapters = installed_adapters()
    errors = load_adapter_errors()
    return _text(_success({
        "adapters": adapters,
        "adapter_count": len(adapters),
        "errors": errors,
        "error_count": len(errors),
    }))


def _handle_tool_adapter_extract(name, arguments, root):
    from research_os.adapters.runner import run_extract
    adapter_name = arguments.get("adapter_name")
    if not adapter_name:
        return _text(_error("adapter_name is required"))
    res = run_extract(root, adapter_name, step_id=arguments.get("step_id"))
    if res.get("status") == "success":
        return _text(_success(res))
    # Failure: try to enrich with did_you_mean against installed adapter names.
    msg = res.get("message", "extract failed")
    try:
        from research_os.adapters import installed_adapters
        from research_os.server.errors import did_you_mean
        names = [
            a.get("name") for a in installed_adapters()
            if isinstance(a, dict) and a.get("name")
        ]
        if adapter_name not in names:
            suggestions = did_you_mean(adapter_name, names, n=3, cutoff=0.5)
            if not suggestions and names:
                suggestions = names[:3]
            suffix = (
                f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
            )
            return _text(_error(
                what=f"Adapter '{adapter_name}' not found",
                why="no adapter with that name was discovered at server startup",
                next_action=(
                    f"call sys_adapters_installed to list valid adapter names.{suffix}"
                ),
            ))
    except Exception:
        pass
    return _text(_error(msg))


def _handle_tool_adapters_list(name, arguments, root):
    from research_os.adapters.runner import list_adapters
    return _text(_success(list_adapters(root)))


def _handle_tool_adapters_run_all(name, arguments, root):
    from research_os.adapters.runner import run_all
    return _text(_success(run_all(root, step_id=arguments.get("step_id"))))


HANDLERS = {
    "sys_notify": _handle_sys_notify,
    "tool_session_handoff": _handle_sys_session_handoff,
    "sys_env": _handle_sys_env,
}
