"""`research-os doctor` — pre-flight + workspace health checks.

A diagnostic harness modelled on `brew doctor` / `rustup doctor`. Runs a
list of independent checks and prints a coloured summary (or JSON, with
``--json``). Each check returns a tri-state status:

* ``pass``  — everything looks correct.
* ``warn``  — non-fatal: the user should know, but the install is usable.
* ``fail``  — something is genuinely broken and will bite at runtime.

Exit codes:
    0 — all pass (warnings ok)
    1 — at least one warn (no fail)
    2 — at least one fail

Two scopes:

* **Install checks** (always run): python version, conda env, version
  consistency across `pyproject.toml` / `__init__.py` / `CITATION.cff`,
  pack discoverability, embeddings freshness, typst / chromium on PATH,
  optional dep coverage.
* **Workspace checks** (only when invoked inside a workspace, OR always
  unless ``--workspace-only`` flips the inverse): MCP config wiring,
  orphan figures, unresolved BLOCK gates in the
  audit ledger, disk usage, git cleanliness, .gitignore coverage.

The module exposes one entry-point (`cmd_doctor`) plus a thin public
API of `check_*` functions so each one is unit-testable in isolation.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# ── Status type ───────────────────────────────────────────────────────

# A check function returns ``(status, message, fix_hint_or_None)``.
# ``status`` is one of "pass" | "warn" | "fail".
CheckResult = tuple[str, str, Optional[str]]


@dataclass
class CheckReport:
    """One row in the doctor output."""
    name: str
    status: str
    message: str
    fix: Optional[str] = None
    scope: str = "install"  # "install" or "workspace"

    def to_dict(self) -> dict:
        d = {"name": self.name, "status": self.status,
             "message": self.message, "scope": self.scope}
        if self.fix:
            d["fix"] = self.fix
        return d


@dataclass
class DoctorRun:
    """Aggregated checks for one invocation."""
    checks: list[CheckReport] = field(default_factory=list)

    def add(self, name: str, result: CheckResult, scope: str = "install") -> None:
        status, msg, fix = result
        self.checks.append(CheckReport(name=name, status=status, message=msg,
                                       fix=fix, scope=scope))

    @property
    def summary(self) -> dict[str, int]:
        out = {"pass": 0, "warn": 0, "fail": 0}
        for c in self.checks:
            if c.status in out:
                out[c.status] += 1
        return out

    @property
    def exit_code(self) -> int:
        s = self.summary
        if s["fail"]:
            return 2
        if s["warn"]:
            return 1
        return 0

    def to_json(self) -> dict:
        return {
            "checks": [c.to_dict() for c in self.checks],
            "summary": self.summary,
            "exit_code": self.exit_code,
        }


# ── Tiny ANSI helpers (mirror cli.py / wizard.py style) ──────────────


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    return True


def _supports_utf8() -> bool:
    """True when stdout can encode the ✓/⚠/✗ glyphs (else fall back to ASCII)."""
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in enc


class _Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    GREY = "\033[90m"
    CYAN = "\033[36m"


def _c(text: str, code: str, enable: bool) -> str:
    return f"{code}{text}{_Style.RESET}" if enable else text


# ── Install-level checks ──────────────────────────────────────────────


def check_python_version() -> CheckResult:
    """Require Python >= 3.10 (matches pyproject `requires-python`)."""
    v = sys.version_info
    if (v.major, v.minor) >= (3, 10):
        return ("pass", f"Python {v.major}.{v.minor}.{v.micro} (>= 3.10)", None)
    return (
        "fail",
        f"Python {v.major}.{v.minor}.{v.micro} is too old (need >= 3.10)",
        "Install Python 3.10+ via conda: "
        "`conda create -n research-os python=3.11 && conda activate research-os`",
    )


def check_conda_active() -> CheckResult:
    """Warn if CONDA_DEFAULT_ENV isn't set — the project doctrine
    requires conda envs per project folder."""
    env = os.environ.get("CONDA_DEFAULT_ENV")
    if env:
        return ("pass", f"Conda env active: {env}", None)
    return (
        "warn",
        "No conda env active (CONDA_DEFAULT_ENV unset)",
        "Activate the project env: "
        "`source /scratch/vsetlur/anaconda3/etc/profile.d/conda.sh && "
        "conda activate research-os`",
    )


def _repo_root() -> Path:
    """Best-effort: the repo root where pyproject.toml + CITATION.cff live.

    We walk up from the installed `research_os` package's `__file__`. For
    a wheel install this returns site-packages, where the consistency
    check will simply skip (files absent). For an editable / source
    install, this hits the real repo root.
    """
    here = Path(__file__).resolve()
    for p in (here.parent, *here.parents):
        if (p / "pyproject.toml").exists() and (p / "CITATION.cff").exists():
            return p
    # Fallback: cwd. The consistency check will fail with a helpful
    # message if the files aren't there.
    return Path.cwd()


def _read_version_pyproject(root: Path) -> Optional[str]:
    pp = root / "pyproject.toml"
    if not pp.exists():
        return None
    for line in pp.read_text(encoding="utf-8").splitlines():
        m = re.match(r'^version\s*=\s*"([^"]+)"', line.strip())
        if m:
            return m.group(1)
    return None


def _read_version_init() -> Optional[str]:
    try:
        from research_os import __version__
        return __version__
    except Exception:
        return None


def _read_version_citation(root: Path) -> Optional[str]:
    cf = root / "CITATION.cff"
    if not cf.exists():
        return None
    for line in cf.read_text(encoding="utf-8").splitlines():
        m = re.match(r'^version\s*:\s*(\S+)', line.strip())
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return None


def check_version_consistency(root: Path | None = None) -> CheckResult:
    """pyproject.toml + __init__.py + CITATION.cff must agree."""
    root = root or _repo_root()
    v_pp = _read_version_pyproject(root)
    v_init = _read_version_init()
    v_cff = _read_version_citation(root)

    parts = [f"pyproject={v_pp}", f"__init__={v_init}", f"CITATION={v_cff}"]
    available = [v for v in (v_pp, v_init, v_cff) if v]
    if not available:
        return (
            "warn",
            "Could not read any version files (likely a wheel install)",
            None,
        )
    if len(set(available)) == 1 and v_pp and v_init and v_cff:
        return ("pass", f"All three agree on v{v_pp}", None)
    if len(set(available)) == 1:
        # Partial files but they all agree — still pass.
        return ("pass", f"Available versions agree on v{available[0]}", None)
    return (
        "fail",
        "Version mismatch across files: " + ", ".join(parts),
        "Reconcile pyproject.toml, src/research_os/__init__.py, and "
        "CITATION.cff to the same version string.",
    )


# Known in-tree (bundled) packs. Kept in sync with server._discover_packs_once.
BUNDLED_PACKS = (
    "humanities",
    "qualitative",
    "theory_math",
    "wet_lab",
    "engineering",
)


def check_in_tree_packs_registered() -> CheckResult:
    """All 5 bundled packs should be importable + return a PackRegistration."""
    missing: list[str] = []
    broken: list[tuple[str, str]] = []
    for name in BUNDLED_PACKS:
        mod_name = f"research_os_{name}"
        try:
            import importlib
            mod = importlib.import_module(mod_name)
        except Exception as exc:
            missing.append(f"{name} (import: {exc})")
            continue
        reg_fn = getattr(mod, "register", None)
        if reg_fn is None:
            broken.append((name, "no register() function"))
            continue
        try:
            reg = reg_fn()
        except Exception as exc:
            broken.append((name, f"register() raised: {exc}"))
            continue
        if not getattr(reg, "name", None):
            broken.append((name, "register() returned object without .name"))
    if not missing and not broken:
        return (
            "pass",
            f"All {len(BUNDLED_PACKS)} in-tree packs register cleanly",
            None,
        )
    if missing:
        return (
            "fail",
            f"In-tree packs missing: {', '.join(missing)}",
            "Reinstall the wheel: `pip install -e .[all_packs]`",
        )
    detail = ", ".join(f"{n} ({why})" for n, why in broken)
    return (
        "fail",
        f"In-tree packs failed to register: {detail}",
        "Check pack register() implementations.",
    )


def check_external_pack_entrypoints() -> CheckResult:
    """Enumerate `research_os.protocol_pack` (and the spec'd `research_os.packs`)
    entry points; report counts. Zero is fine — most users have none.
    """
    try:
        from importlib.metadata import entry_points
    except ImportError:
        return ("warn", "importlib.metadata unavailable", None)
    eps = entry_points()
    selected: list[str] = []
    for group in ("research_os.protocol_pack", "research_os.packs"):
        try:
            if hasattr(eps, "select"):
                selected.extend(ep.name for ep in eps.select(group=group))
            else:  # pragma: no cover — py<3.10 fallback
                selected.extend(ep.name for ep in eps.get(group, []))
        except Exception:
            continue
    if not selected:
        return ("pass", "No external packs installed (this is fine)", None)
    return (
        "pass",
        f"External packs registered ({len(selected)}): {', '.join(sorted(set(selected)))}",
        None,
    )


def _embedding_paths() -> tuple[Path, Path]:
    """Locate the compiled protocol bundle + embeddings under the package."""
    here = Path(__file__).resolve().parent
    protocols = here / "protocols"
    return (protocols / "_protocols.bundle",
            protocols / "_embeddings.npz")


def check_embeddings_fresh(
    *, embeddings: Path | None = None, router_index: Path | None = None,
) -> CheckResult:
    """The compiled bundle + embeddings must be present and mutually fresh.

    P1: routing/gates/preconditions load from ``_protocols.bundle``; the
    semantic router loads ``_embeddings.npz``. Both are checked-in build
    artefacts. The ``router_index`` kwarg is kept for signature back-compat
    but now points at the bundle.
    """
    bundle_default, emb_default = _embedding_paths()
    embeddings = embeddings or emb_default
    bundle = router_index or bundle_default
    if not bundle.exists():
        return (
            "warn",
            f"Compiled protocol bundle missing: {bundle}",
            "Build it: `python scripts/build_protocols.py`.",
        )
    if not embeddings.exists():
        return (
            "warn",
            "Pre-built embeddings missing (semantic router will fall back to "
            "trigger-substring matching)",
            "Run the embeddings build step or `pip install research-os[semantic]`.",
        )
    bundle_mtime = bundle.stat().st_mtime
    if embeddings.stat().st_mtime < bundle_mtime:
        return (
            "warn",
            "Embeddings are STALE: the protocol bundle is newer than the "
            "embeddings",
            "Rebuild embeddings: `python scripts/build_embeddings.py` "
            "(see docs/RELEASING.md).",
        )
    return ("pass", "Protocol bundle + embeddings present and mutually fresh", None)


def check_typst_on_path() -> CheckResult:
    """`typst` CLI is required for poster + PDF synthesis."""
    if shutil.which("typst"):
        return ("pass", "typst found on PATH", None)
    return (
        "warn",
        "typst not on PATH (poster + Typst PDF synthesis unavailable)",
        "Install Typst: https://github.com/typst/typst#installation",
    )


def check_chromium_on_path() -> CheckResult:
    """Optional: headless Chromium for the print-stylesheet audit."""
    for binary in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        if shutil.which(binary):
            return ("pass", f"Chromium found on PATH ({binary})", None)
    return (
        "warn",
        "No Chromium on PATH (print-stylesheet audit unavailable)",
        "Install Chromium or set `pyppeteer` to download its own binary.",
    )


def check_optional_deps(*, workspace: Path | None = None) -> CheckResult:
    """If `synthesis.interactive_figures` is on, `pyvis` should be importable."""
    if workspace is None:
        return ("pass", "No workspace; skipping optional-dep check", None)
    cfg = workspace / "inputs" / "researcher_config.yaml"
    if not cfg.exists():
        return ("pass", "No researcher_config.yaml; skipping optional-dep check", None)
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError as exc:
        return ("warn", f"Couldn't read researcher_config.yaml: {exc}", None)
    # Cheap inline parse: look for "interactive_figures: true" in the
    # synthesis block. (ruamel/PyYAML would be heavier than needed here
    # and we deliberately avoid making the doctor import the whole
    # config plumbing.)
    in_synthesis = False
    interactive = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith("synthesis:"):
            in_synthesis = True
            continue
        # Leave the block when we hit another top-level key.
        if in_synthesis and line and not line.startswith((" ", "\t")):
            in_synthesis = False
        if in_synthesis and "interactive_figures" in line:
            m = re.search(r"interactive_figures\s*:\s*(\S+)", line)
            if m and m.group(1).lower() in ("true", "yes", "on", "1"):
                interactive = True
    if not interactive:
        return ("pass", "interactive_figures disabled; no extra deps required", None)
    try:
        import pyvis  # noqa: F401
        return ("pass", "interactive_figures on; pyvis is importable", None)
    except ImportError:
        return (
            "warn",
            "interactive_figures is on but `pyvis` is not installed",
            "`pip install research-os[interactive_figures]`",
        )


# IDE → primary config file used by `research-os ide list`. Local copy so
# the doctor can be exercised in isolation without importing collab (which
# pulls in the whole project_ops surface).
_IDE_PRIMARY: dict[str, str] = {
    "claude":      ".claude/mcp.json",
    "cursor":      ".cursor/mcp.json",
    "vscode":      ".vscode/mcp.json",
    "antigravity": ".antigravity/mcp.json",
    "opencode":    "opencode.json",
    "windsurf":    ".windsurfrules",
    "continue":    ".continuerules",
    "aider":       ".aider.conf.yml",
}


def _declared_ides(workspace: Path) -> list[str]:
    """Which IDEs are declared by the workspace? We consider an IDE
    'declared' if its primary config file exists on disk OR if it's
    referenced in the workspace state under ``ides``."""
    declared: set[str] = set()
    for ide, primary in _IDE_PRIMARY.items():
        if (workspace / primary).exists():
            declared.add(ide)
    state_file = workspace / ".os_state" / "state.json"
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            for ide in data.get("ides", []) or []:
                if ide in _IDE_PRIMARY:
                    declared.add(ide)
        except (OSError, json.JSONDecodeError):
            pass
    return sorted(declared)


def check_mcp_configs_wired(*, workspace: Path | None = None) -> CheckResult:
    """Each declared IDE has its primary MCP config file on disk AND
    (for JSON-shaped configs) the file parses as valid JSON. A file
    that exists but contains malformed JSON is treated as a failure —
    silently passing on a corrupt config defeats the whole point of
    the doctor."""
    if workspace is None:
        return ("pass", "No workspace; skipping MCP wiring check", None)
    declared = _declared_ides(workspace)
    if not declared:
        return ("warn", "No AI IDE config detected in this workspace",
                "`research-os ide add claude` (or your IDE of choice).")
    missing: list[str] = []
    invalid: list[tuple[str, str]] = []
    for ide in declared:
        primary = workspace / _IDE_PRIMARY[ide]
        if not primary.exists():
            missing.append(ide)
            continue
        # JSON-shaped IDE configs: validate that they actually parse.
        if primary.suffix == ".json" or primary.name.endswith("mcp.json"):
            try:
                json.loads(primary.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                invalid.append((ide, str(exc).splitlines()[0][:120]))
    if missing:
        return (
            "fail",
            f"Declared IDEs missing config file: {', '.join(missing)}",
            f"Re-wire: `research-os ide add {' '.join(missing)}`",
        )
    if invalid:
        detail = ", ".join(f"{ide} ({why})" for ide, why in invalid)
        bad = " ".join(ide for ide, _ in invalid)
        return (
            "fail",
            f"Declared IDE configs are invalid JSON: {detail}",
            f"Repair the JSON or re-wire: `research-os ide add {bad}`",
        )
    return ("pass", f"All declared IDEs wired ({', '.join(declared)})", None)


def check_mcp_json_validity(*, workspace: Path | None = None) -> CheckResult:
    """For each declared IDE config file shaped like JSON, open it,
    parse it, drill into ``mcpServers.research-os.command`` (or the
    common variants ``mcp_servers``/``servers``), and verify the
    command is actually on PATH. Catches "everything looked fine"
    failure modes where the JSON is malformed, the server entry was
    renamed, or the command was uninstalled."""
    if workspace is None:
        return ("pass", "No workspace; skipping MCP JSON check", None)
    declared = _declared_ides(workspace)
    if not declared:
        return ("pass", "No declared IDEs; skipping MCP JSON check", None)
    problems: list[str] = []
    checked = 0
    for ide in declared:
        primary = workspace / _IDE_PRIMARY[ide]
        if not primary.exists():
            # `check_mcp_configs_wired` already reports this.
            continue
        if primary.suffix != ".json" and not primary.name.endswith("mcp.json"):
            # YAML / RC-style configs aren't in scope here.
            continue
        checked += 1
        try:
            data = json.loads(primary.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(
                f"{ide}: JSON parse error: {str(exc).splitlines()[0][:80]}"
            )
            continue
        servers = None
        if isinstance(data, dict):
            for key in ("mcpServers", "mcp_servers", "servers"):
                cand = data.get(key)
                if isinstance(cand, dict):
                    servers = cand
                    break
        if not servers:
            problems.append(f"{ide}: no mcpServers/servers block found")
            continue
        # Look for any research-os-shaped entry (the canonical name is
        # `research-os` but historical configs used `research_os`).
        entry = None
        for cand in ("research-os", "research_os", "researchos"):
            if isinstance(servers.get(cand), dict):
                entry = servers[cand]
                break
        if entry is None:
            problems.append(
                f"{ide}: no research-os entry in {key} (keys: "
                f"{', '.join(sorted(servers)[:3])})"
            )
            continue
        cmd = entry.get("command")
        if not cmd or not isinstance(cmd, str):
            problems.append(f"{ide}: research-os entry has no `command`")
            continue
        if not shutil.which(cmd):
            problems.append(f"{ide}: command `{cmd}` not on PATH")
    if not checked:
        return ("pass", "No JSON-shaped IDE configs to validate", None)
    if problems:
        return (
            "fail",
            f"MCP JSON wiring issues: {'; '.join(problems[:5])}",
            "Re-wire with `research-os ide add <ide>` or fix the JSON by hand.",
        )
    return ("pass", f"MCP JSON wiring valid in {checked} IDE config(s)", None)


def check_config_perms(*, workspace: Path | None = None) -> CheckResult:
    """``inputs/researcher_config.yaml`` may contain author identity /
    API keys / project secrets. Warn if it is world-readable (mode
    bits ``& 0o077 != 0``) — W17 enforces ``chmod 600`` on the file;
    this check verifies the chmod actually stuck."""
    if workspace is None:
        return ("pass", "No workspace; skipping config-perm check", None)
    cfg = workspace / "inputs" / "researcher_config.yaml"
    if not cfg.exists():
        return ("pass", "No researcher_config.yaml; nothing to chmod", None)
    try:
        mode = cfg.stat().st_mode & 0o777
    except OSError as exc:
        return ("warn", f"Couldn't stat researcher_config.yaml: {exc}", None)
    if mode & 0o077:
        return (
            "warn",
            f"researcher_config.yaml is mode {oct(mode)[2:]} (group/other readable)",
            f"`chmod 600 {cfg}` to restrict to the owner.",
        )
    return ("pass", f"researcher_config.yaml mode is {oct(mode)[2:]} (owner-only)",
            None)


def check_state_ledger_parses(*, workspace: Path | None = None) -> CheckResult:
    """``.os_state/state_ledger.json`` is the run history. A corrupt
    ledger silently breaks ``research-os status`` and the audit
    pipeline — warn if it exists but does not parse as JSON."""
    if workspace is None:
        return ("pass", "No workspace; skipping ledger-parse check", None)
    ledger = workspace / ".os_state" / "state_ledger.json"
    if not ledger.exists():
        return ("pass", "No state_ledger.json yet (fresh workspace)", None)
    try:
        json.loads(ledger.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (
            "warn",
            f"state_ledger.json is corrupt: {str(exc).splitlines()[0][:120]}",
            "Back it up and delete `.os_state/state_ledger.json` — the next "
            "tool run will recreate a clean one.",
        )
    return ("pass", "state_ledger.json parses cleanly", None)


def check_workspace_writable(*, workspace: Path | None = None) -> CheckResult:
    """Drop a probe file under ``workspace/`` and remove it — catches
    read-only mounts (NFS EROFS) and permission misconfigurations
    that ``check_disk_space`` does not surface."""
    if workspace is None:
        return ("pass", "No workspace; skipping writable check", None)
    ws_dir = workspace / "workspace"
    if not ws_dir.exists():
        try:
            ws_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return (
                "warn",
                f"Could not create workspace/ directory: {exc}",
                "Check the parent directory's permissions and mount options.",
            )
    probe = ws_dir / ".doctor_probe"
    try:
        probe.write_text("doctor probe — safe to delete\n", encoding="utf-8")
    except OSError as exc:
        return (
            "warn",
            f"workspace/ is not writable: {exc}",
            "Check filesystem mount options (EROFS?) or directory permissions.",
        )
    try:
        probe.unlink()
    except OSError:
        # Wrote but couldn't unlink — still effectively writable.
        pass
    return ("pass", "workspace/ is writable", None)


def check_env_var_consistency(*, workspace: Path | None = None) -> CheckResult:
    """If ``RESEARCH_OS_WORKSPACE`` is exported, it must point at the
    same directory the doctor is operating on — otherwise tools the
    user runs interactively will silently act on a different
    workspace than the doctor reports on."""
    if workspace is None:
        return ("pass", "No workspace; skipping env-var consistency check", None)
    env_val = os.environ.get("RESEARCH_OS_WORKSPACE")
    if not env_val:
        return ("pass", "RESEARCH_OS_WORKSPACE not set (default lookup applies)",
                None)
    try:
        env_resolved = Path(env_val).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        return ("warn", f"RESEARCH_OS_WORKSPACE is unparseable: {exc}", None)
    ws_resolved = workspace.resolve()
    if env_resolved == ws_resolved:
        return ("pass", f"RESEARCH_OS_WORKSPACE matches workspace ({ws_resolved})",
                None)
    return (
        "warn",
        f"RESEARCH_OS_WORKSPACE={env_resolved} does not match active workspace "
        f"{ws_resolved}",
        f"`unset RESEARCH_OS_WORKSPACE` or `export RESEARCH_OS_WORKSPACE={ws_resolved}`.",
    )


def check_typst_compiles_fixture() -> CheckResult:
    """``shutil.which('typst')`` only checks PATH — a broken / version-
    mismatched binary lies. Compile a tiny known-good fixture to be
    sure the typst on PATH actually works end-to-end."""
    if not shutil.which("typst"):
        return ("pass", "typst not on PATH; skipping compile probe", None)
    import tempfile
    fixture = "= Doctor probe\n\nResearch OS doctor compile test.\n"
    with tempfile.TemporaryDirectory(prefix="ros-doctor-typst-") as tmp:
        src = Path(tmp) / "probe.typ"
        out = Path(tmp) / "probe.pdf"
        src.write_text(fixture, encoding="utf-8")
        try:
            result = subprocess.run(
                ["typst", "compile", str(src), str(out)],
                capture_output=True, text=True, timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return (
                "warn",
                f"typst compile probe failed to run: {exc}",
                "Reinstall typst: https://github.com/typst/typst#installation",
            )
        if result.returncode != 0 or not out.exists():
            stderr = (result.stderr or "").splitlines()
            first = stderr[0] if stderr else f"exit {result.returncode}"
            return (
                "warn",
                f"typst on PATH but compile failed: {first[:120]}",
                "Reinstall typst or check the version (>= 0.10 recommended).",
            )
    return ("pass", "typst compiles a known-good fixture", None)


def check_workspace_integrity(*, workspace: Path | None = None) -> CheckResult:
    """Look for orphan figures, unresolved BLOCK gates.

    None of these are catastrophic on their own — a workspace that's
    mid-pipeline naturally accumulates partial state — so we collect
    findings and report them as a single ``warn`` (or ``pass``).
    """
    if workspace is None:
        return ("pass", "No workspace; skipping integrity check", None)

    findings: list[str] = []

    # Orphan figures: figures/*.png whose owning step directory is gone.
    figures_root = workspace / "workspace" / "figures"
    if figures_root.exists():
        steps_root = workspace / "workspace"
        for fig in figures_root.glob("*.png"):
            owner_stem = fig.stem.split("__")[0] if "__" in fig.stem else fig.stem
            owner_dir = steps_root / owner_stem
            if not owner_dir.exists() and owner_stem:
                # Don't list every file — keep noise down.
                findings.append(f"orphan figure: {fig.name}")
                if len([f for f in findings if f.startswith("orphan figure:")]) >= 3:
                    findings.append("(+ more orphan figures…)")
                    break

    # (step_summary.yaml was retired in 3.2 — conclusions.md is the source
    # of truth, so there is no derived sidecar to go stale anymore.)

    # Unresolved BLOCK gates in the audit ledger.
    audit_log = workspace / ".audit_findings.jsonl"
    if audit_log.exists():
        try:
            blocks = 0
            for line in audit_log.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                level = (obj.get("level") or obj.get("severity") or "").upper()
                resolved = obj.get("resolved", False)
                if level == "BLOCK" and not resolved:
                    blocks += 1
            if blocks:
                findings.append(f"{blocks} unresolved BLOCK gate(s) in audit ledger")
        except OSError:
            pass

    if not findings:
        return ("pass", "Workspace integrity OK", None)
    return (
        "warn",
        f"Workspace has {len(findings)} integrity finding(s): "
        + "; ".join(findings[:5]),
        "Inspect the workspace; rerun the offending step or resolve the BLOCK gate.",
    )


def _directory_size_bytes(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def check_disk_space(
    *, workspace: Path | None = None, threshold_gb: float = 5.0,
) -> CheckResult:
    """Warn if the workspace's data + cache size exceeds the threshold."""
    if workspace is None:
        return ("pass", "No workspace; skipping disk-space check", None)
    bytes_used = _directory_size_bytes(workspace)
    gb = bytes_used / (1024 ** 3)
    if gb > threshold_gb:
        return (
            "warn",
            f"Workspace size {gb:.1f} GB exceeds {threshold_gb:.1f} GB threshold",
            "Consider archiving old `.versions/` snapshots or moving heavy "
            "raw data out of `inputs/raw_data/` to external storage.",
        )
    return ("pass", f"Workspace size {gb:.2f} GB (under {threshold_gb:.1f} GB)", None)


def check_git_clean(*, workspace: Path | None = None) -> CheckResult:
    """Warn if the workspace's git tree is dirty. Skip silently for
    non-git workspaces (many researchers don't `git init` immediately)."""
    if workspace is None:
        return ("pass", "No workspace; skipping git-clean check", None)
    if not (workspace / ".git").exists():
        return ("pass", "Workspace is not a git repo; nothing to check", None)
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ("warn", f"git status failed: {exc}", None)
    if result.returncode != 0:
        return ("warn", f"git status exited {result.returncode}", None)
    dirty = [line for line in result.stdout.splitlines() if line.strip()]
    if not dirty:
        return ("pass", "Git working tree clean", None)
    return (
        "warn",
        f"Git working tree dirty: {len(dirty)} change(s)",
        "Review with `git status`; commit or discard before sharing.",
    )


def check_gitignore_covers_state(*, workspace: Path | None = None) -> CheckResult:
    """`.gitignore` must mention `.os_state/` and `workspace/scratch/` so
    per-run state never pollutes the repo."""
    if workspace is None:
        return ("pass", "No workspace; skipping .gitignore check", None)
    gi = workspace / ".gitignore"
    if not gi.exists():
        return (
            "warn",
            "No .gitignore in workspace",
            "Copy from templates/.gitignore or run `research-os init --force`.",
        )
    try:
        text = gi.read_text(encoding="utf-8")
    except OSError as exc:
        return ("warn", f"Couldn't read .gitignore: {exc}", None)
    # .os_state/ must be ignored as a WHOLE tree, not just a subdir like
    # .os_state/cache/ (a plain substring check would pass on the old buggy
    # generator that only ignored subdirs and still committed run history).
    lines = {ln.strip() for ln in text.splitlines()}
    state_ok = ".os_state/" in lines or ".os_state" in lines
    # Accept the anchored top-level form (workspace/scratch/) or the
    # UNANCHORED form (scratch/ — which also covers the per-step copies under
    # workspace/<NN_step>/scratch/). The unanchored form is what the current
    # generator emits; the anchored form is accepted for older projects.
    # NOTE: `workspace/scratch/` is the ONE canonical throwaway dir — there is
    # no `workspace/cache/`. Older projects that ignored `cache/` are still
    # accepted here (back-compat), but new ones use scratch only.
    scratch_ok = (
        "scratch/" in lines or "scratch" in lines
        or "workspace/scratch" in text
        # back-compat: legacy projects may still ignore a cache/ dir.
        or "cache/" in lines or "workspace/cache" in text
    )
    logs_ok = (
        "logs/" in lines or "logs" in lines
        or "workspace/logs/" in lines or "workspace/logs" in lines
    )
    missing = []
    if not state_ok:
        missing.append(".os_state/ (the whole tree, not just a subdir)")
    if not scratch_ok:
        missing.append("scratch/ (unanchored, or workspace/scratch/)")
    if not logs_ok:
        missing.append("logs/ (unanchored, or workspace/logs/)")
    if missing:
        return (
            "warn",
            f".gitignore missing entries: {', '.join(missing)}",
            "Append the missing lines to .gitignore.",
        )
    return ("pass", ".gitignore covers .os_state/ and workspace/scratch/", None)


# ── Orchestration ─────────────────────────────────────────────────────


def _find_workspace_root(start: Path | None = None) -> Optional[Path]:
    p = (start or Path.cwd()).resolve()
    for parent in (p, *p.parents):
        if (parent / ".os_state").exists():
            return parent
    return None


_INSTALL_CHECKS: list[tuple[str, Callable[[], CheckResult]]] = [
    ("python_version", check_python_version),
    ("conda_active", check_conda_active),
    ("version_consistency", lambda: check_version_consistency()),
    ("in_tree_packs_registered", check_in_tree_packs_registered),
    ("external_pack_entrypoints", check_external_pack_entrypoints),
    ("embeddings_fresh", lambda: check_embeddings_fresh()),
    ("typst_on_path", check_typst_on_path),
    ("typst_compiles_fixture", check_typst_compiles_fixture),
    ("chromium_on_path", check_chromium_on_path),
]


def _run_workspace_checks(report: DoctorRun, workspace: Path) -> None:
    pairs: list[tuple[str, Callable[[], CheckResult]]] = [
        ("optional_deps", lambda: check_optional_deps(workspace=workspace)),
        ("mcp_configs_wired", lambda: check_mcp_configs_wired(workspace=workspace)),
        ("mcp_json_validity", lambda: check_mcp_json_validity(workspace=workspace)),
        ("config_perms", lambda: check_config_perms(workspace=workspace)),
        ("state_ledger_parses",
         lambda: check_state_ledger_parses(workspace=workspace)),
        ("workspace_writable",
         lambda: check_workspace_writable(workspace=workspace)),
        ("env_var_consistency",
         lambda: check_env_var_consistency(workspace=workspace)),
        ("workspace_integrity",
         lambda: check_workspace_integrity(workspace=workspace)),
        ("disk_space", lambda: check_disk_space(workspace=workspace)),
        ("git_clean", lambda: check_git_clean(workspace=workspace)),
        ("gitignore_covers_state",
         lambda: check_gitignore_covers_state(workspace=workspace)),
    ]
    for name, fn in pairs:
        try:
            report.add(name, fn(), scope="workspace")
        except Exception as exc:
            report.add(name, ("fail", f"check raised: {exc}", None),
                       scope="workspace")


def run_all_checks(
    *, workspace_only: bool = False, workspace: Path | None = None,
) -> DoctorRun:
    """Run the doctor checks and return a populated DoctorRun."""
    report = DoctorRun()
    ws = workspace if workspace is not None else _find_workspace_root()
    if not workspace_only:
        for name, fn in _INSTALL_CHECKS:
            try:
                report.add(name, fn(), scope="install")
            except Exception as exc:
                report.add(name, ("fail", f"check raised: {exc}", None),
                           scope="install")
    if ws is not None:
        _run_workspace_checks(report, ws)
    elif workspace_only:
        report.add(
            "workspace_present",
            ("fail",
             "--workspace-only was passed but no .os_state was found above CWD",
             "cd into a Research OS workspace or drop --workspace-only."),
            scope="workspace",
        )
    return report


# ── Human-readable rendering ──────────────────────────────────────────


_ICON_UTF8 = {"pass": "✓", "warn": "⚠", "fail": "✗"}
_ICON_ASCII = {"pass": "[+]", "warn": "[!]", "fail": "[x]"}
_COLOR = {"pass": _Style.GREEN, "warn": _Style.YELLOW, "fail": _Style.RED}


def _icons() -> dict[str, str]:
    """Pick glyphs at render time so the stdout encoding is read when printed."""
    return _ICON_UTF8 if _supports_utf8() else _ICON_ASCII


def _render_human(report: DoctorRun, *, verbose: bool, color: bool) -> str:
    lines: list[str] = []
    icons = _icons()
    rule_char = "─" if _supports_utf8() else "-"
    lines.append("")
    title = _c("research-os doctor", _Style.BOLD, color)
    lines.append(f"  {title}")
    lines.append(f"  {_c(rule_char * 60, _Style.GREY, color)}")

    last_scope = None
    for c in report.checks:
        if c.scope != last_scope:
            header = "Install checks" if c.scope == "install" else "Workspace checks"
            lines.append("")
            lines.append(f"  {_c(header, _Style.BOLD, color)}")
            last_scope = c.scope
        icon = _c(icons[c.status], _COLOR[c.status], color)
        name = c.name.ljust(28)
        lines.append(f"    {icon} {name} {c.message}")
        if c.fix and (verbose or c.status != "pass"):
            lines.append(f"        {_c('→ fix:', _Style.DIM, color)} {c.fix}")

    s = report.summary
    lines.append("")
    summary = (
        f"{_c(str(s['pass']) + ' pass', _Style.GREEN, color)},  "
        f"{_c(str(s['warn']) + ' warn', _Style.YELLOW, color)},  "
        f"{_c(str(s['fail']) + ' fail', _Style.RED, color)}"
    )
    lines.append(f"  Summary: {summary}")
    if report.exit_code == 0:
        lines.append(f"  {_c('All clear.', _Style.GREEN, color)}")
    elif report.exit_code == 1:
        lines.append(f"  {_c('OK with warnings.', _Style.YELLOW, color)}")
    else:
        lines.append(f"  {_c('FAILURES present — fix before shipping.', _Style.RED, color)}")
    lines.append(
        f"  {_c('Exit code policy:', _Style.GREY, color)} 0=all-pass, 1=warn-only, 2=fail."
    )
    lines.append("")
    return "\n".join(lines)


# ── CLI entrypoint ────────────────────────────────────────────────────


def cmd_doctor(args: argparse.Namespace) -> int:
    """`research-os doctor` — print a health report and return exit code."""
    workspace = None
    if getattr(args, "workspace", None):
        workspace = Path(args.workspace).resolve()
    report = run_all_checks(
        workspace_only=getattr(args, "workspace_only", False),
        workspace=workspace,
    )
    if getattr(args, "json", False):
        print(json.dumps(report.to_json(), indent=2, sort_keys=True))
    else:
        color = _supports_color() and not getattr(args, "no_color", False)
        print(_render_human(report, verbose=getattr(args, "verbose", False),
                            color=color))
    return report.exit_code
