# Research OS workspace — Claude Code

**Read `AGENTS.md` at the project root — it is the canonical, lean operating
manual** (session loop, hard rules, token economy, modes, quick lookup).
This file only adds the Claude-Code-specific essentials.

You act only AFTER a researcher message. On the **first turn** of a session,
two MCP calls before anything else:

1. `sys_boot` — state + config + history + next protocol + pause + active
   plan (one call; don't fire the individual sys_* calls separately).
2. `tool_route(prompt=<verbatim message>)` — picks the protocol; if
   `ask_user` is non-null, ASK it and re-route (never guess). Then walk an
   `active_plan` (`tool_plan`) for `complexity:high`, or load the protocol
   summary-first for `complexity:low`. (Full branching: AGENTS.md.)

Tools use underscores (`sys_state_get`, `tool_data`, `mem_log`); dot notation
+ legacy names auto-rewrite. Use `sys_boot` for current state, `tool_route` for
+ routing, and `sys_daemon` for gate/notification state. `sys_tool_describe(name)`
+ for a tool's full spec.

Research OS does NOT manage LLM provider keys — Claude Code owns model access.
The only credentials it uses are optional literature / web-search keys.
