"""Semantic routing for Research OS.

Drop-in companion to ``router.py``: replaces brittle trigger-substring
matching with embedding-cosine search over protocol + tool descriptions,
with an exact-trigger BOOST so deterministic phrases still dominate.

Architecture:
- Pre-built embeddings ship in ``protocols/_embeddings.npz`` (~330 KiB).
  Built by ``scripts/build_embeddings.py`` from each protocol's
  id / name / summary / triggers / description / step names, and each
  tool's name / short / description / category.
- At runtime we embed only the user's prompt and compute cosine
  similarity against the pre-built matrix in memory. Pure numpy +
  fastembed-for-the-query.
- We then add a trigger-boost: if any of a protocol's trigger phrases
  (loaded from ``_router_index.yaml``) appears as a substring in the
  prompt, we add ``_TRIGGER_BOOST`` to its score. This gives the
  semantic path a "deterministic floor" — phrases like
  "preregister" / "write the paper" land on the intended protocol
  even when other protocols share vocabulary.
- If ``fastembed`` is not installed OR the on-disk ``_embeddings.npz``
  is missing, ``semantic_available()`` returns False and callers should
  fall back to ``router.route()`` (trigger-based). Nothing breaks.

Design choices (and why):
- Local ONNX (fastembed, BGE-small) rather than an API embedder, to
  keep Research OS's "no LLM keys" promise. ~150 MiB optional dep.
- L2-normalised vectors → cosine sim = dot product → numpy one-liner.
- Embeddings checked into the repo so the trigger-based fallback
  works without fastembed but the semantic path is INSTANT when it's
  present (no network, no rebuild on install).
- Decision thresholds + trigger-boost magnitude are empirically
  calibrated on the prompt fixture in
  ``tests/tools/test_semantic_routing.py``; keep that suite green if
  you change them.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _collapse_hyphens(text: str) -> str:
    """Treat hyphens as word separators so 'agent-based' == 'agent based'.

    Mirrors ``router.py:_collapse_hyphens`` so the trigger-boost path can't
    drift from the trigger-substring path. ``protocol_triggers`` are lowered
    when loaded but NOT hyphen-collapsed, so the per-trigger collapse here
    is required for hyphen-insensitive matching.
    """
    return re.sub(r"-+", " ", text)


# ---------------------------------------------------------------------------
# Paths + constants — keep in sync with scripts/build_embeddings.py
# ---------------------------------------------------------------------------

_PROTOCOLS_DIR = Path(__file__).resolve().parents[2] / "protocols"
_EMBEDS_NPZ = _PROTOCOLS_DIR / "_embeddings.npz"
_EMBEDS_META = _PROTOCOLS_DIR / "_embeddings_meta.json"
# Triggers + intent_class come from the compiled _protocols.bundle via
# ProtocolRegistry (P1) — the router index YAML/JSON sidecars are gone.
_EMBEDS_MODEL = "BAAI/bge-small-en-v1.5"
_EMBEDS_DIM = 384

# Trigger-boost: when a protocol's trigger substring appears in the prompt
# we add a per-protocol boost to its cosine score, sized by the LONGEST
# matched trigger. Multi-word triggers ("bias audit", "hand off to the
# team") therefore beat single-word triggers ("audit", "handoff") when
# both match — the specific match wins over the generic one.
_TRIGGER_BOOST_BASE = 0.08          # added if ANY trigger matches
_TRIGGER_BOOST_PER_CHAR = 0.006     # added per char of the longest matched trigger (cap at 0.15)
_TRIGGER_BOOST_MAX = 0.20           # ceiling for the per-protocol boost

# When top-1 scores at or above this, we are confident enough to ACCEPT
# the result even when neighbours cluster nearby (the narrow-spread
# detector is suppressed). High absolute score means we found a real
# topic even though many adjacent topics share vocabulary.
_NARROW_SPREAD_SUPPRESS_AT = 0.65

# BGE-small recommends a query-side prefix for retrieval. Documents are
# embedded without prefix (matches the build script).
_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# Empirical thresholds (BGE-small + our protocol corpus, with the query
# prefix above). Tuned against tests/tools/test_semantic_routing.py —
# keep that suite green if you change these.
_CONFIDENT_FLOOR = 0.62    # top-1 above this → high confidence
_PRIMARY_FLOOR = 0.50      # top-1 above this → eligible as primary route at all
_AMBIGUOUS_GAP = 0.025     # if top1-top2 < this → return both as candidates
_NOTHING_FLOOR = 0.45      # top-1 below this → no match, surface ask_user

# When the top-k spread is very narrow (all candidates cluster within
# this delta), nothing actually dominates — usually means the query
# was gibberish or too generic. Treat as low confidence regardless of
# the absolute top-1 score. SUPPRESSED above _NARROW_SPREAD_SUPPRESS_AT
# because high absolute cosines mean we found a real topic even when
# neighbours share vocabulary.
_NARROW_SPREAD = 0.055
_NARROW_SPREAD_K = 5

# Query-embedder lock so model load happens once even under thread races.
_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Data class for retrieval results
# ---------------------------------------------------------------------------


@dataclass
class Match:
    id: str
    score: float


# ---------------------------------------------------------------------------
# Availability + lazy loaders
# ---------------------------------------------------------------------------


def fastembed_available() -> bool:
    """Is the fastembed library importable?"""
    try:
        import fastembed  # noqa: F401
        return True
    except ImportError:
        return False


def embeddings_on_disk() -> bool:
    return _EMBEDS_NPZ.exists() and _EMBEDS_META.exists()


def semantic_available() -> bool:
    """Both deps satisfied: we can use semantic routing this process."""
    return fastembed_available() and embeddings_on_disk()


@lru_cache(maxsize=1)
def _load_embeddings_bundle() -> dict[str, Any] | None:
    """Load the on-disk npz + meta + per-protocol trigger list.

    Cached for process lifetime; call ``reset_caches()`` after rebuilding.
    """
    if not embeddings_on_disk():
        return None
    try:
        npz = np.load(_EMBEDS_NPZ, allow_pickle=True)
        meta = json.loads(_EMBEDS_META.read_text())
    except Exception as exc:  # pragma: no cover — corrupted file
        logger.warning("Failed to load embeddings bundle: %s", exc)
        return None

    protocol_ids = list(npz["protocol_ids"])
    protocol_embeds = np.asarray(npz["protocol_embeds"], dtype=np.float32)
    tool_names = list(npz["tool_names"])
    tool_embeds = np.asarray(npz["tool_embeds"], dtype=np.float32)

    if protocol_embeds.shape[1] != _EMBEDS_DIM:
        logger.warning(
            "Embedding dim mismatch (got %d, expected %d) — semantic search disabled.",
            protocol_embeds.shape[1],
            _EMBEDS_DIM,
        )
        return None

    # Load triggers + intent_class per protocol — best-effort; semantic
    # works without them. intent_class is used for the same-parent-intent
    # tiebreak so e.g. synthesis/synthesis_abstract and writing/writing_*
    # don't pretend to be ambiguous when they share the synthesize parent.
    protocol_triggers: dict[str, list[str]] = {}
    protocol_intent_class: dict[str, str] = {}
    try:
        from research_os.tools.actions.protocol import ProtocolRegistry

        routing_map = ProtocolRegistry.get_routing_map()
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to load routing map: %s", exc)
        routing_map = {}
    for pid, entry in (routing_map or {}).items():
        if not isinstance(entry, dict):
            continue
        trigs = entry.get("triggers") or []
        protocol_triggers[pid] = [t.lower() for t in trigs if isinstance(t, str)]
        ic = entry.get("intent_class")
        if isinstance(ic, str):
            protocol_intent_class[pid] = ic

    return {
        "meta": meta,
        "protocol_ids": protocol_ids,
        "protocol_embeds": protocol_embeds,
        "tool_names": tool_names,
        "tool_embeds": tool_embeds,
        "protocol_triggers": protocol_triggers,
        "protocol_intent_class": protocol_intent_class,
    }


def _get_query_model():
    """Return a cached fastembed TextEmbedding model. None if unavailable."""
    if "model" in _MODEL_CACHE:
        return _MODEL_CACHE["model"]
    with _MODEL_LOCK:
        if "model" in _MODEL_CACHE:
            return _MODEL_CACHE["model"]
        if not fastembed_available():
            return None
        from fastembed import TextEmbedding
        try:
            _MODEL_CACHE["model"] = TextEmbedding(model_name=_EMBEDS_MODEL)
        except Exception as exc:
            logger.warning("Failed to init fastembed model: %s", exc)
            return None
        return _MODEL_CACHE["model"]


# ---------------------------------------------------------------------------
# Query embedding
# ---------------------------------------------------------------------------


def embed_query(text: str) -> np.ndarray | None:
    """L2-normalised embedding of ``text``. Returns None if unavailable.

    BGE-small recommends a retrieval prefix on the QUERY (not the
    document) — we prepend it here. Documents were embedded without
    the prefix in scripts/build_embeddings.py.
    """
    model = _get_query_model()
    if model is None:
        return None
    text = (text or "").strip()
    if not text:
        return None
    try:
        prefixed = _BGE_QUERY_PREFIX + text
        vec = next(iter(model.embed([prefixed])))
    except Exception as exc:  # pragma: no cover
        logger.warning("Query embedding failed: %s", exc)
        return None
    vec = np.asarray(vec, dtype=np.float32)
    norm = np.linalg.norm(vec)
    if norm == 0:
        return None
    return vec / norm


# ---------------------------------------------------------------------------
# Search primitives
# ---------------------------------------------------------------------------


def _topk(matrix: np.ndarray, query_vec: np.ndarray, ids: list[str], k: int) -> list[Match]:
    """Cosine-similarity top-k for L2-normalised vectors (= dot product)."""
    if matrix.size == 0:
        return []
    scores = matrix @ query_vec  # (N,)
    k = min(k, scores.shape[0])
    # argpartition for speed when N >> k, then sort the k winners.
    top_idx = np.argpartition(-scores, k - 1)[:k]
    top_idx = top_idx[np.argsort(-scores[top_idx])]
    return [Match(id=ids[i], score=float(scores[i])) for i in top_idx]


def _compute_trigger_boost(query_lower: str, triggers_for_id: list[str]) -> float:
    """Return the boost magnitude for one protocol given a lowered query.

    Returns 0.0 if no trigger matches. The longest matched trigger drives
    the boost so multi-word specific triggers ("bias audit") beat
    single-word generic ones ("audit").
    """
    # Hyphen-insensitive on both sides so 'agent-based' matches the
    # 'agent based' trigger (and vice versa). Mirrors router.py.
    q = _collapse_hyphens(query_lower)
    matched_lens = [
        len(t) for t in triggers_for_id if t and _collapse_hyphens(t) in q
    ]
    if not matched_lens:
        return 0.0
    longest = max(matched_lens)
    return min(
        _TRIGGER_BOOST_BASE + _TRIGGER_BOOST_PER_CHAR * longest,
        _TRIGGER_BOOST_MAX,
    )


def _apply_trigger_boost(
    matches_full: list[Match],
    query: str,
    triggers: dict[str, list[str]],
    k: int,
    all_ids: list[str] | None = None,
    all_embeds: np.ndarray | None = None,
    qvec: np.ndarray | None = None,
) -> list[Match]:
    """Boost trigger-matched protocols; force-include them even if outside the pool.

    The semantic pool is a top-N slice of all protocols. Trigger-matched
    protocols that fall outside the pool (because their pre-boost cosine
    was low) wouldn't otherwise get their boost applied, which silently
    broke routing on the most deterministic inputs. We fix that by
    computing trigger matches over ALL protocols and force-injecting any
    triggered-but-out-of-pool matches with their cosine + boost.
    """
    if not triggers or not query:
        return matches_full[:k]
    q_lower = _collapse_hyphens(query.lower())
    in_pool_ids = {m.id for m in matches_full}
    boosted: list[Match] = []
    for m in matches_full:
        boost = _compute_trigger_boost(q_lower, triggers.get(m.id) or [])
        boosted.append(Match(id=m.id, score=m.score + boost) if boost else m)
    # Force-inject any out-of-pool triggered protocols (need their cosine
    # to add the boost on top of). Only run when we have the full index.
    if all_ids is not None and all_embeds is not None and qvec is not None:
        id_to_idx = {pid: i for i, pid in enumerate(all_ids)}
        for pid, trigs in triggers.items():
            if pid in in_pool_ids:
                continue
            boost = _compute_trigger_boost(q_lower, trigs)
            if not boost:
                continue
            idx = id_to_idx.get(pid)
            if idx is None:
                continue
            cosine = float(all_embeds[idx] @ qvec)
            boosted.append(Match(id=pid, score=cosine + boost))
    boosted.sort(key=lambda x: x.score, reverse=True)
    return boosted[:k]


def top_k_protocols(query: str, k: int = 5) -> list[Match]:
    """Top-k protocols by semantic similarity (with trigger boost). [] if unavailable."""
    bundle = _load_embeddings_bundle()
    if bundle is None:
        return []
    qvec = embed_query(query)
    if qvec is None:
        return []
    # Pull a wider pool first so trigger boost can promote results
    # outside the un-boosted top-k. The full bundle is also passed
    # so trigger-matched protocols outside the pool are force-injected.
    pool = _topk(
        bundle["protocol_embeds"],
        qvec,
        bundle["protocol_ids"],
        max(k * 3, 15),
    )
    return _apply_trigger_boost(
        pool, query, bundle.get("protocol_triggers") or {}, k,
        all_ids=bundle["protocol_ids"],
        all_embeds=bundle["protocol_embeds"],
        qvec=qvec,
    )


def top_k_tools(query: str, k: int = 5) -> list[Match]:
    """Top-k tools by semantic similarity. [] if unavailable."""
    bundle = _load_embeddings_bundle()
    if bundle is None:
        return []
    qvec = embed_query(query)
    if qvec is None:
        return []
    return _topk(bundle["tool_embeds"], qvec, bundle["tool_names"], k)


# ---------------------------------------------------------------------------
# High-level: semantic route — returns a router-shaped payload
# ---------------------------------------------------------------------------


def semantic_route(prompt: str, k: int = 5) -> dict[str, Any] | None:
    """Run a semantic route and shape the result like ``router.route``.

    Returns ``None`` if semantic routing is unavailable — the caller
    should then fall back to the trigger-based router.

    Returned shape:
        {
            "primary_protocol": <id or None>,
            "candidates":       [{"id": ..., "score": ...}, ...],
            "ask_user":         <one-line question or None>,
            "confidence":       "high" | "medium" | "low" | "none",
            "method":           "semantic",
        }

    Decision rules (empirical, see _CONFIDENT_FLOOR / _AMBIGUOUS_GAP):
        - top-1 < _NOTHING_FLOOR             → ask_user, primary=None
        - top1 - top2 < _AMBIGUOUS_GAP       → ask_user picking between top-2
        - top-1 >= _CONFIDENT_FLOOR (clear)  → primary = top-1, high
        - else                               → primary = top-1, medium
    """
    if not semantic_available():
        return None
    matches = top_k_protocols(prompt, k=k)
    if not matches:
        return None
    top = matches[0]
    cand_payload = [{"id": m.id, "score": round(m.score, 4)} for m in matches]

    # 0. Narrow-spread → no clear winner regardless of absolute scores.
    #    Happens on vague / gibberish prompts where everything embeds
    #    similarly to a noisy mid-band score. SUPPRESSED when top-1 is
    #    already high-confidence (we found a real topic; neighbours
    #    just share vocabulary).
    if (
        len(matches) >= _NARROW_SPREAD_K
        and top.score < _NARROW_SPREAD_SUPPRESS_AT
    ):
        window = matches[:_NARROW_SPREAD_K]
        spread = window[0].score - window[-1].score
        if spread < _NARROW_SPREAD:
            return {
                "primary_protocol": None,
                "candidates": cand_payload,
                "ask_user": (
                    "No protocol clearly stands out for that prompt — the top "
                    f"{_NARROW_SPREAD_K} candidates are within {_NARROW_SPREAD:.2f} "
                    "of each other. Could you rephrase or pick one of: "
                    + ", ".join(m.id for m in matches[:3]) + "?"
                ),
                "confidence": "none",
                "method": "semantic",
            }

    # 1. No good match at all
    if top.score < _NOTHING_FLOOR:
        return {
            "primary_protocol": None,
            "candidates": cand_payload,
            "ask_user": (
                "I couldn't find a protocol that clearly matches your ask. "
                "Could you rephrase or pick from these candidates: "
                + ", ".join(m.id for m in matches[:3]) + "?"
            ),
            "confidence": "none",
            "method": "semantic",
        }

    # 2. Two strong candidates within the ambiguity gap → conditional ask.
    #    Suppress the ambiguity when the contenders share their parent
    #    intent_class — choosing wrong within an intent-class is a small
    #    error the AI can recover from; choosing wrong across intent
    #    classes is the real failure mode worth asking about.
    bundle = _load_embeddings_bundle()
    intent_class_lookup = (bundle or {}).get("protocol_intent_class") or {}
    if (
        len(matches) >= 2
        and (top.score - matches[1].score) < _AMBIGUOUS_GAP
        and matches[1].score >= _PRIMARY_FLOOR
    ):
        top_intent = intent_class_lookup.get(top.id)
        runner_intent = intent_class_lookup.get(matches[1].id)
        intents_match = top_intent and top_intent == runner_intent
        if not intents_match:
            return {
                "primary_protocol": None,
                "candidates": cand_payload,
                "ask_user": (
                    f"Two protocols match similarly well — '{matches[0].id}' and "
                    f"'{matches[1].id}'. Which fits your ask?"
                ),
                "confidence": "low",
                "method": "semantic",
            }
        # else: fall through; both are in the same intent_class, top-1
        # wins and confidence is calibrated below.

    # 3. Below the primary floor — surface as a candidate but flag uncertainty
    if top.score < _PRIMARY_FLOOR:
        return {
            "primary_protocol": top.id,
            "candidates": cand_payload,
            "ask_user": (
                f"Best guess is '{top.id}' but I'm not very confident. "
                f"Is that what you meant?"
            ),
            "confidence": "low",
            "method": "semantic",
        }

    confidence = "high" if top.score >= _CONFIDENT_FLOOR else "medium"
    return {
        "primary_protocol": top.id,
        "candidates": cand_payload,
        "ask_user": None,
        "confidence": confidence,
        "method": "semantic",
    }


# ---------------------------------------------------------------------------
# Cache reset (used by tests + after rebuild)
# ---------------------------------------------------------------------------


def reset_caches() -> None:
    """Drop the in-memory bundle + model cache. Tests + post-rebuild use this."""
    _load_embeddings_bundle.cache_clear()
    _MODEL_CACHE.pop("model", None)
    try:
        from research_os.tools.actions.protocol import ProtocolRegistry

        ProtocolRegistry.reload()
    except Exception:  # noqa: BLE001
        pass
