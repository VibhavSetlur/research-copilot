"""DockerRunner: containerised jobs through the daemon (composition + tracking)."""
from __future__ import annotations


import pytest

from research_os.daemon.runners import DockerRunner, docker_available


def test_compose_docker_run_argv():
    r = DockerRunner(
        "img:1.0", "python run.py --in data.csv",
        cwd="/proj", mount_root="/proj", env={"SEED": "42"},
        binary="/usr/bin/docker",
    )
    argv = r._inner.cmd
    assert argv[:3] == ["/usr/bin/docker", "run", "--rm"]
    assert "--network" in argv and "none" in argv  # isolated by default
    assert "-v" in argv and "/proj:/proj" in argv
    assert "-w" in argv and "/proj" in argv
    assert "-e" in argv and "SEED" in argv
    # inner command preserved after the image
    i = argv.index("img:1.0")
    assert argv[i + 1:] == ["python", "run.py", "--in", "data.csv"]


def test_gpus_and_network_flags():
    r = DockerRunner("img", "x", cwd="/p", mount_root="/p",
                     gpus="all", network=True, binary="/usr/bin/docker")
    argv = r._inner.cmd
    assert "--gpus" in argv and "all" in argv
    assert "none" not in argv  # network requested → no --network none


def test_missing_cli_raises(monkeypatch):
    # Force "no container CLI" by making both the override and discovery empty.
    monkeypatch.setattr("research_os.daemon.runners._container_cli", lambda: None)
    with pytest.raises(RuntimeError):
        DockerRunner("img", "x")  # no binary, discovery returns None → raise


def test_docker_available_is_bool():
    assert isinstance(docker_available(), bool)


def test_list_command_preserved():
    r = DockerRunner("img", ["bash", "-lc", "echo hi"], cwd="/p",
                     mount_root="/p", binary="/usr/bin/docker")
    i = r._inner.cmd.index("img")
    assert r._inner.cmd[i + 1:] == ["bash", "-lc", "echo hi"]
