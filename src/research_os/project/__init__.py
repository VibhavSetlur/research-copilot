"""``research_os.project`` — internal sub-package for workspace operations.

Submodules
----------
layout          Canonical directory layout (LAYOUT_SPEC, SCAFFOLD_PROFILES, …)
step_discovery  Step-dir discovery (discover_step_dirs, resolve_step_dir, …)
overrides       Override-gate validation, logging, and enforcement
sharing         Sharing templates and helpers (_EXPORT_PY_TEMPLATE, …)

Public symbols live in the submodules below and are re-exported by
``research_os.project_ops`` for backward compatibility — callers that do::

    from research_os.project_ops import scaffold_minimal_workspace

continue to work unchanged.
"""
