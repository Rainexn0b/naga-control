"""DEBT-10 wave-A hygiene ratchet: narrow silent-broad-except gate.

Only ``silent_broad_except`` (bare ``pass``/bare ``return`` under a broad
handler) is budgeted at zero. Logged, fallback, propagation, and
cleanup/rethrow boundaries stay informational under this ratchet.

Scanner limit (see parent ``docs/debt-exception-inventory.md``): the hygiene
check is a local AST heuristic. It does not follow failure propagation through
futures or GUI model updates, so an unlogged local finding is not proof of a
silent runtime failure. No new model protocol is invented here.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
from pathlib import Path

import pytest

from buildpython.core.profiles import PROFILES
from buildpython.steps.code_hygiene import step as hygiene_step
from buildpython.steps.code_hygiene.ast_scanners import _detect_broad_exception_patterns
from buildpython.utils.subproc import RunResult

SILENT_EXCEPTION = "try:\n    operation()\nexcept Exception:\n    pass\n"
SILENT_BARE = "try:\n    operation()\nexcept:\n    pass\n"
SILENT_BASE = "try:\n    operation()\nexcept BaseException:\n    pass\n"
CLEANUP_BASE = "try:\n    operation()\nexcept BaseException:\n    release()\n    raise\n"
CLEANUP_BROAD = "try:\n    operation()\nexcept Exception:\n    cleanup()\n    raise\n"
LOGGED_BODY = (
    "import logging\nlogger = logging.getLogger(__name__)\n"
    "def example():\n    try:\n        operation()\n"
    "    except Exception:\n        logger.error('failed')\n        return 1\n"
)
FALLBACK_BODY = (
    "def example():\n    try:\n        operation()\n    except Exception:\n        return 1\n"
)


def _write_tmp_repo(tmp_path: Path, hygiene_section: dict[str, object]) -> Path:
    payload: dict[str, object] = {
        "code_hygiene": hygiene_section,
        "coverage": {
            "minimum_total_percent": None,
            "tracked_prefixes": {},
            "minimum_watch_file_percent": 0,
            "per_file_minimums": {},
            "watch_files": [],
        },
        "exception_transparency": {"counts": {}, "gated_categories": []},
        "file_size_analysis": {"counts": {}},
        "flat_directories": {"allowed": []},
        "code_markers": {"marker_counts": {}, "gated_markers": []},
    }
    config = tmp_path / "buildpython" / "config"
    config.mkdir(parents=True)
    (config / "debt_baselines.json").write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


def _write_source(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / "src" / "naga_control" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _run_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RunResult:
    monkeypatch.setattr(hygiene_step, "repo_root", lambda: tmp_path)
    return hygiene_step.code_hygiene_runner()


def test_empty_baseline_is_informational_not_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_tmp_repo(tmp_path, {"counts": {}, "gated_categories": [], "path_budgets": {}})
    _write_source(tmp_path, "silent_mod.py", SILENT_EXCEPTION)
    result = _run_runner(tmp_path, monkeypatch)
    assert result.exit_code == 0
    assert "silent_broad_except" in result.stdout
    assert "INFO" in result.stdout
    assert "FAIL" not in result.stdout


def test_gated_silent_pass_fails_with_actionable_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_tmp_repo(
        tmp_path,
        {
            "counts": {"silent_broad_except": 0},
            "gated_categories": ["silent_broad_except"],
            "path_budgets": {},
        },
    )
    _write_source(tmp_path, "silent_mod.py", SILENT_EXCEPTION)
    result = _run_runner(tmp_path, monkeypatch)
    assert result.exit_code == 1
    assert "silent_broad_except" in result.stdout
    assert "FAIL" in result.stdout


@pytest.mark.parametrize("body", [SILENT_BARE, SILENT_BASE])
def test_bare_and_baseexception_pass_share_silent_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    _write_tmp_repo(
        tmp_path,
        {
            "counts": {"silent_broad_except": 0},
            "gated_categories": ["silent_broad_except"],
            "path_budgets": {},
        },
    )
    path = _write_source(tmp_path, "silent_mod.py", body)
    issues = _detect_broad_exception_patterns(path, tmp_path)
    assert [issue.category for issue in issues] == ["silent_broad_except"]
    result = _run_runner(tmp_path, monkeypatch)
    assert result.exit_code == 1


def test_exact_silent_classification_covers_pass_and_bare_return(tmp_path: Path) -> None:
    returning = "try:\n    operation()\nexcept Exception:\n    return\n"
    for body in (SILENT_EXCEPTION, returning):
        path = _write_source(tmp_path, "probe.py", body)
        issues = _detect_broad_exception_patterns(path, tmp_path)
        assert [issue.category for issue in issues] == ["silent_broad_except"]
        path.unlink()
    logged = _write_source(tmp_path, "logged.py", LOGGED_BODY)
    assert [issue.category for issue in _detect_broad_exception_patterns(logged, tmp_path)] == [
        "logged_broad_except"
    ]
    fallback = _write_source(tmp_path, "fallback.py", FALLBACK_BODY)
    assert [issue.category for issue in _detect_broad_exception_patterns(fallback, tmp_path)] == [
        "fallback_broad_except"
    ]


@pytest.mark.parametrize("body", [CLEANUP_BASE, CLEANUP_BROAD])
def test_cleanup_rethrow_does_not_trigger_narrow_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    _write_tmp_repo(
        tmp_path,
        {
            "counts": {"silent_broad_except": 0},
            "gated_categories": ["silent_broad_except"],
            "path_budgets": {},
        },
    )
    path = _write_source(tmp_path, "cleanup_mod.py", body)
    assert _detect_broad_exception_patterns(path, tmp_path) == []
    result = _run_runner(tmp_path, monkeypatch)
    assert result.exit_code == 0


@pytest.mark.parametrize(
    ("name", "body", "category"),
    [
        ("logged_mod.py", LOGGED_BODY, "logged_broad_except"),
        ("fallback_mod.py", FALLBACK_BODY, "fallback_broad_except"),
    ],
)
def test_logged_and_fallback_stay_allowed_under_narrow_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, body: str, category: str
) -> None:
    _write_tmp_repo(
        tmp_path,
        {
            "counts": {"silent_broad_except": 0},
            "gated_categories": ["silent_broad_except"],
            "path_budgets": {},
        },
    )
    path = _write_source(tmp_path, name, body)
    assert [issue.category for issue in _detect_broad_exception_patterns(path, tmp_path)] == [
        category
    ]
    result = _run_runner(tmp_path, monkeypatch)
    assert result.exit_code == 0
    assert category in result.stdout
    assert "silent_broad_except" not in result.stdout or "FAIL" not in result.stdout


def test_relevant_profiles_cover_hygiene_without_changing_default_full() -> None:
    assert PROFILES["debt"].include_steps == [
        "Import Scan",
        "Code Markers",
        "File Size",
        "LOC Check",
        "Code Hygiene",
        "Exception Transparency",
        "Dead Code",
    ]
    assert PROFILES["full"].include_steps == [
        "Compile",
        "Ruff",
        "Ruff Format",
        "Type Check",
        "Pytest",
        "Import Validation",
        "LOC Check",
        "Repo Validation",
        "Architecture Validation",
    ]
    assert "Code Hygiene" not in PROFILES["full"].include_steps
    assert "Coverage" not in PROFILES["full"].include_steps
