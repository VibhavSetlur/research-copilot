"""Workspace scaffolding, state I/O, and shared filesystem helpers.

Conventions
-----------
* Single state file: ``.os_state/state_ledger.json`` (mirrored to
  ``.os_state/state_ledger.yaml`` for human reading).
* Append-only logs: ``workspace/methods.md``, ``analysis.md``, ``citations.md``.
* Immutable: ``inputs/raw_data/``, ``inputs/literature/``.
* All workspace writes go through MCP tools so provenance is captured.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - yaml is a hard dep
    yaml = None

from research_os.errors import check_write_permitted
from research_os.state.state_ledger import ResearchLedger
from research_os.utils.common import find_project_root, now_iso

EXPERIMENT_SUBDIRS = (
    "data/past_step_input",   # symlink → the previous step's data/next_step_output
    "data/next_step_output",  # this step's outputs; the next step consumes them
    "data/share",             # curated datasets packaged to hand to a collaborator
    "scripts",
    "literature",        # per-step PDFs; populated by tool_literature_download(step_id=…)
    "context",           # per-step prose notes, methodology rationale, hand-overs
    "outputs/figures",
    "outputs/tables",
    "environment",
)
# outputs/reports/ is NOT pre-created: when every step ships an empty
# reports/ it becomes a magnet for misplaced analysis artefacts (the
# reaction-similarity project dumped manifest.json / profile.md /
# method_spec.md there). reports/ is for *optional* point-in-time
# PRESENTATION artefacts (a one-off dashboard / slide); tools + the AI
# create it on demand. The finalize inventory tolerates its absence.

# 3.2 renamed the per-step data folders (data/input → data/past_step_input,
# data/output → data/next_step_output) and added data/share. Reading code
# must keep working on pre-3.2 projects that still carry the old names, so
# the two resolvers below return the 3.2 path when present and otherwise
# fall back to the legacy name.


def _present(p: Path) -> bool:
    """True if a path exists OR is a (possibly broken) symlink."""
    return p.is_symlink() or p.exists()


def step_input_link(exp_dir: Path) -> Path:
    """The step's upstream-input link (3.2 ``data/past_step_input``, else
    the legacy ``data/input``). Returns the 3.2 path when neither exists."""
    new = exp_dir / "data" / "past_step_input"
    legacy = exp_dir / "data" / "input"
    if _present(new) or not _present(legacy):
        return new
    return legacy


def step_output_dir(exp_dir: Path) -> Path:
    """The step's output dir (3.2 ``data/next_step_output``, else the legacy
    ``data/output``). Returns the 3.2 path when neither exists."""
    new = exp_dir / "data" / "next_step_output"
    legacy = exp_dir / "data" / "output"
    if _present(new) or not _present(legacy):
        return new
    return legacy


# ---------------------------------------------------------------------------
# Step discovery — flat steps + steps grouped into PATH containers.
#
# 3.2 lets the researcher consolidate a run of steps that explored one
# direction into a descriptive container folder, e.g.
# ``workspace/attitude_pilot_PATH_1/03_eda``. Step numbering stays
# CONTINUOUS across containers (path 2 picks up at step 06, never resets),
# so the lineage is preserved and steps can be moved without renumbering.
# Every code path that enumerates steps MUST go through ``discover_step_dirs``
# so a grouped step is never silently invisible.
# ---------------------------------------------------------------------------

_STEP_DIR_RE = re.compile(r"^\d{2,3}_")
#: A PATH container folder: ``<descriptive_slug>_PATH_<k>``.
_PATH_CONTAINER_RE = re.compile(r"^.+_PATH_\d+$")


def is_path_container(name: str) -> bool:
    """True if *name* is a ``<slug>_PATH_<k>`` container folder name."""
    return bool(_PATH_CONTAINER_RE.match(name))


def _step_sort_key(d: Path) -> tuple[int, str]:
    try:
        return (int(d.name.split("_", 1)[0]), d.name)
    except ValueError:
        return (0, d.name)


def discover_step_dirs(workspace: Path, *, include_dead: bool = True) -> list[Path]:
    """Every numbered step directory, sorted by step number.

    Finds steps both directly under ``workspace/`` AND one level deep inside
    ``<slug>_PATH_<k>/`` container folders. ``include_dead=False`` skips
    ``__DEAD_END`` steps.
    """
    steps: list[Path] = []
    if not workspace.exists():
        return steps
    for p in workspace.iterdir():
        if not p.is_dir():
            continue
        if _STEP_DIR_RE.match(p.name):
            if include_dead or not p.name.endswith("__DEAD_END"):
                steps.append(p)
        elif is_path_container(p.name):
            for c in sorted(p.iterdir()):
                if c.is_dir() and _STEP_DIR_RE.match(c.name):
                    if include_dead or not c.name.endswith("__DEAD_END"):
                        steps.append(c)
    return sorted(steps, key=_step_sort_key)


def resolve_step_dir(workspace: Path, step_id: str) -> Path | None:
    """Locate a step folder by id, whether flat or inside a PATH container.

    Tolerates the ``__DEAD_END`` variant. Returns ``None`` if not found.
    """
    direct = workspace / step_id
    if direct.is_dir():
        return direct
    dead = workspace / f"{step_id}__DEAD_END"
    if dead.is_dir():
        return dead
    for p in workspace.iterdir():
        if p.is_dir() and is_path_container(p.name):
            cand = p / step_id
            if cand.is_dir():
                return cand
            cand_dead = p / f"{step_id}__DEAD_END"
            if cand_dead.is_dir():
                return cand_dead
    return None


# NOTE: no `outputs/dashboards` here on purpose. Dashboards are a *project-level*
# synthesis output (synthesis/dashboard.html), not a per-step artifact.
#
# `context/` is the step's "if a new analyst opened this folder today, what
# narrative would let them act?" — methodology rationale, drafts, screen-grab
# notes from upstream meetings. Distinct from `literature/` (formal sources)
# and `data/` (machine-readable). `finalize_path` rewrites its README to
# summarise whatever was deposited so the dashboard's per-step appendix can
# surface it.

# ===========================================================================
# CANONICAL DIRECTORY LAYOUT — single source of truth
# ===========================================================================
# Every workspace.mode used to hand-duplicate three near-identical directory
# tuples (top_level / eager / lazy), restating the ~7 mode-agnostic safety
# dirs in each. That made the layout *implicit* — a change to the safety
# contract meant editing a dozen copy-pasted tuples, and nothing guaranteed
# the copies stayed in sync.
#
# The layout is now DECLARED ONCE here and COMPOSED. Each profile = a fixed
# backbone (safety prefix + workspace tree + environment) plus a small,
# mode-specific *work surface*. The composer (`_compose_layout`) builds the
# three tuples deterministically; `SCAFFOLD_PROFILES` is derived from
# `LAYOUT_SPEC`, so the safety contract can never drift between modes.
#
# Anything that needs the canonical layout — the wizard, sys_boot, the
# README templates, docs — should read `LAYOUT_SPEC` / `SCAFFOLD_PROFILES`
# / `describe_layout()` rather than re-listing directory names inline.
#
# The mode-agnostic safety backbone (constant across EVERY profile):
#   • ``.os_state``        the only hard-locked tree (provenance / state)
#   • ``docs``             overview + glossary
#   • ``inputs/``          source-of-truth drops: raw_data/ + literature/ are
#                          soft-guarded, context/ + researcher_config.yaml are
#                          AI-writable
#   • ``workspace/``       the work surface; ``workspace/logs`` (audit +
#                          override trail) and ``workspace/scratch`` (the AI
#                          sandbox) always live underneath
#   • ``environment``      reproducibility (env exports, lockfiles)
#
# Profiles only choose the *work surface* between inputs and outputs, and
# whether ``synthesis/`` exists (the eventual paper/report/dashboard home).
# ---------------------------------------------------------------------------

# The fixed backbone, declared once.
_SAFETY_PREFIX: tuple[str, ...] = (
    ".os_state",
    "docs",
    "inputs",
    "inputs/raw_data",
    "inputs/literature",
    "inputs/context",
)
_WORKSPACE_TREE: tuple[str, ...] = (
    "workspace",
    "workspace/logs",
    "workspace/scratch",
)
_ENVIRONMENT: tuple[str, ...] = ("environment",)


# Per-mode declarative spec. Each entry declares ONLY what differs from the
# backbone:
#   work     — the mode-specific work-surface dirs (inserted after the safety
#              prefix, before the workspace tree)
#   synthesis— whether ``synthesis/`` is part of the layout at all
#   lazy     — dirs created LAZILY (only when the first artefact lands; tools
#              must call ``ensure_lazy_dir`` first). Everything else is eager.
#   summary  — one-line human description (surfaced by ``describe_layout``)
LAYOUT_SPEC: dict[str, dict] = {
    # analysis → the classic linear numbered-step model. workspace/NN_* +
    # synthesis/. ``literature/`` is the project-wide corpus of record
    # (aggregated from every step).
    "analysis": {
        "work": ("literature",),
        "synthesis": True,
        "lazy": ("synthesis",),
        "summary": "Linear numbered-step analysis; synthesis/ holds the paper.",
    },
    # tool_build → Research OS sits ABOVE as a governance layer: spec/ (what
    # we're building + design), decisions/ (ADRs), eval/ (the benchmark that
    # defines "done"). The actual tool lives in an INNER project dir with its
    # own git init (see scaffold_minimal_workspace). No synthesis/.
    "tool_build": {
        "work": ("spec", "decisions", "eval"),
        "synthesis": False,
        "lazy": (),
        "summary": "Governance layer over an inner tool repo: spec/decisions/eval.",
    },
    # exploration → scratch-first. workspace/scratch is the home base; the
    # numbered-step + log surface materialises only once a probe is promoted,
    # so workspace/logs and synthesis stay lazy.
    "exploration": {
        "work": (),
        "synthesis": True,
        "lazy": ("workspace/logs", "synthesis"),
        "summary": "Scratch-first probing; numbered steps appear on promote.",
    },
    # notebook → Jupyter-first. The unit of work is a notebook in notebooks/;
    # data/ holds inputs the notebooks read, outputs/ holds what they emit.
    "notebook": {
        "work": ("notebooks", "data", "outputs"),
        "synthesis": True,
        "lazy": ("synthesis",),
        "summary": "Jupyter-first: notebooks/ + data/ + outputs/.",
    },
    # multi_study → portfolio / program. studies/ holds each sub-study,
    # shared/ is the program-wide commons (codebook, prereg, governing
    # protocol), roll_up/ is where cross-study synthesis + meta-analysis live.
    "multi_study": {
        "work": ("studies", "shared", "roll_up"),
        "synthesis": True,
        "lazy": ("synthesis",),
        "summary": "Program/portfolio: studies/ + shared/ + roll_up/.",
    },
    # hybrid (research + software) = analysis spine + a first-class home for
    # the tool half. It keeps the analysis layout (numbered steps + literature
    # + synthesis) AND declares a lazy ``tool/`` surface: the inner software
    # repo / package lives there once the build half starts, giving the hybrid
    # protocols (hybrid_workflow, tool_to_analysis_handoff) a stable path to
    # point at instead of relying purely on detect_software_components(). The
    # dir is lazy, so a hybrid project that hasn't built anything yet looks
    # exactly like an analysis project until the first tool artefact appears.
    "hybrid": {
        "work": ("literature", "tool"),
        "synthesis": True,
        "lazy": ("tool", "synthesis"),
        "summary": "Analysis spine + lazy tool/ home for the inner software repo (also auto-detected).",
    },
}


def _compose_layout(spec: dict) -> dict[str, tuple[str, ...]]:
    """Build the three directory tuples for one mode from its declarative spec.

    top_level = safety prefix + work surface + workspace tree + [synthesis]
                + environment
    eager     = top_level minus the lazy dirs
    lazy      = the deferred dirs (created on first artefact)
    """
    lazy = tuple(spec.get("lazy", ()))
    top: tuple[str, ...] = (
        _SAFETY_PREFIX
        + tuple(spec.get("work", ()))
        + _WORKSPACE_TREE
        + (("synthesis",) if spec.get("synthesis") else ())
        + _ENVIRONMENT
    )
    eager = tuple(d for d in top if d not in lazy)
    return {"top_level_dirs": top, "eager_dirs": eager, "lazy_dirs": lazy}


# Derived registry — one composed profile per mode. Keep the same public
# name + shape downstream code already imports.
SCAFFOLD_PROFILES: dict[str, dict[str, tuple[str, ...]]] = {
    mode: _compose_layout(spec) for mode, spec in LAYOUT_SPEC.items()
}

# Back-compat module constants: ``analysis`` is the default profile, so the
# historical ``TOP_LEVEL_DIRS`` / ``EAGER_DIRS`` / ``LAZY_DIRS`` names now
# alias the composed analysis layout (byte-identical to the old hand-written
# tuples). Existing imports keep working.
TOP_LEVEL_DIRS: tuple[str, ...] = SCAFFOLD_PROFILES["analysis"]["top_level_dirs"]
EAGER_DIRS: tuple[str, ...] = SCAFFOLD_PROFILES["analysis"]["eager_dirs"]
LAZY_DIRS: tuple[str, ...] = SCAFFOLD_PROFILES["analysis"]["lazy_dirs"]


def describe_layout(mode: str = "analysis") -> str:
    """Human-readable one-paragraph description of a mode's canonical layout.

    Single source for docs / sys_boot / the wizard to render the directory
    contract without re-listing folder names inline.
    """
    spec = LAYOUT_SPEC.get(mode)
    if spec is None:
        raise KeyError(f"unknown workspace mode: {mode!r}")
    profile = SCAFFOLD_PROFILES[mode]
    eager = ", ".join(profile["eager_dirs"])
    lazy = ", ".join(profile["lazy_dirs"]) or "(none)"
    return (
        f"{mode}: {spec['summary']}\n"
        f"  created at init (eager): {eager}\n"
        f"  created on first use (lazy): {lazy}"
    )


def ensure_mode_surface(
    root: Path,
    mode: str,
    *,
    project_name: str | None = None,
    config_overrides: dict | None = None,
    plan_only: bool = False,
) -> dict:
    """Additively create the directory + governance surface a workspace `mode`
    requires, WITHOUT touching anything that already exists.

    Shared by init (scaffold_minimal_workspace) and post-init mode transitions
    so both produce the SAME surface from one source of truth. NEVER deletes or
    overwrites — a transition augments. Returns
    {created_dirs: [...], inner_repo: <name|"">, missing_before: [...]}.
    With plan_only=True, reports what WOULD be created without writing.
    """
    root = Path(root)
    profile = SCAFFOLD_PROFILES.get(mode)
    if profile is None:
        raise KeyError(f"unknown workspace mode: {mode!r}")
    # The eager dirs the mode needs at rest (lazy dirs are created on first use).
    needed = profile["eager_dirs"]
    missing = [d for d in needed if not (root / d).exists()]
    if plan_only:
        return {"created_dirs": [], "missing_before": missing, "inner_repo": "", "plan_only": True}

    created: list[str] = []
    for d in missing:
        (root / d).mkdir(parents=True, exist_ok=True)
        created.append(d)
    # Seed the mode-specific governance/scratch files (idempotent _write_if_missing
    # inside) and get the inner-repo name for tool_build / hybrid.
    inner = _seed_mode_extras(
        root, project_name or _read_project_name(root), mode, config_overrides
    )
    # Init the inner repo for modes that have one (tool_build/hybrid) — mirrors
    # the post-scaffold git-init guard.
    if mode in ("tool_build", "hybrid") and inner:
        inner_dir = root / inner
        if not (inner_dir / ".git").exists():
            try:
                inner_dir.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "init"], cwd=inner_dir, capture_output=True)
            except Exception:
                pass
    return {"created_dirs": created, "missing_before": missing, "inner_repo": inner or ""}


def _read_project_name(root: Path) -> str:
    """Best-effort project name from state for surface seeding. Fallback to dir."""
    try:
        st = load_state(Path(root))
        nm = st.get("project_name")
        if nm:
            return str(nm)
    except Exception:
        pass
    return Path(root).name


# Files whose presence in a directory marks it as a software component.
_SOFTWARE_MARKERS = {
    "pyproject.toml": "python", "setup.py": "python", "setup.cfg": "python",
    "Cargo.toml": "rust", "package.json": "node", "go.mod": "go",
    "DESCRIPTION": "r", "pom.xml": "java", "build.gradle": "java",
}
# Top-level dirs that are Research-OS scaffolding, never software components.
_NON_SOFTWARE_DIRS = {
    "workspace", "inputs", ".os_state", "environment", "docs", "synthesis",
    "literature", "reports", "scripts", "spec", "decisions", "eval",
}


def detect_software_components(root: Path) -> list[dict[str, str]]:
    """Find inner software components in a (hybrid) project.

    A child directory counts as a software component when it carries a
    build manifest (pyproject.toml / Cargo.toml / package.json / …) or its
    own ``.git``. Research-OS scaffold dirs are excluded. This is what makes
    a research+software project legible — e.g. KBUtilLib living beside the
    analysis steps. Best-effort; never raises.
    """
    root = Path(root)
    found: dict[str, dict[str, str]] = {}
    try:
        children = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return []
    for child in children:
        if child.name in _NON_SOFTWARE_DIRS or child.name.startswith("."):
            continue
        kind: str | None = None
        for marker, k in _SOFTWARE_MARKERS.items():
            if (child / marker).exists():
                kind = k
                break
        if kind is None and (child / ".git").exists():
            kind = "repo"
        if kind is not None:
            found[child.name] = {
                "path": child.name,
                "name": child.name,
                "kind": kind,
            }
    return list(found.values())


def _resolve_scaffold_profile(mode: str | None) -> tuple[str, dict[str, tuple[str, ...]]]:
    """Return ``(mode, profile)`` for *mode*, defaulting to ``analysis``.

    Any unknown / blank mode collapses to ``analysis`` so a malformed
    config builds the classic workspace rather than failing.
    """
    resolved = mode if mode in SCAFFOLD_PROFILES else "analysis"
    return resolved, SCAFFOLD_PROFILES[resolved]


def _has_user_inputs(root: Path) -> bool:
    """True iff the researcher has dropped real files into inputs/.

    Skips scaffold-seeded ``README.md`` files in each input subfolder
    (so an empty folder isn't a dead end) — those don't count as user
    content.
    """
    for sub in ("raw_data", "literature", "context"):
        d = root / "inputs" / sub
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            if p.name.startswith(".") or p.name == ".gitkeep":
                continue
            if p.name == "README.md" and p.parent.name in {
                "raw_data", "literature", "context"
            }:
                continue
            return True
    return False


def ensure_lazy_dir(root: Path, rel: str) -> Path:
    """Create a lazy workspace directory at first write; idempotent.

    Tools call this before dropping the first artefact into a LAZY_DIRS
    path so the project surface stays minimal until real content arrives.
    Passing a path that is not in ``LAZY_DIRS`` raises so writers can't
    silently grow the lazy surface without updating the registry.
    """
    if rel not in LAZY_DIRS:
        raise ValueError(
            f"ensure_lazy_dir('{rel}') is not a registered lazy directory. "
            f"Allowed: {', '.join(LAZY_DIRS)}. Use Path.mkdir for ad-hoc dirs."
        )
    target = root / rel
    target.mkdir(parents=True, exist_ok=True)
    return target


#: Common low-effort placeholder strings that small models emit when
#: asked for an override rationale. Rejected case-insensitively after
#: stripping whitespace. ai-qwen audit (W11) explicitly flagged 'TODO'
#: and 'preview' as the most common small-model placeholders.
_OVERRIDE_RATIONALE_PLACEHOLDERS = frozenset({
    "",
    "todo",
    "test",
    "preview",
    "tmp",
    "temporary",
    "idk",
    "na",
    "n/a",
    "placeholder",
    "tbd",
    "fix later",
    "check later",
})


def validate_override_rationale(rationale: str | None) -> dict | None:
    """Return an error envelope dict if *rationale* is too thin, else None.

    Rules (all must pass for an override to be accepted):
      1. ``rationale.strip()`` must be at least 20 characters.
      2. ``rationale.strip().lower()`` must NOT be in the placeholder set.
      3. ``rationale.strip()`` must contain at least one whitespace
         character (rejects single-word rationales).

    Callers should:

        from research_os.project_ops import validate_override_rationale
        err = validate_override_rationale(rationale)
        if err is not None:
            return _text(err)

    Returning a pre-built error envelope (rather than raising) keeps the
    call-site shape identical to existing override checks.
    """
    from research_os.server.envelopes import _error

    text = (rationale or "").strip()
    lowered = text.lower()
    n = len(text)
    is_placeholder = lowered in _OVERRIDE_RATIONALE_PLACEHOLDERS
    is_single_word = bool(text) and (" " not in text and "\t" not in text)
    if n < 20 or is_placeholder or is_single_word:
        return _error(
            what="override_rationale_too_thin",
            why=f"rationale {n} chars, single-word/placeholder",
            next_action=(
                'Provide a substantive rationale (>=20 chars, multiple '
                'words). Example: "3pm preview for PI; methods.md is '
                'still a stub but figures are final."'
            ),
        )
    return None


def log_override(
    root: Path,
    *,
    tool: str,
    gate: str,
    rationale: str | None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Append a researcher-authorised gate bypass to the override log.

    Every time the AI calls a tool with ``override_completeness_gate=true``
    (or ``override_gate=true`` on ``tool_plan(operation='advance')``), we record:

    * which tool was bypassed
    * which gate it was
    * the rationale the researcher supplied (or ``<none provided>`` —
      this surfaces in audits as a soft warning)
    * a UTC timestamp

    The log lives at ``workspace/logs/override_log.md`` so the
    pre-submission audit can list every bypass and ask the researcher
    to confirm before publication.
    """
    logs = root / "workspace" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / "override_log.md"
    if not log.exists():
        log.write_text(
            "# Quality-gate bypass log\n\n"
            "Every entry here represents a moment the researcher "
            "explicitly authorised the AI to bypass a quality gate. "
            "The pre-submission audit surfaces this list — confirm "
            "each bypass was intentional before submission.\n\n"
        )
    note = (rationale or "").strip() or "<no rationale provided — flag in audit>"
    extras = ""
    if extra:
        try:
            extras = " · " + json.dumps(extra, sort_keys=True, default=str)
        except Exception:
            extras = ""
    with log.open("a") as fh:
        fh.write(f"- {now_iso()} · `{tool}` · gate={gate} · {note}{extras}\n")
    return log


def enforce_override(
    root: Path,
    *,
    requested: bool,
    rationale: str | None,
    tool: str,
    gate: str,
    blocked: bool,
    extra: dict[str, Any] | None = None,
    empty_msg: str | None = None,
) -> dict | None:
    """One-stop override enforcement for quality gates (the canonical sequence).

    Replaces the require-rationale → reject-thin → log_override block that was
    hand-rolled across many gate handlers (and had drifted: some sites skipped
    the empty-rationale guard, and one never journaled the bypass at all).

    Returns either:
      * an ``_error`` envelope dict — caller must ``return _text(that)``
        (rationale missing-when-required, or too thin); OR
      * ``None`` — proceed. When ``requested and blocked`` is True the bypass has
        already been journaled to override_log.md as a side effect.

    The ``blocked`` trigger varies per auditor (``blockers`` vs
    ``bypassed_blockers`` vs ``override_no_pdfs``), so the caller passes a
    pre-computed bool rather than the helper inspecting the result shape. Typical
    use::

        err = enforce_override(root, requested=req, rationale=r, tool="tool_x",
                               gate="g", blocked=bool(res.get("blockers")))
        if err is not None:
            return _text(err)
        if req and res.get("blockers"):
            res["override_applied"] = True; res["status"] = "success"
    """
    from research_os.server.envelopes import _error

    if requested and not (rationale and str(rationale).strip()):
        return _error(
            what=f"{tool}: override requires override_rationale",
            why=(
                "an un-rationaled bypass would log rationale=None and slip past "
                "the pre-submission audit"
            ),
            next_action=(
                empty_msg
                or 'pass override_rationale="..." (>=20 chars, multi-word, substantive)'
            ),
        )
    if requested and rationale:
        thin = validate_override_rationale(rationale)
        if thin is not None:
            return thin
    if requested and blocked:
        log_override(root, tool=tool, gate=gate, rationale=rationale, extra=extra)
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_root(root: Path | None = None) -> Path:
    if root is not None:
        return root
    r = find_project_root()
    if not r:
        raise ValueError("Could not find project root containing .os_state/")
    return r


def slugify(value: str, fallback: str = "path", *, max_len: int = 40) -> str:
    """Sanitise + truncate a slug for safe filesystem use.

    Strips path-traversal sequences and caps length to prevent
    absurdly-long step folder names. Returns ``fallback`` if the input
    contains no usable characters.
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    # Defence-in-depth against path traversal (the regex already strips
    # `..` and `/`, but make the intent explicit).
    slug = slug.replace("..", "_").replace("/", "_").strip("_")
    if max_len and len(slug) > max_len:
        slug = slug[:max_len].rstrip("_")
    return slug or fallback


def state_path(root: Path) -> Path:
    return root / ".os_state" / "state_ledger.yaml"


def state_json_path(root: Path) -> Path:
    return root / ".os_state" / "state_ledger.json"


def manifest_path(root: Path) -> Path:
    return root / ".os_state" / "manifest.json"


# ---------------------------------------------------------------------------
# Atomic JSON / YAML I/O
# ---------------------------------------------------------------------------


def read_json(path: Path, default: Any) -> Any:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp_path, str(path))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def compute_file_hash(path: Path) -> str:
    sha256 = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except (FileNotFoundError, PermissionError, OSError):
        return "error"


# ---------------------------------------------------------------------------
# State (single source of truth — ResearchLedger)
# ---------------------------------------------------------------------------


def default_state() -> dict:
    """Canonical default state — delegates to ResearchLedger's canonical schema.

    Kept as a thin wrapper for callers that import ``default_state`` directly.
    """
    return ResearchLedger._default_state()


def load_state(root: Path | None = None) -> dict:
    root = _resolve_root(root)
    ledger = ResearchLedger(state_json_path(root))
    state = ledger._load()
    if not state or "paths" not in state:
        state = default_state()
        ledger._save(state)
    return state


def save_state(root: Path, state: dict) -> dict:
    """Persist state via ResearchLedger. Migration runs on ``_load``, so any
    legacy keys that re-appear here from callers are normalised on read."""
    root = _resolve_root(root)
    ledger = ResearchLedger(state_json_path(root))
    state["updated_at"] = now_iso()
    # If callers handed us a legacy-shaped dict, normalise before saving so
    # the on-disk view stays canonical from this point forward.
    ResearchLedger._migrate(state)
    ledger._save(state)
    _write_os_state_summary(root)
    return state


def mutate_state(root: Path | None, fn: "Callable[[dict], None]") -> dict:
    """Atomic load→mutate→save under the ledger's exclusive lock.

    The unguarded ``load_state(...)`` → mutate → ``save_state(...)`` pattern
    has its lock window only around the final write, so two concurrent
    sessions on one workspace (the server is global + per-request
    root-resolved) can read the same state and clobber each other's
    mutation. ``mutate_state`` runs ``fn`` (which edits the state dict
    in-place) INSIDE the flock, serialising the whole read-modify-write.

    ``fn`` must not call back into ``load_state`` / ``save_state`` /
    ``mutate_state`` (it already holds the lock). ``updated_at`` is stamped
    by the ledger. ``STATE.md`` is regenerated OUTSIDE the lock afterwards
    (it re-reads state) so we never nest the lock.
    """
    root = _resolve_root(root)
    ledger = ResearchLedger(state_json_path(root))
    state = ledger.locked_update(fn)
    _write_os_state_summary(root)
    return state


def _write_os_state_summary(root: Path) -> None:
    """Render the canonical project status — a researcher- AND AI-readable
    snapshot of what's going on.

    This file lives at ``STATE.md`` at the PROJECT ROOT so a fresh
    AI session can find it without inside knowledge, and so a
    collaborator opening the project sees the status immediately. The
    contents include the active research question, the open hypotheses
    with status, the most-recent step finalized, the next pipeline-
    recommended protocol, and the key files. A plain-English "where to
    go from here" footer points new sessions
    at AGENTS.md + sys_boot.

    Old ``.os_state/os_state.md`` is removed by the caller (save_state)
    on first save after upgrade so the working tree doesn't end up
    with two copies.
    """
    try:
        state = load_state(root)
    except Exception:
        return

    try:
        from research_os.tools.actions.state.path import list_paths

        paths = list_paths(root).get("paths", []) or []
    except Exception:
        paths = []

    name = state.get("project_name") or "Research Project"
    stage = state.get("pipeline_stage", "init")
    current = state.get("current_path", "main")
    question = (state.get("research_question") or "").strip()
    questions = [
        q for q in (state.get("research_questions") or [])
        if isinstance(q, str) and q.strip()
    ]
    domain = (state.get("domain") or "").strip()
    hyps = state.get("active_hypotheses") or []

    # Last protocol log entry (so a fresh chat knows what happened most
    # recently without digging through workspace/analysis.md).
    last_protocol = None
    try:
        log = root / ".os_state" / "protocol_execution_log.jsonl"
        if log.exists():
            for line in reversed(log.read_text().splitlines()):
                if line.strip():
                    last_protocol = json.loads(line)
                    break
    except Exception:
        last_protocol = None

    lines = [
        f"# {name}",
        "",
        "*The canonical status file. A new AI session reads this first.*",
        f"*Last updated: {now_iso()}.*",
        "",
        "## What this project is",
        "",
        *(
            ["- **Research question(s):**"] + [f"  - {q}" for q in questions]
            if len(questions) > 1
            else [f"- **Research question:** {question or '_(not yet set — just tell the AI what you’re studying, e.g. “I want to know if X affects Y”)_'}"]
        ),
        f"- **Domain:** {domain or '_(unset)_'}",
        f"- **Pipeline phase:** `{stage}`",
        f"- **Active path:** `{current}`",
        "",
        "## Open hypotheses",
        "",
    ]
    if not hyps:
        lines.append("_(none registered yet)_")
    else:
        lines.append("| ID | Status | Statement |")
        lines.append("|---|---|---|")
        for h in hyps:
            hid = h.get("id", "?")
            status = h.get("status", "testing")
            stmt = (h.get("statement") or "")[:140]
            lines.append(f"| {hid} | {status} | {stmt} |")

    lines.extend([
        "",
        "## Analysis steps",
        "",
    ])
    if not paths:
        lines.append("_(no numbered steps yet)_")
    else:
        for p in paths:
            icon = {
                "completed": "✓",
                "active": "→",
                "dead_end": "✗",
            }.get(p.get("status", "active"), "•")
            pid = p.get("path_id", "?")
            hyp = (p.get("hypothesis") or "").strip()[:80]
            extra = f" — {hyp}" if hyp else ""
            lines.append(f"- {icon} `{pid}`{extra}")

    if last_protocol:
        lines.extend([
            "",
            "## Most recent action",
            "",
            f"- Protocol `{last_protocol.get('protocol', '?')}`"
            f" ({last_protocol.get('status', '?')}) at "
            f"{last_protocol.get('timestamp', '?')}",
        ])

    # What to do next — give a resuming AI a concrete pointer, not just a
    # snapshot. Stage-aware, and ALWAYS defers to sys_boot for the
    # authoritative next action so STATE.md can never silently contradict the
    # live router (sys_boot.advice / next_protocol).
    # Count finalized numbered steps on disk (the real "work has happened"
    # signal — there is no completed_steps field in state).
    ws = root / "workspace"
    n_steps = 0
    if ws.is_dir():
        n_steps = sum(
            1 for d in ws.iterdir()
            if d.is_dir() and d.name[:2].isdigit()
            and not d.name.endswith("__DEAD_END")
        )
    plan_exists = (root / "inputs" / "research_plan.md").exists()
    if stage in ("init", "") or not question:
        next_hint = (
            "Project not framed yet — set the research question + hypotheses "
            "(the researcher can just describe the project in chat, or drop "
            "files in `inputs/` and ask to fill the intake)."
        )
    elif (root / "synthesis").exists() and any(
        (root / "synthesis").glob("*.typ")
    ):
        next_hint = (
            "A deliverable is in progress under `synthesis/` — continue it, "
            "then run the pre-submission ship gate before declaring done."
        )
    elif n_steps > 0:
        next_hint = (
            "Analysis underway — continue the next step toward the open "
            "hypotheses, or begin synthesis once the evidence supports it."
        )
    else:
        next_hint = (
            "Framing is set but no steps have run — start the first analysis "
            "step (e.g. a baseline EDA)."
        )
    lines.extend([
        "",
        "## What to do next",
        "",
        f"- {next_hint}",
        "- For the authoritative next action, call `sys_boot` — it returns the"
        " live `advice` + `next_protocol` + active plan"
        + (" (a `inputs/research_plan.md` exists)" if plan_exists else "")
        + ". This file is a snapshot; `sys_boot` is the source of truth.",
    ])

    lines.extend([
        "",
        "## Key files (✓ exists / ⚪ not yet)",
        "",
    ])
    for f, label in [
        ("inputs/intake.md", "intake summary"),
        ("inputs/researcher_config.yaml", "config + autonomy"),
        ("docs/research_overview.md", "research question + overview"),
        ("workspace/analysis.md", "narrative log of every step"),
        ("workspace/methods.md", "methods log (assembles into paper)"),
        ("workspace/citations.md", "auto bibliography"),
        ("environment/requirements.txt", "reproducibility env"),
        ("synthesis/paper.typ", "draft paper (compiles to paper.pdf)"),
    ]:
        exists = (root / f).exists()
        lines.append(f"- {'✓' if exists else '⚪'} `{f}` — {label}")

    lines.extend([
        "",
        "## How to resume in a fresh chat",
        "",
        "1. Read `AGENTS.md` at project root (the AI's operating rules).",
        "2. Read THIS file (status + open hypotheses + what was last done).",
        "3. On your first turn, call `sys_boot` for the live state +"
        " active plan + pause classification.",
        "4. Then `tool_route(prompt=<the researcher's message>)`.",
    ])

    # Write the canonical version at project root.
    state_md = root / "STATE.md"
    state_md.write_text("\n".join(lines) + "\n")

    # Migration: remove the old buried copy if it exists from a prior
    # version. Best-effort — never raise.
    old = root / ".os_state" / "os_state.md"
    if old.exists():
        try:
            old.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Manifest (workspace tree snapshot)
# ---------------------------------------------------------------------------


def _update_manifest(root: Path) -> None:
    """Sync ``.os_state/manifest.json`` with the current workspace tree."""
    workspace = root / "workspace"
    paths_info: dict[str, Any] = {}
    if workspace.exists():
        for p in discover_step_dirs(workspace):
            scripts: list[str] = []
            scripts_dir = p / "scripts"
            if scripts_dir.exists():
                scripts = [f.name for f in sorted(scripts_dir.iterdir()) if f.is_file()]
            info = {
                "status": "dead_end" if "__DEAD_END" in p.name else "active",
                "has_readme": (p / "README.md").exists(),
                "has_conclusions": (p / "conclusions.md").exists(),
                "scripts": scripts,
            }
            # Record the PATH container when the step is grouped under one.
            if p.parent != workspace and is_path_container(p.parent.name):
                info["path_container"] = p.parent.name
            paths_info[p.name] = info
    manifest = read_json(manifest_path(root), {})
    manifest["paths"] = paths_info
    manifest["updated_at"] = now_iso()
    write_json(manifest_path(root), manifest)


# ---------------------------------------------------------------------------
# Hashing of input files
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Scaffolding
# ---------------------------------------------------------------------------


def _resolve_inner_repo_name(config_overrides: dict | None) -> str:
    """Pick the tool_build inner project dir name; blank → ``project``.

    Reads ``config_overrides['workspace']['inner_repo']`` if the wizard
    captured one. Sanitised to a single traversal-safe path segment.
    """
    raw = ""
    ws = (config_overrides or {}).get("workspace")
    if isinstance(ws, dict):
        raw = ws.get("inner_repo") or ""
    name = (raw or "").strip().strip("/").replace("..", "").strip()
    name = name.split("/")[0] if name else ""
    return name or "project"


def _seed_mode_extras(
    root: Path,
    project_name: str,
    mode: str,
    config_overrides: dict | None = None,
) -> str:
    """Seed the mode-specific surface (governance / scratch / onboarding).

    Returns the inner-repo dir name for ``tool_build`` (so the caller can
    ``git init`` it), or ``""`` for the other modes. A no-op for
    ``analysis`` — that mode's files are written entirely by the existing
    generic scaffold path, keeping its surface byte-identical to today.

    Mode-specific GETTING_STARTED.md + README.md are seeded HERE so the
    generic ``_write_getting_started`` / ``_write_project_root_readme``
    (which skip when the file already exists) leave them intact.
    """
    if mode == "analysis":
        return ""

    def _write_if_missing(path: Path, body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(body)

    if mode == "exploration":
        # Scratch-first. Point the researcher at workspace/scratch as the
        # home base, with a clear path to promote a probe into a real step.
        _write_if_missing(
            root / "GETTING_STARTED.md",
            f"""# Getting started with **{project_name}** (exploration mode)

This is a Research OS workspace in **exploration mode** — scratch-first,
light gates. The home base is `workspace/scratch/`: poke at the data,
run quick probes, throw things away freely.

## 1. Bring in your project — chat or files

Just tell the AI what you're poking at ("quick look at whether X relates to Y
in this CSV at <path>") — no files required. Or drop them in:

| Where | What goes here |
|---|---|
| `inputs/raw_data/`  | Data files (CSV, Parquet, FASTQ, NIfTI, JSON, Excel, ...) |
| `inputs/literature/`| PDFs of papers you want the AI to know about |
| `inputs/context/`   | Notes, drafts, prior reports — anything text |

## 2. Probe in scratch

`workspace/scratch/` is the sandbox. Quick EDA, a smoke model, a sanity
plot — none of it has to be rigorous yet. Try:

```
poke at the data
quick look at <column> vs <column>
is there any signal in <hypothesis>?
```

## 3. Promote what earns it

When a probe turns into something worth keeping, promote it to a proper
numbered step (`workspace/01_<slug>/`) — that's where gates, provenance,
and synthesis kick in:

```
promote this to a real step
```

The numbered-step + synthesis surface stays out of your way until then.

## More

* AI rules: `AGENTS.md`
* Config: `inputs/researcher_config.yaml` (`workspace.mode: exploration`)
""",
        )
        _write_if_missing(
            root / "README.md",
            f"""# {project_name}

> A Research OS workspace in **exploration mode** — scratch-first quick
> probes with light gates and a promote-to-step path.

## What's in this folder

| Folder | Purpose |
|---|---|
| `inputs/` | Immutable data, literature, context the probes read. |
| `workspace/scratch/` | The home base — quick throw-away probes. |
| `workspace/NN_slug/` | Promoted steps (appear once a probe earns it). |
| `docs/` | Glossary + overview. |
| `environment/` | Reproducibility surface. |

See `GETTING_STARTED.md` for the workflow.
""",
        )
        return ""

    if mode == "notebook":
        # Jupyter-first. The notebook is the unit of work; seed a starter
        # notebook + getting-started so a fresh researcher opens
        # notebooks/ and starts running cells immediately.
        nb_readme = (
            "# `notebooks/`\n\n"
            "The unit of work in this project is a **notebook**, not a "
            "numbered analysis step. Each notebook is a self-contained, "
            "top-to-bottom-runnable narrative: read from `../data/`, write "
            "figures / tables / exports to `../outputs/`.\n\n"
            "Discipline that keeps a notebook trustworthy:\n\n"
            "* **Restart-and-run-all is the only valid state.** A notebook "
            "  that only works out-of-order is a notebook that doesn't work. "
            "  Re-run top-to-bottom before you trust a result.\n"
            "* **Cells are the provenance unit.** One coherent idea per cell; "
            "  set the RNG seed in the first cell; print library versions so "
            "  the run is reproducible.\n"
            "* **Outputs are derived, never hand-edited.** Anything in "
            "  `../outputs/` should be regenerable by re-running the notebook "
            "  that produced it.\n\n"
            "Name notebooks by what they do, ordered for reading: "
            "`01_explore.ipynb`, `02_clean.ipynb`, `03_model.ipynb`. Run "
            "cells with `tool_notebook_exec`; promote a notebook's result "
            "into a paper/report via the synthesis tools when it's ready.\n"
        )
        _write_if_missing(root / "notebooks" / "README.md", nb_readme)
        _write_if_missing(
            root / "data" / "README.md",
            "# `data/`\n\n"
            "Working data the notebooks read + the derived data they write. "
            "Immutable source data still lives in `../inputs/raw_data/` (the "
            "AI never modifies it); copy or load from there into here, and "
            "treat anything here as regenerable from a notebook run.\n",
        )
        _write_if_missing(
            root / "outputs" / "README.md",
            "# `outputs/`\n\n"
            "Figures, tables, and exports the notebooks emit. Everything "
            "here is **derived** — regenerable by re-running the notebook "
            "that wrote it. Don't hand-edit; fix the cell and re-run.\n",
        )
        _write_if_missing(
            root / "GETTING_STARTED.md",
            f"""# Getting started with **{project_name}** (notebook mode)

This is a Research OS workspace in **notebook mode** — Jupyter-first. The
unit of work is a notebook in `notebooks/`, not a numbered analysis step.

## 1. Bring in your project — chat or files

Tell the AI what the notebook is for ("explore whether X drives Y in this
dataset at <path>") — no files required. Or drop them in:

| Where | What goes here |
|---|---|
| `inputs/raw_data/`  | Immutable source data (CSV, Parquet, FASTQ, ...) |
| `inputs/literature/`| PDFs of papers the AI should know about |
| `inputs/context/`   | Notes, drafts, prior reports |
| `data/`             | Working + derived data the notebooks read/write |

`inputs/raw_data/` + `inputs/literature/` are source-of-truth (soft-guarded);
the AI freely maintains the rest of `inputs/` (context, intake, config). Only
`.os_state/` is hard-locked. Derived + working data lives under `data/`,
and notebook figures/exports under `outputs/`.

## 2. Work in notebooks

`notebooks/` is the home base. Each notebook is a top-to-bottom-runnable
narrative; outputs land in `outputs/`. Try:

```
start a notebook for exploring <dataset>
run this notebook
clean up cell 3 and re-run from there
```

The cell-as-unit discipline (restart-and-run-all, seed in cell 1, derived
outputs only) is what keeps the work reproducible — see
`notebooks/README.md`.

## 3. Synthesize when ready

When a notebook's result is worth keeping, promote it into a paper /
report / dashboard via the synthesis tools.

## More

* AI rules: `AGENTS.md`
* Config: `inputs/researcher_config.yaml` (`workspace.mode: notebook`)
""",
        )
        _write_if_missing(
            root / "README.md",
            f"""# {project_name}

> A Research OS workspace in **notebook mode** — Jupyter-first. The unit of
> work is a notebook in `notebooks/`; outputs are derived into `outputs/`.

## What's in this folder

| Folder | Purpose |
|---|---|
| `notebooks/` | The unit of work — runnable, ordered notebooks. |
| `data/` | Working + derived data the notebooks read/write. |
| `outputs/` | Figures / tables / exports (derived, regenerable). |
| `inputs/` | Immutable source data, literature, context. |
| `synthesis/` | Paper / report (appears once you synthesize). |
| `environment/` | Reproducibility surface. |

See `GETTING_STARTED.md` for the workflow.
""",
        )
        return ""

    if mode == "multi_study":
        # Program / portfolio. Seed the program governance commons so a
        # fresh researcher understands the study → shared → roll-up model.
        _write_if_missing(
            root / "studies" / "README.md",
            "# `studies/` — the sub-studies in this program\n\n"
            "Each sub-study is a **child** of the program: one folder per "
            "study (`studies/<slug>/`), each its own coherent piece of work "
            "with its own question, data, analysis, and conclusion. A study "
            "is the unit of work in multi_study mode — not a numbered step.\n\n"
            "Every study inherits the program commons in `../shared/` (the "
            "codebook, the preregistration, the governing protocol). Keep "
            "study-specific deviations from the shared codebook documented "
            "inside that study so the roll-up can account for them.\n\n"
            "When you start a new study, create `studies/<slug>/` and treat "
            "it as a small project surface; the cross-study synthesis happens "
            "in `../roll_up/`.\n",
        )
        _write_if_missing(
            root / "shared" / "README.md",
            "# `shared/` — the program commons every study inherits\n\n"
            "The single source of truth shared across all sub-studies. "
            "Keeping these here (rather than copied into each study) is what "
            "makes the program coherent and the roll-up valid.\n\n"
            "* `codebook.md` — the shared variable definitions / coding "
            "  scheme. Every study codes to THIS unless it documents a "
            "  deviation. Divergent codebooks make a meta-analysis "
            "  meaningless.\n"
            "* `preregistration.md` — the program-level prereg: the "
            "  hypotheses + analysis commitments that span studies, frozen "
            "  before the studies run.\n"
            "* `protocol.md` — the governing protocol each study follows "
            "  (inclusion criteria, shared measures, common QC).\n",
        )
        _write_if_missing(
            root / "shared" / "codebook.md",
            "# Shared codebook\n\n"
            "Program-wide variable definitions + coding scheme. Every study "
            "codes to this. Document any per-study deviation inside that "
            "study, not here.\n\n"
            "| Variable | Definition | Values / coding | Source |\n"
            "|---|---|---|---|\n",
        )
        _write_if_missing(
            root / "shared" / "preregistration.md",
            "# Program preregistration\n\n"
            "_The hypotheses + analysis commitments that span the studies in "
            "this program, frozen before the studies run. Per-study prereg "
            "(if any) lives inside each study._\n\n"
            "## Program hypotheses\n\n"
            "_What the program as a whole predicts, across studies._\n\n"
            "## Cross-study analysis plan\n\n"
            "_How results will be pooled / compared in `roll_up/` (fixed vs "
            "random effects, heterogeneity handling, moderators), decided "
            "before seeing study results._\n",
        )
        _write_if_missing(
            root / "shared" / "protocol.md",
            "# Governing protocol\n\n"
            "_The protocol every sub-study in this program follows, so the "
            "studies stay commensurable. Referenced by `shared/README.md`, the "
            "program's GETTING_STARTED, and `program/program_setup`. Per-study "
            "deviations are documented inside each study, not here._\n\n"
            "## Eligibility / inclusion\n\n"
            "_What makes a unit (sample, subject, record) eligible for any "
            "study in this program._\n\n"
            "## Shared procedure\n\n"
            "_The steps every study runs the same way (collection, "
            "measurement, QC), so results can be pooled in `roll_up/`._\n\n"
            "## Deviations log\n\n"
            "_When a study must depart from this protocol, record it here with "
            "the study slug + rationale so the roll-up can account for it._\n",
        )
        _write_if_missing(
            root / "roll_up" / "README.md",
            "# `roll_up/` — cross-study synthesis + meta-analysis\n\n"
            "Where the program becomes more than its studies. This is the "
            "ONLY place that reads ACROSS `../studies/` to produce a "
            "program-level claim:\n\n"
            "* the meta-analysis / pooled estimate across studies,\n"
            "* the heterogeneity story (why studies agree or differ),\n"
            "* the cross-study narrative the program reports.\n\n"
            "A roll-up is only valid when the studies share a codebook + "
            "prereg (see `../shared/`). If a study deviated, account for the "
            "deviation here rather than quietly pooling over it.\n",
        )
        _write_if_missing(
            root / "governance.md",
            f"# Governance — {project_name} (program / multi_study)\n\n"
            "This is a **multi_study** Research OS workspace — a research "
            "**program**, not a single analysis. The program model:\n\n"
            "* `studies/<slug>/` — each sub-study, a child of the program. "
            "  The unit of work is a STUDY; heavyweight analysis happens "
            "  inside each study.\n"
            "* `shared/` — the commons every study inherits: the codebook, "
            "  the preregistration, the governing protocol. Coherence across "
            "  studies is what makes the program's roll-up valid.\n"
            "* `roll_up/` — cross-study synthesis + meta-analysis: the one "
            "  place that reads across studies to make a program-level "
            "  claim.\n\n"
            "Mode-agnostic safety holds: `.os_state/` is hard-locked, "
            "original inputs (raw_data/literature) are soft-guarded, all "
            "workspace writes go through the tools, nothing escapes the "
            "project root. Run `program/program_setup` to reason about the "
            "shared codebook + prereg + how the studies roll up.\n",
        )
        _write_if_missing(
            root / "GETTING_STARTED.md",
            f"""# Getting started with **{project_name}** (multi_study mode)

This is a Research OS workspace in **multi_study mode** — a research
**program**: several sub-studies that share a codebook + prereg and roll
up into a cross-study synthesis.

## The program layout

| Path | What it's for |
|---|---|
| `studies/<slug>/` | Each sub-study — a child of the program. |
| `shared/codebook.md` | Variable definitions every study codes to. |
| `shared/preregistration.md` | Program-level hypotheses + pooling plan. |
| `shared/protocol.md` | The governing protocol each study follows. |
| `roll_up/` | Cross-study synthesis + meta-analysis. |
| `governance.md` | How the program model fits together. |

## Typical flow

1. Set up the commons first: the shared codebook + preregistration in
   `shared/`. Coherence here is what makes the roll-up valid.
2. Start each sub-study under `studies/<slug>/`; it inherits the commons.
3. When studies have results, do the cross-study synthesis in `roll_up/`.

Start by running `program/program_setup` — it reasons about the shared
codebook, the prereg, and how the studies will roll up.

## More

* AI rules: `AGENTS.md`
* Config: `inputs/researcher_config.yaml` (`workspace.mode: multi_study`)
""",
        )
        _write_if_missing(
            root / "README.md",
            f"""# {project_name}

> A Research OS workspace in **multi_study mode** — a research program of
> sub-studies that share a codebook + prereg and roll up into a cross-study
> synthesis.

## What's in this folder

| Path | Purpose |
|---|---|
| `studies/` | Each sub-study — a child of the program. |
| `shared/` | The commons every study inherits (codebook / prereg / protocol). |
| `roll_up/` | Cross-study synthesis + meta-analysis. |
| `governance.md` | How the program model fits together. |
| `inputs/` | Immutable data / literature / context. |

See `GETTING_STARTED.md` for the workflow.
""",
        )
        return ""

    # ── hybrid (research + software) ─────────────────────────────────────
    # H1/H2/H3 fix: hybrid was falling through to the tool_build seeding, so a
    # hybrid project got tool_build's surface + onboarding ("...in tool_build
    # mode") and the AI couldn't tell it was hybrid. Seed a hybrid-specific
    # surface that describes BOTH halves: the analysis spine (numbered steps +
    # synthesis) AND the inner software component under tool/ (its own repo,
    # auto-detected by detect_software_components). Returns "tool" so the caller
    # git-inits the inner repo (see the git-init guard below).
    if mode == "hybrid":
        _write_if_missing(
            root / "tool" / "README.md",
            f"# `tool/` — the inner software component of {project_name}\n\n"
            "This hybrid project has TWO halves that share one provenance "
            "discipline:\n\n"
            "1. **The analysis spine** — numbered steps in `workspace/NN_*/` "
            "feeding `synthesis/` (the paper/report), exactly like analysis "
            "mode.\n"
            "2. **This inner tool** — the software you build to DO the analysis "
            "(a model, a pipeline, a library). It is its OWN git repository; "
            "commit code here. Research OS governs it via `tool_git` / "
            "`tool_build` on this repo and auto-detects it as a software "
            "component (it surfaces in `sys_boot.software_components`).\n\n"
            "Which side am I on? If you're producing a FIGURE/finding for the "
            "paper, you're on the analysis spine (use a numbered step). If "
            "you're writing/improving the CODE that produces it, you're in "
            "`tool/` (commit + version it here). The "
            "`hybrid/tool_to_analysis_handoff` protocol moves a finished tool "
            "into an analysis step.\n",
        )
        _write_if_missing(
            root / "GETTING_STARTED.md",
            f"""# Getting started with **{project_name}** (hybrid mode)

This is a Research OS workspace in **hybrid mode** — a research analysis
project that ALSO builds its own software. Two halves, one project:

| Half | Where | Unit of work | Governed by |
|---|---|---|---|
| Analysis spine | `workspace/NN_*/` → `synthesis/` | a numbered step | analysis protocols |
| Inner tool | `tool/` (its own git repo) | a code increment | tool_git / tool_build |

The inner tool is auto-detected — it shows up in `sys_boot.software_components`
so a fresh session always sees both halves. Build/version the code in `tool/`;
when a tool is ready to produce a result, hand it to the analysis spine via the
`hybrid/tool_to_analysis_handoff` protocol and ground the finding there.

Mode-agnostic safety holds: `.os_state/` is hard-locked, original inputs are
soft-guarded, all workspace writes go through the tools, nothing escapes root.

See the protocols `hybrid/hybrid_workflow` and `hybrid/tool_to_analysis_handoff`
for the loop.
""",
        )
        return "tool"

    # ── tool_build ──────────────────────────────────────────────────────
    inner = _resolve_inner_repo_name(config_overrides)

    # spec/ — requirements + design.
    _write_if_missing(
        root / "spec" / "README.md",
        "# `spec/` — what we're building\n\n"
        "The governance source of truth for this tool: requirements,\n"
        "design, and interface contracts. Research OS reads these to keep\n"
        "the build honest against intent.\n\n"
        "* `requirements.md` — what the tool must do (functional +\n"
        "  non-functional). Start here.\n"
        "* `design.md` — how it's built: architecture, key modules, the\n"
        "  data + control flow, trade-offs considered.\n\n"
        "Keep these current as the design moves — a decision that changes\n"
        "the design should land both here AND as an ADR in `decisions/`.\n",
    )
    _write_if_missing(
        root / "spec" / "requirements.md",
        f"# {project_name} — requirements\n\n"
        "## Problem\n\n"
        "_What problem does this tool solve, and for whom?_\n\n"
        "## Functional requirements\n\n"
        "- [ ] _The tool must…_\n\n"
        "## Non-functional requirements\n\n"
        "- [ ] _Performance / reliability / portability constraints…_\n\n"
        "## Out of scope\n\n"
        "_What this tool deliberately does NOT do._\n",
    )
    _write_if_missing(
        root / "spec" / "design.md",
        f"# {project_name} — design\n\n"
        "## Architecture\n\n"
        "_High-level shape: modules, boundaries, the main flow._\n\n"
        "## Key decisions\n\n"
        "_Summarise the load-bearing choices; the full record lives in_\n"
        "`decisions/` _as ADRs._\n\n"
        "## Open questions\n\n"
        "_What's still unresolved._\n",
    )

    # decisions/ — Architecture Decision Records.
    _write_if_missing(
        root / "decisions" / "README.md",
        "# `decisions/` — Architecture Decision Records (ADRs)\n\n"
        "One Markdown file per significant decision, numbered in order:\n"
        "`0001-<slug>.md`, `0002-<slug>.md`, … Each records the context,\n"
        "the decision taken, and the consequences — so a future\n"
        "contributor (or a fresh AI session) understands WHY the tool is\n"
        "shaped the way it is, not just how.\n\n"
        "Template per ADR:\n\n"
        "```\n"
        "# <NNNN>. <Title>\n\n"
        "Status: proposed | accepted | superseded\n\n"
        "## Context\nWhat forces are at play?\n\n"
        "## Decision\nWhat we chose.\n\n"
        "## Consequences\nWhat becomes easier / harder as a result.\n"
        "```\n",
    )

    # eval/ — the benchmark / eval harness that defines "done".
    _write_if_missing(
        root / "eval" / "README.md",
        "# `eval/` — how we know the tool works\n\n"
        "In tool_build mode, **\"done\" is defined by tests / build / eval,\n"
        "not by figures.** This folder holds the harness that decides\n"
        "whether the inner tool meets `spec/requirements.md`:\n\n"
        "* benchmark datasets / fixtures the tool is scored against,\n"
        "* the eval scripts that run it and report pass / fail,\n"
        "* expected-output baselines to diff against.\n\n"
        "Wire the inner project's own test suite up too — the eval here\n"
        "governs from above (acceptance), the inner tests guard from\n"
        "within (units / integration).\n",
    )

    # milestones.md — the build roadmap.
    _write_if_missing(
        root / "milestones.md",
        f"# {project_name} — milestones\n\n"
        "The build roadmap. Each milestone is a coherent, shippable\n"
        "increment with a clear acceptance bar (a passing eval / test, a\n"
        "working build), not a calendar date.\n\n"
        "| # | Milestone | Acceptance (eval / test / build) | Status |\n"
        "|---|---|---|---|\n"
        "| 1 | _First runnable skeleton_ | _builds + smoke eval passes_ | todo |\n",
    )

    # governance.md — the load-bearing explainer for tool_build mode.
    _write_if_missing(
        root / "governance.md",
        f"# Governance — {project_name}\n\n"
        "This is a **tool_build** Research OS workspace. Research OS does\n"
        "NOT contain the tool; it **governs the build from above**.\n\n"
        f"* The actual tool lives in `{inner}/` — its own git repository.\n"
        "  Commit your code there; it has its own history independent of\n"
        "  this governance layer.\n"
        "* This outer workspace holds the governance surface:\n"
        "  * `spec/` — what we're building + the design.\n"
        "  * `decisions/` — ADRs: why the tool is shaped this way.\n"
        "  * `eval/` — the harness that defines \"done\" (tests / build /\n"
        "    benchmarks), since this mode is judged by passing checks,\n"
        "    not by figures.\n"
        "  * `milestones.md` — the roadmap of shippable increments.\n"
        "  * `CHANGELOG.md` — what changed, milestone by milestone.\n\n"
        "Mode-agnostic safety holds here too: `.os_state/` is hard-locked,\n"
        "original inputs (raw_data/literature) are soft-guarded, all\n"
        "workspace writes go through the tools, and nothing escapes the\n"
        "project root.\n",
    )

    # CHANGELOG.md — milestone-by-milestone history.
    _write_if_missing(
        root / "CHANGELOG.md",
        f"# Changelog — {project_name}\n\n"
        "All notable changes to the tool, grouped by milestone. Newest on\n"
        "top.\n\n"
        "## [Unreleased]\n\n"
        "- _Initial scaffold._\n",
    )

    # The inner project dir + a README that orients a builder opening it
    # cold. The dir itself is git-init'd by the caller.
    _write_if_missing(
        root / inner / "README.md",
        f"# {project_name}\n\n"
        "This is the **inner project** — the actual tool. It is its own\n"
        "git repository, governed from above by a Research OS workspace in\n"
        f"the parent directory (see `../governance.md`).\n\n"
        "* What it must do → `../spec/requirements.md`\n"
        "* How it's built → `../spec/design.md`\n"
        "* Why it's shaped this way → `../decisions/`\n"
        "* How we know it works → `../eval/`\n\n"
        "Build here. Commit here. Keep the spec + ADRs + eval in the parent\n"
        "current as the design moves.\n",
    )

    # Onboarding files tuned for tool_build (seeded before the generic
    # writers so they win).
    _write_if_missing(
        root / "GETTING_STARTED.md",
        f"""# Getting started with **{project_name}** (tool_build mode)

This is a Research OS workspace in **tool_build mode**. Research OS
governs the build from above; the tool itself lives in `{inner}/` —
its own git repo. "Done" here means tests / build / eval pass, not
figures.

## The governance layer (this folder)

| Path | What it's for |
|---|---|
| `spec/requirements.md` | What the tool must do. Start here. |
| `spec/design.md` | How it's built. |
| `decisions/` | ADRs — why it's shaped this way. |
| `eval/` | The harness that defines "done". |
| `milestones.md` | Roadmap of shippable increments. |
| `governance.md` | How the whole thing fits together. |
| `{inner}/` | **The actual tool** — its own git repository. |

## Typical loop

1. Sharpen `spec/requirements.md` and `spec/design.md`.
2. Record load-bearing choices as ADRs in `decisions/`.
3. Build in `{inner}/`; commit there.
4. Add / run eval in `eval/`; a milestone is done when its checks pass.
5. Note the change in `CHANGELOG.md`; move to the next milestone.

## More

* AI rules: `AGENTS.md`
* Config: `inputs/researcher_config.yaml` (`workspace.mode: tool_build`)
""",
    )
    _write_if_missing(
        root / "README.md",
        f"""# {project_name}

> A Research OS workspace in **tool_build mode** — Research OS governs the
> build (spec + decisions + eval + milestones); the tool itself lives in
> `{inner}/` as its own git repository.

## What's in this folder

| Path | Purpose |
|---|---|
| `spec/` | Requirements + design — what we're building. |
| `decisions/` | Architecture Decision Records (ADRs). |
| `eval/` | The harness that defines "done" (tests / build / benchmarks). |
| `milestones.md` | Roadmap of shippable increments. |
| `governance.md` | How the governance layer + inner repo fit together. |
| `{inner}/` | The actual tool — its own git repo. |
| `inputs/` | Immutable data / literature / context. |

See `GETTING_STARTED.md` for the build loop.
""",
    )
    return inner


def scaffold_minimal_workspace(
    root: Path,
    project_name: str,
    config_overrides: dict | None = None,
    git_init: bool = False,
    ide_flags: list[str] | None = None,
    copy_agents: bool = True,
    mode: str | None = None,
) -> None:
    """Create the workspace directory tree.

    Philosophy: scaffold creates ONLY the directories + the bare minimum files
    the AI / researcher need before the first session boot. We do NOT
    pre-create synthesis outputs (paper.typ, poster.typ, ...), per-experiment
    folders, or pre-filled docs. Those get written by the protocols that own
    them, when (and only when) they're needed.

    The ``mode`` selects a scaffold profile (see ``SCAFFOLD_PROFILES``).
    When ``None`` the mode is read from the config the wizard captured (via
    ``config_overrides['workspace']['mode']``), falling back to ``analysis``
    — the classic linear-step workspace, whose surface is byte-identical to
    every prior release.
    """
    config_overrides = config_overrides or {}
    # Distinguish "caller didn't specify" (None → sensible default set) from
    # "caller explicitly asked for no IDE wiring" ([] from --ide none). Using
    # `or` here treated the empty list as falsy and wired 5 IDEs anyway — the
    # --ide none footgun. An empty list now correctly wires nothing.
    if ide_flags is None:
        ide_flags = ["cursor", "claude", "antigravity", "opencode", "vscode"]

    # Resolve the workspace mode + its scaffold profile. The wizard threads
    # the chosen mode through config_overrides['workspace']['mode']; an
    # explicit ``mode`` argument wins for direct callers. Anything unknown
    # (or absent) collapses to ``analysis`` so old/odd inputs behave classic.
    if mode is None:
        ws_over = config_overrides.get("workspace")
        if isinstance(ws_over, dict):
            mode = ws_over.get("mode")
    mode, profile = _resolve_scaffold_profile(mode)
    eager_dirs = profile["eager_dirs"]
    top_level_dirs = profile["top_level_dirs"]
    lazy_dirs = profile["lazy_dirs"]

    root.mkdir(parents=True, exist_ok=True)

    # 1. Eager skeleton — only the directories that are GUARANTEED to be
    #    populated by the rest of this scaffold. Lazy dirs (synthesis/,
    #    environment/, inputs/raw_data/, inputs/literature/, inputs/context/)
    #    are deferred to first-write via ``ensure_lazy_dir`` so a fresh
    #    project surface has no orphan .gitkeep folders.
    for rel in eager_dirs:
        d = root / rel
        d.mkdir(parents=True, exist_ok=True)

    # 2. docs/glossary.md — empty table (the AI fills it).
    glossary = root / "docs" / "glossary.md"
    if not glossary.exists():
        glossary.write_text(
            "# Glossary\n\n"
            "Domain-specific terms used in this project — definitions and "
            "their source. The AI auto-populates this table when it "
            "encounters new terminology in your data or literature; you "
            "can also add rows by hand.\n\n"
            "| Term | Definition | Source |\n|---|---|---|\n"
        )

    # 3. docs/research_overview.md — created LAZILY by
    #    ``tool_intake_autofill``. Leaving it absent on a cold init avoids
    #    the "what's all this placeholder text?" friction; the researcher
    #    is pointed at it via inputs/intake.md instead.

    # 4. Append-only workspace logs — start EMPTY but with a header so the
    #    AI knows the file is initialised.
    #    Researcher-facing wording. These files are read by humans
    #    (you, your PI, a collaborator on a fresh chat). They should
    #    not name internal tools by their MCP function name — you
    #    don't care that `mem_log(kind='analysis')` is what writes here; you
    #    care what the file IS and how to read it.
    for fname, header in [
        ("methods.md",
         "# Methods\n\n"
         "Chronological record of every methodological choice made in "
         "this project — which model, why, with what parameters, citing "
         "what literature. The Methods section of your eventual paper "
         "is assembled from this file. Each analysis step appends a "
         "subsection here when it finalizes.\n"),
        ("analysis.md",
         "# Analysis log\n\n"
         "Running narrative of what was done in each numbered analysis "
         "step (`workspace/01_...`, `02_...`, …) — the headline finding, "
         "the figures and tables it produced, the decision taken at the "
         "end. Read top-to-bottom to retrace the project's reasoning; "
         "a fresh AI session can resume from this file alone.\n"),
        ("citations.md",
         "# Citations\n\n"
         "Auto-generated bibliography across the project + every per-"
         "step `literature/` folder. The Discussion / References of "
         "your paper draws from here. Regenerated whenever a step is "
         "finalized so newly-added PDFs appear automatically.\n"),
        # tools.md — append-only log of which Research-OS tools (and
        # which 3rd-party packages, external services, web searches)
        # were used in this project, when, and why. Surfaces the
        # *provenance of the workflow* for reviewers + future
        # collaborators in a single place — methods.md tells WHAT the
        # analysis did; tools.md tells WHICH MACHINERY enabled it.
        ("tools.md",
         "# Tools log\n\n"
         "Chronological record of the tooling stack actually used by "
         "this project — Research-OS MCP calls (route, search, audit, "
         "finalize), 3rd-party packages (statsmodels, scanpy, DESeq2, "
         "Cytoscape, …), external services (Semantic Scholar, PubMed, "
         "GTEx, GEO), and any custom scripts the analyses depend on.\n\n"
         "Format: one bullet per usage, grouped by analysis step + "
         "synthesis stage. The synthesis dashboard surfaces this so a "
         "reviewer can audit reproducibility without re-deriving the "
         "stack from the scripts.\n\n"
         "Each step's `tool_path_finalize` appends a section here from "
         "its `conclusions.md` Methods + the per-step provenance "
         "sidecars; manual additions are welcome.\n"),
    ]:
        p = root / "workspace" / fname
        if not p.exists():
            p.write_text(header)

    # 5. workflow.mermaid — minimal diagram; expanded by _update_workflow_mermaid.
    wf = root / "workspace" / "workflow.mermaid"
    if not wf.exists():
        wf.write_text(
            "graph TD\n"
            "    init[Initialised]:::complete\n"
            "    classDef complete fill:#d4edda,stroke:#28a745\n"
        )

    # 5a. environment/ — project-global env scaffold.
    #     Eager (not lazy) so a fresh researcher can tell whether the
    #     workspace has a reproducible env story at all; an empty
    #     folder with two header files is enough to point them at what
    #     goes here and how it gets filled.
    env_dir = root / "environment"
    env_dir.mkdir(parents=True, exist_ok=True)
    env_req = env_dir / "requirements.txt"
    if not env_req.exists():
        env_req.write_text(
            "# Project-global Python packages.\n"
            "#\n"
            "# Add packages here as you install them, or call\n"
            "# `sys_env(operation='snapshot')` from the AI to regenerate\n"
            "# this from the active interpreter. Pin to a major when\n"
            "# stability matters (e.g. `pandas>=2.0,<3`).\n"
            "#\n"
            "# Per-step requirements (when one step needs different\n"
            "# versions) live in `workspace/<NN_slug>/environment/\n"
            "# requirements.txt` — see that step's README.\n"
        )
    env_readme = env_dir / "README.md"
    if not env_readme.exists():
        env_readme.write_text(
            "# Project environment\n\n"
            "Single source of truth for the Python (and other-language)\n"
            "packages this project depends on. Reproducibility starts here.\n\n"
            "* `requirements.txt` — pip-installable package list. Hand-add\n"
            "  or regenerate via `sys_env(operation='snapshot')`.\n"
            "* `Dockerfile` — generated on demand by\n"
            "  `sys_env(operation='docker_generate')`.\n"
            "* Conda export, R session info, system pkgs — pile in as\n"
            "  needed; the snapshot accepts language hints.\n\n"
            "When a single analysis step needs a bespoke environment\n"
            "different from the project default, snapshot inside that\n"
            "step instead: `sys_env(operation='snapshot', step_id='NN_slug')`.\n"
            "Each step that runs code should carry its OWN snapshot so it\n"
            "is independently reproducible and containerizable — a global\n"
            "env is not enough to re-run ONE step in isolation. The daemon\n"
            "watches for steps that ran scripts but have no per-step\n"
            "snapshot and flags `step_no_env_snapshot`.\n"
        )

    # 5a-b. workspace/logs/ — append-only audit/search/override trail.
    #       Ships with a README so researchers know what lands here
    #       and can grep across audit reports without first finding
    #       out the folder exists. Eager in analysis / tool_build; deferred
    #       in exploration (scratch-first), where it's created on first
    #       audit/override write.
    if "workspace/logs" in eager_dirs:
        logs_dir = root / "workspace" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        logs_readme = logs_dir / "README.md"
        if not logs_readme.exists():
            logs_readme.write_text(
            "# `workspace/logs/` — audit + activity trail\n\n"
            "Aggregated logs that every step (and every audit tool)\n"
            "appends to. Files here are append-only and machine-written;\n"
            "to read across steps, grep here:\n\n"
            "* `audit_report.md` — every `tool_audit_quality_full` run.\n"
            "* `search_log.md` — every literature / web search\n"
            "  (`tool_search_*` and `tool_literature_search_and_save`).\n"
            "* `repair_log.md` — every `tool_workspace_repair` invocation\n"
            "  (file moves, broken-link fixes).\n"
            "* `override_log.md` — every `override_completeness_gate=true`\n"
            "  bypass with the rationale that authorised it. Surfaced at\n"
            "  pre-submission audit time.\n"
            "* `task_*.log` — stdout/stderr of `tool_python_exec` /\n"
            "  `tool_task_run` script invocations.\n"
            "* `notifications.log` — `sys_notify` messages.\n"
            "* `version_coherence.md` — drift between scripts and the\n"
            "  outputs that cite them (from `tool_audit_version_coherence`).\n"
            )

    # 5b. workspace/scratch/ — AI sandbox. Gitignored.
    scratch_dir = root / "workspace" / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    scratch_gi = scratch_dir / ".gitignore"
    if not scratch_gi.exists():
        scratch_gi.write_text("*\n!.gitignore\n!README.md\n")
    scratch_readme = scratch_dir / "README.md"
    if not scratch_readme.exists():
        scratch_readme.write_text(
            "# Scratch\n\n"
            "AI sandbox for one-off tests (syntax checks, smoke runs, parameter\n"
            "sweeps, throw-away queries). Contents are gitignored.\n\n"
            "Anything that produces **research** must be moved into a proper\n"
            "numbered experiment folder via `sys_path(operation='create')` before it counts.\n\n"
            "Tools: `tool_scratch(operation='write')`, `tool_scratch(operation='run')`,\n"
            "`tool_scratch(operation='list')`, `tool_scratch(operation='clear')`.\n"
        )

    # 6. researcher_config.yaml — source of truth for AI behaviour. Stamp
    #    the resolved workspace mode into the config so the file on disk
    #    matches the scaffold that was built (analysis leaves the template
    #    default untouched, so its config stays byte-identical to today).
    from research_os.tools.actions.state.config import init_config

    if mode != "analysis":
        ws_over = dict(config_overrides.get("workspace") or {})
        ws_over.setdefault("mode", mode)
        config_overrides["workspace"] = ws_over
    init_config(root, overrides=config_overrides)

    # 7. .os_state symlink inside workspace/ for scripts that resolve relative.
    workspace_os_state = root / "workspace" / ".os_state"
    if not workspace_os_state.exists():
        try:
            workspace_os_state.symlink_to(root / ".os_state", target_is_directory=True)
        except OSError:
            pass

    # 8. inputs/intake.md — single-line pointer. Replaced wholesale by
    #    tool_intake_autofill once the researcher drops files + says
    #    "fill out the intake".
    intake = root / "inputs" / "intake.md"
    if not intake.exists():
        intake.write_text(
            "# Research Intake\n\n"
            "<!-- ro:intake-template -->\n"
            "You have two easy ways to set this up — pick whichever suits you:\n\n"
            "1. **Just tell the AI in chat.** Say something like \"my question "
            "is X, my data is at <path>, hypotheses are H1/H2\" and ask it to "
            "**fill out the intake** — it captures what you said into this file "
            "(no need to edit anything yourself).\n"
            "2. **Drop files, then ask.** Put data in `inputs/raw_data/`, PDFs "
            "in `inputs/literature/`, notes in `inputs/context/`, then ask the "
            "AI to **fill out the intake** — it reads them and proposes the "
            "question + domain + hypotheses.\n\n"
            "Either way, `tool_intake_autofill` rewrites this file and shows you "
            "the result to approve or refine. You can also mix both.\n"
        )

    # 8-rp. inputs/research_plan.md — the OVERALL project plan the AI and
    #       researcher iterate on (co-scientist style). Distinct from each
    #       step's `plan.md` (that plans one step); this frames the whole
    #       arc: question, hypotheses, the planned sequence of steps, and a
    #       living iteration log. Seeded once, then refined collaboratively.
    research_plan = root / "inputs" / "research_plan.md"
    if not research_plan.exists():
        research_plan.write_text(
            "# Research plan\n\n"
            "> **What this file is.** The living plan for the *whole* "
            "project — the AI and the researcher iterate on it together "
            "(propose → critique → refine). Each analysis step also gets its "
            "own `workspace/<NN_slug>/plan.md`; this file is the arc those "
            "steps fit into. Ask the AI to **draft the research plan** to "
            "fill it in (optionally grounded by a quick literature scan).\n\n"
            "## Research question\n"
            "*(The one question this project answers. Pull from "
            "`inputs/researcher_config.yaml` once set.)*\n\n"
            "## Hypotheses\n"
            "*(H1, H2, … — the testable claims. Register each with "
            "`mem_hypothesis_add`.)*\n\n"
            "## Planned sequence of steps\n"
            "*(The arc: step 1 → step 2 → … Each line: a goal + which "
            "hypothesis it targets. Numbering is continuous across paths.)*\n\n"
            "## Open questions / decisions\n"
            "*(Scope, design, and trade-off calls the researcher wants to "
            "weigh in on before the work proceeds.)*\n\n"
            "## Iteration log\n"
            "*(Append-only: each round of plan refinement — what changed and "
            "why — so the project's direction is itself traceable.)*\n"
        )

    # 8a. Seed each input sub-folder with a one-paragraph README so an
    #     empty folder isn't a dead end for a fresh researcher.
    _SEEDED_INPUT_READMES = {
        "raw_data": (
            "# `inputs/raw_data/`\n\n"
            "Drop datasets here — CSV, Parquet, FASTQ, NIfTI, .h5, .xlsx, "
            "VCF, JSON, whatever your project consumes. The AI reads files "
            "from here but **never modifies them**; derived data lives under "
            "`workspace/<NN_slug>/data/next_step_output/`.\n"
        ),
        "literature": (
            "# `inputs/literature/`\n\n"
            "PDFs / EPUBs of papers + theses + protocols available to EVERY "
            "step. The AI extracts citations + quotes from here when grounding "
            "methodology (`tool_research_method`) and assembling the "
            "bibliography (`tool_citations_verify`, `mem_citations_generate`). "
            "Empty? Ask the AI to **ground the project** — a quick deep-"
            "research pass (`tool_literature_search_and_save` on your research "
            "question, run across a few sub-topics) downloads the foundational "
            "papers — PDF + provenance sidecar — here. Everything here is also "
            "mirrored into the project corpus at `literature/inputs/`.\n"
        ),
        "context": (
            "# `inputs/context/`\n\n"
            "Free-form context that doesn't fit raw_data or literature: PI "
            "emails, protocols, drafts, prior reports, lab notebook excerpts, "
            "screenshots of Slack threads. The AI reads these for project "
            "framing during `tool_intake_autofill` and step planning.\n"
        ),
    }
    for sub, body in _SEEDED_INPUT_READMES.items():
        rp = root / "inputs" / sub / "README.md"
        if not rp.exists():
            rp.write_text(body)

    # 8a-lit. Project-root literature/ — the corpus of record. Every paper
    #         used ANYWHERE (inputs/literature, a step's literature/, or a
    #         step's context/) is aggregated here at step finalization, so
    #         the project has one auditable bibliography substrate.
    #
    #         ONLY for modes whose layout actually has a top-level
    #         ``literature/`` work surface (analysis, hybrid). tool_build /
    #         exploration / notebook / multi_study don't run the numbered-step
    #         finalization that mirrors PDFs here, so seeding the dir + README
    #         in those modes leaves an orphan folder describing a workflow
    #         that never runs (and one that isn't in the mode's scaffold
    #         profile — see LAYOUT_SPEC). Gate on the profile so the surface
    #         matches the declared layout.
    lit_root_readme = root / "literature" / "README.md"
    if "literature" in top_level_dirs and not lit_root_readme.exists():
        lit_root_readme.parent.mkdir(parents=True, exist_ok=True)
        lit_root_readme.write_text(
            "# `literature/` — project corpus of record\n\n"
            "The single aggregated corpus of every paper used across the "
            "project. **Auto-managed** — `tool_path_finalize` mirrors each "
            "step's PDFs (+ their `.meta.yaml` provenance sidecars) here at "
            "step completion; you don't write to it by hand.\n\n"
            "- `inputs/` — papers from `inputs/literature/` (project-wide).\n"
            "- `steps/<NN_slug>/` — papers a step pulled into its own "
            "`literature/` or `context/` folder.\n\n"
            "Each step also keeps a `literature/findings_vs_literature.md` "
            "debate (its claims vs. the sources, with citation keys that "
            "resolve here). `workspace/citations.md` is generated from this "
            "corpus + the per-step indexes.\n"
        )

    # 8b. Mode-specific governance / scratch seeds. No-op for analysis,
    #     so the classic surface is untouched.
    inner_repo_name = _seed_mode_extras(root, project_name, mode, config_overrides)

    # 9. Manifest + state.
    manifest = {
        "schema_version": "2.0",
        "project": {"title": project_name},
        "created_at": now_iso(),
        "top_level_directories": list(top_level_dirs),
        "active_path": "main",
        "paths": {"main": {"status": "active"}},
    }
    write_json(manifest_path(root), manifest)

    state = default_state()
    state["project_name"] = project_name
    state["workspace_mode"] = mode
    # Persist wizard-captured research metadata to state (it used to live in
    # researcher_config.yaml, but that's now reserved for fields a researcher
    # actively chooses). regenerate_intake reads these on subsequent calls.
    if config_overrides:
        if config_overrides.get("domain"):
            state["domain"] = config_overrides["domain"]
        if config_overrides.get("research_question"):
            state["research_question"] = config_overrides["research_question"]
        questions = config_overrides.get("research_questions") or []
        if questions:
            state["research_questions"] = [q for q in questions if isinstance(q, str) and q.strip()]
    save_state(root, state)

    # Only regenerate intake.md if there's something real to put in it:
    # files the researcher already dropped under inputs/, or explicit
    # overrides (research_question / domain) passed via the wizard or
    # `--config-overrides`. On a cold init with no signal, the short
    # pointer written above is the right surface — tool_intake_autofill
    # rewrites it once the researcher has dropped files in and asked
    # for an intake pass.
    intake_signal = _has_user_inputs(root) or any(
        (config_overrides or {}).get(k) for k in ("research_question", "domain", "keywords")
    )
    if intake_signal:
        regenerate_intake(root, project_name, config_overrides)
    _copy_agents_md(root, copy_agents)
    if not (root / "AGENTS.md").exists():
        src = Path(__file__).resolve().parent.parent.parent.parent / "templates" / "AGENTS.md"
        if src.exists():
            shutil.copy2(src, root / "AGENTS.md")
    _setup_mcp_configs(root, ide_flags)
    _setup_gitignore(root)
    _write_getting_started(root, project_name)
    _write_project_root_readme(root, project_name, state)
    _write_sharing_scripts(root, project_name)
    # Open-science scaffolding: CITATION.cff at project root so every
    # Research OS project is citable from day one. Pulls author identity
    # from the researcher_config block. codemeta.json + ro-crate-metadata
    # are NO LONGER emitted at scaffold — they shipped as root clutter with
    # placeholder "Anonymous Researcher" content nobody asked for. They are
    # generated on demand by `sys_export_ro_crate` / the share-archive
    # export, which is when a machine-readable manifest is actually needed.
    try:
        from research_os.tools.actions.state.citation import (
            emit_project_citation_cff,
        )

        researcher_block = ((config_overrides or {}).get("researcher")
                            or {})
        emit_project_citation_cff(root, project_name=project_name,
                                  researcher=researcher_block)
    except Exception:
        # Open-science manifests are best-effort; never block scaffold.
        pass
    _update_manifest(root)
    _prune_stale_gitkeeps(root, top_level_dirs=top_level_dirs, lazy_dirs=lazy_dirs)
    if git_init and not (root / ".git").exists():
        try:
            subprocess.run(["git", "init"], cwd=root, capture_output=True)
        except Exception:
            pass

    # tool_build: the actual tool lives in an INNER project dir that gets
    # its OWN git repo — Research OS (the outer workspace) governs it from
    # above. The inner repo is ALWAYS initialised (independent of the outer
    # git_init flag) so a fresh tool_build project has a working tree the
    # builder can commit into from the first turn. Hybrid's inner tool/ repo
    # gets the same treatment (H2 fix — it was unbounded to tool_build only, so
    # the hybrid build half had no real repo and surfaced no provenance).
    if mode in ("tool_build", "hybrid") and inner_repo_name:
        inner = root / inner_repo_name
        if not (inner / ".git").exists():
            try:
                inner.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "init"], cwd=inner, capture_output=True)
            except Exception:
                # Best-effort: if git is missing or init fails, the scaffold
                # is still usable — the builder can `git init` the inner repo
                # later. Don't fail the whole project creation over it.
                pass


# ---------------------------------------------------------------------------
# Sharing — zip + GitHub init scripts written at scaffold time.
# ---------------------------------------------------------------------------


# Files / directories EXCLUDED from the share-safe archive. These are
# either AI-internal (CLAUDE.md, AGENTS.md, MCP configs) or onboarding
# artefacts a downstream researcher does not need (GETTING_STARTED.md).
_SHARE_EXCLUDE_NAMES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GETTING_STARTED.md",
    # Secret-bearing: plaintext api_keys + author PII. NEVER ship it.
    "researcher_config.yaml",
    ".os_state",
    ".claude",
    ".cursor",
    ".vscode",
    ".antigravity",
    ".opencode",
    "mcp_config.json",
    ".mcp.json",
    "opencode.json",
    "__pycache__",
    ".pytest_cache",
    ".DS_Store",
    "node_modules",
    "venv",
    ".venv",
    "env",
)

# Folders that ARE included by default. Anything else at the project root
# is preserved as-is unless it matches an exclusion above.
_SHARE_INCLUDE_DIRS = (
    "inputs",
    "workspace",
    "synthesis",
    "docs",
    "environment",
)


def _write_sharing_scripts(root: Path, project_name: str) -> None:
    """Scaffold the export-to-zip + GitHub init scripts. Idempotent."""
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    export_py = scripts_dir / "export_share_archive.py"
    if not export_py.exists():
        export_py.write_text(_EXPORT_PY_TEMPLATE)
        try:
            export_py.chmod(0o755)
        except OSError:
            pass

    export_sh = scripts_dir / "export_share_archive.sh"
    if not export_sh.exists():
        export_sh.write_text(
            "#!/usr/bin/env bash\n"
            "# Build a share-safe zip of this project (no AI internals).\n"
            "# Equivalent to `python scripts/export_share_archive.py`.\n"
            "set -euo pipefail\n"
            'HERE="$(cd "$(dirname "$0")/.." && pwd)"\n'
            'python "$HERE/scripts/export_share_archive.py" "$@"\n'
        )
        try:
            export_sh.chmod(0o755)
        except OSError:
            pass

    init_gh = scripts_dir / "init_github.sh"
    if not init_gh.exists():
        slug = slugify(project_name, "research-project").replace("_", "-")
        init_gh.write_text(_INIT_GITHUB_TEMPLATE.replace("__SLUG__", slug))
        try:
            init_gh.chmod(0o755)
        except OSError:
            pass

    sharing_doc = root / "docs" / "SHARING.md"
    if not sharing_doc.exists():
        sharing_doc.write_text(_SHARING_DOC_TEMPLATE)


_EXPORT_PY_TEMPLATE = '''"""Bundle this Research OS project for a collaborator.

Builds a zip that contains a clean, share-safe view of your project —
the inputs you've collected, the analyses you've run, the synthesis
artefacts, and the docs — WITHOUT any AI configuration. The recipient
opens the zip and sees a normal research workspace; they do NOT need
Research OS installed to read it.

What is included:
  inputs/, workspace/, synthesis/, docs/, environment/, README.md (if present)
What is EXCLUDED (always):
  AGENTS.md, CLAUDE.md, GETTING_STARTED.md, CONTRIBUTORS.md,
  .os_state/, .claude/, .cursor/, .vscode/, .antigravity/, .opencode/,
  MCP configs, __pycache__/, .pytest_cache/, .DS_Store, virtualenvs,
  node_modules/.

The zip is written to <project>_share_<YYYY-MM-DD>.zip in the project
root. Use --out PATH to override.

Usage:
    python scripts/export_share_archive.py                    # default zip
    python scripts/export_share_archive.py --out /tmp/x.zip   # custom path
    python scripts/export_share_archive.py --include-raw-data # include raw data
"""
from __future__ import annotations
import argparse
import datetime as _dt
import sys
import zipfile
from pathlib import Path

EXCLUDE_NAMES = {
    "AGENTS.md", "CLAUDE.md", "GETTING_STARTED.md",
    ".os_state", ".claude", ".cursor", ".vscode",
    ".antigravity", ".opencode",
    "mcp_config.json", ".mcp.json", "opencode.json",
    # Secret-bearing: holds plaintext api_keys + author PII. NEVER ship it.
    "researcher_config.yaml",
    "__pycache__", ".pytest_cache", ".DS_Store",
    "node_modules", "venv", ".venv", "env",
}

INCLUDE_DIRS = ("inputs", "workspace", "synthesis", "docs", "environment")


def _excluded(path: Path) -> bool:
    parts = path.parts
    for part in parts:
        if part in EXCLUDE_NAMES:
            return True
        if part.startswith(".") and part not in {".gitignore", ".gitkeep"}:
            return True
    return False


def _read(p: Path, limit: int = 4000) -> str:
    try:
        return p.read_text(errors="replace")[:limit]
    except Exception:
        return ""


def _project_title(root: Path) -> str:
    """Researcher-chosen project_name, falling back to the folder name.

    Reads ``inputs/researcher_config.yaml`` with a minimal line parser so the
    exported script stays dependency-free (no PyYAML on the recipient side,
    and the source side may not have it either). Looks for a top-level
    ``project_name:`` key. Returns ``root.name`` when absent/unreadable.
    """
    cfg = root / "inputs" / "researcher_config.yaml"
    try:
        for raw in cfg.read_text(errors="replace").splitlines():
            # Top-level key only (no leading whitespace) so a nested
            # `project_name:` under some other block can't hijack the title.
            if raw[:1].isspace():
                continue
            if raw.lstrip().lower().startswith("project_name:"):
                val = raw.split(":", 1)[1].strip().strip("\\"'")
                if val:
                    return val
    except OSError:
        pass
    return root.name


def _build_recipient_readme(root: Path) -> str:
    """A human front-door for whoever OPENS the shared archive.

    A collaborator / PI / reviewer who unzips this has none of the AI-facing
    files (they're excluded) and shouldn't have to spelunk numbered folders to
    learn what the project is, what was done, and whether they can trust it.
    This stitches the human-readable status + structure into one overview.
    """
    import datetime as _dt

    # Prefer the researcher-chosen project_name over the on-disk folder name.
    # The directory is often a terse slug ("myproj"); researcher_config.yaml
    # carries the real title ("Quantum Coherence In Photosynthesis"). That
    # config is EXCLUDED from the archive, but it is readable at export time
    # on the source root, and the RO-Crate / CodeMeta manifests already use
    # it — so the human front-door must agree with the machine metadata, or a
    # reviewer sees two different project names and distrusts the bundle.
    name = _project_title(root)
    lines = [
        f"# {name} — shared research archive",
        "",
        f"*Self-contained snapshot, exported {_dt.date.today().isoformat()}. "
        "You do NOT need Research-OS installed to read it — everything below "
        "is plain files.*",
        "",
    ]

    # What this project is — pull from research_overview / STATE / intake.
    # Prefer a candidate that actually names the research question; fall back
    # to the first non-trivial one. (Threshold is low: a 3-line overview with
    # the question + domain is perfectly good and may be < 80 chars.)
    overview = ""
    for cand in ("docs/research_overview.md", "STATE.md", "inputs/intake.md"):
        txt = _read(root / cand)
        if not txt or len(txt.strip()) < 30:
            continue
        if "research question" in txt.lower() and "not yet set" not in txt.lower():
            overview = txt
            break
        if not overview:
            overview = txt
    lines.append("## What this is")
    lines.append("")
    if overview:
        # Lift the question + domain + hypothesis content. Markdown often puts
        # the heading on one line and the value on the next, so when a line is
        # just a heading, pull the following non-empty line as its value.
        olines = overview.splitlines()
        picked: list[str] = []
        for i, ln in enumerate(olines):
            low = ln.lower()
            if any(k in low for k in
                   ("research question", "domain", "hypoth")):
                stripped = ln.strip()
                is_heading_only = (
                    stripped.startswith("#")
                    or stripped.rstrip(":*").lower() in (
                        "research question", "domain", "hypotheses",
                    )
                )
                if is_heading_only:
                    label = stripped.lstrip("#").strip().rstrip(":*").strip()
                    for nxt in olines[i + 1:i + 4]:
                        if nxt.strip():
                            picked.append(f"- **{label.title()}:** "
                                          f"{nxt.strip().strip('*_')}")
                            break
                else:
                    picked.append(stripped if stripped.startswith("-")
                                  else f"- {stripped}")
            if len(picked) >= 5:
                break
        seen = set()
        picked = [p for p in picked if not (p in seen or seen.add(p))]
        if picked:
            lines.extend(picked)
        else:
            lines.append(overview.strip()[:600])
    else:
        lines.append("_(No overview was recorded. See `docs/` and the numbered "
                     "`workspace/` folders for the work itself.)_")
    lines.append("")

    # What was done — the numbered analysis steps + their conclusions.
    ws = root / "workspace"
    steps = []
    if ws.is_dir():
        for d in sorted(ws.iterdir()):
            if (d.is_dir() and d.name[:2].isdigit()
                    and not d.name.endswith("__DEAD_END")):
                concl = d / "conclusions.md"
                summary = ""
                if concl.exists():
                    body = _read(concl, 400).strip()
                    first = next((ln.strip("# ").strip()
                                  for ln in body.splitlines() if ln.strip()), "")
                    summary = first
                steps.append((d.name, summary))
    if steps:
        lines.append("## What was done")
        lines.append("")
        for sname, ssum in steps:
            lines.append(f"- **{sname}**" + (f" — {ssum}" if ssum else ""))
        lines.append("")

    # Deliverables — what's in synthesis/.
    syn = root / "synthesis"
    deliverables = []
    if syn.is_dir():
        for p in sorted(syn.rglob("*")):
            if p.is_file() and p.suffix.lower() in {
                ".pdf", ".html", ".typ", ".docx", ".pptx", ".md"
            }:
                deliverables.append(p.relative_to(syn).as_posix())
    if deliverables:
        lines.append("## Deliverables (`synthesis/`)")
        lines.append("")
        for d in deliverables[:20]:
            lines.append(f"- `synthesis/{d}`")
        lines.append("")

    # Trust + reproduce.
    lines.extend([
        "## How to read & trust this",
        "",
        "- `workspace/<NN_slug>/` — each numbered folder is one analysis step: "
        "the script(s) that ran, the data they produced, and a `conclusions.md`.",
        "- `workspace/methods.md`, `analysis.md`, `citations.md` — the project's "
        "narrative logs (what was done, in order; the bibliography).",
        "- `environment/requirements.txt` — the exact package versions, so the "
        "analyses can be re-run.",
        "- `CITATION.cff` + `ro-crate-metadata.json` — machine-readable "
        "provenance + citation metadata (open standards; optional to read).",
        "- Every quantitative claim in the write-up is meant to trace to an "
        "artefact in `workspace/`. To reproduce: install the pinned "
        "environment, then re-run the scripts in step order.",
        "",
        "_Generated by Research-OS at export time. Edit freely._",
        "",
    ])
    return "\\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None,
                    help="Output zip path. Default: <project>_share_<date>.zip")
    ap.add_argument("--include-raw-data", action="store_true",
                    help="Include inputs/raw_data/ (default: skipped to keep "
                    "the archive small and avoid PII leaks).")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    today = _dt.date.today().isoformat()
    out = args.out or (root / f"{root.name}_share_{today}.zip")
    out = out.resolve()

    # Refresh open-science manifests just before zipping so the
    # archive carries the latest RO-Crate 1.1 + CodeMeta 2.0 view.
    try:
        from research_os.tools.actions.state.ro_crate import (
            build_codemeta as _build_codemeta,
            build_ro_crate as _build_ro_crate,
        )
        _build_ro_crate(root)
        _build_codemeta(root)
    except Exception as _e:
        print(f"[warn] could not refresh RO-Crate / CodeMeta: {_e}")

    files_added = 0
    bytes_added = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # A human front-door for the recipient: what this is, what was done,
        # what's here, how to trust + reproduce it. The AI-facing orientation
        # files (GETTING_STARTED, AGENTS) are excluded from the archive, so
        # without this a collaborator opens raw folders with no guide.
        #
        # We write the SAME share-safe front-door to both README_SHARED.md
        # (the documented name) AND README.md. We deliberately do NOT ship the
        # project's own root README.md: that file is the GitHub/repo-browser
        # page and it points the reader at STATE.md, AGENTS.md, and
        # GETTING_STARTED.md — all of which are EXCLUDED from this archive. A
        # recipient who opened it would be sent to three files that aren't in
        # the bundle. Overwriting README.md with the recipient front-door keeps
        # the repo-browser landing page honest (every link it makes resolves).
        recipient_readme = None
        try:
            recipient_readme = _build_recipient_readme(root)
            zf.writestr(f"{root.name}/README_SHARED.md", recipient_readme)
            files_added += 1
            zf.writestr(f"{root.name}/README.md", recipient_readme)
            files_added += 1
        except Exception as _e:
            print(f"[warn] could not generate recipient README: {_e}")
        # Top-level files we DO want shipped to collaborators. The
        # open-science manifests (RO-Crate + CodeMeta + CITATION.cff)
        # MUST live at archive root so ro-crate-py + cffconvert can
        # auto-discover them. README.md is intentionally NOT in this list —
        # it is replaced by the share-safe recipient front-door above. If the
        # recipient README failed to generate, fall back to the project's own
        # README.md so the archive isn't left without a landing page.
        top_files = ["CONTRIBUTORS.md", "CITATION.cff",
                     "ro-crate-metadata.json", "codemeta.json"]
        if recipient_readme is None:
            top_files.insert(0, "README.md")
        for top in top_files:
            tp = root / top
            if tp.exists():
                zf.write(tp, arcname=f"{root.name}/{top}")
                files_added += 1
                bytes_added += tp.stat().st_size
        for sub in INCLUDE_DIRS:
            base = root / sub
            if not base.exists():
                continue
            for p in base.rglob("*"):
                if not p.is_file():
                    continue
                if not args.include_raw_data and "raw_data" in p.relative_to(root).parts:
                    continue
                rel = p.relative_to(root)
                if _excluded(rel):
                    continue
                arc = f"{root.name}/{rel.as_posix()}"
                zf.write(p, arcname=arc)
                files_added += 1
                bytes_added += p.stat().st_size

    print(f"[done] {out}")
    print(f"       {files_added} files, {bytes_added / 1024:.1f} KB compressed "
          f"({out.stat().st_size / 1024:.1f} KB on disk)")
    if not args.include_raw_data:
        print("       NOTE: inputs/raw_data/ skipped. Pass --include-raw-data to bundle it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


_INIT_GITHUB_TEMPLATE = """#!/usr/bin/env bash
# Initialise a GitHub repo from this project — share-safe by default.
#
# Excludes AI-internal files (AGENTS.md, CLAUDE.md, .os_state/, .claude/,
# MCP configs, GETTING_STARTED.md) and large raw data via .gitignore.
#
# Requires: gh CLI installed and authenticated (`gh auth login`).
#
# Usage:
#   ./scripts/init_github.sh                    # default name from project slug
#   ./scripts/init_github.sh my-repo-name       # custom repo name
#   ./scripts/init_github.sh my-repo --public   # public repo (default private)
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

REPO_NAME="${1:-__SLUG__}"
VISIBILITY="--private"
for arg in "$@"; do
  [[ "$arg" == "--public" ]] && VISIBILITY="--public"
  [[ "$arg" == "--internal" ]] && VISIBILITY="--internal"
done

# 1. Make sure git is initialised.
if [ ! -d ".git" ]; then
  git init -b main
fi

# 2. Make sure the share-safe .gitignore additions are present.
GI=".gitignore"
touch "$GI"
add_ignore() {
  grep -qxF "$1" "$GI" 2>/dev/null || echo "$1" >> "$GI"
}
add_ignore "AGENTS.md"
add_ignore "CLAUDE.md"
add_ignore "GETTING_STARTED.md"
add_ignore ".os_state/"
add_ignore ".claude/"
add_ignore ".cursor/"
add_ignore ".vscode/"
add_ignore ".antigravity/"
add_ignore ".opencode/"
add_ignore "mcp_config.json"
add_ignore ".mcp.json"
add_ignore "opencode.json"
add_ignore "inputs/raw_data/"
add_ignore "__pycache__/"
add_ignore "*.pyc"
add_ignore ".DS_Store"

# 3. Stage + commit (idempotent — skips if nothing changed).
git add .
if ! git diff --staged --quiet; then
  git commit -m "Initial commit: Research OS project (share-safe)"
fi

# 4. Create the remote + push.
if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI not installed. Skipping remote creation."
  echo "Install: https://cli.github.com/  then re-run."
  exit 0
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "gh CLI not authenticated. Run: gh auth login"
  exit 1
fi

if ! gh repo view "$REPO_NAME" >/dev/null 2>&1; then
  gh repo create "$REPO_NAME" $VISIBILITY --source=. --remote=origin --push
else
  echo "Repo $REPO_NAME already exists. Pushing current branch."
  git push -u origin main
fi

echo "[done] Repo URL:"
gh repo view --json url -q .url
"""


_SHARING_DOC_TEMPLATE = """# Sharing this project

**What this is for.** Two safe ways to send this project to a
collaborator (or your PI / advisor / Argonne team) without leaking
AI-internal config or large raw data. Both excludes `.os_state/`,
the IDE MCP configs, `AGENTS.md`, and `CLAUDE.md` by default — what
your collaborator opens looks like a finished research workspace,
not an in-progress AI session.

Pick the one that matches how you collaborate:

* **Option 1** — bundle a zip you can email or upload anywhere.
  No git knowledge required.
* **Option 2** — push to a private GitHub repo so your team can
  pull, contribute, and see the project's `CONTRIBUTORS.md` history.

---

## Option 1 — Zip archive

```sh
python scripts/export_share_archive.py
# → <project>_share_<YYYY-MM-DD>.zip in the project root
```

What's included: `inputs/` (minus raw data unless you pass
`--include-raw-data`), `workspace/`, `synthesis/`, `docs/`, `environment/`,
and a top-level `README.md` if present.

What's excluded (always): `AGENTS.md`, `CLAUDE.md`, `GETTING_STARTED.md`,
`.os_state/`, `.claude/`, `.cursor/`, `.vscode/`, `.antigravity/`,
`.opencode/`, MCP configs, `__pycache__/`, virtualenvs, `node_modules/`.

Pass `--out PATH` to override the destination, e.g.

```sh
python scripts/export_share_archive.py --out /tmp/myproj.zip
```

## Option 2 — GitHub repo

```sh
./scripts/init_github.sh                  # private repo named after the project
./scripts/init_github.sh my-repo-name     # custom repo name
./scripts/init_github.sh my-repo --public # public repo
```

This script:

1. Initialises `git` if needed.
2. Appends the share-safe exclusions to `.gitignore` (idempotent).
3. Commits if there are any new changes.
4. Creates the GitHub repo via the `gh` CLI and pushes the first commit.

Requires the [GitHub CLI](https://cli.github.com/) authenticated
(`gh auth login`). If `gh` is not installed, the local commit still
happens — push manually afterward.

## What collaborators get

A clean research workspace they can read without any Research-OS context:

* `synthesis/dashboard.html` — the polished single-file dashboard
  (open in any browser; self-contained).
* `synthesis/figures/` — every curated figure with its caption sidecar.
* `synthesis/paper.typ` (→ `paper.pdf`) / `synthesis/REPORT.md` — the narrative deliverable.
* `workspace/NN_*/conclusions.md` — the per-step reasoning chain.
* `workspace/NN_*/scripts/` — the actual analysis code (reproducible).
* `workspace/NN_*/data/next_step_output/` — derived artefacts each step persisted.
* `docs/` — research question, glossary, workflow diagram.

The AI-side configuration is intentionally excluded, so the share
reads as a finished research project, not an in-progress AI workspace.
"""



def _prune_stale_gitkeeps(
    root: Path,
    top_level_dirs: tuple[str, ...] = TOP_LEVEL_DIRS,
    lazy_dirs: tuple[str, ...] = LAZY_DIRS,
) -> None:
    """Remove .gitkeep from any project directory that now has real content.

    With the eager/lazy split we no longer create .gitkeep on a cold
    scaffold. This helper still runs for safety: pre-1.0 projects (or
    user-created dirs) may carry .gitkeep files alongside real artefacts,
    and we want them gone so casual ``ls`` and dashboard counters stay
    honest. The pass also removes .gitkeep from any empty LAZY_DIR a
    legacy code path may have created — those dirs should not exist at
    all unless populated.

    ``top_level_dirs`` / ``lazy_dirs`` default to the analysis-mode
    constants so existing callers are unaffected; the scaffold passes the
    active profile's contract for non-analysis modes.
    """
    for rel in top_level_dirs:
        d = root / rel
        if not d.is_dir():
            continue
        keep = d / ".gitkeep"
        if not keep.exists():
            continue
        siblings = [p for p in d.iterdir() if p.name != ".gitkeep"]
        if siblings:
            try:
                keep.unlink()
            except OSError:
                pass
            continue
        # Empty + .gitkeep'd lazy dir → drop both the marker and the dir.
        if rel in lazy_dirs:
            try:
                keep.unlink()
                d.rmdir()
            except OSError:
                pass


def _write_project_root_readme(
    root: Path,
    project_name: str,
    state: dict,
    *,
    force: bool = False,
) -> None:
    """Drop a project-root README.md — the GitHub / repo-browser front page.

    Distinct from GETTING_STARTED.md (which targets the *researcher driving
    this Research OS workspace*); README.md targets anyone who lands on the
    folder cold — a collaborator, a PI, a reviewer cloning from GitHub.
    Researcher-facing AND tooling-neutral: never mentions MCP tool names.

    By default skips when the README already exists (the wizard runs
    once and shouldn't clobber user edits). Pass ``force=True`` to
    regenerate — used by ``regenerate_root_readme`` at project finalize
    to refresh the front page with the current step inventory + a
    headline finding pointer.
    """
    dest = root / "README.md"
    if dest.exists() and not force:
        return
    domain = (state.get("domain") or "").strip()
    question = (state.get("research_question") or "").strip()
    domain_line = f"**Domain:** {domain}\n\n" if domain else ""
    q_line = f"**Research question:** {question}\n\n" if question else ""
    dest.write_text(
        f"""# {project_name}

{q_line}{domain_line}> A research project scaffolded with [Research OS](https://github.com/VibhavSetlur/Research-OS) — a structured AI-collaboration workspace for grounded, reproducible research.

## What's in this folder

| Folder | Purpose |
|---|---|
| `inputs/raw_data/` | Datasets you (or collaborators) provide. Immutable; the AI reads but never writes here. |
| `inputs/literature/` | PDFs / EPUBs of papers, theses, protocols the project draws on. |
| `inputs/context/` | Free-form context: PI emails, lab-notebook entries, prior reports. |
| `workspace/NN_slug/` | Numbered analysis steps. Each has its own scripts, data, outputs, conclusions. |
| `workspace/methods.md` · `analysis.md` · `citations.md` | Append-only project-wide logs (the narrative). |
| `synthesis/` | Final deliverables — paper, poster, dashboard, slides — generated on request. |
| `environment/` | Reproducibility surface — `requirements.txt`, conda exports, optional Dockerfile. |
| `STATE.md` | Canonical project status. A fresh session reads this first to know where things stand. |

## How to read the project

1. Open `STATE.md` for the snapshot: research question, active hypotheses, what's been done.
2. `workspace/analysis.md` gives the chronological narrative.
3. Each `workspace/NN_*/conclusions.md` has the full statistics + decisions for that step.
4. Final outputs (when generated) live in `synthesis/`.

## Reproducing the analysis

```bash
# 1. Install Python + the project's package list
pip install -r environment/requirements.txt

# 2. Run any analysis step end-to-end
cd workspace/01_<slug>
python scripts/01_<slug>_v1.py
```

Each step's `data/past_step_input/` is symlinked from the project's `inputs/raw_data/`
or from the previous step's `data/next_step_output/`. Outputs land under
`workspace/<step>/outputs/{{figures,tables,reports}}`.

## Working on this project with an AI

* Researcher onboarding: `GETTING_STARTED.md`
* AI operating rules: `AGENTS.md`

## License

_(set by you in this README — the scaffold leaves it blank by default.)_
"""
    )

    # When force-regenerating (e.g. at project finalize) append a
    # "Project status" section reflecting the current step inventory,
    # synthesis artefacts on disk, and a pointer to STATE.md for
    # anything deeper. Skipped on first-write so the front page stays
    # clean while a project is fresh.
    if force:
        _append_project_status_section(root, dest, state)


def _append_project_status_section(root: Path, dest: Path, state: dict) -> None:
    """Append a current-as-of-finalize "Project status" section.

    Reads what actually exists on disk (numbered step folders,
    synthesis deliverables) rather than trusting any single index file,
    so the section reflects ground truth even if STATE.md is stale.
    """
    lines: list[str] = ["", "---", "", "## Project status",
                        f"*Snapshot at {now_iso()}.*", ""]

    # Step inventory
    workspace = root / "workspace"
    step_dirs: list[Path] = []
    if workspace.exists():
        step_dirs = sorted(
            p for p in workspace.iterdir()
            if p.is_dir()
            and not p.name.startswith((".", "_"))
            and re.match(r"^\d{2,3}_", p.name)
        )
    if step_dirs:
        lines.append(f"**{len(step_dirs)} analysis step(s) recorded:**")
        lines.append("")
        for sd in step_dirs:
            readme = sd / "README.md"
            headline = ""
            if readme.exists():
                try:
                    text = readme.read_text()
                    # First non-empty non-heading line is usually a one-line summary.
                    for ln in text.splitlines()[1:30]:
                        s = ln.strip()
                        if s and not s.startswith("#"):
                            headline = s[:160]
                            break
                except OSError:
                    pass
            lines.append(
                f"- `workspace/{sd.name}/` — "
                f"{headline}" if headline else f"- `workspace/{sd.name}/`"
            )
        lines.append("")

    # Synthesis deliverables actually on disk
    synth = root / "synthesis"
    deliverables: list[str] = []
    if synth.exists():
        for name in ("paper.typ", "paper.pdf", "slides.typ", "slides.pdf",
                     "poster.typ", "poster.pdf", "dashboard.html"):
            if (synth / name).exists():
                deliverables.append(name)
    if deliverables:
        lines.append("**Synthesis deliverables:** "
                     + ", ".join(f"`synthesis/{d}`" for d in deliverables))
        lines.append("")

    # Pointer to STATE.md (live status doc)
    if (root / "STATE.md").exists():
        lines.append("See `STATE.md` for the live operational snapshot "
                     "(active hypotheses, dead ends, next protocol).")
        lines.append("")

    try:
        with open(dest, "a") as f:
            f.write("\n".join(lines))
    except OSError:
        pass  # README append is best-effort; failures must not crash finalize


def regenerate_root_readme(root: Path) -> dict[str, Any]:
    """Rewrite the project-root README.md from current on-disk state.

    Use at project finalize to refresh the GitHub front page with the
    actual step inventory + synthesis deliverables. Idempotent.
    Returns ``{"status", "path", "step_count", "deliverables"}``.
    """
    try:
        state = load_state(root)
    except Exception:
        state = {}
    project_name = state.get("project_name") or root.name or "Research Project"
    _write_project_root_readme(root, project_name, state, force=True)
    dest = root / "README.md"

    # Re-derive the counts so the caller can log what was written.
    workspace = root / "workspace"
    step_count = 0
    if workspace.exists():
        step_count = sum(
            1 for p in workspace.iterdir()
            if p.is_dir()
            and not p.name.startswith((".", "_"))
            and re.match(r"^\d{2,3}_", p.name)
        )
    deliverables: list[str] = []
    synth = root / "synthesis"
    if synth.exists():
        for name in ("paper.typ", "paper.pdf", "slides.typ", "slides.pdf",
                     "poster.typ", "poster.pdf", "dashboard.html"):
            if (synth / name).exists():
                deliverables.append(name)

    return {
        "status": "success",
        "path": str(dest.relative_to(root)) if dest.exists() else "README.md",
        "step_count": step_count,
        "deliverables": deliverables,
    }


def _write_getting_started(root: Path, project_name: str) -> None:
    """Drop a friendly GETTING_STARTED.md the researcher reads first."""
    dest = root / "GETTING_STARTED.md"
    if dest.exists():
        return
    dest.write_text(
        f"""# Getting started with **{project_name}**

This is a Research OS workspace. Two files matter most to you:

* `AGENTS.md` — what the AI is told to do (you almost never edit this).
* `inputs/researcher_config.yaml` — how the AI should behave for **you**.
  Every field is optional; defaults work.

## 1. Open your AI IDE on this folder

The MCP config was already dropped for whichever IDE you use:
Claude Code, OpenCode, Antigravity, Cursor, Claude Desktop, VS Code,
Windsurf, Continue, Aider. Restart your IDE if it doesn't auto-detect.

The MCP server should show as connected. If it doesn't, run
`research-os start` in a terminal at the project root.

## 2. Just tell the AI what you're studying

The fastest way to start — no files required. In chat, say something like:

```
I want to know if sleep duration affects test scores. My data's a CSV
at ~/data/students.csv. Hypotheses: more sleep → higher scores, and the
effect is stronger for younger students.
```

The AI captures your question, domain, and hypotheses into the project and
shows you what it understood to approve or refine. You never have to edit a
file to get going.

**Prefer to drop files?** That works too — put them here, then say
"fill out the intake":

| Where | What goes here |
|---|---|
| `inputs/raw_data/`  | Data files (CSV, Parquet, FASTQ, NIfTI, JSON, Excel, ...) |
| `inputs/literature/`| PDFs of papers you want the AI to know about |
| `inputs/context/`   | Notes, drafts, prior reports — anything text |

`inputs/raw_data/` + `inputs/literature/` are source-of-truth (soft-guarded);
the AI maintains the rest of `inputs/` for you. Only `.os_state/` is hard-locked.
Derived data lives under `workspace/`.

## 3. Then just chat. Try any of:

```
describe my project              (tell it your question + data — it sets everything up)
what should I do next?            (iterative planning — AI assesses + searches + proposes)
run a baseline EDA                (creates workspace/01_baseline_eda/ with figures + report)
fit a logistic regression         (methodology selection → analysis_plan)
find papers about <topic>         (literature search across S2 + Crossref + PubMed + arXiv)
write the methods section
write the paper for a journal     (verified citations only — no hallucinations)
make me an executive dashboard
draft an NIH R01 narrative
check reproducibility
fix my workspace                  (heals missing dirs / corrupted state, never deletes)
wrap up the session
```

The AI loads the right protocol and walks through it. Interrupt anytime;
"keep going" or "switch to autopilot" both work.

## 4. Where outputs end up

| Folder | What's inside |
|---|---|
| `workspace/01_<slug>/`, `02_<slug>/`, ... | Numbered experiment folders. Scripts + data + outputs + per-step conclusions. |
| `workspace/methods.md`, `analysis.md`, `citations.md` | Append-only logs (the project's narrative). |
| `workspace/scratch/`  | AI sandbox for quick tests (gitignored). |
| `synthesis/`          | Final outputs — paper.typ (→ paper.pdf), poster.typ, slides.typ, dashboard.html (only created when you ask). |

## 5. Controls

In `inputs/researcher_config.yaml`:

* `interaction.autonomy_level: manual | supervised | autopilot | coaching`
* `model_profile: small | medium | large` (affects how the AI batches work)
* `runtime.shared_server: true` if you're on HPC / a shared box

You can change these mid-session by telling the AI ("switch to autopilot").

## 6. When things go wrong

| Problem | Say to the AI... |
|---|---|
| Something seems broken | "Fix my workspace." |
| Lost work | "Show me checkpoints and roll back to the last good one." |
| Conversation too long | "Hand off the session." |
| AI making bad calls | "Switch to manual mode and walk me through each step." |

## 7. Working with collaborators

* `CONTRIBUTORS.md` — opt-in activity log. Created on the first
  `research-os ide add` / `ide remove` / explicit share action so a
  fresh collaborator can see who changed wiring. Fresh projects do not
  ship one until something changes.
* `research-os ide add <name>` — wire a new AI IDE for *you* without
  re-scaffolding the workspace (so nothing your teammate did breaks).
* `research-os ide list` — see which IDE configs are wired.
* `scripts/export_share_archive.py` — bundle this project as a safe
  zip (no AI internals) to email or upload. See `docs/SHARING.md`.
* `scripts/init_github.sh` — push to a private GitHub repo with the
  share-safe `.gitignore` already configured.

## More

`docs/SHARING.md` is bundled in this project. The rest live online in the
Research-OS repository:

* First steps: <https://github.com/VibhavSetlur/Research-OS/blob/main/docs/START.md> (install + first project + cheatsheet)
* Sharing: `docs/SHARING.md` (zip + GitHub paths) — bundled here
* Full guide: <https://github.com/VibhavSetlur/Research-OS/blob/main/docs/RESEARCHER_GUIDE.md>
* Pick a protocol: <https://github.com/VibhavSetlur/Research-OS/blob/main/docs/USE_CASES.md> (role × goal × output)
* All tools: <https://github.com/VibhavSetlur/Research-OS/blob/main/docs/TOOLS.md>
* All protocols: <https://github.com/VibhavSetlur/Research-OS/blob/main/docs/PROTOCOLS.md>
* FAQ: <https://github.com/VibhavSetlur/Research-OS/blob/main/docs/FAQ.md>
"""
    )


def _copy_agents_md(root: Path, copy: bool) -> None:
    if not copy:
        return
    dest = root / "AGENTS.md"
    if dest.exists():
        return
    src = Path(__file__).resolve().parent.parent.parent.parent / "templates" / "AGENTS.md"
    if src.exists():
        shutil.copy2(src, dest)


def _setup_gitignore(root: Path) -> None:
    gi = root / ".gitignore"
    if gi.exists():
        return
    gi.write_text(
        "# Research OS\n"
        "__pycache__/\n*.pyc\n*.pyo\n*.egg-info/\n"
        ".venv/\nvenv/\nenv/\n"
        ".DS_Store\n\n"
        "# Machine-local state, provenance + run logs — never commit these.\n"
        "# .os_state/ is per-machine run history/state; logs/ is per-run audit\n"
        "# + override logs; scratch/ is throwaway sandboxing. All are noise in a\n"
        "# shared repo. The patterns are UNANCHORED (no leading slash) so they\n"
        "# also catch the per-step copies under workspace/<NN_step>/{scratch,logs}/\n"
        "# AND the synthesis draft area synthesis/scratch/ where dashboards /\n"
        "# slide decks are iterated before they land in their final synthesis home\n"
        "# (synthesis/<kind> or synthesis/meetings/<date>/, which ARE committed).\n"
        ".os_state/\n"
        "scratch/\n"
        "logs/\n\n"
        "# Secrets / machine-specific\n"
        "inputs/researcher_config.yaml\n"
        "inputs/literature_index.yaml\n"
        "inputs/raw_data/\n"
    )


def mcp_server_entry() -> dict[str, Any]:
    """The ONE canonical MCP server entry every writer uses.

    Portable: `command: research-os` (resolved from PATH) + the
    `${workspaceFolder}` env hint so the SAME global install serves every
    project. Having a single builder is what keeps the per-IDE files from
    drifting into the abs-path / `${workspaceFolder}` mix that shipped in
    the reaction-similarity project.
    """
    return {
        "command": "research-os",
        "args": ["start"],
        "env": {"RESEARCH_OS_WORKSPACE": "${workspaceFolder}"},
    }


def mcp_restart_notice() -> str:
    """The notice EVERY MCP-setup path must surface: the IDE/session has to
    reload before the freshly-wired server is visible."""
    return (
        "⚠ RESTART REQUIRED: the MCP server was just wired up. If your IDE / "
        "AI session is already open, fully RESTART it (or reload the window) "
        "so the `research-os` tools load. They will NOT appear in the current "
        "session."
    )


def mcp_global_install_hint(ide_flags: list[str]) -> str:
    """Copy-paste commands to register research-os GLOBALLY (user scope) so
    it's available in every project — for `--mcp-scope global`."""
    lines = [
        "To make research-os available in EVERY project (global / user scope), "
        "register it once with your IDE instead of per-project:",
    ]
    if "claude" in ide_flags or "claude_code" in ide_flags:
        lines.append("  • Claude Code:  claude mcp add --scope user research-os -- research-os start")
    if "cursor" in ide_flags:
        lines.append("  • Cursor:       add the research-os entry to ~/.cursor/mcp.json")
    if "vscode" in ide_flags:
        lines.append("  • VS Code:      add it to your user settings.json mcp.servers")
    lines.append(
        "  (The per-project files were still written, so the workspace works "
        "either way.)"
    )
    return "\n".join(lines)


def _setup_mcp_configs(
    root: Path, ide_flags: list[str], *, mcp_scope: str = "workspace",
) -> None:
    """Drop a per-IDE MCP config + rule file so the AI auto-connects.

    The MCP config uses `${workspaceFolder}` so the SAME `research-os`
    binary serves every project the IDE has open — install once,
    scaffold each project with `research-os init`, no rebuild of the
    global install. Editors that don't expand `${workspaceFolder}`
    still work: the server reads `RESEARCH_OS_WORKSPACE` first and
    falls back to walking up from the current working directory for
    `.os_state/` (which the IDE typically launches the server in).

    ``mcp_scope`` is informational here — the per-project files are always
    written (they're harmless and make the workspace self-contained). The
    CLI/wizard surfaces ``mcp_global_install_hint`` when scope='global'.
    """
    mcp_entry = mcp_server_entry()
    templates_dir = Path(__file__).resolve().parent.parent.parent / "templates"

    def _copy_rule(src_rel: str, dest: Path) -> None:
        src = templates_dir / src_rel
        if src.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(src, dest)

    if "cursor" in ide_flags:
        d = root / ".cursor"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "mcp.json"
        if not f.exists():
            f.write_text(json.dumps({"mcpServers": {"research-os": mcp_entry}}, indent=2) + "\n")
        _copy_rule(".cursor/rules/research-os.mdc", d / "rules" / "research-os.mdc")

    if "claude" in ide_flags:
        d = root / ".claude"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "mcp.json"
        if not f.exists():
            f.write_text(json.dumps({"mcpServers": {"research-os": mcp_entry}}, indent=2) + "\n")
        # Claude Code reads project-scoped MCP servers from ROOT `.mcp.json`
        # (NOT .claude/mcp.json). Writing the same canonical entry there too
        # means Claude Code picks up RO's portable config instead of the
        # researcher running `claude mcp add` (which bakes in absolute paths)
        # — the abs-path-vs-portable drift seen in the wild.
        root_mcp = root / ".mcp.json"
        if not root_mcp.exists():
            root_mcp.write_text(
                json.dumps({"mcpServers": {"research-os": mcp_entry}}, indent=2) + "\n"
            )
        _copy_rule(".claude/rules/research-os.md", d / "rules" / "research-os.md")
        _copy_rule(".claude/commands/start-session.md", d / "commands" / "start-session.md")

    if "antigravity" in ide_flags:
        d = root / ".antigravity"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "mcp.json"
        if not f.exists():
            f.write_text(json.dumps({"mcpServers": {"research-os": mcp_entry}}, indent=2) + "\n")
        _copy_rule(".antigravity/rules/research-os.md", d / "rules" / "research-os.md")

    if "opencode" in ide_flags:
        f = root / "opencode.json"
        if not f.exists():
            f.write_text(
                json.dumps(
                    {
                        "mcp": {"research-os": mcp_entry},
                        "system_prompt": "Read AGENTS.md at the project root before any research request.",
                    },
                    indent=2,
                )
                + "\n"
            )

    if "vscode" in ide_flags:
        d = root / ".vscode"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "mcp.json"
        if not f.exists():
            f.write_text(json.dumps({"mcpServers": {"research-os": mcp_entry}}, indent=2) + "\n")

    if "windsurf" in ide_flags:
        # Project-level rules file Windsurf reads automatically.
        _copy_rule(".windsurfrules", root / ".windsurfrules")

    if "continue" in ide_flags:
        _copy_rule(".continuerules", root / ".continuerules")

    if "aider" in ide_flags:
        _copy_rule(".aider.conf.yml", root / ".aider.conf.yml")

    if "claude_code" in ide_flags or "claude" in ide_flags:
        # Claude Code reads CLAUDE.md at the project root.
        _copy_rule("CLAUDE.md", root / "CLAUDE.md")


# ---------------------------------------------------------------------------
# Intake + literature index
# ---------------------------------------------------------------------------


def regenerate_intake(
    root: Path, project_name: str | None = None, config_overrides: dict | None = None
) -> str:
    """Rewrite ``inputs/intake.md`` with current file hashes + config."""
    config_overrides = config_overrides or {}
    try:
        state = load_state(root) or {}
    except Exception:
        state = {}
    project_name = project_name or state.get("project_name") or "Research Project"

    # Domain / research_question used to live in researcher_config.yaml; they
    # now live in .os_state/state.json (written by tool_intake_autofill).
    # Overrides win; state is the fallback; finally a placeholder.
    domain = (
        config_overrides.get("domain")
        or state.get("domain")
        or ""
    )
    research_question = (
        config_overrides.get("research_question")
        or state.get("research_question")
        or ""
    )
    # The wizard / CLI can collect several questions (--questions repeatable);
    # render all of them so questions 2..N aren't silently dropped. Keep the
    # singular one-line form when there's 0 or 1 so existing output is identical.
    research_questions = [
        q for q in (
            config_overrides.get("research_questions")
            or state.get("research_questions")
            or []
        )
        if isinstance(q, str) and q.strip()
    ]
    if len(research_questions) > 1:
        question_lines = ["- Research question(s):"] + [
            f"  - {q}" for q in research_questions
        ]
    else:
        question_lines = [
            f"- Research question: {research_question or '(to be confirmed in project_startup)'}"
        ]
    keywords: list[str] = list(config_overrides.get("keywords", []) or [])
    if not keywords:
        keywords = [
            h.get("statement", "")
            for h in (state.get("active_hypotheses") or [])
            if isinstance(h, dict) and h.get("statement")
        ][:5]

    input_files: list[dict[str, Any]] = []
    for subdir in ("raw_data", "literature", "context"):
        d = root / "inputs" / subdir
        if not d.exists():
            continue
        for f in sorted(d.rglob("*")):
            if not f.is_file() or f.name.startswith(".") or f.name in {".gitkeep"}:
                continue
            input_files.append(
                {
                    "path": f.relative_to(root).as_posix(),
                    "sha256": compute_file_hash(f),
                    "size_kb": round(f.stat().st_size / 1024, 1),
                }
            )

    lines = [
        f"# {project_name} — Research Intake",
        f"*Auto-generated: {now_iso()}*",
        "",
        "## Project",
        f"- Title: {project_name}",
        f"- Domain: {domain or '(not yet classified — domain_analysis will set this)'}",
        *question_lines,
        f"- Keywords: {', '.join(keywords) if keywords else '(none)'}",
        "",
        "## Input files",
    ]
    if input_files:
        lines.extend(["", "| File | SHA-256 | Size |", "|---|---|---|"])
        for f in input_files:
            lines.append(
                f"| {f['path']} | `{f['sha256'][:12]}…` | {f['size_kb']:.1f} KB |"
            )
    else:
        lines.append("- (no inputs yet — drop files into `inputs/raw_data/` or `inputs/literature/`)")
    lines.append("")

    intake_path = root / "inputs" / "intake.md"
    intake_path.parent.mkdir(parents=True, exist_ok=True)
    intake_path.write_text("\n".join(lines) + "\n")
    return str(intake_path.absolute())


def update_literature_index(root: Path) -> dict:
    """Refresh ``inputs/literature_index.yaml`` from PDFs in ``inputs/literature/``."""
    lit_dir = root / "inputs" / "literature"
    index_path = root / "inputs" / "literature_index.yaml"

    index: dict = {"schema_version": "1.0", "last_updated": now_iso(), "entries": {}}
    if index_path.exists() and yaml:
        try:
            existing = yaml.safe_load(index_path.read_text()) or {}
            index["entries"] = existing.get("entries", {})
        except Exception:
            pass

    if lit_dir.exists():
        for f in sorted(lit_dir.iterdir()):
            if not f.is_file() or f.suffix.lower() not in {".pdf", ".epub", ".ps", ".djvu"}:
                continue
            citation_key = re.sub(r"[\s-]+", "_", f.stem).lower()
            sha = compute_file_hash(f)
            entry = index["entries"].get(f.name, {})
            entry.update(
                {
                    "citation_key": citation_key,
                    "sha256": sha,
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "verified": entry.get("verified", False),
                }
            )
            index["entries"][f.name] = entry

    if yaml:
        index_path.write_text(yaml.safe_dump(index, sort_keys=False))
    else:
        index_path.write_text(json.dumps(index, indent=2) + "\n")
    return index


# ---------------------------------------------------------------------------
# Numbered experiment creation
# ---------------------------------------------------------------------------


def _prune_old_checkpoints(
    root: Path, keep: int = 5, keep_backups: int = 3
) -> dict[str, Any]:
    """Bound `.os_state/checkpoints/` size by keeping only the most recent N.

    A checkpoint whose ``.meta.json`` carries any truthy ``tag`` field
    (e.g. ``tag: "before-major-refactor"``) is preserved regardless of
    age — taggable retention lets the researcher / AI mark a checkpoint
    as keep-forever before doing something risky. Untagged checkpoints
    outside the keep window are deleted (sidecar + snapshot dir).

    Pre-rollback backups (``.meta.json`` with ``kind == "pre_rollback"``,
    written automatically before every rollback) get their OWN retention
    bucket (``keep_backups``) independent of the user-checkpoint ``keep``.
    Without this, a few rollbacks — each a full workspace copy — would
    pool into the same budget and silently evict deliberately-created
    user checkpoints.

    Returns a small report: ``{kept, removed, tagged, backups_kept,
    backups_removed}`` for the caller to log. Idempotent and safe to call
    repeatedly.
    """
    ckpt_dir = root / ".os_state" / "checkpoints"
    if not ckpt_dir.exists():
        return {"kept": 0, "removed": 0, "tagged": 0,
                "backups_kept": 0, "backups_removed": 0}
    meta_files = sorted(
        ckpt_dir.glob("*.meta.json"), key=lambda f: f.stat().st_mtime
    )
    if not meta_files:
        return {"kept": 0, "removed": 0, "tagged": 0,
                "backups_kept": 0, "backups_removed": 0}

    # Partition into tagged (always keep), pre-rollback backups (own
    # bucket), and ordinary untagged user checkpoints (subject to GC).
    tagged: list[Path] = []
    backups: list[Path] = []
    untagged: list[Path] = []
    for meta in meta_files:
        try:
            data = json.loads(meta.read_text())
            if data.get("tag"):
                tagged.append(meta)
            elif data.get("kind") == "pre_rollback":
                backups.append(meta)
            else:
                untagged.append(meta)
        except Exception:
            # Malformed sidecar: treat as untagged so GC can remove it.
            untagged.append(meta)

    # Keep the most-recent ``keep`` user checkpoints + ``keep_backups``
    # pre-rollback backups; drop the rest from each bucket independently.
    to_remove = (
        untagged[: max(0, len(untagged) - keep)]
        + backups[: max(0, len(backups) - keep_backups)]
    )
    removed = 0
    backups_removed = 0
    backup_set = set(backups)
    for meta in to_remove:
        try:
            data = json.loads(meta.read_text())
            cid = data.get("checkpoint_id")
        except Exception:
            cid = meta.stem
        meta.unlink(missing_ok=True)
        snapshot_dir = ckpt_dir / cid if cid else None
        if snapshot_dir and snapshot_dir.exists():
            shutil.rmtree(snapshot_dir, ignore_errors=True)
        if meta in backup_set:
            backups_removed += 1
        else:
            removed += 1

    return {
        "kept": len(tagged) + min(keep, len(untagged)),
        "removed": removed,
        "tagged": len(tagged),
        "backups_kept": min(keep_backups, len(backups)),
        "backups_removed": backups_removed,
    }


def _seed_step_subfolder_readmes(
    exp_dir: Path,
    root: Path,
    branch_id: str,
    next_num: int,
    from_step: str | None,
) -> None:
    """Write informative README.md stubs in every step subfolder so an empty
    folder still tells the researcher what to do — and points at the project-
    global resource (inputs/literature, environment/) when nothing step-
    specific was needed. Idempotent.
    """

    def _write_if_missing(path: Path, body: str) -> None:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)

    upstream_hint = (
        f"data/past_step_input → previous step's data/next_step_output "
        f"(step {next_num - 1:02d})."
        if next_num > 1 and not from_step
        else "data/past_step_input → inputs/raw_data (this is the ingest step)."
        if next_num == 1
        else f"data/past_step_input → `{from_step}`'s data/next_step_output."
    )

    # Top-level data/ — explains the four data folders + how steps consume them.
    _write_if_missing(
        exp_dir / "data" / "README.md",
        f"# `{branch_id}` — data\n\n"
        "Four subfolders, all managed by the harness:\n\n"
        "- **`project_inputs/`** — symlink to the project's "
        "`inputs/raw_data/`. The original data, always reachable even if "
        "the upstream step produced nothing.\n"
        "- **`past_step_input/`** — usually a symlink to the previous step's "
        f"`data/next_step_output/`. This step's working inputs. Default: "
        f"{upstream_hint}\n"
        "- **`next_step_output/`** — write CSV/parquet/pickle artefacts the "
        "NEXT step needs here. Downstream steps' `data/past_step_input/` "
        "symlinks to this folder, so name files for reuse "
        "(e.g. `tidy_survey.csv`, `composites.csv`).\n"
        "- **`share/`** — *optional*. A curated, self-contained dataset you "
        "package to hand to a collaborator or a new workflow (data + a small "
        "read-me/script). Distinct from `next_step_output/` (which feeds the "
        "next step); `share/` is for export.\n\n"
        "When this step is complete `tool_path_finalize` rewrites this file "
        "with the actual filename → downstream-step consumer mapping derived "
        "from the workflow DAG.\n",
    )
    pi_path = exp_dir / "data" / "past_step_input"
    _write_if_missing(
        pi_path / "README.md"
        if pi_path.is_dir() and not pi_path.is_symlink()
        else exp_dir / "data" / "_past_step_input_readme.md",
        f"# `{branch_id}/data/past_step_input` — usage\n\n"
        f"Default wiring: {upstream_hint}\n\n"
        "Replace the symlink with a directory only if this step has bespoke "
        "inputs that aren't a clean function of the previous step's outputs. "
        "Document any divergence in `analysis.md` (`mem_log(kind='decision')`).\n",
    )
    _write_if_missing(
        exp_dir / "data" / "next_step_output" / "README.md",
        f"# `{branch_id}/data/next_step_output` — usage\n\n"
        "Persist analytic artefacts (CSV, parquet, pickle, JSON) here so the "
        "next step and the synthesis dashboard can consume them.\n\n"
        "Each saved file should be reproducible from `scripts/` alone — no "
        "ad-hoc REPL edits. After `tool_path_finalize` runs, this README is "
        "rewritten to list every persisted artefact with its consumer step.\n",
    )
    _write_if_missing(
        exp_dir / "data" / "share" / "README.md",
        f"# `{branch_id}/data/share` — export\n\n"
        "Optional. Drop a curated, self-contained dataset here when you want "
        "to hand it to a collaborator or seed a new workflow — the data plus "
        "a short read-me (and a script if it needs regenerating). This is an "
        "EXPORT surface, separate from `next_step_output/` (which feeds the "
        "next analysis step). Iterate on it freely; nothing downstream "
        "depends on it.\n",
    )

    # environment/, literature/, context/ are LAZY — created by tools on
    # first use, not pre-seeded with stub READMEs. Pre-seeded stubs:
    #   * trained the AI to leave the dirs as boilerplate;
    #   * caused literature/ to read as "no citations" when really the
    #     AI just hadn't downloaded any;
    #   * cluttered every step folder with content nobody wrote.
    # Each dir is still in EXPERIMENT_SUBDIRS so the path exists, but
    # the README that should answer "what goes here?" lives in the
    # researcher / AI guides, not duplicated 14x on disk. When the AI
    # downloads a citation into literature/<author-year>.md it appears
    # in an empty dir; the cardinality alone tells the reader the state.

    # Outputs — explain what each subfolder is for. SVG is opt-in via
    # researcher_config.figures.svg_allowed (off by default).
    _write_if_missing(
        exp_dir / "outputs" / "README.md",
        f"# `{branch_id}` — outputs\n\n"
        "- **`figures/`** — `.png` plots (the analysis outputs). Each figure "
        "ships exactly three siblings: the image, a `<name>.prov.json` "
        "provenance record, and a `<name>.caption.md` (the technical "
        "caption the synthesis embeds). The plain-English interpretation "
        "lives inline in `conclusions.md` next to the embed. SVG companions "
        "are opt-in (`researcher_config.figures.svg_allowed: true`); "
        "interactive `.html` figures suit networks / large multi-panels.\n"
        "- **`tables/`** — CSV / TSV tables (analysis outputs). Each table "
        "SHOULD have a sibling `<name>.caption.md`.\n"
        "- **`reports/`** — *optional, created on demand* (not pre-made). For "
        "point-in-time PRESENTATION artefacts you build to SHOW someone — a "
        "one-off dashboard for a committee, a slide for a journal club. These "
        "are NOT analysis-script outputs (those are `figures/` + `tables/`), "
        "NOT intermediate data (that's `data/next_step_output/`), and NOT "
        "where findings live (findings → `conclusions.md`). Only `mkdir` this "
        "when you genuinely build a presentation artefact; header each with "
        "its date + intended audience.\n\n"
        "Follow `figure_guidelines` (DPI ≥150 screen / ≥300 print, colour-blind "
        "safe palette, axis units). The AI MUST `sys_file_read` each figure "
        "before declaring the step done (catches legend-over-plot, missing "
        "axis labels, palette regressions). Audit with `tool_audit_figure`.\n",
    )

    # Scripts — explain naming + reproducibility expectation.
    _write_if_missing(
        exp_dir / "scripts" / "README.md",
        f"# `{branch_id}` — scripts\n\n"
        f"Place runnable analysis scripts here (preferred name: "
        f"`{branch_id}_v1.py`). Bump the suffix when the analysis materially "
        "changes; the dashboard surfaces the latest version. Each script must "
        "be re-runnable end-to-end with only `data/past_step_input/` and the documented "
        "environment as inputs.\n",
    )


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


def create_numbered_experiment(
    root: Path,
    name: str,
    hypothesis: str = "",
    from_step: str | None = None,
    branch_of: str | None = None,
    *,
    enforce_predecessor_finalized: bool = True,
) -> dict:
    """Create the next numbered experiment folder + wire up its data link.

    Branching
    ---------
    Pass ``branch_of=<existing path_id>`` to fork a new analytical path off
    an existing step. The new folder name carries a ``_path_<k>`` lineage
    suffix (e.g. ``05_glmm_path_1``). Subsequent calls that branch off a
    step ALREADY carrying a lineage tag inherit it — the lineage flows
    through every downstream step on the branch. A brand-new fork
    receives the next free lineage number (max existing + 1).

    Dead-ends keep the existing ``__DEAD_END`` convention and stack with
    branch tags: ``05_glmm_path_1`` → ``05_glmm_path_1__DEAD_END``.

    Root validation
    ---------------
    Raises ``ValueError`` if ``root`` is not a Research-OS project (no
    ``.os_state/`` directory present). Prevents accidental pollution of
    arbitrary cwd when a misconfigured caller passes the wrong root.
    """
    if not (root / ".os_state").is_dir():
        raise ValueError(
            f"{root} is not a Research-OS project (no .os_state/ directory). "
            f"Run `research-os init` here first, or pass the correct project root."
        )
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    # Enforce previous-step finalization. Without this, the AI can
    # create step 02 with step 01 left in placeholder form (README +
    # conclusions never filled, analysis.md missing the step 01
    # entry). The rule: refuse to scaffold step N+1 while the most-
    # recent main-path step (N) still has placeholder text in its
    # README. The caller can override via
    # ``enforce_predecessor_finalized=False`` — used by tests that
    # exercise multi-step scaffolding without going through the full
    # finalize workflow, and by ``sys_path(operation='create')`` when the researcher
    # explicitly authorises bypass (logged to workspace/logs/override_log.md).
    all_step_dirs = discover_step_dirs(workspace)
    existing_main_steps = sorted(
        (p for p in all_step_dirs
         if _extract_path_lineage(p.name) is None
         and not p.name.endswith("__DEAD_END")),
        key=_step_sort_key,
    )
    if enforce_predecessor_finalized and existing_main_steps and not branch_of:
        prev = existing_main_steps[-1]
        prev_readme = prev / "README.md"
        prev_conc = prev / "conclusions.md"
        prev_plan = prev / "plan.md"
        if prev_readme.exists() and prev_conc.exists():
            r_txt = prev_readme.read_text()
            c_txt = prev_conc.read_text()
            # plan.md is optional on pre-3.2 steps; only gate when present.
            p_txt = prev_plan.read_text() if prev_plan.exists() else ""
            placeholder_markers_readme = (
                "*(2-3 sentences a colleague",
                "*(list inputs used)*",
                "*(name the method;",
                "*(the single most important result",
                "*(proceed | branch | dead-end",
            )
            placeholder_markers_conc = (
                "*(2-5 quantitative bullets",
                "*(Dataset shape",
                "*(What this step cannot conclude",
            )
            # plan.md seed sections (see the plan.md writer below). A plan
            # that was genuinely written before the work fills the design
            # core; a plan that was SKIPPED leaves these raw. Field-proof:
            # every step of the reaction-similarity project shipped all six
            # of these untouched yet still advanced — because the
            # predecessor gate never inspected plan.md. It does now.
            placeholder_markers_plan = (
                "*(Recap the previous step's outcome",       # Where we are
                "*(The goal for",                            # What this step will do
                "*(How it advances",                         # Why this step, why now
                "*(The decisions you want",                  # Open questions
                "*(Update this AS YOU WORK",                 # Progress & deviations
                "*(Where this likely leads",                 # Anticipated next steps
            )
            unfilled_readme = sum(m in r_txt for m in placeholder_markers_readme)
            unfilled_conc = sum(m in c_txt for m in placeholder_markers_conc)
            unfilled_plan = sum(m in p_txt for m in placeholder_markers_plan)
            plan_skipped = bool(p_txt) and unfilled_plan >= 4
            if unfilled_readme >= 3 or unfilled_conc >= 2 or plan_skipped:
                bits = []
                if unfilled_readme >= 3:
                    bits.append(f"README has {unfilled_readme} unfilled stubs")
                if unfilled_conc >= 2:
                    bits.append(f"conclusions.md has {unfilled_conc}")
                if plan_skipped:
                    bits.append(
                        f"plan.md is still the unfilled seed "
                        f"({unfilled_plan}/6 sections untouched)"
                    )
                raise ValueError(
                    f"Cannot scaffold the next step: previous step "
                    f"`{prev.name}` is still in placeholder form "
                    f"({'; '.join(bits)}). Fill the step's README "
                    "(`## In plain English`, `## Decision`), conclusions.md "
                    "(`## Findings`, `## Decision`), and plan.md (the design + "
                    "`## Progress & deviations from plan` reconcile), then call "
                    f"`tool_path_finalize` on `{prev.name}` to lock its "
                    "findings into workspace/analysis.md + methods.md + "
                    "tools.md + citations.md. If this is a data-plumbing step "
                    "that legitimately has nothing to conclude, write 'No "
                    "substantive findings — see step purpose in README' into "
                    "the stubs before re-trying. To override deliberately, "
                    "call `sys_path(operation='create', "
                    "allow_unfinalized_predecessor=true, override_rationale=…)` "
                    "(logged to workspace/logs/override_log.md)."
                )

    # Numbering is CONTINUOUS across the whole workspace — flat steps AND
    # steps grouped into PATH containers — so a new step never collides with
    # or re-uses a grouped step's number.
    max_num = 0
    for p in all_step_dirs:
        try:
            max_num = max(max_num, int(p.name.split("_", 1)[0]))
        except ValueError:
            pass
    next_num = max_num + 1
    slug = slugify(name, "experiment")

    # Resolve branch lineage. Order of precedence:
    #   1. `branch_of` names an existing step → inherit its lineage if any,
    #      otherwise allocate a fresh lineage number.
    #   2. No `branch_of` → no lineage tag (main path).
    lineage: int | None = None
    parent_id: str | None = None
    if branch_of:
        # Allow callers to pass either the full `NN_slug` or the dead-end
        # variant; we resolve to the real on-disk folder.
        candidates = [branch_of, branch_of.removesuffix("__DEAD_END")]
        parent_dir: Path | None = None
        for cand in candidates:
            # resolve_step_dir finds the step whether it is flat or grouped
            # under a PATH container, and tolerates the dead-end variant.
            found = resolve_step_dir(workspace, cand)
            if found is not None:
                parent_dir = found
                parent_id = found.name
                break
        if parent_dir is None:
            raise ValueError(f"branch_of step '{branch_of}' not found in workspace/")
        inherited = _extract_path_lineage(parent_dir.name)
        lineage = inherited if inherited is not None else _max_path_lineage(workspace) + 1

    if lineage is not None:
        branch_id = f"{next_num:02d}_{slug}_path_{lineage}"
    else:
        branch_id = f"{next_num:02d}_{slug}"
    exp_dir = workspace / branch_id

    if exp_dir.exists():
        raise ValueError(f"Experiment '{branch_id}' already exists at {exp_dir}")

    check_write_permitted(exp_dir)

    # `from_step` ONLY wires data/past_step_input from the named step's output —
    # nothing else. A naive `shutil.copytree` would duplicate
    # outputs/figures/tables/reports/scripts, bloating the workspace,
    # breaking per-step provenance (the new step's outputs/ would
    # contain the previous step's artefacts before any code ran), and
    # confusing tool_path_finalize's inventory. Everything else is
    # scaffolded fresh.
    exp_dir.mkdir(parents=True, exist_ok=True)
    for sub in EXPERIMENT_SUBDIRS:
        (exp_dir / sub).mkdir(parents=True, exist_ok=True)
    # ALWAYS expose the project's inputs/raw_data/ via a
    # `data/project_inputs` symlink so an analysis step can reach the
    # original data when its `data/past_step_input` (which prefers the
    # upstream step's data/next_step_output/) is empty — a common pitfall
    # where step 02 inherits step 01's empty data/next_step_output.
    raw_inputs = root / "inputs" / "raw_data"
    raw_inputs.mkdir(parents=True, exist_ok=True)
    project_inputs_link = exp_dir / "data" / "project_inputs"
    if not project_inputs_link.exists():
        try:
            project_inputs_link.symlink_to(raw_inputs.absolute())
        except OSError:
            pass
    # Wire data/past_step_input → the upstream step's output dir (resolved
    # tolerantly so a step created in a pre-3.2 project still links to that
    # step's legacy data/output). data_input is the new step's input link.
    data_input = exp_dir / "data" / "past_step_input"

    def _link_upstream(upstream_dir: Path) -> None:
        out_dir = step_output_dir(upstream_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            data_input.rmdir()
            data_input.symlink_to(out_dir.absolute())
        except OSError:
            pass

    if from_step:
        # A typo'd from_step previously fell back to (workspace / from_step),
        # silently materialising a phantom upstream dir + a bogus lineage
        # edge. Validate it resolves to a real step (mirror branch_of above).
        from_step_dir = resolve_step_dir(workspace, from_step)
        if from_step_dir is None:
            raise ValueError(f"from_step '{from_step}' not found in workspace/")
        _link_upstream(from_step_dir)
    elif parent_id:
        # Branch steps draw from their parent's output (resolved above,
        # whether the parent is flat or grouped under a PATH container).
        _link_upstream(parent_dir)
    elif next_num == 1:
        raw_dir = root / "inputs" / "raw_data"
        raw_dir.mkdir(parents=True, exist_ok=True)
        try:
            data_input.rmdir()
            data_input.symlink_to(raw_dir.absolute())
        except OSError:
            pass
    else:
        prev_num = next_num - 1
        # Prefer main-path predecessors over branch siblings when both exist.
        # discover_step_dirs spans flat steps + PATH-grouped steps.
        prev_candidates = [
            p for p in all_step_dirs
            if re.match(rf"^{prev_num:02d}_", p.name)
        ]
        prev_dirs = sorted(
            (p for p in prev_candidates
             if _extract_path_lineage(p.name) is None),
            key=_step_sort_key,
        ) or sorted(prev_candidates, key=_step_sort_key)
        if prev_dirs:
            _link_upstream(prev_dirs[0])

    # README — the OVERVIEW reader: short, easy to read, no statistical jargon.
    # `conclusions.md` is the thorough version with method details.
    (exp_dir / "README.md").write_text(
        f"# Experiment: {branch_id}\n*Created: {now_iso()}*\n\n"
        "> **What this file is.** A short overview a non-expert reader can "
        "skim in 60 seconds. The detailed methodology, statistics, and "
        "limitations live in [`conclusions.md`](./conclusions.md). "
        "When the step is finished, run `tool_path_finalize` to populate "
        "the sections below from what was actually produced.\n\n"
        f"## Goal\n{hypothesis or name}\n\n"
        "## In plain English\n"
        "*(2-3 sentences a colleague from another field could follow: what "
        "was tested, what was found, and the strength of the evidence. This "
        "is the canonical plain-language summary — the synthesis dashboard's "
        "executive / teaching views surface it verbatim.)*\n\n"
        "## Input data\n- *(list inputs used)*\n\n"
        "## Methods (one line each)\n- *(name the method; full justification "
        "lives in `conclusions.md` and `literature/findings_vs_literature.md`)*\n\n"
        "## Headline finding\n- *(the single most important result — "
        "researchers should be able to quote this sentence verbatim)*\n\n"
        "## Outputs\n- *(figures / tables produced)*\n\n"
        "## Decision\n- *(proceed | branch | dead-end)*\n\n"
        "## Read next\n"
        "- [`plan.md`](./plan.md) — the living plan: prior context, this "
        "step's design, open questions, and (updated as the step ran) how "
        "it actually went vs. the plan.\n"
        "- [`conclusions.md`](./conclusions.md) — full statistical results, "
        "limitations, decisions, and step-to-step tracking.\n"
        "- [`outputs/figures/`](./outputs/figures/) — every figure has a "
        "sibling `.caption.md` (technical) the synthesis embeds.\n"
        "- [`literature/findings_vs_literature.md`](./literature/findings_vs_literature.md)"
        " — how this step's findings sit against the literature.\n"
    )
    # conclusions.md — the THOROUGH reader: full statistical detail, edge
    # cases, sensitivity checks, every limitation. Targets the same audience
    # as a journal Methods + Results + Discussion section.
    (exp_dir / "conclusions.md").write_text(
        f"# {branch_id} — Conclusions\n*Created: {now_iso()}*\n\n"
        "> **What this file is.** The deep report for this step: the full "
        "statistical record PLUS the thought-process tracking. Method, "
        "assumption checks, every effect size, every limitation, and how "
        "this step's decision evolved — both across the step's own "
        "iterations and from the previous step to this one. The plain-"
        "language summary lives in `README.md` (`## In plain English`); do "
        "not duplicate it here.\n\n"
        "## Findings\n"
        "*(2-5 quantitative bullets with numbers + units + 95% CI where "
        "applicable. Lead with effect sizes, not p-values. Plain frequencies "
        "preferred over percentages for risk communication.)*\n\n"
        "## Hypothesis evidence\n"
        "*(For each hypothesis touched: H<id> status + one-line evidence + "
        "the figure / table the verdict rests on.)*\n\n"
        "## Methods (full detail)\n"
        "*(Dataset shape, transforms applied, model spec, parameter values, "
        "RNG seed, software versions. Reproducible: a competent reader "
        "should be able to re-run this from `scripts/` alone.)*\n\n"
        "## Methodological notes\n"
        "*(Assumption checks, sensitivity analyses, robustness — use "
        "supportive voice. e.g. \"the analysis would benefit from\" rather "
        "than \"is wrong\".)*\n\n"
        "## Limitations\n"
        "*(What this step cannot conclude, and why — sample size, design "
        "constraints, measurement bias, etc. Honest framing: \"no detectable "
        "difference\" beats \"no effect\" when underpowered.)*\n\n"
        "## Decision\n"
        "*(proceed | branch | dead-end. Record the reasoning AND the "
        "lineage: how the previous step led here, and — if this step was "
        "iterated — what changed from the prior version and why. This is "
        "the full thought-process trail a future reader reconstructs the "
        "project from.)*\n\n"
        "## Next steps\n*(2-3 candidates with rationale)*\n"
    )

    # plan.md — the PRE-STEP plan (co-scientist style). Written at step
    # creation, BEFORE any scripts / figures: it carries forward the prior
    # step's outcome + the project's findings-to-date, lays out this step's
    # design, and poses the open question(s) the researcher iterates on
    # before work begins. Under autopilot the AI still fills it in (it is
    # the record of the AI's reasoning), but does not pause for sign-off.
    (exp_dir / "plan.md").write_text(
        f"# {branch_id} — Plan\n*Created: {now_iso()}*\n\n"
        "> **What this file is.** A LIVING plan for this step. Write it "
        "BEFORE any scripts / figures and iterate with the researcher "
        "(propose → critique → refine); then KEEP IT CURRENT as the work "
        "unfolds — when the design shifts mid-step, edit the section that "
        "changed and log why under *Progress & deviations*. At the end, "
        "reconcile plan-vs-actual there so the file records what you "
        "actually did, not just what you intended. The overall-project "
        "counterpart is `inputs/research_plan.md`.\n\n"
        "## Where we are\n"
        "*(Recap the previous step's outcome + the project's findings so far "
        "— the context this step builds on. For step 01, summarise the "
        "research question + inputs instead.)*\n\n"
        "## What this step will do\n"
        f"*(The goal for `{branch_id}`: the question it answers, the data it "
        "uses, the method(s) it will apply, and the artefact(s) it will "
        "produce.)*\n\n"
        "## Why this step, why now\n"
        "*(How it advances the hypotheses / research question, and why it is "
        "the right next move versus the alternatives.)*\n\n"
        "## Open questions for the researcher\n"
        "*(The decisions you want the researcher to weigh in on before you "
        "start — design choices, scope, trade-offs. Under autopilot, note "
        "the choice you made and proceed.)*\n\n"
        "## Progress & deviations from plan\n"
        "*(Update this AS YOU WORK and at finalize: what changed from the "
        "plan above and why (a method swap, a dropped sub-analysis, an "
        "added robustness check), so plan.md ends as a true record of the "
        "step. \"Went exactly to plan\" is a valid entry.)*\n\n"
        "## Anticipated next steps\n"
        "*(Where this likely leads — so the plan carries forward.)*\n"
    )

    _seed_step_subfolder_readmes(exp_dir, root, branch_id, next_num, from_step)

    # State update — under the ledger lock so a concurrent step-create /
    # hypothesis-add on another session can't clobber the new paths[] entry
    # (the folder is already on disk above; the lock closes the
    # lost-paths-entry / orphaned-folder window).
    path_entry: dict[str, Any] = {
        "path_id": branch_id,
        "experiment_number": next_num,
        "status": "active",
        "hypothesis": hypothesis or name,
        "experiment_dir": f"workspace/{branch_id}",
        "created_at": now_iso(),
    }
    if lineage is not None:
        path_entry["path_lineage"] = lineage
    if parent_id:
        path_entry["branch_of"] = parent_id

    def _record_step(state: dict) -> None:
        state.setdefault("paths", {})[branch_id] = path_entry
        state["current_path"] = branch_id
        state["step"] = next_num
        if state.get("pipeline_stage") in (None, "init", "planned"):
            state["pipeline_stage"] = "execution"

    mutate_state(root, _record_step)
    _update_manifest(root)
    _update_workflow_mermaid(root)
    _prune_old_checkpoints(root, keep=5)
    # Refresh DAG view best-effort; don't block step creation on failures.
    try:
        from research_os.tools.actions.state.path import workflow_dag

        workflow_dag(root)
    except Exception:
        pass

    return {
        "path_id": branch_id,
        "experiment_number": next_num,
        "experiment_dir": str(exp_dir.absolute()),
        "from_step": from_step,
        "branch_of": parent_id,
        "path_lineage": lineage,
        "paths_created": [str(exp_dir / sub) for sub in EXPERIMENT_SUBDIRS],
    }


# ---------------------------------------------------------------------------
# Workflow diagram + analysis.md helpers
# ---------------------------------------------------------------------------


def log_decision(
    context: str,
    selected: str,
    rationale: str,
    *,
    options_considered: list[str] | None = None,
    linked_literature: list[str] | None = None,
    root: Path | None = None,
) -> dict:
    """Append a methodological decision to workspace/analysis.md."""
    root = _resolve_root(root)
    analysis_path = root / "workspace" / "analysis.md"
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    entry = (
        f"\n\n### Decision · {ts}\n"
        f"- **Context**: {context}\n"
        f"- **Selected**: {selected}\n"
        f"- **Rationale**: {rationale}\n"
    )
    if options_considered:
        entry += f"- **Options considered**: {', '.join(options_considered)}\n"
    if linked_literature:
        entry += f"- **Linked literature**: {', '.join(linked_literature)}\n"
    with open(analysis_path, "a") as f:
        f.write(entry)
    return {"logged": True, "path": "workspace/analysis.md"}


def _atomic_write_text(path: Path, text: str) -> None:
    """Atomic text write: temp file in the same dir + ``os.replace``.

    analysis.md (and the other append-only logs) are rewritten in place by
    several mutating tools; a bare ``read_text`` → ``write_text`` can lose
    the file to truncation if a concurrent writer interleaves or the
    process dies mid-write. Writing to a sibling temp and renaming makes
    the swap atomic on POSIX."""
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


def _citation_identity(meta: dict) -> tuple:
    """Best-effort identity for a bibliography entry, used to tell a true
    duplicate (same reference seen twice) from a key COLLISION (two
    distinct references that happen to derive the same citation key).

    A duplicate should be deduped (keep first); a collision must be
    disambiguated so the second reference is not silently clobbered.
    """
    doi = (meta.get("doi") or "").strip().lower()
    if doi:
        return ("doi", doi)
    sha = (meta.get("sha256") or "").strip().lower()
    if sha:
        return ("sha", sha)
    fn = (meta.get("filename") or "").strip().lower()
    if fn:
        return ("file", fn)
    title = (meta.get("title") or "").strip().lower()
    return ("title", title)


def _insert_citation_entry(entries: dict, key: str, meta: dict) -> str:
    """Insert ``meta`` under ``key`` into ``entries`` with collision-safe
    disambiguation. Returns the key actually used.

    - If ``key`` is free → use it.
    - If ``key`` is taken by the SAME reference (matching identity) →
      keep the existing entry (dedup, mirrors the old ``setdefault``).
    - If ``key`` is taken by a DIFFERENT reference → append a ``a``/``b``/…
      suffix to the new key so neither reference is lost.
    """
    if key not in entries:
        entries[key] = meta
        return key
    incoming_id = _citation_identity(meta)
    # Walk the base key and any existing suffixed siblings; if we already
    # hold this exact reference, keep it (dedup).
    suffixes = ["", "a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]
    for sfx in suffixes:
        cand = f"{key}{sfx}"
        if cand in entries:
            if _citation_identity(entries[cand]) == incoming_id:
                return cand  # same reference already recorded
            continue
        # First free suffixed slot for a genuinely different reference.
        meta = dict(meta)
        meta["citation_key"] = cand
        entries[cand] = meta
        return cand
    # Exhausted the suffix alphabet (pathological); fall back to a numeric
    # tail so we still never clobber.
    n = 0
    while True:
        cand = f"{key}_{n}"
        if cand not in entries:
            meta = dict(meta)
            meta["citation_key"] = cand
            entries[cand] = meta
            return cand
        if _citation_identity(entries[cand]) == incoming_id:
            return cand
        n += 1


def generate_citations_md(root: Path) -> str:
    """Regenerate workspace/citations.md from project + per-step literature.

    Pulls entries from:
      - inputs/literature_index.yaml                 (project scope)
      - workspace/<step>/literature/literature_index.yaml (each step scope)
      - workspace/<step>/literature/*.meta.{yaml,json}    (sidecars)
    """
    citations_path = root / "workspace" / "citations.md"
    citations_path.parent.mkdir(parents=True, exist_ok=True)

    # citation_key → entry dict
    entries: dict[str, dict] = {}

    # 1. Project-level literature index.
    proj_index = root / "inputs" / "literature_index.yaml"
    if proj_index.exists() and yaml:
        try:
            data = yaml.safe_load(proj_index.read_text()) or {}
            for filename, meta in (data.get("entries") or {}).items():
                key = meta.get("citation_key") or filename
                meta = dict(meta)
                meta.setdefault("citation_key", key)
                meta.setdefault("filename", filename)
                meta.setdefault("scope", "project")
                _insert_citation_entry(entries, key, meta)
        except Exception:
            pass

    # 1b. Project corpus of record (literature/steps/<id>/) — aggregated by
    #     tool_path_finalize. Catches papers pulled into a step's context/
    #     folder, which the per-step literature/ scan below would miss.
    corpus_steps = root / "literature" / "steps"
    if corpus_steps.is_dir() and yaml:
        for step_sub in sorted(corpus_steps.iterdir()):
            if not step_sub.is_dir():
                continue
            for pdf in sorted(step_sub.iterdir()):
                if not pdf.is_file() or pdf.suffix.lower() not in {".pdf", ".epub"}:
                    continue
                for ext in (".meta.yaml", ".meta.json"):
                    side = pdf.with_name(pdf.name + ext)
                    if not side.exists():
                        continue
                    try:
                        if ext == ".meta.yaml":
                            meta = yaml.safe_load(side.read_text()) or {}
                        else:
                            meta = json.loads(side.read_text())
                    except Exception:
                        meta = {}
                    key = meta.get("citation_key") or re.sub(
                        r"[\s-]+", "_", pdf.stem).lower()
                    meta = dict(meta)
                    meta["citation_key"] = key
                    meta["filename"] = pdf.name
                    meta.setdefault("scope", f"corpus:{step_sub.name}")
                    _insert_citation_entry(entries, key, meta)
                    break

    # 2. Per-step literature indexes + sidecars + conclusions.md
    # "References to ground" sections.
    workspace = root / "workspace"
    if workspace.exists():
        for step_dir in discover_step_dirs(workspace):
            # 2a. Scrape `## References to ground` from each step's
            # conclusions.md so prose-cited refs (the AI's most common
            # pattern) make it into the project bibliography without
            # requiring a per-paper sidecar.
            conc = step_dir / "conclusions.md"
            if conc.exists():
                try:
                    txt = conc.read_text()
                    m = re.search(
                        r"##\s*References?\s+to\s+ground\s*\n(.+?)(?=^##|\Z)",
                        txt, re.MULTILINE | re.DOTALL | re.IGNORECASE,
                    )
                    if m:
                        for line in m.group(1).splitlines():
                            line = line.strip()
                            if not line.startswith(("-", "*", "+")):
                                continue
                            ref_text = re.sub(r"^[-*+]\s*", "", line).strip()
                            if len(ref_text) < 5:
                                continue
                            # Derive a citation key from the first author-year-ish chunk.
                            author_m = re.match(r"([A-Z][a-zA-Z'-]+)", ref_text)
                            year_m = re.search(r"(19|20)\d{2}", ref_text)
                            if author_m and year_m:
                                key = f"{author_m.group(1).lower()}{year_m.group(0)}"
                            else:
                                key = "conc_" + re.sub(r"[^a-z0-9]+", "_", ref_text[:30].lower()).strip("_")
                            _insert_citation_entry(entries, key, {
                                "citation_key": key,
                                "title": ref_text,
                                "scope": f"step:{step_dir.name}",
                                "verified": False,
                                "source": "conclusions.md/References to ground",
                            })
                except Exception:
                    pass
            lit_dir = step_dir / "literature"
            if not lit_dir.exists():
                continue
            # First read the step's index (if present).
            step_idx = lit_dir / "literature_index.yaml"
            if step_idx.exists() and yaml:
                try:
                    data = yaml.safe_load(step_idx.read_text()) or {}
                    for filename, meta in (data.get("entries") or {}).items():
                        key = meta.get("citation_key") or filename
                        meta = dict(meta)
                        meta.setdefault("citation_key", key)
                        meta.setdefault("filename", filename)
                        meta.setdefault("scope", f"step:{step_dir.name}")
                        # Don't clobber project entries; step entries are
                        # secondary. Distinct refs sharing a key are
                        # disambiguated rather than dropped.
                        _insert_citation_entry(entries, key, meta)
                except Exception:
                    pass
            # Then fall back to sidecar walk for PDFs that have no index entry.
            for pdf in lit_dir.iterdir():
                if not pdf.is_file() or pdf.suffix.lower() not in {".pdf", ".epub"}:
                    continue
                for ext in (".meta.yaml", ".meta.json"):
                    side = pdf.with_suffix(pdf.suffix + ext)
                    if side.exists():
                        try:
                            if ext == ".meta.yaml":
                                meta = (yaml.safe_load(side.read_text()) or {}) if yaml else {}
                            else:
                                meta = json.loads(side.read_text())
                        except Exception:
                            meta = {}
                        key = meta.get("citation_key") or re.sub(r"[\s-]+", "_", pdf.stem).lower()
                        meta["citation_key"] = key
                        meta["filename"] = pdf.name
                        meta.setdefault("scope", f"step:{step_dir.name}")
                        _insert_citation_entry(entries, key, meta)
                        break

    lines = [
        "# Running Bibliography",
        "",
        "*Auto-generated from project + per-step literature.*",
        "",
    ]
    if entries:
        # Sort by scope (project first), then citation_key.
        ordered = sorted(
            entries.items(),
            key=lambda kv: (0 if kv[1].get("scope") == "project" else 1, kv[0]),
        )
        for key, meta in ordered:
            scope = meta.get("scope", "project")
            # "✅ verified" is reserved for entries an actual verifier
            # (tool_citations_verify / a provider check) marked verified.
            # Merely carrying a DOI/URL string is NOT verification — a
            # fabricated identifier would otherwise read as verified.
            verified = bool(meta.get("verified"))
            has_id = bool(meta.get("doi") or meta.get("url"))
            sha = (meta.get("sha256") or "")[:12]
            if verified:
                badge = "✅ verified"
            elif has_id:
                badge = "⏳ identifier present, not yet verified"
            else:
                badge = "⏳ pending verification"
            lines.append(f"### `{key}`")
            lines.append(f"- Scope: `{scope}`")
            if meta.get("filename"):
                lines.append(f"- File: {meta['filename']}")
            if meta.get("title"):
                lines.append(f"- Title: {meta['title']}")
            if meta.get("authors"):
                authors = meta["authors"]
                if isinstance(authors, list):
                    authors = ", ".join(authors)
                lines.append(f"- Authors: {authors}")
            if meta.get("year"):
                lines.append(f"- Year: {meta['year']}")
            if meta.get("doi"):
                lines.append(f"- DOI: `{meta['doi']}`")
            if meta.get("url"):
                lines.append(f"- URL: {meta['url']}")
            if sha:
                lines.append(f"- SHA-256: `{sha}`")
            lines.append(f"- Status: {badge}")
            lines.append("")
    else:
        lines.append(
            "*(No literature yet — drop PDFs in `inputs/literature/` or call "
            "`tool_literature_download` / `tool_literature_search_and_save`.)*"
        )
        lines.append("")

    citations_path.write_text("\n".join(lines) + "\n")
    return str(citations_path.absolute())


