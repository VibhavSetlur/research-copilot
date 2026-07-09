"""Tests for reproduce verdict environment diffs."""

from research_os.daemon.reproduce import compare_artifacts, env_diff


def test_env_diff_added_removed_changed_and_redaction():
    diff = env_diff(
        {"A": "1", "TOKEN": "old", "REMOVED": "x", "PATH": "/a"},
        {"A": "1", "TOKEN": "new", "ADDED": "y", "PATH": "/b"},
    )
    assert diff["added"] == ["ADDED"]
    assert diff["removed"] == ["REMOVED"]
    assert diff["changed"]["PATH"] == {"expected": "/a", "actual": "/b"}
    assert diff["changed"]["TOKEN"] == {"expected": "[REDACTED]", "actual": "[REDACTED]"}


def test_compare_artifacts_includes_env_diff():
    verdict = compare_artifacts(
        [{"path": "a.txt", "sha256": "1"}],
        [{"path": "a.txt", "sha256": "2"}],
    )
    assert verdict["verdict"] == "diverged"
    assert verdict["env_diff"] == {"added": [], "removed": [], "changed": {}}
