"""Semantic (or keyword-fallback) retrieval over MemoryRecord stores.

Design constraints
------------------
* This module is a **shared library** — it MUST NOT import research_os.daemon
  or research_os.server.  Cross-layer imports go through the seam.
* Heavy dependencies (fastembed / numpy / semantic) are imported **lazily**
  inside methods so that ``import research_os.memory`` stays fast and safe.
* When fastembed is unavailable the retriever degrades transparently to
  term-overlap keyword search — callers never need to branch on availability.

Public API
----------
MemoryRetriever       – per-project (or root-less global) retriever instance
search_all_projects   – cross-project ranked search (§10.4)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from .models import MemoryRecord

if TYPE_CHECKING:
    pass  # kept for future type-only imports


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Store layouts are fixed by TODO.md §10.4:
#   project store  →  <root>/.os_state/memories/records.jsonl
#   global store   →  <research_os_home>/memory/records.jsonl
_PROJECT_STORE_PARTS = (".os_state", "memories", "records.jsonl")
_GLOBAL_STORE_PARTS = ("memory", "records.jsonl")


def _project_store_path(root: Path) -> Path:
    """Path to a project's memory JSONL store."""
    return root.joinpath(*_PROJECT_STORE_PARTS)


def _global_store_path() -> Path | None:
    """Path to the cross-project global memory JSONL store, or None."""
    try:
        from research_os.config.project import _research_os_home  # noqa: PLC0415
        return _research_os_home().joinpath(*_GLOBAL_STORE_PARTS)
    except Exception:  # noqa: BLE001
        return None


def _fastembed_available() -> bool:
    """Return True if fastembed can be imported (and the model cached)."""
    try:
        from research_os.tools.actions.semantic import fastembed_available  # noqa: PLC0415
        return fastembed_available()
    except Exception:  # noqa: BLE001
        return False


def _embed(text: str):
    """Return an L2-normalised float32 numpy array or None."""
    try:
        from research_os.tools.actions.semantic import embed_query  # noqa: PLC0415
        return embed_query(text)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Ranking helpers (shared by search() and search_all_projects())
# ---------------------------------------------------------------------------

def _rank_semantic(
    records: list[MemoryRecord],
    query: str,
    k: int,
    kind: str | None,
) -> list[tuple[float, MemoryRecord]]:
    """Score *records* against *query* using dot-product of L2-normalised vecs.

    Records whose ``embedding`` is None (e.g. entries written to the global
    store as raw JSONL without a vector) are embedded on the fly so that
    cross-project search covers *every* record, not just pre-embedded ones.
    Only records that still cannot be embedded are skipped; if that leaves
    nothing the caller falls through to ``_rank_keyword``.
    """
    import numpy as np  # noqa: PLC0415

    q_vec = _embed(query)
    if q_vec is None:
        return []

    scored: list[tuple[float, MemoryRecord]] = []
    for r in records:
        if kind and r.kind != kind:
            continue
        emb = r.embedding
        if emb is None:
            vec = _embed(r.searchable_text())
            if vec is None:
                continue
            emb = vec.tolist()
        r_vec = np.asarray(emb, dtype=np.float32)
        # Re-normalise: query vectors are unit-length, but stored embeddings
        # may come from an external tool / hand-crafted record that is not,
        # in which case a raw dot-product would not be a valid cosine score.
        norm = float(np.linalg.norm(r_vec))
        if norm > 0:
            r_vec = r_vec / norm
        score = float(np.dot(q_vec, r_vec))
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:k]


def _rank_keyword(
    records: list[MemoryRecord],
    query: str,
    k: int,
    kind: str | None,
) -> list[tuple[float, MemoryRecord]]:
    """Simple term-overlap keyword scorer — used as fallback."""
    q = (query or "").lower().strip()
    scored: list[tuple[float, MemoryRecord]] = []
    for r in records:
        if kind and r.kind != kind:
            continue
        hay = r.searchable_text().lower()
        if not q:
            scored.append((0.0, r))
            continue
        terms = [t for t in q.split() if t]
        hits = sum(1 for t in terms if t in hay)
        if hits:
            scored.append((hits / max(len(terms), 1), r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:k]


def _rank(
    records: list[MemoryRecord],
    query: str,
    k: int,
    kind: str | None,
    *,
    use_semantic: bool,
) -> list[tuple[float, MemoryRecord]]:
    """Unified ranking: semantic when possible, keyword otherwise."""
    if use_semantic:
        results = _rank_semantic(records, query, k, kind)
        if results:
            return results
        # All records lack embeddings — fall through to keyword
    return _rank_keyword(records, query, k, kind)


# ---------------------------------------------------------------------------
# MemoryRetriever
# ---------------------------------------------------------------------------

class MemoryRetriever:
    """Semantic search over MemoryRecord JSONL stores.

    Parameters
    ----------
    root:
        Project root directory.  Per-project records are stored at
        ``<root>/.os_state/memories/records.jsonl``.  Pass ``None`` to
        operate on the global home store only (root-less mode).
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root: Path | None = Path(root) if root is not None else None
        # _available is resolved lazily on first access so __init__ is fast.
        self._available: bool | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """True iff fastembed is importable and semantic search is possible."""
        if self._available is None:
            self._available = _fastembed_available()
        return self._available

    def store(self, record: MemoryRecord) -> MemoryRecord:
        """Persist *record* to the project JSONL store.

        If the embedder is available and *record* has no embedding yet,
        the embedding is computed before writing.  The (possibly updated)
        record is returned.
        """
        try:
            if self.available and record.embedding is None:
                vec = _embed(record.searchable_text())
                if vec is not None:
                    record.embedding = vec.tolist()

            path = self._store_path()
            if path is None:
                return record
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.model_dump(mode="json")) + "\n")
        except Exception:  # noqa: BLE001
            pass  # defensive — never raise from store
        return record

    def search(
        self,
        query: str,
        k: int = 5,
        kind: str | None = None,
    ) -> list[tuple[float, MemoryRecord]]:
        """Return up to *k* records most relevant to *query*.

        Uses semantic (dot-product) search when embeddings are available,
        falling back to keyword overlap otherwise.
        """
        try:
            records = self._all_records()
            return _rank(records, query, k, kind, use_semantic=self.available)
        except Exception:  # noqa: BLE001
            return []

    def get(self, record_id: str) -> MemoryRecord | None:
        """Fetch a single record by its ``id`` field, or None if not found."""
        try:
            for r in self._all_records():
                if r.id == record_id:
                    return r
        except Exception:  # noqa: BLE001
            pass
        return None

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------

    def _store_path(self) -> Path | None:
        """Return the JSONL path for the project store, or None (no root)."""
        if self.root is None:
            return None
        return _project_store_path(self.root)

    def _all_records(self) -> list[MemoryRecord]:
        """Read all records from the project store; skip corrupt lines."""
        path = self._store_path()
        if path is None or not path.exists():
            return []
        records: list[MemoryRecord] = []
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    records.append(MemoryRecord(**data))
                except Exception:  # noqa: BLE001
                    continue
        return records


# ---------------------------------------------------------------------------
# Cross-project search (§10.4)
# ---------------------------------------------------------------------------

def search_all_projects(
    query: str,
    k: int = 5,
    root: Path | None = None,
) -> list[tuple[float, MemoryRecord]]:
    """Search the global home store and optionally a project store.

    Records from both sources are merged (project record wins on id
    collision) then ranked together using the same semantic-or-keyword
    logic as :meth:`MemoryRetriever.search`.

    Parameters
    ----------
    query:
        Free-text query.
    k:
        Maximum number of results to return.
    root:
        Project root for project-local records.  Pass ``None`` to search
        only the global home store.
    """
    try:
        global_path = _global_store_path()
        global_records = _load_jsonl(global_path) if global_path else []

        project_records: list[MemoryRecord] = []
        if root is not None:
            project_records = _load_jsonl(_project_store_path(Path(root)))

        # Merge: project records win on id collision
        merged: dict[str, MemoryRecord] = {r.id: r for r in global_records}
        for r in project_records:
            merged[r.id] = r

        all_records = list(merged.values())
        use_sem = _fastembed_available()
        return _rank(all_records, query, k, None, use_semantic=use_sem)
    except Exception:  # noqa: BLE001
        return []


def _load_jsonl(path: Path) -> list[MemoryRecord]:
    """Load MemoryRecord objects from a JSONL file; skip blank/corrupt lines."""
    if not path.exists():
        return []
    records: list[MemoryRecord] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                records.append(MemoryRecord(**data))
            except Exception:  # noqa: BLE001
                continue
    return records
