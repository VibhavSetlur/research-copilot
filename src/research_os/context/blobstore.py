"""Content-addressable blob store for large tool outputs.

Large results are written to .os_state/blobs/<hash>.json; the tool returns
a small pointer string ``blob:<hash16>`` instead of dumping the full payload
into the LLM context.  The AI fetches the full result later via
``mem_retrieve(pointer=...)``.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

BLOBS_SUBDIR = (".os_state", "blobs")

_HASH_RE = re.compile(r"^[0-9a-f]{16}$")


def _blobs_dir(root: Path) -> Path:
    """Return (and create) <root>/.os_state/blobs/."""
    d = root.joinpath(*BLOBS_SUBDIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def put_blob(root: Path, payload: Any) -> str:
    """Serialize *payload* to canonical JSON, hash it (sha256, first 16 hex
    chars), write to ``<root>/.os_state/blobs/<hash>.json`` if not already
    present, and return the pointer string ``'blob:<hash>'``.
    """
    canonical = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    blob_path = _blobs_dir(root) / f"{digest}.json"
    if not blob_path.exists():
        blob_path.write_text(canonical, encoding="utf-8")
    return f"blob:{digest}"


def get_blob(root: Path, pointer: str) -> Any:
    """Given a pointer ``'blob:<hash>'`` (or bare ``'<hash>'``), read and
    json-decode the blob.

    Raises:
        ValueError: if the hash portion is not a valid 16-hex-char string
            (guards against path traversal).
        FileNotFoundError: if the blob file does not exist.
    """
    raw = pointer.removeprefix("blob:")
    if not _HASH_RE.fullmatch(raw):
        raise ValueError(
            f"Invalid blob hash {raw!r}. "
            "Expected exactly 16 lowercase hex characters."
        )
    blob_path = _blobs_dir(root) / f"{raw}.json"
    # FileNotFoundError propagates naturally
    return json.loads(blob_path.read_text(encoding="utf-8"))


def is_blob_pointer(pointer: str) -> bool:
    """Return ``True`` iff *pointer* starts with ``'blob:'`` followed by a
    valid 16-hex-char hash, or IS a bare 16-hex-char hash.
    """
    if pointer.startswith("blob:"):
        return bool(_HASH_RE.fullmatch(pointer[5:]))
    return bool(_HASH_RE.fullmatch(pointer))
