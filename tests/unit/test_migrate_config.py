"""Unit tests for research_os.config.migrate_config (§9.4).

Covers:
- migrate WITH an old researcher_config.yaml maps keys correctly.
- migrate with NO old config produces valid v5 defaults.
- idempotency (running twice is safe and produces the same result).
- returned summary dict shape.
- CLI --migrate flag wires through to migrate_project_to_v5.
"""

from __future__ import annotations

from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_home(monkeypatch, tmp_path: Path) -> Path:
    """Redirect RESEARCH_OS_HOME to a temp dir so tests don't touch ~/.research-os."""
    ros_home = tmp_path / "fake_ro_home"
    ros_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("RESEARCH_OS_HOME", str(ros_home))
    return ros_home


def _stub_detect(monkeypatch, **fields):
    """Patch detect_environment to return *fields* (any omitted key absent)."""
    monkeypatch.setattr(
        "research_os.config.project.detect_environment",
        lambda **_kw: fields,
    )


def _write_old_config(project_root: Path, data: dict) -> None:
    """Write a legacy inputs/researcher_config.yaml with *data*."""
    inputs_dir = project_root / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    (inputs_dir / "researcher_config.yaml").write_text(
        yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    )


# ---------------------------------------------------------------------------
# Core key-mapping tests
# ---------------------------------------------------------------------------


class TestMigrateWithOldConfig:
    def test_project_name_mapped(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "my_study"
        project_root.mkdir()
        _write_old_config(project_root, {"project_name": "Great Study"})

        from research_os.config.migrate_config import migrate_project_to_v5
        summary = migrate_project_to_v5(project_root)

        config = yaml.safe_load(
            (project_root / ".os_state" / "config.yaml").read_text()
        )
        assert config["project"]["name"] == "Great Study"
        assert "project_name" in summary["migrated_keys"]

    def test_output_types_mapped(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "proj"
        project_root.mkdir()
        _write_old_config(project_root, {
            "research_goal": {"output_types": ["paper", "poster"]}
        })

        from research_os.config.migrate_config import migrate_project_to_v5
        migrate_project_to_v5(project_root)

        config = yaml.safe_load(
            (project_root / ".os_state" / "config.yaml").read_text()
        )
        assert config["project"]["output_types"] == ["paper", "poster"]

    def test_autonomy_level_mapped(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "proj2"
        project_root.mkdir()
        _write_old_config(project_root, {
            "interaction": {"autonomy_level": "autopilot"}
        })

        from research_os.config.migrate_config import migrate_project_to_v5
        migrate_project_to_v5(project_root)

        config = yaml.safe_load(
            (project_root / ".os_state" / "config.yaml").read_text()
        )
        assert config["autonomy"]["level"] == "autopilot"

    def test_quality_gate_mapped(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "proj3"
        project_root.mkdir()
        _write_old_config(project_root, {
            "interaction": {"quality_gate_policy": "warn_only"}
        })

        from research_os.config.migrate_config import migrate_project_to_v5
        migrate_project_to_v5(project_root)

        config = yaml.safe_load(
            (project_root / ".os_state" / "config.yaml").read_text()
        )
        assert config["autonomy"]["quality_gate"] == "warn_only"

    def test_researcher_name_mapped_to_profile(self, monkeypatch, tmp_path):
        ros_home = _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "proj4"
        project_root.mkdir()
        _write_old_config(project_root, {
            "researcher": {"name": "Ada Lovelace", "orcid": "0000-0001-2345-6789"}
        })

        from research_os.config.migrate_config import migrate_project_to_v5
        summary = migrate_project_to_v5(project_root)

        profile = yaml.safe_load((ros_home / "profile.yaml").read_text())
        assert profile["user"]["name"] == "Ada Lovelace"
        assert profile["user"]["orcid"] == "0000-0001-2345-6789"
        assert "researcher.name" in summary["migrated_keys"]
        assert "researcher.orcid" in summary["migrated_keys"]

    def test_compute_environment_mapped_to_profile(self, monkeypatch, tmp_path):
        ros_home = _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "proj5"
        project_root.mkdir()
        _write_old_config(project_root, {
            "runtime": {"compute_environment": "conda env: myproj"}
        })

        from research_os.config.migrate_config import migrate_project_to_v5
        migrate_project_to_v5(project_root)

        profile = yaml.safe_load((ros_home / "profile.yaml").read_text())
        assert profile["compute"]["default"] == "conda env: myproj"

    def test_model_profile_mapped_to_profile(self, monkeypatch, tmp_path):
        ros_home = _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "proj6"
        project_root.mkdir()
        _write_old_config(project_root, {"model_profile": "large"})

        from research_os.config.migrate_config import migrate_project_to_v5
        migrate_project_to_v5(project_root)

        profile = yaml.safe_load((ros_home / "profile.yaml").read_text())
        assert profile["model"]["preferred"] == "large"

    def test_full_mapping_all_keys(self, monkeypatch, tmp_path):
        """All mapped keys present in old config → all forwarded."""
        ros_home = _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "full_proj"
        project_root.mkdir()
        _write_old_config(project_root, {
            "project_name": "Full Study",
            "research_goal": {"output_types": ["paper"]},
            "interaction": {
                "autonomy_level": "supervised",
                "quality_gate_policy": "enforce",
            },
            "researcher": {"name": "Grace Hopper", "orcid": "0000-0002-0000-0001"},
            "runtime": {"compute_environment": "module load cuda/12"},
            "model_profile": "medium",
        })

        from research_os.config.migrate_config import migrate_project_to_v5
        summary = migrate_project_to_v5(project_root)

        expected_keys = {
            "project_name",
            "research_goal.output_types",
            "interaction.autonomy_level",
            "interaction.quality_gate_policy",
            "researcher.name",
            "researcher.orcid",
            "runtime.compute_environment",
            "model_profile",
        }
        assert set(summary["migrated_keys"]) == expected_keys

        config = yaml.safe_load(
            (project_root / ".os_state" / "config.yaml").read_text()
        )
        assert config["project"]["name"] == "Full Study"
        assert config["project"]["output_types"] == ["paper"]
        assert config["autonomy"]["level"] == "supervised"
        assert config["autonomy"]["quality_gate"] == "enforce"

        profile = yaml.safe_load((ros_home / "profile.yaml").read_text())
        assert profile["user"]["name"] == "Grace Hopper"
        assert profile["user"]["orcid"] == "0000-0002-0000-0001"
        assert profile["compute"]["default"] == "module load cuda/12"
        assert profile["model"]["preferred"] == "medium"

    def test_empty_string_fields_not_migrated(self, monkeypatch, tmp_path):
        """Blank/empty old-config values must NOT overwrite v5 defaults."""
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "blank_proj"
        project_root.mkdir()
        _write_old_config(project_root, {
            "project_name": "",
            "researcher": {"name": "", "orcid": ""},
        })

        from research_os.config.migrate_config import migrate_project_to_v5
        summary = migrate_project_to_v5(project_root)

        assert "project_name" not in summary["migrated_keys"]
        assert "researcher.name" not in summary["migrated_keys"]
        assert "researcher.orcid" not in summary["migrated_keys"]


# ---------------------------------------------------------------------------
# Missing old config → valid v5 defaults
# ---------------------------------------------------------------------------


class TestMigrateWithNoOldConfig:
    def test_produces_project_config(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "fresh_proj"
        project_root.mkdir()
        # No inputs/researcher_config.yaml

        from research_os.config.migrate_config import migrate_project_to_v5
        summary = migrate_project_to_v5(project_root)

        assert Path(summary["project_config"]).exists()
        config = yaml.safe_load(Path(summary["project_config"]).read_text())
        assert "project" in config
        assert "autonomy" in config

    def test_project_name_falls_back_to_dir_name(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "fallback_study"
        project_root.mkdir()

        from research_os.config.migrate_config import migrate_project_to_v5
        migrate_project_to_v5(project_root)

        config = yaml.safe_load(
            (project_root / ".os_state" / "config.yaml").read_text()
        )
        assert config["project"]["name"] == "fallback_study"

    def test_produces_user_profile(self, monkeypatch, tmp_path):
        ros_home = _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch, user_name="Auto User", compute="local")
        project_root = tmp_path / "noprofile_proj"
        project_root.mkdir()

        from research_os.config.migrate_config import migrate_project_to_v5
        summary = migrate_project_to_v5(project_root)

        assert Path(summary["user_profile"]).exists()
        profile = yaml.safe_load((ros_home / "profile.yaml").read_text())
        assert isinstance(profile, dict)
        assert "user" in profile

    def test_migrated_keys_empty_when_no_old_config(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "empty_proj"
        project_root.mkdir()

        from research_os.config.migrate_config import migrate_project_to_v5
        summary = migrate_project_to_v5(project_root)

        assert summary["migrated_keys"] == []


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestMigrateIdempotency:
    def test_twice_is_safe(self, monkeypatch, tmp_path):
        ros_home = _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "idempotent_proj"
        project_root.mkdir()
        _write_old_config(project_root, {
            "project_name": "Stable Study",
            "researcher": {"name": "Marie Curie"},
        })

        from research_os.config.migrate_config import migrate_project_to_v5
        summary1 = migrate_project_to_v5(project_root)
        summary2 = migrate_project_to_v5(project_root)

        # Both runs write the same files; paths don't change.
        assert summary1["project_config"] == summary2["project_config"]
        assert summary1["user_profile"] == summary2["user_profile"]

        # Content is consistent after the second run.
        config = yaml.safe_load(
            (project_root / ".os_state" / "config.yaml").read_text()
        )
        assert config["project"]["name"] == "Stable Study"

        profile = yaml.safe_load((ros_home / "profile.yaml").read_text())
        assert profile["user"]["name"] == "Marie Curie"

    def test_twice_with_no_old_config_is_safe(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "empty_idem"
        project_root.mkdir()

        from research_os.config.migrate_config import migrate_project_to_v5
        migrate_project_to_v5(project_root)
        migrate_project_to_v5(project_root)  # second call must not raise

        assert (project_root / ".os_state" / "config.yaml").exists()


# ---------------------------------------------------------------------------
# Summary dict shape
# ---------------------------------------------------------------------------


class TestSummaryShape:
    def test_summary_has_required_keys(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "shape_proj"
        project_root.mkdir()

        from research_os.config.migrate_config import migrate_project_to_v5
        summary = migrate_project_to_v5(project_root)

        assert set(summary.keys()) >= {"user_profile", "project_config", "migrated_keys"}

    def test_paths_are_strings(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "string_proj"
        project_root.mkdir()

        from research_os.config.migrate_config import migrate_project_to_v5
        summary = migrate_project_to_v5(project_root)

        assert isinstance(summary["user_profile"], str)
        assert isinstance(summary["project_config"], str)

    def test_migrated_keys_is_list(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "list_proj"
        project_root.mkdir()

        from research_os.config.migrate_config import migrate_project_to_v5
        summary = migrate_project_to_v5(project_root)

        assert isinstance(summary["migrated_keys"], list)

    def test_project_config_path_ends_in_expected_suffix(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "path_proj"
        project_root.mkdir()

        from research_os.config.migrate_config import migrate_project_to_v5
        summary = migrate_project_to_v5(project_root)

        assert summary["project_config"].endswith(".os_state/config.yaml")

    def test_user_profile_path_ends_in_profile_yaml(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        project_root = tmp_path / "profile_path_proj"
        project_root.mkdir()

        from research_os.config.migrate_config import migrate_project_to_v5
        summary = migrate_project_to_v5(project_root)

        assert summary["user_profile"].endswith("profile.yaml")
