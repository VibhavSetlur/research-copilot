"""State package — ledger management and migration utilities.

Canonical state loader
----------------------
The one authoritative loader is ``research_os.project_ops.load_state``,
which returns a plain ``dict`` (ResearchLedger v4.0 shape) via
:class:`~research_os.state.state_ledger.ResearchLedger`.

``state_schema.load_state`` has been renamed to
``state_schema._load_state_pydantic`` and is scoped to unit tests only.
It is intentionally NOT re-exported here to prevent it from being used
as a competing canonical loader.

``migrate_state`` is re-exported because it is a pure dict transform used
by the ResearchLedger migration path and is safe to share.
"""

from research_os.state.state_schema import migrate_state

__all__ = ["migrate_state"]
