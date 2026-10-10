"""DEBT-10 wave-B coverage ratchet: per-file floor gating with synthetic payloads."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from buildpython.core.cli import _select_steps
from buildpython.core.profiles import PROFILES
from buildpython.steps.coverage_step import runtime as coverage_runtime
from buildpython.steps.coverage_step import step as coverage_step
from buildpython.steps.coverage_step.models import CoverageBaseline
from buildpython.steps.coverage_step.payload import (
    _load_coverage_baseline,
    build_coverage_report,
)
from buildpython.utils.subproc import RunResult

CRITICAL = "synthetic/critical.py"
HELPER = "synthetic/helper.py"
FLOOR = 95.0


def _file_entry(covered: int, statements: int) -> dict[str, Any]:
    return {"summary": {"covered_lines": covered, "num_statements": statements}}


def _payload(
    entries: dict[str, tuple[int, int]], total_covered: int, total_statements: int
) -> dict[str, Any]:
    return {
        "totals": {"covered_lines": total_covered, "num_statements": total_statements},
        "files": {
            path: _file_entry(covered, statements)
            for path, (covered, statements) in entries.items()
        },
    }


def _baseline(target: str = CRITICAL, floor: float = FLOOR) -> CoverageBaseline:
    return CoverageBaseline(
        minimum_total_percent=None,
        tracked_prefixes={},
        watch_files=(),
        per_file_minimums={target: floor},
    )


def _row(report: dict[str, Any], target: str) -> dict[str, Any]:
    for row in report["per_file_minimums"]:
        if row["path"] == target:
            return row
    raise AssertionError(f"missing per-file row for {target}")


def _write_baseline(
    tmp_root: Path, coverage: dict[str, Any] | None, extra: dict[str, Any] | None = None
) -> None:
    payload: dict[str, Any] = {}
    if coverage is not None:
        payload["coverage"] = coverage
    if extra:
        payload.update(extra)
    config_dir = tmp_root / "buildpython" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "debt_baselines.json").write_text(json.dumps(payload), encoding="utf-8")


def _fake_json_run(payload: dict[str, Any]) -> Callable[..., RunResult]:
    def _run(args: list[str], *, cwd: str, **kwargs: Any) -> RunResult:
        raw = Path(args[args.index("-o") + 1]) if "-o" in args else Path(cwd) / "raw.json"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(json.dumps(payload), encoding="utf-8")
        return RunResult(command_str="fake coverage json", stdout="", stderr="", exit_code=0)

    return _run


def _patch_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_root: Path,
    report_dir: Path,
    baseline: CoverageBaseline,
    payload: dict[str, Any],
) -> None:
    monkeypatch.setattr(coverage_step, "repo_root", lambda: tmp_root)
    monkeypatch.setattr(coverage_step, "_coverage_tool_available", lambda: True)
    monkeypatch.setattr(coverage_step, "_has_fresh_pytest_coverage_data", lambda: True)
    monkeypatch.setattr(coverage_step, "_coverage_data_file", lambda: tmp_root / "dummy")

    def _baseline_for(_root: Path) -> CoverageBaseline:
        return baseline

    monkeypatch.setattr(coverage_step, "_load_coverage_baseline", _baseline_for)
    monkeypatch.setattr(coverage_step, "run", _fake_json_run(payload))


@pytest.fixture(autouse=True)
def _isolate_coverage_report_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    report_dir = tmp_path / "reports"

    def _report_dir(_root: Path | None = None) -> Path:
        return report_dir

    monkeypatch.setattr(coverage_step, "buildlog_dir", _report_dir)
    monkeypatch.setattr(coverage_runtime, "buildlog_dir", _report_dir)
    yield report_dir


def test_missing_always_fails_despite_excellent_total() -> None:
    report = build_coverage_report(_payload({HELPER: (100, 100)}, 100, 100), _baseline())
    assert report["summary"]["total_percent"] == 100.0
    assert report["summary"]["files"] == 1
    regressions = report["baseline"]["regressions"]
    assert len(regressions) == 1
    reg = regressions[0]
    assert reg["kind"] == "per_file_missing"
    assert reg["target"] == CRITICAL
    assert reg["current"] == 0.0
    assert reg["baseline"] == FLOOR
    row = _row(report, CRITICAL)
    assert row["status"] == "missing"
    assert row["percent"] is None
    assert row["covered_lines"] == 0
    assert row["num_statements"] == 0


def test_below_floor_fails_without_masking() -> None:
    payload = _payload({CRITICAL: (94, 100), HELPER: (100, 100)}, 194, 200)
    report = build_coverage_report(payload, _baseline())
    assert report["summary"]["total_percent"] == 97.0
    regressions = report["baseline"]["regressions"]
    assert len(regressions) == 1
    reg = regressions[0]
    assert reg["kind"] == "per_file"
    assert reg["target"] == CRITICAL
    assert reg["current"] == 94.0
    assert reg["baseline"] == FLOOR
    row = _row(report, CRITICAL)
    assert row["status"] == "fail"
    assert row["percent"] == 94.0
    assert row["covered_lines"] == 94
    assert row["num_statements"] == 100


@pytest.mark.parametrize(
    ("covered", "statements", "expected"),
    [(95, 100, 95.0), (96, 100, 96.0), (190, 200, 95.0)],
)
def test_at_or_above_floor_passes(covered: int, statements: int, expected: float) -> None:
    report = build_coverage_report(
        _payload({CRITICAL: (covered, statements)}, covered, statements), _baseline()
    )
    assert report["baseline"]["regressions"] == []
    row = _row(report, CRITICAL)
    assert row["status"] == "ok"
    assert row["percent"] == expected
    assert row["covered_lines"] == covered
    assert row["num_statements"] == statements


def test_statement_precision_beats_integer_rounding() -> None:
    report = build_coverage_report(_payload({CRITICAL: (949, 1000)}, 949, 1000), _baseline())
    assert report["summary"]["total_percent"] == 94.9
    regressions = report["baseline"]["regressions"]
    assert len(regressions) == 1
    assert regressions[0]["kind"] == "per_file"
    assert regressions[0]["current"] == 94.9
    row = _row(report, CRITICAL)
    assert row["covered_lines"] == 949
    assert row["num_statements"] == 1000
    assert row["percent"] == 94.9
    assert round(row["percent"]) == 95
    assert row["status"] == "fail"


def test_loader_surfaces_valid_and_filters_invalid(tmp_path: Path) -> None:
    _write_baseline(
        tmp_path,
        {
            "per_file_minimums": {CRITICAL: 95.0, "bad.py": "95", "other.py": None},
            "tracked_prefixes": {"src/": 90, "bad": "high"},
            "watch_files": ["a.py", 123],
            "minimum_total_percent": "95",
            "minimum_watch_file_percent": 80,
        },
        extra={"generic_policy": {"x": 1}},
    )
    baseline = _load_coverage_baseline(tmp_path)
    assert baseline.per_file_minimums == {CRITICAL: 95.0}
    assert baseline.tracked_prefixes == {"src/": 90}
    assert baseline.watch_files == ("a.py",)
    assert baseline.minimum_total_percent is None
    assert baseline.minimum_watch_file_percent == 80.0


def test_loader_defaults_for_missing_malformed_and_legacy(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _load_coverage_baseline(empty).per_file_minimums == {}
    assert _load_coverage_baseline(empty).minimum_total_percent is None
    bad = tmp_path / "bad"
    (bad / "buildpython" / "config").mkdir(parents=True)
    (bad / "buildpython" / "config" / "debt_baselines.json").write_text(
        "{not json", encoding="utf-8"
    )
    assert _load_coverage_baseline(bad).per_file_minimums == {}
    legacy = tmp_path / "legacy"
    _write_baseline(legacy, None, extra={"code_hygiene": {"counts": {}}})
    assert _load_coverage_baseline(legacy).per_file_minimums == {}
    assert _load_coverage_baseline(legacy).tracked_prefixes == {}


def test_runner_reports_missing_with_exit1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = _baseline()
    report_dir = tmp_path / "reports"
    report_dir.mkdir(exist_ok=True)
    _patch_runner(
        monkeypatch, tmp_path, report_dir, baseline, _payload({HELPER: (100, 100)}, 100, 100)
    )
    result = coverage_step.coverage_runner()
    assert result.exit_code == 1
    assert "not present in coverage payload" in result.stdout
    assert "per_file_missing" in result.stdout
    assert CRITICAL in result.stdout
    assert str(report_dir) in result.stdout
    data = json.loads((report_dir / "coverage-summary.json").read_text(encoding="utf-8"))
    assert len(data["baseline"]["regressions"]) == 1
    reg = data["baseline"]["regressions"][0]
    assert reg["kind"] == "per_file_missing"
    assert reg["target"] == CRITICAL
    assert reg["current"] == 0.0
    assert reg["baseline"] == FLOOR
    assert (report_dir / "coverage-summary.md").exists()


def test_runner_passes_at_floor_with_exit0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = _baseline()
    report_dir = tmp_path / "reports"
    report_dir.mkdir(exist_ok=True)
    _patch_runner(
        monkeypatch, tmp_path, report_dir, baseline, _payload({CRITICAL: (95, 100)}, 95, 100)
    )
    result = coverage_step.coverage_runner()
    assert result.exit_code == 0
    assert "Coverage regressions: none" in result.stdout
    assert "95.00%" in result.stdout
    data = json.loads((report_dir / "coverage-summary.json").read_text(encoding="utf-8"))
    assert data["baseline"]["regressions"] == []
    rows = {row["path"]: row for row in data["per_file_minimums"]}
    assert rows[CRITICAL]["status"] == "ok"
    assert rows[CRITICAL]["percent"] == 95.0


def test_runner_missing_capture_is_exit1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(exist_ok=True)
    (report_dir / "coverage-summary.json").write_text('{"stale": true}', encoding="utf-8")
    (report_dir / "coverage-summary.md").write_text("stale", encoding="utf-8")
    (report_dir / "coverage-summary.csv").write_text("stale", encoding="utf-8")
    sentinel = tmp_path / "outside" / "sentinel.txt"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("keep", encoding="utf-8")
    original_unlink = Path.unlink
    unlinked: list[Path] = []

    def _guarded_unlink(self: Path, missing_ok: bool = False) -> None:
        unlinked.append(self)
        assert self.is_relative_to(tmp_path), f"unlink outside tmp: {self}"
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", _guarded_unlink)
    monkeypatch.setattr(coverage_step, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(coverage_step, "_coverage_tool_available", lambda: True)
    monkeypatch.setattr(coverage_step, "_has_fresh_pytest_coverage_data", lambda: False)
    result = coverage_step.coverage_runner()
    assert result.exit_code == 1
    assert "No fresh pytest coverage capture" in result.stdout
    assert not result.skip_reason
    data = json.loads((report_dir / "coverage-summary.json").read_text(encoding="utf-8"))
    assert data["summary"]["status"] == "missing_capture"
    assert "stale" not in (report_dir / "coverage-summary.md").read_text(encoding="utf-8")
    csv_text = (report_dir / "coverage-summary.csv").read_text(encoding="utf-8")
    assert "stale" not in csv_text
    assert "path,percent" in csv_text
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert unlinked
    assert all(path.is_relative_to(report_dir) for path in unlinked)


def test_runner_reports_below_floor_with_exit1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = _baseline()
    report_dir = tmp_path / "reports"
    report_dir.mkdir(exist_ok=True)
    payload = _payload({CRITICAL: (94, 100), HELPER: (100, 100)}, 194, 200)
    _patch_runner(monkeypatch, tmp_path, report_dir, baseline, payload)
    result = coverage_step.coverage_runner()
    assert result.exit_code == 1
    assert "per_file" in result.stdout
    assert "94.00%" in result.stdout
    data = json.loads((report_dir / "coverage-summary.json").read_text(encoding="utf-8"))
    assert data["summary"]["total_percent"] == 97.0
    assert len(data["baseline"]["regressions"]) == 1
    reg = data["baseline"]["regressions"][0]
    assert reg["kind"] == "per_file"
    assert reg["target"] == CRITICAL
    assert reg["current"] == 94.0
    assert reg["baseline"] == FLOOR


def test_runner_missing_tools_skips_without_enforcing_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(coverage_step, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(coverage_step, "_coverage_tool_available", lambda: False)

    def _baseline_for(_root: Path) -> CoverageBaseline:
        return _baseline()

    monkeypatch.setattr(coverage_step, "_load_coverage_baseline", _baseline_for)
    result = coverage_step.coverage_runner()
    assert result.exit_code == 0
    assert result.skip_reason
    assert "not installed" in result.stdout
    assert not (report_dir / "coverage-summary.json").exists()


def test_debt_and_default_selections_do_not_enforce_coverage() -> None:
    assert "Coverage" not in PROFILES["debt"].include_steps
    assert "Pytest" not in PROFILES["debt"].include_steps
    assert "Coverage" not in PROFILES["full"].include_steps
    assert all(step.name != "Coverage" for step in _select_steps(None, None, "debt"))
    assert all(step.name != "Coverage" for step in _select_steps(None, None, None))
    ordered = _select_steps(["Pytest", "Coverage"], None, None)
    assert [step.name for step in ordered] == ["Pytest", "Coverage"]
    assert ordered[0].number < ordered[1].number
