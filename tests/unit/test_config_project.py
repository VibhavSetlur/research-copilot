"""Unit tests for research_os.config.project (§9.1 new v5 config surface)."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
import yaml

from research_os.config.project import (
    _deep_merge,
    init_project_config,
    init_user_profile,
    load_project_config,
    load_user_profile,
    project_config_path,
    save_project_config,
    save_user_profile,
    user_profile_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_detect(monkeypatch, **fields):
    """Patch detect_environment to return *fields* (any omitted key absent)."""
    monkeypatch.setattr(
        "research_os.config.project.detect_environment",
        lambda **_kw: fields,
    )


def _fake_home(monkeypatch, tmp_path: Path) -> Path:
    """Redirect Path.home() and $RESEARCH_OS_HOME to a temp directory."""
    home = tmp_path / "fake_home"
    home.mkdir()
    monkeypatch.setenv("RESEARCH_OS_HOME", str(home / ".research-os"))
    return home / ".research-os"


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_flat_override(self):
        result = _deep_merge({"a": 1, "b": 2}, {"b": 99})
        assert result == {"a": 1, "b": 99}

    def test_nested_merge(self):
        base = {"user": {"name": "", "orcid": ""}, "compute": {"default": "local"}}
        override = {"user": {"name": "Alice"}}
        result = _deep_merge(base, override)
        assert result["user"]["name"] == "Alice"
        assert result["user"]["orcid"] == ""  # preserved from base
        assert result["compute"]["default"] == "local"

    def test_non_dict_override_replaces(self):
        result = _deep_merge({"key": {"nested": 1}}, {"key": "scalar"})
        assert result["key"] == "scalar"

    def test_does_not_mutate_base(self):
        base = {"a": {"x": 1}}
        _deep_merge(base, {"a": {"x": 99}})
        assert base["a"]["x"] == 1

    def test_empty_override_returns_copy_of_base(self):
        base = {"a": 1}
        result = _deep_merge(base, {})
        assert result == base
        assert result is not base

    def test_new_key_in_override_added(self):
        result = _deep_merge({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# user_profile_path
# ---------------------------------------------------------------------------


class TestUserProfilePath:
    def test_default_location(self, monkeypatch, tmp_path):
        ros_home = _fake_home(monkeypatch, tmp_path)
        path = user_profile_path()
        assert path == ros_home / "profile.yaml"

    def test_env_override(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom_home"
        monkeypatch.setenv("RESEARCH_OS_HOME", str(custom))
        path = user_profile_path()
        assert path == custom / "profile.yaml"

    def test_no_env_uses_home(self, monkeypatch, tmp_path):
        monkeypatch.delenv("RESEARCH_OS_HOME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        path = user_profile_path()
        assert path == tmp_path / ".research-os" / "profile.yaml"


# ---------------------------------------------------------------------------
# load_user_profile
# ---------------------------------------------------------------------------


class TestLoadUserProfile:
    def test_returns_default_when_file_missing(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        profile = load_user_profile()
        assert profile == {
            "user": {"name": "", "orcid": ""},
            "compute": {"default": "local", "hpc_partition": ""},
            "model": {"preferred": ""},
        }

    def test_merges_partial_yaml_with_defaults(self, monkeypatch, tmp_path):
        ros_home = _fake_home(monkeypatch, tmp_path)
        ros_home.mkdir(parents=True, exist_ok=True)
        (ros_home / "profile.yaml").write_text(
            yaml.safe_dump({"user": {"name": "Bob"}})
        )
        profile = load_user_profile()
        assert profile["user"]["name"] == "Bob"
        assert profile["user"]["orcid"] == ""  # default preserved
        assert profile["compute"]["default"] == "local"

    def test_round_trip(self, monkeypatch, tmp_path):
        ros_home = _fake_home(monkeypatch, tmp_path)
        ros_home.mkdir(parents=True, exist_ok=True)
        data = {
            "user": {"name": "Carol", "orcid": "0000-0001-2345-6789"},
            "compute": {"default": "hpc", "hpc_partition": "gpu"},
            "model": {"preferred": "CLAUDE.md"},
        }
        (ros_home / "profile.yaml").write_text(yaml.safe_dump(data))
        loaded = load_user_profile()
        assert loaded["user"]["name"] == "Carol"
        assert loaded["compute"]["hpc_partition"] == "gpu"
        assert loaded["model"]["preferred"] == "CLAUDE.md"

    def test_empty_yaml_file_returns_defaults(self, monkeypatch, tmp_path):
        ros_home = _fake_home(monkeypatch, tmp_path)
        ros_home.mkdir(parents=True, exist_ok=True)
        (ros_home / "profile.yaml").write_text("")
        profile = load_user_profile()
        assert profile["user"]["name"] == ""
        assert profile["compute"]["default"] == "local"


# ---------------------------------------------------------------------------
# init_user_profile
# ---------------------------------------------------------------------------


class TestInitUserProfile:
    def test_creates_file(self, monkeypatch, tmp_path):
        ros_home = _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        init_user_profile()
        assert (ros_home / "profile.yaml").exists()

    def test_auto_fills_user_name(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch, user_name="Ada Lovelace", compute="local")
        profile = init_user_profile()
        assert profile["user"]["name"] == "Ada Lovelace"

    def test_auto_fills_compute(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch, compute="hpc")
        profile = init_user_profile()
        assert profile["compute"]["default"] == "hpc"

    def test_auto_fills_model_preferred_from_inferred_client(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch, inferred_client="CLAUDE.md", compute="local")
        profile = init_user_profile()
        assert profile["model"]["preferred"] == "CLAUDE.md"

    def test_overrides_deep_merge(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch, user_name="Auto Name", compute="local")
        profile = init_user_profile(overrides={"user": {"name": "Manual Name"}})
        assert profile["user"]["name"] == "Manual Name"
        assert profile["compute"]["default"] == "local"

    def test_overrides_none_ok(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch, compute="docker")
        profile = init_user_profile(overrides=None)
        assert profile["compute"]["default"] == "docker"

    def test_chmod_600(self, monkeypatch, tmp_path):
        ros_home = _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)
        init_user_profile()
        path = ros_home / "profile.yaml"
        file_stat = path.stat()
        # Check owner read+write only (no group, no other)
        assert file_stat.st_mode & stat.S_IRWXU == (stat.S_IRUSR | stat.S_IWUSR)
        assert file_stat.st_mode & stat.S_IRWXG == 0
        assert file_stat.st_mode & stat.S_IRWXO == 0

    def test_creates_parent_dirs(self, monkeypatch, tmp_path):
        custom = tmp_path / "deep" / "nested" / "home"
        monkeypatch.setenv("RESEARCH_OS_HOME", str(custom))
        _stub_detect(monkeypatch)
        init_user_profile()
        assert (custom / "profile.yaml").exists()

    def test_missing_detect_fields_leave_defaults(self, monkeypatch, tmp_path):
        _fake_home(monkeypatch, tmp_path)
        _stub_detect(monkeypatch)  # no user_name, no inferred_client
        profile = init_user_profile()
        assert profile["user"]["name"] == ""
        assert profile["model"]["preferred"] == ""


# ---------------------------------------------------------------------------
# save_user_profile
# ---------------------------------------------------------------------------


class TestSaveUserProfile:
    def test_round_trip(self, monkeypatch, tmp_path):
        ros_home = _fake_home(monkeypatch, tmp_path)
        ros_home.mkdir(parents=True, exist_ok=True)
        data = {
            "user": {"name": "Dave", "orcid": ""},
            "compute": {"default": "docker", "hpc_partition": ""},
            "model": {"preferred": ""},
        }
        save_user_profile(data)
        loaded = yaml.safe_load((ros_home / "profile.yaml").read_text())
        assert loaded["user"]["name"] == "Dave"

    def test_chmod_600_on_save(self, monkeypatch, tmp_path):
        ros_home = _fake_home(monkeypatch, tmp_path)
        ros_home.mkdir(parents=True, exist_ok=True)
        save_user_profile({"user": {"name": "Eve", "orcid": ""}, "compute": {}, "model": {}})
        path = ros_home / "profile.yaml"
        file_stat = path.stat()
        assert file_stat.st_mode & stat.S_IRWXU == (stat.S_IRUSR | stat.S_IWUSR)
        assert file_stat.st_mode & stat.S_IRWXG == 0
        assert file_stat.st_mode & stat.S_IRWXO == 0

    def test_creates_parent_dirs(self, monkeypatch, tmp_path):
        custom = tmp_path / "nonexistent" / "path"
        monkeypatch.setenv("RESEARCH_OS_HOME", str(custom))
        save_user_profile({"user": {"name": ""}, "compute": {}, "model": {}})
        assert (custom / "profile.yaml").exists()


# ---------------------------------------------------------------------------
# project_config_path
# ---------------------------------------------------------------------------


class TestProjectConfigPath:
    def test_returns_os_state_config(self, tmp_path):
        result = project_config_path(tmp_path)
        assert result == tmp_path / ".os_state" / "config.yaml"

    def test_accepts_string_path(self, tmp_path):
        result = project_config_path(str(tmp_path))
        assert result == tmp_path / ".os_state" / "config.yaml"


# ---------------------------------------------------------------------------
# load_project_config
# ---------------------------------------------------------------------------


class TestLoadProjectConfig:
    def test_returns_default_when_file_missing(self, tmp_path):
        config = load_project_config(tmp_path)
        assert config == {
            "project": {"name": "", "output_types": ["paper", "figures"]},
            "autonomy": {"level": "semi", "quality_gate": "normal"},
        }

    def test_merges_partial_yaml_with_defaults(self, tmp_path):
        os_state = tmp_path / ".os_state"
        os_state.mkdir()
        (os_state / "config.yaml").write_text(
            yaml.safe_dump({"project": {"name": "MyProject"}})
        )
        config = load_project_config(tmp_path)
        assert config["project"]["name"] == "MyProject"
        assert config["project"]["output_types"] == ["paper", "figures"]
        assert config["autonomy"]["level"] == "semi"

    def test_round_trip(self, tmp_path):
        os_state = tmp_path / ".os_state"
        os_state.mkdir()
        data = {
            "project": {"name": "SciPaper", "output_types": ["paper"]},
            "autonomy": {"level": "full", "quality_gate": "strict"},
        }
        (os_state / "config.yaml").write_text(yaml.safe_dump(data))
        config = load_project_config(tmp_path)
        assert config["autonomy"]["level"] == "full"
        assert config["autonomy"]["quality_gate"] == "strict"

    def test_empty_yaml_file_returns_defaults(self, tmp_path):
        os_state = tmp_path / ".os_state"
        os_state.mkdir()
        (os_state / "config.yaml").write_text("")
        config = load_project_config(tmp_path)
        assert config["project"]["name"] == ""
        assert config["autonomy"]["level"] == "semi"


# ---------------------------------------------------------------------------
# init_project_config
# ---------------------------------------------------------------------------


class TestInitProjectConfig:
    def test_creates_file(self, tmp_path):
        project_dir = tmp_path / "my_project"
        project_dir.mkdir()
        init_project_config(project_dir)
        assert (project_dir / ".os_state" / "config.yaml").exists()

    def test_auto_fills_name_from_dir(self, tmp_path):
        project_dir = tmp_path / "awesome_study"
        project_dir.mkdir()
        config = init_project_config(project_dir)
        assert config["project"]["name"] == "awesome_study"

    def test_overrides_deep_merge(self, tmp_path):
        project_dir = tmp_path / "my_study"
        project_dir.mkdir()
        config = init_project_config(
            project_dir,
            overrides={"autonomy": {"level": "full"}, "project": {"output_types": ["paper"]}},
        )
        assert config["autonomy"]["level"] == "full"
        assert config["project"]["output_types"] == ["paper"]
        assert config["project"]["name"] == "my_study"  # auto-filled, not overridden

    def test_overrides_name(self, tmp_path):
        project_dir = tmp_path / "dir_name"
        project_dir.mkdir()
        config = init_project_config(
            project_dir,
            overrides={"project": {"name": "custom_name"}},
        )
        assert config["project"]["name"] == "custom_name"

    def test_overrides_none_ok(self, tmp_path):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        config = init_project_config(project_dir, overrides=None)
        assert config["project"]["name"] == "proj"

    def test_creates_os_state_dir(self, tmp_path):
        project_dir = tmp_path / "new_project"
        project_dir.mkdir()
        init_project_config(project_dir)
        assert (project_dir / ".os_state").is_dir()

    def test_written_yaml_is_valid(self, tmp_path):
        project_dir = tmp_path / "valid_proj"
        project_dir.mkdir()
        init_project_config(project_dir)
        content = (project_dir / ".os_state" / "config.yaml").read_text()
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict)
        assert "project" in parsed
        assert "autonomy" in parsed


# ---------------------------------------------------------------------------
# save_project_config
# ---------------------------------------------------------------------------


class TestSaveProjectConfig:
    def test_round_trip(self, tmp_path):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        data = {
            "project": {"name": "test", "output_types": ["paper", "figures"]},
            "autonomy": {"level": "semi", "quality_gate": "normal"},
        }
        save_project_config(project_dir, data)
        path = project_dir / ".os_state" / "config.yaml"
        assert path.exists()
        loaded = yaml.safe_load(path.read_text())
        assert loaded["project"]["name"] == "test"

    def test_creates_parent_dirs(self, tmp_path):
        project_dir = tmp_path / "deep" / "project"
        project_dir.mkdir(parents=True)
        save_project_config(project_dir, {"project": {"name": "x"}, "autonomy": {}})
        assert (project_dir / ".os_state" / "config.yaml").exists()

    def test_overwrite_existing(self, tmp_path):
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        os_state = project_dir / ".os_state"
        os_state.mkdir()
        (os_state / "config.yaml").write_text(yaml.safe_dump({"project": {"name": "old"}}))
        save_project_config(
            project_dir,
            {"project": {"name": "new", "output_types": []}, "autonomy": {}},
        )
        loaded = yaml.safe_load((os_state / "config.yaml").read_text())
        assert loaded["project"]["name"] == "new"


# ---------------------------------------------------------------------------
# Public API re-exported from research_os.config
# ---------------------------------------------------------------------------


class TestPublicExports:
    def test_all_exported_from_package(self):
        import research_os.config as cfg

        for name in [
            "user_profile_path",
            "load_user_profile",
            "init_user_profile",
            "save_user_profile",
            "project_config_path",
            "load_project_config",
            "init_project_config",
            "save_project_config",
        ]:
            assert hasattr(cfg, name), f"research_os.config missing export: {name}"

    def test_existing_exports_preserved(self):
        import research_os.config as cfg

        assert hasattr(cfg, "detect_environment")
        assert hasattr(cfg, "settings")
        assert hasattr(cfg, "Settings")
