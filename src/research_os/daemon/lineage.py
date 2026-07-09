"""Run lineage graph — the provenance DAG (Phase 1.13).

ARCHITECTURE.md feature #7. Individual runs are recorded (Phase 1.7) and
comparable (1.12), but research is a *chain*: run A produces a cleaned
dataset, run B trains on it, run C plots B's output. When a result is
questioned ("where did fig3 come from?") or an input changes ("I re-ran
the cleaning step — what's now stale?"), you need the graph, not the
list.

The link is **content-addressed and exact**, requiring no manual
declaration: run B depends on run A iff one of B's recorded input hashes
equals one of A's recorded output (artifact) hashes. Because every run
already hashes its inputs (provenance.inputs) and outputs (artifacts),
the DAG falls out of data we're already capturing — no new bookkeeping,
no guessing.

Pure, stdlib-only, fully testable. The daemon method + CLI are thin
wrappers over ``build_lineage``.
"""
from __future__ import annotations

from typing import Any


def _artifact_hashes(manifest: dict) -> dict[str, str]:
    """Map output artifact path -> sha256 for a run manifest.

    Only artifacts that were created/modified carry a meaningful hash;
    deleted artifacts have no content to link on.
    """
    out: dict[str, str] = {}
    for art in manifest.get("artifacts") or []:
        sha = art.get("sha256")
        path = art.get("path")
        if sha and path and art.get("change") != "deleted":
            out[path] = sha
    return out


def _input_hashes(manifest: dict) -> dict[str, str]:
    """Map input path -> sha256 for a run manifest (from provenance)."""
    prov = manifest.get("provenance") or {}
    inputs = prov.get("inputs") or {}
    # inputs is {path: 'sha256:...'} already.
    return {p: h for p, h in inputs.items() if h}


def _run_id(manifest: dict) -> str:
    return manifest.get("id") or manifest.get("run_id") or "?"


def build_lineage(manifests: list[dict]) -> dict[str, Any]:
    """Compute the content-addressed run dependency DAG.

    Args:
        manifests: run manifests (each with ``id``, ``artifacts``,
            ``provenance.inputs``). Order-independent.

    Returns a dict:
        nodes:  [{id, name, status, started, n_inputs, n_outputs}]
        edges:  [{from, to, via}] — ``from`` produced an artifact whose
                hash matches an input of ``to``; ``via`` lists the
                (producer_path, consumer_path, sha) matches.
        roots:  ids with no incoming edge (pure sources).
        leaves: ids with no outgoing edge (terminal results).
        orphans: ids with no edges at all (unlinked runs).
    """
    # Index: sha256 -> [(run_id, output_path)] for every produced artifact.
    producers: dict[str, list[tuple[str, str]]] = {}
    for m in manifests:
        rid = _run_id(m)
        for path, sha in _artifact_hashes(m).items():
            producers.setdefault(sha, []).append((rid, path))

    nodes: list[dict] = []
    for m in manifests:
        rid = _run_id(m)
        spec = m.get("spec") or {}
        nodes.append({
            "id": rid,
            "name": m.get("name") or spec.get("cmd") or rid,
            "status": m.get("status", "?"),
            "started": m.get("started_at") or m.get("created_at"),
            "n_inputs": len(_input_hashes(m)),
            "n_outputs": len(_artifact_hashes(m)),
        })

    # Edges: for each run's inputs, find any producer of that exact hash.
    # Skip self-links (a run consuming its own output).
    edges: list[dict] = []
    edge_index: dict[tuple[str, str], list[dict]] = {}
    for m in manifests:
        consumer = _run_id(m)
        for in_path, in_sha in _input_hashes(m).items():
            for prod_id, prod_path in producers.get(in_sha, []):
                if prod_id == consumer:
                    continue
                key = (prod_id, consumer)
                match = {
                    "producer_path": prod_path,
                    "consumer_path": in_path,
                    "sha256": in_sha,
                }
                edge_index.setdefault(key, []).append(match)

    for (frm, to), matches in edge_index.items():
        edges.append({"from": frm, "to": to, "via": matches})

    all_ids = {_run_id(m) for m in manifests}
    has_incoming = {e["to"] for e in edges}
    has_outgoing = {e["from"] for e in edges}
    linked = has_incoming | has_outgoing

    return {
        "nodes": nodes,
        "edges": edges,
        "roots": sorted(all_ids - has_incoming - (all_ids - linked)),
        "leaves": sorted(all_ids - has_outgoing - (all_ids - linked)),
        "orphans": sorted(all_ids - linked),
        "counts": {
            "runs": len(all_ids),
            "edges": len(edges),
            "linked": len(linked),
        },
    }


def ancestors(lineage: dict, run_id: str) -> list[str]:
    """All runs transitively upstream of ``run_id`` (its provenance chain).

    Answers "where did this result come from?" — every run whose output
    fed, directly or indirectly, into ``run_id``.
    """
    parents: dict[str, set[str]] = {}
    for e in lineage.get("edges", []):
        parents.setdefault(e["to"], set()).add(e["from"])
    seen: set[str] = set()
    stack = list(parents.get(run_id, set()))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(parents.get(cur, set()))
    return sorted(seen)


def descendants(lineage: dict, run_id: str) -> list[str]:
    """All runs transitively downstream of ``run_id``.

    Answers "if I re-run this, what becomes stale?" — every run that
    consumed, directly or indirectly, an output of ``run_id``.
    """
    children: dict[str, set[str]] = {}
    for e in lineage.get("edges", []):
        children.setdefault(e["from"], set()).add(e["to"])
    seen: set[str] = set()
    stack = list(children.get(run_id, set()))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(children.get(cur, set()))
    return sorted(seen)


def topo_order(lineage: dict, subset: "set[str] | None" = None) -> list[str]:
    """Topologically sort runs so producers come before consumers.

    Restricted to ``subset`` when given (edges to runs outside the subset
    are ignored for ordering, but still respected as prerequisites already
    satisfied). Within a dependency tier, ids are sorted for determinism.
    A cycle (should never happen — lineage is content-addressed and
    acyclic by construction) degrades gracefully: cyclic remainder is
    appended in sorted order rather than dropped.

    This is the order a selective re-run must follow: rebuild an upstream
    result before the downstream run that consumes it.
    """
    ids = {n["id"] for n in lineage.get("nodes", [])}
    if subset is not None:
        ids = ids & subset

    # parents within the working set
    parents: dict[str, set[str]] = {i: set() for i in ids}
    children: dict[str, set[str]] = {i: set() for i in ids}
    for e in lineage.get("edges", []):
        frm, to = e["from"], e["to"]
        if frm in ids and to in ids:
            parents[to].add(frm)
            children[frm].add(to)

    # Kahn's algorithm, deterministic tie-break.
    ready = sorted(i for i in ids if not parents[i])
    out: list[str] = []
    indeg = {i: len(parents[i]) for i in ids}
    while ready:
        cur = ready.pop(0)
        out.append(cur)
        newly: list[str] = []
        for c in children[cur]:
            indeg[c] -= 1
            if indeg[c] == 0:
                newly.append(c)
        if newly:
            ready = sorted(ready + newly)

    if len(out) < len(ids):  # cycle fallback — never expected
        out.extend(sorted(ids - set(out)))
    return out


def downstream(lineage: dict, run_id: str) -> list[str]:
    """All runs transitively downstream of ``run_id``.

    §13.4 public alias for :func:`descendants` — the two names co-exist so
    callers can use whichever reads more naturally for their context.
    "Downstream" emphasises data-flow; "descendants" emphasises the DAG.
    """
    return descendants(lineage, run_id)


def provenance(
    manifests_or_lineage: "list[dict] | dict",
    artifact_path: str,
) -> list[str]:
    """Run ids that PRODUCED ``artifact_path``.

    Answers "what produced this file?" — every run whose recorded artifacts
    include a non-deleted entry with path == ``artifact_path``.

    Args:
        manifests_or_lineage: either the raw list of run manifests (preferred
            — covers artifacts not yet consumed by any downstream run) *or* the
            pre-built lineage graph dict.  When a dict is given we extract the
            node ids and re-scan the same content by walking the edges' ``via``
            producer_path entries for linked artifacts; when a list is given we
            scan each manifest's ``artifacts`` array directly (more complete,
            handles orphan producers).
        artifact_path: the path to look up (as recorded in ``artifacts[].path``
            — usually relative to the project root; no normalisation is applied).

    Returns:
        Sorted, de-duplicated list of run_ids that produced the artifact.
        Returns ``[]`` when no run produced it (including deleted artifacts,
        which carry no content and are excluded by :func:`_artifact_hashes`).
    """
    # Prefer the raw-manifest path: it finds producers even when the artifact
    # was never consumed (those wouldn't appear in any edge's via[]).
    if isinstance(manifests_or_lineage, list):
        manifests = manifests_or_lineage
        result: set[str] = set()
        for m in manifests:
            for art in m.get("artifacts") or []:
                if (
                    art.get("path") == artifact_path
                    and art.get("change") != "deleted"
                    and art.get("sha256")  # must have a hash (mirrors _artifact_hashes)
                ):
                    result.add(_run_id(m))
        return sorted(result)

    # Lineage graph branch: walk edges' via entries for linked artifacts, then
    # supplement with node ids that declare the path in their own outputs.
    # (Nodes know n_outputs but not the paths; we can only use what's in edges.)
    graph = manifests_or_lineage
    result = set()
    for e in graph.get("edges") or []:
        for via in e.get("via") or []:
            if via.get("producer_path") == artifact_path:
                result.add(e["from"])
    return sorted(result)


def lineage_to_mermaid(graph: dict) -> str:
    """Render a computed run-lineage DAG as a mermaid flowchart string.

    Pure/stdlib (no render dependency). Surfaces the content-addressed run
    provenance — "how was this output produced, from what, through which runs?"
    — as a diagram a README/conclusions/audit can embed. Nodes are runs (id +
    name + status); edges carry the matched output→input hash as a short label.
    Roots (sources) and leaves (terminal results) get distinct classes so the
    flow reads at a glance. ``graph`` is the dict from :func:`build_lineage`.
    """
    nodes = graph.get("nodes", []) or []
    edges = graph.get("edges", []) or []
    roots = set(graph.get("roots", []) or [])
    leaves = set(graph.get("leaves", []) or [])

    def _nid(rid: str) -> str:
        # mermaid-safe node id
        return "n_" + "".join(c if c.isalnum() else "_" for c in str(rid))

    def _label(text: str, limit: int = 40) -> str:
        t = str(text).replace('"', "'").replace("\n", " ").strip()
        return (t[: limit - 1] + "…") if len(t) > limit else t

    lines: list[str] = ["flowchart LR"]
    if not nodes:
        lines.append('  empty["(no tracked runs yet)"]')
        return "\n".join(lines)

    for n in nodes:
        rid = n.get("id", "?")
        name = _label(n.get("name") or rid)
        status = n.get("status", "?")
        lines.append(f'  {_nid(rid)}["{name}<br/>({status})"]')
    for e in edges:
        frm, to = e.get("from"), e.get("to")
        if not frm or not to:
            continue
        via = e.get("via") or []
        sha = (via[0].get("sha256") if via else "") or ""
        lbl = _label(sha[:12], 14)
        if lbl:
            lines.append(f"  {_nid(frm)} -- {lbl} --> {_nid(to)}")
        else:
            lines.append(f"  {_nid(frm)} --> {_nid(to)}")
    # Distinct classes for sources + terminal results.
    lines.append("  classDef root fill:#1b4332,stroke:#2d6a4f,color:#fff;")
    lines.append("  classDef leaf fill:#3a0ca3,stroke:#7209b7,color:#fff;")
    for rid in roots:
        lines.append(f"  class {_nid(rid)} root;")
    for rid in leaves:
        lines.append(f"  class {_nid(rid)} leaf;")
    return "\n".join(lines)
