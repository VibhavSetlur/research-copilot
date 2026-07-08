# Research-OS — maintainer guide for Claude

This file is for **Claude sessions working on the Research-OS codebase
itself** (the MCP server, protocols, tools). Not to be confused with
`templates/CLAUDE.md`, which gets copied into end-user research projects
when they run `research-os init`.

End-user-facing docs live in `docs/`. Maintainer-facing docs:
[`CONTRIBUTING.md`](CONTRIBUTING.md), [`docs/RELEASING.md`](docs/RELEASING.md),
[`docs/PROTOCOL_DOCTRINE.md`](docs/PROTOCOL_DOCTRINE.md).

---

## The v4.0.0 push (standing order)

We are driving Research-OS to a true final **4.0.0** on branch
`feat/v4-daemon-core`. When the maintainer says only **"continue"**, that
means: take a fresh, **comprehensive, holistic** pass over the *whole*
system from multiple personas — the naive AI under context pressure, the
grad student who can't verify, the PI / reviewer who needs trust, and each
mode (analysis · tool-build · hybrid) plus the shared-HPC researcher — find
inconsistencies, bugs, stale/un-updated parts, and missing or half-built
features, and **hammer many of them out in one pass** (not one or two).
Bring anything that hasn't been touched in a while up to the current
architecture; never leave loose ends.

**The architecture we're converging on:** the daemon is an
enforcement + execution + notification **kernel** that fronts the
(already-good) MCP + protocols. The throughline is turning **soft, trusted
prose into hard, verified structure** — while the *reasoning* layer stays
soft per [`docs/PROTOCOL_DOCTRINE.md`](docs/PROTOCOL_DOCTRINE.md). Designs
for each piece live in [`docs/`](docs/) (UNSKIPPABLE_GATES,
HYBRID_ARCHITECTURE, STALENESS_GATE, NOTIFICATION_SPINE, RESOURCE_BUDGET,
PRECONDITION_GATE, DAEMON_BRIDGE).

**Non-negotiables for every change:**
- **Seam (preflight-enforced):** `server/` and `tools/` MUST NOT import
  `research_os.daemon`. Cross-process only via the on-disk `.os_state/`
  contract, read by shape through `server/daemon_bridge.py` (canonical
  paths + `daemon_present` + `http_get`/`http_post`).
- **Fail-safe closed / degrade-open:** no daemon ⇒ behave exactly as
  today (stdio users unaffected); ambiguous enforcement ⇒ never silently
  pass a gate, never falsely block.
- **`_LEGACY_*` tables are deliberate fail-safes**, not dead code — keep
  them (they activate only when a compiled sidecar is missing).
- **Real "legacy" = unfinished loops, scattered duplication, stale docs** —
  that's what to hunt and fix, not working safety nets.
- After touching `protocols/`, rebuild the sidecars:
  `build_gate_meta.py`, `build_precondition_meta.py`, `build_embeddings.py`.
- A new tool must be wired everywhere: `TOOL_DEFINITIONS` + `HANDLERS` +
  `__all__` + `docs/TOOLS.md` + rebuilt embeddings.
- **Five drift guards** keep the system self-consistent (route-meta,
  gate-meta, precondition-meta, daemon-endpoint catalogue, daemon⇆bridge
  contract). Add a guard whenever you introduce a new cross-layer contract.
- Run the full release gate (below) before **every** commit. Version bump +
  CHANGELOG happen only in the `dev → main` release PR, never on the feat
  branch.

---

## Environment

Use the **`research-os` conda env** for everything in this folder
(per `/scratch/vsetlur/CLAUDE.md`):

```bash
source /scratch/vsetlur/anaconda3/etc/profile.d/conda.sh && conda activate research-os
```

System python (3.12 from /usr/bin) does NOT have `pytest` / `ruff`
installed. Always activate the env first.

---

## Always do before declaring work "done"

```bash
python scripts/preflight.py     # release gate must pass; counts are checked dynamically
python -m pytest -q             # run the full suite; must all pass
ruff check src/ tests/ scripts/ # must be clean
```

These three are the **release gate**. If any of them fails, the work
isn't done. Don't push, don't tag, don't commit a version bump.

---

## Versioning — which bump?

Research-OS follows [SemVer](https://semver.org). Decide based on
**what changed for users**, not how much code moved:

| Change | Bump | Examples |
|---|---|---|
| Bug fix, doc fix, dependency bump, internal refactor with no behaviour change | **PATCH** (`1.1.0 → 1.1.1`) | Fix a router edge case; rewrite README; update CONTRIBUTING; bump CI action versions; fix a typo in a protocol step description. |
| New feature, new protocol, new tool, new config knob — **backwards-compatible** | **MINOR** (`1.1.0 → 1.2.0`) | Add a new protocol YAML; add a new MCP tool; add a new `sys_help` topic; add a new optional field to `researcher_config.yaml`; add a new audit gate that defaults off. |
| Breaking change to the public surface | **MAJOR** (`1.x → 2.0.0`) | Rename / remove an MCP tool without alias; change a tool's required input schema; remove a protocol; change `inputs/` directory layout; require Python ≥ 3.13. |

**Rule of thumb:** if an existing project on the old version would
break after upgrading, it's a MAJOR. If everything still works AND
new things appear, it's a MINOR. If nothing visible changed, it's a
PATCH.

When unsure between PATCH and MINOR: **anything that adds new
trigger phrases, new protocol files, or new tools is MINOR.** Pure
fixes + docs are PATCH.

---

## Branch model (must follow)

```
main           ← protected. Tag = release. Only reached via PR from dev (or hotfix).
└── dev        ← integration. Most PRs land here.
    └── feat/<slug>   ← new feature
    └── fix/<slug>    ← bug fix
    └── docs/<slug>   ← docs only
    └── hotfix/<slug> ← branches off MAIN, PRs back to both main + dev
```

**`main` is protected** by branch rules (5 required CI status checks +
linear history + no force push + no deletions). Direct pushes to main
are blocked. The ONLY ways into main:

1. PR from `dev` (normal release) — squash-merge
2. PR from `hotfix/<slug>` (urgent production fix) — squash-merge,
   then forward-merge main back into dev

### Where to work

| What you're doing | Branch |
|---|---|
| Fixing a bug | `fix/<slug>` off `dev` → PR to `dev` |
| Adding a feature / protocol / tool | `feat/<slug>` off `dev` → PR to `dev` |
| Editing docs only | `docs/<slug>` off `dev` → PR to `dev` |
| Urgent production bug | `hotfix/<slug>` off `main` → PR to `main` AND `dev` |
| Preparing a release | PR `dev → main` titled `Release v<X.Y.Z>` |

**Never** commit version bumps to `dev` and call it done. The bump +
CHANGELOG entry are part of the release PR `dev → main`.


---

## Release flow — the one canonical sequence

The full runbook is [`docs/RELEASING.md`](docs/RELEASING.md). Short version:

```bash
# 0. Decide the version bump (see table above). NEW=1.1.2 (example PATCH).
NEW=1.1.2

# 1. On dev branch, make sure tests are green
git checkout dev && git pull
python scripts/preflight.py && python -m pytest -q && ruff check src/ tests/ scripts/

# 2. Bump version in 3 places (single source of truth: __init__.py)
sed -i "s/^version = .*/version = \"$NEW\"/" pyproject.toml
sed -i "s/^__version__ = .*/__version__ = \"$NEW\"/" src/research_os/__init__.py
sed -i "s/^version: .*/version: $NEW/" CITATION.cff
sed -i "s/^date-released: .*/date-released: $(date +%F)/" CITATION.cff

# 3. For MINOR / MAJOR: also bump every protocol YAML version field
# (skip for PATCH releases unless protocol behavior changed)
# find src/research_os/protocols -name '*.yaml' -not -name '_*' \
#   | xargs sed -i "s/^version: '.*'/version: '$NEW'/"

# 4. Add a CHANGELOG entry — new ## [NEW] — (YYYY-MM-DD) section at the
# TOP of CHANGELOG.md, above the previous version's entry.
# Group changes: Added / Improved / Fixed / Bumped.

# 5. Commit on dev
git add -A
git commit -m "v$NEW <short description>"
git push origin dev

# 6. Open + merge the release PR
gh pr create --base main --head dev \
  --title "Release v$NEW" \
  --body "Bumps version to v$NEW. See CHANGELOG.md for details."
# Wait for CI to pass, then squash-merge via:
gh pr merge --squash --delete-branch=false   # keep dev around

# 7. Tag from main — this triggers publish.yml (PyPI) + release.yml (GitHub Release)
git checkout main && git pull
git tag -a "v$NEW" -m "v$NEW"
git push origin "v$NEW"

# 8. Verify (wait ~2 min for workflows)
gh run list --limit 5
gh release view "v$NEW"
curl -sL https://pypi.org/simple/research-os/ | grep "$NEW"
```

**For autonomous-mode commits to main:** branch protection allows
admins to bypass — but DON'T. The whole point of the branch model is
that even the maintainer goes through PRs so CI catches mistakes. If
you genuinely need to bypass for a doc-only fix, use `--admin` on the
merge AND document why in the commit message.

---

## Hard invariants (never violate)

1. **Never push directly to `main`.** Always via PR from `dev` (or hotfix).
2. **Never push a tag without a matching CHANGELOG entry.** The release
   workflow extracts the CHANGELOG section as the GitHub Release body;
   no section = ugly fallback release notes.
3. **Never bump `pyproject.toml` without also bumping `__init__.py`
   and `CITATION.cff`.** All three must agree.
4. **Never skip the test gate.** preflight 25/25 (or higher; the count grows) + `pytest 895+ pass`
   + `ruff clean` before push.
5. **Never reduce the protocol/tool count without an explicit MAJOR
   bump + a Migration section in the CHANGELOG.** Removing a tool or
   protocol is breaking.
6. **Never edit a published CHANGELOG section.** Append a new one. The
   published one is what was actually released.
7. **Never disable the test workflow gate on a PR to main** to merge
   faster — the whole point is to not.

---

## File locations cheat sheet

| What | Where |
|---|---|
| MCP tool definitions | `src/research_os/server/tool_definitions/*.py` (merged in `registry.py`) |
| MCP tool handlers | `src/research_os/server/handlers/*.py` (merged in `handlers/__init__.py`) |
| Tool aliases / removed-tool messages | `src/research_os/server/aliases.py` |
| Protocols | `src/research_os/protocols/<category>/<name>.yaml` |
| Router index (authoring source of triggers + decompositions) | `src/research_os/protocols/_router_index.yaml` |
| Compiled routing sidecar (runtime; built from the index) | `src/research_os/protocols/_route_meta.json` |
| Hierarchical router | `src/research_os/tools/actions/router.py` + `semantic.py` |
| Protocol loader + pipeline ordering | `src/research_os/tools/actions/protocol.py` |
| Tool action modules | `src/research_os/tools/actions/{audit,data,exec,memory,research,search,state,synthesis,viz}/` |
| Wizard (`research-os init`) | `src/research_os/wizard.py` |
| Per-IDE templates | `templates/` (AGENTS.md, CLAUDE.md, .cursor/, etc.) |
| Preflight wiring checks | `scripts/preflight.py` |
| Tests | `tests/{unit,integration,tools}/` |
| Release workflows | `.github/workflows/{publish,release,test,codeql}.yml` |
| Dependabot config | `.github/dependabot.yml` |
| Maintainer release runbook | `docs/RELEASING.md` |
| Protocol authoring doctrine | `docs/PROTOCOL_DOCTRINE.md` |

---

## When working on protocols

* Read [`docs/PROTOCOL_DOCTRINE.md`](docs/PROTOCOL_DOCTRINE.md) first —
  protocols are **scaffolds for reasoning, not scripts to execute**.
  Reviewers reject prescriptive protocols on sight (hardcoded thresholds,
  named methods picked from a menu, canned step sequences with no
  branch points).
* Every new protocol needs an entry in
  `src/research_os/protocols/_router_index.yaml` with `intent_class`,
  `sub_intent`, `summary`, `triggers`. Preflight fails without it.
* Don't add a `protocol_completion` step manually — the loader injects it.
* `next_protocol` must point at a real protocol or `null`.
* Bump the protocol's `version:` field to match the next package release.

---

## When working on tools

* Add to `TOOL_DEFINITIONS` in the matching `server/tool_definitions/*.py`
  module with `short` + `description` + `category` + `inputSchema`.
* Add a handler `_handle_<name>` in the matching `server/handlers/*.py`
  module and register it in that module's `HANDLERS` (merged into `_HANDLERS`
  by `handlers/__init__.py`).
* Reference the tool from at least one protocol's `decomposition` or
  a `shortcut_intents` entry — orphaned tools get removed.
* Tool name format: `sys_X_Y` / `tool_X_Y` / `mem_X_Y` (underscores;
  dots auto-rewrite for back-compat).
* Renaming a tool? Add an alias to `_ALIASES` and never remove the old
  name without a MAJOR bump.

---

## Dependabot PRs

Open Dependabot PRs in this repo target `main` directly (the dependabot
default). They're low-risk Actions / Python dep bumps, gated by CI.
Workflow:

1. `gh pr list --state open --search "author:app/dependabot"`
2. Review the diff. For Actions bumps, confirm the new major doesn't
   break Node version compatibility (CodeQL action v3 → v4 was a
   Node 20 → 24 jump, fine; some actions deprecate v3 inputs).
3. If green: `gh pr merge <num> --squash --delete-branch`
4. If a bump breaks CI, close + add the dep to `dependabot.yml`'s
   `ignore` list with a comment explaining why.

---

## Common Claude gotchas

* **Forgetting to activate the conda env** → `pytest: command not found`.
  Always `conda activate research-os` first.
* **Bumping version on `dev` and merging to `main` without tagging** →
  PyPI doesn't update. The tag IS the release trigger.
* **Editing `_router_index.yaml` without bumping `version:`** at the
  top of the file → readers can't tell the index changed.
* **Adding a protocol but forgetting the router index entry** →
  preflight fails. Always run preflight after touching `protocols/`.
* **Writing docs that reference tool counts** — they go stale fast.
  Either omit the number, or `git grep` the number before bumping.
* **Touching the `_PROTOCOL_COMPLETION_BLOCK` constant** in
  `tools/actions/protocol.py` — tests check the `id`, but a major
  rewrite changes the AI's end-of-protocol behavior across every
  protocol. Coordinate with a MINOR bump + CHANGELOG entry.
