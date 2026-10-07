"""Characterization for debt-index payload and Markdown bytes."""

from __future__ import annotations

import json
from pathlib import Path

from buildpython.core.debt_index import build_debt_index, write_debt_index


def _write_json(directory: Path, name: str, payload: object) -> None:
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def _write_full_fixture(directory: Path) -> None:
    _write_json(directory, "dead-code-vulture.json", {"count": 2, "actionable_count": 1})
    _write_json(
        directory,
        "code-hygiene.json",
        {
            "active_counts": {
                "silent_broad_except": 1,
                "logged_broad_except": 0,
                "fallback_broad_except": 2,
                "cleanup_hotspot": 0,
                "forbidden_getattr": 3,
            },
            "suppressed_counts": {"silent_broad_except": 1},
            "top_files_by_category": {},
        },
    )
    _write_json(
        directory,
        "exception-transparency.json",
        {
            "counts": {
                "naked_except": 1,
                "baseexception_catch": 0,
                "broad_except_total": 3,
                "broad_except_traceback_logged": 1,
                "broad_except_logged_no_traceback": 1,
                "broad_except_unlogged": 1,
            },
            "waived_total": 2,
            "annotation_inventory": {
                "total": 5,
                "by_subtree": [
                    {"subtree": "a", "count": 3},
                    {"subtree": "b", "count": 2},
                    "bad",
                    {"subtree": "c", "count": 9},
                ],
            },
            "top_files_by_category": {},
        },
    )
    _write_json(
        directory,
        "code-markers.json",
        {"marker_counts": {"TODO": 1}, "baseline": {"regressions": []}, "top_marker_files": {}},
    )
    _write_json(
        directory,
        "file-size-analysis.json",
        {
            "counts": {
                "file_lines": {"refactor": 1, "critical": 0, "severe": 0, "extreme": 0},
                "import_block_lines": {"warning": 1, "critical": 0, "severe": 0},
            },
            "files": [{"path": "a.py", "lines": 360}],
            "import_blocks": [],
            "flat_directories": [],
            "delegation_candidates": [],
            "middleman_modules": [],
            "unreferenced_files": [],
        },
    )
    _write_json(
        directory,
        "loc-check.json",
        {
            "threshold": 400,
            "thresholds": {},
            "count": 1,
            "counts": {"monitor": 1},
            "counts_by_scope": {
                "default": {"severe": 2, "total": 2},
                "tests": {"severe": 1, "total": 1},
            },
            "files": [{"path": "a.py", "lines": 410, "bucket": "REFACTOR"}],
        },
    )
    _write_json(
        directory,
        "architecture-validation.json",
        {"summary": {"findings": 1, "errors": 0, "warnings": 1}},
    )
    _write_json(
        directory,
        "coverage-summary.json",
        {
            "summary": {"total_percent": 94.29},
            "baseline": {
                "regressions": [
                    {"kind": "file", "target": f"f{i}.py", "current": 80.0, "baseline": 90.0}
                    for i in range(11)
                ]
            },
            "tracked_prefixes": [],
            "watch_files": [],
        },
    )


def test_full_payload_schema_reports_and_order(tmp_path: Path) -> None:
    _write_full_fixture(tmp_path)
    payload = build_debt_index(tmp_path)
    assert payload["summary"] == {
        "scope": "latest_available",
        "available_sections": [
            "architecture_validation",
            "code_hygiene",
            "code_markers",
            "coverage",
            "dead_code",
            "exception_transparency",
            "file_size",
            "loc_check",
        ],
        "report_count": 8,
    }
    assert list(payload["sections"].keys()) == [
        "dead_code",
        "code_hygiene",
        "exception_transparency",
        "code_markers",
        "file_size",
        "loc_check",
        "architecture_validation",
        "coverage",
    ]
    assert payload["reports"] == {
        "dead_code": str(tmp_path / "dead-code-vulture.md"),
        "code_hygiene": str(tmp_path / "code-hygiene.md"),
        "exception_transparency": str(tmp_path / "exception-transparency.md"),
        "code_markers": str(tmp_path / "code-markers.md"),
        "file_size": str(tmp_path / "file-size-analysis.md"),
        "loc_check": str(tmp_path / "loc-check.md"),
        "architecture_validation": str(tmp_path / "architecture-validation.md"),
        "coverage": str(tmp_path / "coverage-summary.md"),
    }
    assert payload["sections"]["dead_code"] == {"candidates": 2, "actionable": 1}
    assert payload["sections"]["code_markers"]["marker_counts"] == {"TODO": 1}
    assert payload["sections"]["code_hygiene"]["active_counts"]["forbidden_getattr"] == 3
    assert payload["sections"]["exception_transparency"]["waived_total"] == 2
    assert payload["sections"]["exception_transparency"]["annotation_inventory"]["total"] == 5
    assert payload["sections"]["architecture_validation"]["warnings"] == 1
    assert len(payload["sections"]["coverage"]["regressions"]) == 11


def test_full_markdown_exact_bytes(tmp_path: Path) -> None:
    _write_full_fixture(tmp_path)
    write_debt_index(tmp_path)
    raw_json = (tmp_path / "debt-index.json").read_bytes()
    assert raw_json.endswith(b"\n")
    assert json.loads(raw_json.decode("utf-8")) == build_debt_index(tmp_path)
    text = (tmp_path / "debt-index.md").read_text(encoding="utf-8")
    assert text.endswith("\n")
    expected = (
        "# Naga Control Debt Index\n\n"
        "- Scope: latest_available\n"
        "- Reports: 8\n"
        "- Sections: architecture_validation, code_hygiene, code_markers, coverage, "
        "dead_code, exception_transparency, file_size, loc_check\n\n"
        "## Reports\n\n"
        f"- architecture_validation: {tmp_path}/architecture-validation.md\n"
        f"- code_hygiene: {tmp_path}/code-hygiene.md\n"
        f"- code_markers: {tmp_path}/code-markers.md\n"
        f"- coverage: {tmp_path}/coverage-summary.md\n"
        f"- dead_code: {tmp_path}/dead-code-vulture.md\n"
        f"- exception_transparency: {tmp_path}/exception-transparency.md\n"
        f"- file_size: {tmp_path}/file-size-analysis.md\n"
        f"- loc_check: {tmp_path}/loc-check.md\n\n"
        "## Dead code\n\n- Candidates: 2\n- Actionable findings: 1\n\n"
        "## Code hygiene\n\n"
        "- silent_broad_except: 1 (suppressed 1)\n"
        "- logged_broad_except: 0\n"
        "- fallback_broad_except: 2\n"
        "- cleanup_hotspot: 0\n"
        "- forbidden_getattr: 3\n\n"
        "## Exception transparency\n\n"
        "- Waived via @quality-exception: 2\n"
        "- Runtime-boundary annotations: 5\n"
        "- Top annotation subtrees: a (3), b (2)\n"
        "- naked_except: 1\n"
        "- baseexception_catch: 0\n"
        "- broad_except_total: 3\n"
        "- broad_except_traceback_logged: 1\n"
        "- broad_except_logged_no_traceback: 1\n"
        "- broad_except_unlogged: 1\n\n"
        "## File size\n\n"
        "- File buckets: refactor=1, critical=0, severe=0, extreme=0\n"
        "- Import blocks: warning=1, critical=0, severe=0\n"
        "- Flat directories: 0\n"
        "- Delegation candidates: 0\n"
        "- Middle-man modules: 0\n"
        "- Unreferenced file candidates: 0\n"
        "- Largest file: a.py (360 lines)\n\n"
        "## LOC check\n\n"
        "- File buckets: monitor=1, severe=3 (default 2, tests 1)\n"
        "- Default-scope hits: 2\n"
        "- Test-scope hits: 1\n"
        "- Largest file: a.py (410 lines, REFACTOR)\n\n"
        "## Coverage\n\n- Total coverage: 94.29%\n- Regressions:\n"
        "  - file f0.py: 80.0 < 90.0\n"
        "  - file f1.py: 80.0 < 90.0\n"
        "  - file f2.py: 80.0 < 90.0\n"
        "  - file f3.py: 80.0 < 90.0\n"
        "  - file f4.py: 80.0 < 90.0\n"
        "  - file f5.py: 80.0 < 90.0\n"
        "  - file f6.py: 80.0 < 90.0\n"
        "  - file f7.py: 80.0 < 90.0\n"
        "  - file f8.py: 80.0 < 90.0\n"
        "  - file f9.py: 80.0 < 90.0\n\n"
        "## Architecture validation\n\n- Findings: 1\n- Errors: 0\n- Warnings: 1\n\n"
    )
    assert text == expected
    assert "## Code markers" not in text
    assert "f10.py" not in text
    assert "c (9)" not in text


def test_report_names_filters_stale_and_empty_scope(tmp_path: Path) -> None:
    _write_json(tmp_path, "code-hygiene.json", {"active_counts": {}, "suppressed_counts": {}})
    _write_json(tmp_path, "coverage-summary.json", {"summary": {"total_percent": 10.0}})
    _write_json(tmp_path, "dead-code-vulture.json", {"count": 1, "actionable_count": 0})
    filtered = build_debt_index(tmp_path, report_names=("code-hygiene.json",))
    assert filtered["summary"]["scope"] == "current_run"
    assert filtered["summary"]["available_sections"] == ["code_hygiene"]
    assert set(filtered["reports"].keys()) == {"code_hygiene"}
    write_debt_index(tmp_path, report_names=("code-hygiene.json",))
    filtered_text = (tmp_path / "debt-index.md").read_text(encoding="utf-8")
    assert "- Scope: current_run\n" in filtered_text
    assert "## Code hygiene\n" in filtered_text
    assert "## Coverage\n" not in filtered_text
    assert "## Dead code\n" not in filtered_text
    empty = build_debt_index(tmp_path, report_names=())
    assert empty["summary"]["scope"] == "current_run"
    assert empty["reports"] == {}
    assert empty["sections"] == {}
    write_debt_index(tmp_path, report_names=())
    assert (tmp_path / "debt-index.md").read_text(encoding="utf-8") == (
        "# Naga Control Debt Index\n\n- Scope: current_run\n- Reports: 0\n- Sections: none\n\n"
    )


def test_missing_malformed_nondict_and_oserror_tolerated(tmp_path: Path) -> None:
    assert build_debt_index(tmp_path)["sections"] == {}
    (tmp_path / "code-hygiene.json").write_text("{not json", encoding="utf-8")
    _write_json(tmp_path, "coverage-summary.json", [1, 2, 3])
    (tmp_path / "dead-code-vulture.json").mkdir()
    tolerated = build_debt_index(tmp_path)
    assert tolerated["sections"] == {}
    assert tolerated["summary"]["report_count"] == 0
    (tmp_path / "dead-code-vulture.json").rmdir()
    _write_json(tmp_path, "dead-code-vulture.json", {"count": 1, "actionable_count": 0})
    kept = build_debt_index(tmp_path)
    assert list(kept["sections"].keys()) == ["dead_code"]
    write_debt_index(tmp_path)
    assert (tmp_path / "debt-index.md").read_bytes().endswith(b"\n")


def test_coverage_waiting_and_default_branches_exact(tmp_path: Path) -> None:
    _write_json(
        tmp_path,
        "coverage-summary.json",
        {"summary": {"status": "missing_capture"}, "baseline": {"regressions": []}},
    )
    write_debt_index(tmp_path)
    waiting = (tmp_path / "debt-index.md").read_text(encoding="utf-8")
    expected_waiting = (
        "# Naga Control Debt Index\n\n"
        "- Scope: latest_available\n- Reports: 1\n- Sections: coverage\n\n"
        "## Reports\n\n"
        f"- coverage: {tmp_path}/coverage-summary.md\n\n"
        "## Coverage\n\n"
        "- Status: waiting for pytest coverage capture\n"
        "- Run: .venv/bin/python -m buildpython --run-steps=2,18\n\n"
    )
    assert waiting == expected_waiting
    _write_json(tmp_path, "coverage-summary.json", {"summary": {}, "baseline": {}})
    write_debt_index(tmp_path)
    default = (tmp_path / "debt-index.md").read_text(encoding="utf-8")
    assert "- Total coverage: 0.0%\n" in default
    assert "- Regressions: none\n" in default


def test_legacy_file_size_and_loc_severe_merge(tmp_path: Path) -> None:
    _write_json(
        tmp_path,
        "file-size-analysis.json",
        {
            "counts": {"refactor": 2, "critical": 1},
            "files": [],
            "import_blocks": [],
            "flat_directories": [],
            "delegation_candidates": [],
            "middleman_modules": [],
            "unreferenced_files": [],
        },
    )
    _write_json(
        tmp_path,
        "loc-check.json",
        {
            "threshold": 400,
            "count": 1,
            "counts": {"monitor": 1},
            "counts_by_scope": {
                "default": {"severe": 2, "total": 2},
                "tests": {"severe": 1, "total": 1},
            },
            "files": [],
        },
    )
    payload = build_debt_index(tmp_path)
    assert payload["sections"]["file_size"]["counts"] == {"refactor": 2, "critical": 1}
    write_debt_index(tmp_path)
    text = (tmp_path / "debt-index.md").read_text(encoding="utf-8")
    assert "- File buckets: refactor=2, critical=1, severe=0, extreme=0\n" in text
    assert "- Import blocks: warning=0, critical=0, severe=0\n" in text
    assert "- File buckets: monitor=1, severe=3 (default 2, tests 1)\n" in text
    assert "- Default-scope hits: 2\n" in text
    assert "- Test-scope hits: 1\n" in text
