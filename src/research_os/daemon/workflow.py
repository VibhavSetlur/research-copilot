"""Backward-compatible imports for the daemon DAG executor."""

from research_os.daemon.dag_executor import DAGExecutor, Digraph

__all__ = ["DAGExecutor", "Digraph"]
