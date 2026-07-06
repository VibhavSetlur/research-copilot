"""Handlers — research_exec sub-domain.

Carved out of handlers/research.py to stay under the 600-line ceiling.
"""
from __future__ import annotations

from .._handlers_runtime import *  # noqa: F401,F403
from research_os.server import daemon_bridge as _bridge


# ── §12.5 daemon-routing helpers ─────────────────────────────────────────────

_DAEMON_UNAVAILABLE_NOTE = (
    "Daemon unavailable or not authorized — this run was executed natively "
    "and is NOT journaled (no provenance/CAS/lineage). "
    "Start the daemon with the gateway enabled to journal runs."
)


def _try_daemon_run(
    root,
    command,
    *,
    cwd=None,
    env=None,
    inputs=None,
    timeout=2.0,
):
    """Attempt to submit ``command`` (argv list) as a journaled daemon run.

    Returns the daemon's response dict on success (HTTP 201), or ``None``
    to signal the caller should degrade-open to native subprocess execution.

    Fail-safe: any transport / auth / availability problem → ``None`` (never
    raises). The submit timeout is short (2 s) so a slow/absent daemon never
    stalls a tool call.

    Auth flow: reads the optional gateway bearer token via
    ``daemon_bridge.gateway_bearer``; when the token is set it is added as an
    ``Authorization: Bearer`` header.  When the daemon's gateway is disabled
    the POST returns 503 → ``None`` → degrade.  When no token is set and the
    gateway requires auth the POST returns 401 → ``None`` → degrade.  In all
    degrade cases the caller falls through to the existing native subprocess
    path and (if a daemon URL was configured) appends ``_DAEMON_UNAVAILABLE_NOTE``
    to the payload.

    SEAM: imports only ``research_os.server.daemon_bridge`` — never
    ``research_os.daemon``.
    """
    try:
        base = _bridge.daemon_base_url(root)
        if not base:
            return None
        hdrs: dict[str, str] = {}
        token = _bridge.gateway_bearer(root)
        if token:
            hdrs["Authorization"] = f"Bearer {token}"
        # FIX 3: only include root/cwd in payload when not None — avoids
        # sending the literal string "None" to the daemon.
        payload: dict = {"cmd": command}
        if cwd is not None:
            payload["cwd"] = cwd
        if root is not None:
            payload["root"] = str(root)
        if env is not None:
            payload["env"] = env
        if inputs is not None:
            payload["inputs"] = inputs
        status, body = _bridge.http_post(
            base, "/v1/runs", payload, timeout, headers=hdrs or None
        )
        if status == 201 and isinstance(body, dict):
            return body
        return None
    except Exception:  # noqa: BLE001 — fail-safe: any failure → degrade
        return None


_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})


def _await_daemon_run(root, run_id, *, timeout, poll=0.25):
    """Poll GET /v1/runs/<run_id>?log=1 until terminal or timeout.

    Returns a payload dict mirroring the native exec tool's return shape::

        {
            "stdout": <str>,   # joined log lines (daemon merges stdout+stderr)
            "stderr": "",      # empty — daemon merges into one log stream
            "exit_code": <int>,
            "code": <int>,     # alias for exit_code
            "status": <"success"|"error">,
            "run_id": <str>,
            "journaled": True,
            "note": <str>,     # provenance URL hint
        }

    If the run hasn't reached terminal by ``timeout`` seconds, returns a dict
    with ``status="running"`` + ``run_id`` + a note (does NOT hang forever,
    does NOT kill the run).

    Returns ``None`` if the daemon becomes unreachable during polling — the
    caller should then degrade to native execution.

    SEAM: only uses daemon_bridge; never imports research_os.daemon.
    """
    import time as _time

    try:
        base = _bridge.daemon_base_url(root)
        if not base:
            return None
        hdrs: dict[str, str] = {}
        token = _bridge.gateway_bearer(root)
        if token:
            hdrs["Authorization"] = f"Bearer {token}"

        deadline = _time.monotonic() + timeout
        while True:
            status_code, manifest = _bridge.http_get(
                base, f"/v1/runs/{run_id}?log=1", timeout=5.0, headers=hdrs or None
            )
            if status_code is None or manifest is None:
                # Daemon vanished mid-poll → degrade to native
                return None

            run_status = (manifest.get("status") or "").lower()
            if run_status in _TERMINAL_STATUSES:
                # Map daemon status → exit_code
                result = manifest.get("result") or {}
                if isinstance(result, dict):
                    rc = result.get("returncode")
                else:
                    rc = None
                if rc is None:
                    rc = 0 if run_status == "succeeded" else 1
                try:
                    exit_code = int(rc)
                except (TypeError, ValueError):
                    exit_code = 0 if run_status == "succeeded" else 1

                # Daemon merges stdout+stderr into one log stream (log.txt).
                log_lines = manifest.get("log") or []
                stdout = "\n".join(str(ln) for ln in log_lines)

                return {
                    "stdout": stdout,
                    "stderr": "",
                    "exit_code": exit_code,
                    "code": exit_code,
                    "status": "success" if exit_code == 0 else "error",
                    "run_id": run_id,
                    "journaled": True,
                    "note": (
                        f"Full output and provenance at /v1/runs/{run_id}. "
                        "This run was executed and journaled by the daemon."
                    ),
                }

            # Not yet terminal — check deadline before sleeping.
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                return {
                    "stdout": "",
                    "stderr": "",
                    "exit_code": None,
                    "code": None,
                    "status": "running",
                    "run_id": run_id,
                    "journaled": True,
                    "note": (
                        f"Run {run_id!r} is still executing after {timeout}s. "
                        f"Poll /v1/runs/{run_id} for completion; "
                        "the daemon will continue running it."
                    ),
                }

            _time.sleep(min(poll, remaining))
    except Exception:  # noqa: BLE001 — fail-safe: polling failure → degrade
        return None

__all__ = [
    "_handle_tool_python_exec",
    "_handle_tool_script_exec",
    "_handle_tool_package_install",
    "_handle_tool_slurm_submit",
    "_handle_tool_slurm_status",
    "_handle_tool_slurm_fetch",
    "_handle_tool_slurm_list",
    "_handle_tool_task",
    "_handle_tool_task_run",
    "_handle_tool_task_status",
    "_handle_tool_task_list",
    "_handle_tool_task_kill",
    "_handle_tool_notebook_exec",
    "_handle_tool_rmarkdown_render",
    "_handle_tool_scratch",
    "_handle_tool_scratch_write",
    "_handle_tool_scratch_run",
    "_handle_tool_scratch_list",
    "_handle_tool_scratch_clear",
    "_handle_tool_workspace_repair",
    "_handle_tool_migrate_audit",
    "_handle_tool_migrate_apply",
    "_handle_tool_structure_audit",
]

def _handle_tool_python_exec(name, arguments, root):
    arguments = arguments or {}
    data_op = arguments.get("data_operation")
    if data_op:
        # Delegate to tool_data: map data_operation → tool_data's `operation`.
        # Pass through filepath/n_rows/strategy/output_format as-is.
        from .research_search import _handle_tool_data
        mapped = dict(arguments)
        mapped["operation"] = data_op  # sample | profile | convert
        return _handle_tool_data(name, mapped, root)

    p = root / arguments["script_path"]
    if not p.exists():
        return _text(_error(
            what=f"script not found at {p}",
            why="the script_path is resolved relative to the project root",
            next_action="call sys_file_list or sys_workspace_tree to confirm the path",
        ))
    if not p.is_file():
        return _text(_error(
            what=f"script_path points to a directory, not a file: {p}",
            why="tool_python_exec runs a single .py file",
            next_action="pass the path to the .py script itself",
        ))

    step_name = p.stem
    log_dir = root / "workspace" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    exec_log_path = log_dir / f"{step_name}_exec.log"

    cmd = [sys.executable, str(p)]
    timeout = int(arguments.get("timeout", 600))

    # FIX 7: compute once — is a daemon configured at all?
    daemon_configured = _bridge.daemon_base_url(root) is not None

    # §12.5 — try to route through the daemon journal first.
    # FIX 1+2: submit then POLL to completion so the synchronous contract is
    # preserved — the AI gets stdout/stderr/exit_code back on this call.
    if daemon_configured:
        daemon_resp = _try_daemon_run(root, cmd, cwd=str(p.parent))
        if daemon_resp is not None:
            run_id = daemon_resp.get("run_id")
            awaited = _await_daemon_run(root, run_id, timeout=timeout)
            if awaited is not None:
                # Return the awaited payload (success or error shape).
                if awaited.get("status") == "success":
                    return _text(_success(awaited))
                if awaited.get("status") == "running":
                    # Timed out but run continues — return partial info.
                    return _text(_success(awaited))
                # error (non-zero exit)
                tail = (awaited.get("stdout") or "").strip().splitlines()[-5:]
                msg = f"python exited with code {awaited.get('exit_code')}: " + " | ".join(tail)
                env = _error(msg)
                env["payload"].update(awaited)
                env["data"] = env["payload"]
                return _text(env)
            # await failed (daemon vanished) → fall through to native below

    # Degrade-open: daemon absent / gateway off / 503 / lost mid-poll → run natively.
    try:
        res = subprocess.run(
            cmd,
            cwd=str(p.parent),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return _text(_error(f"Script timed out after {timeout}s"))

    with open(exec_log_path, "a") as f:
        f.write(
            f"--- Executed at {now_iso()} ---\n"
            f"Command: {' '.join(cmd)}\n"
            f"Return Code: {res.returncode}\n"
            f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}\n\n"
        )

    payload = {
        "stdout": res.stdout,
        "stderr": res.stderr,
        "code": res.returncode,
        "exit_code": res.returncode,
    }
    # FIX 7: only attach the degradation warning when a daemon WAS configured
    # but the run fell back to native (routing/observation failed).
    # When no daemon is configured at all, native execution is the normal path
    # and the warning would be noise.
    if daemon_configured:
        payload["warning"] = _DAEMON_UNAVAILABLE_NOTE

    if res.returncode == 0:
        return _text(_success(payload))

    # Non-zero exit → report status:error to match the R/Julia/Bash siblings,
    # but keep the run streams in the payload so the AI can debug.
    tail = (res.stderr or res.stdout or "").strip().splitlines()[-5:]
    msg = f"python exited with code {res.returncode}: " + " | ".join(tail)
    env = _error(msg)
    env["payload"].update(payload)
    env["data"] = env["payload"]
    return _text(env)


def _handle_tool_bash_exec(name, arguments, root):
    """tool_bash_exec with optional task_operation/background dispatch.

    If `task_operation` is present (run/status/list/kill) OR `background` is
    truthy, delegate to _handle_tool_task (maps task_operation → operation).
    Otherwise execute normally as a bash script.
    """
    arguments = arguments or {}
    task_op = arguments.get("task_operation")
    background = arguments.get("background")
    if task_op or background:
        mapped = dict(arguments)
        mapped["operation"] = task_op if task_op else "run"
        return _handle_tool_task(name, mapped, root)
    return _handle_tool_script_exec("tool_bash_exec", arguments, root)


def _handle_tool_script_exec(name, arguments, root):
    import shutil

    from research_os.tools.actions.exec.scripts import (
        execute_bash_script,
        execute_julia_script,
        execute_r_script,
    )

    timeout = int(arguments.get("timeout", 600))
    script_path = arguments["script_path"]
    fn = {
        "tool_r_exec": execute_r_script,
        "tool_julia_exec": execute_julia_script,
        "tool_bash_exec": execute_bash_script,
    }[name]

    # FIX 7: compute once — is a daemon configured at all?
    daemon_configured = _bridge.daemon_base_url(root) is not None

    # §12.5 — build the same argv the native impl would use, then attempt to
    # route through the daemon journal.  Mirror scripts.py exactly so that
    # daemon and native runs are equivalent.
    # FIX 1+2: submit then POLL to completion (synchronous contract preserved).
    p = root / script_path
    _daemon_cmd: list[str] | None = None
    if name == "tool_bash_exec":
        # execute_bash_script uses ["/bin/bash", "-e", str(p)]
        _daemon_cmd = ["/bin/bash", "-e", str(p)]
    elif name == "tool_r_exec":
        if shutil.which("Rscript"):
            _daemon_cmd = ["Rscript", str(p)]
    elif name == "tool_julia_exec":
        if shutil.which("julia"):
            _julia_cmd = ["julia"]
            if (p.parent / "Project.toml").exists():
                _julia_cmd.append("--project=" + str(p.parent))
            elif (root / "environment" / "Project.toml").exists():
                _julia_cmd.append("--project=" + str(root / "environment"))
            _julia_cmd.append(str(p))
            _daemon_cmd = _julia_cmd

    if daemon_configured and _daemon_cmd is not None:
        daemon_resp = _try_daemon_run(root, _daemon_cmd, cwd=str(p.parent))
        if daemon_resp is not None:
            run_id = daemon_resp.get("run_id")
            awaited = _await_daemon_run(root, run_id, timeout=timeout)
            if awaited is not None:
                if awaited.get("status") == "success":
                    return _text(_success(awaited))
                if awaited.get("status") == "running":
                    return _text(_success(awaited))
                # Non-zero exit — return error envelope
                return _text(_error(
                    f"{name} exited with code {awaited.get('exit_code')}"
                ))
            # await failed (daemon vanished) → fall through to native

    # Degrade-open: daemon absent / gateway off / 503 / lost mid-poll → run natively.
    res = fn(script_path, root, timeout)
    if res.get("status") == "error":
        return _text(_error(res.get("message", "execution failed")))
    # FIX 7: only add warning when daemon was configured but we fell back.
    if daemon_configured:
        res["warning"] = _DAEMON_UNAVAILABLE_NOTE
    return _text(_success(res))


def _handle_tool_package_install(name, arguments, root):
    packages = arguments["packages"]
    res = package_install(packages)
    if res.get("status") == "success":
        req_path = root / "environment" / "requirements.txt"
        req_path.parent.mkdir(parents=True, exist_ok=True)
        existing = req_path.read_text().splitlines() if req_path.exists() else []
        with open(req_path, "a") as f:
            for pkg in packages:
                if pkg not in existing:
                    f.write(f"{pkg}\n")
    return _text(_success(res))


def _handle_tool_slurm_submit(name, arguments, root):
    from research_os.tools.actions.exec.cluster import submit_slurm

    # §12.5 NOTE: SLURM submissions are kept on the native path in this phase.
    # submit_slurm generates a batch script, calls sbatch, and records the
    # returned job_id in the project state — bypassing that logic to route
    # through the daemon's local subprocess runner would break the bookkeeping
    # (job_id tracking, dependency resolution, array indexing).  SLURM is its
    # own execution backend; the daemon's /v1/runs runner is a local-subprocess
    # journal and cannot model detached scheduler jobs.
    # TODO §12.5: journal slurm submissions through daemon once the runner
    # models detached scheduler jobs (e.g. a dedicated "slurm_job" run type
    # that records the sbatch argv + returned job_id without re-executing it).
    res = submit_slurm(
        root,
        step_id=arguments.get("step_id"),
        cmd=arguments["cmd"],
        job_name=arguments.get("job_name"),
        cpus=arguments.get("cpus"),
        mem=arguments.get("mem"),
        time_limit=arguments.get("time_limit"),
        partition=arguments.get("partition"),
        gpus=arguments.get("gpus"),
        array=arguments.get("array"),
        dependency=arguments.get("dependency"),
        modules=arguments.get("modules"),
        conda_env=arguments.get("conda_env"),
        extra_sbatch=arguments.get("extra_sbatch"),
    )
    if res.get("status") == "success":
        res["warning"] = (
            "SLURM jobs are not yet journaled through the daemon "
            "(the daemon runner cannot model detached scheduler jobs). "
            "This sbatch submission is NOT recorded in the daemon journal."
        )
        return _text(_success(res))
    return _text(_error(res.get("message", "slurm_submit failed")))


def _handle_tool_slurm_status(name, arguments, root):
    from research_os.tools.actions.exec.cluster import status_slurm

    return _text(_success(status_slurm(root, job_id=arguments.get("job_id"))))


def _handle_tool_slurm_fetch(name, arguments, root):
    from research_os.tools.actions.exec.cluster import fetch_slurm

    return _text(_success(fetch_slurm(
        root, arguments["job_id"],
        poll_interval=int(arguments.get("poll_interval", 30)),
        max_wait=int(arguments.get("max_wait", 7200)),
    )))


def _handle_tool_slurm_list(name, arguments, root):
    from research_os.tools.actions.exec.cluster import list_slurm

    return _text(_success(list_slurm(root)))


def _handle_tool_task(name, arguments, root):
    """Unified background-task dispatcher.

    Operations:
      run    → tool_task_run    (spawn a real background subprocess)
      status → tool_task_status (check task status + tail of log)
      list   → tool_task_list   (list all known background tasks)
      kill   → tool_task_kill   (signal-terminate a running task)

    Every legacy ``tool_task_run`` / ``tool_task_status`` /
    ``tool_task_list`` / ``tool_task_kill`` name is aliased to this
    entry point and has its operation injected via
    ``_ALIAS_PARAM_INJECTION`` so callers (researchers, scripts,
    protocols) using the older per-operation names keep working
    unchanged.
    """
    op = arguments.get("operation")
    if not op:
        return _text(_error(
            "tool_task requires operation='run'|'status'|'list'|'kill'."
        ))
    if op == "run":
        return _handle_tool_task_run(name, arguments, root)
    if op == "status":
        return _handle_tool_task_status(name, arguments, root)
    if op == "list":
        return _handle_tool_task_list(name, arguments, root)
    if op == "kill":
        return _handle_tool_task_kill(name, arguments, root)
    return _text(_error(
        f"tool_task: unknown operation '{op}'. "
        "Valid: run | status | list | kill."
    ))


def _handle_tool_task_run(name, arguments, root):
    import shlex

    from research_os.tools.actions.exec.tasks import task_run

    # §12.5 — op=run is genuinely ASYNCHRONOUS by design: tool_task always
    # returned a task_id (never output), so returning a daemon run_id is the
    # correct equivalent.  Do NOT poll — fire-and-forget is the contract here.
    raw_command = arguments["command"]
    if isinstance(raw_command, str):
        argv = shlex.split(raw_command)
    else:
        argv = list(raw_command)

    # FIX 7: compute once — is a daemon configured at all?
    daemon_configured = _bridge.daemon_base_url(root) is not None

    if daemon_configured:
        daemon_resp = _try_daemon_run(
            root, argv,
            cwd=arguments.get("cwd"),
        )
        if daemon_resp is not None:
            # fire-and-forget: return the run_id so the AI can poll separately.
            return _text(_success({
                "journaled": True,
                "run_id": daemon_resp.get("run_id"),
                "status": daemon_resp.get("status", "submitted"),
                "note": (
                    f"Background task submitted to the daemon journal "
                    f"(run_id={daemon_resp.get('run_id')!r}). "
                    "Poll /v1/runs/<run_id> for status and logs."
                ),
            }))

    # Degrade-open: daemon absent / gateway off → run natively via task_run.
    res = task_run(
        arguments["command"],
        root,
        cwd=arguments.get("cwd"),
        description=arguments.get("description", ""),
    )
    if res.get("status") == "success":
        # FIX 7: only add warning when daemon was configured but we fell back.
        if daemon_configured:
            res["warning"] = _DAEMON_UNAVAILABLE_NOTE
        return _text(_success(res))
    return _text(_error(res.get("message", "task_run failed")))


def _handle_tool_task_status(name, arguments, root):
    from research_os.tools.actions.exec.tasks import task_status

    res = task_status(
        arguments["task_id"], root, tail_lines=int(arguments.get("tail_lines", 50))
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "task_status failed")))


def _handle_tool_task_list(name, arguments, root):
    from research_os.tools.actions.exec.tasks import task_list

    res = task_list(root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "task_list failed")))


def _handle_tool_task_kill(name, arguments, root):
    from research_os.tools.actions.exec.tasks import task_kill

    res = task_kill(
        arguments["task_id"], root, signal_name=arguments.get("signal_name", "TERM")
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "task_kill failed")))


def _handle_tool_notebook_exec(name, arguments, root):
    from research_os.tools.actions.exec.notebook import execute_notebook

    # §12.5 NOTE: notebook daemon routing is intentionally skipped in this
    # phase.  The preferred native path uses the papermill Python API
    # (pm.execute_notebook), not a simple single subprocess, so there is no
    # clean argv to hand to the daemon runner without diverging from the native
    # invocation.  The fallback path does use a subprocess
    # (jupyter nbconvert --execute) but it is only reached when papermill is
    # absent; routing only the fallback branch would create an inconsistent
    # API surface.  Until the daemon's runner supports notebook-specific
    # execution (e.g. via a papermill plugin or a first-class notebook job
    # type), notebook runs execute natively and carry an audit note.
    res = execute_notebook(
        arguments["notebook_path"],
        root,
        timeout=int(arguments.get("timeout", 1800)),
        kernel=arguments.get("kernel", "python3"),
        parameters=arguments.get("parameters"),
        output_path=arguments.get("output_path"),
    )
    if res.get("status") == "success":
        res["warning"] = (
            "Notebook runs are not yet journaled through the daemon "
            "(papermill API path — no single CLI argv to submit). "
            "This run is NOT recorded in the daemon journal."
        )
        return _text(_success(res))
    return _text(_error(res.get("message", "notebook exec failed")))


def _handle_tool_rmarkdown_render(name, arguments, root):
    from research_os.tools.actions.exec.notebook import render_rmarkdown

    res = render_rmarkdown(
        arguments["doc_path"],
        root,
        output_format=arguments.get("output_format", "html_document"),
        timeout=int(arguments.get("timeout", 1800)),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "rmarkdown render failed")))


def _handle_tool_scratch(name, arguments, root):
    """Unified scratch-sandbox dispatcher.

    Operations:
      write → tool_scratch_write (write a file under workspace/scratch/)
      run   → tool_scratch_run   (execute a script in workspace/scratch/)
      list  → tool_scratch_list  (list current scratch files)
      clear → tool_scratch_clear (wipe scratch contents)

    Every legacy ``tool_scratch_write`` / ``tool_scratch_run`` /
    ``tool_scratch_list`` / ``tool_scratch_clear`` name is aliased to
    this entry point and has its operation injected via
    ``_ALIAS_PARAM_INJECTION`` so callers (researchers, scripts,
    protocols) using the older per-operation names keep working
    unchanged.
    """
    op = arguments.get("operation")
    if not op:
        return _text(_error(
            "tool_scratch requires operation='write'|'run'|'list'|'clear'."
        ))
    if op == "write":
        return _handle_tool_scratch_write(name, arguments, root)
    if op == "run":
        return _handle_tool_scratch_run(name, arguments, root)
    if op == "list":
        return _handle_tool_scratch_list(name, arguments, root)
    if op == "clear":
        return _handle_tool_scratch_clear(name, arguments, root)
    return _text(_error(
        f"tool_scratch: unknown operation '{op}'. "
        "Valid: write | run | list | clear."
    ))


def _handle_tool_scratch_write(name, arguments, root):
    from research_os.tools.actions.state.scratch import scratch_write

    res = scratch_write(arguments["filename"], arguments["content"], root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "scratch_write failed")))


def _handle_tool_scratch_run(name, arguments, root):
    from research_os.tools.actions.state.scratch import scratch_run

    res = scratch_run(arguments["filename"], root, timeout=int(arguments.get("timeout", 60)))
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "scratch_run failed")))


def _handle_tool_scratch_list(name, arguments, root):
    from research_os.tools.actions.state.scratch import scratch_list

    res = scratch_list(root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "scratch_list failed")))


def _handle_tool_scratch_clear(name, arguments, root):
    from research_os.tools.actions.state.scratch import scratch_clear

    res = scratch_clear(root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "scratch_clear failed")))


def _handle_tool_workspace_repair(name, arguments, root):
    from research_os.tools.actions.state.repair import workspace_repair

    res = workspace_repair(root, dry_run=bool(arguments.get("dry_run", False)))
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "workspace_repair failed")))


def _handle_tool_migrate_audit(name, arguments, root):
    from research_os.tools.actions.state.migrate import audit_chaos, plan_migration

    src = arguments.get("source_dir")
    if not src:
        return _text(_error("source_dir is required"))
    dest = arguments.get("dest_dir")
    if dest:
        res = plan_migration(src, dest)
    else:
        res = audit_chaos(src)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "migrate_audit failed")))


def _handle_tool_migrate_apply(name, arguments, root):
    from research_os.tools.actions.state.migrate import apply_migration

    src = arguments.get("source_dir")
    dest = arguments.get("dest_dir")
    if not src or not dest:
        return _text(_error("source_dir and dest_dir are required"))
    res = apply_migration(src, dest, verify=bool(arguments.get("verify", True)))
    if res.get("status") in ("success", "partial"):
        return _text(_success(res))
    return _text(_error(res.get("message", "migrate_apply failed")))


def _handle_tool_structure_audit(name, arguments, root):
    from research_os.tools.actions.state.structure_audit import audit_structure

    res = audit_structure(root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "structure_audit failed")))


HANDLERS = {
    "tool_python_exec": _handle_tool_python_exec,
    "tool_bash_exec": _handle_tool_bash_exec,
    "tool_package_install": _handle_tool_package_install,
    "tool_slurm_submit": _handle_tool_slurm_submit,
    "tool_task": _handle_tool_task,
    "tool_notebook_exec": _handle_tool_notebook_exec,
    "tool_scratch": _handle_tool_scratch,
    "tool_migrate_audit": _handle_tool_migrate_audit,
}
