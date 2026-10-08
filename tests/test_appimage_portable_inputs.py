"""Driver input gates and filesystem discipline (fakes only, no real Docker)."""

from __future__ import annotations

from pathlib import Path

from tests.appimage_portable_fakes import (
    DOCKERFILE,
    INNER,
    SCRIPT,
    docker_commands,
    portable_harness,
    read_text,
    stage_repo_copy,
)


def _repo_script(tmp_path: Path) -> tuple[Path, Path]:
    repo = stage_repo_copy(tmp_path)
    return repo, repo / "buildpython/steps/appimage/portable-build.sh"


def test_help_exits_zero_without_docker(tmp_path: Path) -> None:
    fake = portable_harness(tmp_path)
    (fake.root / "bin/docker").unlink()
    result, commands = fake.run("--help")
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "static" in result.stdout.lower()
    assert commands == []


def test_inner_help_exits_zero() -> None:
    text = read_text(INNER)
    assert "Usage:" in text
    assert "build" in text and "gate" in text and "check" in text


def test_unknown_arguments_are_rejected(tmp_path: Path) -> None:
    fake = portable_harness(tmp_path)
    for extra in ("--install-openrazer", "--version", "--with-appimage", "AppImage"):
        result, commands = fake.run(extra)
        assert result.returncode != 0, extra
        assert "unknown argument" in result.stderr
        assert docker_commands(commands, "build") == []


def test_inner_unknown_phase_is_rejected() -> None:
    text = read_text(INNER)
    assert "unknown phase" in text


def test_preflight_gates_run_before_writes(tmp_path: Path) -> None:
    cases: list[tuple[dict[str, str], str]] = [
        ({"uid": "0"}, "not root"),
        ({"os": "Darwin"}, "requires Linux"),
        ({"arch": "aarch64"}, "requires x86_64"),
    ]
    for index, (changes, message) in enumerate(cases):
        base = tmp_path / f"gate-{index}"
        base.mkdir(parents=True)
        fake = portable_harness(base)
        fake.configure(**changes)
        _, script = _repo_script(base)
        before = set((fake.root / "home").rglob("*"))
        result, commands = fake.run(script=script)
        assert result.returncode != 0
        assert message in result.stderr
        assert commands != []
        assert all(c[0] in ("id", "uname") for c in commands)
        assert docker_commands(commands, "build") == []
        assert set((fake.root / "home").rglob("*")) == before
        assert list((fake.root / "runner-temp").iterdir()) == []
        assert list((fake.root / "tmpdir").iterdir()) == []


def test_missing_docker_is_read_only(tmp_path: Path) -> None:
    fake = portable_harness(tmp_path)
    (fake.root / "bin/docker").unlink()
    _, script = _repo_script(tmp_path)
    result, commands = fake.run(script=script)
    assert result.returncode != 0
    assert "docker is required" in result.stderr
    assert commands == [c for c in commands if c[0] in ("id", "uname")]
    assert list((fake.root / "runner-temp").iterdir()) == []


def test_missing_repo_inputs_fail_closed(tmp_path: Path) -> None:
    for missing in (
        "pyproject.toml",
        "buildpython/steps/appimage/Dockerfile.portable",
        "buildpython/steps/appimage/portable-inner.sh",
    ):
        base = tmp_path / missing.replace("/", "_")
        base.mkdir(parents=True)
        fake = portable_harness(base)
        repo, script = _repo_script(base)
        (repo / missing).unlink()
        result, _ = fake.run(script=script)
        assert result.returncode != 0, missing
        assert missing.split("/")[-1] in result.stderr


def test_scratch_prefers_runner_temp_and_cleans_up(tmp_path: Path) -> None:
    fake = portable_harness(tmp_path)
    _, script = _repo_script(tmp_path)
    before_home = set((fake.root / "home").rglob("*"))
    result, _ = fake.run(script=script)
    assert result.returncode == 0, result.stderr
    assert list((fake.root / "runner-temp").iterdir()) == []
    assert list((fake.root / "tmpdir").iterdir()) == []
    assert set((fake.root / "home").rglob("*")) == before_home
    text = read_text(SCRIPT)
    assert "RUNNER_TEMP" in text
    assert "TMPDIR" in text
    assert "/tmp/opencode" in text
    assert text.index("RUNNER_TEMP") < text.index("TMPDIR")
    assert text.index("TMPDIR") < text.index("/tmp/opencode")
    assert "umask 077" in text
    assert "trap cleanup EXIT" in text


def test_paths_with_spaces_are_quoted(tmp_path: Path) -> None:
    fake = portable_harness(tmp_path)
    spaced_base = tmp_path / "base with spaces"
    spaced_base.mkdir()
    fake.environment["RUNNER_TEMP"] = str(fake.root / "runner temp with spaces")
    (fake.root / "runner temp with spaces").mkdir()
    repo = stage_repo_copy(spaced_base, name="repo with spaces")
    script = repo / "buildpython/steps/appimage/portable-build.sh"
    result, commands = fake.run(script=script)
    assert result.returncode == 0, result.stderr
    builds = docker_commands(commands, "build")
    runs = docker_commands(commands, "run")
    assert len(builds) == 1 and len(runs) == 3
    assert str(repo / "buildpython/steps/appimage/Dockerfile.portable") in builds[0]
    for run in runs:
        assert any(f"{repo}:/workspace" in token for token in run)


def test_no_polling_or_stdin_redirection() -> None:
    for path in (SCRIPT, INNER):
        text = read_text(path)
        lowered = text.lower()
        assert "sleep" not in lowered
        assert "</dev/null" not in text or "service --help" in text
        assert "while true" not in lowered
        assert "poll" not in lowered
    assert DOCKERFILE.exists()
    assert INNER.exists()
