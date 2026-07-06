"""Unit tests for research_os.daemon.cas — content-addressed blob storage."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_os.daemon.cas import Artifact, CASStore, DEFAULT_MAX_BLOB_BYTES


# ── helpers ────────────────────────────────────────────────────────────────────

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_store(tmp_path: Path, max_blob_bytes: int = DEFAULT_MAX_BLOB_BYTES) -> CASStore:
    return CASStore(tmp_path, max_blob_bytes=max_blob_bytes)


# ── store() basic behaviour ────────────────────────────────────────────────────

class TestStore:
    def test_stores_blob_at_shard_path(self, tmp_path):
        store = _make_store(tmp_path)
        src = tmp_path / "hello.txt"
        src.write_bytes(b"hello world")
        expected_hash = _sha256(b"hello world")

        artifact = store.store(src, "run-1")

        assert artifact is not None
        assert artifact.id == expected_hash
        assert artifact.size == len(b"hello world")
        blob = Path(artifact.storage_path)
        assert blob.exists()
        assert blob.read_bytes() == b"hello world"
        # Two-level shard: blobs/<hash[:2]>/<hash>
        assert blob.parent.name == expected_hash[:2]
        assert blob.name == expected_hash

    def test_artifact_fields(self, tmp_path):
        store = _make_store(tmp_path)
        src = tmp_path / "data.bin"
        src.write_bytes(b"\x00\x01\x02")

        artifact = store.store(src, "run-42")

        assert artifact is not None
        assert artifact.run_id == "run-42"
        assert artifact.original_path == str(src.resolve())
        assert artifact.oversize is False
        # mime_type for .bin varies by platform but must be a non-empty string
        assert isinstance(artifact.mime_type, str) and artifact.mime_type

    def test_mime_type_known_extension(self, tmp_path):
        store = _make_store(tmp_path)
        src = tmp_path / "image.png"
        src.write_bytes(b"\x89PNG\r\n\x1a\n")

        artifact = store.store(src, "run-1")

        assert artifact is not None
        assert artifact.mime_type == "image/png"

    def test_mime_type_unknown_falls_back(self, tmp_path):
        store = _make_store(tmp_path)
        src = tmp_path / "weirdfile.xyz123abc"
        src.write_bytes(b"random")

        artifact = store.store(src, "run-1")

        assert artifact is not None
        assert artifact.mime_type == "application/octet-stream"

    def test_returns_none_for_missing_file(self, tmp_path):
        store = _make_store(tmp_path)
        artifact = store.store(tmp_path / "nonexistent.txt", "run-1")
        assert artifact is None

    def test_returns_none_for_directory(self, tmp_path):
        store = _make_store(tmp_path)
        subdir = tmp_path / "adir"
        subdir.mkdir()
        artifact = store.store(subdir, "run-1")
        assert artifact is None


# ── deduplication ──────────────────────────────────────────────────────────────

class TestDedup:
    def test_identical_content_stored_once(self, tmp_path):
        store = _make_store(tmp_path)
        src1 = tmp_path / "a.txt"
        src2 = tmp_path / "b.txt"
        content = b"duplicate content"
        src1.write_bytes(content)
        src2.write_bytes(content)

        art1 = store.store(src1, "run-1")
        art2 = store.store(src2, "run-2")

        assert art1 is not None
        assert art2 is not None
        # Same hash → same blob path
        assert art1.id == art2.id
        assert art1.storage_path == art2.storage_path
        # Blob exists exactly once
        blob = Path(art1.storage_path)
        assert blob.exists()

    def test_second_store_does_not_rewrite_blob(self, tmp_path):
        """The blob file mtime must not change on the second store."""
        store = _make_store(tmp_path)
        src = tmp_path / "file.txt"
        src.write_bytes(b"same bytes")

        art1 = store.store(src, "run-1")
        assert art1 is not None
        blob = Path(art1.storage_path)
        mtime_after_first = blob.stat().st_mtime

        art2 = store.store(src, "run-1")
        assert art2 is not None
        mtime_after_second = blob.stat().st_mtime

        assert mtime_after_first == mtime_after_second

    def test_both_appear_in_their_manifests(self, tmp_path):
        store = _make_store(tmp_path)
        content = b"shared"
        src1 = tmp_path / "x.dat"
        src2 = tmp_path / "y.dat"
        src1.write_bytes(content)
        src2.write_bytes(content)

        store.store(src1, "run-A")
        store.store(src2, "run-B")

        m_a = store.manifest("run-A")
        m_b = store.manifest("run-B")
        assert len(m_a) == 1
        assert len(m_b) == 1


# ── resolve() ─────────────────────────────────────────────────────────────────

class TestResolve:
    def test_resolve_points_at_stored_blob(self, tmp_path):
        store = _make_store(tmp_path)
        src = tmp_path / "target.bin"
        data = b"resolve me"
        src.write_bytes(data)

        artifact = store.store(src, "run-1")
        assert artifact is not None

        resolved = store.resolve(artifact.id)
        assert resolved == Path(artifact.storage_path)
        assert resolved.read_bytes() == data

    def test_resolve_bytes_round_trip(self, tmp_path):
        store = _make_store(tmp_path)
        original = b"\xff\xfe" + b"binary data \x00\x01\x02" * 100
        src = tmp_path / "binary.bin"
        src.write_bytes(original)

        artifact = store.store(src, "run-1")
        assert artifact is not None
        assert store.resolve(artifact.id).read_bytes() == original


# ── manifest() ────────────────────────────────────────────────────────────────

class TestManifest:
    def test_manifest_contains_stored_artifact(self, tmp_path):
        store = _make_store(tmp_path)
        src = tmp_path / "report.csv"
        src.write_bytes(b"col1,col2\n1,2\n")

        artifact = store.store(src, "run-99")
        assert artifact is not None

        m = store.manifest("run-99")
        assert len(m) == 1
        key = next(iter(m))
        entry = m[key]
        assert entry["id"] == artifact.id
        assert entry["size"] == artifact.size
        assert entry["run_id"] == "run-99"

    def test_unknown_run_id_returns_empty_dict(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.manifest("no-such-run") == {}

    def test_manifest_merge_not_clobber(self, tmp_path):
        """Two stores in the same run both appear; second doesn't erase first."""
        store = _make_store(tmp_path)
        f1 = tmp_path / "one.txt"
        f2 = tmp_path / "two.txt"
        f1.write_bytes(b"file one")
        f2.write_bytes(b"file two")

        store.store(f1, "run-X")
        store.store(f2, "run-X")

        m = store.manifest("run-X")
        assert len(m) == 2

    def test_re_store_updates_entry_not_duplicates(self, tmp_path):
        """Storing the same file twice in the same run overwrites the entry."""
        store = _make_store(tmp_path)
        src = tmp_path / "changing.txt"
        src.write_bytes(b"version 1")
        store.store(src, "run-Z")

        src.write_bytes(b"version 2")
        store.store(src, "run-Z")

        m = store.manifest("run-Z")
        assert len(m) == 1  # one key, not two

    def test_manifest_json_on_disk(self, tmp_path):
        """The manifest file must be valid JSON."""
        store = _make_store(tmp_path)
        src = tmp_path / "file.txt"
        src.write_bytes(b"data")
        store.store(src, "run-json")

        manifest_path = store.blobs_dir / "run-json.json"
        assert manifest_path.exists()
        with manifest_path.open() as fh:
            parsed = json.load(fh)
        assert isinstance(parsed, dict)
        assert len(parsed) == 1


# ── oversize files ────────────────────────────────────────────────────────────

class TestOversize:
    def test_oversize_is_recorded_not_written(self, tmp_path):
        # Set cap to 10 bytes so a tiny file triggers it.
        store = CASStore(tmp_path, max_blob_bytes=10)
        src = tmp_path / "big.bin"
        src.write_bytes(b"x" * 20)  # 20 bytes > 10-byte cap

        artifact = store.store(src, "run-big")

        assert artifact is not None
        assert artifact.oversize is True
        assert artifact.size == 20
        # The blob must NOT be written to disk.
        blob = Path(artifact.storage_path)
        assert not blob.exists()

    def test_oversize_appears_in_manifest(self, tmp_path):
        store = CASStore(tmp_path, max_blob_bytes=5)
        src = tmp_path / "large.bin"
        src.write_bytes(b"A" * 100)

        store.store(src, "run-large")

        m = store.manifest("run-large")
        assert len(m) == 1
        entry = next(iter(m.values()))
        assert entry["oversize"] is True

    def test_normal_file_below_cap_is_stored(self, tmp_path):
        store = CASStore(tmp_path, max_blob_bytes=1000)
        src = tmp_path / "small.txt"
        src.write_bytes(b"tiny")

        artifact = store.store(src, "run-ok")

        assert artifact is not None
        assert artifact.oversize is False
        assert Path(artifact.storage_path).exists()


# ── manifest key collision avoidance ──────────────────────────────────────────

class TestManifestKey:
    def test_same_basename_different_dirs_no_collision(self, tmp_path):
        """Two files named 'out.csv' in different subdirs get distinct keys."""
        store = _make_store(tmp_path)
        d1 = tmp_path / "run_a"
        d2 = tmp_path / "run_b"
        d1.mkdir()
        d2.mkdir()
        f1 = d1 / "out.csv"
        f2 = d2 / "out.csv"
        f1.write_bytes(b"aaa")
        f2.write_bytes(b"bbb")

        store.store(f1, "run-col")
        store.store(f2, "run-col")

        m = store.manifest("run-col")
        assert len(m) == 2, f"Expected 2 distinct keys, got {list(m.keys())}"

    def test_file_outside_root_uses_absolute_path_key(self, tmp_path):
        store_root = tmp_path / "project"
        store_root.mkdir()
        store = CASStore(store_root)

        # File lives outside the project root
        external = tmp_path / "external.txt"
        external.write_bytes(b"outside")

        artifact = store.store(external, "run-ext")
        assert artifact is not None

        m = store.manifest("run-ext")
        # Key should be the absolute path (str), not just the filename
        keys = list(m.keys())
        assert len(keys) == 1
        assert str(external.resolve()) == keys[0]


# ── Artifact.to_dict() ────────────────────────────────────────────────────────

class TestArtifactToDict:
    def test_to_dict_is_json_serialisable(self, tmp_path):
        store = _make_store(tmp_path)
        src = tmp_path / "test.txt"
        src.write_bytes(b"test")
        artifact = store.store(src, "run-1")
        assert artifact is not None

        d = artifact.to_dict()
        # Must round-trip through JSON without error
        assert json.dumps(d)  # no TypeError

    def test_to_dict_storage_path_is_str(self, tmp_path):
        store = _make_store(tmp_path)
        src = tmp_path / "test.txt"
        src.write_bytes(b"test")
        artifact = store.store(src, "run-1")
        assert artifact is not None

        d = artifact.to_dict()
        assert isinstance(d["storage_path"], str)

    def test_to_dict_has_all_fields(self, tmp_path):
        store = _make_store(tmp_path)
        src = tmp_path / "f.txt"
        src.write_bytes(b"x")
        artifact = store.store(src, "run-1")
        assert artifact is not None

        d = artifact.to_dict()
        for field in ("id", "size", "storage_path", "run_id", "original_path",
                      "mime_type", "oversize"):
            assert field in d, f"Missing field: {field}"


# ── DEFAULT_MAX_BLOB_BYTES ─────────────────────────────────────────────────────

def test_default_max_blob_bytes_is_100mb():
    assert DEFAULT_MAX_BLOB_BYTES == 100 * 1024 * 1024


def test_max_blob_bytes_param_overrides_default(tmp_path):
    cap = 50
    store = CASStore(tmp_path, max_blob_bytes=cap)
    assert store.max_blob_bytes == cap
