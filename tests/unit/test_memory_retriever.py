"""Unit tests for the Research-OS memory subsystem.

Covers: MemoryRecord / Hypothesis / EvidenceLink models, MemoryRetriever
(store / get / search / kind-filter), keyword fallback mode, and the
cross-project search_all_projects helper.

All tests pass in BOTH semantic and keyword modes.  Tests that can only
verify semantic ranking are skipped when fastembed is unavailable.
"""

from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path

import pytest

from research_os.memory import (
    EvidenceLink,
    Hypothesis,
    MemoryRecord,
    MemoryRetriever,
    search_all_projects,
)
import research_os.memory.retriever as _retriever_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    content: str,
    *,
    kind: str = "analysis",
    summary: str = "",
    project: str = "test-project",
    tags: list[str] | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        kind=kind,  # type: ignore[arg-type]
        content=content,
        summary=summary,
        project=project,
        tags=tags or [],
    )


# ---------------------------------------------------------------------------
# 1. Model round-trip
# ---------------------------------------------------------------------------

def test_models_roundtrip() -> None:
    # EvidenceLink defaults
    ev = EvidenceLink(kind="analysis", ref="outputs/fig1.png")
    assert ev.strength == "moderate"

    # Hypothesis defaults
    hyp = Hypothesis(statement="Effect size is > 0.5 in the treated group.")
    assert hyp.status == "proposed"
    assert hyp.id  # non-empty hex
    assert len(hyp.id) == 32  # uuid4().hex is always 32 chars
    assert hyp.created_at.tzinfo is not None  # timezone-aware

    # MemoryRecord defaults + auto-id
    rec = _make_record(
        content="Bootstrap CI covers the null at α=0.05.",
        summary="bootstrap confidence interval result",
    )
    assert rec.id  # non-empty hex
    assert len(rec.id) == 32
    assert rec.timestamp.tzinfo is not None
    assert rec.timestamp.tzinfo == timezone.utc

    # Round-trip through JSON serialisation
    dumped = rec.model_dump(mode="json")
    rec2 = MemoryRecord(**dumped)
    assert rec2.id == rec.id
    assert rec2.content == rec.content
    assert rec2.summary == rec.summary
    assert rec2.kind == rec.kind
    assert rec2.project == rec.project

    # searchable_text must include both summary and content
    text = rec.searchable_text()
    assert rec.summary in text
    assert rec.content in text


# ---------------------------------------------------------------------------
# 2. Store and get
# ---------------------------------------------------------------------------

def test_store_and_get(tmp_path: Path) -> None:
    retriever = MemoryRetriever(tmp_path)
    rec = _make_record("Logistic regression outperformed SVM on held-out set.")

    returned = retriever.store(rec)
    # store() returns the (possibly augmented) record
    assert returned.id == rec.id

    # JSONL file must exist at the expected path
    jsonl = tmp_path / ".os_state" / "memories" / "records.jsonl"
    assert jsonl.exists(), "JSONL store file was not created"

    # get() by id returns a matching record
    fetched = retriever.get(rec.id)
    assert fetched is not None
    assert fetched.id == rec.id
    assert fetched.content == rec.content

    # get() for unknown id returns None
    assert retriever.get("00000000000000000000000000000000") is None


# ---------------------------------------------------------------------------
# 3. Search returns relevant result
# ---------------------------------------------------------------------------

def test_search_returns_relevant(tmp_path: Path) -> None:
    retriever = MemoryRetriever(tmp_path)

    # Three records with clearly distinct topics — keyword overlap also works
    r_forest = _make_record(
        "random forest classifier accuracy on tabular benchmark",
        summary="random forest result",
    )
    r_bayes = _make_record(
        "bayesian hierarchical model posterior samples",
        summary="bayesian posterior",
    )
    r_pca = _make_record(
        "principal component analysis variance explained",
        summary="PCA variance",
    )
    retriever.store(r_forest)
    retriever.store(r_bayes)
    retriever.store(r_pca)

    results = retriever.search("random forest", k=3)

    # Must be a list of (float, MemoryRecord) tuples
    assert isinstance(results, list)
    assert len(results) > 0
    score, top_record = results[0]
    assert isinstance(score, float)
    assert isinstance(top_record, MemoryRecord)

    # Top result must be the random-forest record
    assert top_record.id == r_forest.id, (
        f"Expected random-forest record on top, got: {top_record.content!r}"
    )


# ---------------------------------------------------------------------------
# 4. Kind filter
# ---------------------------------------------------------------------------

def test_kind_filter(tmp_path: Path) -> None:
    retriever = MemoryRetriever(tmp_path)

    r_analysis = _make_record(
        "analysis of variance showed significant treatment effect",
        kind="analysis",
    )
    r_decision = _make_record(
        "decision to proceed with logistic regression model",
        kind="decision",
    )
    retriever.store(r_analysis)
    retriever.store(r_decision)

    # Without filter: both kinds can appear
    all_results = retriever.search("analysis decision model", k=5)
    all_kinds = {r.kind for _, r in all_results}
    assert len(all_kinds) >= 1  # sanity

    # With kind='decision': only decision records
    decision_results = retriever.search("decision logistic regression", kind="decision", k=5)
    for _, r in decision_results:
        assert r.kind == "decision", f"Expected kind='decision', got {r.kind!r}"

    # With kind='analysis': only analysis records
    analysis_results = retriever.search("variance treatment effect", kind="analysis", k=5)
    for _, r in analysis_results:
        assert r.kind == "analysis", f"Expected kind='analysis', got {r.kind!r}"


# ---------------------------------------------------------------------------
# 5. Keyword fallback when fastembed unavailable
# ---------------------------------------------------------------------------

def test_keyword_fallback_when_no_embeddings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force the keyword path by making _fastembed_available() return False
    monkeypatch.setattr(_retriever_mod, "_fastembed_available", lambda: False)

    retriever = MemoryRetriever(tmp_path)
    # Force the cached _available to False too
    retriever._available = False

    assert retriever.available is False

    # Store records (without embeddings, since available=False)
    r_neural = _make_record(
        "neural network training convergence loss curve plateau",
        summary="neural network training",
    )
    r_cluster = _make_record(
        "k-means clustering silhouette score optimum",
        summary="k-means cluster quality",
    )
    retriever.store(r_neural)
    retriever.store(r_cluster)

    # Records stored without embeddings (keyword mode)
    fetched_neural = retriever.get(r_neural.id)
    assert fetched_neural is not None
    assert fetched_neural.embedding is None  # no embedding was computed

    # Keyword search should still find the right record
    results = retriever.search("neural network training", k=5)
    assert len(results) > 0
    top_id = results[0][1].id
    assert top_id == r_neural.id, (
        f"Expected neural-network record on top, got: {results[0][1].content!r}"
    )


# ---------------------------------------------------------------------------
# 6. search_all_projects merges global + project stores
# ---------------------------------------------------------------------------

def test_search_all_projects_merges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force keyword mode so records written without embeddings (directly to
    # JSONL) rank the same as those stored through the retriever.  This makes
    # the test deterministic regardless of whether fastembed is installed.
    monkeypatch.setattr(_retriever_mod, "_fastembed_available", lambda: False)

    # Set RESEARCH_OS_HOME to a temp directory so _research_os_home() is isolated
    fake_home = tmp_path / "ros_home"
    fake_home.mkdir()
    monkeypatch.setenv("RESEARCH_OS_HOME", str(fake_home))

    # Write a record directly into the global store (raw JSONL — no embedding)
    global_store = fake_home / "memory" / "records.jsonl"
    global_store.parent.mkdir(parents=True, exist_ok=True)
    global_rec = _make_record(
        "gradient boosting ensemble on global benchmark dataset",
        summary="global gradient boosting",
        project="global-project",
    )
    global_store.write_text(
        json.dumps(global_rec.model_dump(mode="json")) + "\n",
        encoding="utf-8",
    )

    # Write a project-local record via MemoryRetriever
    project_root = tmp_path / "my-project"
    project_root.mkdir()
    retriever = MemoryRetriever(project_root)
    retriever._available = False  # consistent with monkeypatch
    project_rec = _make_record(
        "random forest project-local analysis",
        summary="project local random forest",
        project="my-project",
    )
    retriever.store(project_rec)

    # search_all_projects should find the global record when we query for it
    results = search_all_projects(
        "gradient boosting global benchmark",
        k=5,
        root=project_root,
    )
    assert len(results) > 0
    all_ids = [r.id for _, r in results]
    assert global_rec.id in all_ids, (
        f"Global record not found in merged results. Found IDs: {all_ids}"
    )

    # Dedup test: write a record with the SAME id to BOTH stores but different
    # content; the project version must win (project record overwrites global).
    shared_id = "aaaa" + "0" * 28  # valid 32-char hex
    global_version = MemoryRecord(
        id=shared_id,
        kind="analysis",
        content="global version of the shared record",
        summary="global version",
        project="global-project",
    )
    project_version = MemoryRecord(
        id=shared_id,
        kind="analysis",
        content="project version of the shared record — should win",
        summary="project version wins",
        project="my-project",
    )
    # Append global version to global store
    with global_store.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(global_version.model_dump(mode="json")) + "\n")
    # Write project version via the project retriever
    retriever.store(project_version)

    results2 = search_all_projects(
        "shared record version",
        k=10,
        root=project_root,
    )
    id_to_content = {r.id: r.content for _, r in results2}
    assert shared_id in id_to_content, "Shared record not found in merged results"
    assert "project version" in id_to_content[shared_id], (
        f"Project version should win, got: {id_to_content[shared_id]!r}"
    )


# ---------------------------------------------------------------------------
# 6b. semantic cross-project search covers un-embedded global records
# ---------------------------------------------------------------------------

def test_search_all_projects_semantic_embeds_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In semantic mode, a global record stored as raw JSONL (no embedding)
    must still be found — _rank_semantic embeds it on the fly."""
    if not MemoryRetriever(tmp_path).available:
        pytest.skip("fastembed unavailable — semantic path not exercised")

    fake_home = tmp_path / "ros_home"
    fake_home.mkdir()
    monkeypatch.setenv("RESEARCH_OS_HOME", str(fake_home))

    global_store = fake_home / "memory" / "records.jsonl"
    global_store.parent.mkdir(parents=True, exist_ok=True)
    # Raw JSONL, deliberately NO embedding field populated.
    global_rec = _make_record(
        "always set a random seed for reproducible experiments",
        summary="reproducibility lesson",
        kind="lesson",
        project="other-project",
    )
    assert global_rec.embedding is None
    global_store.write_text(
        json.dumps(global_rec.model_dump(mode="json")) + "\n",
        encoding="utf-8",
    )

    project_root = tmp_path / "proj"
    project_root.mkdir()
    MemoryRetriever(project_root).store(
        _make_record("chose postgres over mysql", kind="decision")
    )

    # Query is semantically related but shares no literal terms with the
    # global record — only a real embedding match can surface it.
    results = search_all_projects("reproducibility determinism", k=5, root=project_root)
    assert any(r.id == global_rec.id for _, r in results), (
        "Semantic cross-project search failed to embed the raw global record"
    )


# ---------------------------------------------------------------------------
# 7. store() never raises even on bad root
# ---------------------------------------------------------------------------

def test_store_never_raises_on_bad_root() -> None:
    # Use a path that is guaranteed to be unwritable (inside /proc)
    retriever = MemoryRetriever(Path("/proc/nonexistent/xyz"))
    rec = _make_record("this record cannot be persisted to /proc")

    # store() must not raise — it degrades silently
    returned = retriever.store(rec)

    # The same record object (or an equivalent one) is returned
    assert returned is rec or returned.id == rec.id
