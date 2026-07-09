"""Literature download + per-experiment-step literature management.

Two scopes:

* **Project literature** lives at ``inputs/literature/`` and is shared
  across the whole project. PDFs the researcher dropped in by hand, plus
  papers the AI downloaded that ground the overall research question, go
  here.

* **Step literature** lives at ``workspace/<step>/literature/`` and is
  attached to a specific numbered experiment. Useful when a paper is
  relevant ONLY to a specific analysis step (e.g. the canonical paper for
  the method the step uses). The AI can reference these in the step's
  conclusions.md and they bubble up into citations automatically.

Public functions
----------------
* ``download_literature(url, filename, root, step_id=None)`` — download a
  PDF to the chosen scope.
* ``search_and_save(query, source, root, step_id=None, limit=5,
  download_top=True)`` — run a literature search, optionally download the
  top-N results into the chosen scope, return the search results.
* ``step_literature_list(root, step_id=None)`` — list every PDF in a step's
  (or all steps') literature folder.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("research_os.tools.search.literature")

# Hard ceiling on a single PDF fetch so a slow/hanging file server cannot
# block the MCP server indefinitely. urllib.request.urlretrieve does not
# accept a timeout, so we stream via urlopen(..., timeout=...) instead.
_DOWNLOAD_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Unpaywall (open-access pre-check)
# ---------------------------------------------------------------------------


def _check_unpaywall(url: str) -> Dict[str, Any]:
    """Best-effort: does the DOI look open-access via Unpaywall?"""
    match = re.search(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", url, re.I)
    if not match:
        return {"is_oa": True, "reason": "No DOI in URL; assuming direct PDF link."}
    doi = match.group(1)
    try:
        req_url = f"https://api.unpaywall.org/v2/{doi}?email=research@os.local"
        data = json.loads(urllib.request.urlopen(req_url, timeout=10).read())
        is_oa = bool(data.get("is_oa"))
        return {
            "is_oa": is_oa,
            "reason": (
                "Unpaywall reports open access."
                if is_oa
                else "Unpaywall reports closed access."
            ),
        }
    except Exception as e:
        # Fail-open with a noted warning. We don't want to block downloads
        # because Unpaywall is down.
        return {"is_oa": True, "reason": f"Unpaywall check failed ({e}); proceeding."}


# ---------------------------------------------------------------------------
# PDF integrity
# ---------------------------------------------------------------------------


# A real PDF always begins with the "%PDF-" magic header (per the PDF
# spec, the first line is "%PDF-<major>.<minor>"). A renamed 403 page,
# a paywall interstitial, or an HTML error returned with a 200 status
# do NOT — they typically begin with "<!DOCTYPE", "<html", or JSON.
# Validating the magic bytes is the difference between "we have the
# paper" and "we have a file named like the paper". Some servers prefix
# a UTF-8 BOM or a few stray whitespace/newline bytes before the header,
# so we scan a small leading window rather than requiring byte-0.
_PDF_MAGIC = b"%PDF-"
_PDF_MAGIC_SCAN_BYTES = 1024


def is_valid_pdf(path: Path) -> bool:
    """Return True only if ``path`` is a real PDF (magic-byte validated).

    This is the single source of truth for "is this actually a PDF?".
    Every gate / counter that claims to count *downloaded papers* must
    route through this helper rather than counting by ``.pdf`` extension
    — a renamed HTML/403/JSON error page has a ``.pdf`` name but is not
    a paper.

    Non-PDF literature formats (.epub/.djvu/.ps) are out of scope for
    magic-byte validation here and return False; callers that genuinely
    accept those formats should check extension separately. In practice
    the download path only ever writes ``.pdf`` for fetched-from-URL
    papers, so this is the right default for the count sites.
    """
    try:
        if not path.is_file():
            return False
        with open(path, "rb") as fh:
            head = fh.read(_PDF_MAGIC_SCAN_BYTES)
    except OSError:
        return False
    if not head:
        return False
    # Fast path: header at byte 0. Tolerant path: header after at most a
    # single UTF-8 BOM and stray leading whitespace. We ANCHOR the match
    # rather than scanning a window, so an HTML/JSON page that merely
    # *contains* "%PDF-" somewhere near its start is correctly rejected.
    if head.startswith(_PDF_MAGIC):
        return True
    h = head[3:] if head.startswith(b"\xef\xbb\xbf") else head  # one UTF-8 BOM
    h = h.lstrip(b" \t\r\n\x0c")  # stray leading whitespace before header
    return h.startswith(_PDF_MAGIC)


def count_valid_pdfs(directory: Path) -> int:
    """Count only magic-validated PDFs in ``directory`` (non-recursive).

    Replacement for ``sum(1 for _ in dir.glob('*.pdf'))`` at gate sites.
    A directory full of renamed error pages now counts as zero papers,
    which is the honest answer.
    """
    if not directory.is_dir():
        return 0
    return sum(
        1
        for f in directory.glob("*.pdf")
        if f.is_file() and is_valid_pdf(f)
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(text: str, maxlen: int = 80) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", text.strip()).strip("_") or "paper"
    return s[:maxlen]


def _step_literature_dir(root: Path, step_id: str) -> Path:
    """Resolve ``workspace/<step_id>/literature/``."""
    from research_os.server.errors import RoError, did_you_mean
    workspace = root / "workspace"
    if not workspace.exists():
        raise RoError(
            what="workspace/ not found",
            why="project has not been scaffolded yet",
            next_action="run the scaffold protocol first",
        )
    candidate = workspace / step_id
    if not candidate.exists() or not candidate.is_dir():
        existing = [p.name for p in workspace.iterdir() if p.is_dir()]
        suggestions = did_you_mean(step_id, existing, n=3, cutoff=0.5)
        if not suggestions and existing:
            suggestions = existing[:3]
        suffix = (
            f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        )
        raise RoError(
            what=f"Step '{step_id}' not found under workspace/",
            why="no matching numbered step directory",
            next_action=(
                f"call sys_path(operation='list') to see valid step IDs.{suffix}"
            ),
        )
    if not re.match(r"^\d{2,3}_", step_id):
        raise ValueError(
            f"'{step_id}' is not a numbered experiment path (expected NN_<slug>)."
        )
    lit = candidate / "literature"
    lit.mkdir(parents=True, exist_ok=True)
    return lit


_SIDECAR_METADATA_FIELDS = frozenset({
    "title",
    "year",
    "authors",
    "doi",
    "url",
    "venue",
    "source",
    "downloaded_at",
    "scope",
    "step_id",
})


def _public_sidecar_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Keep citation sidecars from persisting accidental secret-bearing fields."""
    return {k: v for k, v in meta.items() if k in _SIDECAR_METADATA_FIELDS}


def _write_sidecar(pdf_path: Path, meta: dict[str, Any]) -> Path:
    """Drop a .meta.yaml alongside the PDF with citation metadata."""
    public_meta = _public_sidecar_metadata(meta)
    side = pdf_path.with_suffix(pdf_path.suffix + ".meta.yaml")
    try:
        import yaml  # type: ignore

        side.write_text(yaml.safe_dump(public_meta, sort_keys=False))
    except Exception:
        # Fall back to JSON if pyyaml unavailable.
        side = pdf_path.with_suffix(pdf_path.suffix + ".meta.json")
        side.write_text(json.dumps(public_meta, indent=2, default=str))
    return side


def _update_step_literature_index(step_lit_dir: Path) -> Path:
    """Maintain ``literature_index.yaml`` inside the step's literature folder."""
    index_path = step_lit_dir / "literature_index.yaml"
    entries: dict[str, dict[str, Any]] = {}
    for pdf in sorted(step_lit_dir.iterdir()):
        if pdf.is_file() and pdf.suffix.lower() in {".pdf", ".epub", ".djvu", ".ps"}:
            citation_key = re.sub(r"[\s-]+", "_", pdf.stem).lower()
            entry = {"citation_key": citation_key, "filename": pdf.name}
            sidecar_yaml = pdf.with_suffix(pdf.suffix + ".meta.yaml")
            sidecar_json = pdf.with_suffix(pdf.suffix + ".meta.json")
            for side in (sidecar_yaml, sidecar_json):
                if side.exists():
                    try:
                        if side.suffix == ".yaml":
                            import yaml  # type: ignore

                            sidedata = yaml.safe_load(side.read_text()) or {}
                        else:
                            sidedata = json.loads(side.read_text())
                        entry.update(
                            {
                                k: sidedata.get(k)
                                for k in ("title", "year", "authors", "doi", "url",
                                          "venue", "source")
                                if sidedata.get(k)
                            }
                        )
                    except Exception:
                        pass
                    break
            entries[pdf.name] = entry

    try:
        import yaml  # type: ignore

        body = yaml.safe_dump(
            {
                "schema_version": "1.0",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "entries": entries,
            },
            sort_keys=False,
        )
    except Exception:
        body = json.dumps({"entries": entries}, indent=2)
    index_path.write_text(body)
    return index_path


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_literature(
    url: str,
    filename: str,
    root: Path,
    *,
    step_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    skip_unpaywall: bool = False,
) -> dict[str, Any]:
    """Download a PDF into either the project or a specific experiment step.

    Parameters
    ----------
    url : str
        Direct PDF URL or DOI link.
    filename : str
        Saved filename (sanitised). Bare names only — no path separators.
    root : Path
        Project root.
    step_id : str, optional
        ``"NN_<slug>"`` to save under ``workspace/<step_id>/literature/``.
        ``None`` saves under ``inputs/literature/``.
    metadata : dict, optional
        Citation metadata to write into the sidecar (.meta.yaml). Keys the
        downstream tools look for: ``title``, ``year``, ``authors``, ``doi``,
        ``url``, ``venue``, ``source``.
    skip_unpaywall : bool
        Skip the open-access pre-check (e.g. for direct preprint links).
    """
    try:
        if "/" in filename or ".." in filename:
            return {"status": "error",
                    "message": "filename may not contain '/' or '..'"}
        # SSRF / local-file-read guard: urllib's default opener registers
        # FileHandler / FTPHandler / DataHandler, so file:// / ftp:// / data:
        # URLs would resolve and exfiltrate local files into inputs/literature/.
        # Only http(s) downloads are ever legitimate here. This also covers the
        # data-driven path (search_and_save feeds provider-supplied URLs here).
        from urllib.parse import urlparse

        scheme = (urlparse(url).scheme or "").lower()
        if scheme not in ("http", "https"):
            return {"status": "error",
                    "message": (f"refusing to download from a non-http(s) URL "
                                f"(scheme={scheme!r}); only http/https are allowed.")}
        # Force a .pdf suffix if absent (most callers omit it).
        safe_name = _slugify(Path(filename).name)
        if not safe_name.lower().endswith((".pdf", ".epub", ".djvu", ".ps")):
            safe_name += ".pdf"

        # Paywall memory pre-check. Skip download retries when the
        # URL/DOI is in workspace/.os_state/tool_failures.jsonl with
        # permanent=true OR has hit the max-retries threshold.
        try:
            from research_os.tools.actions.state.paywall_memory import (
                is_known_bad,
                record_failure,
            )
            prior = is_known_bad(root, url)
            if prior.get("known_bad"):
                return {
                    "status": "skipped",
                    "message": (
                        f"Skipped (known-bad target): "
                        f"{prior.get('reason')} "
                        f"(last attempt {prior.get('last_attempt_ts')})"
                    ),
                    "known_bad": True,
                    "reason": prior.get("reason"),
                }
        except Exception:
            record_failure = None  # type: ignore[assignment]

        if not skip_unpaywall:
            oa = _check_unpaywall(url)
            if not oa["is_oa"]:
                log_path = root / "workspace" / "logs" / "errors.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(log_path, "a") as f:
                    f.write(f"Paywall warning for {url}: {oa['reason']}\n")
                if record_failure:
                    try:
                        record_failure(
                            root,
                            tool="tool_literature_download",
                            target=url,
                            reason="paywall",
                            error_text=oa.get("reason", ""),
                            permanent=True,
                        )
                    except Exception:
                        # Best-effort logging — the cache is a
                        # convenience, not a correctness guarantee.
                        # Swallow any failure so the paywall response
                        # below still reaches the caller.
                        pass
                return {
                    "status": "error",
                    "message": f"Paywall: {oa['reason']}",
                }

        # Resolve target directory + scope.
        if step_id:
            target_dir = _step_literature_dir(root, step_id)
            scope = f"workspace/{step_id}/literature"
        else:
            target_dir = root / "inputs" / "literature"
            target_dir.mkdir(parents=True, exist_ok=True)
            scope = "inputs/literature"

        out_path = target_dir / safe_name
        # Never overwrite — rename if needed.
        if out_path.exists():
            stem = out_path.stem
            i = 1
            while (target_dir / f"{stem}_v{i}{out_path.suffix}").exists():
                i += 1
            out_path = target_dir / f"{stem}_v{i}{out_path.suffix}"

        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Research-OS/1.0"}
            )
            with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp, \
                    open(out_path, "wb") as fh:
                shutil.copyfileobj(resp, fh)
        except Exception as e:
            err_text = str(e)
            # Record the failure for paywall memory.
            if record_failure:
                reason = "download_failed"
                permanent_flag = False
                lower = err_text.lower()
                if "404" in lower or "not found" in lower:
                    reason = "permanent_404"
                    permanent_flag = True
                elif "403" in lower or "forbidden" in lower:
                    reason = "permanent_403"
                    permanent_flag = True
                try:
                    record_failure(
                        root,
                        tool="tool_literature_download",
                        target=url,
                        reason=reason,
                        error_text=err_text,
                        permanent=permanent_flag,
                    )
                except Exception:
                    # Cache write is best-effort; the actual download
                    # error below is what the caller acts on. Don't
                    # mask the real failure with a cache-write fault.
                    pass
            return {"status": "error",
                    "message": f"Download failed: {e}"}

        # PDF integrity gate. urlretrieve writes ANY bytes the server
        # returned — including a 200-OK HTML paywall page, a JSON error
        # body, or a soft-403 interstitial. If the fetched file is named
        # *.pdf but does NOT begin with the %PDF- magic header, it is not
        # a paper. Delete the fake file (so no downstream counter is
        # fooled by its extension) and record a structured failure.
        if safe_name.lower().endswith(".pdf") and not is_valid_pdf(out_path):
            # Capture a short prefix of what we actually got, to aid
            # debugging (HTML doctype, JSON error, etc.) — bounded so the
            # failure record stays small.
            sniff = ""
            try:
                with open(out_path, "rb") as fh:
                    sniff = fh.read(120).decode("utf-8", "replace").strip()
            except OSError:
                sniff = ""
            try:
                out_path.unlink()
            except OSError:
                # If we can't remove it, at least don't claim success.
                pass
            if record_failure:
                try:
                    record_failure(
                        root,
                        tool="tool_literature_download",
                        target=url,
                        reason="not_a_pdf",
                        error_text=(
                            "fetched bytes are not a PDF (no %PDF- magic "
                            f"header); leading bytes: {sniff!r}"
                        ),
                        # Not permanent: a transient interstitial / rate
                        # limit can resolve on retry. Paywall/403/404 are
                        # caught above and marked permanent there.
                        permanent=False,
                    )
                except Exception:
                    # Best-effort enrichment of the error envelope; fall
                    # through to the generic not-a-PDF error below.
                    pass
            return {
                "status": "error",
                "not_a_pdf": True,
                "message": (
                    "Downloaded file is not a valid PDF (missing %PDF- "
                    "magic header) — likely an HTML error page, paywall "
                    "interstitial, or JSON error returned with a 200 "
                    "status. The fake file was deleted; no .pdf was kept. "
                    f"Leading bytes: {sniff!r}"
                ),
            }

        # Write citation-only sidecar metadata. Metadata may originate from
        # callers, so _write_sidecar filters to public citation fields.
        meta = dict(metadata or {})
        meta.setdefault("url", url)
        meta.setdefault("downloaded_at", datetime.now(timezone.utc).isoformat())
        meta.setdefault("scope", scope)
        if step_id:
            meta.setdefault("step_id", step_id)
        sidecar = _write_sidecar(out_path, meta)

        # Refresh the per-step index (or the project index if no step).
        if step_id:
            _update_step_literature_index(target_dir)
        else:
            try:
                from research_os.project_ops import update_literature_index

                update_literature_index(root)
            except Exception:
                pass

        return {
            "status": "success",
            "filepath": str(out_path.relative_to(root)),
            "sidecar": str(sidecar.relative_to(root)),
            "scope": scope,
            "step_id": step_id,
        }
    except (FileNotFoundError, ValueError) as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.exception("download_literature failed")
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Combined search + download
# ---------------------------------------------------------------------------


def search_and_save(
    query: str,
    root: Path,
    *,
    source: str = "semantic_scholar",
    step_id: str | None = None,
    limit: int = 5,
    download_top: int = 3,
) -> dict[str, Any]:
    """Search a literature provider, then download the top-N PDF candidates
    into the chosen scope.

    Skips entries without a URL/DOI; never overwrites; preserves citation
    metadata in a sidecar so downstream tools can render real citations.
    """
    try:
        from research_os.tools.actions.search.search import (
            search_arxiv,
            search_crossref,
            search_pubmed,
            search_semantic_scholar,
        )

        provider = {
            "semantic_scholar": search_semantic_scholar,
            "crossref": search_crossref,
            "pubmed": search_pubmed,
            "arxiv": search_arxiv,
        }.get(source.lower())
        if not provider:
            return {
                "status": "error",
                "message": f"Unknown source '{source}'. "
                           f"Allowed: semantic_scholar | crossref | pubmed | arxiv",
            }

        hits = provider(query, limit=int(limit)) or []
        downloads: list[dict[str, Any]] = []
        for h in hits[: int(download_top)]:
            link = h.get("url") or h.get("doi")
            if not link:
                continue
            # Build a sensible filename: <firstAuthorLast><year>_<firstword>.pdf
            authors = h.get("authors") or []
            first = (authors[0] if authors else "anon").split()[-1].lower()
            first = re.sub(r"[^a-z]", "", first) or "anon"
            year = str(h.get("year") or "nd")
            title_words = re.findall(r"[A-Za-z]{4,}", h.get("title") or "")
            stem = (title_words[0] if title_words else "paper").lower()
            fname = f"{first}{year}_{stem}.pdf"

            meta = {
                "title": h.get("title"),
                "authors": authors,
                "year": h.get("year"),
                "doi": h.get("doi"),
                "url": h.get("url"),
                "source": source,
            }
            res = download_literature(
                link, fname, root, step_id=step_id, metadata=meta, skip_unpaywall=False
            )
            downloads.append({"query_hit": h, "download": res})

        return {
            "status": "success",
            "query": query,
            "source": source,
            "step_id": step_id,
            "hits_found": len(hits),
            "downloads_attempted": len(downloads),
            "downloads_succeeded": sum(
                1 for d in downloads if d["download"].get("status") == "success"
            ),
            "results": downloads,
        }
    except Exception as e:
        logger.exception("search_and_save failed")
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def step_literature_list(root: Path, step_id: str | None = None) -> dict[str, Any]:
    """List PDFs in a specific step (``step_id`` provided) or across all steps."""
    try:
        workspace = root / "workspace"
        if not workspace.exists():
            return {"status": "success", "by_step": {}, "total_count": 0}

        out: dict[str, list[dict[str, Any]]] = {}

        def _scan(step_dir: Path) -> list[dict[str, Any]]:
            lit = step_dir / "literature"
            if not lit.exists():
                return []
            files: list[dict[str, Any]] = []
            for f in sorted(lit.iterdir()):
                if not f.is_file():
                    continue
                if f.suffix.lower() not in {".pdf", ".epub", ".djvu", ".ps"}:
                    continue
                entry: dict[str, Any] = {
                    "filename": f.name,
                    "relative_path": str(f.relative_to(root)),
                    "size_kb": round(f.stat().st_size / 1024, 1),
                }
                sidecar_yaml = f.with_suffix(f.suffix + ".meta.yaml")
                sidecar_json = f.with_suffix(f.suffix + ".meta.json")
                for side in (sidecar_yaml, sidecar_json):
                    if side.exists():
                        try:
                            if side.suffix == ".yaml":
                                import yaml  # type: ignore

                                entry["metadata"] = yaml.safe_load(side.read_text()) or {}
                            else:
                                entry["metadata"] = json.loads(side.read_text())
                        except Exception:
                            pass
                        break
                files.append(entry)
            return files

        if step_id:
            step_dir = workspace / step_id
            if not step_dir.exists():
                return {"status": "error", "message": f"Step '{step_id}' not found."}
            out[step_id] = _scan(step_dir)
        else:
            for step_dir in sorted(workspace.iterdir()):
                if step_dir.is_dir() and re.match(r"^\d{2,3}_", step_dir.name):
                    files = _scan(step_dir)
                    if files:
                        out[step_dir.name] = files

        total = sum(len(v) for v in out.values())
        return {"status": "success", "by_step": out, "total_count": total}
    except Exception as e:
        logger.exception("step_literature_list failed")
        return {"status": "error", "message": str(e)}
