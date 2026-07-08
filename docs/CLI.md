# Research OS — CLI reference

`research-os` ships ten top-level commands. A few set up + run the MCP
server; the rest wire integrations, preview routing, diagnose health,
keep project templates fresh, and emit shell completions.

| Command            | What it does                                         |
| ------------------ | ---------------------------------------------------- |
| `research-os init` | Scaffold a workspace ready for any AI IDE.           |
| `research-os ide`  | Add / remove / list AI IDE MCP configs.              |
| `research-os mcp`  | Compose third-party MCP servers into IDE configs.    |
| `research-os hermes` | Wire Research-OS into Hermes Agent (`~/.hermes/config.yaml`). |
| `research-os skills` | Install / list science-skill libraries (K-Dense scientific-agent-skills). |
| `research-os route` | Preview the protocol router for a prompt (no IDE needed). |
| `research-os api-key` | Manage api_keys in `inputs/researcher_config.yaml`. |
| `research-os start`| Run the MCP server (your IDE auto-launches it).      |
| `research-os doctor` | Diagnose install + workspace health (this page).   |
| `research-os refresh` | Refresh project copies of bundled templates (drift check). |
| `research-os completion` | Print a sourceable shell-completion script.    |

See `research-os <command> --help` for full flag reference.

---

## `research-os init`

Scaffolds a Research OS workspace ready for any AI IDE. Interactive by default; pass `--yes` for non-interactive / scripted use.

```bash
# Interactive 7-step arrow-key wizard (default).
research-os init

# Non-interactive / CI / scripted — wires only Claude Code, no prompts.
research-os init . --yes --name "my-project" --ide claude

# Wire all supported IDEs.
research-os init . --yes --ide all

# Skip IDE wiring entirely (e.g. for headless / CI / multi-user HPC).
research-os init . --yes --ide none

# Comma-separated list of specific IDEs.
research-os init . --yes --ide cursor,vscode,windsurf
```

### `--ide` values

`cursor`, `claude`, `antigravity`, `opencode`, `vscode`, `windsurf`, `continue`, `aider` — plus the sentinels:

- `all` — wire every supported IDE (drops MCP config files in each).
- `none` — first-class opt-out; no MCP config written.

Unknown values exit non-zero with a message listing valid options.

---

## `research-os ide add | remove | list`

Wires / unwires / inspects AI IDE MCP configs in an existing workspace without re-running `init`. Use this when you start using a new IDE on a project that's already initialized.

```bash
research-os ide add cursor              # add Cursor MCP config to this workspace
research-os ide remove vscode           # remove VS Code's
research-os ide list                    # which IDEs are wired here
research-os ide config-path claude      # print the absolute path of the config file
```

---

## `research-os mcp add | list | remove | template`

Composes **other** MCP servers (Slack, GitHub, Postgres, Filesystem,
Memory, Notion, ...) into the IDE configs Research-OS already manages,
so your AI IDE picks them up alongside the RO server.

Additive to `research-os ide add`, which wires the RO server itself.

```bash
# Drop a vetted snippet for a known server (with ${TOKEN} placeholders).
# Known templates: slack, github, postgres, notion, filesystem, memory.
research-os mcp template slack

# Roll your own — adds to every wired IDE config by default.
research-os mcp add my-server --command npx --args=-y,@scope/server-name

# Restrict to specific IDEs (cursor, claude, antigravity, vscode, opencode).
research-os mcp add my-server --command npx --args=-y,@x --ide cursor,claude

# Inspect every wired server across IDEs.
research-os mcp list

# Remove (idempotent — no-op if not present).
research-os mcp remove my-server
```

Note: only IDEs with JSON `mcpServers` (or `mcp` for OpenCode) blocks
can be composed this way. Windsurf / Continue / Aider use their own
rule files and are not supported here.

---

## `research-os hermes add | remove | status`

Wires Research-OS into [Hermes Agent](https://hermes-agent.nousresearch.com)
by editing its global config (`~/.hermes/config.yaml`). Registers the RO
MCP server under `mcp_servers:` and installs the canonical RO `SKILL.md`
so Hermes loads the research workflow automatically. The edit is
comment-preserving, idempotent, and reversible.

```bash
# Wire it: auto-detects the stdio launch command and installs the skill.
research-os hermes add

# Check what's wired.
research-os hermes status

# Unwire (idempotent — no-op if not present).
research-os hermes remove

# Register an HTTP/SSE endpoint instead of a stdio command.
research-os hermes add --url http://127.0.0.1:8765/mcp

# Override the launch command / args explicitly.
research-os hermes add --command research-os --args start

# Target a non-default config location.
research-os hermes add --config /path/to/config.yaml
```

Respects `$HERMES_CONFIG` and `$HERMES_HOME`. When the skill lands in the
built-in `~/.hermes/skills` tree (which Hermes already scans), no
`skills.external_dirs` entry is added. Restart Hermes after `add` to pick
up the new server and skill.

---

## `research-os skills add-science-pack | list-science`

Bring case-specific scientific capability into the AI's skill layer. Research
OS supplies the rigorous workflow; **skills** supply the field-specific how-to.

```bash
# Clone the K-Dense scientific-agent-skills library (140 MIT skills in the open
# Agent-Skills standard) and wire it into Hermes skills.external_dirs.
research-os skills add-science-pack

# Pin a specific release / choose where it clones.
research-os skills add-science-pack --ref v1.2.3 --dest ~/sci-skills

# Clone only, don't touch the Hermes config.
research-os skills add-science-pack --no-hermes

# Show the domain → skill map RO uses for recommendations.
research-os skills list-science
```

The library is REFERENCED (shallow clone, pinned ref, recorded commit), not
vendored. After install, restart Hermes so it loads the new skills; IDEs on the
Agent-Skills standard can point at the printed `skills/` dir. RO's
`sys_boot.recommended_skills` then names the specific skills that match each
project's domain + mode. License: MIT (source:
github.com/K-Dense-AI/scientific-agent-skills).

---

## `research-os route "<prompt>"`

Preview the protocol router from the terminal — the same hierarchical
router the MCP `tool_route` calls. Prints the matched protocol, intent
class, planned tool sequence, and ranked alternatives so you can see
what Research-OS *would* do for a request without opening an IDE. It is
read-only: it never persists an active plan.

```bash
# Human-readable decision.
research-os route "fit a mixed-effects model to my data"

# Raw decision as JSON (for scripting / non-MCP agents).
research-os route "draft the methods section" --json
```

Run it inside a workspace for state-aware routing (it reads the project
workflow shape + workspace mode), or anywhere for a stateless preview.

---

## `research-os api-key add | list | rotate | remove | test`

Manages the `api_keys:` block of `inputs/researcher_config.yaml`.
Hidden input via `getpass` so secrets never echo; `chmod 600` is
re-applied after every write.

```bash
# Hidden prompt (getpass) — value is read interactively, not from argv.
research-os api-key add semantic_scholar

# CI-friendly: read from an env var so the secret never appears in a
# shell-history file or a CI log.
research-os api-key add openai --from-env OPENAI_API_KEY

# Show every configured provider with masked previews (abcd…wxyz).
research-os api-key list

# Replace an existing key (same as `add`; just clearer naming).
research-os api-key rotate pubmed

# 1-token round-trip against the provider to verify the key works.
# Reports "OK" or "FAIL <reason>". Known: semantic_scholar, pubmed, crossref.
research-os api-key test pubmed

# Clear a key (sets the value to "").
research-os api-key remove crossref
```

Exit codes: `0` on success / OK; `1` on FAIL; `2` on bad usage (no
provider given, etc.).

---

## `research-os start`

Runs the MCP server. Your AI IDE auto-launches this; you rarely call it directly.

```bash
research-os start                       # uses current directory as workspace
research-os start --workspace /path/to/project
```

---

## `research-os daemon <subcommand>`

The **optional** persistent process: long jobs without blocking the chat,
run provenance + freshness, hard human-approved gates, an enforced resource
budget, and completion notifications. Full guide: [DAEMON.md](DAEMON.md).
Research OS works fully without it — start it for big / long-lived projects.

```bash
research-os daemon setup          # HPC-friendly: free port + conda check + bg launch line
research-os daemon setup --start  # ...and start it detached now (no Docker/systemd)
research-os daemon start          # serve the localhost API + job queue (foreground)
research-os daemon start --background  # detached launch (logs to .os_state/daemon.log)
research-os daemon status         # is it running? which project is active?
research-os daemon stop           # graceful per-project stop

# long jobs + provenance
research-os daemon run "<cmd>"    # run a command as a tracked job
research-os daemon docker IMG -- CMD  # run in a Docker/Podman image (records image+digest)
research-os daemon runs           # list recorded runs
research-os daemon logs <run_id>  # a run's details + captured output
research-os daemon submit "<cmd>" # submit to SLURM with provenance
research-os daemon reproduce <id> # re-run a recorded run, check outputs match
research-os daemon diff <a> <b>   # compare two runs (command, env, outputs)

# freshness
research-os daemon lineage        # the run dependency graph
research-os daemon stale          # which runs are stale
research-os daemon rebuild        # re-run only the stale sub-graph

# the human side of hard gates
research-os daemon consent                # list pending approval requests + grants
research-os daemon consent approve <id>   # mint a one-shot, argument-bound token
research-os daemon consent deny <id>      # refuse

# notifications + misc
research-os daemon notifications  # the outbox + delivery status (--undelivered)
research-os daemon domain         # detected research field + defaults
```

`research-os daemon gateway` was removed in v5. Use MCP stdio for AI-client
connections; use `daemon status`, `daemon exec`, and the run/consent commands
above for daemon-managed execution and approval flows.

Every subcommand takes `--help` for its own flags. The daemon binds
`127.0.0.1` only.

---

## `research-os doctor`

Runs a battery of health checks against the install and (if invoked
inside a workspace) the workspace itself. Modelled on `brew doctor` /
`rustup doctor` — every check returns one of three statuses:

| Status | Meaning                                                       |
| ------ | ------------------------------------------------------------- |
| pass   | Everything looks correct.                                     |
| warn   | Non-fatal: the user should know, but the install is usable.   |
| fail   | Something is genuinely broken and will bite at runtime.       |

### Exit codes

| Code | Condition                          |
| ---- | ---------------------------------- |
| 0    | All checks pass (no warnings).     |
| 1    | At least one warn, no fail.        |
| 2    | At least one fail.                 |

### Flags

| Flag              | Meaning                                                              |
| ----------------- | -------------------------------------------------------------------- |
| `--verbose`       | Show fix hints even for passing checks.                              |
| `--workspace-only`| Skip install checks; only run workspace checks.                      |
| `--workspace PATH`| Explicit workspace path (default: walk up from CWD).                 |
| `--json`          | Emit machine-readable JSON instead of the human report.              |
| `--no-color`      | Disable ANSI styling (auto-disabled when `NO_COLOR` is set).         |

### What gets checked

#### Install-level (always)

| Check                       | Purpose                                                                                |
| --------------------------- | -------------------------------------------------------------------------------------- |
| `python_version`            | Python >= 3.11 (matches `pyproject.toml`'s `requires-python`).                         |
| `conda_active`              | Warns if `CONDA_DEFAULT_ENV` is unset.                                                 |
| `version_consistency`       | `pyproject.toml`, `__init__.py`, `CITATION.cff` agree on the same version string.     |
| `in_tree_packs_registered`  | All 5 bundled packs (humanities, qualitative, theory_math, wet_lab, engineering) import and register cleanly. |
| `external_pack_entrypoints` | Lists external packs declared under the `research_os.protocol_pack` / `research_os.packs` entry-point groups. |
| `embeddings_fresh`          | `_embeddings.npz` mtime >= `_router_index.yaml` mtime — otherwise the semantic router is stale. |
| `typst_on_path`             | `typst` CLI for poster + PDF synthesis.                                                |
| `chromium_on_path`          | Optional: headless Chromium for the print-stylesheet audit.                            |

#### Workspace-level (only when inside a workspace)

| Check                       | Purpose                                                                                |
| --------------------------- | -------------------------------------------------------------------------------------- |
| `optional_deps`             | If `synthesis.interactive_figures` is enabled, `pyvis` must be importable.             |
| `mcp_configs_wired`         | Each declared IDE has its primary MCP config file.                                     |
| `workspace_integrity`       | No orphan figures, no unresolved BLOCK gates in the audit ledger. |
| `disk_space`                | Workspace size under 5 GB (warns above).                                               |
| `git_clean`                 | Working tree clean (skipped when the workspace isn't a git repo).                      |
| `gitignore_covers_state`    | `.gitignore` mentions `.os_state/` and `workspace/scratch/`. |

### Examples

```bash
# Full report — install + workspace if cwd is inside one.
research-os doctor

# Just JSON (for CI / scripts).
research-os doctor --json | jq .summary

# Show fix hints even for passing checks.
research-os doctor --verbose

# Only check this workspace (skip install).
cd /path/to/my-research && research-os doctor --workspace-only

# Explicit workspace path.
research-os doctor --workspace /path/to/my-research
```

### JSON shape

```json
{
  "checks": [
    {"name": "python_version", "status": "pass",
     "message": "Python 3.11.15 (>= 3.11)", "scope": "install"},
    ...
  ],
  "summary": {"pass": 6, "warn": 2, "fail": 0},
  "exit_code": 1
}
```

Every check entry has `name`, `status`, `message`, and `scope`
(`install` or `workspace`). When a check produced a fix hint, the
entry also carries a `fix` field.

---

## `research-os refresh`

Detects drift between a project's copies of the bundled templates
(`AGENTS.md`, `CLAUDE.md`, `.claude/rules/research-os.md`, and the
per-IDE rule files) and the versions shipped with the installed
`research-os`. The wizard copies templates once at init, so a project
that has lived across a few releases can be teaching the AI a stale tool
surface or out-of-date hard rules. `refresh` shows the gap and, with
`--write`, overwrites the project copies in place.

Read-only by default. `--check` exits non-zero on drift so CI can fail
when a project falls out of sync.

```bash
research-os refresh                 # report drift (default, read-only)
research-os refresh --check         # report + exit 1 if any drift
research-os refresh --write         # prompt per-file, then overwrite
research-os refresh --write --yes   # overwrite every drifted file, no prompts
research-os refresh --regen-readme  # also regenerate project-root README.md
research-os refresh --json          # machine-readable report
```

| Flag             | Meaning                                                            |
| ---------------- | ----------------------------------------------------------------- |
| `--check`        | Report only; exit non-zero if any project copy has drifted.       |
| `--write`        | Overwrite drifted project copies with the bundled template.       |
| `-y`, `--yes`    | With `--write`, skip the per-file confirmation prompt.            |
| `--regen-readme` | Also regenerate the project-root `README.md` with the current step inventory + synthesis deliverable list (use at finalize). |
| `--workspace`    | Explicit workspace path (default: walk up from CWD).              |
| `--json`         | Emit JSON instead of the human-readable report.                  |
| `--no-color`     | Disable ANSI styling (auto-disabled when `NO_COLOR` is set).      |

---

## `research-os completion`

Print a sourceable shell-completion script. Supports **bash**, **zsh**, and
**fish**. After sourcing the output, `research-os <TAB>` completes
subcommand names and `research-os init --ide <TAB>` completes IDE names.

```bash
# Install into your shell rc file (one-liner):
eval "$(research-os completion zsh)"     # zsh — add to ~/.zshrc
eval "$(research-os completion bash)"    # bash — add to ~/.bashrc
research-os completion fish | source     # fish — for current shell
research-os completion fish \
  > ~/.config/fish/completions/research-os.fish   # fish — persistent
```

For richer dynamic completion in bash/zsh (subcommand-aware flags),
install the `completion` extra so [argcomplete](https://pypi.org/project/argcomplete/)
backs the generated script:

```bash
pip install "research-os[completion]"
```

Without that extra, a smaller hand-rolled fallback is emitted — TAB
still completes top-level subcommands and `--ide` values.
