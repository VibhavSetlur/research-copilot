"""Protocol-as-DAG executor (Phase 7 §13.2).

Compiles a protocol's decomposition into a dependency graph and executes
ready batches concurrently via ``asyncio.gather``.

HARD RULES:
* No LLM / model calls — ever.  Executing a step means dispatching the
  Research-OS tool named in the ``tool:`` field via
  ``research_os.server.dispatch._handle_tool_call``.
* All heavy imports are lazy (inside function bodies) following the
  established daemon pattern (see daemon/core.py:962).
* This module MUST NOT be imported by server/ or tools/ (seam direction).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Digraph ──────────────────────────────────────────────────────────────────


class _Node:
    """Internal node representation."""

    __slots__ = ("id", "data", "deps", "completed")

    def __init__(self, node_id: str, **data: Any) -> None:
        self.id: str = node_id
        self.data: dict[str, Any] = data
        self.deps: set[str] = set()      # predecessor node ids
        self.completed: bool = False


class Digraph:
    """Minimal directed-acyclic graph for protocol step scheduling.

    Supports:
    * ``add_node(id, **data)`` — register a node with arbitrary metadata.
    * ``add_edge(src, dst)`` — declare that *src* must complete before *dst*.
    * ``has_ready()`` — True if any uncompleted node has all deps satisfied.
    * ``pop_ready()`` — return sorted list of currently ready nodes (and mark
      them *in-flight* so they are not returned again); deterministic order.
    * ``mark_completed(id)`` — record a node as done; unblocks its dependents.
    * ``detect_cycle()`` — raise ``ValueError`` if the graph contains a cycle.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, _Node] = {}
        self._in_flight: set[str] = set()

    # ── construction ──────────────────────────────────────────────────

    def add_node(self, node_id: str, **data: Any) -> None:
        if node_id in self._nodes:
            return  # idempotent
        self._nodes[node_id] = _Node(node_id, **data)

    def add_edge(self, src: str, dst: str) -> None:
        """Add dependency: *dst* cannot run until *src* completes."""
        if src not in self._nodes:
            raise KeyError(f"DAG edge source {src!r} not found")
        if dst not in self._nodes:
            raise KeyError(f"DAG edge destination {dst!r} not found")
        self._nodes[dst].deps.add(src)

    # ── cycle detection ───────────────────────────────────────────────

    def detect_cycle(self) -> None:
        """Raise ``ValueError`` describing the cycle if one exists (DFS)."""
        WHITE, GREY, BLACK = 0, 1, 2
        color: dict[str, int] = {nid: WHITE for nid in self._nodes}
        path: list[str] = []

        def dfs(nid: str) -> None:
            color[nid] = GREY
            path.append(nid)
            # Build forward-edge map on the fly from deps (which are back-edges).
            # We need successors, i.e. nodes that list nid in their deps.
            for candidate, node in self._nodes.items():
                if nid in node.deps:
                    if color[candidate] == GREY:
                        cycle_start = path.index(candidate)
                        cycle = path[cycle_start:] + [candidate]
                        raise ValueError(
                            f"DAG contains a cycle: {' -> '.join(cycle)}"
                        )
                    if color[candidate] == WHITE:
                        dfs(candidate)
            path.pop()
            color[nid] = BLACK

        for nid in list(self._nodes):
            if color[nid] == WHITE:
                dfs(nid)

    # ── scheduling ────────────────────────────────────────────────────

    def _completed_ids(self) -> set[str]:
        return {nid for nid, n in self._nodes.items() if n.completed}

    def has_ready(self) -> bool:
        """Return True if there is at least one node ready to run."""
        done = self._completed_ids()
        for nid, node in self._nodes.items():
            if not node.completed and nid not in self._in_flight:
                if node.deps <= done:
                    return True
        return False

    def pop_ready(self) -> list[_Node]:
        """Return all currently ready nodes (sorted by id) and mark them
        in-flight so subsequent calls do not return them again."""
        done = self._completed_ids()
        ready = []
        for nid in sorted(self._nodes):
            node = self._nodes[nid]
            if not node.completed and nid not in self._in_flight:
                if node.deps <= done:
                    ready.append(node)
        for node in ready:
            self._in_flight.add(node.id)
        return ready

    def mark_completed(self, node_id: str) -> None:
        """Mark *node_id* as completed and remove from in-flight."""
        self._nodes[node_id].completed = True
        self._in_flight.discard(node_id)

    def node_data(self, node_id: str) -> dict[str, Any]:
        return self._nodes[node_id].data


# ── DAGExecutor ──────────────────────────────────────────────────────────────


class DAGExecutor:
    """Compile a protocol's decomposition into a DAG and execute it.

    Usage::

        executor = DAGExecutor()
        dag = executor.compile(protocol)
        results = await executor.execute(dag, root=Path("/workspace"))
    """

    # ── compile ───────────────────────────────────────────────────────

    def compile(self, protocol: Any) -> Digraph:  # protocol: Protocol
        """Build a ``Digraph`` from *protocol.decomposition*.

        Two modes:

        * **Explicit** — if a decomposition entry carries an ``id`` field
          (allowed by ``DecompositionStep``'s ``extra="allow"``), use its
          ``id`` as the node id and its ``depends_on`` list (if present) to
          build edges.  Independent steps will be scheduled in parallel.

        * **Serial fallback** (the common case today) — if entries have no
          ``id``, synthesise stable ids (``"step_0"``, ``"step_1"``, …) and
          wire each step as depending on its predecessor, preserving the
          ordered-list semantics of existing flat decompositions.
        """
        dag = Digraph()
        decomposition = protocol.decomposition  # list[DecompositionStep]

        if not decomposition:
            return dag

        # Detect whether entries carry explicit ids.
        def _step_id(step: Any, index: int) -> str | None:
            # DecompositionStep allows extra fields — id may be stored there.
            raw = step.model_dump() if hasattr(step, "model_dump") else dict(step)
            return raw.get("id")

        has_explicit_ids = any(
            _step_id(step, i) is not None for i, step in enumerate(decomposition)
        )

        if has_explicit_ids:
            self._compile_explicit(dag, decomposition)
        else:
            self._compile_serial(dag, decomposition)

        dag.detect_cycle()
        return dag

    def _step_to_dict(self, step: Any) -> dict[str, Any]:
        if hasattr(step, "model_dump"):
            return step.model_dump()
        return dict(step)

    def _compile_explicit(self, dag: Digraph, decomposition: list[Any]) -> None:
        """Build DAG from steps that carry explicit ``id`` / ``depends_on``."""
        for i, step in enumerate(decomposition):
            raw = self._step_to_dict(step)
            step_id: str = raw.get("id") or f"step_{i}"
            dag.add_node(step_id, **raw)

        for i, step in enumerate(decomposition):
            raw = self._step_to_dict(step)
            step_id = raw.get("id") or f"step_{i}"
            for dep in raw.get("depends_on") or []:
                dag.add_edge(str(dep), step_id)

    def _compile_serial(self, dag: Digraph, decomposition: list[Any]) -> None:
        """Build a linear chain when no explicit ids are present."""
        prev_id: str | None = None
        for i, step in enumerate(decomposition):
            raw = self._step_to_dict(step)
            # Synthesise a stable id from index (and tool name when available).
            tool_name = raw.get("tool") or raw.get("protocol") or raw.get("decision")
            if tool_name:
                # Sanitise: replace non-alphanumeric with underscores.
                safe = "".join(c if c.isalnum() else "_" for c in tool_name)
                step_id = f"step_{i}_{safe}"
            else:
                step_id = f"step_{i}"
            dag.add_node(step_id, **raw)
            if prev_id is not None:
                dag.add_edge(prev_id, step_id)
            prev_id = step_id

    # ── execute ───────────────────────────────────────────────────────

    async def execute(
        self,
        dag: Digraph,
        root: Any = None,
        bus: Any = None,
    ) -> dict[str, Any]:
        """Execute all steps in the DAG, running independent batches in parallel.

        Args:
            dag:  A compiled ``Digraph`` (from :meth:`compile`).
            root: The workspace ``Path`` forwarded to tool dispatch.
            bus:  Optional ``EventBus`` for publishing step events (fail-open).

        Returns:
            ``{step_id: result}`` for every step in the DAG.
        """
        results: dict[str, Any] = {}

        while dag.has_ready():
            ready = dag.pop_ready()
            coros = [self._execute_step(node, root, bus, results) for node in ready]
            batch_results = await asyncio.gather(*coros, return_exceptions=True)

            for node, result in zip(ready, batch_results):
                if isinstance(result, BaseException):
                    logger.warning(
                        "Step %r raised during execution: %s", node.id, result
                    )
                    results[node.id] = {
                        "error": str(result),
                        "step_id": node.id,
                    }
                else:
                    results[node.id] = result
                dag.mark_completed(node.id)

        return results

    async def _execute_step(
        self,
        node: _Node,
        root: Any,
        bus: Any,
        results: dict[str, Any],
    ) -> Any:
        """Execute a single step node.

        * ``tool:`` steps → dispatch via ``_handle_tool_call`` in a thread
          (so ``asyncio.gather`` actually parallelises synchronous handlers).
        * ``protocol:`` / ``decision:`` steps with no ``tool`` → return a
          structured placeholder; no LLM call is ever made.
        """
        data = node.data
        tool_name: str | None = data.get("tool")
        protocol_ref: str | None = data.get("protocol")
        decision_ref: str | None = data.get("decision")
        purpose: str | None = data.get("purpose")

        # ── publish start event (fail-open) ──────────────────────────
        if bus is not None:
            try:
                from .events import PROTOCOL_STEP_STARTED  # lazy

                bus.publish(
                    PROTOCOL_STEP_STARTED,
                    data={
                        "step_id": node.id,
                        "tool": tool_name,
                        "protocol": protocol_ref,
                        "purpose": purpose,
                    },
                    root=str(root) if root is not None else None,
                )
            except Exception:  # noqa: BLE001
                pass  # event bus failure must never block execution

        # ── tool step: dispatch the named Research-OS tool ────────────
        if tool_name:
            return await self._dispatch_tool(tool_name, data, root)

        # ── protocol step: record dependency without LLM-driving ──────
        if protocol_ref:
            return {
                "type": "protocol_ref",
                "protocol": protocol_ref,
                "purpose": purpose,
                "note": "sub-protocol dependency recorded; client drives reasoning",
            }

        # ── decision step: structured placeholder ─────────────────────
        if decision_ref:
            return {
                "type": "decision",
                "decision": decision_ref,
                "purpose": purpose,
                "note": "decision point recorded; no automated resolution",
            }

        # ── fallback: unknown step type ───────────────────────────────
        return {
            "type": "unknown",
            "step_id": node.id,
            "data": data,
            "note": "step has no tool/protocol/decision field",
        }

    async def _dispatch_tool(
        self,
        tool_name: str,
        step_data: dict[str, Any],
        root: Any,
    ) -> Any:
        """Run ``_handle_tool_call`` in a thread so gather parallelises I/O."""
        # Lazy import — daemon is allowed to import from server.
        from research_os.server.dispatch import _handle_tool_call  # noqa: PLC0415

        # Build arguments from the step data, excluding DAG-internal keys.
        _SKIP = {"tool", "protocol", "decision", "purpose", "id", "depends_on"}
        arguments: dict[str, Any] = {
            k: v for k, v in step_data.items() if k not in _SKIP and v is not None
        }

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            _handle_tool_call,
            tool_name,
            arguments,
            root,
        )
        return result
