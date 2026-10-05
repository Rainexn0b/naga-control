"""Naga policies and generic scanner contracts with filesystem-only fixtures."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
from pathlib import Path

import pytest

from buildpython.steps import loc_check_constants, step_loc_check
from buildpython.steps._architecture_validation_helpers import _scan_python_signals
from buildpython.steps._architecture_validation_integrity import validate_rule_corpora
from buildpython.steps.architecture_validation import load_architecture_rules, scan_architecture
from buildpython.steps.code_hygiene.baseline import _iter_python_files, _load_hygiene_baseline
from buildpython.steps.code_hygiene.detectors import _collect_all_issues
from buildpython.steps.code_hygiene.reporting import _write_reports
from buildpython.steps.code_hygiene.step import _resolved_category_thresholds
from buildpython.steps.code_markers.baseline import load_marker_baseline
from buildpython.steps.code_markers.scanning import scan_source_files
from buildpython.steps.coverage_step.payload import _load_coverage_baseline
from buildpython.steps.exception_transparency.baseline import iter_python_files, load_baseline
from buildpython.steps.file_size_analysis.constants import SIZE_SCAN_ROOTS, file_bucket
from buildpython.steps.file_size_analysis.scanning import collect_hotspots
from buildpython.steps.file_size_analysis.usage_graph import build_usage_graph, module_name_for_path
from buildpython.steps.reports import buildlog_dir

ROOT = Path(__file__).resolve().parents[1]


def test_architecture_rules_cover_the_actual_project() -> None:
    rules = load_architecture_rules(ROOT / "buildpython/config/architecture_rules.json")
    validate_rule_corpora(ROOT, rules)
    result = scan_architecture(ROOT, rules)
    assert result.scanned_files > 0
    assert not result.findings


@pytest.mark.parametrize("layer", ["domain", "ports", "application", "service", "adapters"])
def test_qt_is_forbidden_in_headless_layers(tmp_path: Path, layer: str) -> None:
    path = tmp_path / "src" / "naga_control" / layer / "sample.py"
    path.parent.mkdir(parents=True)
    path.write_text("from PySide6.QtCore import QObject\n", encoding="utf-8")
    rules = load_architecture_rules(ROOT / "buildpython/config/architecture_rules.json")
    assert any(
        f.rule_id == "headless-layers-no-qt" for f in scan_architecture(tmp_path, rules).findings
    )


def test_src_relative_imports_are_canonical() -> None:
    imports, _ = _scan_python_signals(
        "from .. import adapters\nfrom ..gui import app\n",
        relative_path="src/naga_control/service/runtime.py",
    )
    names = {item.module for item in imports}
    assert "naga_control.adapters" in names
    assert "naga_control.gui.app" in names
    assert all(not name.startswith("src.") for name in names)


@pytest.mark.parametrize("path", [Path("src/naga_control/sample.py"), Path("tests/test_sample.py")])
def test_400_lines_is_inclusive_in_all_scopes(path: Path) -> None:
    assert loc_check_constants.loc_bucket(400, rel_path=path) == "MONITOR"
    assert loc_check_constants.loc_bucket(401, rel_path=path) == "REFACTOR"
    assert file_bucket(400) == "REFACTOR"
    assert file_bucket(401) == "CRITICAL"


def test_line_limit_cannot_be_waived(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    path = tests / "test_large.py"
    path.write_text(
        "# @quality-exception loc-check: copied exception\n"
        "# @quality-exception file-size-analysis: copied exception\n" + "\n" * 399,
        encoding="utf-8",
    )
    monkeypatch.setattr(step_loc_check, "repo_root", lambda: tmp_path)
    assert step_loc_check.loc_check_runner().exit_code == 1
    rows, *_ = collect_hotspots(tmp_path, roots=SIZE_SCAN_ROOTS)
    assert rows[0]["lines"] == 401
    assert rows[0]["path"] == "tests/test_large.py"


def test_copied_baselines_are_empty_and_heuristics_are_informational() -> None:
    assert not _load_hygiene_baseline(ROOT).counts
    assert not _resolved_category_thresholds(ROOT)
    assert not load_baseline(ROOT).counts
    assert not load_marker_baseline(ROOT).counts
    assert _load_coverage_baseline(ROOT).minimum_total_percent is None
    payload = json.loads((ROOT / "buildpython/config/debt_baselines.json").read_text())
    assert not payload["flat_directories"]["allowed"]
    assert not payload["file_size_analysis"]["counts"]


def test_scanners_visit_all_naga_roots_without_importing(tmp_path: Path) -> None:
    files: list[Path] = []
    for name in SIZE_SCAN_ROOTS:
        path = tmp_path / name / "sample.py"
        path.parent.mkdir(parents=True)
        path.write_text("raise RuntimeError('must never be imported')\n", encoding="utf-8")
        files.append(path)
    assert set(_iter_python_files(tmp_path)) == set(files)
    assert set(iter_python_files(tmp_path)) == set(files)
    assert not _collect_all_issues(tmp_path)
    assert buildlog_dir(tmp_path) == tmp_path / "buildlog/naga-control"


def test_hygiene_reports_keep_counts_without_thresholds(tmp_path: Path) -> None:
    from collections import Counter

    _write_reports(tmp_path, [], Counter({"any_type_hint": 2}), Counter(), category_thresholds={})
    payload = json.loads((buildlog_dir(tmp_path) / "code-hygiene.json").read_text())
    assert payload["active_counts"] == {"any_type_hint": 2}
    assert "INFO" in (buildlog_dir(tmp_path) / "code-hygiene.md").read_text()


def test_marker_scan_counts_comments_and_docstrings_not_string_constants(tmp_path: Path) -> None:
    path = tmp_path / "sample.py"
    path.write_text(
        '"""REVIEW: a module-level note."""\n'
        'vocabulary = ["TODO", "FIXME", "HACK"]\n'
        "# TODO: an actual outstanding task\n"
        "# import removed_code\n",
        encoding="utf-8",
    )
    counts, _, hits, commented = scan_source_files([path], root=tmp_path)
    assert counts == {"REVIEW": 1, "TODO": 1}
    assert any("sample.py:3:" in hit for hit in hits)
    assert commented == ["sample.py:4: # import removed_code"]


def test_usage_graph_follows_src_imports_entrypoints_and_nested_launches(tmp_path: Path) -> None:
    package = tmp_path / "src/naga_control"
    package.mkdir(parents=True)
    sources = {
        "__init__.py": "",
        "cli.py": "from . import worker\n",
        "worker.py": "import importlib\nimportlib.import_module(f'{__package__}.dynamic')\n",
        "dynamic.py": "import subprocess\nsubprocess.run(['python', '-m', 'naga_control.leaf'])\n",
        "leaf.py": "",
        "unused.py": "",
    }
    for name, source in sources.items():
        (package / name).write_text(source, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project.scripts]\nnaga-control = 'naga_control.cli:main'\n", encoding="utf-8"
    )
    graph = build_usage_graph(tmp_path, roots=("src/naga_control",))
    assert module_name_for_path(tmp_path, package / "cli.py") == "naga_control.cli"
    assert {path.name for path in graph.reachable} == set(sources) - {"unused.py"}
    assert package / "cli.py" in graph.reverse_adjacency[package / "worker.py"]


def test_tests_are_usage_roots_not_unreferenced_candidates(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    path = tests / "test_sample.py"
    path.write_text("def test_fake():\n    assert True\n", encoding="utf-8")
    graph = build_usage_graph(tmp_path, roots=("tests",))
    assert path in graph.root_paths
    assert not collect_hotspots(tmp_path, roots=("tests",))[6]
