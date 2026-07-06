"""Handlers — research_exec sub-domain.

Carved out of handlers/research.py to stay under the 600-line ceiling.
"""
from __future__ import annotations

from .._handlers_runtime import *  # noqa: F401,F403

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
    from research_os.tools.actions.exec.scripts import (
        execute_bash_script,
        execute_julia_script,
        execute_r_script,
    )

    timeout = arguments.get("timeout", 600)
    script_path = arguments["script_path"]
    fn = {
        "tool_r_exec": execute_r_script,
        "tool_julia_exec": execute_julia_script,
        "tool_bash_exec": execute_bash_script,
    }[name]
    res = fn(script_path, root, timeout)
    if res.get("status") == "error":
        return _text(_error(res.get("message", "execution failed")))
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
    from research_os.tools.actions.exec.tasks import task_run

    res = task_run(
        arguments["command"],
        root,
        cwd=arguments.get("cwd"),
        description=arguments.get("description", ""),
    )
    if res.get("status") == "success":
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

    res = execute_notebook(
        arguments["notebook_path"],
        root,
        timeout=int(arguments.get("timeout", 1800)),
        kernel=arguments.get("kernel", "python3"),
        parameters=arguments.get("parameters"),
        output_path=arguments.get("output_path"),
    )
    if res.get("status") == "success":
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
