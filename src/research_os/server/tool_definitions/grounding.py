"""Tool definitions for the grounding domain."""
from __future__ import annotations

from typing import Any


GROUNDING_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "tool_thought": {
        "short": "Unified ReAct trace tool. operation=log|trace.",
        "description": "Unified thinking-log dispatcher (ReAct: thought → action → observation). operation='log' appends one trace entry — thought / plan / action / observation / reflection / decision — to workspace/.thoughts/thoughts.jsonl; use to surface reasoning BEFORE acting; optional decision_id links the trace to a grounding record. operation='trace' returns the tail of workspace/.thoughts/thoughts.jsonl, filterable by step / decision; use to remind yourself what you concluded earlier in the session. Every legacy tool_thought_log / tool_thought_trace name aliases to this entry point with operation injected via _ALIAS_PARAM_INJECTION so callers using the older per-operation names keep working unchanged.",
        "category": "memory",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["log", "trace"],
                    "description": "Which thought sub-operation to invoke.",
                },
                # operation='log' kwargs
                "kind": {
                    "type": "string",
                    "description": "operation='log' — REQUIRED. thought | plan | action | observation | reflection | decision.",
                },
                "content": {
                    "type": "string",
                    "description": "operation='log' — REQUIRED. The trace entry text.",
                },
                "metadata": {
                    "type": "object",
                    "description": "operation='log' — Optional structured metadata to attach to the entry.",
                },
                # operation='trace' kwargs
                "tail": {
                    "type": "number",
                    "description": "operation='trace' — Number of recent entries to return (default 50).",
                },
                # Shared by both operations
                "step_id": {
                    "type": "string",
                    "description": "operation='log' / 'trace' — Optional step folder to scope the entry / filter.",
                },
                "decision_id": {
                    "type": "string",
                    "description": "operation='log' / 'trace' — Optional decision id to link / filter by.",
                },
            },
            "required": ["operation"],
        },
    },
    "tool_ground": {
        "short": "Register a grounded claim. mode='explicit' (sources) or 'from_context' (context_paths).",
        "description": "Unified grounding tool. mode='explicit' uses an explicit `sources` list (replaces tool_grounding_register). mode='from_context' anchors the claim to files already in the project context (replaces tool_ground_from_context).",
        "category": "research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["explicit", "from_context"]},
                "claim": {"type": "string"},
                "decision_id": {"type": "string"},
                "sources": {"type": "array", "items": {"type": "object"}},
                "context_paths": {"type": "array", "items": {"type": "string"}},
                "cited_excerpts": {"type": "array", "items": {"type": "string"}},
                "step_id": {"type": "string"},
                "confidence": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["claim"],
        },
    },
    "tool_verify": {
        "short": "Verify claims OR that declared outputs exist. scope='claim'|'project'|'outputs'.",
        "description": "Unified verification tool. scope='claim' checks one claim against a verifications list (replaces tool_claim_verify). scope='project' sweeps every registered grounded claim in the project (replaces tool_grounding_verify). scope='outputs' is the 'did the work actually land?' gate — it resolves the active (or named) protocol's declared expected_outputs against the filesystem (glob-aware) and reports each as present / empty / missing with a next_action telling you to regenerate (and bump a version) rather than log 'completed' over a missing or empty file; pass all_protocols=true to sweep every protocol in the execution log. PROVENANCE-BOUND (scope='claim'): supports:true is not accepted on assertion alone — each verification's evidence.path is resolved under the project root and the cited token (evidence.cited_text / locator / anchor / expected / token) must actually be present in that file (verbatim, whitespace-normalized, or ±0.5% numeric match). A supporting verification whose source lacks the token is downgraded to needs_revision; one with no checkable path/locator is kept but flagged unverifiable and the claim verdict becomes 'unverified' (never 'verified').",
        "category": "research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["claim", "project", "outputs", "step"]},
                "claim": {"type": "string"},
                "verifications": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "scope='claim' — list of {question, answer, supports: bool, evidence: {type, path, cited_text}}. For supports:true to be honoured, evidence.path must resolve under the project and contain evidence.cited_text (or locator/anchor/expected/token). Otherwise the entry is downgraded (needs_revision) or flagged unverifiable.",
                },
                "decision_id": {"type": "string"},
                "step_id": {"type": "string"},
                "protocol_name": {"type": "string", "description": "scope='outputs' — which protocol's expected_outputs to check (defaults to the active / most-recently-logged protocol)."},
                "all_protocols": {"type": "boolean", "description": "scope='outputs' — sweep every protocol in the execution log instead of just the active one."},
                "min_bytes": {"type": "integer", "description": "scope='outputs' — a file smaller than this counts as empty (default 1)."},
            },
        },
    },
    "tool_lessons": {
        "short": "Unified lessons + failure memory. operation=record|consult|failure_*|dead_end|mistake_replay.",
        "description": "Single entry point for the 'what went wrong / what did we learn' family. operation='record' appends a Reflexion-style lesson (was tool_lessons_record). operation='consult' retrieves the top-K matching prior lessons for the next task (was tool_lessons_consult). operation='failure_record' persists a known-bad URL/DOI / paywall hit (was tool_failure_record). operation='failure_check' pre-checks before retrying a download (was tool_failure_check). operation='failure_list' returns the most recent failures (was tool_failure_list). operation='dead_end' pulls lessons from every __DEAD_END folder (was tool_dead_end_lessons). operation='mistake_replay' surfaces recurring patterns from reliability + override logs (was tool_mistake_replay). The legacy tool names continue to dispatch through this entry point via alias + param injection.",
        "category": "research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "record",
                        "consult",
                        "failure_record",
                        "failure_check",
                        "failure_list",
                        "dead_end",
                        "mistake_replay",
                    ],
                },
                # record args
                "outcome": {"type": "string"},
                "reflection": {"type": "string"},
                "what_worked": {"type": "string"},
                "what_didnt": {"type": "string"},
                "recommendation": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "step_id": {"type": "string"},
                "scope": {"type": "string"},
                # consult args
                "task": {"type": "string"},
                "top_k": {"type": "integer"},
                "scope_filter": {"type": "array", "items": {"type": "string"}},
                # failure_record / failure_check / failure_list args
                "tool": {"type": "string", "description": "For failure_record: which tool errored."},
                "target": {"type": "string", "description": "For failure_record/failure_check: URL or DOI being checked."},
                "reason": {"type": "string", "description": "For failure_record: error reason (paywall, permanent_404, ...)."},
                "error_text": {"type": "string"},
                "permanent": {"type": "boolean"},
                # failure_list / mistake_replay shared
                "limit": {"type": "integer"},
            },
        },
    },
    "tool_reliability": {
        "short": "Unified reliability log. operation='log_event'|'report'. Replaces tool_reliability_log_event + tool_reliability_report.",
        "description": "Telemetry-free local reliability log. operation='log_event' appends one redacted structural event (gate fire, tool error, recovery, etc.) to workspace/.os_state/reliability.jsonl (was tool_reliability_log_event). operation='report' aggregates the log into a markdown summary at workspace/logs/reliability_report.md (was tool_reliability_report). The log contains no project content — safe to paste into a GitHub issue when filing a regression report. Allowed event types: gate_fire, gate_recover, gate_abandon, tool_error, tool_success, protocol_start, protocol_complete, override_used, stale_state_detected, paywall_skipped.",
        "category": "state",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["log_event", "report"]},
                # log_event args
                "event_type": {"type": "string"},
                "protocol_name": {"type": "string"},
                "model_profile": {"type": "string"},
                "payload": {"type": "object", "additionalProperties": True},
            },
        },
    },
    "mem_log": {
        "short": "Unified memory append. kind='methods'|'decision'|'hypothesis'|'analysis'. Use when logging a memory entry.",
        "description": "Consolidates the four memory-append tools behind one entry. kind='methods' (was mem_methods_append) takes method/parameters/justification. kind='decision' (was mem_decision_log) takes context/selected/rationale. kind='hypothesis' (was mem_hypothesis_update) takes hypothesis_id/status/evidence/step. kind='analysis' (was mem_analysis_log) takes a free-form entry.",
        "category": "memory",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["methods", "decision", "hypothesis", "analysis"]},
                "entry": {"type": "string"},
                "method": {"type": "string"},
                "step_name": {"type": "string"},
                "step_number": {"type": "string"},
                "dataset_name": {"type": "string"},
                "dataset_hash": {"type": "string"},
                "implementation": {"type": "string"},
                "parameters": {"type": "string"},
                "justification": {"type": "string"},
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "context": {"type": "string"},
                "selected": {"type": "string"},
                "rationale": {"type": "string"},
                "hypothesis_id": {"type": "string"},
                "status": {"type": "string"},
                "evidence": {"type": "string"},
                "step": {"type": "string"},
            },
            "required": ["kind"],
        },
    },
    "tool_skills": {
        "short": "Self-improving skill registry. operation=distill|promote|list: turn recurring lessons into reusable SKILL.md cards.",
        "description": "The self-improving loop on top of tool_lessons. operation='distill' clusters this project's recorded lessons (workspace/.lessons/lessons.jsonl) by tag and crystallizes every pattern seen >= min_occurrences times into a reusable, Hermes-compatible SKILL.md card under workspace/.skills/ (idempotent — rewrites cards in place). operation='promote' lifts project- and methodology-scoped distilled skills into the cross-project profile (~/.config/research-os/profile.yaml -> learned_skills) so the SAME researcher inherits them in their NEXT project (two-way learning: lessons flow up; research-os init reads them back down). operation='list' shows both the project-local distilled skills and the promoted cross-project ones. Pure local aggregation — no network, no model call; the AI triggers it and narrates the result. Run distill after a milestone (plan complete, paper drafted), then promote the durable lessons.",
        "category": "research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["distill", "promote", "list"],
                },
                "min_occurrences": {
                    "type": "integer",
                    "description": "A tag cluster becomes a skill only when seen this many times (default 2). Raise to be more conservative.",
                },
            },
            "required": ["operation"],
        },
    },
}
