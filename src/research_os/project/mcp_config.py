"""MCP configuration setup for per-IDE wiring.

Canonical implementations for dropping MCP configs and rule files.
``project_ops`` re-exports all public symbols for backward compatibility.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


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
    templates_dir = Path(__file__).resolve().parent.parent.parent.parent / "templates"

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
