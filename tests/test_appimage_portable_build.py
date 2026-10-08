"""Portable recipe pins and driver build/run foundation (fakes only)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.appimage_portable_fakes import (
    ALLOWED_APT,
    BASE_IMAGE,
    CANDIDATE,
    CONTROL_BIN,
    DOCKERFILE,
    INNER,
    PENDING,
    PYTHON_SHA,
    PYTHON_URL,
    SCRIPT,
    apt_tokens,
    docker_commands,
    portable_harness,
    read_text,
    run_fragments,
    stage_repo_copy,
)


def test_dockerfile_pins_base_source_and_checksum_order() -> None:
    text = read_text(DOCKERFILE)
    assert f"FROM {BASE_IMAGE}" in text
    assert PYTHON_URL in text
    assert PYTHON_SHA in text
    sha_pos = text.index(PYTHON_SHA)
    assert sha_pos < text.index("tar -xf")
    assert sha_pos < text.index("./configure")
    assert "sha256sum -c" in text


def test_dockerfile_apt_is_jammy_without_t64() -> None:
    text = read_text(DOCKERFILE)
    assert "t64" not in text
    tokens = apt_tokens(text)
    assert tokens, "expected apt package tokens"
    assert set(tokens) <= ALLOWED_APT
    for required in ("build-essential", "libssl-dev", "libffi-dev", "zlib1g-dev"):
        assert required in tokens


def test_dockerfile_container_provides_file_utility_for_appimagetool() -> None:
    text = read_text(DOCKERFILE)
    tokens = apt_tokens(text)
    assert "file" in tokens


def test_dockerfile_toolchain_only_static_policy() -> None:
    text = read_text(DOCKERFILE)
    lowered = text.lower()
    assert "copy" not in lowered
    assert "\nadd " not in lowered
    assert "pythonhome" not in lowered
    assert "march=native" not in lowered and "march-native" not in lowered
    assert "\narg " not in lowered
    assert "--enable-shared" in text
    assert "--without-static-libpython" in text
    assert "--prefix=/opt/naga-python" in text
    assert "ENV LD_LIBRARY_PATH=/opt/naga-python/lib" in text
    assert f"ENV PYTHON_BIN={CONTROL_BIN}" in text
    for claim in ("reproducib", "provenance", "sbom", "slsa"):
        assert claim not in lowered


def test_dockerfile_ascii_and_run_fragments_parse(tmp_path: Path) -> None:
    raw = DOCKERFILE.read_bytes()
    assert all(byte < 128 for byte in raw)
    fragments = run_fragments(read_text(DOCKERFILE))
    assert len(fragments) == 2
    for index, fragment in enumerate(fragments):
        probe = tmp_path / f"fragment-{index}.sh"
        probe.write_text(fragment + "\n", encoding="utf-8")
        result = subprocess.run(
            ["/bin/sh", "-n", str(probe)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr


def test_driver_build_and_run_success_uses_immutable_id(tmp_path: Path) -> None:
    fake = portable_harness(tmp_path)
    repo = stage_repo_copy(tmp_path)
    script = repo / "buildpython/steps/appimage/portable-build.sh"
    result, commands = fake.run(script=script)
    assert result.returncode == 0, result.stderr
    assert CANDIDATE in result.stdout
    assert PENDING not in result.stdout
    builds = docker_commands(commands, "build")
    runs = docker_commands(commands, "run")
    assert len(builds) == 1
    assert len(runs) == 3
    build = builds[0]
    assert "--platform" in build and "linux/amd64" in build
    assert "--iidfile" in build
    assert not any(token in ("-t", "--tag") for token in build)
    assert str(repo / "buildpython/steps/appimage/Dockerfile.portable") in build
    for run in runs:
        assert run.count("--rm") == 1
    images = {run[run.index("-w") + 2] for run in runs}
    assert len(images) == 1
    phases = [run[-1] for run in runs]
    assert phases == ["build", "gate", "check"]
    for run in runs:
        assert "portable-inner.sh" in run[-2]


def test_driver_build_failure_has_no_retry_and_cleans_scratch(tmp_path: Path) -> None:
    fake = portable_harness(tmp_path)
    fake.configure(build_fail=1)
    repo = stage_repo_copy(tmp_path)
    script = repo / "buildpython/steps/appimage/portable-build.sh"
    result, commands = fake.run(script=script)
    assert result.returncode != 0
    assert CANDIDATE not in result.stdout
    assert len(docker_commands(commands, "build")) == 1
    assert docker_commands(commands, "run") == []
    scratch_parent = fake.root / "runner-temp"
    assert list(scratch_parent.iterdir()) == []


def test_driver_bad_image_ids_are_rejected(tmp_path: Path) -> None:
    for bad in ("short", "upper", "empty"):
        base = tmp_path / f"case-{bad}"
        base.mkdir(parents=True)
        fresh = portable_harness(base)
        fresh.configure(bad_iid=bad)
        repo = stage_repo_copy(base, name=f"repo-{bad}")
        script = repo / "buildpython/steps/appimage/portable-build.sh"
        result, commands = fresh.run(script=script)
        assert result.returncode != 0, bad
        assert docker_commands(commands, "run") == []


def test_driver_run_failure_preserves_status_without_candidate(tmp_path: Path) -> None:
    fake = portable_harness(tmp_path)
    fake.configure(run_fail=1)
    repo = stage_repo_copy(tmp_path)
    script = repo / "buildpython/steps/appimage/portable-build.sh"
    result, commands = fake.run(script=script)
    assert result.returncode != 0
    assert CANDIDATE not in result.stdout
    assert len(docker_commands(commands, "build")) == 1
    assert len(docker_commands(commands, "run")) == 1


def test_driver_gate_failure_stops_before_check(tmp_path: Path) -> None:
    fake = portable_harness(tmp_path)
    fake.configure(run_fail_at=2)
    repo = stage_repo_copy(tmp_path)
    script = repo / "buildpython/steps/appimage/portable-build.sh"
    result, commands = fake.run(script=script)
    assert result.returncode != 0
    assert CANDIDATE not in result.stdout
    runs = docker_commands(commands, "run")
    assert len(runs) == 2
    assert [run[-1] for run in runs] == ["build", "gate"]


def test_driver_check_failure_has_no_verified_message(tmp_path: Path) -> None:
    fake = portable_harness(tmp_path)
    fake.configure(run_fail_at=3)
    repo = stage_repo_copy(tmp_path)
    script = repo / "buildpython/steps/appimage/portable-build.sh"
    result, commands = fake.run(script=script)
    assert result.returncode != 0
    assert CANDIDATE not in result.stdout
    assert len(docker_commands(commands, "run")) == 3


def test_script_references_pinned_toolchain() -> None:
    text = read_text(SCRIPT)
    assert "Dockerfile.portable" in text
    assert "portable-inner.sh" in text
    assert "--iidfile" in text
    assert CONTROL_BIN in text
    assert CANDIDATE in text
    assert PENDING not in text
    inner = read_text(INNER)
    assert "3.12.15" in inner
    assert "2.35" in inner
    assert "--run-steps AppImage" in inner
    assert "--baseline-root /" in inner
    assert "buildpython.steps.appimage.artifact" in inner
