"""Static gate ordering, confinement, and version policy (fakes only)."""

from __future__ import annotations

import ast
from pathlib import Path

from tests.appimage_portable_fakes import (
    CANDIDATE,
    CONTROL_BIN,
    INNER,
    REPO,
    SCRIPT,
    docker_commands,
    portable_harness,
    read_text,
    stage_repo_copy,
)


def _phases(commands: list[list[str]]) -> list[str]:
    return [run[-1] for run in docker_commands(commands, "run")]


def test_gate_runs_before_any_bundled_execution(tmp_path: Path) -> None:
    fake = portable_harness(tmp_path)
    repo = stage_repo_copy(tmp_path)
    result, commands = fake.run(script=repo / "buildpython/steps/appimage/portable-build.sh")
    assert result.returncode == 0, result.stderr
    assert _phases(commands) == ["build", "gate", "check"]
    inner = read_text(INNER)
    build_pos = inner.index("--run-steps AppImage")
    gate_pos = inner.index("buildpython.steps.appimage.artifact")
    apprun_pos = inner.index('"$APPRUN" python -c "import dbus')
    assert build_pos < gate_pos < apprun_pos


def test_gate_uses_controlled_python_with_clean_env_and_baseline_root() -> None:
    inner = read_text(INNER)
    assert CONTROL_BIN in inner
    assert '"-m", "buildpython.steps.appimage.artifact"' in inner or (
        "-m buildpython.steps.appimage.artifact" in inner
        or "buildpython.steps.appimage.artifact" in inner
    )
    assert "--baseline-root /" in inner
    assert "env -u PYTHONHOME -u PYTHONPATH -u LD_PRELOAD" in inner
    assert 'PYTHON_BIN="$CONTROL_BIN"' in inner or "PYTHON_BIN=" in inner
    assert ".venv" in inner
    assert "VIRTUAL_ENV" in inner
    assert "host .venv must not be on PATH" in inner


def test_gate_import_chain_is_stdlib_only() -> None:
    allowed = {
        "argparse",
        "ast",
        "collections",
        "contextlib",
        "dataclasses",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "re",
        "selectors",
        "shutil",
        "stat",
        "subprocess",
        "sys",
        "tempfile",
        "time",
        "typing",
        "__future__",
    }
    for name in ("artifact.py", "elf.py", "versions.py", "dependencies.py", "extraction.py"):
        path = REPO / f"buildpython/steps/appimage/{name}"
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] in allowed, (name, alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                assert node.module is None or node.module.split(".")[0] in {
                    *allowed,
                    "buildpython",
                }, (name, node.module)


def test_exactly_one_artifact_is_required_before_gate_and_check() -> None:
    inner = read_text(INNER)
    assert "expected exactly one AppImage" in inner
    assert inner.count("one_appimage") >= 3
    assert "Naga-Control-*-x86_64.AppImage" in inner
    assert "test -s" in inner


def test_version_mismatch_fails_closed() -> None:
    inner = read_text(INNER)
    assert "RELEASE_VERSION" in inner
    assert "bundled version" in inner
    assert "expected version" in inner
    assert inner.count("exit 1") >= 4
    assert "tomllib" in inner
    assert "pyproject.toml" in inner
    assert "version('naga-control')" in inner or 'version("naga-control")' in inner


def test_check_uses_offscreen_appdir_without_service_launch() -> None:
    inner = read_text(INNER)
    assert "QT_QPA_PLATFORM" in inner
    assert "offscreen" in inner
    assert "AppRun" in inner
    assert "service --help" in inner
    assert "capture --help" in inner
    assert "integration --help" in inner
    assert "integration-payload-ok" in inner
    assert "KillMode=mixed" in inner
    assert "len(installed) == 8" in inner
    for forbidden in ("service --debug", "gui --", "EVIOCGRAB", "/dev/uinput"):
        assert forbidden not in inner


def test_fail_propagates_with_no_verified_message(tmp_path: Path) -> None:
    for fail_at in (1, 2, 3):
        base = tmp_path / f"fail-{fail_at}"
        base.mkdir(parents=True)
        fake = portable_harness(base)
        if fail_at == 1:
            fake.configure(run_fail=1)
        else:
            fake.configure(run_fail_at=fail_at)
        repo = stage_repo_copy(base, name=f"repo-{fail_at}")
        result, commands = fake.run(script=repo / "buildpython/steps/appimage/portable-build.sh")
        assert result.returncode != 0, fail_at
        assert CANDIDATE not in result.stdout
        if fail_at == 1:
            assert len(docker_commands(commands, "run")) == 1
        elif fail_at == 2:
            assert _phases(commands) == ["build", "gate"]
        else:
            assert len(docker_commands(commands, "run")) == 3


def test_driver_reports_static_plus_smoke_without_pending() -> None:
    assert "static ABI" in CANDIDATE
    assert "userspace" in CANDIDATE.lower() or "smoke" in CANDIDATE.lower()
    assert "desktop/hardware" in CANDIDATE.lower()
    assert "pending" not in CANDIDATE.lower() or "still required" in CANDIDATE.lower()
    assert "static ABI" in read_text(SCRIPT)
    assert "desktop/hardware acceptance still required" in read_text(SCRIPT)


def test_inner_refuses_root_and_requires_toolchain() -> None:
    inner = read_text(INNER)
    assert "refusing to run" in inner
    assert "3.12.15" in inner
    assert "2.35" in inner
    assert "/usr/bin/unsquashfs" in inner
    assert "/usr/bin/readelf" in inner
    assert Path(read_text(SCRIPT).splitlines()[0]).name in ("bash",)
