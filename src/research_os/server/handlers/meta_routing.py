"""Handlers for the meta_routing sub-domain.

Carved out of handlers/meta.py to stay under the 600-line ceiling.
"""
from __future__ import annotations

from .._handlers_runtime import *  # noqa: F401,F403
# mem_log dispatcher delegates to a methodology handler — pull it into scope.

__all__ = [
    "_handle_sys_protocol_list",
    "_handle_tool_protocols_list",
    "_handle_tool_tools_list",
    "_handle_sys_protocol_get",
    "_handle_sys_boot",
    "_handle_tool_route",
    "_handle_tool_semantic_route",
    "_handle_sys_semantic_tool_search",
    "_handle_sys_active_tools",
    "_handle_tool_cache_clear",
    "_handle_tool_step_env_lock",
    "_handle_tool_workflow_dag",
    "_handle_sys_tool_describe",
    "_handle_sys_protocol_validate",
    "_handle_sys_protocol_next",
    "_handle_sys_protocol_log",
    "_handle_sys_protocol_history",
    "_handle_sys_active_project",
]

def _handle_sys_protocol_list(name, arguments, root):
    try:
        cat = arguments.get("category") if isinstance(arguments, dict) else None
        cat = cat if isinstance(cat, str) and cat else None
        protocols = list_protocols(category=cat)
        # Unknown category? Build a "did you mean" hint from the live catalog.
        if cat and not protocols:
            from research_os.server.errors import did_you_mean
            all_p = list_protocols(category=None)
            valid_cats = sorted({
                (p.get("name") or "").split("/", 1)[0]
                for p in all_p
                if (p.get("name") or "")
            })
            suggestions = did_you_mean(cat, valid_cats, n=3, cutoff=0.5)
            if not suggestions and valid_cats:
                suggestions = valid_cats[:3]
            suffix = (
                f" Did you mean: {', '.join(suggestions)}?"
                if suggestions else ""
            )
            return _text(_error(
                what=f"No protocols for category '{cat}'",
                why="category does not match any known protocol prefix",
                next_action=(
                    f"call sys_protocol_list with a valid category.{suffix}"
                ),
            ))
        return _text(_success({
            "protocols": protocols,
            "count": len(protocols),
            "category": cat,
        }))
    except Exception as e:
        return _text(_error(str(e)))


def _handle_tool_protocols_list(name, arguments, root):
    from research_os.tools.actions.listers import list_protocols_flat

    try:
        cat = arguments.get("category")
        pack = arguments.get("pack")
        include_packs = arguments.get("include_pack_protocols", True)
        if include_packs is None:
            include_packs = True
        protocols = list_protocols_flat(
            category=cat if isinstance(cat, str) and cat else None,
            pack=pack if isinstance(pack, str) and pack else None,
            include_pack_protocols=bool(include_packs),
        )
        return _text(_success({
            "protocols": protocols,
            "count": len(protocols),
            "filters": {
                "category": cat or None,
                "pack": pack or None,
                "include_pack_protocols": bool(include_packs),
            },
        }))
    except Exception as e:
        return _text(_error(str(e)))


def _handle_tool_tools_list(name, arguments, root):
    from research_os.tools.actions.listers import (
        VALID_LISTING_MODES,
        list_tools_flat,
    )

    try:
        scope = arguments.get("scope") or "all"
        include_deprecated = bool(arguments.get("include_deprecated", False))
        match = arguments.get("match_substring")
        # mode-scoped surface (context-bloat fix). 'auto' resolves the
        # active workspace mode from config; an explicit mode is passed
        # through; omitted/empty ⇒ no mode filter (back-compat).
        raw_mode = arguments.get("mode")
        resolved_mode = None
        if isinstance(raw_mode, str) and raw_mode.strip():
            m = raw_mode.strip().lower()
            if m == "auto":
                try:
                    from research_os.tools.actions.state.config import (
                        get_workspace_mode,
                    )
                    resolved_mode = get_workspace_mode(root)
                except Exception:
                    resolved_mode = None
            elif m in VALID_LISTING_MODES:
                resolved_mode = m
            else:
                return _text(_error(
                    what=f"Unknown mode '{raw_mode}'",
                    why="mode must be 'auto' or one of "
                        f"{', '.join(VALID_LISTING_MODES)}",
                    next_action=(
                        "call tool_tools_list with mode='auto' (resolve from "
                        "config) or a valid mode name, or omit mode entirely."
                    ),
                ))
        tools = list_tools_flat(
            TOOL_DEFINITIONS,
            aliases=_ALIASES,
            deprecated_aliases=_DEPRECATED_ALIASES,
            scope=scope,
            include_deprecated=include_deprecated,
            match_substring=match if isinstance(match, str) and match else None,
            mode=resolved_mode,
        )
        return _text(_success({
            "tools": tools,
            "count": len(tools),
            "filters": {
                "scope": scope,
                "include_deprecated": include_deprecated,
                "match_substring": match or None,
                "mode": resolved_mode,
            },
        }))
    except Exception as e:
        return _text(_error(str(e)))


def _handle_sys_protocol_get(name, arguments, root):
    p_name = arguments.get("protocol_name")
    profile = _read_profile(root)
    model_profile = profile.get("model_profile", "medium")
    context_class = profile.get("context_class", "short")
    # Default format respects the AI-side knobs (W20):
    #   model_profile=small  → lean
    #   context_class=long   → full
    #   otherwise            → summary (~300 tokens)
    # Callers who need a specific format pass it explicitly.
    if arguments.get("format"):
        fmt = arguments["format"].lower()
    elif model_profile == "small":
        fmt = "lean"
    elif context_class == "long":
        fmt = "full"
    else:
        fmt = "summary"
    step_id = arguments.get("step_id")
    try:
        import yaml as _yaml

        data = load_protocol(
            p_name, model_profile=model_profile, format=fmt, step_id=step_id
        )
        # Surface UNMET mechanical preconditions (precondition gate, tier 1):
        # the prose `prerequisites` says what should be true; this tells the
        # AI exactly which checkable ones are NOT yet satisfied, so it does
        # the missing step instead of proceeding on a missing foundation.
        # Pure read, fail-safe — no daemon needed; absent when all met.
        unmet = []
        try:
            from research_os.server.preconditions import unmet_preconditions

            # The sidecar is keyed by full protocol PATH (e.g.
            # "guidance/analysis_plan"); the loaded data's `id` is often the
            # bare leaf ("analysis_plan"). Prefer the requested path, and try
            # both so a bare or qualified name resolves.
            unmet = unmet_preconditions(str(p_name), root)
            if not unmet:
                alt = (data.get("id") if isinstance(data, dict) else None)
                if alt and str(alt) != str(p_name):
                    unmet = unmet_preconditions(str(alt), root)
        except Exception:  # noqa: BLE001 - surfacing must never break the load
            unmet = []
        if fmt in {"summary", "step"}:
            # Lean structured payload (no yaml dump bulk).
            response = dict(data)
            response.setdefault(
                "_loaded_as", fmt
            )
            if unmet:
                response["unmet_preconditions"] = unmet
        else:
            # format=full: AI explicitly opted into the bulk payload —
            # don't tack on another paragraph telling it to prefer
            # summary. Boot reminder also lives in sys_boot now.
            response = {"content": _yaml.dump(data, sort_keys=False)}
            if model_profile == "small":
                response["note"] = "Loaded in light mode (small model profile)."
            if unmet:
                response["unmet_preconditions"] = unmet
        return _text(_success(response))
    except Exception as e:
        return _text(_error(str(e)))


def _handle_sys_boot(name, arguments, root):
    from research_os.tools.actions.router import sys_boot
    from .meta_workspace import _handle_sys_where
    from .meta_sys import _handle_sys_config

    arguments = arguments or {}
    operation = arguments.get("operation", "boot")

    if operation == "where":
        return _handle_sys_where(name, arguments, root)

    if operation in ("config_get", "config_note"):
        # Map to sys_config's expected `operation` arg ('get' or 'note').
        mapped = dict(arguments)
        mapped["operation"] = "get" if operation == "config_get" else "note"
        return _handle_sys_config(name, mapped, root)

    # Default: boot
    lean = bool(arguments.get("lean", False))
    res = sys_boot(root, lean=lean)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "sys_boot failed")))


def _handle_tool_route(name, arguments, root):
    from research_os.tools.actions.router import route_request

    arguments = arguments or {}
    mode = arguments.get("mode", "route")
    if mode == "tool_search":
        return _handle_sys_semantic_tool_search(name, arguments, root)

    res = route_request(
        arguments["prompt"],
        root,
        persist_plan=bool(arguments.get("persist_plan", True)),
    )
    if res.get("status") == "success":
        # Phase-9 cross-cutting: name the next tool to call so the AI
        # doesn't burn a turn deciding.
        res.setdefault("recommended_action", _recommended_action_for_route(res))
        # Universal skill-pull reflex: for THIS task, recommend the
        # capability skills the AI should pull + load + use before doing the
        # work (then keep working inside Research-OS). Keyed off the resolved
        # task (sub_intent / primary_protocol) + the project's domain + mode,
        # so the recommendation is task-specific, not just project-generic.
        # By-shape, fail-open — never blocks a route.
        try:
            from research_os.tools.actions.research.skills import (
                recommend_skills as _rec_skills,
            )
            from research_os.tools.actions.state.config import (
                get_research_config,
                get_workspace_mode,
            )

            _cfg = get_research_config(root) or {}
            _domain = (_cfg.get("domain")
                       or _cfg.get("research_goal", {}).get("domain")
                       or "")
            _rs = _rec_skills(
                root,
                domain=_domain,
                workspace_mode=get_workspace_mode(root),
                task_intent=res.get("sub_intent"),
                protocol=res.get("primary_protocol"),
            )
            skills = _rs.get("recommended_skills") or []
            if skills:
                res["recommended_skills"] = skills
                res["skills_advice"] = _rs.get("note", "")
        except Exception:
            pass
        # Live drop-zone: surface (and consume) any context the researcher
        # dropped since the last prompt. Fires on the turn after the drop —
        # "I put a paper in context/" → the AI is told to read it.
        try:
            from research_os.tools.actions.state.context_watch import (
                detect_new_context,
            )

            nc = detect_new_context(root, update_marker=True)
            if nc.get("new_files") or nc.get("changed_files"):
                res["new_context"] = {
                    "new_files": nc.get("new_files", []),
                    "changed_files": nc.get("changed_files", []),
                    "hint": nc.get("hint", ""),
                }
        except Exception:
            pass
        return _text(_success(res))
    return _text(_error(res.get("message", "tool_route failed")))


def _handle_tool_semantic_route(name, arguments, root):
    from research_os.tools.actions import semantic

    if not semantic.semantic_available():
        # The op didn't run — signal that with a `warning` status rather
        # than `success`, but keep the diagnostic payload intact so
        # clients that read it still work. (No inner redundant `status`.)
        env = _success({
            "reason": (
                "Semantic routing requires the `semantic` extra. "
                "Reinstall to restore it: pip install --upgrade research-os "
                "and confirm protocols/_embeddings.npz is present "
                "(run scripts/build_embeddings.py)."
            ),
            "fastembed_installed": semantic.fastembed_available(),
            "embeddings_on_disk": semantic.embeddings_on_disk(),
        }, next_recommended_call="tool_route(prompt=<original_or_refined>)")
        env["status"] = "warning"
        return _text(env)
    prompt = arguments["prompt"]
    top_k = int(arguments.get("top_k") or 5)
    matches = semantic.top_k_protocols(prompt, k=top_k)
    payload = semantic.semantic_route(prompt, k=top_k) or {}
    payload["status"] = "success"
    payload["matches"] = [{"id": m.id, "score": round(m.score, 4)} for m in matches]
    # Phase-9 cross-cutting: mirror tool_route's recommended_action hint.
    # When semantic produces a primary candidate, recommend loading it
    # summary-first; otherwise fall back to tool_route for a full pass.
    primary = (matches[0].id if matches else None) or payload.get("primary_protocol")
    if primary:
        payload.setdefault(
            "recommended_action",
            f"sys_protocol_get(protocol_name='{primary}', format='summary')",
        )
    else:
        payload.setdefault(
            "recommended_action",
            "tool_route(prompt=<original_or_refined>)",
        )
    return _text(_success(payload))


def _handle_sys_semantic_tool_search(name, arguments, root):
    from research_os.tools.actions import semantic

    if not semantic.semantic_available():
        # Op didn't run — `warning` status, payload preserved, no inner
        # redundant `status` key.
        env = _success({
            "reason": (
                "Semantic tool search requires the `semantic` extra. "
                "Reinstall to restore it: pip install --upgrade research-os."
            ),
            "fastembed_installed": semantic.fastembed_available(),
            "embeddings_on_disk": semantic.embeddings_on_disk(),
        }, next_recommended_call="tool_tools_list(match_substring=<keyword>)")
        env["status"] = "warning"
        return _text(env)
    query = arguments["query"]
    top_k = int(arguments.get("top_k") or 5)
    matches = semantic.top_k_tools(query, k=top_k)
    return _text(_success({
        "status": "success",
        "query": query,
        "matches": [{"name": m.id, "score": round(m.score, 4)} for m in matches],
    }))


def _handle_sys_active_tools(name, arguments, root):
    from research_os.tools.actions.router import active_tools_for_protocol

    p_name = arguments.get("protocol_name")
    if not p_name:
        return _text(_error("protocol_name is required"))
    res = active_tools_for_protocol(p_name)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "sys_active_tools failed")))


def _handle_tool_cache_clear(name, arguments, root):
    from research_os.tools.actions.search import cache_clear

    res = cache_clear(
        root,
        source=arguments.get("source"),
        older_than_days=arguments.get("older_than_days"),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "tool_cache_clear failed")))


def _handle_tool_step_env_lock(name, arguments, root):
    from research_os.tools.actions.exec import step_env_lock

    res = step_env_lock(
        root,
        step_id=arguments.get("step_id"),
        write_conda_yaml=bool(arguments.get("write_conda_yaml", False)),
        write_dockerfile=bool(arguments.get("write_dockerfile", False)),
        write_apptainer=bool(arguments.get("write_apptainer", False)),
        write_entrypoint=bool(arguments.get("write_entrypoint", True)),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "tool_step_env_lock failed")))


def _handle_tool_workflow_dag(name, arguments, root):
    from research_os.tools.actions.state import workflow_dag

    res = workflow_dag(
        root,
        render_png=bool(arguments.get("render_png", False)),
        output_dir=arguments.get("output_dir", "docs"),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "tool_workflow_dag failed")))


def _handle_sys_tool_describe(name, arguments, root):
    tool_name = arguments.get("tool_name")
    if not tool_name:
        return _text(_error("tool_name is required"))
    canonical = _resolve_tool_name(tool_name)
    schema = TOOL_DEFINITIONS.get(canonical)
    if not schema:
        return _text(
            _error(
                f"Unknown tool '{tool_name}'. Try sys_protocol_list to browse, "
                "or tool_route to find by prompt."
            )
        )
    return _text(
        _success(
            {
                "name": canonical,
                "category": schema.get("category", ""),
                "short": schema.get("short", ""),
                "description": schema.get("description", ""),
                "inputSchema": schema.get("inputSchema", {}),
                # Phase-9 cross-cutting introspection.
                "status": schema.get("status", "live"),
                "pack": schema.get("pack", "core"),
            }
        )
    )


def _handle_sys_protocol_validate(name, arguments, root):
    res = validate_protocol(arguments.get("protocol_name"), root)
    if "error" in res:
        return _text(_error(res["error"]))
    return _text(_success(res))


def _handle_sys_protocol_next(name, arguments, root):
    return _text(_success(get_next_protocol(root)))


def _handle_sys_protocol_log(name, arguments, root):
    from research_os.tools.actions.protocol import log_protocol_execution

    res = log_protocol_execution(
        root,
        arguments["protocol_name"],
        arguments["status"],
        arguments.get("details", ""),
        override_completeness_gate=bool(arguments.get("override_completeness_gate", False)),
    )
    # Surface a blocked completion as an error so the AI sees it must act, not a
    # silent success it can ignore.
    if isinstance(res, dict) and res.get("status") == "blocked":
        return _text(_error(res.get("message", "completion blocked: outputs missing")))
    return _text(_success(res))


def _handle_sys_protocol_history(name, arguments, root):
    from research_os.tools.actions.protocol import get_protocol_history

    res = get_protocol_history(root, arguments.get("limit", 20))
    return _text(_success(res))


def _handle_sys_active_project(name, arguments, root):
    """Report which project root the server resolved for this request."""
    env_root = os.environ.get("RESEARCH_OS_WORKSPACE", "").strip()
    via = "cwd"
    if env_root and Path(env_root).expanduser().resolve() == root:
        via = "RESEARCH_OS_WORKSPACE"
    elif (root / ".os_state").exists():
        via = "cwd→.os_state"
    has_state = (root / ".os_state").exists()
    payload: dict[str, Any] = {
        "project_root": str(root),
        "has_os_state": has_state,
        "resolved_via": via,
    }
    # Only surface the orientation advice when the project isn't
    # scaffolded — that's the only branch the AI needs to act on.
    if not has_state:
        payload["advice"] = (
            "No .os_state/ here — run `research-os init` or open a "
            "scaffolded folder. Project resolution order: "
            "RESEARCH_OS_WORKSPACE env var → cwd walked up → cwd."
        )
    return _text(_success(payload))


HANDLERS = {
    "sys_protocol_get": _handle_sys_protocol_get,
    "sys_boot": _handle_sys_boot,
    "tool_route": _handle_tool_route,
    "sys_active_tools": _handle_sys_active_tools,
    "tool_workflow_dag": _handle_tool_workflow_dag,
    "tool_protocols_list": _handle_tool_protocols_list,
    "sys_active_project": _handle_sys_active_project,
}
