"""Handlers for the meta_workspace sub-domain.

Carved out of handlers/meta.py to stay under the 600-line ceiling.
"""
from __future__ import annotations

from .._handlers_runtime import *  # noqa: F401,F403
# mem_log dispatcher delegates to a methodology handler — pull it into scope.
from research_os.errors import WriteProtectedError, check_write_permitted
from research_os.tools.actions.audit.script_naming import (
    is_versioned_name,
    next_version_name,
    suggest_version_bump,
)


def _resolve_inside_root(root, filepath):
    """Resolve *filepath* against *root* and guard against path traversal.

    Raises WriteProtectedError when the resolved target escapes *root*
    (e.g. ``../../etc/passwd``, absolute paths outside the project,
    symlinks pointing outside the project tree). This is the central
    path-containment guard for every sys_file_* handler.
    """
    root_resolved = Path(root).resolve()
    target = Path(filepath)
    candidate = target if target.is_absolute() else (root_resolved / target)
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise WriteProtectedError(
            str(candidate),
            f"Path could not be resolved: {exc}",
        )
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise WriteProtectedError(
            str(filepath),
            f"Path '{filepath}' escapes project root.",
        )
    return resolved


__all__ = [
    "_handle_sys_workspace_mode",
    "_handle_sys_workspace_scaffold",
    "_handle_sys_workspace_tree",
    "_handle_sys_state_get",
    "_handle_sys_file_read",
    "_handle_sys_file_write",
    "_handle_sys_file_list",
    "_handle_sys_file_delete",
    "_handle_sys_file_validate_md",
    "_handle_sys_path_create",
    "_handle_sys_path_abandon",
    "_handle_sys_path_list",
    "_handle_tool_path_finalize",
    "_handle_tool_synthesis_curate_figures",
    "_handle_sys_export_share_archive",
    "_handle_sys_export_ro_crate",
    "_handle_sys_checkpoint_create",
    "_handle_sys_checkpoint_rollback",
    "_handle_sys_checkpoint_list",
    "_handle_sys_path",
    "_handle_sys_where",
    "_handle_sys_daemon",
    "_handle_sys_consent",
]

def _handle_sys_workspace_scaffold(name, arguments, root):
    ide = arguments.get("ide", "all")
    valid = [
        "cursor", "claude", "antigravity", "opencode", "vscode",
        "windsurf", "continue", "aider",
    ]
    ide_flags = (
        valid
        if ide == "all"
        else [i.strip() for i in ide.split(",") if i.strip() in valid]
    )
    scaffold_minimal_workspace(
        root,
        arguments.get("project_name", "Research Project"),
        ide_flags=ide_flags,
        copy_agents=True,
    )
    if (root / ".os_state").exists() and (root / "workspace").exists():
        _profile_inputs(root)
    return _text(_success({"scaffolded": True, "ide_flags": ide_flags}))


def _handle_sys_workspace_tree(name, arguments, root):
    # Coerce + clamp depth at the boundary: a negative depth never reaches the
    # `if depth == 0` base case (unbounded recursion / RecursionError on a deep
    # tree), and a non-int like "3" raises a TypeError on `depth - 1`. MCP arg
    # types are advisory, so harden here.
    raw_depth = arguments.get("depth", 3)
    try:
        depth = int(raw_depth)
    except (TypeError, ValueError):
        depth = 3
    depth = max(0, min(depth, 12))
    include_files = arguments.get("include_files", True)
    tree = _build_tree(root / "workspace", depth, include_files)
    return _text(_success({"tree": tree}))


def _handle_sys_state_get(name, arguments, root):
    arguments = arguments or {}
    operation = arguments.get("operation", "state_get")
    if operation not in ("state_get", ""):
        # Delegate to _handle_sys_path — map sys_state_get's `operation`
        # directly onto sys_path's `operation` arg (same names: create,
        # abandon, list, rename, group).
        mapped = dict(arguments)
        mapped["operation"] = operation
        return _handle_sys_path(name, mapped, root)

    fmt = (arguments.get("format") or "full").lower()
    state = load_state(root)
    if fmt == "minimal":
        from research_os.server._helpers import _read_profile
        from research_os.state.state_ledger import ResearchLedger

        # context_class=long → broader history window (10000 tokens)
        # so long-context models get the full project arc on boot.
        # short (default) keeps the lean 450-token summary.
        profile = _read_profile(root)
        max_tokens = (
            10000 if profile.get("context_class") == "long" else 450
        )
        ledger = ResearchLedger(root / ".os_state" / "state_ledger.json")
        return _text(_success({"minimal_context": ledger.get_project_summary(max_tokens=max_tokens)}))
    if fmt == "markdown":
        md_path = root / ".os_state" / "os_state.md"
        if not md_path.exists():
            return _text(_error("os_state.md missing: run a tool that mutates state first."))
        return _text(_success({"markdown": md_path.read_text(encoding="utf-8")}))
    # full (lean projection — strip very large fields)
    paths = state.get("paths", {})
    out: dict[str, Any] = {
        "project_name": state.get("project_name") or state.get("project", ""),
        "pipeline_stage": state.get("pipeline_stage", state.get("phase", "init")),
        "workspace_mode": state.get("workspace_mode", "analysis"),
        "step": state.get("step", 0),
        "current_path": state.get("current_path", "main"),
    }
    # Only include collection-valued fields when they have content —
    # empty list/dict/None on a fresh project just burns tokens.
    paths_summary = {k: v.get("status") for k, v in paths.items()}
    if paths_summary:
        out["paths_summary"] = paths_summary
    hypotheses = state.get("active_hypotheses") or []
    if hypotheses:
        out["active_hypotheses"] = hypotheses
    if state.get("resumable_from"):
        out["resumable_from"] = state["resumable_from"]
    return _text(_success(out))


def _handle_sys_file_read(name, arguments, root):
    try:
        p = _resolve_inside_root(root, arguments["filepath"])
    except WriteProtectedError as exc:
        return _text(_error(str(exc)))
    if not p.exists() or not p.is_file():
        return _text(_error(f"File not found: {arguments['filepath']}"))
    if p.stat().st_size > 50 * 1024 * 1024:
        return _text(_error("File too large (>50 MB). Use tool_data_sample for tabular data."))
    return _text(_success({"content": p.read_text(encoding="utf-8", errors="replace")}))


def _handle_sys_file_write(name, arguments, root):
    try:
        p = _resolve_inside_root(root, arguments["filepath"])
    except WriteProtectedError as exc:
        return _text(_error(str(exc)))
    force = arguments.get("force", False)
    root_resolved = Path(root).resolve()
    rel = str(p.relative_to(root_resolved))

    # Central write-permission gate. As of 3.2.2 only `.os_state/` is
    # hard-locked (internal state, never hand-edited).
    try:
        check_write_permitted(p, root=root_resolved)
    except WriteProtectedError as exc:
        return _text(_error(str(exc)))

    # inputs/ is the researcher's source-of-truth — writable. But the two
    # ORIGINAL trees (raw_data, literature) get a SOFT guard: a deliberate
    # force=true + a confirm-with-researcher warning, so the AI never
    # silently rewrites primary data / provenance. literature_index.yaml
    # (the AI-maintained citation ledger) is the documented exception.
    soft_warning = None
    is_original_input = (
        rel.startswith(("inputs/raw_data/", "inputs/literature/"))
        and not rel.endswith("literature_index.yaml")
    )
    if is_original_input and not force:
        return _text(_error(
            f"`{rel}` is original input data — your project's source-of-truth. "
            "Editing it changes provenance and staleness the intake SHA-256 "
            "inventory. Confirm with the researcher, then pass force=true. "
            "(To ADD new inputs, prefer the wizard / tool_context_intake; for "
            "free-form context notes, write under inputs/context/ — no force "
            "needed.)"
        ))
    if is_original_input and force:
        soft_warning = (
            f"Modified original input `{rel}` — provenance changed. Confirm "
            "the researcher approved this; the intake inventory is now stale "
            "(re-run mem_intake_regenerate)."
        )
    if rel.startswith("synthesis/") and p.exists() and not force:
        return _text(_error("synthesis/ files exist: pass force=true to overwrite."))

    # Versioned-artifact immutability gate. A file named `*_v<N>.<ext>`
    # carries an explicit version suffix BECAUSE edits are supposed to land
    # in a NEW version, not overwrite the existing one (which destroys the
    # prior version's provenance). When the AI tries to overwrite an existing
    # `_v<N>` artifact under workspace/ or synthesis/, refuse and point it at
    # the bumped name. force=true is the deliberate escape hatch (e.g. fixing
    # a typo in the SAME version before it's been used downstream).
    if (
        rel.startswith(("workspace/", "synthesis/"))
        and p.exists()
        and not force
        and is_versioned_name(p.name)
    ):
        bumped = suggest_version_bump(p) or next_version_name(p.name)
        return _text(_error(
            f"`{rel}` is a versioned artifact ({p.name}) that already exists. "
            "Editing a produced version in place overwrites its provenance — "
            f"write your changes as a NEW version instead: `{bumped}` "
            "(same directory). The _v<k> suffix exists so each revision is a "
            "distinct, traceable file. If you truly need to overwrite this "
            "exact version (e.g. a typo fix before it was used), pass "
            "force=true."
        ))

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(arguments["content"], encoding="utf-8")
    if rel.startswith("workspace/"):
        _update_manifest(root)
    payload = {"written": True, "checksum": compute_file_hash(p)}
    if soft_warning:
        payload["warning"] = soft_warning
    return _text(_success(payload))


def _handle_sys_file_list(name, arguments, root):
    from research_os.project_ops import LAZY_DIRS

    rel = arguments["directory"]
    try:
        p = _resolve_inside_root(root, rel)
    except WriteProtectedError as exc:
        return _text(_error(str(exc)))
    if not p.exists() or not p.is_dir():
        # A lazy directory that hasn't been materialised yet is NOT an
        # error — it just hasn't received its first artefact. Return an
        # empty list with a hint so protocols can detect the empty state
        # without retry loops.
        if rel.strip("/") in LAZY_DIRS:
            return _text(_success({
                "files": [],
                "empty": True,
                "lazy_dir": True,
                "hint": (
                    f"`{rel}` is created on first write. "
                    "Drop files here (or via the wizard) to materialise it."
                ),
            }))
        return _text(_error("Directory not found"))
    root_resolved = Path(root).resolve()
    files = [str(f.relative_to(root_resolved)) for f in p.rglob("*") if f.is_file()]
    return _text(_success({"files": files, "empty": not files}))


def _handle_sys_file_delete(name, arguments, root):
    try:
        p = _resolve_inside_root(root, arguments["filepath"])
    except WriteProtectedError as exc:
        return _text(_error(str(exc)))
    if not p.exists():
        return _text(_error("File or directory not found"))
    # Central write-permission gate — was previously bypassed for sys_file_delete.
    try:
        check_write_permitted(p, root=Path(root).resolve())
    except WriteProtectedError as exc:
        return _text(_error(str(exc)))
    if p.is_file():
        p.unlink()
        return _text(_success({"deleted": True}))
    try:
        p.rmdir()
        return _text(_success({"deleted": True, "type": "directory"}))
    except OSError as e:
        return _text(_error(f"Cannot delete directory: {e}"))


def _handle_sys_file_validate_md(name, arguments, root):
    from research_os.tools.actions.audit.md_audit import validate_md_template

    try:
        _resolve_inside_root(root, arguments["filepath"])
    except WriteProtectedError as exc:
        return _text(_error(str(exc)))
    res = validate_md_template(arguments["filepath"], arguments["protocol_name"], root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "Validation failed")))


def _handle_sys_path_create(name, arguments, root):
    from research_os.project_ops import create_numbered_experiment

    try:
        # The MCP handler defaults to enforcing
        # previous-step finalization. Researcher can opt out by passing
        # `allow_unfinalized_predecessor=true` (logged to override_log).
        allow_bypass = bool(arguments.get("allow_unfinalized_predecessor", False))
        res = create_numbered_experiment(
            root,
            arguments["name"],
            hypothesis=arguments.get("hypothesis", ""),
            branch_of=arguments.get("branch_of"),
            from_step=arguments.get("from_step"),
            enforce_predecessor_finalized=not allow_bypass,
        )
        if allow_bypass:
            from research_os.project_ops import log_override, validate_override_rationale
            thin = validate_override_rationale(arguments.get("override_rationale"))
            if thin is not None:
                return _text(thin)
            log_override(
                root,
                tool="sys_path_create",
                gate="enforce_predecessor_finalized",
                rationale=arguments.get("override_rationale"),
                extra={"new_step": res.get("path_id")},
            )
        return _text(_success(res))
    except Exception as e:
        return _text(_error(str(e)))


def _handle_sys_path_abandon(name, arguments, root):
    res = abandon_path(arguments["path_name"], arguments["rationale"], root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "abandon failed")))


def _handle_sys_path_list(name, arguments, root):
    return _text(_success(list_paths(root)))


def _handle_tool_path_finalize(name, arguments, root):
    from research_os.tools.actions.audit.step_literature import (
        audit_step_literature,
    )
    from research_os.tools.actions.state.path import finalize_path

    # First-gate
    # literature-loop check. Closes the gap where
    # literature_per_step was documented as pipeline-mandatory but
    # never enforced (autopilot skipped it). Override via
    # override_literature_gate=true + override_rationale.
    override_lit = bool(arguments.get("override_literature_gate", False))
    override_rationale = str(arguments.get("override_rationale", "")).strip()
    path_name = arguments.get("path_name")
    step_id = path_name if (path_name and path_name != "main") else None
    try:
        lit_audit = audit_step_literature(root, step_id=step_id)
    except Exception as e:
        lit_audit = {"status": "error", "message": str(e), "blockers": []}
    if (
        lit_audit.get("status") == "error"
        and lit_audit.get("blockers")
        and not (override_lit and override_rationale)
    ):
        msg = (
            f"tool_path_finalize blocked by tool_audit_step_literature "
            f"({len(lit_audit['blockers'])} blocker(s)). "
            "Either run research/literature_per_step OR pass "
            "override_literature_gate=true + override_rationale=... to "
            "proceed. See workspace/logs/step_literature_audit.md."
        )
        # Pass a STRING message (a dict here made envelope.error a dict);
        # stash the audit detail in the payload (env-04).
        env = _error(
            what=msg,
            why="the step literature gate has unresolved blocker(s)",
            next_action=(
                "run research/literature_per_step OR pass "
                "override_literature_gate=true + override_rationale=..."
            ),
        )
        env["payload"]["literature_audit"] = lit_audit
        return _text(env)

    res = finalize_path(arguments.get("path_name"), root)
    if isinstance(res, dict):
        res.setdefault("literature_audit", lit_audit)
        if override_lit and override_rationale:
            res["literature_override"] = {
                "override_literature_gate": True,
                "override_rationale": override_rationale,
            }
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "finalize failed")))


def _handle_tool_synthesis_curate_figures(name, arguments, root):
    from research_os.tools.actions.synthesis.curate import curate_figures

    mode = (arguments or {}).get("mode", "focal")
    res = curate_figures(root, mode=mode)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "curate failed")))


def _handle_sys_export_share_archive(name, arguments, root):
    """Run scripts/export_share_archive.py for the project root."""
    import subprocess as _sp
    import sys as _sys

    script = root / "scripts" / "export_share_archive.py"
    # Always (re)write the export script from the CURRENT template before
    # running it. Projects scaffolded before a security fix would otherwise
    # keep running a stale script — e.g. one that bundles the secret-bearing
    # inputs/researcher_config.yaml into the "share-safe" zip (3.2.10 A2).
    try:
        from research_os.project_ops import _EXPORT_PY_TEMPLATE
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(_EXPORT_PY_TEMPLATE, encoding="utf-8")
        try:
            script.chmod(0o755)
        except OSError:
            pass
    except Exception as e:
        return _text(_error(f"export script could not be refreshed: {e}"))

    cmd = [_sys.executable, str(script)]
    out_arg = arguments.get("out")
    if out_arg:
        # Guard against path-traversal: the export destination must live
        # inside the project root.
        try:
            _resolve_inside_root(root, str(out_arg))
        except WriteProtectedError as exc:
            return _text(_error(str(exc)))
        cmd += ["--out", str(out_arg)]
    if arguments.get("include_raw_data"):
        cmd += ["--include-raw-data"]
    try:
        res = _sp.run(cmd, capture_output=True, text=True, timeout=180, cwd=str(root))
        if res.returncode != 0:
            return _text(_error(
                f"export failed (rc={res.returncode}):\n"
                f"stdout:\n{res.stdout[-1000:]}\n"
                f"stderr:\n{res.stderr[-1000:]}"
            ))
        return _text(_success({"status": "success", "stdout": res.stdout.strip()}))
    except _sp.TimeoutExpired:
        return _text(_error("export timed out (>180s)"))
    except Exception as e:
        return _text(_error(f"export failed: {e}"))


def _handle_sys_export_ro_crate(name, arguments, root):
    """Emit ro-crate-metadata.json + codemeta.json at project root."""
    try:
        from research_os.tools.actions.state.ro_crate import (
            sys_export_ro_crate as _emit,
        )
    except Exception as e:
        return _text(_error(f"ro_crate module unavailable: {e}"))
    op = arguments.get("operation", "build")
    res = _emit(root, operation=op)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "ro_crate export failed")))


def _handle_sys_checkpoint_create(name, arguments, root):
    res = create_checkpoint(arguments.get("description", "manual"), root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "checkpoint failed")))


def _handle_sys_checkpoint_rollback(name, arguments, root):
    # rollback is destructive; if a rationale was supplied, enforce
    # the same min-quality bar as other override flags so audit trails
    # don't fill with 'TODO' / 'preview' placeholders.
    rationale = arguments.get("override_rationale")
    if rationale:
        from research_os.project_ops import validate_override_rationale
        thin = validate_override_rationale(rationale)
        if thin is not None:
            return _text(thin)
    res = rollback_checkpoint(arguments["checkpoint_id"], root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "rollback failed")))


def _handle_sys_checkpoint_list(name, arguments, root):
    res = list_checkpoints(root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "checkpoint list failed")))


def _handle_sys_where(name, arguments, root):
    """Lightweight orientation — ~30 tokens. Cheaper than sys_boot.

    Returns: project_root (basename), tier (current_tier), active_plan
    (step/total or None), unresolved_blocks (audit ledger count),
    last_protocol (most recent protocol_history entry name).

    Designed for mid-session "where am I?" checks by small / long-context
    models that don't need the full sys_boot payload.
    """
    payload: dict[str, Any] = {
        "project_root": Path(root).name,
        "tier": None,
        "active_plan": None,
        "unresolved_blocks": 0,
        "last_protocol": None,
    }

    # current_tier
    try:
        from research_os.tools.actions.state.tier_state import get_current_tier

        payload["tier"] = get_current_tier(Path(root))
    except Exception:
        pass

    # active_plan — step / total
    try:
        plan_path = Path(root) / ".os_state" / "active_plan.json"
        if plan_path.exists():
            plan = json.loads(plan_path.read_text())
            decomp = plan.get("decomposition") or []
            payload["active_plan"] = {
                "step": int(plan.get("current_step", 1)),
                "total": len(decomp),
            }
    except Exception:
        pass

    # unresolved_blocks — count of BLOCKer-severity findings in the ledger
    try:
        ledger = Path(root) / "workspace" / "logs" / ".audit_findings.jsonl"
        if ledger.exists():
            count = 0
            for raw in ledger.read_text().splitlines():
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                sev = str(obj.get("severity", "")).upper()
                if sev in ("BLOCK", "BLOCKER"):
                    count += 1
            payload["unresolved_blocks"] = count
    except Exception:
        pass

    # last_protocol — most recent history entry
    try:
        from research_os.tools.actions.protocol import get_protocol_history

        hist = get_protocol_history(Path(root), limit=1)
        entries = hist.get("entries", []) or []
        if entries:
            last = entries[-1]
            payload["last_protocol"] = (
                last.get("protocol") or last.get("protocol_name")
            )
    except Exception:
        pass

    return _text(_success(payload))


def _handle_sys_path_rename(name, arguments, root):
    from research_os.tools.actions.state.path import rename_path

    new_label = arguments.get("new_name") or arguments.get("new_label")
    if not arguments.get("path_name") or not new_label:
        return _text(_error(
            "operation='rename' requires path_name= and new_name= "
            "(the new human label; the NN_ step number is preserved)."
        ))
    res = rename_path(arguments["path_name"], new_label, root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "rename failed")))


def _handle_sys_path_group(name, arguments, root):
    from research_os.tools.actions.state.path import group_paths

    container_name = arguments.get("name") or arguments.get("path_name")
    steps = arguments.get("steps") or arguments.get("step_ids")
    if not container_name or not steps:
        return _text(_error(
            "operation='group' requires name=<descriptive container label> "
            "and steps=[<path_id>, …] — the flat steps to consolidate into a "
            "workspace/<name>_PATH_<k>/ folder (numbering is preserved)."
        ))
    if isinstance(steps, str):
        steps = [s.strip() for s in steps.split(",") if s.strip()]
    res = group_paths(container_name, list(steps), root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "group failed")))


def _handle_sys_path(name, arguments, root):
    """Unified path dispatcher (create | abandon | list | rename | group)."""
    legacy = {
        "sys_path_create": "create",
        "sys_path_abandon": "abandon",
        "sys_path_list": "list",
    }
    operation = arguments.get("operation") or legacy.get(name)
    if not operation:
        return _text(_error(
            "sys_path requires operation='create'|'abandon'|'list'|'rename'|'group'"
        ))
    if operation == "create":
        return _handle_sys_path_create(name, arguments, root)
    if operation == "abandon":
        return _handle_sys_path_abandon(name, arguments, root)
    if operation == "list":
        return _handle_sys_path_list(name, arguments, root)
    if operation == "rename":
        return _handle_sys_path_rename(name, arguments, root)
    if operation == "group":
        return _handle_sys_path_group(name, arguments, root)
    return _text(_error(f"Unknown sys_path operation '{operation}'"))


def _daemon_http_get(base_url, path, timeout):
    """GET base_url+path and return parsed JSON, or None on any failure.

    Thin wrapper over the canonical ``daemon_bridge.http_get`` (kept as a
    local name so existing tests that monkeypatch ``mw._daemon_http_get``
    keep working). Pure stdlib; the daemon is an opaque local HTTP service —
    the reasoning layer never imports research_os.daemon.
    """
    from research_os.server import daemon_bridge as _bridge

    return _bridge.http_get(base_url, path, timeout)


def _handle_sys_daemon(name, arguments, root):
    """Bridge the MCP session to a running daemon (Phase 3).

    Discovers the daemon via its self-advertised descriptor at
    <root>/.os_state/daemon.json, confirms the PID is alive, then pulls
    the read-only /v1/orient + /v1/jobs telemetry over localhost HTTP.
    Degrades to running=false with a start hint when nothing is running.

    Stdlib-only by design: the reasoning layer must not import the daemon
    package, so this re-implements the trivial descriptor read rather than
    importing research_os.daemon.discovery (same on-disk SHAPE, no import).
    """
    timeout = arguments.get("timeout")
    try:
        timeout = float(timeout) if timeout is not None else 2.0
    except (TypeError, ValueError):
        timeout = 2.0
    timeout = max(0.1, min(timeout, 30.0))

    not_running = {
        "running": False,
        "hint": "No daemon running for this project. Start one with "
        "'research-os daemon start' to enable background jobs, live "
        "freshness, and a recommended next action.",
    }

    desc_path = Path(root) / ".os_state" / "daemon.json"
    try:
        if not desc_path.exists():
            return _text(_success(not_running))
        desc = json.loads(desc_path.read_text(encoding="utf-8"))
        if not isinstance(desc, dict):
            return _text(_success(not_running))
    except (OSError, ValueError):
        return _text(_success(not_running))

    # Confirm the advertised PID is actually alive — a stale descriptor
    # (daemon crashed without cleanup) must not read as "running".
    pid = desc.get("pid")
    if isinstance(pid, int):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            stale = dict(not_running)
            stale["hint"] = (
                "Found a stale daemon descriptor (pid %s not alive). "
                "Start a fresh daemon with 'research-os daemon start'." % pid
            )
            return _text(_success(stale))
        except PermissionError:
            pass  # alive, owned by another user
        except OSError:
            pass

    base_url = desc.get("base_url") or f"http://{desc.get('host')}:{desc.get('port')}"
    orient = _daemon_http_get(base_url, "/v1/orient", timeout)
    jobs = _daemon_http_get(base_url, "/v1/jobs", timeout)
    # Also surface the execution bound (resource budget) and any
    # undelivered researcher notifications, so the AI sees — in ONE call —
    # the budget it must cite before a big run and what the researcher was
    # paged about. Both are read-only; failures degrade to absent fields.
    sandbox = _daemon_http_get(base_url, "/v1/sandbox", timeout)
    notifications = _daemon_http_get(
        base_url, "/v1/notifications?undelivered=true&limit=10", timeout
    )

    if orient is None and jobs is None:
        # Descriptor present + pid alive but HTTP unreachable: the daemon
        # is starting up or bound elsewhere. Report reachable=false rather
        # than pretend it is fully up.
        return _text(_success({
            "running": True,
            "reachable": False,
            "base_url": base_url,
            "version": desc.get("version"),
            "pid": pid,
            "hint": "Daemon process is alive but its HTTP surface did not "
            "answer in time; it may still be starting.",
        }))

    payload: dict[str, Any] = {
        "running": True,
        "reachable": True,
        "base_url": base_url,
        "version": desc.get("version"),
        "pid": pid,
        "started_at": desc.get("started_at"),
    }
    if isinstance(orient, dict):
        payload["narrative"] = orient.get("narrative")
        payload["recommended_next_action"] = orient.get("recommended_next_action")
        payload["field"] = orient.get("field")
    if isinstance(jobs, dict):
        items = jobs.get("jobs") or jobs.get("items") or []
        # The daemon already computes status counts; prefer them, fall
        # back to counting the returned items if absent.
        counts = jobs.get("counts")
        if not isinstance(counts, dict):
            counts = {}
            for j in items if isinstance(items, list) else []:
                st = str((j or {}).get("status", "unknown")).lower()
                counts[st] = counts.get(st, 0) + 1
        payload["jobs"] = {
            "total": jobs.get("total", len(items) if isinstance(items, list) else 0),
            "by_status": counts,
        }
    if isinstance(sandbox, dict):
        # The execution bound: strongest isolation tier + the resource
        # budget the AI must respect (and cite) before a heavy run.
        payload["sandbox"] = {
            "best_tier": sandbox.get("best_tier"),
            "resource_budget": sandbox.get("resource_budget"),
            "effective_limits": sandbox.get("effective_limits"),
        }
    if isinstance(notifications, dict):
        undelivered = notifications.get("notifications") or []
        if undelivered:
            # Surface what the researcher was paged about but may not have
            # received — high-signal for the AI to repeat or escalate.
            payload["undelivered_notifications"] = [
                {"level": n.get("level"), "title": n.get("title"),
                 "ts": n.get("ts")}
                for n in undelivered if isinstance(n, dict)
            ]
    return _text(_success(payload))


def _handle_sys_consent(name, arguments, root):
    """In-band consent loop with a running daemon (the consent_required path).

    A floor gate under a daemon returns what='consent_required' with a
    gate_key + arg_fingerprint. This tool lets the agent (a) request consent
    for that exact action, (b) check pending/granted status, (c) fetch a
    minted token once the researcher approves — all over the daemon's
    localhost HTTP surface, WITHOUT importing the daemon package.

    When no daemon is running, returns available=false (the gate degrades to
    confirmed=true anyway, so there's nothing to request).
    """
    from research_os.server import daemon_bridge as _bridge

    action = (arguments.get("action") or "").strip().lower()
    timeout = arguments.get("timeout")
    try:
        timeout = float(timeout) if timeout is not None else 2.0
    except (TypeError, ValueError):
        timeout = 2.0
    timeout = max(0.1, min(timeout, 30.0))

    base_url = _bridge.daemon_base_url(root)
    if not base_url:
        return _text(_success({
            "available": False,
            "hint": "No daemon is enforcing consent for this project. If a "
                    "floor gate blocked you, it degrades to confirmed=true — "
                    "retry with confirmed=true once the researcher authorizes.",
        }))

    if action == "request":
        gate_key = arguments.get("gate_key")
        fingerprint = arguments.get("arg_fingerprint")
        if not gate_key or not fingerprint:
            return _text(_error(
                "gate_key and arg_fingerprint are required for action='request' "
                "(both are in the consent_required error's next step)"
            ))
        status, body = _bridge.http_post(base_url, "/v1/consent/request", {
            "gate_key": str(gate_key),
            "arg_fingerprint": str(fingerprint),
            "tool": str(arguments.get("tool", "")),
            "reason": str(arguments.get("reason", "")),
        }, timeout)
        if status == 201 and isinstance(body, dict):
            req = body.get("request") or {}
            return _text(_success({
                "available": True,
                "requested": True,
                "request_id": req.get("id"),
                "next": "Tell the researcher exactly what needs approval and "
                        "why. They approve with 'research-os daemon consent "
                        "approve <request_id>'. Then call "
                        "sys_consent(action='token', gate_key=..., "
                        "arg_fingerprint=...) and retry with the token.",
            }))
        return _text(_error(
            f"consent request failed (status={status}): "
            f"{(body or {}).get('error', 'unknown')}"
        ))

    if action == "status":
        pending = _bridge.http_get(base_url, "/v1/consent/pending", timeout) or {}
        grants = _bridge.http_get(base_url, "/v1/consent/grants", timeout) or {}
        return _text(_success({
            "available": True,
            "pending": pending.get("requests") or pending.get("pending") or [],
            "grants": grants.get("grants") or [],
        }))

    if action == "token":
        gate_key = arguments.get("gate_key")
        fingerprint = arguments.get("arg_fingerprint")
        if not gate_key or not fingerprint:
            return _text(_error(
                "gate_key and arg_fingerprint are required for action='token'"
            ))
        grants = _bridge.http_get(base_url, "/v1/consent/grants", timeout) or {}
        token = None
        for g in (grants.get("grants") or []):
            if not isinstance(g, dict):
                continue
            # Match the exact action; skip grants the daemon already marked
            # consumed. (The gate does the authoritative one-shot check via
            # its spent-log on retry; this is the best-available token.)
            if (g.get("gate_key") == str(gate_key)
                    and g.get("arg_fingerprint") == str(fingerprint)
                    and not g.get("consumed")):
                token = g.get("token")
                break
        if token:
            return _text(_success({
                "available": True,
                "consent_token": token,
                "next": "Retry the blocked tool with consent_token=<this>. "
                        "It is one-shot — burned on first use.",
            }))
        return _text(_success({
            "available": True,
            "consent_token": None,
            "hint": "No minted token yet for this action. The researcher has "
                    "not approved, or it was already consumed. Check "
                    "sys_consent(action='status').",
        }))

    return _text(_error(
        f"unknown action {action!r}; use 'request', 'status', or 'token'"
    ))


def _handle_sys_workspace_mode(name, arguments, root):
    """Report or transition the workspace mode (first-class, additive)."""
    op = (arguments.get("operation") or "status").strip().lower()
    if op == "status":
        from research_os.tools.actions.state.mode_transition import workspace_mode_status

        return _text(_success(workspace_mode_status(Path(root))))
    if op == "transition":
        to_mode = arguments.get("to") or arguments.get("mode") or ""
        if not to_mode:
            return _text(_error("operation='transition' requires `to` (target mode)"))
        from research_os.tools.actions.state.mode_transition import transition_workspace_mode

        # plan unless explicitly applying (confirm=true / plan_only=false)
        plan_only = not (
            bool(arguments.get("confirm")) or arguments.get("plan_only") is False
        )
        res = transition_workspace_mode(
            Path(root), to_mode, plan_only=plan_only,
            rationale=arguments.get("rationale", ""),
        )
        if res.get("status") == "error":
            return _text(_error(res.get("message", "transition failed")))
        return _text(_success(res))
    return _text(_error(f"unknown operation '{op}'. Use 'status' or 'transition'."))


HANDLERS = {
    "sys_workspace_tree": _handle_sys_workspace_tree,
    "sys_state_get": _handle_sys_state_get,
    "sys_file_read": _handle_sys_file_read,
    "sys_file_write": _handle_sys_file_write,
    "sys_file_list": _handle_sys_file_list,
}
