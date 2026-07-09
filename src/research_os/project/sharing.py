"""Sharing-related constants and helpers.

Template strings are loaded from ``templates/*.tmpl`` files inside this
package (``importlib.resources`` so they are accessible whether installed
from PyPI or run from the source tree).  ``project_ops`` re-exports all
public symbols for backward compatibility.
"""
from __future__ import annotations

import importlib.resources
from pathlib import Path


# ---------------------------------------------------------------------------
# Sharing-exclusion / inclusion lists
# ---------------------------------------------------------------------------

# Files / directories EXCLUDED from the share-safe archive. These are
# either AI-internal (CLAUDE.md, AGENTS.md, MCP configs) or onboarding
# artefacts a downstream researcher does not need (GETTING_STARTED.md).
_SHARE_EXCLUDE_NAMES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GETTING_STARTED.md",
    # Secret-bearing: plaintext api_keys + author PII. NEVER ship it.
    "researcher_config.yaml",
    ".os_state",
    ".claude",
    ".cursor",
    ".vscode",
    ".antigravity",
    ".opencode",
    "mcp_config.json",
    ".mcp.json",
    "opencode.json",
    "__pycache__",
    ".pytest_cache",
    ".DS_Store",
    "node_modules",
    "venv",
    ".venv",
    "env",
)

# Folders that ARE included by default.
_SHARE_INCLUDE_DIRS = (
    "inputs",
    "workspace",
    "synthesis",
    "docs",
    "environment",
)


# ---------------------------------------------------------------------------
# Template loader (importlib.resources → works installed or from source)
# ---------------------------------------------------------------------------

def _load_template(name: str) -> str:
    """Read a ``*.tmpl`` file from this package's ``templates/`` sub-package.

    Uses ``importlib.resources`` so the file is found whether the package is
    installed as a wheel or run from the source tree.  Falls back to a
    filesystem path relative to this file so the source-tree case works even
    on Python 3.8 where ``importlib.resources.files`` is not available.
    """
    try:
        # Python 3.9+  — __name__ here is ``research_os.project.sharing``
        # so the templates sub-package is ``research_os.project.templates``.
        pkg = __name__.rsplit(".", 1)[0] + ".templates"  # research_os.project.templates
        ref = importlib.resources.files(pkg).joinpath(name)  # type: ignore[attr-defined]
        return ref.read_text(encoding="utf-8")
    except (AttributeError, ModuleNotFoundError, FileNotFoundError):
        pass
    # Fallback: same directory as this file, then templates/ sub-dir
    here = Path(__file__).parent
    candidate = here / "templates" / name
    if candidate.exists():
        return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Template not found: {name}")


# Lazy-loaded module-level template constants.
# Accessed as ``_EXPORT_PY_TEMPLATE`` etc. — identical to the old strings.
def _get_export_py_template() -> str:
    return _load_template("export_share_archive.py.tmpl")


def _get_init_github_template() -> str:
    return _load_template("init_github.sh.tmpl")


def _get_sharing_doc_template() -> str:
    return _load_template("SHARING.md.tmpl")


# Eagerly-computed module-level constants (matches old ``project_ops`` API).
# We load at import time so ``from research_os.project_ops import _EXPORT_PY_TEMPLATE``
# gives the same object type (str) it always did.
_EXPORT_PY_TEMPLATE: str = _get_export_py_template()
_INIT_GITHUB_TEMPLATE: str = _get_init_github_template()
_SHARING_DOC_TEMPLATE: str = _get_sharing_doc_template()


# ---------------------------------------------------------------------------
# _write_sharing_scripts
# ---------------------------------------------------------------------------

def _write_sharing_scripts(root: Path, project_name: str) -> None:
    """Scaffold the export-to-zip + GitHub init scripts. Idempotent."""
    # Import slugify lazily to avoid a circular dependency with project_ops.
    from research_os.project_ops import slugify

    scripts_dir = root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    export_py = scripts_dir / "export_share_archive.py"
    if not export_py.exists():
        export_py.write_text(_EXPORT_PY_TEMPLATE)
        try:
            export_py.chmod(0o755)
        except OSError:
            pass

    export_sh = scripts_dir / "export_share_archive.sh"
    if not export_sh.exists():
        export_sh.write_text(
            "#!/usr/bin/env bash\n"
            "# Build a share-safe zip of this project (no AI internals).\n"
            "# Equivalent to `python scripts/export_share_archive.py`.\n"
            "set -euo pipefail\n"
            'HERE="$(cd "$(dirname "$0")/.." && pwd)"\n'
            'python "$HERE/scripts/export_share_archive.py" "$@"\n'
        )
        try:
            export_sh.chmod(0o755)
        except OSError:
            pass

    init_gh = scripts_dir / "init_github.sh"
    if not init_gh.exists():
        slug = slugify(project_name, "research-project").replace("_", "-")
        init_gh.write_text(_INIT_GITHUB_TEMPLATE.replace("__SLUG__", slug))
        try:
            init_gh.chmod(0o755)
        except OSError:
            pass

    sharing_doc = root / "docs" / "SHARING.md"
    if not sharing_doc.exists():
        sharing_doc.write_text(_SHARING_DOC_TEMPLATE)
