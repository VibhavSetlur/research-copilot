"""Tool definitions for the meta domain."""
from __future__ import annotations

from typing import Any


META_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "sys_boot": {
        "short": "One-call session bootstrap (state + config + history + deps + next). Use at session start; lean=true mid-session.",
        "then": "tool_route(prompt=<user_message>)",
        "description": "Single-call session bootstrap. Returns state + researcher config + protocol history tail + optional-dep inventory + recommended next protocol + pause classification + any active plan from a previous turn + active_packs. Call this ONCE per session instead of sys_state_get + sys_config_get + sys_protocol_history + sys_protocol_next + sys_dep_inventory separately. Cuts a typical boot from ~5K tokens to ~800. Pass lean=true mid-session to get only {active_plan, pause_classification, current_tier, root, active_packs} (~50 tokens) — for cheap orientation when you only need to know where you are.",
        "category": "routing",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lean": {
                    "type": "boolean",
                    "description": "When true, return only {active_plan, pause_classification, current_tier, root, active_packs} (~50 tokens). Default false (full boot payload).",
                },
            },
        },
    },
    "sys_where": {
        "short": "~30-token snapshot (root, tier, plan, blocks, last_protocol). Use for cheap mid-session 'where am I?'.",
        "description": "Lightweight orientation tool for mid-session checks. Returns five fields: project_root (basename), tier (current_tier from .os_state/current_tier.json), active_plan ({step, total} from .os_state/active_plan.json, or null), unresolved_blocks (count of BLOCK-severity entries in workspace/logs/.audit_findings.jsonl), last_protocol (most recent entry from protocol history). ~30 tokens, <100ms. Use instead of sys_boot when you only need to remember your tier + active plan position. For the full boot payload, call sys_boot (or sys_boot(lean=true) for an intermediate ~50-token subset).",
        "category": "routing",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "sys_daemon": {
        "short": "Is a daemon running for this project? Return its live telemetry (jobs, freshness, next action).",
        "compare_to": "sys_where (state-file orientation, no daemon). sys_daemon adds awareness of a RUNNING daemon's live jobs + freshness.",
        "description": "Bridge between the MCP session and a running Research-OS daemon. The daemon is a separate, optional persistent process that runs long jobs, tracks run provenance/freshness, and serves an HTTP surface. This tool discovers it WITHOUT coupling: it reads the daemon's self-advertised descriptor at .os_state/daemon.json, confirms the process is alive, then GETs the daemon's read-only /v1/orient (narrative + ONE recommended next action) and /v1/jobs (running/queued/done counts). Returns {running: bool, ...}. When no daemon is running it returns running=false with a one-line hint on how to start one ('research-os daemon start'). Read-only and fast; never mutates. Use it at session start or mid-session to answer 'is anything running in the background, and what should I do next?' — the same continuity an HTTP agent gets from /v1/orient, now inside MCP.",
        "category": "routing",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timeout": {
                    "type": "number",
                    "description": "Per-request HTTP timeout in seconds when probing the daemon (default 2.0). Kept small so a hung daemon never stalls the session.",
                },
            },
            "additionalProperties": False,
        },
    },
    "sys_consent": {
        "short": "Request/check researcher consent for a daemon-gated action (when a floor gate returned consent_required).",
        "compare_to": "Plain confirmed=true works only when NO daemon is enforcing. sys_consent is the in-band path when a daemon IS present and a floor gate demands a real, human-authorized, one-shot token.",
        "description": "Bridge to a running daemon's consent authority. When a floor gate returns what='consent_required', the agent's own confirmed=true is not honored — a daemon-minted, one-shot, argument-bound token is required, and only an authorized human can mint it. This tool is the agent's in-band path through that loop, WITHOUT importing the daemon (it POSTs/GETs the daemon's /v1/consent endpoints over localhost). Actions: action='request' (gate_key, arg_fingerprint, tool, reason) queues a consent request for the researcher and returns its request_id — requesting is harmless, it cannot self-grant; action='status' lists pending requests + granted tokens so the agent can see whether the researcher has approved; action='token' (gate_key, arg_fingerprint) returns a minted, unspent token matching that exact action if one exists, else null. Typical loop: hit a gate → sys_consent(request) → tell the researcher what needs approval → they approve (CLI: 'research-os daemon consent approve <id>') → sys_consent(token) → retry the tool with consent_token=<minted>. Returns {available: bool, ...}; when no daemon is running, available=false (the gate degrades to confirmed=true anyway). NEVER request consent the researcher did not actually authorize.",
        "category": "routing",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["request", "status", "token"],
                    "description": "request: queue a consent request. status: list pending + granted. token: fetch a minted unspent token for a (gate_key, arg_fingerprint).",
                },
                "gate_key": {
                    "type": "string",
                    "description": "The gate key from the consent_required error (e.g. 'tool_typst_compile'). Required for request + token.",
                },
                "arg_fingerprint": {
                    "type": "string",
                    "description": "The arg_fingerprint from the consent_required error — binds consent to this EXACT action. Required for request + token.",
                },
                "tool": {
                    "type": "string",
                    "description": "The tool name the gate blocked (for request; helps the researcher see what they're approving).",
                },
                "reason": {
                    "type": "string",
                    "description": "Short human-readable reason shown to the researcher when they review the request.",
                },
                "timeout": {
                    "type": "number",
                    "description": "Per-request HTTP timeout in seconds (default 2.0).",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    "tool_route": {
        "short": "Prompt → protocol + decomposition + recommended_action. Call after every researcher message.",
        "then": "sys_protocol_get(protocol_name=<resolved>, format=<lean|summary|full per model_profile>)",
        "compare_to": "tool_quick_route (detects throwaway/sanity-check intent BEFORE this) and tool_semantic_route (direct top-k semantic-only ranking, no trigger fallback).",
        "description": "Hybrid router. Tries SEMANTIC search first (embeddings cosine over protocol descriptions + triggers) — best for fuzzy intent + as the protocol catalog grows. Falls back to the hierarchical L1→L2→L3 trigger picker when semantic confidence is low / unavailable. Returns primary_protocol, shortcut_tool, decomposition, complexity, ask_user, alternatives, method (=semantic|trigger), confidence (=high|medium|low|none), and `recommended_action` — a single-string hint naming the exact next tool to call (typically `sys_protocol_get(protocol_name='<primary>', format='summary')`, or the shortcut tool, or an `ask_user:` prompt, or a `tool_semantic_route` fallback when nothing resolved). High-complexity prompts get an active_plan persisted to .os_state/.",
        "category": "routing",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "persist_plan": {"type": "boolean"},
            },
            "required": ["prompt"],
        },
    },
    "tool_semantic_route": {
        "short": "Direct semantic search over protocol embeddings. Returns top-k candidates with scores.",
        "compare_to": "tool_route (hybrid semantic + trigger picker that returns a single primary protocol) and tool_quick_route (quick/throwaway short-circuit).",
        "description": "Embed the prompt with BAAI/bge-small-en-v1.5 (local ONNX, no network) and return the top-k protocols by cosine similarity, with the length-weighted trigger-phrase boost applied. Use this when you want to SEE the ranked candidates yourself — tool_route picks a primary; tool_semantic_route surfaces the alternatives so you can route deliberately. Ships in the base install; falls back to status='unavailable' only if the local embedder is somehow missing.",
        "category": "routing",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 25},
            },
            "required": ["prompt"],
        },
    },
    "sys_semantic_tool_search": {
        "short": "Find tools by what they do — semantic search over tool descriptions.",
        "compare_to": "sys_tool_describe (return one tool's full body when you already know its name).",
        "description": "Given a natural-language description of what you want to do (e.g. 'compute kappa for inter-rater agreement on transcript codes'), return the top-k matching tool names ranked by semantic similarity to each tool's short + description + category. Useful when sys_active_tools doesn't surface the right tool because the active protocol's decomposition is narrow. Requires the `semantic` extra; falls back to status='unavailable' otherwise.",
        "category": "system",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 25},
            },
            "required": ["query"],
        },
    },
    "sys_tool_describe": {
        "short": "Return the full description + schema + status + pack for one tool.",
        "compare_to": "sys_semantic_tool_search (discover tool names by natural-language task, then call this for one).",
        "description": "list_tools ships only short descriptions to keep context lean. When you genuinely need the full detail (parameter semantics, longer rationale, examples) for one tool, call this. Returns name, category, short, description, inputSchema, plus the introspection fields: status ('live' = canonical | 'alias' = legacy name dispatched to a consolidated tool | 'deprecated' = removed but still tagged) and pack ('core' = built-in | '<pack_name>' = contributed by an installed protocol pack or adapter). Cheaper than re-listing every tool.",
        "category": "routing",
        "inputSchema": {
            "type": "object",
            "properties": {"tool_name": {"type": "string"}},
            "required": ["tool_name"],
        },
    },
    "sys_active_tools": {
        "short": "Active tool shortlist for a protocol (essentials + decomposition tools).",
        "compare_to": "tool_tools_list (flat catalog of every registered MCP tool with scope/summary/required-fields filters).",
        "description": "Given a protocol name, return the tight set of tools the AI should prefer while executing it: ~10-15 tools = essentials + everything the protocol's decomposition actually calls. Use after sys_protocol_get to scope your working set instead of triaging all 212 tools per turn.",
        "category": "routing",
        "inputSchema": {
            "type": "object",
            "properties": {"protocol_name": {"type": "string"}},
            "required": ["protocol_name"],
        },
    },
    "sys_active_project": {
        "short": "Return the project root the server resolved for THIS request (global-server mode).",
        "description": "Returns the currently-resolved project root + how it was resolved (env var / cwd walk / fallback). The Research OS MCP server is GLOBAL — one process serves multiple projects. Each request resolves a project per the rules: (1) RESEARCH_OS_WORKSPACE env var (the IDE MCP config typically sets this to ${workspaceFolder}); (2) the current working directory walked up for `.os_state/`; (3) the current working directory itself. Call this when you need to confirm which project this session is operating on, OR when a tool surprised you and you want to verify the root.",
        "category": "routing",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "sys_help": {
        "short": "AI orientation — how to use Research OS efficiently (protocols + tools + routing).",
        "description": "Returns a compact orientation block for the AI: the session-start sequence (every turn is triggered by a researcher message — on the first turn, sys_boot is your 1st MCP call and tool_route(prompt=their message) is your 2nd, followed by sys_protocol_get / sys_active_tools as needed), the protocol categories with one-line summaries, and the tool namespaces (sys_* / tool_* / mem_*). Use this when starting cold (no prior session memory), when a new AI takes over from a handoff, or when a tool / protocol mention is ambiguous and the orientation block clarifies it.",
        "category": "routing",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Optional — a topic to focus the orientation on (e.g. 'synthesis', 'methodology', 'audit'). Returns category-specific guidance.",
                },
            },
        },
    },
    "sys_protocol_get": {
        "short": "Load a protocol (default format='summary'). Use 'step', 'lean', 'dryrun', or 'full' as needed.",
        "then": "sys_active_tools(protocol_name=<name>)",
        "compare_to": "tool_protocols_list (flat catalog of every protocol; this loads one protocol's body).",
        "description": "Load a protocol YAML by name (e.g. 'guidance/project_startup'). Five formats — summary (the default) returns id + step headings + quality_bar + expected outputs in ~300 tokens; step returns one specific step body (requires step_id); full returns the entire YAML (~1.5-3K tokens) and requires opt-in; lean serves the protocol's explicit lean_variant block if present, else auto-distils (cap 3 steps, drop optional sub-steps, trim step descriptions to 200 chars) for small/fast models; dryrun returns the full tool-call sequence with predicted args without executing — for supervised review. Prefer summary first then step on demand; use lean when researcher_config.model_profile=='small'; use dryrun in supervised mode to preview before commit. Routing tip: call tool_route(prompt) BEFORE this to pick the right protocol_name.",
        "category": "protocol",
        "inputSchema": {
            "type": "object",
            "properties": {
                "protocol_name": {"type": "string"},
                "format": {
                    "type": "string",
                    "enum": ["ref", "summary", "step", "full", "lean", "dryrun"],
                    "default": "summary",
                    "description": "ref | summary | step | full | lean | dryrun (default: summary, ~300 tokens). 'ref' is the cheapest peek (~50 tokens: id + summary + step count); pass 'full' explicitly when you actually need the whole YAML.",
                },
                "step_id": {
                    "type": "string",
                    "description": "Required when format='step'.",
                },
            },
            "required": ["protocol_name"],
            "additionalProperties": False,
        },
    },
    "sys_protocol_list": {
        "short": "Full catalog dump (core + packs). Use for debugging; prefer tool_route / tool_semantic_route at runtime.",
        "description": "Returns every protocol name + one-line summary + pack_or_core source, walking both the in-tree core protocols and every registered pack (humanities, qualitative, theory_math, wet_lab, engineering, plus any externally-installed packs). Pass `category` (e.g. 'theory_math', 'audit', 'guidance') to narrow to one pack or one core category. Designed for debugging + maintainer browsing; not the primary entrypoint at runtime. For routing a user prompt, call tool_route (hybrid semantic + trigger). For inspecting ranked alternatives, call tool_semantic_route. For finding tools by what they do, call sys_semantic_tool_search. As the catalog grows beyond ~150 protocols, dumping the full list every turn wastes context — semantic retrieval is the AI-friendly path.",
        "category": "protocol",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter to a single category. For core protocols this matches the first path segment (e.g. 'guidance', 'audit'). For pack protocols it matches the pack name (e.g. 'theory_math') or the pack-internal category.",
                },
            },
        },
    },
    "tool_protocols_list": {
        "short": "Flat protocol catalog with category + pack + intent_class. Filterable.",
        "compare_to": "sys_protocol_get (load one protocol body) and sys_protocol_list (verbose catalog dump for maintainers).",
        "description": "Returns a flat list of every protocol with structured metadata: name, category, pack_or_'core', intent_class, tier, version, description_short. Filter with `category` (e.g. 'audit', 'guidance'), `pack` ('core' or a pack name), and `include_pack_protocols` (default true). Cheaper for the AI to scan than sys_protocol_list when it only needs the protocols in one category or one pack. Use this when a researcher asks 'what audit protocols do you have?' — narrower than dumping the full catalog.",
        "category": "protocol",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter to a single category (first path segment, e.g. 'guidance', 'audit', 'synthesis').",
                },
                "pack": {
                    "type": "string",
                    "description": "Filter to a single source: 'core' or a pack name ('humanities', 'qualitative', etc.).",
                },
                "include_pack_protocols": {
                    "type": "boolean",
                    "description": "When false, skip every pack-contributed protocol. Default true.",
                },
            },
        },
    },
    "tool_tools_list": {
        "short": "Flat tool catalog with scope + summary + required-fields. Filterable; mode='auto' scopes to the active workspace.",
        "compare_to": "sys_active_tools (narrow shortlist scoped to one protocol's decomposition).",
        "description": "Returns a flat list of every registered MCP tool: name, scope ('core' or pack name), summary_first_line, input_schema_required_fields, deprecated, alias_of. Filter with `scope` ('all'|'core'|<pack-name>'), `include_deprecated` (default false), `match_substring` (case-insensitive needle against name + summary), and `mode` — the context-bloat fix. mode='auto' resolves the project's workspace.mode (analysis | tool_build | exploration) and returns only CORE + that mode's working tools (e.g. tool_build mode surfaces tool_git/tool_build + scope='tool' audits; analysis surfaces the analysis set), cutting the ~16K-token full list to a fraction. Pass an explicit mode name to scope deliberately; omit mode for the full catalog (default, unchanged). A pack's tools stay visible under mode scoping when you also pass scope=<packname>. Call sys_tool_describe for one tool's full body when you actually need it.",
        "category": "system",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "'all' | 'core' | a pack name. Default 'all'.",
                },
                "include_deprecated": {
                    "type": "boolean",
                    "description": "When true, include alias entries flagged as deprecated. Default false.",
                },
                "match_substring": {
                    "type": "string",
                    "description": "Restrict to tools whose name or summary contains this substring (case-insensitive).",
                },
                "mode": {
                    "type": "string",
                    "enum": ["auto", "analysis", "tool_build", "exploration"],
                    "description": "Scope to CORE + a workspace mode's tools. 'auto' reads the project's workspace.mode; an explicit name forces it; omit for the full catalog (default).",
                },
            },
        },
    },
    "sys_protocol_next": {
        "short": "Recommend the next protocol from workspace state + pipeline. Use when picking the next move.",
        "description": "Recommend the next protocol to run based on current workspace state and the pipeline.",
        "category": "protocol",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "sys_protocol_validate": {
        "short": "Check protocol's expected outputs exist in workspace. Use when confirming a protocol finished cleanly.",
        "description": "Check whether the expected outputs of a protocol are present in the workspace.",
        "category": "protocol",
        "inputSchema": {
            "type": "object",
            "properties": {"protocol_name": {"type": "string"}},
            "required": ["protocol_name"],
        },
    },
    "sys_protocol_log": {
        "short": "Record protocol execution status. Use when starting/completing/failing/skipping a protocol.",
        "description": "Record a protocol execution (started|completed|failed|skipped) to the pipeline log. COMPLETENESS GATE: logging 'completed' for a protocol that declares expected_outputs is REFUSED (status='blocked') if any declared output is missing on disk — produce the outputs first, then log completed. For the rare legitimate case (e.g. an intentionally-external output) pass override_completeness_gate=true; the override is recorded in the log + override_log.md.",
        "category": "protocol",
        "inputSchema": {
            "type": "object",
            "properties": {
                "protocol_name": {"type": "string"},
                "status": {"type": "string"},
                "details": {"type": "string"},
                "override_completeness_gate": {
                    "type": "boolean",
                    "description": "Log 'completed' even when declared outputs are missing (rare; recorded as an override).",
                },
            },
            "required": ["protocol_name", "status"],
        },
    },
    "sys_protocol_history": {
        "short": "Return recent protocol execution log entries. Use when reviewing what was run lately.",
        "description": "Return the most recent protocol execution log entries.",
        "category": "protocol",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "number"}},
        },
    },
    "sys_state_get": {
        "short": "Return full workspace state (project, stage, path, hypotheses). Use for orientation.",
        "description": "Return the full workspace state: project name, pipeline stage, current path, all experiment paths, and active hypotheses.",
        "category": "state",
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "description": "full | minimal | markdown — controls verbosity (default: full).",
                }
            },
        },
    },
    "sys_workspace_scaffold": {
        "short": "Create the Research OS directory layout. Use when researcher asks for a re-scaffold.",
        "description": "Create the standard Research OS directory layout. Used by `research-os init`; only call from inside the MCP if the researcher explicitly asks for a re-scaffold.",
        "category": "workspace",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "ide": {
                    "type": "string",
                    "description": "all | cursor | claude | antigravity | opencode | vscode",
                    "default": "all",
                },
            },
        },
    },
    "sys_workspace_mode": {
        "short": "Report or transition the workspace mode (analysis/tool_build/exploration/notebook/multi_study/hybrid).",
        "description": "First-class workspace-mode lifecycle. operation='status' returns the current mode (config + state), a drift flag, and the supported transitions from here. operation='transition' with `to=<mode>` moves the project to another mode — PLANS by default (shows what scaffold surface the target mode needs that's missing), and APPLIES when confirm=true: it ADDITIVELY creates the missing surface (never deletes prior work), syncs config + state (fixing any drift), records the move to .os_state/mode_history.jsonl, and points you at the promotion/handoff protocol for the crossing (e.g. exploration→analysis promotes probes into steps; analysis→hybrid adds an inner tool repo; analysis→multi_study reframes as study 01). Use this instead of sys_config(workspace.mode=…), which only flips the string and leaves the scaffold missing.",
        "category": "workspace",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["status", "transition"], "default": "status"},
                "to": {"type": "string", "description": "Target mode (for operation='transition')."},
                "confirm": {"type": "boolean", "description": "Apply the transition (default false = plan only)."},
                "rationale": {"type": "string", "description": "Why the mode is changing (recorded in mode_history)."},
            },
        },
    },
    "sys_workspace_tree": {
        "short": "Tree of workspace/ — paths, scripts, outputs. Use at session start for orientation.",
        "description": "Return a structured tree of workspace/ — experiment paths, scripts, outputs. Call at session start for orientation.",
        "category": "workspace",
        "inputSchema": {
            "type": "object",
            "properties": {
                "depth": {"type": "number"},
                "include_files": {"type": "boolean"},
            },
        },
    },
    "sys_file_read": {
        "short": "Read a workspace file (<=50MB). Use when inspecting project content.",
        "description": "Read a workspace file. Up to 50 MB; use tool_data_sample for larger datasets.",
        "category": "file",
        "inputSchema": {
            "type": "object",
            "properties": {"filepath": {"type": "string"}},
            "required": ["filepath"],
        },
    },
    "sys_file_write": {
        "short": "Write a workspace file (immutable inputs blocked). Use when producing project content.",
        "description": "Write a file. Refuses to write into inputs/raw_data/ or inputs/literature/ (immutable). Use force=true to overwrite a file in synthesis/. Versioned artifacts (`*_v<n>.<ext>`) under workspace/ or synthesis/ are immutable: an edit must be written as a NEW version (`_v<n+1>`) — overwriting an existing version is refused (the error names the bumped filename); pass force=true only for a genuine same-version fix. In autopilot mode, writes to synthesis/ with force=true require confirmed=true (server-enforced autopilot floor gate — see guidance/autopilot.yaml).",
        "category": "file",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string"},
                "content": {"type": "string"},
                "force": {"type": "boolean"},
                "confirmed": {"type": "boolean", "description": "Required in autopilot mode for force-overwrites into synthesis/. Researcher consent."},
            },
            "required": ["filepath", "content"],
        },
    },
    "sys_file_list": {
        "short": "List files in a workspace directory (recursive). Use when inventorying a folder.",
        "description": "List files in a workspace directory (recursive).",
        "category": "file",
        "inputSchema": {
            "type": "object",
            "properties": {"directory": {"type": "string"}},
            "required": ["directory"],
        },
    },
    "sys_file_delete": {
        "short": "Delete a workspace file or empty directory. Use when removing project content.",
        "description": "Delete a workspace file or an empty directory.",
        "category": "file",
        "inputSchema": {
            "type": "object",
            "properties": {"filepath": {"type": "string"}},
            "required": ["filepath"],
        },
    },
    "sys_file_validate_md": {
        "short": "Validate markdown headings/sections against a writing protocol. Use when checking required structure.",
        "description": "Validate a markdown file against the headings/sections expected by a writing protocol.",
        "category": "file",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string"},
                "protocol_name": {"type": "string"},
            },
            "required": ["filepath", "protocol_name"],
        },
    },
    "sys_export_share_archive": {
        "short": "Build a share-safe zip of the project (excludes AI internals + raw_data). Use when sharing externally.",
        "description": (
            "Build a share-safe zip of this project (default: "
            "<project>_share_<YYYY-MM-DD>.zip in the project root). "
            "Excludes AI-internal files (AGENTS.md, CLAUDE.md, .os_state/, "
            ".claude/, MCP configs, GETTING_STARTED.md) and — unless "
            "include_raw_data=true — inputs/raw_data/. Includes inputs/ "
            "(minus raw_data), workspace/, synthesis/, docs/, environment/, "
            "and a top-level README.md if present. Equivalent to running "
            "`python scripts/export_share_archive.py` from the project root."
        ),
        "category": "interaction",
        "inputSchema": {
            "type": "object",
            "properties": {
                "out": {"type": "string",
                        "description": "Optional explicit output zip path."},
                "include_raw_data": {
                    "type": "boolean",
                    "description": "Set true to bundle inputs/raw_data/ (default false to keep archives small and avoid PII)."
                },
            },
        },
    },
    "sys_export_ro_crate": {
        "short": "Emit RO-Crate 1.1 + CodeMeta 2.0 manifests at project root. Use before sharing externally.",
        "description": (
            "Build open-science manifests at the project root: "
            "ro-crate-metadata.json (RO-Crate 1.1 Lightweight Profile, "
            "JSON-LD against https://w3id.org/ro/crate/1.1/context) and "
            "codemeta.json (CodeMeta 2.0). Populated from "
            "inputs/researcher_config.yaml (author + ORCID + license_data / "
            "license_code), inputs/intake.md (description), and a walk "
            "of synthesis/ + workspace/*/outputs/ for hasPart entries "
            "(including every *.prov.json sidecar). operation='build' "
            "(default) writes both files; operation='preview' returns "
            "what WOULD be emitted without touching disk. The manifests "
            "are auto-included in sys_export_share_archive zips at root."
        ),
        "category": "interaction",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["build", "preview"],
                    "description": "build (default) writes manifests; preview returns summary only.",
                },
            },
        },
    },
    "tool_synthesis_curate_figures": {
        "short": "Curate step figures + captions into synthesis/figures/. mode='focal' (one/step) or 'all' (every figure).",
        "description": (
            "Collect step figures into synthesis/figures/ with stable, "
            "ordered names so the AI-authored synthesis files (paper.typ, "
            "dashboard.html, slides.typ) can embed them deterministically. "
            "Always copies each figure's .caption.md sidecar if present, or "
            "seeds a placeholder explaining how to write one. Mode 'focal' "
            "(default) picks one focal figure per step and names them "
            "fig01_<slug>.png, fig02_<slug>.png, … — the canonical curated "
            "set for paper.typ. Mode 'all' copies every figure in every "
            "step's outputs/figures/ — appropriate for a dashboard that "
            "wants the full evidence base, and the only reliable way to "
            "ensure every figure that lands in synthesis/figures/ has a "
            "caption sidecar (figures written there directly by the AI, "
            "bypassing the per-step pipeline, are the most common cause of "
            "missing captions). Returns the list of curated figures, any "
            "step with no figures, and any step with missing captions."
        ),
        "category": "synthesis",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["focal", "all"],
                    "description": "'focal' (default) curates one figure per step; 'all' curates every figure in every step.",
                },
            },
        },
    },
    "tool_path_finalize": {
        "short": "Rewrite step + subfolder READMEs from actual produced artifacts. Use before marking a step complete.",
        "description": (
            "Rewrite a step's stub README + every subfolder README from what "
            "actually got produced. Call this BEFORE marking a step complete: "
            "(a) `environment/README.md` is normalised to either 'used the "
            "project-global env' or a list of bespoke requirements, (b) "
            "`literature/README.md` either points at the global corpus + the "
            "step's decision log or lists the step-specific sources + the "
            "decisions they informed, (c) `data/next_step_output/README.md` lists every "
            "persisted artefact and which downstream step consumes it, (d) "
            "`outputs/README.md` enumerates produced figures / tables / "
            "reports, and (e) any stub sections in the step's main `README.md` "
            "are populated from `conclusions.md` + `analysis.md` decisions. "
            "Idempotent — running it a second time is a no-op if nothing "
            "changed. Defaults to the current path."
        ),
        "category": "path",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path_name": {
                    "type": "string",
                    "description": "Step folder name (e.g. '03_replicate_attitude_demographics'). Defaults to current_path.",
                },
                "override_literature_gate": {
                    "type": "boolean",
                    "description": "Bypass the step-literature gate when it blocks finalize. Requires override_rationale.",
                },
                "override_rationale": {
                    "type": "string",
                    "description": "Justification logged when override_literature_gate=true.",
                },
            },
        },
    },
    "sys_checkpoint_create": {
        "short": "Snapshot the workspace (copied snapshot). Use before risky operations.",
        "description": "Snapshot the current workspace (copied snapshot). Returns checkpoint_id.",
        "category": "checkpoint",
        "inputSchema": {
            "type": "object",
            "properties": {"description": {"type": "string"}},
        },
    },
    "sys_checkpoint_rollback": {
        "short": "Restore workspace to a checkpoint (current state backed up first). Use when undoing changes.",
        "do_not": "Set override_* params only when researcher explicitly authorizes. Without a substantive override_rationale (>=20 chars, multi-word), the override is rejected.",
        "description": "Restore the workspace to a checkpoint. The current state is backed up first. In autopilot mode, requires confirmed=true (server-enforced autopilot floor gate — see guidance/autopilot.yaml).",
        "category": "checkpoint",
        "inputSchema": {
            "type": "object",
            "properties": {
                "checkpoint_id": {"type": "string"},
                "confirmed": {"type": "boolean", "description": "Required in autopilot mode. Researcher consent."},
            },
            "required": ["checkpoint_id"],
        },
    },
    "sys_checkpoint_list": {
        "short": "List all checkpoints with descriptions + timestamps. Use when picking a rollback target.",
        "description": "List all checkpoints with descriptions and timestamps.",
        "category": "checkpoint",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "sys_config": {
        "short": "Unified researcher-config tool. operation=get|set|validate|note.",
        "description": "Unified researcher-config dispatcher for inputs/researcher_config.yaml. operation='get' reads the full config (autonomy level, expertise, model profile, research goal, API keys masked). operation='set' writes a single value via dot notation (e.g. key='researcher.expertise_level', value='advanced'). operation='validate' checks the schema and reports which API keys are present. operation='note' APPENDS a learned, durable researcher preference or correction to interaction.agent_notes (e.g. note='always segregate transport reactions', 'prefer DRFP over structural fingerprints', 'never touch the prod DB') — this is the learn-the-user loop: record it when the researcher corrects you or states a standing preference, and the next session inherits it (agent_notes is surfaced at every boot). Appends rather than clobbers, and is idempotent (re-recording the same preference is a no-op). Use 'note' for free-form standing preferences; use 'set' for the structured knobs (autonomy_level, output_types, citation_style, compute_environment). Every legacy sys_config_get / sys_config_set / sys_config_validate name aliases to this entry point with operation injected via _ALIAS_PARAM_INJECTION so callers using the older per-operation names keep working unchanged.",
        "category": "config",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["get", "set", "validate", "note"],
                    "description": "Which config sub-operation to invoke.",
                },
                # operation='set' kwargs
                "key": {
                    "type": "string",
                    "description": "operation='set' — REQUIRED. Dot-notation key (e.g. 'researcher.expertise_level').",
                },
                "value": {
                    "type": "string",
                    "description": "operation='set' — REQUIRED. New value as a string.",
                },
                # operation='note' kwargs
                "note": {
                    "type": "string",
                    "description": "operation='note' — REQUIRED. A learned researcher preference / correction to append to interaction.agent_notes, in plain language.",
                },
            },
            "required": ["operation"],
        },
    },
    "sys_notify": {
        "short": "Notify the researcher (logged). Use when surfacing info|warn|action_required.",
        "description": "Notify the researcher (logged to workspace/logs/notifications.log).",
        "category": "interaction",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "level": {"type": "string", "description": "info|warn|action_required"},
            },
            "required": ["message", "level"],
        },
    },
    "sys_session_handoff": {
        "short": "Generate a markdown handoff (state, last action, next step). Use at session end.",
        "description": "Generate a structured markdown handoff describing the project state, last action, and next step. Use at session end.",
        "category": "interaction",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "sys_env": {
        "short": "Unified environment tool. operation=snapshot|docker_generate.",
        "description": "Unified environment dispatcher. operation='snapshot' captures the current Python (and optionally R/Julia) environment — target by step_id='NN_slug' for a per-step snapshot, scope='project' for the eager-scaffolded project-global environment/ folder, or omit both for the legacy default (most-recent numbered step, or project-global when none exist). operation='docker_generate' generates a Dockerfile (+ .dockerignore) from the environment snapshot for full reproducibility (run snapshot first) — pass step_id='NN_slug' to dockerize ONE analysis step (writes workspace/<step>/environment/Dockerfile with the step's own pinned requirements, build context = the step dir), or omit step_id for a whole-project image. Every legacy sys_env_snapshot / sys_env_docker_generate name aliases to this entry point with operation injected via _ALIAS_PARAM_INJECTION so callers using the older per-operation names keep working unchanged.",
        "category": "environment",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["snapshot", "docker_generate"],
                    "description": "Which environment sub-operation to invoke.",
                },
                # operation='snapshot' + 'docker_generate' kwargs
                "step_id": {
                    "type": "string",
                    "description": "Optional NN_slug of the numbered step to target. For operation='snapshot' it snapshots into that step's environment/ (mutually exclusive with scope); for operation='docker_generate' it writes a step-scoped Dockerfile (workspace/<step>/environment/Dockerfile) so ONE step is independently containerizable.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["project"],
                    "description": "operation='snapshot' — optional. Set to 'project' to snapshot into the project-global environment/ folder.",
                },
            },
            "required": ["operation"],
        },
    },
    "mem_citations_generate": {
        "short": "Refresh workspace/citations.md from inputs/literature_index.yaml. Use after literature changes.",
        "description": "Refresh workspace/citations.md from inputs/literature_index.yaml.",
        "category": "memory",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "mem_intake_regenerate": {
        "short": "Regenerate inputs/intake.md (SHA-256 file inventory). Use after inputs/ changes.",
        "description": "Regenerate inputs/intake.md (file inventory with SHA-256 hashes).",
        "category": "memory",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "sys_dep_inventory": {
        "short": "Report which optional deps failed to import. Use once at session start.",
        "description": "Report which optional dependencies (search, viz, audit, ml, notebook, literature, web) failed to import. Call once at session start so you know which tools will work.",
        "category": "state",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "tool_cache_clear": {
        "short": "Wipe cached search results (optionally per-provider or older-than-N-days).",
        "description": "Manage the file-backed search cache at .os_state/cache/search/<provider>/. Call when you suspect stale results, or after a long break to free disk. Cache TTL defaults to 24h (configurable via runtime.cache_ttl_seconds).",
        "category": "search",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Restrict to one provider (semantic_scholar | crossref | pubmed | arxiv | web). Omit for all.",
                },
                "older_than_days": {
                    "type": "number",
                    "description": "Only delete entries older than this many days. Omit for all entries.",
                },
            },
        },
    },
    "tool_workflow_dag": {
        "short": "Build a DAG of numbered steps + their data dependencies; write docs/workflow_dag.mermaid.",
        "description": "Walks each numbered step's data/past_step_input symlinks to derive cross-step dependencies, then writes docs/workflow_dag.mermaid with colour-coded nodes (active / completed / dead_end). Pass render_png=true to also emit a PNG (requires mmdc — npm install -g @mermaid-js/mermaid-cli). Auto-refreshed by sys_path(operation='create') and sys_path(operation='abandon') so the DAG stays in sync without manual calls.",
        "category": "state",
        "inputSchema": {
            "type": "object",
            "properties": {
                "render_png": {"type": "boolean"},
                "output_dir": {
                    "type": "string",
                    "description": "Where to write (default: docs).",
                },
            },
        },
    },
    "sys_path": {
        "short": "Unified step/path dispatcher. operation='create'|'abandon'|'list'|'rename'|'group'. Also callable as sys_step.",
        "description": "One entry for the analysis-step (a.k.a. 'path') lifecycle. operation='create' (was sys_path_create) takes name + hypothesis + branch_of. operation='abandon' (was sys_path_abandon) takes path_name + rationale. operation='list' (was sys_path_list) returns all steps with status (including steps grouped under PATH containers, each tagged with path_container). operation='rename' takes path_name + new_name and gives a generic step a meaningful human label — it keeps the NN_ step number, renames the folder, and re-points every downstream data/* symlink. operation='group' takes name=<descriptive label> + steps=[<path_id>, …] and CONSOLIDATES those flat steps into a workspace/<name>_PATH_<k>/ container folder (the 3.2 way to organise a direction you explored) — it moves the step folders, re-points every absolute data/* symlink, and preserves step numbering (continuous across the project; path 2 keeps going at step 06, never resets). Callable as either sys_path or sys_step (alias). In autopilot mode, operation='abandon' requires confirmed=true (server-enforced autopilot floor gate — see guidance/autopilot.yaml).",
        "category": "state",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["create", "abandon", "list", "rename", "group"]},
                "name": {"type": "string", "description": "operation='create' — step slug. operation='group' — the descriptive container label (becomes <slug>_PATH_<k>)."},
                "hypothesis": {"type": "string"},
                "branch_of": {"type": "string"},
                "from_step": {"type": "string"},
                "allow_unfinalized_predecessor": {"type": "boolean"},
                "override_rationale": {"type": "string"},
                "path_name": {"type": "string"},
                "new_name": {"type": "string", "description": "operation='rename' — the new human label for the step (the NN_ number is preserved)."},
                "steps": {"type": "array", "items": {"type": "string"}, "description": "operation='group' — the path_ids of the flat steps to move into the new PATH container."},
                "rationale": {"type": "string"},
                "confirmed": {"type": "boolean", "description": "Required in autopilot mode for operation='abandon'. Researcher consent."},
            },
            "required": ["operation"],
        },
    },
    "tool_deprecations_summary": {
        "short": "Aggregate counts from .os_state/deprecations.log — which deprecated aliases / redirects this project is still hitting.",
        "description": "Reads .os_state/deprecations.log (populated whenever a deprecated alias is invoked OR a redirect-stub protocol is loaded) and returns aggregated counts by kind/source/target. Use to audit which deprecated names the project still relies on before the next major (when aliases hard-remove).",
        "category": "state",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "sys_packs_installed": {
    "short": "List installed protocol packs (name, version, tool count, router entries, errors).",
    "description": "Returns the set of protocol packs currently registered with the server — both bundled (humanities, qualitative) and externally pip-installed via the `research_os.protocol_pack` entry-point group. Use to confirm a pack is loadable, to see its tool / router contributions, and to surface any registration errors (full traceback in `workspace/logs/pack_errors.log`).",
    "category": "routing",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
},
    "sys_adapters_installed": {
    "short": "List installed infrastructure adapters (HPC / workflow / data-platform / experiment-tracking; plus external plugins).",
    "description": "Returns the set of infrastructure adapters currently registered via the `research_os.adapter` entry-point group. Adapters are pluggable detectors + provenance extractors for HPC schedulers, workflow engines, analysis platforms, and data systems. Use to confirm an adapter is loaded; pair with tool_adapters_list to check detection on the current project.",
    "category": "routing",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
},
    "tool_adapter_extract": {
    "short": "Run one adapter's extract() + write provenance YAML to workspace/<step>/provenance/<adapter>.yaml.",
    "description": "Executes a specific installed adapter against the current project (or one step within it) and persists the extracted provenance as a structured YAML file. Returns the path to the YAML plus a small summary of cardinalities. Idempotent — re-running overwrites the YAML so it always reflects the current filesystem state.",
    "category": "state",
    "inputSchema": {
        "type": "object",
        "properties": {
            "adapter_name": {"type": "string"},
            "step_id": {"type": "string"},
        },
        "required": ["adapter_name"],
    },
},
    "tool_adapters_list": {
    "short": "List adapters + their detection status on the current project (e.g. 'slurm: detected_in_project=true').",
    "description": "Walks every installed adapter, calls its detect(root) callable, and returns the combined status. Detect is cheap (filesystem-only; no network). Use to surface which adapters are relevant before deciding whether to run tool_adapter_extract / tool_adapters_run_all.",
    "category": "state",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
},
    "tool_adapters_run_all": {
    "short": "Run every detected adapter's extract() and write per-adapter provenance YAMLs.",
    "description": "Bulk version of tool_adapter_extract — walks every installed adapter, calls detect(), and runs extract() only on the matches. Writes one provenance/<adapter>.yaml per match. Returns a per-adapter status list.",
    "category": "state",
    "inputSchema": {
        "type": "object",
        "properties": {"step_id": {"type": "string"}},
        "additionalProperties": False,
    },
},
}
