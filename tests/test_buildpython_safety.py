"""Subprocess checks for build pytest safety, using synthetic tests only."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import os
from pathlib import Path

import pytest

from buildpython.steps.coverage_step import runtime, step
from buildpython.steps.coverage_step.pytest_safety import _deny_device_open
from buildpython.steps.reports import buildlog_dir
from buildpython.utils.subproc import RunResult

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("capture", [False, True])
@pytest.mark.parametrize("inherited", ["-m hardware", "-m 'hardware or integration'"])
def test_build_pytest_preserves_options_and_never_collects_hardware(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capture: bool, inherited: str
) -> None:
    if capture:
        pytest.importorskip("coverage")
    tests = tmp_path / "tests"
    hardware = tests / "hardware"
    hardware.mkdir(parents=True)
    (tmp_path / "src" / "naga_control").mkdir(parents=True)
    (tmp_path / "src" / "naga_control" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n"
        "addopts = \"-ra --strict-config --strict-markers -m 'not hardware'\"\n"
        "testpaths = ['tests']\n"
        "markers = ['hardware: requires hardware', 'integration: fake adapter test']\n",
        encoding="utf-8",
    )
    (hardware / "test_forbidden.py").write_text(
        "raise AssertionError('hardware directory was collected')\n", encoding="utf-8"
    )
    (tests / "test_fake.py").write_text(
        "import pytest\n"
        "@pytest.mark.integration\n"
        "def test_fake(pytestconfig):\n"
        "    assert pytestconfig.getoption('strict_markers')\n"
        "    assert pytestconfig.getoption('strict_config')\n"
        "    assert pytestconfig.getoption('markexpr') == 'not hardware'\n"
        "    with pytest.raises(PermissionError, match='Build tests'):\n"
        "        open('/dev/uinput', 'rb')\n"
        "@pytest.mark.hardware\n"
        "def test_marked_hardware():\n"
        "    raise AssertionError('marked hardware test ran')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTEST_ADDOPTS", inherited)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")]))
    monkeypatch.setattr(runtime, "buildlog_dir", lambda: buildlog_dir(tmp_path))
    monkeypatch.setattr(runtime, "_coverage_tool_available", lambda: capture)
    result = runtime.pytest_runner_with_optional_coverage(root=tmp_path)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
    assert "1 deselected" in result.stdout
    assert "addopts=" not in result.command_str
    assert runtime._has_fresh_pytest_coverage_data() is capture


def test_failed_capture_clears_old_data_and_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime, "buildlog_dir", lambda: tmp_path)
    for name in (
        runtime._DATA_FILE_NAME,
        runtime._CAPTURE_MARKER_NAME,
        runtime._RAW_JSON_NAME,
        runtime._SUMMARY_JSON_NAME,
        runtime._SUMMARY_MD_NAME,
        runtime._SUMMARY_CSV_NAME,
    ):
        (tmp_path / name).write_text("stale", encoding="utf-8")

    def fail_run(*args: object, **kwargs: object) -> RunResult:
        return RunResult("pytest", "", "", 1)

    monkeypatch.setattr(runtime, "run", fail_run)
    result = runtime._run_pytest_under_coverage(root=tmp_path, reason="test")
    assert result.exit_code == 1
    assert not runtime._has_fresh_pytest_coverage_data()
    assert not list(tmp_path.iterdir())


def test_missing_optional_coverage_is_explicitly_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(step, "_coverage_tool_available", lambda: False)
    result = step.coverage_runner()
    assert result.exit_code == 0
    assert result.skip_reason


@pytest.mark.parametrize("path", ["/dev/input/event123", "/dev/uinput", b"/dev/hidraw123"])
def test_device_open_guard_does_not_open_nodes(path: str | bytes) -> None:
    with pytest.raises(PermissionError, match="Build tests"):
        _deny_device_open("open", (path, "rb", 0))


def test_guard_denies_aliases_but_allows_ordinary_files(tmp_path: Path) -> None:
    alias = tmp_path / "fake-device"
    alias.symlink_to("/dev/uinput")
    with pytest.raises(PermissionError):
        _deny_device_open("open", (alias, "rb", 0))
    _deny_device_open("open", (tmp_path / "config.toml", "rb", 0))
    _deny_device_open("open", ("/dev/null", "rb", 0))
    _deny_device_open("open", (1, "rb", 0))
