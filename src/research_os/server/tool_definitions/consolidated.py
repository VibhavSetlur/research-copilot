"""Consolidated tool surface — the 45 core Research-OS tools."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .audit import AUDIT_TOOL_DEFINITIONS
from .build import BUILD_TOOL_DEFINITIONS
from .grounding import GROUNDING_TOOL_DEFINITIONS
from .meta import META_TOOL_DEFINITIONS
from .methodology import METHODOLOGY_TOOL_DEFINITIONS
from .research import RESEARCH_TOOL_DEFINITIONS
from .synthesis import SYNTHESIS_TOOL_DEFINITIONS

_SOURCE_DEFINITIONS: dict[str, dict[str, Any]] = {
    **META_TOOL_DEFINITIONS,
    **RESEARCH_TOOL_DEFINITIONS,
    **AUDIT_TOOL_DEFINITIONS,
    **SYNTHESIS_TOOL_DEFINITIONS,
    **METHODOLOGY_TOOL_DEFINITIONS,
    **GROUNDING_TOOL_DEFINITIONS,
    **BUILD_TOOL_DEFINITIONS,
}


def _schema(name: str) -> dict[str, Any]:
    return deepcopy(_SOURCE_DEFINITIONS[name]["inputSchema"])


def _tool(name: str, short: str, description: str, category: str | None = None) -> dict[str, Any]:
    source = _SOURCE_DEFINITIONS[name]
    return {
        "short": short,
        "description": description,
        "category": category or source["category"],
        "inputSchema": deepcopy(source["inputSchema"]),
    }


def _merged_schema(*names: str) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name in names:
        schema = _schema(name)
        properties.update(schema.get("properties", {}))
        for field in schema.get("required", []):
            if field not in required:
                required.append(field)
    return {"type": "object", "properties": properties, "required": required}


_SYS_BOOT_SCHEMA = _merged_schema("sys_boot", "sys_where", "sys_config")
_SYS_BOOT_SCHEMA["properties"]["operation"] = {
    "type": "string",
    "enum": ["boot", "where", "config_get", "config_note"],
    "default": "boot",
}
_SYS_BOOT_SCHEMA["required"] = []

_TOOL_ROUTE_SCHEMA = _merged_schema("tool_route", "sys_semantic_tool_search")
_TOOL_ROUTE_SCHEMA["properties"]["mode"] = {
    "type": "string",
    "enum": ["route", "tool_search"],
    "default": "route",
}
_TOOL_ROUTE_SCHEMA["required"] = ["prompt"]

_SYS_STATE_SCHEMA = _merged_schema("sys_state_get", "sys_path")
_SYS_STATE_SCHEMA["properties"]["operation"] = {
    "type": "string",
    "enum": ["state_get", "create", "abandon", "list", "rename", "group"],
    "default": "state_get",
}
_SYS_STATE_SCHEMA["required"] = []

_TOOL_SEARCH_SCHEMA = _merged_schema("tool_search", "tool_web_scrape", "tool_literature_search_and_save")
_TOOL_SEARCH_SCHEMA["properties"]["mode"] = {
    "type": "string",
    "enum": ["search", "scrape", "literature"],
    "default": "search",
}
_TOOL_SEARCH_SCHEMA["required"] = []

_TOOL_PYTHON_SCHEMA = _schema("tool_python_exec")
_TOOL_PYTHON_SCHEMA["properties"].update(
    {
        "data_operation": {"type": "string", "enum": ["sample", "profile", "convert"]},
        "filepath": _schema("tool_data")["properties"]["filepath"],
        "n_rows": _schema("tool_data")["properties"]["n_rows"],
        "strategy": _schema("tool_data")["properties"]["strategy"],
        "output_format": _schema("tool_data")["properties"]["output_format"],
    }
)

_TOOL_BASH_SCHEMA = _schema("tool_bash_exec")
_TOOL_BASH_SCHEMA["properties"].update(
    {
        "background": {"type": "boolean"},
        "task_operation": _schema("tool_task")["properties"]["operation"],
        "command": _schema("tool_task")["properties"]["command"],
        "cwd": _schema("tool_task")["properties"]["cwd"],
        "description": _schema("tool_task")["properties"]["description"],
        "task_id": _schema("tool_task")["properties"]["task_id"],
        "tail_lines": _schema("tool_task")["properties"]["tail_lines"],
        "signal_name": _schema("tool_task")["properties"]["signal_name"],
        "confirmed": _schema("tool_task")["properties"]["confirmed"],
    }
)

_TOOL_PLAN_SCHEMA = _merged_schema("tool_plan", "tool_step", "tool_step_pipeline", "tool_plan_step_grounded")
_TOOL_PLAN_SCHEMA["properties"]["operation"] = {
    "type": "string",
    "enum": [
        "turn",
        "advance",
        "clear",
        "iterate",
        "iterations_list",
        "revision_options",
        "env_lock",
        "define",
        "run",
        "status",
        "diagram",
        "grounded_step",
    ],
}
_TOOL_PLAN_SCHEMA["required"] = ["operation"]

_MEM_LOG_SCHEMA = _merged_schema("mem_log", "mem_hypothesis_add", "tool_lessons")
_MEM_LOG_SCHEMA["properties"]["kind"] = {
    "type": "string",
    "enum": ["methods", "decision", "hypothesis", "analysis", "lesson"],
}
_MEM_LOG_SCHEMA["required"] = ["kind"]

CONSOLIDATED_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    # ---- CORE (15) ----
    "sys_boot": {
        "short": "Bootstrap, locate, or read/note config in one entry point.",
        "description": "Session bootstrap plus lightweight where/config access for v5 clients.",
        "category": "routing",
        "inputSchema": _SYS_BOOT_SCHEMA,
    },
    "tool_route": {
        "short": "Route prompts to protocols or search the tool catalog semantically.",
        "description": "Resolve a user prompt to the next protocol, shortcut, or matching tools.",
        "category": "routing",
        "inputSchema": _TOOL_ROUTE_SCHEMA,
    },
    "sys_protocol_get": _tool(
        "sys_protocol_get",
        "Load one protocol as ref, summary, step, lean, dryrun, or full.",
        "Return a protocol body or focused view for the routed research task.",
    ),
    "sys_active_tools": _tool(
        "sys_active_tools",
        "Return the active tool shortlist for one protocol.",
        "Scope the working tool set to essentials plus protocol decomposition tools.",
    ),
    "sys_file_read": _tool(
        "sys_file_read",
        "Read a workspace file up to 50MB.",
        "Inspect project content from a path inside the workspace.",
    ),
    "sys_file_write": _tool(
        "sys_file_write",
        "Write a workspace file with immutable-input safeguards.",
        "Produce project content while blocking protected raw inputs by default.",
    ),
    "sys_file_list": _tool(
        "sys_file_list",
        "List files in a workspace directory recursively.",
        "Inventory a workspace directory by relative path.",
    ),
    "sys_state_get": {
        "short": "Read workspace state or manage analysis paths.",
        "description": "Return state or dispatch path lifecycle actions through the v5 state tool.",
        "category": "state",
        "inputSchema": _SYS_STATE_SCHEMA,
    },
    "tool_search": {
        "short": "Search literature/web, scrape pages, or save literature hits.",
        "description": "Unified search entry for provider search, webpage scraping, and literature saves.",
        "category": "search",
        "inputSchema": _TOOL_SEARCH_SCHEMA,
    },
    "tool_python_exec": {
        "short": "Execute Python scripts, with optional data-operation passthroughs.",
        "description": "Run workspace Python code and carry data-operation arguments for v5 routing.",
        "category": "execution",
        "inputSchema": _TOOL_PYTHON_SCHEMA,
    },
    "tool_bash_exec": {
        "short": "Execute Bash scripts, with optional background-task fields.",
        "description": "Run workspace shell utilities and carry task-management args for v5 routing.",
        "category": "execution",
        "inputSchema": _TOOL_BASH_SCHEMA,
    },
    "tool_plan": {
        "short": "Plan turns, step iterations, pipelines, or grounded substeps.",
        "description": "Unified planning surface for active plans, step lifecycle, DAGs, and grounded plans.",
        "category": "routing",
        "inputSchema": _TOOL_PLAN_SCHEMA,
    },
    "tool_audit": _tool(
        "tool_audit",
        "Unified audit across step, project, synthesis, tool, and active gates.",
        "Run the selected quality gate and return findings for the requested scope.",
    ),
    "mem_log": {
        "short": "Append decisions, hypotheses, analyses, methods, or lessons to memory.",
        "description": "Unified memory write surface for durable project decisions and lessons.",
        "category": "memory",
        "inputSchema": _MEM_LOG_SCHEMA,
    },
    "tool_thought": _tool(
        "tool_thought",
        "Log or read ReAct-style thought traces.",
        "Record reasoning traces or retrieve recent thought history for continuity.",
    ),
    # ---- MODE (15) ----
    "tool_data": _tool(
        "tool_data",
        "Sample, profile, or convert tabular data.",
        "Inspect and convert datasets through the unified data dispatcher.",
    ),
    "tool_notebook_exec": _tool(
        "tool_notebook_exec",
        "Execute a Jupyter notebook with optional papermill parameters.",
        "Run notebooks and write executed outputs with provenance where supported.",
    ),
    "tool_slurm_submit": _tool(
        "tool_slurm_submit",
        "Submit a SLURM job using project cluster defaults.",
        "Generate, submit, and record an sbatch job for HPC execution.",
    ),
    "tool_synthesis_scaffold": _tool(
        "tool_synthesis_scaffold",
        "Scaffold a synthesis deliverable from archetypes and palettes.",
        "Create paper, slides, poster, essay, dashboard, grant, or handout skeletons.",
    ),
    "tool_typst_compile": _tool(
        "tool_typst_compile",
        "Compile a Typst source to PDF.",
        "Render AI-authored Typst synthesis files and report compiler issues.",
    ),
    "tool_reviewer": _tool(
        "tool_reviewer",
        "Scaffold, write, or compile reviewer responses.",
        "Manage reviewer rebuttal scaffolds and response compilation for revisions.",
    ),
    "tool_preregister": _tool(
        "tool_preregister",
        "Freeze or diff a preregistration plan.",
        "Manage preregistration snapshots and deviation checks for synthesis.",
    ),
    "tool_sensitivity": _tool(
        "tool_sensitivity",
        "Define or run multiverse sensitivity analyses.",
        "Create and execute specification grids with optional curve rendering.",
    ),
    "tool_git": _tool(
        "tool_git",
        "Run contained git operations for project or inner tool repos.",
        "Manage provenance commits, status, branches, tags, logs, diffs, and restores.",
    ),
    "tool_build": _tool(
        "tool_build",
        "Run configured build, test, or lint commands.",
        "Execute researcher-declared tool-build commands in the contained inner repo.",
    ),
    "tool_package_install": _tool(
        "tool_package_install",
        "Install Python packages and record them in requirements.",
        "Add Python dependencies to the project environment with consent gating.",
    ),
    "tool_scratch": _tool(
        "tool_scratch",
        "Write, run, list, or clear scratch sandbox files.",
        "Use the gitignored scratch area for quick tests before promoting durable work.",
    ),
    "tool_task": _tool(
        "tool_task",
        "Run, inspect, list, or kill background tasks.",
        "Manage long-running subprocesses without blocking the MCP session.",
    ),
    "tool_session_handoff": {
        "short": "Generate a markdown handoff for a future session.",
        "description": "Summarize state, last action, and next step when ending or splitting a chat.",
        "category": "interaction",
        "inputSchema": _schema("sys_session_handoff"),
    },
    "tool_migrate_audit": _tool(
        "tool_migrate_audit",
        "Audit a messy project directory and map it into RO layout.",
        "Classify source files and show a read-only migration plan into Research-OS.",
    ),
    # ---- FULL (15) ----
    "tool_ground": _tool(
        "tool_ground",
        "Register a grounded claim from explicit sources or project context.",
        "Anchor claims to sources, context files, excerpts, and confidence metadata.",
    ),
    "tool_verify": _tool(
        "tool_verify",
        "Verify claims, project grounding, outputs, or step evidence.",
        "Check evidence bindings and declared outputs before considering work complete.",
    ),
    "tool_reliability": _tool(
        "tool_reliability",
        "Log reliability events or generate a reliability report.",
        "Record local structural reliability events and summarize recovery patterns.",
    ),
    "mem_search": {
        "short": "Semantic search across recorded memory.",
        "description": "Semantic search across recorded memory entries: decisions, hypotheses, and lessons.",
        "category": "memory",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 1},
                "kind": {"type": "string"},
                "all_projects": {"type": "boolean"},
            },
            "required": ["query"],
        },
    },
    "mem_hypothesis": {
        "short": "Add, list, update, or get tracked hypotheses.",
        "description": "Manage durable project hypotheses and their statuses.",
        "category": "memory",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["add", "list", "update", "get"]},
                "statement": {"type": "string"},
                "status": {"type": "string"},
                "hypothesis_id": {"type": "string"},
            },
            "required": ["operation"],
        },
    },
    "mem_retrieve": {
        "short": "Retrieve memory by pointer or semantic query.",
        "description": "Fetch a specific memory pointer or top matching memory records.",
        "category": "memory",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pointer": {"type": "string"},
                "query": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 1},
            },
            "required": [],
        },
    },
    "tool_dry_run": _tool(
        "tool_dry_run",
        "Preview a protocol tool-call sequence without executing it.",
        "Return predicted protocol steps and calls for supervised review.",
    ),
    "tool_finalize_project": _tool(
        "tool_finalize_project",
        "Check or enforce the final project ship gate.",
        "Aggregate blockers and optionally refuse finalization unless explicitly overridden.",
    ),
    "tool_workflow_dag": _tool(
        "tool_workflow_dag",
        "Build the numbered-step workflow DAG.",
        "Derive step dependencies and write a Mermaid workflow graph.",
    ),
    "tool_protocols_list": _tool(
        "tool_protocols_list",
        "List protocols with category, pack, and intent metadata.",
        "Return a filterable flat protocol catalog for browsing available workflows.",
    ),
    "sys_env": _tool(
        "sys_env",
        "Snapshot environments or generate Docker files.",
        "Capture reproducibility metadata or emit project/step container scaffolds.",
    ),
    "sys_notify": _tool(
        "sys_notify",
        "Notify the researcher and log the message.",
        "Surface info, warning, or action-required messages to the project log.",
    ),
    "sys_workspace_tree": _tool(
        "sys_workspace_tree",
        "Return a structured tree of workspace files.",
        "Inspect workspace steps, scripts, outputs, and optional files for orientation.",
    ),
    "sys_active_project": _tool(
        "sys_active_project",
        "Return the project root resolved for this request.",
        "Confirm which workspace the global MCP server is operating on.",
    ),
    "tool_lessons": _tool(
        "tool_lessons",
        "Record, consult, or replay lessons and failure memory.",
        "Manage durable lessons, known failures, dead-end learning, and mistake replay.",
    ),
}
