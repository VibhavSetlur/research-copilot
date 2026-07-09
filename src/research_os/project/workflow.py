"""Workflow diagram construction, manifest updates, and path lineage helpers.

Canonical implementations for the workspace workflow DAG and lineage tracking.
``project_ops`` re-exports all public symbols for backward compatibility.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from research_os.project.step_discovery import (
    discover_step_dirs,
    is_path_container,
    step_input_link,
)
from research_os.project.layout import detect_software_components
from research_os.project.legacy import _update_manifest as _update_manifest_impl


# ---------------------------------------------------------------------------
# Path lineage extraction
# ---------------------------------------------------------------------------


_PATH_LINEAGE_RE = re.compile(r"_path_(\d+)(?:__DEAD_END)?$")


def _extract_path_lineage(branch_id: str) -> int | None:
    """Return the branch lineage number embedded in a folder name, or None.

    ``05_glmm_path_2`` → ``2``; ``05_glmm`` → ``None``; ``05_glmm_path_2__DEAD_END`` → ``2``.
    """
    m = _PATH_LINEAGE_RE.search(branch_id)
    return int(m.group(1)) if m else None


def _max_path_lineage(workspace: Path) -> int:
    """Largest existing ``_path_<k>`` lineage tag across the workspace."""
    best = 0
    if not workspace.exists():
        return 0
    for p in discover_step_dirs(workspace):
        k = _extract_path_lineage(p.name)
        if k is not None and k > best:
            best = k
    return best


def _max_path_container_seq(workspace: Path) -> int:
    """Largest existing ``_PATH_<k>`` container sequence number."""
    best = 0
    if not workspace.exists():
        return 0
    for p in workspace.iterdir():
        if p.is_dir() and is_path_container(p.name):
            m = re.search(r"_PATH_(\d+)$", p.name)
            if m:
                best = max(best, int(m.group(1)))
    return best


# ---------------------------------------------------------------------------
# Workflow DAG construction
# ---------------------------------------------------------------------------


def _atomic_write_text(path: Path, text: str) -> None:
    """Atomic text write: temp file in the same dir + ``os.replace``.

    analysis.md (and the other append-only logs) are rewritten in place by
    several mutating tools; a bare ``read_text`` → ``write_text`` can lose
    the file to truncation if a concurrent writer interleaves or the
    process dies mid-write. Writing to a sibling temp and renaming makes
    the swap atomic on POSIX."""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp_path, str(path))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _update_analysis_mermaid_block(root: Path, mermaid_content: str) -> None:
    analysis_path = root / "workspace" / "analysis.md"
    if not analysis_path.exists():
        return
    content = analysis_path.read_text()
    start = content.find("```mermaid")
    if start == -1:
        return
    end = content.find("```", start + 10)
    if end == -1:
        return
    end += 3
    new_block = f"```mermaid\n{mermaid_content}\n```"
    new_content = content[:start] + new_block + content[end:]
    if new_content == content:
        return  # no change → skip the rewrite (avoids needless churn/race)
    _atomic_write_text(analysis_path, new_content)


def _step_purpose(exp_dir: Path, fallback: str) -> str:
    """A short (<=46 char) one-liner for a workflow node, taken from the
    step's README ``## Goal`` (skipping the unfilled stub). Falls back to
    the step name."""
    readme = exp_dir / "README.md"
    if readme.exists():
        try:
            txt = readme.read_text()
        except OSError:
            txt = ""
        m = re.search(r"^##\s+Goal\s*\n+(.+)", txt, re.M)
        if m:
            line = re.sub(r"\s+", " ", m.group(1).strip().lstrip("-* ").strip())
            if line and not line.startswith(("*(", "_(")):
                return line[:46]
    return re.sub(r"\s+", " ", fallback)[:46]


def _build_workflow_mermaid(root: Path) -> str:
    """Build a realistic workflow DAG (graph TD) for the project.

    Unlike the old `init --> every step` fan-out, this derives REAL
    data-dependency edges from each step's ``data/past_step_input``
    symlinks (→ another step's ``data/next_step_output`` or
    ``inputs/raw_data``), labels nodes with status + a one-line purpose,
    styles dead-ends, groups branch paths (``*_PATH_k``) into subgraphs,
    and falls back to a sequential chain for main-path steps whose inputs
    aren't symlinked yet. Shared by ``workspace/workflow.mermaid`` and
    ``docs/workflow_dag.mermaid`` so the two never drift.
    """
    from research_os.tools.actions.state.path import list_paths

    workspace = root / "workspace"
    try:
        steps = list_paths(root).get("paths", []) or []
    except Exception:
        steps = []

    def _num(pid: str) -> int:
        m = re.match(r"^(\d+)", pid)
        return int(m.group(1)) if m else 0

    def _safe(pid: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]", "_", pid)

    info: dict[str, dict[str, Any]] = {}
    for s in steps:
        pid = s["path_id"]
        exp = root / s.get("experiment_dir", f"workspace/{pid}")
        info[pid] = {
            "status": s.get("status", "active"),
            "lineage": _extract_path_lineage(pid),
            "purpose": _step_purpose(exp, s.get("name") or pid),
            "exp": exp,
            "num": _num(pid),
            "short": pid.replace("__DEAD_END", ""),
        }

    # ── edges from data symlinks ──────────────────────────────────────
    try:
        ws_resolved = workspace.resolve()
        raw_resolved = (root / "inputs" / "raw_data").resolve()
    except OSError:
        ws_resolved, raw_resolved = workspace, root / "inputs" / "raw_data"
    edges: set[tuple[str, str]] = set()
    consumes_raw: set[str] = set()
    for pid, meta in info.items():
        din = step_input_link(meta["exp"])
        targets: list[Path] = []
        if din.is_symlink():
            try:
                targets.append(din.resolve())
            except OSError:
                pass
        elif din.is_dir():
            for ch in din.iterdir():
                if ch.is_symlink():
                    try:
                        targets.append(ch.resolve())
                    except OSError:
                        pass
        for t in targets:
            try:
                rel = t.relative_to(ws_resolved)
            except (ValueError, OSError):
                try:
                    t.relative_to(raw_resolved)
                    consumes_raw.add(pid)
                except (ValueError, OSError):
                    pass
                continue
            anc = next((p for p in rel.parts if re.match(r"^\d{2,3}_", p)), None)
            if anc and anc in info and anc != pid:
                edges.add((anc, pid))

    # ── fallback sequential chain for un-wired main-path steps ────────
    main_sorted = sorted(
        (p for p in info if info[p]["lineage"] is None), key=lambda p: info[p]["num"]
    )
    have_in = {dst for _, dst in edges}
    prev: str | None = None
    for pid in main_sorted:
        if prev and pid not in have_in and (prev, pid) not in edges:
            edges.add((prev, pid))
            have_in.add(pid)
        prev = pid
    if main_sorted and main_sorted[0] not in have_in:
        consumes_raw.add(main_sorted[0])

    # ── assemble ──────────────────────────────────────────────────────
    css_for = {"completed": "completed", "active": "active", "dead_end": "dead_end"}
    lines = [
        "graph TD",
        "    classDef active fill:#fff3cd,stroke:#856404,color:#333",
        "    classDef completed fill:#d4edda,stroke:#28a745,color:#155724",
        "    classDef dead_end fill:#f8d7da,stroke:#dc3545,color:#721c24,stroke-dasharray: 5 5",
        "    classDef planned fill:#e2e3e5,stroke:#6c757d,color:#333",
        "    classDef source fill:#e7f1ff,stroke:#0d6efd,color:#084298",
        "    classDef software fill:#f0e7ff,stroke:#6f42c1,color:#3d1a78",
    ]
    if consumes_raw:
        lines.append('    raw[("inputs/raw_data")]:::source')

    def _node_line(pid: str, indent: str = "    ") -> str:
        meta = info[pid]
        css = css_for.get(meta["status"], "planned")
        label = meta["short"]
        purpose = meta["purpose"]
        if purpose and purpose.lower() not in (label.lower(), ""):
            label = f"{label}<br/><i>{purpose}</i>"
        return f'{indent}{_safe(pid)}["{label}"]:::{css}'

    # group branch lineages into subgraphs; main path stays ungrouped.
    lineages = sorted({m["lineage"] for m in info.values() if m["lineage"] is not None})
    for pid in main_sorted:
        lines.append(_node_line(pid))
    for k in lineages:
        members = sorted(
            (p for p in info if info[p]["lineage"] == k), key=lambda p: info[p]["num"]
        )
        lines.append(f'    subgraph path_{k}["Path {k} — alternative approach"]')
        for pid in members:
            lines.append(_node_line(pid, indent="        "))
        lines.append("    end")

    for pid in consumes_raw:
        lines.append(f"    raw --> {_safe(pid)}")
    for src, dst in sorted(edges):
        lines.append(f"    {_safe(src)} --> {_safe(dst)}")

    # Software components (hybrid research+software projects): show the code
    # deliverable as its own subgraph + a dashed "informs" link from the
    # latest research step (the analysis feeds the implementation).
    try:
        components = detect_software_components(root)
    except Exception:
        components = []
    if components:
        lines.append('    subgraph software_component["Software"]')
        for c in components:
            cid = "sw_" + re.sub(r"[^A-Za-z0-9_]", "_", c["name"])
            lines.append(f'        {cid}["{c["name"]}<br/><i>{c["kind"]}</i>"]:::software')
        lines.append("    end")
        all_nums = sorted(info, key=lambda p: info[p]["num"]) if info else []
        anchor = main_sorted[-1] if main_sorted else (all_nums[-1] if all_nums else None)
        if anchor:
            for c in components:
                cid = "sw_" + re.sub(r"[^A-Za-z0-9_]", "_", c["name"])
                lines.append(f"    {_safe(anchor)} -. informs .-> {cid}")

    if not info and not components:
        lines.append('    empty["No analysis steps yet"]:::planned')

    return "\n".join(lines)


def _update_workflow_mermaid(root: Path) -> None:
    """Regenerate workspace/workflow.mermaid + analysis.md block + (optional) PNG.

    Refuses to write into ``root/workspace/`` unless ``root`` is a
    valid Research-OS project (``.os_state/`` present). Without that
    guard, a misconfigured caller can pollute a non-project tree (e.g.
    write ``workspace/workflow.mermaid`` into the Research-OS source
    repo).
    """
    if not (root / ".os_state").is_dir():
        # Guard against pollution of a non-project tree (e.g. a
        # misconfigured caller writing workspace/workflow.mermaid into
        # the Research-OS source repo). Silent return is fine — the
        # consequence of NOT writing the mermaid in a non-project dir
        # is exactly what we want.
        return
    try:
        text = _build_workflow_mermaid(root)
    except Exception:
        # Never let a diagram refresh break step create/finalize.
        return
    mermaid_path = root / "workspace" / "workflow.mermaid"
    mermaid_path.write_text(text + "\n")
    _update_analysis_mermaid_block(root, text)

    mmdc = shutil.which("mmdc")
    if mmdc:
        try:
            subprocess.run(
                [mmdc, "-i", str(mermaid_path), "-o", str(root / "workspace" / "workflow.png"), "-b", "white"],
                capture_output=True,
                timeout=60,
            )
        except Exception:
            pass


# Re-export _update_manifest from state module for backward compat
_update_manifest = _update_manifest_impl
