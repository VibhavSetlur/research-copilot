"""Unit tests for daemon/lineage.py pure functions (§13.4).

These are the *first* direct unit tests for the lineage module — prior
coverage came only via the HTTP endpoint tests in test_daemon_server.py.

Fixture: a 2-run chain where:
  - run "aaaa1111" (producer) writes model.txt with sha H1
  - run "bbbb2222" (consumer) reads model.txt:H1 and writes result.txt

The content-addressed link is established by the shared hash H1.
"""
from __future__ import annotations

import pytest

from research_os.daemon.lineage import (
    ancestors,
    build_lineage,
    descendants,
    downstream,
    provenance,  # import directly from lineage submodule (avoids daemon/__init__ shadowing)
    topo_order,
)
from research_os.daemon.runstore import build_manifest

# Shared hashes used throughout
H1 = "sha256:" + "a" * 64  # model.txt hash (links producer -> consumer)
H2 = "sha256:" + "c" * 64  # result.txt hash
HD = "sha256:" + "d" * 64  # data.csv hash (producer's input)

PRODUCER_ID = "aaaa1111"
CONSUMER_ID = "bbbb2222"


@pytest.fixture
def producer_manifest():
    return build_manifest(
        run_id=PRODUCER_ID,
        name="buildA",
        kind="subprocess",
        status="succeeded",
        root=None,
        spec={"cmd": ["python", "train.py"]},
        provenance={"inputs": {"data.csv": HD}},
        artifacts=[{"path": "model.txt", "sha256": H1, "change": "created"}],
        submitted_at=100.0,
    )


@pytest.fixture
def consumer_manifest():
    return build_manifest(
        run_id=CONSUMER_ID,
        name="buildB",
        kind="subprocess",
        status="succeeded",
        root=None,
        spec={"cmd": ["python", "plot.py"]},
        provenance={"inputs": {"model.txt": H1}},
        artifacts=[{"path": "result.txt", "sha256": H2, "change": "created"}],
        submitted_at=200.0,
    )


@pytest.fixture
def two_run_lineage(producer_manifest, consumer_manifest):
    return build_lineage([producer_manifest, consumer_manifest])


# ── build_lineage sanity ──────────────────────────────────────────────


def test_build_lineage_counts(two_run_lineage):
    """2-run chain: 2 runs, 1 edge, 2 linked nodes."""
    counts = two_run_lineage["counts"]
    assert counts["runs"] == 2
    assert counts["edges"] == 1
    assert counts["linked"] == 2


def test_build_lineage_roots_and_leaves(two_run_lineage):
    """Producer is a root; consumer is a leaf."""
    assert two_run_lineage["roots"] == [PRODUCER_ID]
    assert two_run_lineage["leaves"] == [CONSUMER_ID]
    assert two_run_lineage["orphans"] == []


def test_build_lineage_edge_direction(two_run_lineage):
    """Edge goes FROM producer TO consumer via model.txt."""
    edges = two_run_lineage["edges"]
    assert len(edges) == 1
    e = edges[0]
    assert e["from"] == PRODUCER_ID
    assert e["to"] == CONSUMER_ID
    via = e["via"]
    assert len(via) == 1
    assert via[0]["producer_path"] == "model.txt"
    assert via[0]["consumer_path"] == "model.txt"
    assert via[0]["sha256"] == H1


# ── ancestors / descendants ───────────────────────────────────────────


def test_descendants_of_producer(two_run_lineage):
    """Descendants of the producer = [consumer]."""
    result = descendants(two_run_lineage, PRODUCER_ID)
    assert result == [CONSUMER_ID]


def test_ancestors_of_consumer(two_run_lineage):
    """Ancestors of the consumer = [producer]."""
    result = ancestors(two_run_lineage, CONSUMER_ID)
    assert result == [PRODUCER_ID]


def test_descendants_of_consumer_is_empty(two_run_lineage):
    """The consumer has no descendants (it's a leaf)."""
    assert descendants(two_run_lineage, CONSUMER_ID) == []


def test_ancestors_of_producer_is_empty(two_run_lineage):
    """The producer has no ancestors (it's a root)."""
    assert ancestors(two_run_lineage, PRODUCER_ID) == []


# ── downstream alias ──────────────────────────────────────────────────


def test_downstream_is_alias_for_descendants(two_run_lineage):
    """downstream() must return exactly the same result as descendants()."""
    assert downstream(two_run_lineage, PRODUCER_ID) == descendants(
        two_run_lineage, PRODUCER_ID
    )
    assert downstream(two_run_lineage, CONSUMER_ID) == descendants(
        two_run_lineage, CONSUMER_ID
    )


# ── provenance() ─────────────────────────────────────────────────────


def test_provenance_finds_producer(producer_manifest, consumer_manifest):
    """provenance('model.txt') returns the producer run id."""
    manifests = [producer_manifest, consumer_manifest]
    result = provenance(manifests, "model.txt")
    assert result == [PRODUCER_ID]


def test_provenance_finds_consumer_output(producer_manifest, consumer_manifest):
    """provenance('result.txt') returns the consumer (who wrote it)."""
    manifests = [producer_manifest, consumer_manifest]
    result = provenance(manifests, "result.txt")
    assert result == [CONSUMER_ID]


def test_provenance_unknown_path_returns_empty(producer_manifest, consumer_manifest):
    """An artifact path not produced by any run returns []."""
    manifests = [producer_manifest, consumer_manifest]
    assert provenance(manifests, "no_such_file.txt") == []


def test_provenance_deleted_artifact_excluded():
    """Deleted artifacts must NOT count as produced."""
    m = build_manifest(
        run_id="del-run",
        name="del",
        kind="subprocess",
        status="succeeded",
        root=None,
        artifacts=[{"path": "gone.txt", "sha256": H1, "change": "deleted"}],
    )
    assert provenance([m], "gone.txt") == []


def test_provenance_no_sha_excluded():
    """Artifacts without a sha256 must NOT count as produced."""
    m = build_manifest(
        run_id="nohash-run",
        name="nohash",
        kind="subprocess",
        status="succeeded",
        root=None,
        artifacts=[{"path": "mystery.txt", "sha256": None, "change": "created"}],
    )
    assert provenance([m], "mystery.txt") == []


def test_provenance_two_producers_returns_both_sorted():
    """When two runs produce the same artifact, both are returned sorted+deduped."""
    m1 = build_manifest(
        run_id="run-z",
        name="runZ",
        kind="subprocess",
        status="succeeded",
        root=None,
        artifacts=[{"path": "shared.txt", "sha256": H1, "change": "created"}],
    )
    m2 = build_manifest(
        run_id="run-a",
        name="runA",
        kind="subprocess",
        status="succeeded",
        root=None,
        artifacts=[{"path": "shared.txt", "sha256": H2, "change": "modified"}],
    )
    result = provenance([m1, m2], "shared.txt")
    assert result == sorted(["run-z", "run-a"])
    assert len(result) == 2  # deduped


def test_provenance_dedupes_same_run_same_path():
    """If a single run has the same path twice (edge case), it appears once."""
    m = build_manifest(
        run_id="dup-run",
        name="dup",
        kind="subprocess",
        status="succeeded",
        root=None,
        artifacts=[
            {"path": "out.txt", "sha256": H1, "change": "created"},
            {"path": "out.txt", "sha256": H2, "change": "modified"},
        ],
    )
    result = provenance([m], "out.txt")
    assert result == ["dup-run"]


# ── topo_order ────────────────────────────────────────────────────────


def test_topo_order_producer_before_consumer(two_run_lineage):
    """Topological sort must put the producer before the consumer."""
    order = topo_order(two_run_lineage)
    assert order.index(PRODUCER_ID) < order.index(CONSUMER_ID)


def test_topo_order_subset(two_run_lineage):
    """When a subset is given, only those ids are returned."""
    order = topo_order(two_run_lineage, subset={PRODUCER_ID})
    assert order == [PRODUCER_ID]


def test_topo_order_single_run():
    """A single orphan run has a well-defined (trivial) topo order."""
    m = build_manifest(
        run_id="solo",
        name="solo",
        kind="subprocess",
        status="succeeded",
        root=None,
    )
    g = build_lineage([m])
    assert topo_order(g) == ["solo"]
