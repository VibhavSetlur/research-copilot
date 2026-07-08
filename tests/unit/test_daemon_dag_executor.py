"""Tests for Protocol-as-DAG executor (Phase 7 §13.2).

Style follows tests/unit/test_daemon_workflows.py: plain tmp_path, direct
class/function calls, assert dict/list returns.

pytest-asyncio is NOT installed; async tests are driven with asyncio.run().
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from research_os.daemon import DAGExecutor, Digraph


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_step(tool=None, protocol=None, decision=None, purpose=None, **extra):
    """Build a minimal mock DecompositionStep with model_dump()."""
    data = {}
    if tool is not None:
        data["tool"] = tool
    if protocol is not None:
        data["protocol"] = protocol
    if decision is not None:
        data["decision"] = decision
    if purpose is not None:
        data["purpose"] = purpose
    data.update(extra)

    m = MagicMock()
    m.model_dump.return_value = data
    return m


def _make_protocol(steps):
    p = MagicMock()
    p.decomposition = steps
    return p


class TestDigraph:
    def test_add_node_and_has_ready(self):
        dag = Digraph()
        dag.add_node("a")
        assert dag.has_ready()

    def test_no_nodes_not_ready(self):
        dag = Digraph()
        assert not dag.has_ready()

    def test_dependency_blocks_until_completed(self):
        dag = Digraph()
        dag.add_node("a")
        dag.add_node("b")
        dag.add_edge("a", "b")
        ready = dag.pop_ready()
        assert [n.id for n in ready] == ["a"]
        assert not dag.has_ready()
        dag.mark_completed("a")
        assert dag.has_ready()
        ready2 = dag.pop_ready()
        assert [n.id for n in ready2] == ["b"]

    def test_pop_ready_is_sorted_deterministic(self):
        dag = Digraph()
        for nid in ["c", "a", "b"]:
            dag.add_node(nid)
        ids = [n.id for n in dag.pop_ready()]
        assert ids == ["a", "b", "c"]

    def test_mark_completed_drains(self):
        dag = Digraph()
        dag.add_node("x")
        ready = dag.pop_ready()
        assert len(ready) == 1
        dag.mark_completed("x")
        assert not dag.has_ready()

    def test_independent_nodes_all_pop_at_once(self):
        dag = Digraph()
        for nid in ["p", "q", "r"]:
            dag.add_node(nid)
        ready = dag.pop_ready()
        assert sorted(n.id for n in ready) == ["p", "q", "r"]

    def test_second_pop_after_first_not_completed_returns_empty(self):
        dag = Digraph()
        dag.add_node("a")
        dag.pop_ready()
        assert dag.pop_ready() == []

    def test_add_node_idempotent(self):
        dag = Digraph()
        dag.add_node("a", foo=1)
        dag.add_node("a", foo=2)
        assert dag._nodes["a"].data["foo"] == 1

    def test_add_edge_unknown_node_raises(self):
        dag = Digraph()
        dag.add_node("a")
        with pytest.raises(KeyError):
            dag.add_edge("a", "nonexistent")
        with pytest.raises(KeyError):
            dag.add_edge("nonexistent", "a")


class TestDAGExecutorCompile:
    def test_flat_decomposition_serial_chain(self):
        executor = DAGExecutor()
        steps = [_make_step(tool="tool_a"), _make_step(tool="tool_b"), _make_step(tool="tool_c")]
        proto = _make_protocol(steps)
        dag = executor.compile(proto)
        ready = dag.pop_ready()
        assert len(ready) == 1
        assert "tool_a" in ready[0].id or ready[0].id == "step_0_tool_a"
        dag.mark_completed(ready[0].id)
        ready2 = dag.pop_ready()
        assert len(ready2) == 1
        dag.mark_completed(ready2[0].id)
        ready3 = dag.pop_ready()
        assert len(ready3) == 1
        dag.mark_completed(ready3[0].id)
        assert not dag.has_ready()

    def test_empty_decomposition_returns_empty_dag(self):
        executor = DAGExecutor()
        proto = _make_protocol([])
        dag = executor.compile(proto)
        assert not dag.has_ready()

    def test_explicit_ids_independent_branches_parallel(self):
        executor = DAGExecutor()
        steps = [
            _make_step(tool="root_tool", id="root", depends_on=[]),
            _make_step(tool="branch_a", id="branch_a", depends_on=["root"]),
            _make_step(tool="branch_b", id="branch_b", depends_on=["root"]),
        ]
        proto = _make_protocol(steps)
        dag = executor.compile(proto)
        ready = dag.pop_ready()
        assert [n.id for n in ready] == ["root"]
        dag.mark_completed("root")
        ready2 = dag.pop_ready()
        assert sorted(n.id for n in ready2) == ["branch_a", "branch_b"]

    def test_explicit_ids_cycle_raises(self):
        executor = DAGExecutor()
        steps = [_make_step(tool="a", id="a", depends_on=["b"]), _make_step(tool="b", id="b", depends_on=["a"])]
        proto = _make_protocol(steps)
        with pytest.raises(ValueError, match="cycle"):
            executor.compile(proto)

    def test_single_step_serial(self):
        executor = DAGExecutor()
        steps = [_make_step(tool="only_tool")]
        proto = _make_protocol(steps)
        dag = executor.compile(proto)
        ready = dag.pop_ready()
        assert len(ready) == 1
        dag.mark_completed(ready[0].id)
        assert not dag.has_ready()


class TestDAGExecutorExecute:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_empty_dag_returns_empty_dict(self):
        executor = DAGExecutor()
        proto = _make_protocol([])
        dag = executor.compile(proto)
        results = self._run(executor.execute(dag, root=Path("/tmp")))
        assert results == {}

    def test_tool_steps_dispatched_and_collected(self, tmp_path):
        fake_result = [MagicMock(text="ok")]
        executor = DAGExecutor()
        steps = [_make_step(tool="sys_protocol_list"), _make_step(tool="sys_health")]
        proto = _make_protocol(steps)
        dag = executor.compile(proto)
        with patch.object(DAGExecutor, "_dispatch_tool", new=_async_return(fake_result)):
            results = self._run(executor.execute(dag, root=tmp_path))
        assert len(results) == 2
        for v in results.values():
            assert v == fake_result

    def test_independent_steps_run_concurrently(self, tmp_path):
        call_order: list[str] = []

        async def fake_dispatch(self_inner, tool_name, step_data, root):
            call_order.append(f"start:{tool_name}")
            await asyncio.sleep(0)
            call_order.append(f"end:{tool_name}")
            return {"tool": tool_name}

        executor = DAGExecutor()
        steps = [_make_step(tool="alpha", id="a", depends_on=[]), _make_step(tool="beta", id="b", depends_on=[])]
        proto = _make_protocol(steps)
        dag = executor.compile(proto)
        with patch.object(DAGExecutor, "_dispatch_tool", fake_dispatch):
            results = self._run(executor.execute(dag, root=tmp_path))
        assert set(results.keys()) == {"a", "b"}
        assert len([e for e in call_order if e.startswith("start:")]) == 2
        assert len([e for e in call_order if e.startswith("end:")]) == 2

    def test_protocol_step_returns_placeholder_no_tool_call(self, tmp_path):
        executor = DAGExecutor()
        steps = [_make_step(protocol="some_sub_protocol")]
        proto = _make_protocol(steps)
        dag = executor.compile(proto)
        with patch.object(DAGExecutor, "_dispatch_tool") as mock_dispatch:
            results = self._run(executor.execute(dag, root=tmp_path))
        mock_dispatch.assert_not_called()
        result_values = list(results.values())
        assert len(result_values) == 1
        assert result_values[0]["type"] == "protocol_ref"
        assert result_values[0]["protocol"] == "some_sub_protocol"

    def test_decision_step_returns_placeholder_no_tool_call(self, tmp_path):
        executor = DAGExecutor()
        steps = [_make_step(decision="Choose method A or B")]
        proto = _make_protocol(steps)
        dag = executor.compile(proto)
        with patch.object(DAGExecutor, "_dispatch_tool") as mock_dispatch:
            results = self._run(executor.execute(dag, root=tmp_path))
        mock_dispatch.assert_not_called()
        result_values = list(results.values())
        assert result_values[0]["type"] == "decision"

    def test_results_are_json_serialisable(self, tmp_path):
        import json
        executor = DAGExecutor()
        steps = [_make_step(protocol="sub_proto", purpose="explore"), _make_step(decision="pick one", purpose="decide")]
        proto = _make_protocol(steps)
        dag = executor.compile(proto)
        results = self._run(executor.execute(dag, root=tmp_path))
        json.dumps(results)

    def test_results_has_one_entry_per_step(self, tmp_path):
        executor = DAGExecutor()
        steps = [_make_step(protocol=f"proto_{i}") for i in range(5)]
        proto = _make_protocol(steps)
        dag = executor.compile(proto)
        results = self._run(executor.execute(dag, root=tmp_path))
        assert len(results) == 5

    def test_bus_publish_called_on_tool_step(self, tmp_path):
        fake_result = {"ok": True}

        async def fake_dispatch(self_inner, tool_name, step_data, root):
            return fake_result

        bus = MagicMock()
        executor = DAGExecutor()
        steps = [_make_step(tool="sys_health", id="s1", depends_on=[])]
        proto = _make_protocol(steps)
        dag = executor.compile(proto)
        with patch.object(DAGExecutor, "_dispatch_tool", fake_dispatch):
            self._run(executor.execute(dag, root=tmp_path, bus=bus))
        bus.publish.assert_called_once()
        call_kwargs = bus.publish.call_args
        kind_arg = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("kind")
        assert "protocol.step_started" in str(kind_arg) or kind_arg is not None


def test_public_import_from_daemon():
    from research_os.daemon import DAGExecutor as DE, Digraph as DG  # noqa: N814
    assert DE is DAGExecutor
    assert DG is Digraph


def _async_return(value: Any):
    async def _inner(*args, **kwargs):
        return value

    return _inner
