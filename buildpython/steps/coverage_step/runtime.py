from __future__ import annotations

from pathlib import Path

from ...utils.subproc import RunResult, python_exe, run
from ..reports import buildlog_dir, write_json
from .constants import (
    _CAPTURE_MARKER_NAME,
    _DATA_FILE_NAME,
    _RAW_JSON_NAME,
    _SUMMARY_CSV_NAME,
    _SUMMARY_JSON_NAME,
    _SUMMARY_MD_NAME,
)


def pytest_runner_with_optional_coverage(*, root: Path) -> RunResult:
    if _coverage_tool_available():
        return _run_pytest_under_coverage(root=root, reason="pytest-step")

    _clear_coverage_artifacts()
    return run(
        [python_exe(), "-m", "pytest", *_safe_pytest_args(root)],
        cwd=str(root),
    )


def _run_pytest_under_coverage(*, root: Path, reason: str) -> RunResult:
    _clear_coverage_artifacts()
    result = run(
        [
            python_exe(),
            "-m",
            "coverage",
            "run",
            "--data-file",
            str(_coverage_data_file()),
            "--source=src/naga_control",
            "-m",
            "pytest",
            *_safe_pytest_args(root),
        ],
        cwd=str(root),
    )
    if result.exit_code == 0:
        write_json(
            _capture_marker_file(),
            {
                "reason": reason,
                "data_file": str(_coverage_data_file()),
            },
        )
    return result


def _coverage_tool_available() -> bool:
    try:
        import coverage  # noqa: F401
    except ImportError:
        return False
    return True


def _has_fresh_pytest_coverage_data() -> bool:
    return _coverage_data_file().exists() and _capture_marker_file().exists()


def _coverage_data_file() -> Path:
    return buildlog_dir() / _DATA_FILE_NAME


def _capture_marker_file() -> Path:
    return buildlog_dir() / _CAPTURE_MARKER_NAME


def _clear_coverage_artifacts() -> None:
    buildlog_dir().mkdir(parents=True, exist_ok=True)
    _clear_coverage_report_artifacts()
    for path in (
        _coverage_data_file(),
        _capture_marker_file(),
        buildlog_dir() / _RAW_JSON_NAME,
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            continue


def _safe_pytest_args(root: Path) -> list[str]:
    # CLI arguments follow both pyproject addopts and inherited PYTEST_ADDOPTS.
    # The plugin also fences marked tests independently of marker selection.
    return [
        "-q",
        "-p",
        "buildpython.steps.coverage_step.pytest_safety",
        "--ignore",
        str(root / "tests" / "hardware"),
        "-m",
        "not hardware",
    ]


def _clear_coverage_report_artifacts() -> None:
    for path in (
        buildlog_dir() / _SUMMARY_JSON_NAME,
        buildlog_dir() / _SUMMARY_MD_NAME,
        buildlog_dir() / _SUMMARY_CSV_NAME,
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
