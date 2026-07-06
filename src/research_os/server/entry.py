"""MCP server wiring + `main()` CLI entry point.

This module is the user-facing entry. It:
1. Annotates every TOOL_DEFINITIONS entry with pack=/status= metadata
   for sys_tool_describe / tool_tools_list filters.
2. Wires the MCP Server object + list_tools + call_tool handlers.
3. Provides `main()` for `research-os start`.

Keeps the file lean — the bulk of the work happens in dispatch.py,
registry.py, handlers/, and tool_definitions/.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from .aliases import _DEPRECATED_ALIASES, _REMOVED_TOOLS
from .dispatch import _handle_tool_call
from .envelopes import HAS_MCP, TextContent
from .registry import TOOL_DEFINITIONS
from .tool_surface import select_visible_tools


logger = logging.getLogger("research-os.server")


if HAS_MCP:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool


def _short_for_list(schema: dict) -> str:
    """Tight description used by list_tools — saves ~2K tokens per message.

    Resolution order:
        1. Explicit `short` field if present.
        2. First sentence of the full description, capped at 160 chars.
    The AI can call sys_tool_describe(name) for the full text on demand.

    Appends the ``then`` chain hint (when present) so the canonical
    boot-ritual sequence is self-reinforcing on every list_tools scan —
    small models that lose the MCP `instructions` field after the first
    turn still see "after this, call X" inline.
    """
    if isinstance(schema.get("short"), str) and schema["short"].strip():
        base = schema["short"].strip()
    else:
        full = schema.get("description", "")
        first = full.split(". ")[0].strip()
        if not first.endswith("."):
            first += "."
        base = first[:120]
    then = schema.get("then")
    if isinstance(then, str) and then.strip():
        return f"{base} then: {then.strip()}"
    return base


def _annotate_core_tool_metadata() -> None:
    """Backfill `pack` + `status` on every TOOL_DEFINITIONS entry.

    Pack/adapter loaders set these at registration time. Anything that
    doesn't yet have a `pack` field is therefore a core tool defined in
    this module. Aliases that still appear in TOOL_DEFINITIONS get
    status='alias'; anything in _REMOVED_TOOLS that leaked in gets
    status='deprecated' (and a logger warning — it's a bug).
    """
    for tool_name, schema in TOOL_DEFINITIONS.items():
        # 1) pack — anything not already set is core.
        schema.setdefault("pack", "core")
        # 2) status — alias > deprecated > live.
        if tool_name in _REMOVED_TOOLS:
            schema["status"] = "deprecated"
            logger.warning(
                "tool %r is in _REMOVED_TOOLS but still has a TOOL_DEFINITIONS "
                "entry. Remove the entry or drop it from _REMOVED_TOOLS.",
                tool_name,
            )
        elif tool_name in _DEPRECATED_ALIASES:
            schema["status"] = "alias"
        else:
            schema.setdefault("status", "live")


# ── One-time metadata annotation ─────────────────────────────────────
_annotate_core_tool_metadata()


# Phase-9 cross-cutting: MCP-level instructions surfaced at handshake.
# Any compliant MCP client (Claude Code, Cursor, Cline, etc.) will show
# these to the model on the first turn, removing the need for the AI to
# discover the canonical session-start ritual by calling sys_help first.
_MCP_INSTRUCTIONS = (
    'On every turn: '
    '(1) call sys_boot() once per session, '
    '(2) call tool_route(prompt="<user_message>") to identify the right protocol, '
    '(3) load returned protocol with sys_protocol_get(protocol_name="<resolved>", format="summary"), '
    '(4) call sys_active_tools(protocol_name="<resolved>") to scope your working tool set. '
    'PROGRESSIVE DISCLOSURE: the tool list advertised at handshake is a LEAN '
    'bootstrap surface (~25 core tools), NOT the full catalog (~160 tools). '
    'Every other tool is still fully callable by name — just call it. To '
    'find a tool you need, use sys_active_tools(protocol_name) (the shortlist '
    'for a protocol), tool_tools_list(mode="auto") (the catalog scoped to '
    'your workspace mode), sys_semantic_tool_search(query) (find a tool by '
    'what it does), or sys_tool_describe(tool_name) (one tool\'s full schema). '
    'Then dispatch the tool directly — it works even though it was not in the '
    'handshake list. Pack tools are loaded on-demand via tool_route routing. '
    'Each envelope ships next_recommended_call (string hint) and '
    'next_recommended_call_structured ({tool, arguments}) — strict tool-loop '
    'clients can dispatch the structured form directly.'
)


def _resolve_project_root() -> Path:
    """Resolve the active project root for the current request.

    Resolution order:
      1. RESEARCH_OS_WORKSPACE environment variable (set by IDE MCP
         config, typically to ${workspaceFolder}).
      2. Current working directory walked up to the nearest `.os_state/`
         (the project marker dropped by `research-os init`).
      3. Current working directory itself (last resort — tools that
         need a real workspace will report it gracefully).
    """
    env_root = os.environ.get("RESEARCH_OS_WORKSPACE", "").strip()
    if env_root:
        p = Path(env_root).expanduser().resolve()
        if p.exists():
            return p

    try:
        from research_os.utils.asset_manager import AssetManager
        detected = AssetManager.find_project_root()
        if (detected / ".os_state").exists():
            return detected
    except Exception:
        pass

    return Path.cwd().resolve()


def _inject_api_keys(root: Path) -> None:
    """Export literature / search API keys from researcher_config to env vars.

    Research OS does NOT manage LLM provider keys — your AI client owns that.
    Only research-data-source credentials (Semantic Scholar, PubMed, Crossref,
    Firecrawl, SerpAPI) are injected here, with SDK-friendly aliases.
    """
    try:
        import yaml as _yaml

        cfg_path = root / "inputs" / "researcher_config.yaml"
        if not cfg_path.exists():
            cfg_path = root / "researcher_config.yaml"
            if not cfg_path.exists():
                return
        cfg = _yaml.safe_load(cfg_path.read_text()) or {}
        api_keys = cfg.get("api_keys", {}) or {}
        allowed = {"semantic_scholar", "pubmed", "crossref", "firecrawl", "serpapi"}
        for key, value in api_keys.items():
            if not value or key not in allowed:
                continue
            env_name = key.upper()
            os.environ[env_name] = str(value)
            # SDK-compat aliases.
            if key == "semantic_scholar":
                os.environ["SEMANTIC_SCHOLAR_API_KEY"] = str(value)
                os.environ["S2_API_KEY"] = str(value)
            if key == "pubmed":
                os.environ["NCBI_API_KEY"] = str(value)
            if key == "firecrawl":
                os.environ["FIRECRAWL_API_KEY"] = str(value)
            if key == "serpapi":
                os.environ["SERPAPI_API_KEY"] = str(value)
    except Exception as e:  # pragma: no cover - non-fatal
        logger.debug(f"API key injection skipped: {e}")


# ── MCP server wiring ─────────────────────────────────────────────────
if HAS_MCP:
    # Read profile lazily inside list_tools so per-request resolution stays cheap.
    from ._helpers import _read_profile

    from research_os import __version__ as _RO_VERSION
    server = Server("research-os", version=_RO_VERSION, instructions=_MCP_INSTRUCTIONS)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        root = _resolve_project_root()
        profile = _read_profile(root)
        # Progressive disclosure: advertise only the configured surface
        # (default: the ~25-tool CORE bootstrap set). Every other tool is
        # still callable by name via call_tool — the AI reaches it through
        # tool_route / sys_active_tools / tool_tools_list / sys_tool_describe.
        visible = set(select_visible_tools(TOOL_DEFINITIONS, root))
        tools: list[Tool] = []
        for name, schema in TOOL_DEFINITIONS.items():
            if name not in visible:
                continue
            desc = _short_for_list(schema)
            if profile.get("model_profile") == "small":
                desc = desc[:120]
            tools.append(
                Tool(name=name, description=desc, inputSchema=schema["inputSchema"])
            )
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        root = _resolve_project_root()
        return _handle_tool_call(name, arguments, root)

    async def run_stdio() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="research-os start",
        description=(
            "Run the Research OS MCP server over stdio. The server is "
            "GLOBAL — it does not need a `--workspace` argument. The "
            "active project is resolved per-request via the "
            "RESEARCH_OS_WORKSPACE env var (preferred; set by your IDE "
            "MCP config to ${workspaceFolder}) or by walking up from the "
            "current working directory looking for `.os_state/`."
        ),
    )
    parser.add_argument(
        "--transport", default="stdio",
        help="MCP transport (default: stdio). 'sse' not yet implemented — falls back to stdio.",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help=(
            "DEPRECATED. Workspace is auto-resolved from the "
            "RESEARCH_OS_WORKSPACE env var or the current working "
            "directory. Passing --workspace still works (back-compat) "
            "but is no longer required."
        ),
    )
    args = parser.parse_args()

    # Only stdio is implemented today. A non-stdio --transport (e.g. sse) is
    # accepted by the parser but silently discarded below; warn instead of
    # leaving the user to wonder why their SSE endpoint never comes up.
    if getattr(args, "transport", "stdio") != "stdio":
        logger.warning(
            "transport %r is not yet implemented; falling back to stdio. "
            "Only 'stdio' is currently supported.",
            args.transport,
        )
        print(
            f"  warning: --transport {args.transport!r} not yet implemented "
            "— falling back to stdio.",
            file=sys.stderr,
        )

    if args.workspace:
        os.environ["RESEARCH_OS_WORKSPACE"] = str(
            Path(args.workspace).expanduser().resolve()
        )

    try:
        _inject_api_keys(_resolve_project_root())
    except Exception:
        pass

    if HAS_MCP:
        asyncio.run(run_stdio())
    else:
        sys.exit("MCP package missing. Install with: pip install research-os")


if __name__ == "__main__":
    main()
