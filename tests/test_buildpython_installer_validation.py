"""Fake-only validation for new native installer and distro-report gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from buildpython.steps import step_repo_validation, step_shellcheck
from buildpython.steps.step_repo_validation import REQUIRED_FILES, repo_validation_runner
from buildpython.steps.step_shellcheck import shell_scripts, shellcheck_runner
from buildpython.utils.subproc import RunResult

NEW_SHELL_SCRIPTS = (
    "scripts/install_openrazer_native.sh",
    "scripts/distro_report.sh",
)

NATIVE_PAYLOAD_FILES = (
    "buildpython/openrazer_native/__init__.py",
    "buildpython/openrazer_native/__main__.py",
    "buildpython/openrazer_native/archive_audit.py",
    "buildpython/openrazer_native/build.py",
    "buildpython/openrazer_native/payload.py",
    "buildpython/openrazer_native/recipes.py",
    "buildpython/openrazer_native/rpm_audit.py",
    "buildpython/openrazer_native/validation.py",
    "buildpython/openrazer_native/README.md",
)

NEW_REQUIRED_FILES = (*NEW_SHELL_SCRIPTS, *NATIVE_PAYLOAD_FILES)

_FAKE_PYPROJECT = """\
[project]
name = "naga-control"
version = "0.5.0"
dependencies = ["evdev>=2,<3"]
[project.scripts]
naga-control-service = "naga_control.service.service_cli:main"
naga-control-capture = "naga_control.diagnostics.capture_cli:main"
naga-control-gui = "naga_control.gui.app:main"
naga-control-integration = "naga_control.integration_cli:main"
"""

_FAKE_ENTRY_MODULES = (
    "src/naga_control/service/service_cli.py",
    "src/naga_control/diagnostics/capture_cli.py",
    "src/naga_control/gui/app.py",
    "src/naga_control/integration_cli.py",
)


def _touch_required_files(root: Path) -> None:
    for relative in REQUIRED_FILES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")


def _write_fake_metadata(root: Path) -> None:
    (root / "pyproject.toml").write_text(_FAKE_PYPROJECT, encoding="utf-8")
    for relative in _FAKE_ENTRY_MODULES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def main():\n    return 0\n", encoding="utf-8")


def _make_complete_fake_repo(root: Path) -> None:
    _touch_required_files(root)
    _write_fake_metadata(root)


def _touch_shell_scripts(root: Path) -> None:
    for relative in shell_scripts():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("#!/usr/bin/env bash\n", encoding="utf-8")


def test_new_shell_scripts_listed_exactly_once() -> None:
    scripts = shell_scripts()
    for script in NEW_SHELL_SCRIPTS:
        assert scripts.count(script) == 1, f"missing or duplicated: {script}"


def test_new_files_required_exactly_once() -> None:
    for path in NEW_REQUIRED_FILES:
        assert REQUIRED_FILES.count(path) == 1, f"missing or duplicated: {path}"


def test_shellcheck_argv_lists_every_script_once_with_x(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _touch_shell_scripts(tmp_path)
    captured: list[list[str]] = []

    def fake_bin() -> str | None:
        return "/usr/bin/shellcheck"

    def fake_run(
        args: list[str],
        *,
        cwd: str,
        env_overrides: object | None = None,
    ) -> RunResult:
        assert cwd == str(tmp_path)
        assert env_overrides is None
        captured.append(list(args))
        return RunResult(command_str=" ".join(args), stdout="ok\n", stderr="", exit_code=0)

    monkeypatch.setattr(step_shellcheck, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(step_shellcheck, "shellcheck_bin", fake_bin)
    monkeypatch.setattr(step_shellcheck, "run", fake_run)
    result = shellcheck_runner()
    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(captured) == 1
    argv = captured[0]
    assert argv[0] == "/usr/bin/shellcheck"
    assert argv[1] == "-x"
    assert argv[2:] == [str(Path(path)) for path in shell_scripts()]
    for script in NEW_SHELL_SCRIPTS:
        assert argv.count(script) == 1
    assert len(set(argv[2:])) == len(argv[2:])


@pytest.mark.parametrize("missing", NEW_SHELL_SCRIPTS)
def test_missing_new_shell_script_fails_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    _touch_shell_scripts(tmp_path)
    (tmp_path / missing).unlink()

    def fake_bin() -> str | None:
        return "/usr/bin/shellcheck"

    def fail_run(
        args: list[str],
        *,
        cwd: str,
        env_overrides: object | None = None,
    ) -> RunResult:
        raise AssertionError("ShellCheck must not spawn when a required file is missing")

    monkeypatch.setattr(step_shellcheck, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(step_shellcheck, "shellcheck_bin", fake_bin)
    monkeypatch.setattr(step_shellcheck, "run", fail_run)
    result = shellcheck_runner()
    assert result.exit_code == 1
    assert "missing" in result.stdout.lower()
    assert missing in result.stdout


def test_repo_validation_succeeds_with_complete_fake_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_complete_fake_repo(tmp_path)
    monkeypatch.setattr(step_repo_validation, "repo_root", lambda: tmp_path)
    result = repo_validation_runner()
    assert result.exit_code == 0, result.stdout
    assert "OK" in result.stdout


@pytest.mark.parametrize("missing", NEW_REQUIRED_FILES)
def test_repo_validation_missing_each_new_file_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    _make_complete_fake_repo(tmp_path)
    (tmp_path / missing).unlink()
    monkeypatch.setattr(step_repo_validation, "repo_root", lambda: tmp_path)
    result = repo_validation_runner()
    assert result.exit_code == 1
    assert f"Missing required file: {missing}" in result.stdout
