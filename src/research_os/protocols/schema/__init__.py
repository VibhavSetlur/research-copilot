"""Protocol schema package — the single Pydantic source of truth.

``Protocol`` is the typed model every protocol YAML validates against
after Protocol Unification (P1). Routing metadata (intent_class,
sub_intent, triggers, summary, shortcut_tool, token_estimate,
decomposition) that used to live only in ``_router_index.yaml`` is now a
self-contained part of each protocol body, so one model validates all.
"""

from research_os.protocols.schema.protocol import (
    DecompositionStep,
    GateSpec,
    Protocol,
    RequiresBlock,
    RequirementCheck,
    Step,
)

__all__ = [
    "Protocol",
    "Step",
    "GateSpec",
    "RequirementCheck",
    "RequiresBlock",
    "DecompositionStep",
]
