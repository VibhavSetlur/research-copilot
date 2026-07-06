"""The ``Protocol`` Pydantic model — single source of truth (P1).

A protocol is a YAML file under ``src/research_os/protocols/`` (or a
pack's ``protocols/`` tree). Before Protocol Unification it had a body
(``id``, ``steps``, ``expected_outputs``, ``enforcement.gates``,
``requires.checks``, …) while its routing metadata (``intent_class``,
``triggers``, ``decomposition``, …) lived separately in
``_router_index.yaml``. Now the routing fields are merged INTO each
protocol body and this one model validates the whole thing.

Design notes:

* ``model_config`` allows EXTRA fields. Protocol bodies carry many
  pedagogical / presentational keys (``pedagogical_prelude``,
  ``model_adaptations``, ``lean_variant``, ``see_also``, …) that the
  runtime doesn't type but must round-trip. Extra keys are preserved so
  ``Protocol.model_dump()`` reconstructs the source faithfully.
* Validation is intentionally permissive on optional structure (steps
  may be free-form dicts) but strict on the load-bearing invariants:
  ``id`` is required, ``schema_version`` must be ``"3.0"`` post-merge,
  gate ``floor`` ∈ {light, normal, strict}, requirement ``kind`` is one
  of the four checkable kinds.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── routing-field allowlist (merged from the old _router_index.yaml) ───────
# These are the fields Step 1 injects into each protocol body. Only those
# actually present on an index entry are injected (per the merge policy);
# every one is optional on the model.
ROUTING_FIELDS: tuple[str, ...] = (
    "intent_class",
    "sub_intent",
    "triggers",
    "summary",
    "shortcut_tool",
    "token_estimate",
    "decomposition",
    "modes",
)

_VALID_FLOORS = {"light", "normal", "strict"}
_VALID_CHECK_KINDS = {
    "file_exists",
    "glob_min",
    "protocol_completed",
    "state_field",
}
_REQUIRED_CHECK_FIELD = {
    "file_exists": "path",
    "glob_min": "pattern",
    "protocol_completed": "protocol",
    "state_field": "field",
}


class DecompositionStep(BaseModel):
    """One entry in a protocol's planned tool/decision decomposition.

    Entries are heterogeneous — a ``tool`` step, a ``protocol`` step, or a
    free-form ``decision`` — so all fields are optional.
    """

    model_config = ConfigDict(extra="allow")

    tool: str | None = None
    protocol: str | None = None
    decision: str | None = None
    purpose: str | None = None


class GateSpec(BaseModel):
    """One declared floor gate (was ``enforcement.gates[*]``)."""

    model_config = ConfigDict(extra="allow")

    key: str
    tool: str
    floor: Literal["light", "normal", "strict"]
    when: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""

    @field_validator("when", mode="before")
    @classmethod
    def _coerce_when(cls, v: Any) -> dict[str, Any]:
        return v or {}


class RequirementCheck(BaseModel):
    """One mechanically-checkable precondition (was ``requires.checks[*]``)."""

    model_config = ConfigDict(extra="allow")

    kind: Literal["file_exists", "glob_min", "protocol_completed", "state_field"]
    path: str | None = None
    pattern: str | None = None
    protocol: str | None = None
    field: str | None = None
    because: str = ""
    non_empty: bool = False
    min: int = 1

    @field_validator("kind")
    @classmethod
    def _kind_ok(cls, v: str) -> str:
        if v not in _VALID_CHECK_KINDS:
            raise ValueError(f"check kind {v!r} not in {sorted(_VALID_CHECK_KINDS)}")
        return v


class RequiresBlock(BaseModel):
    """The ``requires:`` block (holds the checkable precondition list)."""

    model_config = ConfigDict(extra="allow")

    checks: list[RequirementCheck] = Field(default_factory=list)


class Step(BaseModel):
    """One protocol step. Free-form beyond id/name/description."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str = ""
    description: str = ""


class Enforcement(BaseModel):
    """The ``enforcement:`` block (holds the declared gate list)."""

    model_config = ConfigDict(extra="allow")

    gates: list[GateSpec] = Field(default_factory=list)


class Protocol(BaseModel):
    """The unified protocol model — body + merged routing metadata.

    Extra keys are allowed and preserved so a protocol dumped from this
    model round-trips to the source YAML (minus comments).
    """

    model_config = ConfigDict(extra="allow")

    # ── identity / metadata ──────────────────────────────────────────
    id: str
    name: str = ""
    version: str | None = None
    schema_version: str | None = None
    tier: str | None = None
    description: str = ""
    trigger: str = ""

    # ── body ─────────────────────────────────────────────────────────
    prerequisites: list[Any] = Field(default_factory=list)
    inputs: list[Any] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    expected_outputs: list[Any] = Field(default_factory=list)
    next_protocol: str | None = None
    next_protocol_kind: str | None = None
    on_failure: str | None = None
    enforcement: Enforcement | None = None
    requires: RequiresBlock | None = None

    # ── merged routing metadata (was _router_index.yaml) ─────────────
    intent_class: str | None = None
    sub_intent: str | None = None
    triggers: list[str] = Field(default_factory=list)
    summary: str = ""
    shortcut_tool: str | None = None
    token_estimate: int | None = None
    decomposition: list[DecompositionStep] = Field(default_factory=list)
    modes: list[str] = Field(default_factory=list)

    @field_validator("version", "schema_version", mode="before")
    @classmethod
    def _stringify(cls, v: Any) -> Any:
        # YAML may parse "3.0" as a float 3.0; keep versions as strings.
        if v is None:
            return v
        return str(v)

    # ── convenience accessors used by ProtocolRegistry ───────────────
    def gate_list(self) -> list[dict[str, Any]]:
        """Return declared gates as plain dicts (sidecar-compatible)."""
        if not self.enforcement:
            return []
        out: list[dict[str, Any]] = []
        for g in self.enforcement.gates:
            out.append(
                {
                    "key": g.key,
                    "tool": g.tool,
                    "floor": g.floor,
                    "when": g.when or {},
                    "reason": g.reason or "",
                    "source_protocol": self.id,
                }
            )
        return out

    def precondition_list(self) -> list[dict[str, Any]]:
        """Return checkable preconditions as plain dicts (sidecar-compatible)."""
        if not self.requires:
            return []
        out: list[dict[str, Any]] = []
        for c in self.requires.checks:
            req_field = _REQUIRED_CHECK_FIELD[c.kind]
            entry: dict[str, Any] = {
                "kind": c.kind,
                req_field: getattr(c, req_field),
                "because": c.because or "",
            }
            if c.kind == "file_exists" and c.non_empty:
                entry["non_empty"] = True
            if c.kind == "glob_min":
                entry["min"] = int(c.min)
            out.append(entry)
        return out
