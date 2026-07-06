"""Handlers — research_search sub-domain.

Carved out of handlers/research.py to stay under the 600-line ceiling.
"""
from __future__ import annotations

from .._handlers_runtime import *  # noqa: F401,F403

__all__ = [
    "_handle_tool_search",
    "_handle_tool_web_scrape",
    "_handle_tool_literature_download",
    "_handle_tool_literature_search_and_save",
    "_handle_tool_step_literature_list",
    "_handle_tool_data_sample",
    "_handle_tool_data_profile",
    "_handle_tool_data_convert",
    "_handle_tool_data",
    "_handle_tool_research_method",
    "_handle_tool_research_tool",
    "_handle_tool_external_tool_instructions",
    "_handle_tool_alternative_path_propose",
    "_handle_tool_intake_autofill",
    "_handle_tool_context_intake",
    "_handle_tool_citations_verify",
]

def _handle_tool_search(name, arguments, root):
    """Unified search dispatcher (this-release consolidation of 5 search tools).

    mode='search'     (default) — literature/web search by source/auto
    mode='scrape'               — web scrape a URL (delegates to tool_web_scrape)
    mode='literature'           — search + save to inputs/literature/

    Selects provider by:
      1. Explicit `source` arg (one of: semantic_scholar | pubmed | crossref |
         arxiv | web | auto).
      2. Legacy: if invoked under one of the deprecated per-provider names
         (tool_search_<provider>), pick that provider for back-compat.
      3. Default 'auto' — picks providers based on a quick keyword heuristic.
    """
    arguments = arguments or {}
    mode = arguments.get("mode", "search")
    if mode == "scrape":
        return _handle_tool_web_scrape(name, arguments, root)
    if mode == "literature":
        return _handle_tool_literature_search_and_save(name, arguments, root)

    q = arguments["query"]
    limit = arguments.get("limit", 5)

    provider_fn = {
        "semantic_scholar": search_semantic_scholar,
        "pubmed": search_pubmed,
        "crossref": search_crossref,
        "arxiv": search_arxiv,
        "web": search_web,
    }
    legacy_map = {
        "tool_search_semantic_scholar": "semantic_scholar",
        "tool_search_pubmed": "pubmed",
        "tool_search_crossref": "crossref",
        "tool_search_arxiv": "arxiv",
        "tool_search_web": "web",
    }

    source = arguments.get("source")
    if not source:
        source = legacy_map.get(name, "auto")

    if source == "auto":
        ql = q.lower()
        if any(t in ql for t in ("rna", "gene", "snrna", "scrna", "protein",
                                 "clinical", "disease", "neuron", "patient",
                                 "tumor", "biomarker")):
            picks = ["semantic_scholar", "pubmed"]
        elif any(t in ql for t in ("transformer", "neural", "embedding",
                                   "diffusion", "llm")):
            picks = ["semantic_scholar", "arxiv"]
        elif any(t in ql for t in ("psychometric", "survey", "qualitative",
                                   "behavioral")):
            picks = ["crossref", "semantic_scholar"]
        elif any(t in ql for t in ("climate", "geology", "ocean", "atmosphere")):
            picks = ["crossref", "arxiv"]
        else:
            picks = ["web"]
        merged: list = []
        per_source = max(1, limit // len(picks))
        for src in picks:
            try:
                _log_search(root, f"tool_search:{src}", q, 0)
                sub = provider_fn[src](q, per_source) or []
                if isinstance(sub, list):
                    for item in sub:
                        if isinstance(item, dict):
                            item.setdefault("_source", src)
                    merged.extend(sub)
                elif isinstance(sub, dict):
                    sub.setdefault("_source", src)
                    merged.append(sub)
            except Exception as e:
                merged.append({"_source": src, "_error": str(e)})
        return _text(_success({"results": merged[:limit], "sources": picks,
                               "mode": "auto"}))

    if source not in provider_fn:
        return _text(_error(
            f"Unknown search source '{source}'. Valid: "
            f"{sorted(provider_fn)} | auto"
        ))
    fn = provider_fn[source]
    _log_search(root, f"tool_search:{source}", q, 0)
    res = fn(q, limit)
    return _text(_success(res))


def _handle_tool_web_scrape(name, arguments, root):
    return _text(_success(scrape_web(arguments["url"])))


def _handle_tool_literature_download(name, arguments, root):
    res = download_literature(
        arguments["url"],
        arguments["filename"],
        root,
        step_id=arguments.get("step_id"),
        metadata=arguments.get("metadata"),
        skip_unpaywall=bool(arguments.get("skip_unpaywall", False)),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "download failed")))


def _handle_tool_literature_search_and_save(name, arguments, root):
    from research_os.tools.actions.search.literature import search_and_save

    res = search_and_save(
        arguments["query"],
        root,
        source=arguments.get("source", "semantic_scholar"),
        step_id=arguments.get("step_id"),
        limit=int(arguments.get("limit", 5)),
        download_top=int(arguments.get("download_top", 3)),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "search_and_save failed")))


def _handle_tool_step_literature_list(name, arguments, root):
    from research_os.tools.actions.search.literature import step_literature_list

    res = step_literature_list(root, step_id=arguments.get("step_id"))
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "step_literature_list failed")))


def _handle_tool_data_sample(name, arguments, root):
    from research_os.tools.actions.data import data_sample

    res = data_sample(
        arguments["filepath"],
        int(arguments.get("n_rows", 20)),
        arguments.get("strategy", "head"),
        root,
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", res.get("error", "sample failed"))))


def _handle_tool_data_profile(name, arguments, root):
    from research_os.tools.actions.data import data_profile

    res = data_profile(arguments["filepath"], root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", res.get("error", "profile failed"))))


def _handle_tool_data_convert(name, arguments, root):
    from research_os.tools.actions.data import data_convert

    res = data_convert(arguments["filepath"], arguments["output_format"], root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", res.get("error", "convert failed"))))


def _handle_tool_data(name, arguments, root):
    """Unified data dispatcher.

    Operations:
      sample  → tool_data_sample  (N-row sample by head|random|tail)
      profile → tool_data_profile (schema + dtypes + missingness + stats)
      convert → tool_data_convert (CSV/Parquet/Feather/RDS interchange)

    Every legacy ``tool_data_sample`` / ``tool_data_profile`` /
    ``tool_data_convert`` name is aliased to this entry point and has
    its operation injected via ``_ALIAS_PARAM_INJECTION`` so callers
    (researchers, scripts, protocols) using the older per-operation
    names keep working unchanged.
    """
    op = arguments.get("operation")
    if not op:
        return _text(_error(
            "tool_data requires operation='sample'|'profile'|'convert'."
        ))
    if op == "sample":
        return _handle_tool_data_sample(name, arguments, root)
    if op == "profile":
        return _handle_tool_data_profile(name, arguments, root)
    if op == "convert":
        return _handle_tool_data_convert(name, arguments, root)
    return _text(_error(
        f"tool_data: unknown operation '{op}'. "
        "Valid: sample | profile | convert."
    ))


def _handle_tool_research_method(name, arguments, root):
    from research_os.tools.actions.research.research import research_method

    res = research_method(arguments["query"], root, limit=int(arguments.get("limit", 5)))
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "research_method failed")))


def _handle_tool_research_tool(name, arguments, root):
    from research_os.tools.actions.research.research import research_tool

    res = research_tool(arguments["task"], root, language=arguments.get("language", "any"))
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "research_tool failed")))


def _handle_tool_external_tool_instructions(name, arguments, root):
    from research_os.tools.actions.research.research import external_tool_instructions

    res = external_tool_instructions(
        arguments["tool_name"],
        arguments["purpose"],
        arguments["url"],
        root,
        steps=arguments.get("steps"),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "external_tool_instructions failed")))


def _handle_tool_alternative_path_propose(name, arguments, root):
    from research_os.tools.actions.research.research import alternative_path_propose

    res = alternative_path_propose(
        arguments["task"],
        arguments["user_method"],
        root,
        data_summary=arguments.get("data_summary", ""),
        limit=int(arguments.get("limit", 5)),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "alternative_path_propose failed")))


def _handle_tool_intake_autofill(name, arguments, root):
    from research_os.tools.actions.data.intake import intake_autofill

    hyp = arguments.get("hypotheses")
    if isinstance(hyp, str):  # tolerate a single-string hypothesis
        hyp = [hyp]
    res = intake_autofill(
        root,
        overwrite=bool(arguments.get("overwrite", False)),
        question=arguments.get("question"),
        domain=arguments.get("domain"),
        hypotheses=hyp,
        context_note=arguments.get("context_note"),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "intake_autofill failed")))


def _handle_tool_context_intake(name, arguments, root):
    from research_os.tools.actions.data.context_intake import context_intake

    res = context_intake(
        root,
        source_dir=arguments.get("source_dir"),
        dry_run=bool(arguments.get("dry_run", False)),
        also_autofill=bool(arguments.get("also_autofill", False)),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "context_intake failed")))


def _handle_tool_citations_verify(name, arguments, root):
    from research_os.tools.actions.synthesis.citations import verify_all_in_workspace

    res = verify_all_in_workspace(root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "citations_verify failed")))


HANDLERS = {
    "tool_search": _handle_tool_search,
    "tool_data": _handle_tool_data,
}
