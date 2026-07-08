"""SLURM / HPC cluster integration.

National-lab analyses outgrow a single workstation fast. This module
adds a thin wrapper around ``sbatch`` / ``squeue`` / ``sacct`` so the
AI can submit jobs to a SLURM cluster, poll status, and pull results
back into ``workspace/<step>/`` without leaving the IDE.

What's here
-----------
* ``submit`` — generate an sbatch script from a template (cpus, mem,
  time, partition, array, dependency) and submit it. Records the
  job_id + spec in ``.os_state/cluster/jobs/<job_id>.json``.
* ``status`` — poll squeue for live jobs; sacct for finished ones.
  Returns a structured record per job.
* ``fetch`` — wait for completion + copy stdout/stderr (and any
  declared output directory) back into the step folder.
* ``list`` — every job submitted from this project, oldest first.

Why this exists
---------------
``tool_task_run`` runs locally. For 100k-row analyses + a ResNet-50
fit on 8 GPUs that's not a fit. SLURM gives you partition selection,
GPU allocation, job arrays for parameter sweeps, and dependency
chains so the next stage waits for the previous one. The wrapper
mirrors ``tool_task_run``'s ergonomics so the AI picks the right
backend without thinking.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("research_os.cluster")


def _jobs_dir(root: Path) -> Path:
    p = root / ".os_state" / "cluster" / "jobs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _has_slurm() -> bool:
    return bool(shutil.which("sbatch")) and bool(shutil.which("squeue"))


def _cfg_defaults(root: Path) -> dict[str, Any]:
    """Pull runtime.cluster_defaults from researcher_config.yaml."""
    cfg_path = root / "inputs" / "researcher_config.yaml"
    if not cfg_path.exists():
        return {}
    try:
        import yaml  # type: ignore

        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        return (cfg.get("runtime") or {}).get("cluster_defaults") or {}
    except Exception:
        return {}


def _build_sbatch(
    *,
    job_name: str,
    cmd: str,
    cpus: int,
    mem: str,
    time_limit: str,
    partition: str,
    gpus: int | None = None,
    array: str | None = None,
    dependency: str | None = None,
    modules: list[str] | None = None,
    conda_env: str | None = None,
    extra_sbatch: list[str] | None = None,
    output_dir: Path | None = None,
) -> str:
    """Render the sbatch script body."""
    out_dir = output_dir or Path("logs")
    out_template = str(out_dir / "%x-%j.out")
    err_template = str(out_dir / "%x-%j.err")
    if array:
        out_template = str(out_dir / "%x-%A_%a.out")
        err_template = str(out_dir / "%x-%A_%a.err")

    head = [
        "#!/bin/bash",
        f"#SBATCH --job-name={job_name}",
        f"#SBATCH --partition={partition}",
        f"#SBATCH --cpus-per-task={cpus}",
        f"#SBATCH --mem={mem}",
        f"#SBATCH --time={time_limit}",
        f"#SBATCH --output={out_template}",
        f"#SBATCH --error={err_template}",
    ]
    if gpus:
        head.append(f"#SBATCH --gres=gpu:{gpus}")
    if array:
        head.append(f"#SBATCH --array={array}")
    if dependency:
        head.append(f"#SBATCH --dependency={dependency}")
    for line in (extra_sbatch or []):
        if not line.startswith("#SBATCH"):
            line = "#SBATCH " + line
        head.append(line)

    body = [
        "",
        "set -euo pipefail",
        "echo \"# Started at $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname)\"",
        "echo \"# Working directory: $(pwd)\"",
        "echo \"# SLURM job id: ${SLURM_JOB_ID:-?}\"",
    ]
    for m in (modules or []):
        body.append(f"module load {m}")
    if conda_env:
        body.append(f"source activate {conda_env}")
    body.append("")
    body.append(cmd)
    body.append("")
    body.append("echo \"# Ended at $(date -u +%Y-%m-%dT%H:%M:%SZ)\"")
    return "\n".join(head + body) + "\n"


def submit_slurm(
    root: Path,
    *,
    offline: bool = False,
    step_id: str | None = None,
    cmd: str,
    job_name: str | None = None,
    cpus: int | None = None,
    mem: str | None = None,
    time_limit: str | None = None,
    partition: str | None = None,
    gpus: int | None = None,
    array: str | None = None,
    dependency: str | None = None,
    modules: list[str] | None = None,
    conda_env: str | None = None,
    extra_sbatch: list[str] | None = None,
) -> dict[str, Any]:
    """Submit a SLURM job and record its metadata.

    All optional parameters default to ``researcher_config.runtime.
    cluster_defaults`` when omitted, so a typical call is just::

        submit_slurm(root, step_id="03_fit", cmd="python scripts/03_fit_v1.py")
    """
    if offline:
        return {
            "status": "error",
            "message": "offline mode blocks SLURM job submission because it requires scheduler I/O",
            "offline": True,
        }
    if not _has_slurm():
        return {
            "status": "error",
            "message": (
                "sbatch / squeue not found on PATH. Either you're not on "
                "a SLURM cluster, or `module load slurm` is required."
            ),
        }
    defaults = _cfg_defaults(root)
    job_name = job_name or (step_id or "research-os") + "-job"
    cpus = int(cpus or defaults.get("cpus_per_task", 4))
    mem = str(mem or defaults.get("mem", "16G"))
    time_limit = str(time_limit or defaults.get("time", "02:00:00"))
    partition = str(partition or defaults.get("partition", "compute"))
    modules = modules or defaults.get("modules") or []
    conda_env = conda_env or defaults.get("conda_env")
    extra_sbatch = extra_sbatch or defaults.get("extra_sbatch") or []

    # Working directory + log dir.
    if step_id:
        cwd = root / "workspace" / step_id
        if not cwd.is_dir():
            return {"status": "error",
                    "message": f"step '{step_id}' not found"}
        log_dir = cwd / "logs"
    else:
        cwd = root
        log_dir = root / "workspace" / "logs" / "cluster"
    log_dir.mkdir(parents=True, exist_ok=True)

    script_body = _build_sbatch(
        job_name=job_name, cmd=cmd,
        cpus=int(cpus), mem=str(mem), time_limit=str(time_limit), partition=str(partition),
        gpus=gpus, array=array, dependency=dependency,
        modules=modules, conda_env=conda_env, extra_sbatch=extra_sbatch,
        output_dir=log_dir,
    )

    # Write script next to the logs. A short uuid suffix prevents two
    # submits within the same wall-clock second from overwriting each
    # other's script.
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    script_path = log_dir / f"sbatch_{job_name}_{ts}_{uuid.uuid4().hex[:6]}.sh"
    script_path.write_text(script_body)
    script_path.chmod(0o755)

    try:
        res = subprocess.run(
            ["sbatch", str(script_path)],
            cwd=str(cwd), capture_output=True, text=True, errors="replace", timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"status": "error", "message": f"sbatch invocation failed: {e}"}
    if res.returncode != 0:
        return {
            "status": "error",
            "exit_code": res.returncode,
            "stderr": (res.stderr or "").strip(),
            "message": "sbatch returned non-zero",
        }
    # Parse "Submitted batch job 12345".
    m = re.search(r"\b(\d+)\b", res.stdout or "")
    if not m:
        return {
            "status": "error",
            "message": f"could not parse job_id from sbatch output: {res.stdout}",
        }
    job_id = m.group(1)
    record = {
        "job_id": job_id,
        "job_name": job_name,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "submitted_by": os.environ.get("USER"),
        "step_id": step_id,
        "cwd": str(cwd),
        "cmd": cmd,
        "partition": partition,
        "cpus": cpus, "mem": mem, "time": time_limit,
        "gpus": gpus, "array": array, "dependency": dependency,
        "modules": modules, "conda_env": conda_env,
        "offline": bool(offline),
        "script": str(script_path.relative_to(root)),
        "log_dir": str(log_dir.relative_to(root)),
    }
    (_jobs_dir(root) / f"{job_id}.json").write_text(
        json.dumps(record, indent=2, default=str) + "\n"
    )
    return {
        "status": "success",
        **record,
        "advice": (
            f"Job {job_id} queued. Poll with tool_slurm_status job_id={job_id}; "
            f"fetch results with tool_slurm_fetch job_id={job_id}."
        ),
    }


def status_slurm(root: Path, job_id: str | None = None) -> dict[str, Any]:
    """Live status via squeue + post-mortem via sacct."""
    if not _has_slurm():
        return {"status": "error", "message": "SLURM not on PATH"}

    if job_id:
        ids = [job_id]
    else:
        # All jobs recorded for this project.
        ids = sorted(p.stem for p in _jobs_dir(root).glob("*.json"))
    out: list[dict[str, Any]] = []
    for jid in ids:
        rec_path = _jobs_dir(root) / f"{jid}.json"
        recorded = {}
        if rec_path.exists():
            try:
                recorded = json.loads(rec_path.read_text())
            except Exception:
                pass
        # Try squeue first (live).
        live_state = None
        try:
            sq = subprocess.run(
                ["squeue", "-j", jid, "-h", "-o", "%T|%M|%R"],
                capture_output=True, text=True, errors="replace", timeout=15,
            )
            if sq.returncode == 0 and sq.stdout.strip():
                parts = sq.stdout.strip().split("|", 2)
                if len(parts) == 3:
                    state, elapsed, reason = parts
                    live_state = {"state": state, "elapsed": elapsed, "reason": reason}

        except (OSError, subprocess.TimeoutExpired):
            pass

        # Fall back to sacct.
        finished = None
        if not live_state and shutil.which("sacct"):
            try:
                sa = subprocess.run(
                    ["sacct", "-j", jid, "-P", "-n",
                     "-o", "JobID,State,Elapsed,MaxRSS,ExitCode,Start,End"],
                    capture_output=True, text=True, errors="replace", timeout=15,
                )
                if sa.returncode == 0:
                    # First line is the parent job; later lines are .batch / .extern
                    for line in (sa.stdout or "").splitlines():
                        cols = line.split("|")
                        if cols and cols[0] == jid and len(cols) >= 7:
                            finished = {
                                "state": cols[1],
                                "elapsed": cols[2],
                                "max_rss": cols[3],
                                "exit_code": cols[4],
                                "start": cols[5],
                                "end": cols[6],
                            }
                            break
            except (OSError, subprocess.TimeoutExpired):
                pass
        out.append({
            "job_id": jid,
            "recorded": recorded,
            "live": live_state,
            "finished": finished,
        })
    return {"status": "success", "jobs": out}


def fetch_slurm(
    root: Path, job_id: str, *, poll_interval: int = 30, max_wait: int = 7200,
) -> dict[str, Any]:
    """Block until ``job_id`` finishes, then return stdout/stderr paths."""
    if not _has_slurm():
        return {"status": "error", "message": "SLURM not on PATH"}
    rec_path = _jobs_dir(root) / f"{job_id}.json"
    if not rec_path.exists():
        return {"status": "error",
                "message": f"no record for job_id={job_id}"}
    record = json.loads(rec_path.read_text())
    deadline = time.time() + max_wait
    last_state = None
    while time.time() < deadline:
        st = status_slurm(root, job_id)
        jobs = st.get("jobs") or []
        if jobs:
            job = jobs[0]
            if job.get("finished"):
                last_state = job["finished"].get("state")
                break
            live = job.get("live")
            if live:
                last_state = live.get("state")
        time.sleep(poll_interval)
    log_dir = (root / record["log_dir"]).resolve()
    out_files = sorted(log_dir.glob(f"*-{job_id}*.out"))
    err_files = sorted(log_dir.glob(f"*-{job_id}*.err"))
    return {
        "status": "success" if last_state in {"COMPLETED", None} else "warning",
        "job_id": job_id,
        "final_state": last_state,
        "stdout_paths": [str(p.relative_to(root)) for p in out_files],
        "stderr_paths": [str(p.relative_to(root)) for p in err_files],
        "log_dir": record["log_dir"],
    }


def list_slurm(root: Path) -> dict[str, Any]:
    out = []
    for f in sorted(_jobs_dir(root).glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except Exception:
            continue
    return {"status": "success", "jobs": out, "n_jobs": len(out)}


__all__ = ["fetch_slurm", "list_slurm", "status_slurm", "submit_slurm"]
