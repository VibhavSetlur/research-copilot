"""Hybrid gate layer: protocols declare floor gates, the engine enforces.

docs/HYBRID_ARCHITECTURE.md. A protocol's ``enforcement.gates`` block
compiles (scripts/build_gate_meta.py) into protocols/_gate_meta.json, which
server/gate_spec.py reads and server/autopilot_gate.py enforces. These
tests drive gate_spec's predicate evaluator + loader directly and assert
the compiled sidecar reproduces the engine's floor exactly (zero behaviour
change vs the legacy hand-coded tables).
"""
from __future__ import annotations

import pytest

from research_os.server import gate_spec as gs


# --- when-predicate evaluator ---------------------------------------------

def test_empty_when_always_matches():
    assert gs._match_predicate({}, {"anything": 1}, None) is True


def test_scalar_equality_string_normalised():
    assert gs._match_predicate({"operation": "abandon"},
                               {"operation": "abandon"}, None) is True
    assert gs._match_predicate({"operation": "abandon"},
                               {"operation": "create"}, None) is False
    # missing arg → empty string → no match
    assert gs._match_predicate({"operation": "abandon"}, {}, None) is False


def test_list_membership():
    p = {"source": ["paid", "paid_or_licensed"]}
    assert gs._match_predicate(p, {"source": "paid"}, None) is True
    assert gs._match_predicate(p, {"source": "paid_or_licensed"}, None) is True
    assert gs._match_predicate(p, {"source": "free"}, None) is False


def test_truthy_clause():
    p = {"paid": {"truthy": True}}
    assert gs._match_predicate(p, {"paid": True}, None) is True
    assert gs._match_predicate(p, {"paid": 1}, None) is True
    assert gs._match_predicate(p, {"paid": False}, None) is False
    assert gs._match_predicate(p, {}, None) is False


def test_any_of_is_or():
    p = {"any_of": [{"source": ["paid"]}, {"paid": {"truthy": True}}]}
    assert gs._match_predicate(p, {"source": "paid"}, None) is True
    assert gs._match_predicate(p, {"paid": True}, None) is True
    assert gs._match_predicate(p, {"source": "free"}, None) is False


def test_unknown_dict_clause_fails_closed():
    # An unrecognised clause shape must NOT invent a gate.
    assert gs._match_predicate({"x": {"bogus": 1}}, {"x": 1}, None) is False


def test_all_clauses_must_hold():
    p = {"scope": "step", "dimension": "reproducibility"}
    assert gs._match_predicate(p, {"scope": "step",
                                   "dimension": "reproducibility"}, None) is True
    assert gs._match_predicate(p, {"scope": "step",
                                   "dimension": "power"}, None) is False


# --- synthesis-force path clause (needs root) ------------------------------

def test_path_clause_fires_only_on_existing_synthesis_overwrite(tmp_path):
    (tmp_path / "synthesis").mkdir()
    (tmp_path / "synthesis" / "paper.typ").write_text("x")
    clause = {"synthesis_force": {"path_prefix": "synthesis/",
                                  "exists": True, "when_arg": "force"}}
    # existing + force → gate
    assert gs._match_predicate(
        clause, {"filepath": "synthesis/paper.typ", "force": True}, tmp_path
    ) is True
    # non-existent + force → no gate (nothing to clobber)
    assert gs._match_predicate(
        clause, {"filepath": "synthesis/new.typ", "force": True}, tmp_path
    ) is False
    # existing but no force → no gate
    assert gs._match_predicate(
        clause, {"filepath": "synthesis/paper.typ", "force": False}, tmp_path
    ) is False
    # outside synthesis/ → no gate
    assert gs._match_predicate(
        clause, {"filepath": "workspace/x.md", "force": True}, tmp_path
    ) is False


# --- loader reads the bundle, fails safe -----------------------------------

def test_loader_reads_from_bundle():
    """P1: _load_gate_meta serves gates from _protocols.bundle."""
    gates = gs._load_gate_meta()
    assert isinstance(gates, list) and gates, "bundle should declare gates"
    assert all({"key", "tool", "floor", "when"} <= set(g) for g in gates)


def test_loader_fails_safe_when_registry_broken(monkeypatch):
    """A broken ProtocolRegistry.get_gates() degrades to [] (never raises)."""
    from research_os.tools.actions import protocol as proto

    monkeypatch.setattr(
        proto.ProtocolRegistry, "get_gates",
        classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("boom"))),
    )
    assert gs._load_gate_meta() == []


def test_loader_drops_malformed_gates(monkeypatch):
    """Malformed gate entries from the registry are dropped, not surfaced."""
    from research_os.tools.actions import protocol as proto

    bad = [
        {"key": "ok", "tool": "t", "floor": "light", "when": {}},
        {"key": "", "tool": "t", "floor": "light", "when": {}},   # bad key
        {"key": "k2", "tool": "t", "floor": "nope", "when": {}},  # bad floor
        {"key": "k3", "tool": "t", "floor": "light", "when": []},  # bad when
    ]
    monkeypatch.setattr(
        proto.ProtocolRegistry, "get_gates", classmethod(lambda cls: bad)
    )
    gates = gs._load_gate_meta()
    assert [g["key"] for g in gates] == ["ok"]


# --- resolve_declared_gate -------------------------------------------------

def _gates():
    return [
        {"key": "tool_package_install", "tool": "tool_package_install",
         "floor": "light", "when": {}, "reason": "", "source_protocol": "x"},
        {"key": "tool_audit:reproducibility", "tool": "tool_audit",
         "floor": "normal",
         "when": {"scope": "step", "dimension": "reproducibility"},
         "reason": "", "source_protocol": "x"},
    ]


def test_resolve_returns_matching_gate():
    g = gs.resolve_declared_gate("tool_package_install", {}, None, gates=_gates())
    assert g is not None and g["floor"] == "light"
    g2 = gs.resolve_declared_gate(
        "tool_audit", {"scope": "step", "dimension": "reproducibility"},
        None, gates=_gates(),
    )
    assert g2 is not None and g2["key"] == "tool_audit:reproducibility"


def test_resolve_returns_none_on_no_match():
    assert gs.resolve_declared_gate(
        "tool_audit", {"scope": "step", "dimension": "power"},
        None, gates=_gates(),
    ) is None
    assert gs.resolve_declared_gate("unknown_tool", {}, None, gates=_gates()) is None


def test_declared_floor_map():
    fm = gs.declared_floor_map(_gates())
    assert fm == {"tool_package_install": "light",
                  "tool_audit:reproducibility": "normal"}


# --- the shipped sidecar reproduces the engine floor exactly ---------------

def test_shipped_sidecar_matches_engine_floor():
    """The committed _gate_meta.json must agree with autopilot_gate's floor.

    This is the drift guard in test form: the compiled declaration and the
    engine's resolved floor map are the same set with the same floors.
    """
    from research_os.server import autopilot_gate as ag

    declared = gs.declared_floor_map()
    engine = ag._GATE_FLOOR_resolved()
    assert declared, "shipped _gate_meta.json should declare gates"
    assert declared == engine


@pytest.mark.parametrize("tool,args,expect_key", [
    ("tool_package_install", {}, "tool_package_install"),
    ("tool_search", {"source": "paid"}, "search_paid_sources"),
    ("tool_search", {"paid": True}, "search_paid_sources"),
    ("tool_search", {"source": "free"}, None),
    ("tool_typst_compile", {}, "tool_typst_compile"),
    ("tool_audit", {"scope": "step", "dimension": "reproducibility"},
     "tool_audit:reproducibility"),
    ("tool_audit", {"scope": "step", "dimension": "power"}, None),
    ("tool_task", {"operation": "run"}, "tool_task:run"),
    ("tool_task", {"operation": "status"}, None),
])
def test_engine_gate_key_matches_declaration(tool, args, expect_key):
    """autopilot_gate._gate_key (now sidecar-driven) returns the declared key."""
    from research_os.server import autopilot_gate as ag

    assert ag._gate_key(tool, args) == expect_key
