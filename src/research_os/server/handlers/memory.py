"""Handlers for the memory domain.

Provides mem_search, mem_hypothesis (CRUD), and mem_retrieve — the three
consolidated memory tools added in the v4.0 surface. The heavy lifting is
delegated to existing module functions; this module wires them into the
handler registry.
"""
from __future__ import annotations

from .._handlers_runtime import *  # noqa: F401,F403
# Reuse existing hypothesis handlers from methodology (shared logic).
from .methodology import (  # noqa: F401
    _handle_mem_hypothesis_add,
    _handle_mem_hypothesis_list,
    _handle_mem_hypothesis_update,
)

__all__ = [
    "_handle_mem_search",
    "_handle_mem_hypothesis",
    "_handle_mem_retrieve",
]


def _handle_mem_search(name, arguments, root):
    """Semantic search over recorded project memory.

    Searches across:
      - MemoryRecord store (semantic / keyword; new store)
      - state.active_hypotheses  (kind filter: 'hypothesis')
      - workspace/analysis.md    (kind filter: 'analysis')
      - workspace/methods.md     (kind filter: 'methods')
      - workspace/decisions.md   (kind filter: 'decision')

    Returns up to top_k results (semantic hits first, then ad-hoc).
    Envelope includes "semantic": bool indicating which backend ran.
    """
    try:
        query = (arguments.get("query") or "").strip().lower()
        kind = (arguments.get("kind") or "").strip().lower()
        top_k = int(arguments.get("top_k") or 10)
        results: list[dict] = []
        semantic_available = False

        # ── New MemoryRecord store (semantic / keyword) ───────────────────
        try:
            from research_os.memory import MemoryRetriever, search_all_projects  # lazy
            retriever = MemoryRetriever(root)
            semantic_available = retriever.available
            raw_query = (arguments.get("query") or "").strip()
            if arguments.get("all_projects"):
                sem_hits = search_all_projects(raw_query, k=top_k, root=root)
            else:
                sem_hits = retriever.search(raw_query, k=top_k, kind=(kind or None))
            for score, record in sem_hits:
                results.append({
                    "kind": record.kind,
                    "id": record.id,
                    "score": round(score, 4),
                    "summary": record.summary,
                    "text": record.content,
                    "source": "memory_store",
                })
        except Exception:
            pass

        # ── Hypothesis store ──────────────────────────────────────────────
        if not kind or kind == "hypothesis":
            try:
                from research_os.project_ops import load_state
                state = load_state(root)
                for h in (state.get("active_hypotheses") or []):
                    if not isinstance(h, dict):
                        continue
                    haystack = " ".join(str(v) for v in h.values()).lower()
                    if not query or query in haystack:
                        results.append({"kind": "hypothesis", **h})
            except Exception:
                pass

        # ── Flat-file stores (analysis / methods / decisions) ─────────────
        file_map = {
            "analysis": root / "workspace" / "analysis.md",
            "methods": root / "workspace" / "methods.md",
            "decision": root / "workspace" / "decisions.md",
        }
        for fkind, fpath in file_map.items():
            if kind and kind != fkind:
                continue
            if not fpath.exists():
                continue
            try:
                lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in lines:
                    if line.strip() and (not query or query in line.lower()):
                        results.append({"kind": fkind, "text": line.strip()})
            except Exception:
                pass

        # Cap + return
        results = results[:top_k]
        return _text(_success({
            "query": arguments.get("query") or "",
            "kind_filter": kind or None,
            "count": len(results),
            "results": results,
            "semantic": semantic_available,
        }))
    except Exception as e:
        return _text(_error(str(e)))


def _handle_mem_hypothesis(name, arguments, root):
    """CRUD dispatcher for hypotheses.

    operation='add'    → create a new hypothesis (delegates to _handle_mem_hypothesis_add)
    operation='list'   → list all hypotheses (delegates to _handle_mem_hypothesis_list)
    operation='update' → update status/evidence on an existing hypothesis
    operation='get'    → fetch one hypothesis by id
    """
    try:
        op = (arguments.get("operation") or "").strip().lower()
        if not op:
            return _text(_error(
                "mem_hypothesis requires operation='add'|'list'|'update'|'get'"
            ))

        if op == "add":
            return _handle_mem_hypothesis_add(name, arguments, root)

        if op == "list":
            return _handle_mem_hypothesis_list(name, arguments, root)

        if op == "update":
            return _handle_mem_hypothesis_update(name, arguments, root)

        if op == "get":
            hypothesis_id = (arguments.get("hypothesis_id") or "").strip()
            if not hypothesis_id:
                return _text(_error(
                    "mem_hypothesis(operation='get') requires hypothesis_id=..."
                ))
            try:
                from research_os.project_ops import load_state
                state = load_state(root)
                hyps = state.get("active_hypotheses") or []
                match = next(
                    (h for h in hyps
                     if isinstance(h, dict) and h.get("id") == hypothesis_id),
                    None,
                )
                if match is None:
                    return _text(_error(
                        f"No hypothesis '{hypothesis_id}'. "
                        "Call mem_hypothesis(operation='list') to see all."
                    ))
                return _text(_success({"hypothesis": match}))
            except Exception as e:
                return _text(_error(str(e)))

        return _text(_error(
            f"mem_hypothesis: unknown operation '{op}'. "
            "Valid: add | list | update | get."
        ))
    except Exception as e:
        return _text(_error(str(e)))


def _handle_mem_retrieve(name, arguments, root):
    """Pointer-architecture memory retrieval.

    If `pointer` is given, resolve it as a path/key:
      - If it looks like a hypothesis id (H\\d+), look it up in state.
      - Otherwise treat it as a relative file path inside the project root
        and return the file's content.
    If `query` is given (and no pointer), delegate to mem_search logic.
    If neither is given, return an empty success envelope.
    """
    try:
        pointer = (arguments.get("pointer") or "").strip()
        query = (arguments.get("query") or "").strip()

        if pointer:
            # ── Blob pointer (highest priority) ───────────────────────────
            from research_os.context.blobstore import is_blob_pointer, get_blob
            if is_blob_pointer(pointer):
                try:
                    data = get_blob(Path(root), pointer)
                    return _text(_success({"pointer": pointer, "kind": "blob", "data": data}))
                except (FileNotFoundError, ValueError) as e:
                    return _text(_error(f"blob pointer resolution failed: {e}"))

            import re
            # MemoryRecord id pointer — try resolving before H\d+ / file-path
            try:
                from research_os.memory import MemoryRetriever  # lazy
                rec = MemoryRetriever(root).get(pointer)
                if rec is not None:
                    return _text(_success({
                        "pointer": pointer,
                        "kind": "memory_record",
                        "record": rec.model_dump(mode="json"),
                        "content": rec.content,
                    }))
            except Exception:
                pass
            # Hypothesis id pointer (e.g. "H1", "H12")
            if re.fullmatch(r"H\d+", pointer, re.IGNORECASE):
                mapped = dict(arguments)
                mapped["hypothesis_id"] = pointer
                mapped["operation"] = "get"
                return _handle_mem_hypothesis(name, mapped, root)

            # File-path pointer — resolve inside project root
            try:
                p = Path(root) / pointer
                resolved = p.resolve()
                root_resolved = Path(root).resolve()
                resolved.relative_to(root_resolved)  # guard traversal
                if resolved.exists() and resolved.is_file():
                    content = resolved.read_text(encoding="utf-8", errors="replace")
                    return _text(_success({
                        "pointer": pointer,
                        "kind": "file",
                        "content": content,
                    }))
                return _text(_success({
                    "pointer": pointer,
                    "kind": "file",
                    "content": None,
                    "note": f"No file found at '{pointer}' inside project root.",
                }))
            except Exception as e:
                return _text(_error(f"pointer resolution failed: {e}"))

        if query:
            # Delegate to mem_search
            mapped = dict(arguments)
            mapped["query"] = query
            return _handle_mem_search(name, mapped, root)

        # No pointer, no query — return empty
        return _text(_success({
            "pointer": None,
            "query": None,
            "results": [],
            "note": "Provide pointer= or query= to retrieve memory entries.",
        }))
    except Exception as e:
        return _text(_error(str(e)))


HANDLERS = {
    "mem_search": _handle_mem_search,
    "mem_hypothesis": _handle_mem_hypothesis,
    "mem_retrieve": _handle_mem_retrieve,
}
