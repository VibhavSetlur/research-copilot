#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""Research OS CLI.

Four commands, by design:

    research-os init [dir] [--name X] [--ide all|cursor|claude|...]
        Scaffold a Research OS workspace. Interactive by default; pass
        ``--yes`` (or pipe stdin) for a non-interactive one-shot.

    research-os ide add|remove|list <name>
        Wire / unwire / inspect AI IDE MCP configs without re-running
        ``init`` (so existing data + state is never touched).

    research-os start [--workspace .]
        Run the MCP server. Your AI IDE connects to this.

    research-os doctor [--verbose|--workspace-only|--json]
        Diagnose install + workspace health (python version, conda env,
        version consistency, pack registration, embeddings freshness,
        IDE wiring, disk usage, git cleanliness, etc.). Returns exit
        code 0 (clean), 1 (warnings), or 2 (failures).

    research-os completion bash|zsh|fish
        Print a sourceable shell-completion script. Install with
        ``eval "$(research-os completion zsh)"`` (or your shell's
        equivalent) in your shell rc file.

All real research work happens by talking to the AI in the IDE.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from research_os import __version__
from research_os.project_ops import scaffold_minimal_workspace
from research_os.utils.asset_manager import AssetManager  # noqa: F401  (re-export)

VALID_IDES = (
    "cursor", "claude", "antigravity", "opencode", "vscode",
    "windsurf", "continue", "aider",
)

# Shell-completion choice list for the `init --ide` flag.
# Includes the two sentinels ("all", "none") so argcomplete can suggest them.
IDE_CHOICES_FOR_COMPLETION = (*VALID_IDES, "auto", "all", "none")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

from research_os._cli.term import _check, _cross, _warn_glyph
from research_os._cli.term import _supports_utf8 as _supports_utf8


def _detect_ide() -> list[str]:
    """Best-effort detect the SINGLE AI IDE the user is running, from the
    environment. Returns [ide] when confident, else [] (caller then asks /
    skips rather than wiring all of them).

    We never guess more than one — wiring every IDE (the old default) litters
    a project with config for tools the user doesn't have. Detection signals,
    in priority order: explicit env hint, the host editor's env vars, and
    well-known binaries on PATH.
    """
    import os
    import shutil

    env = os.environ
    # 1. Explicit override (CI / scripted / agent can set this).
    forced = (env.get("RESEARCH_OS_IDE") or "").strip().lower()
    if forced in VALID_IDES:
        return [forced]

    # 2. Host-editor environment fingerprints (set by the editor itself).
    term_prog = (env.get("TERM_PROGRAM") or "").lower()
    if "cursor" in term_prog or env.get("CURSOR_TRACE_ID"):
        return ["cursor"]
    if "windsurf" in term_prog or env.get("WINDSURF_ENV"):
        return ["windsurf"]
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return ["claude"]
    if "vscode" in term_prog or env.get("VSCODE_PID") or env.get("VSCODE_GIT_IPC_HANDLE"):
        return ["vscode"]

    # 3. A single well-known binary on PATH (only decisive when exactly one).
    bins = {
        "cursor": "cursor",
        "windsurf": "windsurf",
        "claude": "claude",
        "aider": "aider",
        "opencode": "opencode",
    }
    found = [ide for ide, b in bins.items() if shutil.which(b)]
    if len(found) == 1:
        return found
    return []


def _ide_choice(args_ide: str | None) -> list[str]:
    # 'auto' (the new default) → detect the user's single IDE; if detection is
    # inconclusive, return [] so we DON'T wire all 8 (the old footgun). The
    # caller surfaces a hint telling the user to re-run with --ide <name>.
    if args_ide is None or args_ide.strip().lower() == "auto":
        return _detect_ide()
    if args_ide == "all":
        return list(VALID_IDES)
    if args_ide.strip().lower() == "none":
        # Explicit opt-out: skip all IDE wiring. Caller passes the empty
        # list, which downstream code treats as "no MCP config, no .ide
        # files, no IDE-specific docs".
        return []
    parts = [p.strip() for p in args_ide.split(",") if p.strip()]
    invalid = [p for p in parts if p not in VALID_IDES]
    if invalid:
        valid_names = ", ".join(VALID_IDES)
        print(
            f"  {_cross()} Unknown IDE(s): {', '.join(invalid)}.\n"
            f"    Valid choices: {valid_names}, all, none.\n"
            f"    Use --ide none to skip IDE wiring entirely."
        )
        sys.exit(2)
    return parts


def _detect_existing_data(target_dir: Path) -> list[Path]:
    found: list[Path] = []
    if not target_dir.exists():
        return found
    for pattern in ("*.csv", "*.tsv", "*.json", "*.jsonl", "*.xlsx", "*.xls",
                    "*.parquet", "*.feather", "*.pdf"):
        found.extend(p for p in list(target_dir.glob(pattern))[:5]
                     if not p.is_symlink())
    return found


def _link_inputs(target_dir: Path, sources: list[Path]) -> list[str]:
    linked: list[str] = []
    inputs_raw = target_dir / "inputs" / "raw_data"
    inputs_raw.mkdir(parents=True, exist_ok=True)
    for src in sources:
        link = inputs_raw / src.name
        if link.exists():
            continue
        try:
            link.symlink_to(src.absolute())
            linked.append(src.name)
        except OSError:
            try:
                shutil.copy2(src, link)
                linked.append(src.name)
            except OSError as exc:
                print(f"  {_warn_glyph()}  Could not link {src.name}: {exc}")
    return linked


def _save_linked_meta(target_dir: Path, linked: list[str]) -> None:
    try:
        from research_os.project_ops import load_state, save_state
        state = load_state(target_dir)
        linked_meta = state.setdefault("linked_external_data", [])
        for name in linked:
            if name not in linked_meta:
                linked_meta.append(name)
        save_state(target_dir, state)
    except Exception:
        pass


def _count_scaffold(target_dir: Path) -> dict:
    files = 0
    dirs = 0
    for p in target_dir.rglob("*"):
        if p.is_dir():
            dirs += 1
        elif p.is_file():
            files += 1
    return {"files": files, "dirs": dirs}


def _copy_attachments(target_dir: Path, paths: list[Path]) -> list[Path]:
    """Copy attachments into inputs/. PDFs → literature/, anything else → context/.
    Returns the list of destination paths actually written.

    Refuses to copy symlinks whose target escapes the user's home directory —
    a paper.pdf → /etc/passwd trick would otherwise be silently dragged in.
    """
    from research_os import wizard  # local import to avoid cycle
    from research_os.wizard import IMAGE_EXTENSIONS  # noqa: F401

    lit_dir = target_dir / "inputs" / "literature"
    ctx_dir = target_dir / "inputs" / "context"
    lit_dir.mkdir(parents=True, exist_ok=True)
    ctx_dir.mkdir(parents=True, exist_ok=True)
    home = Path.home().resolve()
    written: list[Path] = []
    for src in paths:
        # Reject symlinks that point outside the user's home directory.
        if src.is_symlink():
            try:
                real_src = src.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                wizard.warn(f"Skipping {src.name}", f"unresolvable symlink: {exc}")
                continue
            if home != real_src and home not in real_src.parents:
                wizard.warn(
                    f"Skipping {src.name}",
                    f"symlink target escapes home directory ({real_src})",
                )
                continue

        suffix = src.suffix.lower()
        dest_dir = lit_dir if suffix == ".pdf" else ctx_dir
        dest = dest_dir / src.name
        # Don't clobber.
        if dest.exists() and dest.samefile(src):
            continue
        if dest.exists():
            stem, ext = dest.stem, dest.suffix
            i = 1
            while (dest_dir / f"{stem}_{i}{ext}").exists():
                i += 1
            dest = dest_dir / f"{stem}_{i}{ext}"
        try:
            shutil.copy2(src, dest)
            written.append(dest)
        except OSError as exc:
            print(f"  {_warn_glyph()}  Could not copy {src.name}: {exc}")
    return written


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> None:
    """Scaffold a Research OS workspace. Interactive by default."""
    from research_os import wizard
    if getattr(args, "no_color", False):
        wizard.disable_color()

    # ── --migrate: upgrade an existing project to the v5 config layout ──
    if getattr(args, "migrate", False):
        # Resolve target root with the same logic as the non-interactive path.
        if getattr(args, "directory", None):
            migrate_root = Path(os.path.expanduser(args.directory)).resolve()
        else:
            migrate_root = Path.cwd().resolve()

        from research_os.config.migrate_config import migrate_project_to_v5
        summary = migrate_project_to_v5(migrate_root)

        print(f"  research-os migrate → v5 config written for: {migrate_root}")
        print(f"    project config : {summary['project_config']}")
        print(f"    user profile   : {summary['user_profile']}")
        if summary["migrated_keys"]:
            print(f"    migrated keys  : {', '.join(summary['migrated_keys'])}")
        else:
            print("    migrated keys  : (none — old config absent; v5 defaults written)")
        return

    interactive = wizard.should_run_wizard(args)

    if interactive:
        try:
            result = wizard.run_wizard(args)
            if not wizard.show_summary_and_confirm(result):
                print()
                print(f"  {wizard._C.YELLOW}Cancelled — no changes made.{wizard._C.RESET}")
                sys.exit(0)
        except (KeyboardInterrupt, EOFError):
            # Ctrl+C / Ctrl+D mid-wizard → clean exit, never a raw traceback.
            print()
            print(f"  {wizard._C.YELLOW}Cancelled — no changes made.{wizard._C.RESET}")
            sys.exit(0)
        _execute(result, run_preflight_repo=args.preflight)
        return

    # ── Non-interactive path (legacy / scripted) ────────────────────────
    if args.name and args.directory is None:
        from research_os.wizard import slugify

        slug = slugify(args.name)
        target_dir = (Path.cwd() / slug).resolve()
        created_new_folder = not target_dir.exists()
        # `--name X` with no directory creates a NESTED slugified subdir, which
        # surprises users who already `mkdir`'d + `cd`'d into their project
        # folder (the docs' own pattern). Say so loudly so the AI/user doesn't
        # `cd` to the wrong place. To scaffold the CURRENT folder instead, pass
        # an explicit `.` (e.g. `research-os init . --name "X"`).
        print(
            f"  {_warn_glyph()} Creating the project in a new subfolder: "
            f"{target_dir}\n"
            f"    (--name without a directory nests under the current folder.) "
            f"To scaffold THIS folder instead, re-run as "
            f"`research-os init . --name \"{args.name}\"`."
        )
    elif args.directory:
        target_dir = Path(os.path.expanduser(args.directory)).resolve()
        created_new_folder = not target_dir.exists()
    else:
        target_dir = Path.cwd().resolve()
        created_new_folder = False

    project_name = args.name or target_dir.name
    already_initialized = (target_dir / ".os_state").exists()
    if already_initialized and not args.force:
        print(f"  {_cross()} Workspace already exists at: {target_dir}")
        print("  Pass --force to re-scaffold (preserves your data and config).")
        sys.exit(1)

    ide_flags = _ide_choice(args.ide)
    # When the default 'auto' couldn't identify a single IDE, DON'T wire all of
    # them (the old footgun). Tell the user exactly how to pick theirs + that a
    # restart is required — MCP config only loads on a fresh IDE/agent session.
    if (args.ide is None or str(args.ide).strip().lower() == "auto") and not ide_flags:
        print(
            f"  {_warn_glyph()} Couldn't auto-detect your AI IDE, so no IDE config was "
            "written (Research OS itself is fully set up).\n"
            "    Wire your IDE with ONE of:\n"
            "      research-os ide add <claude|cursor|vscode|windsurf|...>\n"
            "    then RESTART that IDE / agent session in this project so it "
            "loads the MCP server."
        )
    raw_data_sources = (_detect_existing_data(target_dir)
                        if (target_dir.exists() and not args.force) else [])

    # Multi-question support: take args.questions if given; else fall back
    # to the singular args.question.
    questions = list(getattr(args, "questions", None) or [])
    if args.question and args.question not in questions:
        questions.insert(0, args.question)

    result = wizard.WizardResult(
        target_dir=target_dir,
        project_name=project_name,
        domain=args.domain or "",
        question=questions[0] if questions else (args.question or ""),
        questions=questions,
        ides=ide_flags,
        force=args.force,
        run_verify=True,
        start_server=False,
        create_dir_needed=created_new_folder,
        detected_inputs=raw_data_sources,
        workspace_mode=getattr(args, "workspace_mode", None) or "analysis",
        mcp_scope=getattr(args, "mcp_scope", None) or "workspace",
        wire_hermes=bool(getattr(args, "hermes", None)),
    )
    _execute(result, run_preflight_repo=args.preflight, quiet_banner=True)


def _execute(r, run_preflight_repo: bool = False, quiet_banner: bool = False) -> None:
    """Actually scaffold + post-process. Shared by interactive + non-interactive."""
    from research_os import collab, wizard
    from research_os.verify import verify_workspace, summarize

    target_dir: Path = r.target_dir

    already_initialized = (target_dir / ".os_state").exists()
    if already_initialized and not r.force:
        wizard.fail(f"Workspace already exists: {target_dir}",
                    "Pass --force to re-scaffold (data is preserved).")
        sys.exit(1)

    if not quiet_banner:
        print()
        print(f"  {wizard._C.GREY}{wizard._hr('━')}{wizard._C.RESET}")
        print(f"  {wizard._C.BOLD}Scaffolding workspace…{wizard._C.RESET}")
        print(f"  {wizard._C.GREY}{wizard._hr('━')}{wizard._C.RESET}")
        print()

    # 1. Resolve author identity BEFORE scaffold so we can pass to config.
    author = collab.whoami(target_dir if target_dir.exists() else None)

    # 2. Scaffold.
    researcher_block = {
        "name": getattr(r, "researcher_name", "") or "",
        "email": getattr(r, "researcher_email", "") or "",
        "institution": getattr(r, "researcher_institution", "") or "",
        "orcid": getattr(r, "researcher_orcid", "") or "",
    }
    config_overrides = {
        "project_name": r.project_name,
        "domain": r.domain,
        "research_question": r.question,
        "research_questions": list(getattr(r, "questions", []) or []),
        "authors": [author.as_dict()],
        "api_keys": dict(getattr(r, "api_keys", {}) or {}),
        "model_profile": getattr(r, "model_profile", "medium"),
        "researcher": researcher_block,
    }
    # Wire Step-2 output_types + target_venue into research_goal block.
    _output_types = list(getattr(r, "output_types", None) or [])
    _target_venue = getattr(r, "target_venue", "") or ""
    if _output_types or _target_venue:
        rg: dict = config_overrides.setdefault("research_goal", {})
        if _output_types:
            rg["output_types"] = _output_types
        if _target_venue:
            rg["target_venue"] = _target_venue
    # Workspace mode (analysis | tool_build | exploration). Threaded into
    # config_overrides so init_config stamps it AND the scaffold selects
    # the matching profile. Default analysis keeps the classic surface.
    workspace_mode = getattr(r, "workspace_mode", "analysis") or "analysis"
    if workspace_mode != "analysis":
        config_overrides["workspace"] = {"mode": workspace_mode}
    scaffold_minimal_workspace(
        target_dir,
        r.project_name,
        config_overrides=config_overrides,
        ide_flags=r.ides,
        copy_agents=True,
        mode=workspace_mode,
    )
    wizard.ok("Workspace scaffolded", str(target_dir))

    # 2a. Opt-in cross-project profile save.
    if getattr(r, "save_as_profile", False) and any(researcher_block.values()):
        try:
            from research_os.tools.actions.state.config import (
                load_profile, save_profile,
            )
            profile = load_profile()
            existing_r = profile.get("researcher") if isinstance(profile.get("researcher"), dict) else {}
            existing_r.update({k: v for k, v in researcher_block.items() if v})
            profile["researcher"] = existing_r
            # Persist non-empty api_keys + model_profile too.
            api_keys = config_overrides.get("api_keys") or {}
            if api_keys:
                profile.setdefault("api_keys", {}).update(
                    {k: v for k, v in api_keys.items() if v}
                )
            if config_overrides.get("model_profile"):
                profile["model_profile"] = config_overrides["model_profile"]
            res = save_profile(profile)
            wizard.ok("Saved cross-project profile",
                      f"→ {res.get('profile_path')}")
        except Exception as e:
            wizard.warn("Cross-project profile save failed", str(e))

    # 3. Link any pre-existing input files the user agreed to.
    linked: list[str] = []
    if r.detected_inputs:
        linked = _link_inputs(target_dir, r.detected_inputs)
        if linked:
            _save_linked_meta(target_dir, linked)
            wizard.ok(f"Linked {len(linked)} data file(s)",
                      f"→ inputs/raw_data/  ({', '.join(linked[:3])}{'…' if len(linked) > 3 else ''})")

    # 4. Copy attachments (images, screenshots, PDFs).
    attachment_results = []
    if getattr(r, "pending_attachments", None):
        attachment_results = _copy_attachments(target_dir, r.pending_attachments)
        if attachment_results:
            wizard.ok(f"Copied {len(attachment_results)} attachment(s)",
                      "→ inputs/context | inputs/literature")

    # 5. Save any pasted notes captured during Step 5.
    note_results = []
    if getattr(r, "pending_notes", None):
        from research_os.inputs.paste import save as save_note
        ctx_dir = target_dir / "inputs" / "context"
        for source_hint, blob in r.pending_notes:
            try:
                res = save_note(blob, ctx_dir, source_hint=source_hint)
                note_results.append(res)
            except Exception as e:
                wizard.warn(f"Could not save note ({source_hint})", str(e))
        if note_results:
            wizard.ok(f"Saved {len(note_results)} pasted note(s)", "→ inputs/context/")

    # 6. Download any pasted paper URLs / DOIs / arXiv IDs (with per-paper progress).
    paper_results = []
    if getattr(r, "pending_papers", None):
        from research_os.inputs.papers import fetch_one
        lit_dir = target_dir / "inputs" / "literature"
        total = len(r.pending_papers)
        wizard.info(f"Fetching {total} paper(s) — may take a moment…")
        for i, token in enumerate(r.pending_papers, 1):
            print(f"      {wizard._C.GREY}[{i}/{total}] {token[:60]}…{wizard._C.RESET}", end="", flush=True)
            res = fetch_one(token, lit_dir)
            paper_results.append(res)
            if res.ok:
                size_kb = res.bytes_written / 1024
                print(f"\r      {wizard._C.GREEN}✓{wizard._C.RESET} "
                      f"[{i}/{total}] {token[:60]}  "
                      f"{wizard._C.GREY}→ {res.path.name if res.path else ''} "
                      f"({size_kb:.0f} KB){wizard._C.RESET}")
            else:
                print(f"\r      {wizard._C.YELLOW}✗{wizard._C.RESET} "
                      f"[{i}/{total}] {token[:60]}  "
                      f"{wizard._C.GREY}— {res.error}{wizard._C.RESET}")

    # 7. Smoke check.
    verify_summary = None
    if r.run_verify:
        results = verify_workspace(target_dir, ides=r.ides)
        passed, failed, summary = summarize(results)
        if failed == 0:
            wizard.ok("Smoke check passed", summary)
            verify_summary = summary
        else:
            wizard.warn("Smoke check found issues", summary)
            for name, ok, detail in results:
                if not ok:
                    wizard.fail(f"  · {name}", detail)

    # 8. Optionally run the repo's preflight (dev mode only).
    if run_preflight_repo:
        _run_repo_preflight()

    # 9. Optional: kick off the MCP server in the background.
    if r.start_server:
        _try_start_server(target_dir)

    # 10. Optional: wire Research-OS into Hermes (the self-improving agent
    # layer). Registers the RO MCP server + skill in ~/.hermes/config.yaml,
    # non-destructively and idempotently. Best-effort: a failure here never
    # aborts a successful scaffold.
    if getattr(r, "wire_hermes", False):
        try:
            from research_os import hermes_integration as _hi

            summary = _hi.add()
            wizard.ok(
                "Hermes wired",
                f"server '{summary['server_key']}' {summary['server_action']} "
                f"in {summary['config_path']} — restart Hermes to load it.",
            )
        except Exception as exc:  # noqa: BLE001 - never abort scaffold on this
            wizard.warn(
                "Hermes wiring skipped",
                f"{exc}. Run `research-os hermes add` manually when ready.",
            )

    # NOTE: `CONTRIBUTORS.md` is not created automatically at init time.
    # It only gets written when an action explicitly logs to it (e.g.
    # `research-os ide add ...`, which is a deliberate change to project
    # wiring).

    # 11. Final report.
    stats = _count_scaffold(target_dir)
    wizard.show_done_card(r, stats, verify_summary,
                          note_results=note_results,
                          paper_results=paper_results,
                          attachment_results=attachment_results,
                          author=author)


def _run_repo_preflight() -> None:
    from research_os import wizard
    here = Path(__file__).resolve()
    for parent in (here.parent.parent.parent, *here.parents):
        candidate = parent / "scripts" / "preflight.py"
        if candidate.exists():
            print()
            wizard.info(f"Running repo preflight: {candidate.relative_to(parent)}")
            try:
                rc = subprocess.run(
                    [sys.executable, str(candidate)],
                    cwd=str(parent),
                    timeout=60,
                ).returncode
            except (OSError, subprocess.TimeoutExpired) as e:
                wizard.warn(f"Preflight didn't finish: {e}")
                return
            if rc == 0:
                wizard.ok("Repo preflight passed")
            else:
                wizard.warn(f"Repo preflight exited {rc}")
            return


def _try_start_server(target_dir: Path) -> None:
    from research_os import wizard

    binary = shutil.which("research-os")
    if not binary:
        wizard.warn("research-os not found on PATH",
                    "Skipping server start — open your IDE; it will launch the server.")
        return

    log_path = target_dir / ".os_state" / "server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["RESEARCH_OS_WORKSPACE"] = str(target_dir)
    try:
        with open(log_path, "ab") as logf:
            proc = subprocess.Popen(
                [binary, "start"],
                stdout=logf,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
        wizard.ok(f"MCP server started (PID {proc.pid})",
                  f"logs → {log_path.relative_to(target_dir)}")
    except OSError as e:
        wizard.warn(f"Could not start server: {e}",
                    "Run `research-os start` manually if your IDE doesn't auto-launch it.")


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


def cmd_start(args: argparse.Namespace) -> None:
    from research_os.server import main as server_main

    if args.workspace:
        workspace = Path(args.workspace).resolve()
        if not (workspace / ".os_state").exists():
            print(f"  {_warn_glyph()}  --workspace points at a non-RO directory: {workspace}")
            print("  Run 'research-os init' there first, or omit --workspace.")
            # Launching the server against an un-scaffolded path leaves the AI
            # with no state to boot from — fail fast rather than start broken.
            sys.exit(1)
        sys.argv = [sys.argv[0], "--transport", args.transport,
                    "--workspace", str(workspace)]
    else:
        sys.argv = [sys.argv[0], "--transport", args.transport]

    server_main()


def _daemon_setup(daemon, args: argparse.Namespace) -> int:
    """Shared-server-friendly daemon setup: free port + conda/PATH check +
    background-launch command (optionally start it). For no-Docker conda HPC
    nodes where two users/projects must coexist and there's no systemd."""
    from research_os.daemon.shared_setup import (
        background_launch_command,
        conda_env_name,
        find_free_port,
        launch_background,
        research_os_executable,
    )

    root = daemon.root
    if root is None:
        print(f"  {_warn_glyph()}  no workspace resolved — run from a project "
              "dir or pass --workspace.")
        return 1
    host = daemon.config.host or "127.0.0.1"
    preferred = getattr(args, "port", None) or daemon.config.port
    port = find_free_port(host, preferred)

    print("  Research OS daemon — shared-server setup")
    print(f"  root:      {root}")
    print(f"  conda env: {conda_env_name() or '(none active — activate one first)'}")
    print(f"  executable:{research_os_executable()}")
    if port != preferred:
        print(f"  port:      {port}  (port {preferred} was busy — picked a free one)")
    else:
        print(f"  port:      {port}")
    print()

    if getattr(args, "start", False):
        try:
            info = launch_background(root, port, host)
        except Exception as exc:  # noqa: BLE001
            print(f"  {_warn_glyph()}  background launch failed: {exc}")
            return 1
        print(f"  Started in background (pid {info['pid']}).")
        print(f"  url: http://{host}:{port}   log: {info['log']}")
        print("  stop: research-os daemon stop")
        return 0

    print("  To run it detached (no systemd needed), copy-paste:")
    print()
    print(f"    {background_launch_command(root, port, host)}")
    print()
    print("  Or let RO do it:  research-os daemon setup --start")
    print("  Stop anytime:     research-os daemon stop")
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    """Run / inspect the Research-OS daemon (enforcement + execution kernel).

    ``status`` reports daemon + active-project state (read-only). ``start``
    runs the persistent daemon: a background task queue plus read-only HTTP
    endpoints (/healthz, /v1/state, /v1/jobs) on localhost. The HTTP stack
    needs the optional ``research-os[daemon]`` extra. See docs/ROADMAP.md.
    """
    from research_os.daemon import Daemon

    sub = getattr(args, "daemon_command", None)
    if sub is None:
        print("  Research OS daemon (enforcement + execution kernel)")
        print()
        print("  research-os daemon status   show daemon + project state")
        print("  research-os daemon setup    free port + conda check + bg launch (HPC-friendly)")
        print("  research-os daemon start    run the daemon (localhost, read-only API)")
        print("  research-os daemon stop     stop this project's daemon (per-project)")
        print("  research-os daemon run      run a command as a tracked job")
        print("  research-os daemon docker   run a command in a container image (tracked, reproducible)")
        print("  research-os daemon runs     list recorded runs (durable history)")
        print("  research-os daemon logs ID  show a run's details + output")
        print("  research-os daemon reproduce ID  re-run + verify outputs match")
        print("  research-os daemon submit SCRIPT  submit to HPC scheduler (SLURM)")
        print("  research-os daemon diff A B  compare two runs (cmd/context/outputs)")
        print("  research-os daemon lineage [ID]  run dependency graph (provenance DAG)")
        print("  research-os daemon stale  flag results built from changed inputs")
        print("  research-os daemon rebuild  re-run only the stale runs (in order)")
        print("  research-os daemon domain  detect the project's research field + defaults")
        print()
        print("  Architecture + roadmap: docs/ROADMAP.md")
        return 0

    overrides: dict = {}
    if getattr(args, "host", None):
        overrides["host"] = args.host
    if getattr(args, "port", None):
        overrides["port"] = args.port

    workspace = getattr(args, "workspace", None)
    if workspace:
        root = Path(workspace).expanduser().resolve()
        daemon = Daemon.for_root(root, **overrides)
    else:
        daemon = Daemon.autoresolve(**overrides)

    if sub == "status":
        status = daemon.status()
        if getattr(args, "as_json", False):
            print(json.dumps(status.to_dict(), indent=2, default=str))
            return 0
        _print_daemon_status(status)
        return 0

    if sub == "start":
        # Shared/HPC convenience: detached launch with no systemd/Docker.
        if getattr(args, "background", False):
            from research_os.daemon.shared_setup import launch_background
            if daemon.root is None:
                print(f"  {_warn_glyph()}  no workspace resolved — run from a "
                      "project dir or pass --workspace.")
                return 1
            host = daemon.config.host
            port = daemon.config.port
            try:
                info = launch_background(daemon.root, port, host)
            except Exception as exc:  # noqa: BLE001
                print(f"  {_warn_glyph()}  background launch failed: {exc}")
                return 1
            print(f"  Research OS daemon launched in background (pid {info['pid']})")
            print(f"  root: {daemon.root}")
            print(f"  url:  http://{host}:{port}   log: {info['log']}")
            print("  stop: research-os daemon stop")
            return 0
        print(f"  Research OS daemon starting on {daemon.config.base_url}")
        print(f"  root: {daemon.root or '(none resolved)'}")
        print("  endpoints: GET /healthz  /v1/state  /v1/jobs   (read-only)")
        print("  Ctrl-C to stop.")
        try:
            daemon.serve()
        except RuntimeError as exc:
            # Missing [daemon] extra (or other startup failure) — clear hint.
            print(f"  {_warn_glyph()}  {exc}")
            return 1
        except KeyboardInterrupt:
            print("\n  daemon stopped.")
            return 0
        return 0

    if sub == "setup":
        return _daemon_setup(daemon, args)

    if sub == "stop":
        # Per-project graceful stop: read THIS project's descriptor
        # (<root>/.os_state/daemon.json), SIGTERM the recorded pid, and clear
        # the descriptor. Per-run state in .os_state/runs/ is preserved, so a
        # later `daemon start` resumes the project exactly where it left off.
        import os as _os
        import signal as _signal

        from research_os.daemon.discovery import (
            clear_discovery,
            read_discovery,
        )

        root = daemon.root
        if root is None:
            print(f"  {_cross()} No project resolved — run from inside a project "
                  "or pass --workspace.")
            return 1
        desc = read_discovery(root)
        pid = (desc or {}).get("pid")
        if not desc or not pid:
            print(f"  No running daemon recorded for {root}.")
            return 0
        try:
            _os.kill(int(pid), _signal.SIGTERM)
            print(f"  {_check()} Sent stop signal to daemon (pid {pid}) for {root}.")
        except ProcessLookupError:
            print(f"  Daemon (pid {pid}) was not running; clearing stale descriptor.")
        except (OSError, ValueError) as exc:
            print(f"  {_warn_glyph()} Could not stop daemon (pid {pid}): {exc}")
            return 1
        try:
            clear_discovery(root)
        except Exception:
            pass
        print("  Per-project run history in .os_state/runs/ is preserved — "
              "`research-os daemon start` resumes where you left off.")
        return 0

    if sub == "run":
        return _daemon_run(daemon, args)

    if sub == "docker":
        return _daemon_docker(daemon, args)

    if sub == "runs":
        return _daemon_runs(daemon, args)

    if sub == "logs":
        return _daemon_logs(daemon, args)

    if sub == "reproduce":
        return _daemon_reproduce(daemon, args)

    if sub == "submit":
        return _daemon_submit(daemon, args)

    if sub == "diff":
        return _daemon_diff(daemon, args)

    if sub == "lineage":
        return _daemon_lineage(daemon, args)

    if sub == "stale":
        return _daemon_stale(daemon, args)

    if sub == "notifications":
        return _daemon_notifications(daemon, args)

    if sub == "consent":
        return _daemon_consent(daemon, args)

    if sub == "rebuild":
        return _daemon_rebuild(daemon, args)

    if sub == "domain":
        return _daemon_domain(daemon, args)

    if sub == "token":
        return _daemon_token(daemon, args)

    print(f"  {_warn_glyph()}  Unknown daemon command: {sub!r}")
    return 2


def _daemon_run(daemon, args) -> int:
    """Execute a command as a tracked, provenance-recording run (blocking)."""
    import time as _time

    cmd = list(getattr(args, "cmd", []) or [])
    # argparse.REMAINDER keeps a leading "--"; strip it.
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print(f"  {_warn_glyph()}  No command given. Use: research-os daemon run -- <cmd>")
        return 2
    if daemon.runstore is None:
        print(f"  {_warn_glyph()}  No workspace resolved — runs need a project root.")
        print("  Run inside a research-os project, or pass --workspace <path>.")
        return 2

    daemon.tasks.start()
    daemon._start_journal()

    # Decide shell vs argv. A single token carrying shell metacharacters
    # (pipes, redirects, &&, globs, env-var refs) is what a researcher
    # means by "run this command line" — exec'ing it as one argv would
    # look for a file literally named "python x.py | tee log". Pass such a
    # command to the shell. Explicit --shell forces it; multi-token argv
    # (the `-- python analyze.py` form) stays exec-style.
    _SHELL_META = set("|&;<>()$`*?[]{}~#")
    force_shell = getattr(args, "force_shell", False)
    use_shell = force_shell
    cmd_arg: "str | list[str]" = cmd
    if len(cmd) == 1 and (force_shell or (_SHELL_META & set(cmd[0]))):
        cmd_arg = cmd[0]
        use_shell = True
    elif force_shell:
        # Explicit --shell on a multi-token command: join into one line.
        cmd_arg = " ".join(cmd)

    jid = daemon.run_command(
        cmd_arg,
        name=getattr(args, "name", None),
        cwd=getattr(args, "cwd", None),
        shell=use_shell,
        inputs=getattr(args, "inputs", None) or None,
        track_artifacts=not getattr(args, "no_artifacts", False),
    )

    if not getattr(args, "as_json", False):
        print(f"  run {jid} started: {' '.join(cmd)}")
    # Stream log lines as they land by polling the live log file.
    last = 0
    while True:
        job = daemon.tasks.get(jid)
        if not getattr(args, "as_json", False):
            lines = daemon.runstore.read_log(jid)
            for ln in lines[last:]:
                print(f"    {ln}")
            last = len(lines)
        if job and job.status.value in ("succeeded", "failed", "cancelled"):
            break
        _time.sleep(0.15)

    # Give the journal a beat to flush the terminal manifest.
    _time.sleep(0.3)
    manifest = daemon.runstore.read_manifest(jid) or {}
    daemon.tasks.shutdown(wait=False)

    if getattr(args, "as_json", False):
        print(json.dumps(manifest, indent=2, default=str))
        return 0 if manifest.get("status") == "succeeded" else 1

    status = manifest.get("status", "?")
    result = manifest.get("result") or {}
    rc = result.get("returncode")
    arts = manifest.get("artifacts") or []
    glyph = "✓" if status == "succeeded" else "✗"
    print(f"  {glyph} run {jid}: {status}" + (f" (exit {rc})" if rc is not None else ""))
    if arts:
        print(f"  artifacts ({len(arts)}):")
        for a in arts[:20]:
            h = (a.get("sha256") or "")[:19]
            print(f"    {a.get('change','?'):8} {a.get('path')}  {a.get('size')}b  {h}")
        if len(arts) > 20:
            print(f"    … and {len(arts) - 20} more")
    print(f"  record: {daemon.runstore._run_dir(jid)}")
    return 0 if status == "succeeded" else 1


def _daemon_docker(daemon, args) -> int:
    """Run a command inside a container image as a tracked job, streaming output."""
    import time as _time

    from research_os.daemon.runners import docker_available

    cmd = list(getattr(args, "cmd", []) or [])
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print(f"  {_warn_glyph()}  no command given. "
              "Usage: research-os daemon docker IMAGE -- <command>")
        return 2
    if not docker_available():
        print(f"  {_warn_glyph()}  no container CLI (docker/podman) found on PATH. "
              "Run natively with `research-os daemon run` instead.")
        return 1
    try:
        jid = daemon.run_container(
            args.image,
            cmd,
            name=getattr(args, "name", None),
            cwd=getattr(args, "cwd", None),
            gpus=getattr(args, "gpus", None),
            network=getattr(args, "network", False),
            inputs=getattr(args, "inputs", None) or None,
        )
    except RuntimeError as exc:
        print(f"  {_warn_glyph()}  {exc}")
        return 1

    if not getattr(args, "as_json", False):
        print(f"  container run {jid} started: {args.image}  {' '.join(cmd)}")
    last = 0
    while True:
        job = daemon.tasks.get(jid)
        if not getattr(args, "as_json", False):
            lines = daemon.runstore.read_log(jid)
            for ln in lines[last:]:
                print(f"    {ln}")
            last = len(lines)
        if job and job.status.value in ("succeeded", "failed", "cancelled"):
            break
        _time.sleep(0.15)

    _time.sleep(0.3)
    manifest = daemon.runstore.read_manifest(jid) or {}
    daemon.tasks.shutdown(wait=False)
    if getattr(args, "as_json", False):
        print(json.dumps(manifest, indent=2, default=str))
        return 0 if manifest.get("status") == "succeeded" else 1
    status = manifest.get("status", "?")
    result = manifest.get("result") or {}
    rc = result.get("returncode")
    container = result.get("container") or {}
    glyph = "✓" if status == "succeeded" else "✗"
    print(f"  {glyph} container run {jid}: {status}"
          + (f" (exit {rc})" if rc is not None else ""))
    if container.get("image_digest"):
        print(f"  image: {container.get('image')} @ {container['image_digest']}")
    print(f"  record: {daemon.runstore._run_dir(jid)}")
    return 0 if status == "succeeded" else 1


def _daemon_runs(daemon, args) -> int:
    """List the durable run history for the workspace."""
    if daemon.runstore is None:
        print("  no workspace resolved — nothing to list.")
        return 0
    runs = daemon.runstore.list_runs(limit=getattr(args, "limit", 20))
    if getattr(args, "as_json", False):
        print(json.dumps(runs, indent=2, default=str))
        return 0
    if not runs:
        print("  no recorded runs yet.")
        print(f"  (looked in {daemon.runstore.runs_dir})")
        return 0
    print(f"  {len(runs)} run(s) in {daemon.runstore.runs_dir}:")
    for r in runs:
        rid = r.get("id") or "?"
        status = r.get("status", "?")
        name = r.get("name") or ""
        nart = r.get("artifact_count") or 0
        rc = r.get("returncode")
        glyph = {"succeeded": "✓", "failed": "✗", "cancelled": "⊘"}.get(status, "·")
        extra = f"  exit={rc}" if rc is not None else ""
        artx = f"  {nart} artifact(s)" if nart else ""
        print(f"  {glyph} {rid}  {status:10}{extra}{artx}  {name}")
    return 0


def _daemon_logs(daemon, args) -> int:
    """Show one run's manifest + captured log."""
    if daemon.runstore is None:
        print(f"  {_warn_glyph()}  No workspace resolved — no runs to read.")
        return 1
    rid = args.run_id
    manifest = daemon.runstore.read_manifest(rid)
    if manifest is None:
        print(f"  {_warn_glyph()}  No run found: {rid}")
        return 1
    if getattr(args, "as_json", False):
        print(json.dumps(manifest, indent=2, default=str))
        return 0
    print(f"  run {rid}")
    print(f"  status:   {manifest.get('status','?')}")
    spec = manifest.get("spec") or {}
    cmd_val = spec.get("cmd") or spec.get("command")
    if cmd_val:
        print(f"  command:  {cmd_val}")
    prov = manifest.get("provenance") or {}
    git = prov.get("git") or {}
    commit = git.get("commit")
    if commit:
        dirty = " (dirty)" if git.get("dirty") else ""
        print(f"  commit:   {commit[:12]}{dirty} [{git.get('branch','?')}]")
    env = prov.get("env") or {}
    if env.get("conda_env"):
        print(f"  env:      {env.get('conda_env')} / python {env.get('python_version','?')}")
    arts = manifest.get("artifacts") or []
    if arts:
        print(f"  artifacts ({len(arts)}):")
        for a in arts[:20]:
            print(f"    {a.get('change','?'):8} {a.get('path')}  {a.get('size')}b")
    tail = getattr(args, "tail", 0) or None
    lines = daemon.runstore.read_log(rid, tail=tail)
    if lines:
        label = f"last {len(lines)}" if tail else f"{len(lines)}"
        print(f"  log ({label} lines):")
        for ln in lines:
            print(f"    {ln}")
    else:
        print("  (no log captured)")
    return 0


def _daemon_reproduce(daemon, args) -> int:
    """Re-run a recorded run and report whether its outputs still match."""
    from research_os.daemon import reproduce as _repro

    if daemon.runstore is None:
        print(f"  {_warn_glyph()}  No workspace resolved — no runs to reproduce.")
        return 2
    timeout = getattr(args, "timeout", 0) or None
    try:
        daemon.tasks.start()
        daemon._start_journal()
        report = daemon.reproduce_run(
            args.run_id,
            cwd=getattr(args, "cwd", None),
            timeout=timeout,
        )
    except ValueError as exc:
        print(f"  {_warn_glyph()}  {exc}")
        return 2
    finally:
        daemon.tasks.shutdown(wait=False)

    if getattr(args, "as_json", False):
        print(json.dumps(report, indent=2, default=str))
        return 0 if report["verdict"] == _repro.REPRODUCED else 1

    comp = report["comparison"]
    verdict = report["verdict"]
    glyph = _repro.verdict_glyph(verdict)
    print(f"  reproducing {report['original_id']} → run {report['repro_id']}")
    print(f"  command:  {report['command']}")
    print(f"  re-run:   {report['repro_status']}")
    c = comp["counts"]
    print(
        f"  outputs:  {c['matched']} matched, {c['changed']} changed, "
        f"{c['missing']} missing, {c['added']} new"
    )
    for ch in comp["changed"][:20]:
        r = (ch.get("recorded_sha256") or "?")[:19]
        f = (ch.get("fresh_sha256") or "?")[:19]
        print(f"    changed  {ch['path']}")
        print(f"             was {r}  now {f}")
    for p in comp["missing"][:20]:
        print(f"    missing  {p}")
    for p in comp["added"][:20]:
        print(f"    new      {p}")
    if comp["unhashed"]:
        print(f"  ({len(comp['unhashed'])} output(s) compared by size only — too large to hash)")
    label = {
        _repro.REPRODUCED: "REPRODUCED — every recorded output came back identical",
        _repro.DIVERGED: "DIVERGED — at least one output changed",
        _repro.INCOMPLETE: "INCOMPLETE — an output was not regenerated",
    }.get(verdict, verdict)
    print(f"  {glyph} {label}")
    return 0 if verdict == _repro.REPRODUCED else 1


def _daemon_submit(daemon, args) -> int:
    """Submit a job to an HPC scheduler and report the handle.

    Non-blocking: the cluster job may run for hours. We wait only long
    enough to confirm the submission itself succeeded (or failed cleanly),
    then print the daemon job id + scheduler job id and return — the daemon
    worker owns the poll-wait, and 'daemon runs/logs' track it from there.
    """
    import time as _time

    if daemon.runstore is None:
        print(f"  {_warn_glyph()}  No workspace resolved — cannot record a submission.")
        return 2
    daemon.tasks.start()
    daemon._start_journal()
    jid = daemon.submit_job(
        args.script,
        scheduler=getattr(args, "scheduler", "slurm"),
        name=getattr(args, "name", None),
        cwd=getattr(args, "cwd", None),
        poll_interval=getattr(args, "poll", 5.0),
    )

    # Briefly poll the job to surface an immediate submission failure (bad
    # scheduler, sbatch error) without blocking on the cluster run itself.
    scheduler_job_id = None
    submit_error = None
    deadline = _time.time() + 8.0
    while _time.time() < deadline:
        job = daemon.tasks.get(jid)
        if job is None:
            break
        res = job.result if isinstance(job.result, dict) else {}
        if res.get("scheduler_job_id"):
            scheduler_job_id = res["scheduler_job_id"]
            break
        if job.status.value == "failed" or res.get("error"):
            submit_error = res.get("error") or job.error
            break
        # A terminal status with no scheduler id but no error = very fast job.
        if job.status.value in ("succeeded", "cancelled"):
            scheduler_job_id = res.get("scheduler_job_id")
            break
        _time.sleep(0.25)

    if getattr(args, "as_json", False):
        print(json.dumps({
            "job_id": jid,
            "scheduler": getattr(args, "scheduler", "slurm"),
            "scheduler_job_id": scheduler_job_id,
            "error": submit_error,
        }, default=str))
        return 1 if submit_error else 0

    if submit_error:
        print(f"  {_warn_glyph()}  submission failed: {submit_error}")
        print(f"  daemon run id: {jid}  (see 'daemon logs {jid}')")
        return 1
    print(f"  submitted to {getattr(args, 'scheduler', 'slurm')}")
    print(f"  daemon run id:   {jid}")
    if scheduler_job_id:
        print(f"  scheduler job:   {scheduler_job_id}")
    print(f"  the daemon is now tracking it — 'daemon runs' / 'daemon logs {jid}'")
    return 0


def _daemon_diff(daemon, args) -> int:
    """Compare two recorded runs across command, context, and outputs."""
    from research_os.daemon import compare as _compare

    if daemon.runstore is None:
        print(f"  {_warn_glyph()}  No workspace resolved — no runs to read.")
        return 1
    ma = daemon.runstore.read_manifest(args.run_a)
    mb = daemon.runstore.read_manifest(args.run_b)
    if ma is None:
        print(f"  {_warn_glyph()}  No run found: {args.run_a}")
        return 1
    if mb is None:
        print(f"  {_warn_glyph()}  No run found: {args.run_b}")
        return 1

    report = _compare.compare_runs(ma, mb)
    if getattr(args, "as_json", False):
        print(json.dumps(report, indent=2, default=str))
        return 0 if report["same"] else 1

    a_id, b_id = report["ids"]["a"], report["ids"]["b"]
    print(f"  diff  {a_id}  ->  {b_id}")
    st = report["status"]
    print(f"  status:  {st['a']}  ->  {st['b']}")

    if report["same"]:
        print("  ✓  identical: same command, same context, same outputs")
        return 0

    cmd = report["command"]
    if cmd["changed"]:
        print("  command changed:")
        for field, ab in cmd["fields"].items():
            print(f"    {field}:")
            print(f"      a: {ab['a']}")
            print(f"      b: {ab['b']}")
    else:
        print("  command: (unchanged)")

    ctx = report["context"]
    if ctx["changed"]:
        print("  context changed:")
        for field, ab in ctx["fields"].items():
            if field in ("inputs", "packages"):
                print(f"    {field}:")
                for name, sub in ab.items():
                    print(f"      {name}:  {sub['a']}  ->  {sub['b']}")
            else:
                print(f"    {field}:  {ab['a']}  ->  {ab['b']}")
    else:
        print("  context: (unchanged — same git commit + env)")

    out = report["outputs"]
    oc = out["counts"]
    if out["changed"] or out["missing"] or out["added"]:
        print("  outputs changed:")
        for c in out["changed"]:
            ra = (c.get("recorded_sha256") or "?")[:10]
            fa = (c.get("fresh_sha256") or "?")[:10]
            print(f"    ~ {c['path']}  {ra} -> {fa}")
        for p in out["missing"]:
            print(f"    - {p}  (in {a_id[:8]}, not in {b_id[:8]})")
        for p in out["added"]:
            print(f"    + {p}  (new in {b_id[:8]})")
        print(f"    ({oc['matched']} identical, {oc['changed']} changed, "
              f"{oc['missing']} removed, {oc['added']} added)")
    else:
        print(f"  outputs: (unchanged — {oc['matched']} artifacts identical)")

    return 1


def _daemon_lineage(daemon, args) -> int:
    """Show the run dependency graph, or one run's up/downstream lineage."""
    from research_os.daemon import lineage as _lin

    if daemon.runstore is None:
        print(f"  {_warn_glyph()}  No workspace resolved — no runs to read.")
        return 1

    manifests = daemon.runstore.recent_manifests(limit=getattr(args, "limit", 200))
    graph = _lin.build_lineage(manifests)
    rid = getattr(args, "run_id", None)
    as_json = getattr(args, "as_json", False)

    # ── focused: one run's ancestors or descendants ──────────────────
    if rid:
        known = {n["id"] for n in graph["nodes"]}
        if rid not in known:
            # accept a unique short-prefix match
            cands = [i for i in known if i.startswith(rid)]
            if len(cands) == 1:
                rid = cands[0]
            elif not cands:
                print(f"  {_warn_glyph()}  No run found: {rid}")
                return 1
            else:
                print(f"  {_warn_glyph()}  Ambiguous prefix {rid!r}: {', '.join(cands[:5])}")
                return 1
        up = _lin.ancestors(graph, rid)
        down = _lin.descendants(graph, rid)
        if as_json:
            print(json.dumps({"run": rid, "ancestors": up, "descendants": down},
                             indent=2, default=str))
            return 0
        want_up = getattr(args, "upstream", False)
        want_down = getattr(args, "downstream", False)
        if not want_up and not want_down:
            want_up = want_down = True  # default: both
        if want_up:
            print(f"  upstream of {rid[:12]} (provenance — where it came from):")
            print("    " + (", ".join(a[:12] for a in up) if up else "(none — this is a source run)"))
        if want_down:
            print(f"  downstream of {rid[:12]} (impact — stale if re-run):")
            print("    " + (", ".join(d[:12] for d in down) if down else "(none — this is a terminal result)"))
        return 0

    # ── whole graph ──────────────────────────────────────────────────
    if as_json:
        print(json.dumps(graph, indent=2, default=str))
        return 0

    c = graph["counts"]
    print(f"  run lineage: {c['runs']} run(s), {c['edges']} dependency edge(s), "
          f"{c['linked']} linked")
    if not graph["edges"]:
        print("  (no links yet — runs become linked when one's input hash "
              "matches another's output)")
        return 0
    print("  edges (producer -> consumer):")
    name_by_id = {n["id"]: n["name"] for n in graph["nodes"]}
    for e in graph["edges"]:
        frm, to = e["from"], e["to"]
        paths = ", ".join(sorted({m["producer_path"] for m in e["via"]}))
        fn = (name_by_id.get(frm, "") or "")[:28]
        tn = (name_by_id.get(to, "") or "")[:28]
        print(f"    {frm[:12]} ({fn})  ->  {to[:12]} ({tn})")
        print(f"        via: {paths}")
    if graph["roots"]:
        print(f"  roots (sources): {', '.join(r[:12] for r in graph['roots'])}")
    if graph["leaves"]:
        print(f"  leaves (final results): {', '.join(lf[:12] for lf in graph['leaves'])}")
    if graph["orphans"]:
        print(f"  orphans (unlinked): {len(graph['orphans'])} run(s)")
    return 0


def _daemon_stale(daemon, args) -> int:
    """Freshness assessment: which runs were built from changed inputs."""
    from research_os.daemon import provenance as _prov
    from research_os.daemon import staleness as _stale

    if daemon.runstore is None:
        print(f"  {_warn_glyph()}  No workspace resolved — no runs to read.")
        return 1

    manifests = daemon.runstore.recent_manifests(limit=getattr(args, "limit", 200))

    # Resolve input paths relative to the workspace root, then hash current
    # on-disk state. Shared helper so CLI + /v1/staleness never diverge.
    hash_file = _prov.hash_fn_for_root(getattr(daemon, "root", None))

    report = _stale.assess(manifests, hash_file)
    as_json = getattr(args, "as_json", False)
    if as_json:
        print(json.dumps(report, indent=2, default=str))
        return 1 if report["stale"] else 0

    c = report["counts"]
    print(f"  freshness: {c['total']} run(s) — {c['fresh']} fresh, "
          f"{c['stale']} stale, {c['unknown']} unknown")

    if not report["stale"]:
        print("  ✓  all results are fresh (no recorded input has changed on disk)")
        if getattr(args, "show_all", False):
            _print_stale_rows(report, _stale, include_fresh=True)
        return 0

    print("  stale runs (results may no longer be valid):")
    _print_stale_rows(report, _stale, include_fresh=getattr(args, "show_all", False))
    print("  → re-run a stale run with: research-os daemon reproduce <ID>")
    return 1


def _print_stale_rows(report, _stale, *, include_fresh: bool) -> None:
    """Render per-run freshness rows for _daemon_stale."""
    for rid, v in sorted(report["runs"].items()):
        st = v["status"]
        if not include_fresh and st in (_stale.FRESH, _stale.UNKNOWN):
            continue
        g = _stale.status_glyph(st)
        print(f"    {g} {rid[:12]}  {st}  — {v['reason']}")
        for ch in v["changed"]:
            r = (ch.get("recorded") or "?")[:18]
            cur = (ch.get("current") or "?")[:18]
            print(f"        ~ {ch['path']}  {r} -> {cur}")
        for p in v["missing"]:
            print(f"        - {p}  (input now missing)")
        if v["stale_ancestors"]:
            anc = ", ".join(a[:12] for a in v["stale_ancestors"])
            print(f"        ↑ depends on stale: {anc}")


def _daemon_notifications(daemon, args) -> int:
    """Show the notification outbox — what the daemon told the researcher.

    The notification spine (docs/NOTIFICATION_SPINE.md) records every
    completion / page in .os_state/notifications/outbox.jsonl. This surfaces
    it so a researcher can see what happened (and what delivery missed)
    without tailing a file. --undelivered filters to records that did not
    reach the configured channel.
    """
    from research_os.daemon import notifications as _ntfy

    root = getattr(daemon, "root", None)
    if not root:
        print(f"  {_warn_glyph()}  No workspace resolved — no outbox to read.")
        return 1
    undelivered = getattr(args, "undelivered", False)
    records = _ntfy.read_outbox(
        root, undelivered_only=undelivered, limit=getattr(args, "limit", 100)
    )
    if getattr(args, "as_json", False):
        print(json.dumps(records, indent=2, default=str))
        return 0
    if not records:
        scope = "undelivered " if undelivered else ""
        print(f"  no {scope}notifications recorded.")
        return 0
    _level_glyph = {"info": "·", "warn": "▲", "action_required": "!"}
    print(f"  {len(records)} notification(s)"
          + (" (undelivered only)" if undelivered else "") + ":")
    for r in records:
        g = _level_glyph.get(r.get("level", "info"), "·")
        ts = (r.get("ts") or "")[:19].replace("T", " ")
        delivered = r.get("delivered")
        mark = "✓" if delivered else ("✗" if r.get("delivery", {}).get("attempted") else "·")
        print(f"    {g} [{ts}] {mark} {r.get('title', '')}")
        body = r.get("body", "")
        if body and body != r.get("title"):
            print(f"        {body}")
        det = (r.get("delivery") or {}).get("detail")
        if not delivered and det:
            print(f"        delivery: {det}")
    return 0


def _daemon_consent(daemon, args) -> int:
    """Review + approve/deny consent requests — the researcher's half of the
    un-skippable-gate loop (docs/UNSKIPPABLE_GATES.md).

    When the AI hits a floor gate under a daemon it calls
    sys_consent(action='request'), which queues a request here. This is how
    the human authorizes (or refuses) it:

        research-os daemon consent              # list pending + active grants
        research-os daemon consent approve <id> # mint a one-shot token
        research-os daemon consent deny <id>    # refuse

    The agent can never self-grant — minting authority lives only here.
    """
    from research_os.daemon.consent import ConsentStore

    root = getattr(daemon, "root", None)
    if not root:
        print(f"  {_warn_glyph()}  No workspace resolved — no consent ledger.")
        return 1
    store = ConsentStore(root)
    action = (getattr(args, "consent_action", None) or "list").lower()

    if action == "approve":
        rid = getattr(args, "request_id", None)
        if not rid:
            print("  usage: research-os daemon consent approve <request_id>")
            return 1
        grant = store.approve(rid)
        if grant is None:
            print(f"  {_warn_glyph()}  No pending request with id {rid!r} "
                  "(already resolved, or wrong id). Run 'consent' to list.")
            return 1
        print(f"  ✓ approved {rid} — minted a one-shot token for "
              f"{grant.get('gate_key')} (expires {grant.get('expires_at','')[:19]}).")
        print("    The agent can now fetch it via sys_consent(action='token').")
        return 0

    if action == "deny":
        rid = getattr(args, "request_id", None)
        if not rid:
            print("  usage: research-os daemon consent deny <request_id>")
            return 1
        ok = store.deny(rid)
        print(f"  ✓ denied {rid}." if ok else
              f"  {_warn_glyph()}  No pending request with id {rid!r}.")
        return 0 if ok else 1

    # default: list pending requests + active grants
    pending = store._live_pending()
    grants = store._live_grants()
    if getattr(args, "as_json", False):
        print(json.dumps({"pending": pending, "grants": grants}, indent=2, default=str))
        return 0
    if not pending and not grants:
        print("  no consent requests or active grants.")
        return 0
    if pending:
        print(f"  {len(pending)} pending request(s) — approve with "
              "'research-os daemon consent approve <id>':")
        for r in pending:
            ts = (r.get("requested_at") or "")[:19].replace("T", " ")
            print(f"    • {r.get('id')}  [{ts}]  {r.get('gate_key')}"
                  f"  ({r.get('tool','')})")
            if r.get("reason"):
                print(f"        reason: {r.get('reason')}")
    if grants:
        print(f"  {len(grants)} active grant(s):")
        for g in grants:
            mark = "spent" if g.get("consumed") else "live"
            print(f"    • {g.get('gate_key')}  [{mark}]  "
                  f"expires {g.get('expires_at','')[:19].replace('T',' ')}")
    return 0


def _daemon_rebuild(daemon, args) -> int:
    """Re-run exactly the stale sub-DAG in dependency order."""
    if daemon.runstore is None:
        print(f"  {_warn_glyph()}  No workspace resolved — no runs to rebuild.")
        return 1

    dry = getattr(args, "dry_run", False)
    report = daemon.rebuild_stale(
        limit=getattr(args, "limit", 200),
        dry_run=dry,
        timeout=getattr(args, "timeout", None),
    )

    if getattr(args, "as_json", False):
        print(json.dumps(report, indent=2, default=str))
        return 0

    plan = report["plan"]
    if not plan:
        print("  ✓  nothing to rebuild — all results are fresh")
        return 0

    if dry:
        print(f"  rebuild plan: {len(plan)} stale run(s), in dependency order:")
        for i, rid in enumerate(plan, 1):
            print(f"    {i}. {rid[:12]}")
        print("  → run without --dry-run to execute")
        return 0

    c = report["counts"]
    print(f"  rebuild: {c['planned']} planned — {c['rebuilt']} rebuilt, "
          f"{c['skipped']} skipped")
    for r in report["rebuilt"]:
        from research_os.daemon import reproduce as _repro
        g = _repro.verdict_glyph(r["verdict"])
        print(f"    {g} {r['run_id'][:12]} -> {r['repro_id'][:12]}  ({r['verdict']})")
    for s in report["skipped"]:
        print(f"    · {s['run_id'][:12]}  skipped — {s['reason']}")
    return 0


def _daemon_domain(daemon, args) -> int:
    """Detect the project's research field and show field-aware defaults."""
    from research_os.daemon import all_profiles, detect

    if getattr(args, "list_all", False):
        profs = all_profiles()
        if getattr(args, "as_json", False):
            print(json.dumps([p.as_dict() for p in profs], indent=2))
            return 0
        print(f"  {len(profs)} built-in domain profiles:\n")
        for p in profs:
            aliases = ", ".join(p.aliases) if p.aliases else "—"
            print(f"  {p.id}")
            print(f"      {p.label}")
            print(f"      aliases: {aliases}")
            print(f"      languages: {', '.join(p.languages) or '—'}")
            print()
        return 0

    root = daemon.root or Path.cwd()
    result = detect(root)

    if getattr(args, "as_json", False):
        out = result.as_dict()
        out["root"] = str(root)
        print(json.dumps(out, indent=2))
        return 0

    p = result.profile
    pct = int(round(result.confidence * 100))
    print(f"  project: {root}")
    print(f"  field:   {p.label}  [{p.id}]")
    print(f"  via:     {result.source} ({pct}% confidence)")
    if result.matched_signals:
        print(f"  signals: {', '.join(result.matched_signals)}")
    print()
    print(f"  languages:        {', '.join(p.languages) or '—'}")
    print(f"  deliverables:     {', '.join(p.artifacts) or '—'}")
    print(f"  reproducibility:  {p.reproducibility or '—'}")
    if p.notes:
        print(f"  note:             {p.notes}")
    if result.source == "fallback":
        print()
        print("  No strong field signal — set `domain:` in "
              "inputs/researcher_config.yaml to specialize,")
        print("  or run `research-os daemon domain --list` to see options.")
    return 0


def _daemon_token(daemon, args) -> int:
    """Show / mint the daemon's bearer token for the mutating endpoints.

    RO calls no LLM and has no gateway. This token only guards the daemon's
    own mutating endpoints (/v1/runs, /v1/gates/respond, /v1/consent/*, …).
    It lives in an environment variable by design (never in config files);
    when unset, those endpoints stay open behind the 127.0.0.1 bind.
    """
    import os
    import secrets

    cfg = daemon.config

    if getattr(args, "mint_token", False):
        token = secrets.token_urlsafe(32)
        print(f"  export {cfg.auth_token_env}={token}")
        print()
        print("  Set this on the daemon process; clients send it in the")
        print("  Authorization header as a Bearer token on mutating POSTs.")
        return 0

    token_set = bool(os.environ.get(cfg.auth_token_env, ""))

    if getattr(args, "as_json", False):
        print(json.dumps({
            "token_env": cfg.auth_token_env,
            "token_set": token_set,
            "enforced": token_set,
            "note": "RO has no LLM gateway; this guards mutating endpoints only",
        }, indent=2))
        return 0

    ok = _check()
    warn = _warn_glyph()
    print("  Research OS daemon auth token (mutating endpoints)")
    print()
    print(f"    {ok if token_set else warn}  bearer token  "
          f"(${cfg.auth_token_env}{' set — enforced' if token_set else ' unset — open on localhost'})")
    print()
    if not token_set:
        print("  To require a bearer token on mutating endpoints:")
        print("    research-os daemon token --mint-token")
    return 0


def _print_daemon_status(status) -> None:
    """Pretty-print a DaemonStatus for the terminal."""
    serving = "yes" if status.serving else "no"
    print(f"  Research OS daemon v{status.version}")
    print(f"  serving:     {serving}")
    print(f"  bind:        {status.config.get('base_url')}")
    _tok_env = status.config.get("auth_token_env")
    _tok_set = bool(_tok_env and os.environ.get(_tok_env))
    print(f"  auth:        {'token-enforced' if _tok_set else 'open (localhost)'}")
    print(f"  dashboard:   {'on' if status.config.get('enable_dashboard') else 'off'}")
    print(f"  sandbox:     {status.config.get('sandbox_mode')}")
    print(f"  workers:     {status.config.get('task_workers')}")
    print(f"  root:        {status.root or '(none resolved)'}")
    print(f"  initialized: {'yes' if status.project_initialized else 'no'}")
    if status.active_protocol:
        print(f"  protocol:    {status.active_protocol}")
    if status.progress:
        done = status.progress.get("completed") or status.progress.get("steps_done")
        total = status.progress.get("total") or status.progress.get("steps_total")
        if done is not None and total is not None:
            print(f"  progress:    {done}/{total} steps")
    jobs = status.jobs or {}
    if jobs.get("total"):
        counts = jobs.get("counts", {})
        summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
        print(f"  jobs:        {jobs['total']} ({summary})")
    if len(status.roots) > 1:
        print(f"  roots:       {len(status.roots)} registered")
    for note in status.notes:
        print(f"  {_warn_glyph()}  {note}")


# ---------------------------------------------------------------------------
# ide subcommand
# ---------------------------------------------------------------------------


def _find_workspace_root(start: Path | None = None) -> Path | None:
    p = (start or Path.cwd()).resolve()
    for parent in (p, *p.parents):
        if (parent / ".os_state").exists():
            return parent
    return None


def cmd_ide(args: argparse.Namespace) -> None:
    """Inspect / add / remove AI IDE MCP configs in the current workspace."""
    from research_os import collab, wizard
    if getattr(args, "no_color", False):
        wizard.disable_color()

    root = _find_workspace_root()
    if not root:
        wizard.fail("Not inside a Research OS workspace",
                    "Run `research-os init` first, or cd into a project.")
        sys.exit(1)

    action = args.action

    if action == "list":
        wired = collab.list_wired_ides(root)
        print()
        print(f"  {wizard._C.BOLD}AI IDE configs in {root}{wizard._C.RESET}")
        print(f"  {wizard._C.GREY}{wizard._hr()}{wizard._C.RESET}")
        for ide, present in wired.items():
            mark = (f"{wizard._C.GREEN}✓{wizard._C.RESET}" if present
                    else f"{wizard._C.GREY}·{wizard._C.RESET}")
            primary = collab.IDE_FILES[ide][0]
            line = f"  {mark} {ide:<14}{wizard._C.GREY}{primary}{wizard._C.RESET}"
            if not present:
                line += f"  {wizard._C.DIM}(run `research-os ide add {ide}` to wire){wizard._C.RESET}"
            print(line)
        print()
        return

    if action == "config-path":
        names = args.names or []
        if not names:
            wizard.fail("`research-os ide config-path` needs at least one IDE name",
                        "e.g. `research-os ide config-path cursor`")
            sys.exit(1)
        unknown = [n for n in names if n not in collab.IDE_FILES]
        if unknown:
            wizard.fail(f"Unknown IDE(s): {', '.join(unknown)}",
                        f"Choose from: {', '.join(sorted(collab.IDE_FILES))}")
            sys.exit(1)
        for ide in names:
            print(collab.IDE_FILES[ide][0])
        return

    if action in ("add", "remove"):
        names = args.names or []
        if not names:
            wizard.fail(f"`research-os ide {action}` needs at least one IDE name",
                        f"e.g. `research-os ide {action} cursor`")
            sys.exit(1)
        unknown = [n for n in names if n not in collab.IDE_FILES]
        if unknown:
            wizard.fail(f"Unknown IDE(s): {', '.join(unknown)}",
                        f"Choose from: {', '.join(sorted(collab.IDE_FILES))}")
            sys.exit(1)

        author = collab.whoami(root)
        added_any = False
        for ide in names:
            if action == "add":
                created = collab.add_ide(root, ide)
                if created:
                    wizard.ok(f"Wired {ide}", f"{', '.join(created)}")
                    collab.log_action(root, author, f"Added IDE config: {ide}")
                    added_any = True
                else:
                    wizard.warn(f"{ide} already wired", "no changes made")
            else:  # remove
                removed = collab.remove_ide(root, ide)
                if removed:
                    wizard.ok(f"Removed {ide} config", ", ".join(removed))
                    collab.log_action(root, author, f"Removed IDE config: {ide}")
                else:
                    wizard.warn(f"{ide} was not wired", "no changes made")
        # Wiring an MCP server only takes effect on a FRESH session — the #1
        # naive miss is to wire and report success while the already-open IDE
        # never reloads. Surface the same restart notice init prints.
        if added_any:
            from research_os.project_ops import mcp_restart_notice
            print()
            for line in mcp_restart_notice().splitlines():
                print(f"  {line}")


# ---------------------------------------------------------------------------
# mcp subcommand — compose OTHER MCP servers (Slack, GitHub, Postgres, ...)
# into the IDE configs RO already manages.
#
# This is additive: `research-os ide add` still wires the RO server itself
# into an IDE. `research-os mcp add` wires extra third-party MCP servers
# into the same mcpServers block so the IDE picks them up alongside RO.
# ---------------------------------------------------------------------------


def cmd_mcp(args: argparse.Namespace) -> int:
    """Add / list / remove / template third-party MCP servers."""
    from research_os import collab, wizard
    if getattr(args, "no_color", False):
        wizard.disable_color()

    root = _find_workspace_root()
    if not root:
        wizard.fail("Not inside a Research OS workspace",
                    "Run `research-os init` first, or cd into a project.")
        return 1

    action = args.action

    if action == "list":
        servers_by_ide = collab.mcp_list_servers(root)
        if not servers_by_ide:
            wizard.warn("No IDE configs with composable mcpServers found",
                        "Run `research-os ide add <name>` to wire an IDE first.")
            return 0
        print()
        print(f"  {wizard._C.BOLD}MCP servers in {root}{wizard._C.RESET}")
        print(f"  {wizard._C.GREY}{wizard._hr()}{wizard._C.RESET}")
        for ide, servers in servers_by_ide.items():
            relpath = collab.IDES_WITH_MCP_JSON[ide][0]
            print(f"  {wizard._C.BOLD}{ide}{wizard._C.RESET} "
                  f"{wizard._C.GREY}({relpath}){wizard._C.RESET}")
            if not servers:
                print(f"    {wizard._C.GREY}(no servers configured){wizard._C.RESET}")
                continue
            for name, entry in sorted(servers.items()):
                cmd = entry.get("command", "?") if isinstance(entry, dict) else "?"
                print(f"    {wizard._C.GREEN}·{wizard._C.RESET} "
                      f"{name:<24}{wizard._C.GREY}{cmd}{wizard._C.RESET}")
        print()
        return 0

    if action == "template":
        name = (args.name or "").strip().lower()
        if not name:
            wizard.fail("`research-os mcp template` needs --name",
                        f"Known: {', '.join(sorted(collab.MCP_TEMPLATES))}")
            return 2
        entry = collab.MCP_TEMPLATES.get(name)
        if not entry:
            wizard.fail(f"Unknown template: {name!r}",
                        f"Known: {', '.join(sorted(collab.MCP_TEMPLATES))}")
            return 2
        ides = _parse_ide_list_for_mcp(args.ide, collab)
        results = collab.mcp_add_server(root, args.as_name or name, entry, ides=ides)
        _print_mcp_results(results, args.as_name or name, action="added", wizard=wizard)
        author = collab.whoami(root)
        collab.log_action(root, author, f"Added MCP server template: {args.as_name or name}")
        return 0

    if action == "add":
        if not args.name:
            wizard.fail("`research-os mcp add` needs --name", "")
            return 2
        if not args.mcp_command:
            wizard.fail("`research-os mcp add` needs --command",
                        "e.g. `--command npx --args -y,@scope/server`")
            return 2
        entry: dict = {"command": args.mcp_command}
        if args.mcp_args:
            # Accept comma- or space-separated lists (commas are simpler in shells).
            arg_list = [a for a in args.mcp_args.replace(",", " ").split() if a]
            if arg_list:
                entry["args"] = arg_list
        ides = _parse_ide_list_for_mcp(args.ide, collab)
        results = collab.mcp_add_server(root, args.name, entry, ides=ides)
        _print_mcp_results(results, args.name, action="added", wizard=wizard)
        author = collab.whoami(root)
        collab.log_action(root, author, f"Added MCP server: {args.name}")
        return 0

    if action == "remove":
        if not args.name:
            wizard.fail("`research-os mcp remove` needs --name", "")
            return 2
        ides = _parse_ide_list_for_mcp(args.ide, collab)
        results = collab.mcp_remove_server(root, args.name, ides=ides)
        _print_mcp_results(results, args.name, action="removed", wizard=wizard)
        author = collab.whoami(root)
        collab.log_action(root, author, f"Removed MCP server: {args.name}")
        return 0

    wizard.fail(f"Unknown mcp action: {action}", "")
    return 2


def _parse_ide_list_for_mcp(value: str | None, collab_mod) -> list[str] | None:
    """Parse the --ide flag for `mcp` subcommands. None / 'all' / 'wired'
    → return None (delegate to mcp_add_server's default).
    Comma-separated → return the explicit list, validated against the
    set of IDEs that DO support composable mcpServers blocks."""
    if not value or value.lower() in ("all", "wired"):
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    valid = collab_mod.IDES_WITH_MCP_JSON
    invalid = [p for p in parts if p not in valid]
    if invalid:
        print(f"  {_cross()} Unknown IDE(s) for mcp: {', '.join(invalid)}. "
              f"Choose from: {', '.join(sorted(valid))}.")
        sys.exit(2)
    return parts


def _print_mcp_results(results: dict[str, str], name: str, action: str, wizard) -> None:
    if not results:
        wizard.warn(f"No IDEs to {action.rstrip('ed')} {name!r}",
                    "Wire one with `research-os ide add <name>` first.")
        return
    for ide, status in results.items():
        if status in ("added", "updated", "removed"):
            wizard.ok(f"{ide}: {status} {name}")
        else:
            wizard.warn(f"{ide}", status)


# ---------------------------------------------------------------------------
# hermes subcommand — wire Research-OS into Hermes Agent (~/.hermes/config.yaml)
# ---------------------------------------------------------------------------


def cmd_hermes(args: argparse.Namespace) -> int:
    """Wire / unwire / inspect Research-OS inside Hermes Agent."""
    from research_os import hermes_integration as hi
    from research_os import wizard
    if getattr(args, "no_color", False):
        wizard.disable_color()

    action = args.action
    cfg = Path(args.config).expanduser() if getattr(args, "config", None) else None

    if action == "status":
        st = hi.status(config_path=cfg)
        print()
        print(f"  {wizard._C.BOLD}Research-OS in Hermes{wizard._C.RESET}")
        print(f"  {wizard._C.GREY}{wizard._hr()}{wizard._C.RESET}")
        print(f"  config        {st['config_path']}"
              f"  {'(exists)' if st['config_exists'] else '(missing)'}")
        if st["server_registered"]:
            wizard.ok("MCP server registered", repr(st["server_entry"]))
        else:
            wizard.warn("MCP server not registered",
                        "run `research-os hermes add`")
        if st["skill_installed"]:
            wizard.ok("Skill installed", st["skill_path"])
        else:
            wizard.warn("Skill not installed", "run `research-os hermes add`")
        if st["external_dirs"]:
            print(f"  external_dirs {st['external_dirs']}")
        return 0

    if action == "add":
        raw = getattr(args, "mcp_args", None)
        mcp_args = [a for a in raw.replace(",", " ").split() if a] if raw else None
        res = hi.add(
            command=getattr(args, "hermes_command", None),
            args=mcp_args,
            url=getattr(args, "url", None),
            config_path=cfg,
        )
        wizard.ok(f"MCP server {res['server_action']}",
                  f"{res['server_key']} → {res['config_path']}")
        if res["url"]:
            print(f"  url     {res['url']}")
        else:
            print(f"  command {res['command']} {' '.join(res['args'])}")
        wizard.ok("Skill installed", res["skill_path"])
        if res["external_dir_added"]:
            wizard.ok("Registered skills dir in external_dirs")
        elif not res["external_dir_needed"]:
            print("  (skill lives in the built-in Hermes skills tree; "
                  "no external_dir needed)")
        print()
        print("  Restart Hermes to pick up the new MCP server and skill.")
        return 0

    if action == "remove":
        res = hi.remove(config_path=cfg)
        if res["server_removed"]:
            wizard.ok("MCP server unregistered", res["config_path"])
        else:
            wizard.warn("MCP server was not registered", "no changes")
        if res["external_dir_removed"]:
            wizard.ok("Removed skills dir from external_dirs")
        return 0

    wizard.fail(f"Unknown hermes action: {action!r}",
                "Choose from: add, remove, status")
    return 2


# ---------------------------------------------------------------------------
# route subcommand — preview the protocol router from the terminal
# ---------------------------------------------------------------------------


def cmd_skills(args: argparse.Namespace) -> int:
    """Manage science-skill libraries (the K-Dense scientific-agent-skills pack)."""
    from research_os import wizard  # local import to avoid cycle
    from research_os.tools.actions.research import science_pack

    action = getattr(args, "action", None)
    if action == "list-science":
        print(f"  Science pack: {science_pack.SCIENCE_PACK_REPO}")
        print(f"  License: {science_pack.SCIENCE_PACK_LICENSE} · "
              "140 skills in the open Agent-Skills standard.")
        print("  Domains mapped to skills:")
        for dom, names in sorted(science_pack.SCIENCE_PACK_BY_DOMAIN.items()):
            print(f"    {dom:16s} {', '.join(names)}")
        print("\n  Install with: research-os skills add-science-pack")
        return 0

    if action == "add-science-pack":
        ref = getattr(args, "skills_ref", None) or science_pack.SCIENCE_PACK_DEFAULT_REF
        dest = getattr(args, "skills_dest", None)
        wire = not getattr(args, "skills_no_hermes", False)
        print(f"  Fetching {science_pack.SCIENCE_PACK_NAME} ({ref}) — this may take a moment...")
        res = science_pack.install_science_pack(dest=dest, ref=ref, wire_hermes=wire)
        if res.get("status") != "success":
            wizard.warn("Science pack not installed", res.get("message", "unknown error"))
            return 1
        wizard.ok(
            f"Science pack {res['action']}",
            f"{res['n_skills']} skills at {res['skills_dir']} (commit {res['commit'][:8]})",
        )
        herm = res.get("hermes") or {}
        if herm.get("added"):
            print(f"  Wired into Hermes: {herm['external_dir']}")
            print("  Restart Hermes so it loads the new skills.")
        elif herm.get("status") == "skipped":
            print(f"  Hermes wiring skipped: {herm.get('reason')}")
        else:
            print("  (Already registered in Hermes.)")
        print("  IDEs on the Agent-Skills standard: point them at "
              f"{res['skills_dir']}")
        print(f"  License: {res['license']} · source: {res['repo']}")
        return 0

    wizard.warn("Unknown skills action", str(action))
    return 1


def cmd_route(args: argparse.Namespace) -> int:
    """Run the runtime protocol router on a prompt and print the decision.

    This is the same ``route_request`` the MCP ``tool_route`` calls, exposed
    so a researcher (or a non-MCP agent) can preview what Research-OS would
    do for a given request without loading an IDE. Read-only: never persists
    an active plan.
    """
    import json as _json

    from research_os import wizard
    from research_os.tools.actions.router import route_request

    if getattr(args, "no_color", False):
        wizard.disable_color()

    prompt = (args.prompt or "").strip()
    if not prompt:
        wizard.fail("Empty prompt", 'Usage: research-os route "<your request>"')
        return 2

    root = _find_workspace_root() or Path.cwd()

    result = route_request(prompt, root, persist_plan=False)

    if getattr(args, "json", False):
        print(_json.dumps(result, indent=2, default=str))
        return 0 if result.get("status") == "success" else 1

    if result.get("status") != "success":
        wizard.fail("Routing failed", result.get("message", "unknown error"))
        return 1

    C = wizard._C
    level = result.get("resolved_level")
    intent = result.get("intent_class") or "—"
    sub = result.get("sub_intent") or "—"
    primary = result.get("primary_protocol")
    shortcut = result.get("shortcut_tool")
    complexity = result.get("complexity") or "—"
    tier = result.get("tier")
    why = result.get("why_matched") or result.get("why") or ""
    ask = result.get("ask_user")
    decomposition = result.get("decomposition") or []
    alternatives = result.get("alternatives") or []
    triggers = result.get("matched_triggers") or []

    print()
    print(f"  {C.BOLD}Route for:{C.RESET} {prompt}")
    print(f"  {C.GREY}{wizard._hr()}{C.RESET}")
    print(f"  {C.BOLD}intent{C.RESET}        {intent} / {sub}")
    if primary:
        print(f"  {C.BOLD}protocol{C.RESET}      {C.GREEN}{primary}{C.RESET}")
    if shortcut:
        print(f"  {C.BOLD}shortcut{C.RESET}      {C.GREEN}{shortcut}{C.RESET}")
    print(f"  {C.BOLD}level{C.RESET}         L{level}   "
          f"complexity={complexity}" + (f"   tier={tier}" if tier else ""))
    if triggers:
        print(f"  {C.BOLD}triggers{C.RESET}      {', '.join(str(t) for t in triggers)}")
    if why:
        print(f"  {C.BOLD}why{C.RESET}           {C.GREY}{why}{C.RESET}")
    if ask:
        print(f"  {C.BOLD}{C.YELLOW}ask first{C.RESET}     {ask}")

    if decomposition:
        print()
        print(f"  {C.BOLD}planned tool sequence{C.RESET}")
        for i, step in enumerate(decomposition, 1):
            tool = step.get("tool") if isinstance(step, dict) else str(step)
            note = step.get("why", "") if isinstance(step, dict) else ""
            line = f"    {i:>2}. {tool}"
            if note:
                line += f"   {C.GREY}{note}{C.RESET}"
            print(line)

    if alternatives:
        print()
        print(f"  {C.BOLD}alternatives{C.RESET}")
        for alt in alternatives[:4]:
            if isinstance(alt, dict):
                aid = alt.get("name") or alt.get("protocol") or alt.get("primary_protocol") or "—"
                ascore = alt.get("score")
            else:
                aid, ascore = str(alt), None
            sc = f"  ({ascore})" if ascore is not None else ""
            print(f"    - {aid}{C.GREY}{sc}{C.RESET}")
    print()
    return 0


# ---------------------------------------------------------------------------
# api-key subcommand — manage api_keys in inputs/researcher_config.yaml
# ---------------------------------------------------------------------------


def cmd_api_key(args: argparse.Namespace) -> int:
    """Add / list / rotate / remove / test an API key in researcher_config.yaml."""
    from research_os import collab, wizard
    from research_os.tools.actions.state.config import (
        add_api_key, check_api_key, list_api_keys, remove_api_key,
    )
    if getattr(args, "no_color", False):
        wizard.disable_color()

    root = _find_workspace_root()
    if not root:
        wizard.fail("Not inside a Research OS workspace",
                    "Run `research-os init` first, or cd into a project.")
        return 1

    action = args.action

    if action == "list":
        res = list_api_keys(root)
        if res.get("status") != "success":
            wizard.fail("Could not list API keys", res.get("message", ""))
            return 1
        api_keys = res.get("api_keys") or {}
        print()
        print(f"  {wizard._C.BOLD}API keys in {root / 'inputs' / 'researcher_config.yaml'}{wizard._C.RESET}")
        print(f"  {wizard._C.GREY}{wizard._hr()}{wizard._C.RESET}")
        if not api_keys:
            print(f"  {wizard._C.GREY}(no keys configured){wizard._C.RESET}")
        for provider, masked_val in sorted(api_keys.items()):
            mark = (f"{wizard._C.GREEN}·{wizard._C.RESET}" if masked_val
                    else f"{wizard._C.GREY}·{wizard._C.RESET}")
            display = masked_val or f"{wizard._C.GREY}(blank){wizard._C.RESET}"
            print(f"  {mark} {provider:<22}{display}")
        print()
        return 0

    if action in ("add", "rotate"):
        provider = args.provider
        if not provider:
            wizard.fail(f"`research-os api-key {action}` needs a provider",
                        f"e.g. `research-os api-key {action} semantic_scholar`")
            return 2
        value = _read_secret_value(args, provider, wizard)
        if not value:
            return 2
        res = add_api_key(root, provider, value)
        if res.get("status") != "success":
            wizard.fail(f"Could not store key for {provider}",
                        res.get("message", ""))
            return 1
        verb = "Rotated" if res.get("rotated") or action == "rotate" else "Added"
        wizard.ok(f"{verb} key for {provider}", "chmod 600 applied")
        author = collab.whoami(root)
        collab.log_action(root, author, f"{verb} API key: {provider}")
        return 0

    if action == "remove":
        provider = args.provider
        if not provider:
            wizard.fail("`research-os api-key remove` needs a provider", "")
            return 2
        res = remove_api_key(root, provider)
        if res.get("status") == "success":
            wizard.ok(f"Removed key for {provider}")
            author = collab.whoami(root)
            collab.log_action(root, author, f"Removed API key: {provider}")
            return 0
        if res.get("status") == "noop":
            wizard.warn(res.get("message", "no-op"))
            return 0
        wizard.fail("Could not remove key", res.get("message", ""))
        return 1

    if action == "test":
        provider = args.provider
        if not provider:
            wizard.fail("`research-os api-key test` needs a provider",
                        "e.g. `research-os api-key test pubmed`")
            return 2
        res = check_api_key(root, provider)
        if res.get("status") == "ok":
            wizard.ok(f"{provider}: OK", res.get("detail", ""))
            return 0
        wizard.fail(f"{provider}: FAIL", res.get("detail", ""))
        return 1

    wizard.fail(f"Unknown api-key action: {action}", "")
    return 2


def _read_secret_value(args: argparse.Namespace, provider: str, wizard) -> str:
    """Return the secret to store, prompting via getpass if not in --from-env."""
    if getattr(args, "from_env", None):
        env_name = args.from_env
        val = os.environ.get(env_name, "").strip()
        if not val:
            wizard.fail(f"Environment variable {env_name} not set or empty", "")
            return ""
        return val
    # Interactive: hidden prompt.
    import getpass as _getpass
    try:
        val = _getpass.getpass(f"Paste {provider} API key (input hidden): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        wizard.warn("Cancelled — no key stored")
        return ""
    if not val:
        wizard.warn("Empty input — no key stored")
        return ""
    return val


# ---------------------------------------------------------------------------
# refresh — update project copies of templates from the bundled source
# ---------------------------------------------------------------------------


# Files that the wizard copies into a new project from
# `templates/`. The refresh command compares each project copy against
# the bundled source and (optionally) overwrites when they diverge.
# Path is relative to the project root; the bundled source lives at the
# same relative path under `templates/`. Order matches the wizard.
_REFRESHABLE_TEMPLATES: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/rules/research-os.md",
    ".cursor/rules/research-os.mdc",
    ".antigravity/rules/research-os.md",
    ".windsurfrules",
    ".continuerules",
    ".aider.conf.yml",
)


def _bundled_templates_dir() -> Path:
    """Path to the bundled templates directory shipped with the package."""
    return Path(__file__).resolve().parent.parent.parent / "templates"


def _diff_template(bundled: Path, project: Path) -> tuple[str, str]:
    """Return ``(status, message)`` for one project copy vs the bundled source.

    Status values:
      * ``fresh``    — project copy missing OR identical to bundled source.
      * ``drift``    — both exist but content differs.
      * ``absent``   — neither exists (file isn't applicable to this project,
                       e.g. .cursor/ rules in a project wired only for Claude).
      * ``error``    — couldn't read one of the files.
    """
    bundled_exists = bundled.exists()
    project_exists = project.exists()
    if not bundled_exists and not project_exists:
        return ("absent", "neither source nor project copy present")
    if not project_exists:
        return ("absent", "project copy missing (file is opt-in per IDE)")
    if not bundled_exists:
        return ("error", "bundled source missing — package install corrupt?")
    try:
        b_text = bundled.read_text()
        p_text = project.read_text()
    except OSError as e:
        return ("error", f"read failed: {e}")
    if b_text == p_text:
        return ("fresh", "identical to bundled template")
    # Cheap line-level diff stats so the report is meaningful without
    # running a full diff library.
    b_lines = b_text.splitlines()
    p_lines = p_text.splitlines()
    delta = len(b_lines) - len(p_lines)
    sign = "+" if delta > 0 else ""
    return (
        "drift",
        f"differs from bundled (project has {len(p_lines)} lines, "
        f"bundled has {len(b_lines)}, {sign}{delta} after refresh)",
    )


def cmd_refresh(args: argparse.Namespace) -> int:
    """Detect drift between project template copies and bundled sources;
    optionally overwrite.

    Read-only by default (``--check`` is the only mode that exits non-zero
    on drift). Pass ``--write`` to overwrite drifted files; pass ``--yes``
    to skip the confirmation prompt for each file.
    """
    from research_os import wizard

    if getattr(args, "no_color", False):
        wizard.disable_color()

    workspace = (
        Path(args.workspace).resolve() if getattr(args, "workspace", None)
        else _find_workspace_root()
    )
    if not workspace:
        wizard.fail(
            "Not inside a Research OS workspace",
            "cd into a project directory or pass --workspace <path>.",
        )
        return 1

    bundled_dir = _bundled_templates_dir()
    if not bundled_dir.exists():
        wizard.fail(
            "Bundled templates directory not found",
            f"expected at {bundled_dir} — package install may be corrupt.",
        )
        return 1

    results: list[tuple[str, str, str, Path, Path]] = []
    for rel in _REFRESHABLE_TEMPLATES:
        bundled = bundled_dir / rel
        project = workspace / rel
        status, message = _diff_template(bundled, project)
        results.append((rel, status, message, bundled, project))

    drift_count = sum(1 for _, status, *_ in results if status == "drift")
    error_count = sum(1 for _, status, *_ in results if status == "error")
    fresh_count = sum(1 for _, status, *_ in results if status == "fresh")
    absent_count = sum(1 for _, status, *_ in results if status == "absent")

    # ── JSON mode ───────────────────────────────────────────────────────
    if getattr(args, "json", False):
        out = {
            "workspace": str(workspace),
            "bundled_dir": str(bundled_dir),
            "drift_count": drift_count,
            "error_count": error_count,
            "fresh_count": fresh_count,
            "absent_count": absent_count,
            "files": [
                {
                    "relative_path": rel,
                    "status": status,
                    "message": msg,
                    "bundled_source": str(bundled),
                    "project_copy": str(project),
                }
                for rel, status, msg, bundled, project in results
            ],
        }
        print(json.dumps(out, indent=2))
        if getattr(args, "check", False):
            return 0 if drift_count == 0 and error_count == 0 else 1
        return 0

    # ── Human-readable report ───────────────────────────────────────────
    print(f"\nWorkspace: {workspace}")
    print(f"Templates: {bundled_dir}\n")
    for rel, status, msg, _bundled, _project in results:
        if status == "fresh":
            wizard.ok(f"  {rel}", msg)
        elif status == "drift":
            wizard.warn(f"  {rel}", msg)
        elif status == "absent":
            # Quiet success — file not applicable.
            print(f"  · {rel}: not applicable (no project copy)")
        else:
            wizard.fail(f"  {rel}", msg)
    print()

    if drift_count == 0 and error_count == 0:
        wizard.ok(
            "All template copies fresh",
            f"{fresh_count} match, {absent_count} not applicable.",
        )
        return 0

    # ── Check mode: report only, exit non-zero on drift ─────────────────
    if getattr(args, "check", False):
        wizard.warn(
            f"{drift_count} drifted, {error_count} error(s)",
            "re-run without --check (and with --write to apply) to upgrade.",
        )
        return 1

    # ── Write mode: overwrite drifted files ─────────────────────────────
    if not getattr(args, "write", False):
        wizard.warn(
            f"{drift_count} drifted file(s)",
            "Re-run with --write to overwrite the project copy with the "
            "bundled template (use --yes to skip per-file confirmation).",
        )
        return 1

    auto_yes = bool(getattr(args, "yes", False))
    written = 0
    for rel, status, _msg, bundled, project in results:
        if status != "drift":
            continue
        if not auto_yes:
            try:
                resp = input(f"Overwrite {rel}? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                wizard.warn("Cancelled by user — partial refresh", "")
                return 1
            if resp not in ("y", "yes"):
                print(f"  skipped: {rel}")
                continue
        try:
            project.parent.mkdir(parents=True, exist_ok=True)
            project.write_text(bundled.read_text())
            wizard.ok(f"  wrote: {rel}", "")
            written += 1
        except OSError as e:
            wizard.fail(f"  failed: {rel}", str(e))
            return 1

    if written:
        wizard.ok(
            f"Refreshed {written} file(s)",
            "Diff against your prior version with `git diff` to spot any "
            "project-specific tweaks you want to re-apply on top.",
        )
    else:
        wizard.warn(
            "No files written",
            "Every drifted file was skipped — re-run with --yes to apply "
            "without per-file prompting.",
        )

    # Optional: regenerate the project-root README with a "Project
    # status" section reflecting current step inventory + synthesis
    # deliverables. Idempotent; safe to run repeatedly.
    if getattr(args, "regen_readme", False):
        from research_os.project_ops import regenerate_root_readme

        try:
            res = regenerate_root_readme(workspace)
            wizard.ok(
                f"Regenerated {res['path']}",
                f"{res['step_count']} step(s) + "
                f"{len(res['deliverables'])} synthesis deliverable(s) listed.",
            )
        except Exception as e:  # noqa: BLE001
            wizard.fail("README regeneration failed", str(e))
            return 1

    return 0


# ---------------------------------------------------------------------------
# completion
# ---------------------------------------------------------------------------


# Top-level subcommand names recognized by the CLI. Kept in one place so
# the fish completion script and the argparse subparser registry stay in
# sync (the test suite cross-checks these).
SUBCOMMANDS_FOR_COMPLETION = (
    "init", "ide", "mcp", "hermes", "skills", "route", "api-key", "start",
    "daemon", "doctor", "refresh", "completion",
)


_FISH_COMPLETION_TEMPLATE = """\
# research-os fish completion
# Generated by `research-os completion fish`.
# Source via: research-os completion fish | source

complete -c research-os -f

# Top-level subcommands.
function __research_os_no_subcommand
    set -l cmd (commandline -opc)
    set -l subs {sub_list}
    if test (count $cmd) -le 1
        return 0
    end
    for token in $cmd[2..-1]
        for s in $subs
            if test "$token" = "$s"
                return 1
            end
        end
    end
    return 0
end

{sub_complete_block}

# init flags
complete -c research-os -n '__fish_seen_subcommand_from init' -l name -d 'Project name'
complete -c research-os -n '__fish_seen_subcommand_from init' -l domain -d 'Domain hint'
complete -c research-os -n '__fish_seen_subcommand_from init' -l question -d 'Initial research question'
complete -c research-os -n '__fish_seen_subcommand_from init' -l ide -d 'IDE(s) to wire' -xa "{ide_choices}"
complete -c research-os -n '__fish_seen_subcommand_from init' -l force -d 'Re-scaffold even if workspace exists'
complete -c research-os -n '__fish_seen_subcommand_from init' -s y -l yes -d 'Skip the wizard'
complete -c research-os -n '__fish_seen_subcommand_from init' -l no-color -d 'Disable ANSI styling'
complete -c research-os -n '__fish_seen_subcommand_from init' -l preflight -d 'Run repo preflight after scaffold'

# ide subcommand
complete -c research-os -n '__fish_seen_subcommand_from ide' -xa 'list add remove config-path'

# start flags
complete -c research-os -n '__fish_seen_subcommand_from start' -l workspace -d 'Pin to a workspace path' -r
complete -c research-os -n '__fish_seen_subcommand_from start' -l transport -d 'MCP transport' -xa 'stdio sse'

# doctor flags
complete -c research-os -n '__fish_seen_subcommand_from doctor' -l verbose -d 'Show fix hints for passing checks'
complete -c research-os -n '__fish_seen_subcommand_from doctor' -l workspace-only -d 'Skip install checks'
complete -c research-os -n '__fish_seen_subcommand_from doctor' -l workspace -d 'Explicit workspace path' -r
complete -c research-os -n '__fish_seen_subcommand_from doctor' -l json -d 'Emit JSON report'
complete -c research-os -n '__fish_seen_subcommand_from doctor' -l no-color -d 'Disable ANSI styling'

# refresh flags
complete -c research-os -n '__fish_seen_subcommand_from refresh' -l check -d 'Report only; exit 1 on drift'
complete -c research-os -n '__fish_seen_subcommand_from refresh' -l write -d 'Overwrite drifted files'
complete -c research-os -n '__fish_seen_subcommand_from refresh' -s y -l yes -d 'Skip per-file confirmation'
complete -c research-os -n '__fish_seen_subcommand_from refresh' -l workspace -d 'Explicit workspace path' -r
complete -c research-os -n '__fish_seen_subcommand_from refresh' -l json -d 'Emit JSON report'
complete -c research-os -n '__fish_seen_subcommand_from refresh' -l no-color -d 'Disable ANSI styling'

# completion subcommand
complete -c research-os -n '__fish_seen_subcommand_from completion' -xa 'bash zsh fish'
"""


def _build_fish_completion() -> str:
    """Hand-rolled fish completion script for the research-os CLI."""
    sub_list = " ".join(SUBCOMMANDS_FOR_COMPLETION)
    # Per-subcommand top-level entries with short descriptions.
    sub_descriptions = {
        "init": "Scaffold a Research OS workspace",
        "ide": "Add / remove / list AI IDE MCP configs",
        "start": "Run the MCP server",
        "doctor": "Diagnose install + workspace health",
        "refresh": "Refresh project template copies from bundled sources",
        "completion": "Print shell completion script",
    }
    lines = []
    for name in SUBCOMMANDS_FOR_COMPLETION:
        desc = sub_descriptions.get(name, "")
        lines.append(
            f"complete -c research-os -n '__research_os_no_subcommand' "
            f"-xa '{name}' -d '{desc}'"
        )
    return _FISH_COMPLETION_TEMPLATE.format(
        sub_list=sub_list,
        sub_complete_block="\n".join(lines),
        ide_choices=" ".join(IDE_CHOICES_FOR_COMPLETION),
    )


def _build_bash_zsh_completion(shell: str) -> str:
    """Use argcomplete to emit a bash/zsh completion script when available.

    Falls back to a minimal hand-rolled script when argcomplete isn't
    installed so the subcommand still works without the optional extra.
    """
    try:
        import shlex
        import subprocess as _sub
        # argcomplete ships a console script `register-python-argcomplete`.
        # It emits a sh-eval'able snippet. For zsh, it auto-detects via
        # `-s zsh`; for bash, the default mode works.
        cmd = ["register-python-argcomplete"]
        if shell == "zsh":
            cmd += ["-s", "zsh"]
        cmd += ["research-os"]
        try:
            out = _sub.check_output(cmd, text=True, stderr=_sub.DEVNULL)
            return out
        except (OSError, _sub.CalledProcessError):
            # Fall through to fallback below.
            pass
        # Try the python module form.
        cmd = [sys.executable, "-m", "argcomplete.scripts.register_python_argcomplete"]
        if shell == "zsh":
            cmd += ["-s", "zsh"]
        cmd += ["research-os"]
        try:
            out = _sub.check_output(cmd, text=True, stderr=_sub.DEVNULL)
            return out
        except (OSError, _sub.CalledProcessError):
            pass
        _ = shlex  # keep import side-effect free for linters
    except Exception:
        pass
    # Fallback: minimal hand-rolled completion covering subcommands +
    # --ide values. Works without argcomplete.
    subs = " ".join(SUBCOMMANDS_FOR_COMPLETION)
    ides = " ".join(IDE_CHOICES_FOR_COMPLETION)
    if shell == "zsh":
        return (
            "#compdef research-os\n"
            "# Minimal fallback completion (argcomplete not installed).\n"
            "_research_os() {\n"
            "  local -a subs ides\n"
            f"  subs=({subs})\n"
            f"  ides=({ides})\n"
            "  if (( CURRENT == 2 )); then\n"
            "    compadd -- $subs\n"
            "    return\n"
            "  fi\n"
            "  if [[ $words[2] == init && $words[CURRENT-1] == --ide ]]; then\n"
            "    compadd -- $ides\n"
            "    return\n"
            "  fi\n"
            "}\n"
            "compdef _research_os research-os\n"
        )
    # bash
    return (
        "# Minimal fallback completion (argcomplete not installed).\n"
        "_research_os() {\n"
        '  local cur prev words cword\n'
        '  _init_completion 2>/dev/null || {\n'
        '    cur="${COMP_WORDS[COMP_CWORD]}"\n'
        '    prev="${COMP_WORDS[COMP_CWORD-1]}"\n'
        "  }\n"
        f'  local subs="{subs}"\n'
        f'  local ides="{ides}"\n'
        '  if [[ $COMP_CWORD -eq 1 ]]; then\n'
        '    COMPREPLY=( $(compgen -W "$subs" -- "$cur") )\n'
        "    return 0\n"
        "  fi\n"
        '  if [[ "$prev" == "--ide" ]]; then\n'
        '    COMPREPLY=( $(compgen -W "$ides" -- "$cur") )\n'
        "    return 0\n"
        "  fi\n"
        "}\n"
        "complete -F _research_os research-os\n"
    )


def cmd_completion(args: argparse.Namespace) -> int:
    """Print a sourceable shell completion script."""
    shell = args.shell
    if shell == "fish":
        sys.stdout.write(_build_fish_completion())
    elif shell in ("bash", "zsh"):
        sys.stdout.write(_build_bash_zsh_completion(shell))
    else:
        # Should never hit — argparse `choices=` enforces this.
        print(
            f"  {_cross()} Unsupported shell: {shell}. "
            "Choose one of: bash, zsh, fish.",
            file=sys.stderr,
        )
        return 2
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-os",
        description=(
            "Research OS — an MCP-native research operating system.\n\n"
            "Four commands:\n"
            "  research-os init    scaffold a workspace ready for any AI IDE\n"
            "  research-os ide     add / remove / list AI IDE MCP configs\n"
            "  research-os start   run the MCP server (your IDE auto-launches it)\n"
            "  research-os doctor  diagnose install + workspace health\n\n"
            "Research OS does NOT manage LLM provider keys. Your AI client\n"
            "(Claude Code, OpenCode, Antigravity, Cursor, Claude Desktop,\n"
            "VS Code, Windsurf, Continue, Aider, ...) owns model access.\n\n"
            "Documentation: docs/START.md · docs/RESEARCHER_GUIDE.md ·\n"
            "               docs/USE_CASES.md · docs/TOOLS.md · docs/PROTOCOLS.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version",
                        version=f"research-os {__version__}")
    sub = parser.add_subparsers(dest="command")

    # ── init ────────────────────────────────────────────────────────────
    p_init = sub.add_parser(
        "init",
        help="Initialise a Research OS workspace (interactive by default).",
        description=(
            "Scaffold a workspace directory ready for AI-driven research.\n\n"
            "By default launches a 6-step interactive wizard with arrow-key\n"
            "navigation, multi-select IDE wiring, paper auto-download, and\n"
            "a paste-helper for notes / Slack threads / emails. Skip the\n"
            "wizard with --yes, or by piping stdin (CI / scripts).\n\n"
            "Examples:\n"
            "  research-os init                              # interactive wizard\n"
            "  research-os init my-project --yes             # one-shot, no prompts\n"
            "  research-os init my-project --name 'Cohort'   # explicit name\n"
            "  research-os init . --force                    # re-scaffold an existing folder\n"
            "  research-os init --ide cursor,claude          # only those two IDEs\n"
            "  research-os init --no-color                   # disable ANSI styling"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_init.add_argument("directory", nargs="?", default=None,
                        help="Target directory (default: current directory).")
    p_init.add_argument("--name", help="Project name (default: directory name).")
    p_init.add_argument("--domain",
                        help="Domain hint (clinical / nlp / genomics / ...). Optional.")
    p_init.add_argument("--question",
                        help="Initial research question. Refined later by the AI.")
    p_init.add_argument("--questions", action="append", default=None,
                        help="Add a research question (repeatable). Builds a list.")
    p_init.add_argument("--workspace-mode", dest="workspace_mode",
                        choices=["analysis", "tool_build", "exploration",
                                 "notebook", "multi_study", "hybrid"],
                        default=None,
                        help="What kind of work this is. "
                             "analysis (default) = linear analysis steps; "
                             "tool_build = governed software build; "
                             "exploration = scratch-first probes; "
                             "notebook = Jupyter-first notebook project; "
                             "multi_study = multi-study program (portfolio "
                             "+ cross-study meta-analysis); "
                             "hybrid = research + software (analysis steps "
                             "plus an inner software component).")
    p_init.add_argument("--mcp-scope", dest="mcp_scope",
                        choices=["workspace", "global"], default="workspace",
                        help="Where to register the MCP server. workspace "
                             "(default) = per-project config files. global = "
                             "also print the user-scope install command so "
                             "research-os is available in every project. "
                             "Either way, RESTART your IDE afterwards.")
    _ide_arg = p_init.add_argument(
        "--ide", default="auto",
        help="IDE(s) to wire up. Default 'auto' detects your single IDE "
             "from the environment (wires nothing extra if unsure). "
             "Or pass 'all', 'none', or a comma-separated list. "
             "Valid names: " + ", ".join(VALID_IDES)
             + " (plus 'auto', 'all', 'none').",
    )
    # Attach argcomplete completer hook (no-op when argcomplete absent).
    _ide_arg.completer = lambda **kw: list(IDE_CHOICES_FOR_COMPLETION)
    p_init.add_argument(
        "--hermes", dest="hermes", action="store_true", default=None,
        help="Wire Research-OS into Hermes (the self-improving agent layer) "
             "after scaffolding: registers the RO MCP server + skill in "
             "~/.hermes/config.yaml. Default: ask in the wizard.",
    )
    p_init.add_argument(
        "--no-hermes", dest="hermes", action="store_false",
        help="Skip wiring Research-OS into Hermes during init.",
    )
    p_init.add_argument("--force", action="store_true",
                        help="Re-scaffold even if the workspace already exists.")
    p_init.add_argument("-y", "--yes", action="store_true",
                        help="Skip the wizard and use defaults + provided flags.")
    p_init.add_argument("--non-interactive", dest="no_interactive", action="store_true",
                        help="Alias for --yes.")
    p_init.add_argument("--no-color", action="store_true",
                        help="Disable ANSI styling. Auto-disabled when NO_COLOR is set.")
    p_init.add_argument("--preflight", action="store_true",
                        help="After scaffolding, run the repo's preflight (dev only).")
    p_init.add_argument("--migrate", action="store_true",
                        help=(
                            "Migrate an existing project to the v5 config layout. "
                            "Reads inputs/researcher_config.yaml (if present) and writes "
                            ".os_state/config.yaml + ~/.research-os/profile.yaml. "
                            "Idempotent and safe — the old config is never modified. "
                            "Does NOT run the scaffold wizard."
                        ))

    # ── ide ─────────────────────────────────────────────────────────────
    p_ide = sub.add_parser(
        "ide",
        help="Add / remove / list AI IDE MCP configs in this workspace.",
        description=(
            "Manage which AI IDEs are wired up in the current workspace —\n"
            "without re-running `research-os init` (which would re-scaffold\n"
            "the whole tree). Walks up the directory tree for `.os_state/`\n"
            "to find the workspace.\n\n"
            "Examples:\n"
            "  research-os ide list                # show which IDEs are wired\n"
            "  research-os ide add cursor          # add Cursor MCP config\n"
            "  research-os ide add windsurf aider  # add several at once\n"
            "  research-os ide remove opencode     # remove OpenCode config"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ide.add_argument("action", choices=["list", "add", "remove", "config-path"],
                       help="What to do. `config-path <name>` prints the expected MCP config path for one IDE.")
    p_ide.add_argument("names", nargs="*",
                       help="IDE names (required for add / remove / config-path).")
    p_ide.add_argument("--no-color", action="store_true",
                       help="Disable ANSI styling.")

    # ── mcp ─────────────────────────────────────────────────────────────
    p_mcp = sub.add_parser(
        "mcp",
        help="Compose third-party MCP servers (Slack, GitHub, Postgres, ...) into IDE configs.",
        description=(
            "Manage OTHER MCP servers wired into your IDE configs. Additive to\n"
            "`research-os ide add`, which wires the Research-OS server itself.\n\n"
            "Examples:\n"
            "  research-os mcp list\n"
            "  research-os mcp template --name slack\n"
            "  research-os mcp add my-server --command npx --args -y,@scope/server\n"
            "  research-os mcp remove my-server\n"
            "  research-os mcp add foo --command npx --args -y,@x --ide cursor,claude"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_mcp.add_argument("action", choices=["list", "add", "remove", "template"],
                       help="What to do.")
    p_mcp.add_argument("name", nargs="?", default=None,
                       help="Server name (for add/remove) or template key (for template).")
    p_mcp.add_argument("--name", dest="name_flag",
                       help="Alternate way to supply --name; positional 'name' takes precedence.")
    p_mcp.add_argument("--command", dest="mcp_command",
                       help="Command to run the MCP server (e.g. 'npx').")
    p_mcp.add_argument("--args", dest="mcp_args",
                       help="Comma- or space-separated args list for the command "
                            "(e.g. '-y,@scope/server-name').")
    p_mcp.add_argument("--ide", default="wired",
                       help="Which IDE config(s) to update. 'wired' (default) = "
                            "every wired IDE that supports mcpServers; 'all' is an "
                            "alias; or pass a comma-separated list (cursor,claude,...).")
    p_mcp.add_argument("--as-name", dest="as_name",
                       help="Override the name a template is registered under "
                            "(default: the template's own key).")
    p_mcp.add_argument("--no-color", action="store_true",
                       help="Disable ANSI styling.")

    # ── hermes ──────────────────────────────────────────────────────────
    p_hermes = sub.add_parser(
        "hermes",
        help="Wire Research-OS into Hermes Agent (~/.hermes/config.yaml).",
        description=(
            "Make Research-OS a first-class citizen inside Hermes Agent.\n"
            "Registers the RO MCP server under mcp_servers: and installs the\n"
            "canonical RO skill so the agent loads it automatically. The edit\n"
            "is comment-preserving, idempotent, and reversible.\n\n"
            "Examples:\n"
            "  research-os hermes add        # auto-detect launch command\n"
            "  research-os hermes status\n"
            "  research-os hermes remove\n"
            "  research-os hermes add --url http://127.0.0.1:8765/mcp\n"
            "  research-os hermes add --command research-os --args start"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_hermes.add_argument("action", choices=["add", "remove", "status"],
                          help="What to do.")
    p_hermes.add_argument("--command", dest="hermes_command",
                          help="Command to launch the RO MCP server (stdio). "
                               "Defaults to the installed `research-os` script "
                               "or `python -m research_os.server`.")
    p_hermes.add_argument("--args", dest="mcp_args",
                          help="Comma- or space-separated args for --command.")
    p_hermes.add_argument("--url", dest="url",
                          help="Register an HTTP/SSE endpoint instead of a "
                               "stdio command.")
    p_hermes.add_argument("--config", dest="config",
                          help="Path to the Hermes config (default: "
                               "$HERMES_CONFIG or ~/.hermes/config.yaml).")
    p_hermes.add_argument("--no-color", action="store_true",
                          help="Disable ANSI styling.")

    # ── skills ──────────────────────────────────────────────────────────
    p_skills = sub.add_parser(
        "skills",
        help="Manage science-skill libraries (K-Dense scientific-agent-skills).",
        description=(
            "Bring case-specific scientific capability into Research-OS.\n"
            "`add-science-pack` clones the community K-Dense scientific-agent-\n"
            "skills library (140 MIT skills in the open Agent-Skills standard)\n"
            "and wires it into Hermes so the AI loads the right domain skill\n"
            "(bulk-rnaseq, experimental-design, literature-review, rdkit, ...)\n"
            "alongside RO's guidance. IDEs on the Agent-Skills standard can\n"
            "point at the same skills/ dir.\n\n"
            "Examples:\n"
            "  research-os skills add-science-pack\n"
            "  research-os skills add-science-pack --ref v1.2.3 --dest ~/sci-skills\n"
            "  research-os skills list-science"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_skills.add_argument("action",
                          choices=["add-science-pack", "list-science"],
                          help="What to do.")
    p_skills.add_argument("--ref", dest="skills_ref", default=None,
                          help="Git ref (tag/branch/commit) to pin. Default: main.")
    p_skills.add_argument("--dest", dest="skills_dest", default=None,
                          help="Where to clone (default: a shared data dir).")
    p_skills.add_argument("--no-hermes", dest="skills_no_hermes",
                          action="store_true",
                          help="Clone only; don't wire into Hermes.")

    # ── route ───────────────────────────────────────────────────────────
    p_route = sub.add_parser(
        "route",
        help="Preview the protocol router for a prompt (no IDE needed).",
        description=(
            "Run the same hierarchical router the MCP `tool_route` uses and\n"
            "print the routing decision: matched protocol, intent class,\n"
            "planned tool sequence, and alternatives. Read-only — never\n"
            "persists an active plan. Run inside a workspace for state-aware\n"
            "routing, or anywhere for a stateless preview.\n\n"
            "Examples:\n"
            '  research-os route "fit a mixed-effects model to my data"\n'
            '  research-os route "draft the methods section" --json'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_route.add_argument("prompt", help="The request to route.")
    p_route.add_argument("--json", action="store_true",
                         help="Emit the raw routing decision as JSON.")
    p_route.add_argument("--no-color", action="store_true",
                         help="Disable ANSI styling.")

    # ── api-key ─────────────────────────────────────────────────────────
    p_api = sub.add_parser(
        "api-key",
        help="Manage api_keys in inputs/researcher_config.yaml (chmod 600 + hidden prompts).",
        description=(
            "Add / rotate / list / remove / test API keys for free-tier research\n"
            "providers (Semantic Scholar, PubMed, Crossref, OpenAlex, ...).\n"
            "Stored in inputs/researcher_config.yaml under api_keys:; every write\n"
            "re-applies chmod 600. Hidden input via getpass for add and rotate.\n\n"
            "Examples:\n"
            "  research-os api-key list\n"
            "  research-os api-key add semantic_scholar          # prompts via getpass\n"
            "  research-os api-key add openai --from-env OPENAI_API_KEY  # for CI\n"
            "  research-os api-key rotate pubmed                 # prompts via getpass\n"
            "  research-os api-key test pubmed                   # 1-token round-trip\n"
            "  research-os api-key remove crossref"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_api.add_argument("action", choices=["add", "list", "rotate", "remove", "test"],
                       help="What to do.")
    p_api.add_argument("provider", nargs="?", default=None,
                       help="Provider name (e.g. semantic_scholar, pubmed, crossref). "
                            "Required for add/rotate/remove/test; ignored for list.")
    p_api.add_argument("--from-env", dest="from_env", default=None,
                       help="Read the key from this environment variable instead of "
                            "prompting (used in CI).")
    p_api.add_argument("--no-color", action="store_true",
                       help="Disable ANSI styling.")

    # ── start ───────────────────────────────────────────────────────────
    p_start = sub.add_parser(
        "start",
        help="Start the Research OS MCP server (global — one server, many projects).",
        description=(
            "Run the Research OS MCP server. Your AI IDE connects via stdio.\n"
            "Install once, share across all your projects. The active project\n"
            "is resolved per-request via $RESEARCH_OS_WORKSPACE, or by walking\n"
            "the CWD up to find `.os_state/`."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_start.add_argument("--workspace", default=None,
                        help="(Back-compat) Pin this server to a specific workspace path.")
    p_start.add_argument("--transport", choices=["stdio", "sse"], default="stdio",
                        help="MCP transport (default: stdio).")

    # ── daemon ──────────────────────────────────────────────────────────
    # The daemon: persistent localhost service that runs jobs,
    # journals/recovers runs, enforces gates, and notifies.
    p_daemon = sub.add_parser(
        "daemon",
        help="Run / inspect the Research-OS daemon (execution + enforcement kernel).",
        description=(
            "The Research OS daemon is a persistent, headless, localhost\n"
            "service that owns the master execution state machine: it runs\n"
            "long jobs, journals every run and recovers them across restarts,\n"
            "enforces hard gates, and notifies the researcher. It offers a\n"
            "sandbox tier (opt-in for security). RO calls no LLM and has no\n"
            "chat gateway. A read-only web dashboard is the one piece still\n"
            "to come.\n\n"
            "OPTIONAL: with no daemon running, Research OS works exactly as\n"
            "the stdio MCP server — the daemon only adds durable execution,\n"
            "recovery, enforcement, and notifications.\n\n"
            "Examples:\n"
            "  research-os daemon status            # show daemon + project state\n"
            "  research-os daemon status --json     # machine-readable\n"
            "  research-os daemon start             # run the localhost service"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    daemon_sub = p_daemon.add_subparsers(dest="daemon_command")
    pd_status = daemon_sub.add_parser(
        "status", help="Show daemon + active-project state (read-only)."
    )
    pd_status.add_argument("--json", dest="as_json", action="store_true",
                           help="Emit machine-readable JSON.")
    pd_status.add_argument("--workspace", default=None,
                           help="Explicit workspace path (else auto-resolved).")
    pd_start = daemon_sub.add_parser(
        "start", help="Start the daemon serving loop (localhost HTTP, read-only API)."
    )
    pd_start.add_argument("--workspace", default=None,
                          help="Explicit workspace path (else auto-resolved).")
    pd_start.add_argument("--host", default=None, help="Bind host (default 127.0.0.1).")
    pd_start.add_argument("--port", default=None, type=int, help="Bind port (default 8787).")
    pd_start.add_argument(
        "--background", action="store_true",
        help="Launch detached (nohup) and return — for shared/HPC nodes with no "
             "systemd/Docker. Logs to .os_state/daemon.log; stop with "
             "`research-os daemon stop`.")

    # setup: one-shot shared-server-friendly setup — pick a free port, check the
    # conda/PATH wiring, and print the exact background-launch command.
    pd_setup = daemon_sub.add_parser(
        "setup",
        help="Prepare the daemon for THIS machine (free port, conda/PATH check, "
             "background-launch command). Ideal for no-Docker conda HPC nodes.",
    )
    pd_setup.add_argument("--workspace", default=None,
                          help="Explicit workspace path (else auto-resolved).")
    pd_setup.add_argument("--port", default=None, type=int,
                          help="Preferred port (else auto-pick a free one).")
    pd_setup.add_argument("--start", action="store_true",
                          help="Also start the daemon in the background now.")

    # stop: gracefully terminate THIS project's running daemon (per-project).
    pd_stop = daemon_sub.add_parser(
        "stop",
        help="Stop this project's running daemon (graceful; per-project).",
    )
    pd_stop.add_argument("--workspace", default=None,
                         help="Explicit workspace path (else auto-resolved).")

    # run: execute any command as a tracked, provenance-recording run.
    pd_run = daemon_sub.add_parser(
        "run",
        help="Run a command as a tracked job (provenance + artifacts recorded).",
        description=(
            "Execute any shell command as a Research OS run. The command's\n"
            "output streams to your terminal; on completion a durable record\n"
            "(command, environment, git commit, input/output artifact hashes,\n"
            "timestamps) is written to .os_state/runs/<id>/. This is the\n"
            "human door to the same durable-run machinery the daemon API uses.\n\n"
            "Examples:\n"
            "  research-os daemon run -- python analyze.py --in data.csv\n"
            "  research-os daemon run --name fig3 -- Rscript plot.R\n"
            "  research-os daemon run --json -- snakemake -j4"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pd_run.add_argument("--workspace", default=None,
                        help="Explicit workspace path (else auto-resolved).")
    pd_run.add_argument("--name", default=None, help="Human label for the run.")
    pd_run.add_argument("--cwd", default=None,
                        help="Working directory for the command (default: workspace root).")
    pd_run.add_argument("--no-artifacts", dest="no_artifacts", action="store_true",
                        help="Skip output-artifact detection for this run.")
    pd_run.add_argument("--input", dest="inputs", action="append", default=[],
                        metavar="PATH",
                        help="Declare an input file (hashed for provenance + "
                             "lineage linking). Repeatable.")
    pd_run.add_argument("--shell", dest="force_shell", action="store_true",
                        help="Run the command through a shell (enables pipes, "
                             "redirects, &&). Auto-detected for single-string "
                             "commands containing shell metacharacters.")
    pd_run.add_argument("--json", dest="as_json", action="store_true",
                        help="Emit the run manifest as JSON on completion.")
    pd_run.add_argument("cmd", nargs=argparse.REMAINDER,
                        help="The command to run (use -- to separate it from flags).")

    # docker: run a command inside a container image as a tracked job.
    pd_docker = daemon_sub.add_parser(
        "docker",
        help="Run a command inside a container image as a tracked, "
             "reproducible job (records the image digest in provenance).",
        description=(
            "Run a long, reproducible job inside a Docker/Podman image through\n"
            "the daemon. Same durable-run machinery as `daemon run` (provenance,\n"
            "artifacts, journal, stall watch) plus the exact image + digest are\n"
            "recorded so the run is recreatable bit-for-bit. The project root is\n"
            "mounted into the container so outputs land back in the workspace.\n\n"
            "Examples:\n"
            "  research-os daemon docker myimg:1.0 -- python run.py --in data.csv\n"
            "  research-os daemon docker --gpus all torch:2 -- python train.py\n"
            "  research-os daemon docker --network biotools:latest -- nextflow run ."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pd_docker.add_argument("--workspace", default=None,
                           help="Explicit workspace path (else auto-resolved).")
    pd_docker.add_argument("--name", default=None, help="Human label for the run.")
    pd_docker.add_argument("--cwd", default=None,
                           help="Working dir inside the container (default: workspace root).")
    pd_docker.add_argument("--gpus", default=None,
                           help="GPUs to expose (e.g. 'all', '0,1') — passed to --gpus.")
    pd_docker.add_argument("--network", action="store_true",
                           help="Allow host networking (default: isolated, no network).")
    pd_docker.add_argument("--input", dest="inputs", action="append", default=[],
                           metavar="PATH",
                           help="Declare an input file (hashed for provenance). Repeatable.")
    pd_docker.add_argument("--json", dest="as_json", action="store_true",
                           help="Emit the run manifest as JSON on completion.")
    pd_docker.add_argument("image", help="Container image (tag or digest).")
    pd_docker.add_argument("cmd", nargs=argparse.REMAINDER,
                           help="The command to run in the container (use -- to separate).")

    # runs: list the durable run history.
    pd_runs = daemon_sub.add_parser(
        "runs", help="List recorded runs (durable history) for the workspace."
    )
    pd_runs.add_argument("--workspace", default=None,
                         help="Explicit workspace path (else auto-resolved).")
    pd_runs.add_argument("--limit", default=20, type=int, help="Max runs to show.")
    pd_runs.add_argument("--json", dest="as_json", action="store_true",
                         help="Emit machine-readable JSON.")

    # logs: show one run's manifest + captured log.
    pd_logs = daemon_sub.add_parser(
        "logs", help="Show a recorded run's details + captured output."
    )
    pd_logs.add_argument("run_id", help="The run id (from 'daemon runs').")
    pd_logs.add_argument("--workspace", default=None,
                         help="Explicit workspace path (else auto-resolved).")
    pd_logs.add_argument("--tail", default=0, type=int,
                         help="Show only the last N log lines (0 = full log).")
    pd_logs.add_argument("--json", dest="as_json", action="store_true",
                         help="Emit the full manifest as JSON.")

    # reproduce: re-run a recorded run and compare its outputs.
    pd_repro = daemon_sub.add_parser(
        "reproduce",
        help="Re-run a recorded run and check its outputs still match.",
    )
    pd_repro.add_argument("run_id", help="The run id to reproduce (from 'daemon runs').")
    pd_repro.add_argument("--workspace", default=None,
                          help="Explicit workspace path (else auto-resolved).")
    pd_repro.add_argument("--cwd", default=None,
                          help="Override the working directory for the re-run.")
    pd_repro.add_argument("--timeout", default=0, type=float,
                          help="Max seconds to wait for the re-run (0 = no limit).")
    pd_repro.add_argument("--json", dest="as_json", action="store_true",
                          help="Emit the full reproduction report as JSON.")

    # submit: hand a job to an HPC scheduler (SLURM, …).
    pd_submit = daemon_sub.add_parser(
        "submit",
        help="Submit a job to an HPC scheduler (SLURM) with full provenance.",
    )
    pd_submit.add_argument("script",
                           help="Batch script path, or inline command string.")
    pd_submit.add_argument("--scheduler", default="slurm",
                           help="Scheduler backend (default: slurm).")
    pd_submit.add_argument("--workspace", default=None,
                           help="Explicit workspace path (else auto-resolved).")
    pd_submit.add_argument("--cwd", default=None,
                           help="Working directory for the job (default: workspace).")
    pd_submit.add_argument("--name", default=None, help="Human-friendly job name.")
    pd_submit.add_argument("--poll", default=5.0, type=float,
                           help="Scheduler poll interval in seconds (default: 5).")
    pd_submit.add_argument("--json", dest="as_json", action="store_true",
                           help="Emit the submitted job id as JSON.")

    # diff: compare two recorded runs (the experiment diff).
    pd_diff = daemon_sub.add_parser(
        "diff",
        help="Compare two recorded runs: command, context (git/env), outputs.",
    )
    pd_diff.add_argument("run_a", help="Baseline run id.")
    pd_diff.add_argument("run_b", help="New run id to compare against the baseline.")
    pd_diff.add_argument("--workspace", default=None,
                         help="Explicit workspace path (else auto-resolved).")
    pd_diff.add_argument("--json", dest="as_json", action="store_true",
                         help="Emit the full diff report as JSON.")

    # lineage: the content-addressed run dependency graph.
    pd_lin = daemon_sub.add_parser(
        "lineage",
        help="Show the run dependency graph (which run's output fed which run).",
        description=(
            "Build the provenance DAG: run B depends on run A when one of B's\n"
            "input hashes matches one of A's output artifact hashes. With a\n"
            "run id, show that run's ancestors (--upstream) or the runs that\n"
            "would go stale if you re-ran it (--downstream)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pd_lin.add_argument("run_id", nargs="?", default=None,
                        help="Focus on one run's lineage (omit for whole graph).")
    pd_lin.add_argument("--workspace", default=None,
                        help="Explicit workspace path (else auto-resolved).")
    pd_lin.add_argument("--upstream", action="store_true",
                        help="With run_id: show transitive ancestors (provenance).")
    pd_lin.add_argument("--downstream", action="store_true",
                        help="With run_id: show transitive descendants (impact).")
    pd_lin.add_argument("--limit", default=200, type=int,
                        help="Max recent runs to include in the graph.")
    pd_lin.add_argument("--json", dest="as_json", action="store_true",
                        help="Emit the lineage graph as JSON.")

    # stale: freshness check — which results were built from changed inputs.
    pd_stale = daemon_sub.add_parser(
        "stale",
        help="Check which runs are stale (inputs changed, or an upstream run is stale).",
        description=(
            "Freshness verdict over the lineage DAG. A run is input-stale when\n"
            "a file it recorded as an input now hashes differently on disk;\n"
            "transitive-stale when an upstream run it depends on is stale.\n"
            "Exit 0 = all fresh, 1 = at least one stale run found."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pd_stale.add_argument("--workspace", default=None,
                          help="Explicit workspace path (else auto-resolved).")
    pd_stale.add_argument("--limit", default=200, type=int,
                          help="Max recent runs to assess.")
    pd_stale.add_argument("--all", dest="show_all", action="store_true",
                          help="Show fresh + unknown runs too (default: only stale).")
    pd_stale.add_argument("--json", dest="as_json", action="store_true",
                          help="Emit the full freshness assessment as JSON.")

    # notifications: the spine outbox — what the daemon told the researcher.
    pd_ntfy = daemon_sub.add_parser(
        "notifications",
        help="Show the notification outbox (job completions, gate pages) + delivery.",
        description=(
            "The notification spine records every completion / page the daemon\n"
            "emitted, with whether delivery through the configured channel\n"
            "succeeded. Use --undelivered to see only what did NOT reach you."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pd_ntfy.add_argument("--workspace", default=None,
                         help="Explicit workspace path (else auto-resolved).")
    pd_ntfy.add_argument("--undelivered", action="store_true",
                         help="Only show notifications that did not reach the channel.")
    pd_ntfy.add_argument("--limit", default=100, type=int,
                         help="Max recent notifications to show.")
    pd_ntfy.add_argument("--json", dest="as_json", action="store_true",
                         help="Emit the outbox records as JSON.")

    # consent: the researcher's half of the un-skippable-gate loop.
    pd_consent = daemon_sub.add_parser(
        "consent",
        help="Review + approve/deny agent consent requests for gated actions.",
        description=(
            "When the AI hits a floor gate under a daemon it queues a consent\n"
            "request (sys_consent). This is how YOU authorize it:\n"
            "  research-os daemon consent              list pending + grants\n"
            "  research-os daemon consent approve <id> mint a one-shot token\n"
            "  research-os daemon consent deny <id>    refuse\n"
            "The agent can never self-grant — minting authority lives here."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pd_consent.add_argument("consent_action", nargs="?", default="list",
                            choices=["list", "approve", "deny"],
                            help="list (default), approve, or deny.")
    pd_consent.add_argument("request_id", nargs="?", default=None,
                            help="Request id (for approve/deny).")
    pd_consent.add_argument("--workspace", default=None,
                            help="Explicit workspace path (else auto-resolved).")
    pd_consent.add_argument("--json", dest="as_json", action="store_true",
                            help="Emit pending + grants as JSON.")

    # rebuild: re-run exactly the stale sub-DAG in dependency order.
    pd_rebuild = daemon_sub.add_parser(
        "rebuild",
        help="Re-run only the stale runs (in dependency order) to refresh results.",
        description=(
            "A minimal 'make' over the lineage DAG: find every stale run\n"
            "(input-stale or transitive-stale), order it producers-first, and\n"
            "reproduce each. Fixing an upstream result clears its descendants'\n"
            "transitive staleness, so a descendant only rebuilds if still stale\n"
            "when its turn comes. Use --dry-run to preview the plan."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pd_rebuild.add_argument("--workspace", default=None,
                            help="Explicit workspace path (else auto-resolved).")
    pd_rebuild.add_argument("--limit", default=200, type=int,
                            help="Max recent runs to assess.")
    pd_rebuild.add_argument("--dry-run", dest="dry_run", action="store_true",
                            help="Show the rebuild plan without executing.")
    pd_rebuild.add_argument("--timeout", default=None, type=float,
                            help="Per-run timeout (seconds) for each re-run.")
    pd_rebuild.add_argument("--json", dest="as_json", action="store_true",
                            help="Emit the rebuild report as JSON.")

    # domain: detect the project's research field + field-aware defaults.
    pd_domain = daemon_sub.add_parser(
        "domain",
        help="Detect the project's research field and show field-aware defaults.",
        description=(
            "Infer what field this project is in — from a declared\n"
            "`domain:` in researcher_config, else by scanning the project's\n"
            "files (markers + extensions). Prints the resolved profile:\n"
            "idiomatic languages, the artifacts that are the real\n"
            "deliverables, what reproducibility means in that field, and a\n"
            "one-line orientation. Use --list to see every built-in field."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pd_domain.add_argument("--workspace", default=None,
                           help="Explicit workspace path (else auto-resolved).")
    pd_domain.add_argument("--list", dest="list_all", action="store_true",
                           help="List every built-in domain profile and exit.")
    pd_domain.add_argument("--json", dest="as_json", action="store_true",
                           help="Emit the detection result as JSON.")

    # token: bearer token that guards the daemon's mutating endpoints.
    pd_token = daemon_sub.add_parser(
        "token",
        help="Show / mint the daemon's bearer token for mutating endpoints.",
        description=(
            "Inspect or mint the bearer token that guards the daemon's own\n"
            "mutating endpoints (/v1/runs, /v1/gates/respond, /v1/consent/*,\n"
            "…). Research-OS calls no LLM and has no chat gateway — this token\n"
            "is purely local write-authorization. When unset, mutating\n"
            "endpoints stay open behind the 127.0.0.1 bind. The token lives in\n"
            "an environment variable by design, never in config files.\n\n"
            "Examples:\n"
            "  research-os daemon token              # status\n"
            "  research-os daemon token --mint-token # generate a session token\n"
            "  research-os daemon token --json       # machine-readable"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pd_token.add_argument("--workspace", default=None,
                          help="Explicit workspace path (else auto-resolved).")
    pd_token.add_argument("--mint-token", dest="mint_token", action="store_true",
                          help="Generate a strong session token and exit.")
    pd_token.add_argument("--json", dest="as_json", action="store_true",
                          help="Emit token config as JSON.")

    # ── doctor ──────────────────────────────────────────────────────────
    p_doctor = sub.add_parser(
        "doctor",
        help="Diagnose install + workspace health (returns exit code 0/1/2).",
        description=(
            "Run a battery of health checks against the install and (if "
            "invoked inside a workspace) the workspace itself. Prints a\n"
            "coloured summary, exits 0 (all pass), 1 (warnings only), or\n"
            "2 (failures present).\n\n"
            "Checks include: python version, conda env, version consistency,\n"
            "pack registration, embeddings freshness, typst / chromium on\n"
            "PATH, IDE MCP wiring, orphan figures, stale step_summary,\n"
            "unresolved BLOCK gates, disk usage, git cleanliness, and\n"
            ".gitignore coverage.\n\n"
            "Examples:\n"
            "  research-os doctor                    # full report\n"
            "  research-os doctor --json             # machine-readable\n"
            "  research-os doctor --verbose          # show fix hints for passing checks\n"
            "  research-os doctor --workspace-only   # skip install checks\n"
            "  research-os doctor --workspace .      # explicit workspace path"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_doctor.add_argument("--verbose", action="store_true",
                          help="Show fix hints even for passing checks.")
    p_doctor.add_argument("--workspace-only", dest="workspace_only",
                          action="store_true",
                          help="Skip install checks; only run workspace checks.")
    p_doctor.add_argument("--workspace", default=None,
                          help="Explicit workspace path (default: walk up from CWD).")
    p_doctor.add_argument("--json", action="store_true",
                          help="Emit JSON instead of the human-readable report.")
    p_doctor.add_argument("--no-color", action="store_true",
                          help="Disable ANSI styling. Auto-disabled when NO_COLOR is set.")

    # ── refresh ─────────────────────────────────────────────────────────
    p_refresh = sub.add_parser(
        "refresh",
        help="Refresh project copies of AGENTS.md / CLAUDE.md / IDE rules from the bundled templates.",
        description=(
            "Detect drift between a project's copies of bundled templates\n"
            "(AGENTS.md, CLAUDE.md, .claude/rules/research-os.md, IDE rule\n"
            "files) and the version shipped with this `research-os` install.\n\n"
            "Templates evolve across releases; the wizard only copies them\n"
            "once at init, so a project that's been around for a few\n"
            "releases can be teaching the AI a stale tool surface or\n"
            "out-of-date hard rules. `refresh` shows the gap and (with\n"
            "--write) overwrites the project copies in place.\n\n"
            "Read-only by default. --check exits non-zero on drift so CI\n"
            "can fail if the project gets out of sync.\n\n"
            "Examples:\n"
            "  research-os refresh             # report drift (default)\n"
            "  research-os refresh --check     # report + exit 1 if drift\n"
            "  research-os refresh --write     # prompt per-file, overwrite\n"
            "  research-os refresh --write --yes  # overwrite every drifted file\n"
            "  research-os refresh --json      # machine-readable report"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_refresh.add_argument(
        "--check", action="store_true",
        help="Report only; exit non-zero if any project copy has drifted.",
    )
    p_refresh.add_argument(
        "--write", action="store_true",
        help="Overwrite drifted project copies with the bundled template.",
    )
    p_refresh.add_argument(
        "-y", "--yes", action="store_true",
        help="With --write, skip the per-file confirmation prompt.",
    )
    p_refresh.add_argument(
        "--regen-readme", action="store_true",
        help="Also regenerate the project-root README.md with the current "
             "step inventory + synthesis deliverable list (use at project "
             "finalize to refresh the GitHub front page).",
    )
    p_refresh.add_argument(
        "--workspace", default=None,
        help="Explicit workspace path (default: walk up from CWD).",
    )
    p_refresh.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of the human-readable report.",
    )
    p_refresh.add_argument(
        "--no-color", action="store_true",
        help="Disable ANSI styling. Auto-disabled when NO_COLOR is set.",
    )

    # ── completion ──────────────────────────────────────────────────────
    p_completion = sub.add_parser(
        "completion",
        help="Print a sourceable shell completion script (bash | zsh | fish).",
        description=(
            "Emit a shell-completion script for `research-os` to stdout.\n\n"
            "Install (zsh): eval \"$(research-os completion zsh)\"\n"
            "Install (bash): eval \"$(research-os completion bash)\"\n"
            "Install (fish): research-os completion fish | source\n\n"
            "Tab-completes subcommand names and --ide values."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_completion.add_argument(
        "shell",
        choices=["bash", "zsh", "fish"],
        help="Shell to emit completion script for.",
    )

    return parser


def main() -> None:
    parser = build_parser()

    # Activate argcomplete if the optional dep is installed; otherwise this
    # is a no-op. argcomplete short-circuits the process when invoked by the
    # shell-completion machinery.
    try:
        import argcomplete  # type: ignore
        argcomplete.autocomplete(parser)
    except ImportError:
        pass

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "ide":
        cmd_ide(args)
    elif args.command == "mcp":
        # Positional `name` wins over `--name`; argparse stores --name as name_flag.
        if not getattr(args, "name", None) and getattr(args, "name_flag", None):
            args.name = args.name_flag
        sys.exit(cmd_mcp(args))
    elif args.command == "hermes":
        sys.exit(cmd_hermes(args))
    elif args.command == "skills":
        sys.exit(cmd_skills(args))
    elif args.command == "route":
        sys.exit(cmd_route(args))
    elif args.command == "api-key":
        sys.exit(cmd_api_key(args))
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "daemon":
        sys.exit(cmd_daemon(args))
    elif args.command == "doctor":
        from research_os.cli_doctor import cmd_doctor
        sys.exit(cmd_doctor(args))
    elif args.command == "refresh":
        sys.exit(cmd_refresh(args))
    elif args.command == "completion":
        sys.exit(cmd_completion(args))
    else:
        parser.print_help()
        print()
        print("  Tip: 'research-os init' to scaffold, then open your IDE and chat with the AI.")


if __name__ == "__main__":
    main()
