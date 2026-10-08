"""Driver confinement and bounded AppImage phases (fakes only, no real Docker)."""

from __future__ import annotations

from pathlib import Path

from tests.appimage_portable_fakes import (
    CANDIDATE,
    CONTROL_BIN,
    INNER,
    PENDING,
    SCRIPT,
    docker_commands,
    portable_harness,
    read_text,
    stage_repo_copy,
)


def _success(tmp_path: Path) -> tuple[list[list[str]], Path]:
    fake = portable_harness(tmp_path)
    repo = stage_repo_copy(tmp_path)
    script = repo / "buildpython/steps/appimage/portable-build.sh"
    result, commands = fake.run(script=script)
    assert result.returncode == 0, result.stderr
    assert CANDIDATE in result.stdout
    assert PENDING not in result.stdout
    return commands, repo


def _runs_by_phase(commands: list[list[str]]) -> dict[str, list[str]]:
    runs = docker_commands(commands, "run")
    assert len(runs) == 3
    return {run[-1]: run for run in runs}


def test_runs_are_unprivileged_with_dropped_caps(tmp_path: Path) -> None:
    commands, _ = _success(tmp_path)
    for run in docker_commands(commands, "run"):
        assert "--rm" in run
        assert "--platform" in run and "linux/amd64" in run
        user_index = run.index("--user") + 1
        uid, gid = run[user_index].split(":")
        assert uid == "1000" and gid == "1000" and uid != "0"
        assert "--cap-drop=ALL" in run
        assert "--security-opt=no-new-privileges" in run


def test_build_mounts_writable_workspace_gate_check_are_read_only(tmp_path: Path) -> None:
    commands, repo = _success(tmp_path)
    phases = _runs_by_phase(commands)
    assert phases["build"].count(f"{repo}:/workspace") == 1
    assert f"{repo}:/workspace:ro" not in phases["build"]
    assert "--read-only" not in phases["build"]
    for phase in ("gate", "check"):
        run = phases[phase]
        assert f"{repo}:/workspace:ro" in run
        assert "--read-only" in run
        assert "--tmpfs" in run
        tmpfs = run[run.index("--tmpfs") + 1]
        assert tmpfs.startswith("/tmp/opencode:")
        assert "size=3G" in tmpfs
        assert "--network" in run and "none" in run
        assert "--pids-limit" in run and "--memory" in run and "--cpus" in run


def test_runs_mount_only_workspace(tmp_path: Path) -> None:
    commands, repo = _success(tmp_path)
    for run in docker_commands(commands, "run"):
        assert "--privileged" not in run
        assert "--device" not in run
        assert "--net=host" not in run
        assert "--network=host" not in run
        assert not any(
            token == "--network" and run[i + 1] == "host" for i, token in enumerate(run[:-1])
        )
        volumes: list[str] = []
        for index, token in enumerate(run):
            if token in ("-v", "--volume"):
                volumes.append(run[index + 1])
            elif token.startswith("--mount"):
                volumes.append(token)
        assert volumes == [v for v in volumes if f"{repo}:/workspace" in v]
        assert len(volumes) == 1
        assert "-w" in run and "/workspace" in run
        for token in run:
            assert "docker.sock" not in token
            assert token not in ("/dev", "/run", "/home", "/etc")
            assert "DBUS" not in token


def test_env_cleans_host_injection(tmp_path: Path) -> None:
    commands, _ = _success(tmp_path)
    for run in docker_commands(commands, "run"):
        env_values: list[str] = []
        for index, token in enumerate(run):
            if token == "-e":
                env_values.append(run[index + 1])
            elif token.startswith("-e"):
                env_values.append(token[2:])
        assert "HOME=/tmp/opencode/home" in env_values
        assert f"PYTHON_BIN={CONTROL_BIN}" in env_values
        assert "ARCH=x86_64" in env_values
        assert "LD_LIBRARY_PATH=/opt/naga-python/lib" in env_values
        assert "PYTHONHOME=" in env_values
        assert "PYTHONPATH=" in env_values
        assert "LD_PRELOAD=" in env_values
        assert all("=" in value for value in env_values)
    assert "PYTHONHOME=" in read_text(SCRIPT)
    assert "PYTHONHOME" in read_text(INNER)
    assert "env -u PYTHONHOME" in read_text(INNER)
    assert "HOME=/tmp/opencode/home" in read_text(INNER)
    assert "/tmp/opencode/portable-venv" in read_text(INNER)
    check = _runs_by_phase(commands)["check"]
    joined = " ".join(check)
    assert "QT_QPA_PLATFORM=offscreen" in joined
    assert "RELEASE_VERSION=" in joined


def test_bounded_phases_run_only_selected_steps(tmp_path: Path) -> None:
    commands, _ = _success(tmp_path)
    phases = _runs_by_phase(commands)
    inner = read_text(INNER)
    assert "--run-steps AppImage" in inner
    assert "pip install" in inner and ".[dev]" in inner
    assert "portable-venv" in inner
    assert "--baseline-root /" in inner
    assert "buildpython.steps.appimage.artifact" in inner
    assert "QT_QPA_PLATFORM=offscreen" in inner
    assert "AppRun" in inner
    for forbidden in ("--appimage-extract-and-run", "release-assets"):
        assert forbidden not in inner
    build_inner = " ".join(phases["build"])
    assert "portable-inner.sh" in build_inner


def test_tripwire_host_commands_never_run(tmp_path: Path) -> None:
    commands, _ = _success(tmp_path)
    names = {command[0] for command in commands}
    for forbidden in (
        "sudo",
        "systemctl",
        "busctl",
        "curl",
        "wget",
        "apt-get",
        "pacman",
        "dnf",
        "zypper",
        "python",
        "python3",
        "openrazer",
        "AppImage",
    ):
        assert forbidden not in names
    assert names <= {"docker", "id", "uname"}


def test_image_identity_is_immutable_and_reused(tmp_path: Path) -> None:
    commands, _ = _success(tmp_path)
    builds = docker_commands(commands, "build")
    runs = docker_commands(commands, "run")
    assert len(builds) == 1 and len(runs) == 3
    assert "--iidfile" in builds[0]
    assert not any(token in ("-t", "--tag") for token in builds[0])
    images = {run[run.index("-w") + 2] for run in runs}
    assert len(images) == 1
    image = next(iter(images))
    plain = image.removeprefix("sha256:")
    assert len(plain) == 64
    assert all(char in "0123456789abcdef" for char in plain)
    assert "--network" not in _runs_by_phase(commands)["build"]


def test_home_stays_read_only_and_scratch_cleaned(tmp_path: Path) -> None:
    fake = portable_harness(tmp_path)
    repo = stage_repo_copy(tmp_path)
    script = repo / "buildpython/steps/appimage/portable-build.sh"
    before = {path.read_bytes() for path in (fake.root / "home").rglob("*") if path.is_file()}
    result, _ = fake.run(script=script)
    assert result.returncode == 0, result.stderr
    after = {path.read_bytes() for path in (fake.root / "home").rglob("*") if path.is_file()}
    assert before == after
    assert list((fake.root / "runner-temp").iterdir()) == []
    assert CANDIDATE in result.stdout
    assert PENDING not in result.stdout


def test_scripts_have_no_host_mounts_or_elevations() -> None:
    for path in (SCRIPT, INNER):
        text = read_text(path)
        assert "--privileged" not in text
        assert "--device" not in text
        assert "docker.sock" not in text
        assert "sudo " not in text
    assert Path(read_text(SCRIPT).splitlines()[0]).name in ("bash",)
