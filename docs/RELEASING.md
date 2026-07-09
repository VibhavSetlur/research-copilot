# Releasing Research OS

This doc is for maintainers. If you just want to *use* Research OS,
read [START.md](START.md) instead.

---

## Versioning

[SemVer](https://semver.org). Given `MAJOR.MINOR.PATCH`:

* **PATCH** (`1.1.0 → 1.1.1`) — bug fixes, doc fixes, dependency bumps,
  no behaviour change for users following the public surface.
* **MINOR** (`1.1.0 → 1.2.0`) — new features, new protocols, new tools.
  Backwards-compatible: every existing tool keeps its name, schema, and
  semantics. Existing protocols stay loadable.
* **MAJOR** (`1.x → 2.0.0`) — breaking change. Reserved for tool-name
  renames, schema changes, removed protocols, or workspace-layout
  changes that need migration.

Pre-releases use `aN` / `bN` / `rcN` suffixes (e.g. `1.2.0rc1`).
The release workflow auto-detects them and marks the GitHub Release
as pre-release.

---

## Branch model

```
main           ← production. Protected. Every commit is tagged-or-tagable.
└── dev        ← integration. PRs land here first.
    └── feat/* ← short-lived feature branches off dev.
    └── fix/*  ← short-lived bug-fix branches off dev (or main for hotfixes).
```

* **`main`** — only receives merges from `dev` (or a hotfix branch).
  Direct pushes are disabled by branch protection. Every merge to
  `main` should be release-ready.
* **`dev`** — integration branch. Most PRs target this. Tests run on
  every push and PR.
* **`feat/<short-slug>`** — one feature per branch. Open a PR against
  `dev` when ready. Delete after merge.
* **`fix/<short-slug>`** — one bug per branch. Same flow.
* **`hotfix/<short-slug>`** — urgent production fix. Branch off `main`,
  PR back to `main` AND to `dev`. Tag a `PATCH` release as soon as it
  merges.

The "delete branch on merge" repo setting cleans up feature branches
automatically.

---

## Release flow

### Patch release (`1.1.0 → 1.1.1`)

For bug fixes + doc updates + dependency bumps. No new protocols or
tools.

```bash
# 0. Make sure dev is green
gh run list --workflow=tests --branch dev --limit 3

# 1. Pick the version
NEW=1.1.1

# 2. Bump version in code (one source of truth: src/research_os/__init__.py)
#    pyproject.toml uses static `version = "X.Y.Z"`; bump there too.
sed -i "s/^version = .*/version = \"$NEW\"/" pyproject.toml
sed -i "s/^__version__ = .*/__version__ = \"$NEW\"/" src/research_os/__init__.py

# 3. Bump CITATION.cff
sed -i "s/^version: .*/version: $NEW/" CITATION.cff
sed -i "s/^date-released: .*/date-released: $(date +%F)/" CITATION.cff

# Confirm Python-floor docs match pyproject.toml's requires-python before release:
# README.md, docs/SETUP.md, docs/CLI.md, and doctor output examples.

# 4. Add the CHANGELOG entry under a new ## [NEW] — date heading.
#    Group changes under Added / Improved / Fixed / Bumped sections.

# 5. Open a PR from dev → main with the bumps + CHANGELOG entry.
gh pr create --base main --head dev --title "Release v$NEW" \
  --body "Bumps version to $NEW. See CHANGELOG.md."

# 6. After CI passes and the PR merges, tag from main:
git checkout main && git pull
git tag -a "v$NEW" -m "v$NEW"
git push origin "v$NEW"

# 7. The publish.yml + release.yml workflows fire automatically:
#    * publish.yml builds sdist + wheel and uploads to PyPI via Trusted Publishing
#    * release.yml creates a GitHub Release from the CHANGELOG section
```

### Minor release (`1.1.x → 1.2.0`)

Same flow, but the PR title is `Release v1.2.0` and the CHANGELOG
entry should call out new protocols / tools / config knobs explicitly.

Pre-1.2: also bump every `protocols/**/*.yaml` `version:` field so
preflight's freshness check stays green. A `find` one-liner:

```bash
find src/research_os/protocols -name '*.yaml' -not -name '_*' \
  | xargs sed -i "s/^version: '.*'/version: '$NEW'/"
```

### Major release (`1.x → 2.0.0`)

Add a **Migration** section to the CHANGELOG entry covering every
breaking change with a before/after. Open the PR a week ahead and
solicit review.

---

## Hotfix

Production bug in 1.1.0; `dev` already has unreleased changes for 1.2.

```bash
git checkout main && git pull
git checkout -b hotfix/<short-slug>

# … fix the bug …

git commit -m "<conventional commit>"
gh pr create --base main --head hotfix/<short-slug> --title "Hotfix: …"

# After merge:
git checkout main && git pull
NEW=1.1.1
# … bump version (above), CHANGELOG entry, push tag.

# Then forward-merge into dev so the fix doesn't get lost:
git checkout dev && git pull
git merge main --no-edit
git push origin dev
```

---

## Pre-release checklist

Before tagging:

- [ ] Test suite green on `dev` (`gh run list --branch dev`).
- [ ] `python scripts/preflight.py` all checks pass (currently 24; check count varies — see scripts/preflight.py).
- [ ] `ruff check src/ tests/ scripts/` is clean.
- [ ] `__version__`, `pyproject.toml`, `CITATION.cff` agree.
- [ ] CHANGELOG.md has a fresh `## [X.Y.Z]` section with a date.
- [ ] If protocols changed: bumped their `version:` fields.
- [ ] No `1.0.0` (or stale-version) strings in docs.
- [ ] No `TODO` / `XXX` markers in the diff for this release.

---

## Post-release checklist

- [ ] PyPI shows the new version (`pip install research-os==X.Y.Z`).
- [ ] GitHub Releases tab shows the new release with the CHANGELOG body.
- [ ] If a hotfix: forward-merged `main` into `dev`.
- [ ] Updated [SECURITY.md](../SECURITY.md) supported-versions table if
      a minor / major shipped.
- [ ] Closed milestone (if one existed) and bumped the next milestone.

---

## Yanking a bad release

If a published version has a serious bug:

```bash
# Yank from PyPI (it stays installable by pinned versions but isn't the
# default resolution):
pip install twine
twine upload --skip-existing --repository pypi ...   # only if re-publishing
# OR via PyPI web UI: Manage → Release → Yank.
```

Then publish a fixed PATCH release immediately. Document the yank in
the new release's CHANGELOG entry.
