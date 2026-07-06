"""Content-addressed blob storage — immutable, deduplicated run artifacts.

WHY THIS EXISTS:

``artifacts.py`` *detects* which files a run created or modified by
comparing mtime+size snapshots before and after execution.  ``cas.py``
*stores* their content — one canonical copy per unique sha256 hash — so
the history is not just a list of names but a permanent, retrievable
archive.

Three protocol-level consumers make this worthwhile:

* **§5.3 freshness checks** compare a source file's current hash against
  the hash recorded in the last run's manifest.  CAS gives that comparison
  a ground truth: the manifest points at an immutable blob, so "has the
  input changed?" has a definitive yes/no answer rather than a best-guess
  mtime comparison.

* **§5.6 dataset versioning** points researchers at specific CAS blobs
  ("the training set used in run abc123 is blob 9f3e…") — reproducible at
  any future date regardless of what happened to the original path.

* **Dedup across runs** is free: identical content (same bytes → same
  sha256) occupies exactly one blob on disk no matter how many runs
  reference it.  A 500 MB checkpoint shared across 20 runs stores once.

DESIGN CONSTRAINTS (all best-effort, never blocks or fails a run):

* Blobs land at ``<root>/.os_state/blobs/<hash[:2]>/<hash>`` — a
  two-level shard keeps the directory entry count manageable even with
  tens of thousands of blobs.

* Per-run manifests live at ``<root>/.os_state/blobs/<run_id>.json``.
  They map a deterministic key (see ``_manifest_key`` below) to the
  ``Artifact`` record so callers can look up "what blob did run X store
  for file Y?" in O(1).

* **Manifest key rule**: prefer ``str(path.relative_to(root))`` for paths
  inside the project root (gives collision-free relative paths even when
  two files share a basename).  For paths outside the root, fall back to
  ``str(path)`` (absolute).  Both are deterministic and stable across
  re-stores of the same file.

* Blob writes are guarded: if the blob already exists (same hash ⇒ same
  bytes, by construction) the write is skipped entirely — content-
  addressing makes overwriting redundant.

* Files exceeding ``max_blob_bytes`` are recorded in the manifest with
  ``oversize=True`` but the blob is NOT written (don't blow up the disk).

* Manifest writes use the atomic temp+rename pattern (same as
  ``RunStore.write_manifest``) so a crash mid-write can't corrupt it.

stdlib only: ``dataclasses``, ``hashlib``, ``json``, ``mimetypes``,
``os``, ``pathlib``.  No dependency on the rest of the daemon.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import mimetypes
import os
import tempfile
from pathlib import Path

# 100 MB: blobs above this cap are recorded but not copied.
# Matches the spirit of DEFAULT_MAX_HASH_BYTES in artifacts.py.
DEFAULT_MAX_BLOB_BYTES = 100 * 1024 * 1024

BLOBS_DIRNAME = "blobs"


@dataclasses.dataclass
class Artifact:
    """A single stored blob, returned by :meth:`CASStore.store`.

    ``id`` is the raw sha256 hexdigest (no ``sha256:`` prefix) so it
    splits cleanly into ``id[:2]`` / ``id`` for the two-level shard path.
    """

    id: str             # sha256 hexdigest — the canonical blob address
    size: int           # file size in bytes
    storage_path: str   # absolute path to the blob inside the blobs dir
    run_id: str         # the run that first stored this blob
    original_path: str  # absolute path of the source file at store() time
    mime_type: str      # mimetypes.guess_type result, or application/octet-stream
    oversize: bool = False  # True → blob was NOT written (file exceeded cap)

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dict (storage_path coerced to str)."""
        d = dataclasses.asdict(self)
        d["storage_path"] = str(self.storage_path)
        return d


class CASStore:
    """Content-addressed blob storage at ``<root>/.os_state/blobs/``.

    Thread-safety note: concurrent stores of *different* files are safe
    (each blob path is unique by hash; the manifest write is atomic).
    Concurrent stores of the *same* file from two threads in the same
    process may race on the manifest merge — acceptable for the current
    single-daemon use-case; add a lock if that changes.
    """

    def __init__(
        self,
        root: str | os.PathLike,
        *,
        max_blob_bytes: int = DEFAULT_MAX_BLOB_BYTES,
    ) -> None:
        self.root = Path(root)
        self.blobs_dir = self.root / ".os_state" / BLOBS_DIRNAME
        self.max_blob_bytes = max_blob_bytes

    # ── public API ─────────────────────────────────────────────────────

    def store(self, path: str | os.PathLike, run_id: str) -> Artifact | None:
        """Hash ``path`` and store its content as a CAS blob.

        Returns an :class:`Artifact` (with ``oversize=True`` if the file
        exceeded the size cap) or ``None`` if the source file is missing
        or unreadable.  Never raises.
        """
        try:
            src = Path(path).resolve()
            if not src.is_file():
                return None

            # ── size guard ──────────────────────────────────────────────
            try:
                file_size = src.stat().st_size
            except OSError:
                return None

            mime_type, _ = mimetypes.guess_type(str(src))
            if mime_type is None:
                mime_type = "application/octet-stream"

            oversize = file_size > self.max_blob_bytes

            if oversize:
                # We still need the hash for dedup identity, but we won't
                # read the full file into memory — use a streaming digest.
                hex_hash = self._hash_stream(src)
                if hex_hash is None:
                    return None
                blob_path = self._blob_path(hex_hash)
                artifact = Artifact(
                    id=hex_hash,
                    size=file_size,
                    storage_path=str(blob_path),
                    run_id=run_id,
                    original_path=str(src),
                    mime_type=mime_type,
                    oversize=True,
                )
                self._update_manifest(run_id, src, artifact)
                return artifact

            # ── read + hash ─────────────────────────────────────────────
            try:
                data = src.read_bytes()
            except OSError:
                return None

            hex_hash = hashlib.sha256(data).hexdigest()
            blob_path = self._blob_path(hex_hash)

            # ── write once (dedup guard) ─────────────────────────────────
            if not blob_path.exists():
                blob_path.parent.mkdir(parents=True, exist_ok=True)
                # Atomic write: temp + rename so a crash never leaves a
                # partial blob that would satisfy the existence check above.
                fd, tmp = tempfile.mkstemp(dir=str(blob_path.parent), suffix=".tmp")
                try:
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(data)
                    os.replace(tmp, blob_path)
                finally:
                    if os.path.exists(tmp):
                        try:
                            os.unlink(tmp)
                        except OSError:
                            pass

            artifact = Artifact(
                id=hex_hash,
                size=len(data),
                storage_path=str(blob_path),
                run_id=run_id,
                original_path=str(src),
                mime_type=mime_type,
                oversize=False,
            )
            self._update_manifest(run_id, src, artifact)
            return artifact

        except Exception:  # noqa: BLE001 - store must never raise into a run
            return None

    def resolve(self, artifact_id: str) -> Path:
        """Return the filesystem path for a blob by its sha256 hex id.

        Does not check whether the blob exists — callers should test
        ``resolve(id).exists()`` if they need that guarantee.
        """
        return self._blob_path(artifact_id)

    def manifest(self, run_id: str) -> dict:
        """Return the stored manifest for ``run_id``, or ``{}`` if absent."""
        manifest_path = self._manifest_path(run_id)
        if not manifest_path.exists():
            return {}
        try:
            with manifest_path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    # ── internal helpers ───────────────────────────────────────────────

    def _blob_path(self, hex_hash: str) -> Path:
        """``blobs/<hash[:2]>/<hash>`` — two-level shard."""
        return self.blobs_dir / hex_hash[:2] / hex_hash

    def _manifest_path(self, run_id: str) -> Path:
        """``blobs/<run_id>.json``."""
        return self.blobs_dir / f"{run_id}.json"

    def _manifest_key(self, src: Path) -> str:
        """Deterministic, collision-resistant key for the per-run manifest.

        Prefer a path relative to the project root so two files with the
        same basename but different directories get distinct keys.  Fall
        back to the absolute path string for files outside the root.
        """
        try:
            return str(src.relative_to(self.root))
        except ValueError:
            return str(src)

    def _update_manifest(self, run_id: str, src: Path, artifact: Artifact) -> None:
        """Merge ``artifact`` into the per-run manifest (atomic write)."""
        try:
            existing = self.manifest(run_id)
            key = self._manifest_key(src)
            existing[key] = artifact.to_dict()
            self.blobs_dir.mkdir(parents=True, exist_ok=True)
            target = self._manifest_path(run_id)
            fd, tmp = tempfile.mkstemp(dir=str(self.blobs_dir), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(existing, fh, indent=2)
                os.replace(tmp, target)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
        except Exception:  # noqa: BLE001 - manifest update must never raise
            pass

    @staticmethod
    def _hash_stream(path: Path) -> str | None:
        """sha256 hexdigest via streaming read (for large files). None on error."""
        try:
            h = hashlib.sha256()
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
            return h.hexdigest()
        except OSError:
            return None
