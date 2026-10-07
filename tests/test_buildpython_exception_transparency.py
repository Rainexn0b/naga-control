"""Synthetic-source regressions for the heuristic exception-transparency scan."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

from buildpython.steps.exception_transparency.reporting import build_stdout, write_reports
from buildpython.steps.exception_transparency.scanner import (
    count_broad_waivers,
    has_quality_exception_waiver,
    scan_annotation_inventory,
    scan_python_source,
)
from buildpython.steps.quality_exceptions import python_comments
from buildpython.steps.reports import buildlog_dir

TAG = "@quality-exception exception-transparency: reviewed boundary policy"
REL_PATH = "tests/synthetic.py"


def _source(declarations: str, caught: str, body: str = "pass") -> str:
    handler = f"except {caught}:" if caught else "except:"
    return (
        f"{declarations}\ndef example():\n    try:\n        operation()\n    {handler}\n"
        + "\n".join(f"        {line}" for line in body.split("\n"))
        + "\n"
    )


@pytest.mark.parametrize(
    ("declarations", "caught", "baseexception"),
    [
        ("", "Exception", False),
        ("", "BaseException", True),
        ("import builtins", "builtins.Exception", False),
        ("import builtins", "builtins.BaseException", True),
        ("import builtins as core", "core.Exception", False),
        ("import builtins as core", "core.BaseException", True),
        ("from builtins import Exception as Failure", "Failure", False),
        ("from builtins import BaseException as Failure", "Failure", True),
        ("import builtins as core\nbuiltins = object()", "core.Exception", False),
        ("import builtins as core\nbuiltins = object()", "core.BaseException", True),
        ("from builtins import Exception as Failure\nException = ValueError", "Failure", False),
        (
            "from builtins import BaseException as Failure\nBaseException = ValueError",
            "Failure",
            True,
        ),
        ("Failure = Exception", "Failure", False),
        ("Failure: object = BaseException", "Failure", True),
        ("Failure = Exception\nBoundary = Failure", "Boundary", False),
        ("Failures = (OSError,) + (Exception,)", "Failures", False),
        ("Failures = (BaseException,) + (OSError,)", "Failures", True),
        ("import builtins\nFailure = builtins.Exception", "Failure", False),
        ("import builtins as core\nFailure = core.BaseException", "Failure", True),
        (
            "from builtins import Exception as Failure\nFailures = (OSError,) + (Failure,)",
            "Failures",
            False,
        ),
        ("import pytest", "(pytest.skip.Exception, Exception)", False),
        ("import library", "(library.Exception, BaseException)", True),
    ],
)
def test_builtin_broad_handlers_and_aliases_remain_visible(
    declarations: str, caught: str, baseexception: bool
) -> None:
    findings = scan_python_source(_source(declarations, caught), rel_path=REL_PATH)
    expected = ["broad_except_total", "broad_except_unlogged"]
    if baseexception:
        expected.insert(0, "baseexception_catch")
    assert [finding.category for finding in findings] == expected
    assert all(finding.path == REL_PATH for finding in findings)


@pytest.mark.parametrize(
    ("declarations", "caught"),
    [
        ("import pytest", "pytest.skip.Exception"),
        ("import library", "library.Exception"),
        ("import library", "library.BaseException"),
        ("import library as lib", "lib.Exception"),
        ("import pytest\nFailure = pytest.skip.Exception", "Failure"),
        ("import library\nFailure: object = library.Exception", "Failure"),
        ("import library\nFailure = library.BaseException\nBoundary = Failure", "Boundary"),
        ("import pytest\nFailures = (pytest.skip.Exception, OSError)", "Failures"),
        ("import library\nFailures = (OSError,) + (library.Exception,)", "Failures"),
        ("import library\nFailure = library.Exception\nFailures = (Failure,)", "Failures"),
        ("from .builtins import Exception as Failure", "Failure"),
        ("from .builtins import BaseException as Failure", "Failure"),
        ("from ..builtins import Exception as Failure", "Failure"),
        ("from ..builtins import BaseException as Failure", "Failure"),
        ("", "OSError"),
        ("", "(ValueError, RuntimeError)"),
    ],
)
def test_foreign_qualified_exceptions_are_not_builtin_broad_catches(
    declarations: str, caught: str
) -> None:
    assert scan_python_source(_source(declarations, caught), rel_path=REL_PATH) == []


@pytest.mark.parametrize(
    "body",
    [
        "future.set_exception(error)",
        "completion.set_exception(error)",
        "return FailureState(error=str(error))",
        "state.failure = str(error)\nreturn state",
        "pytest.fail(str(error))",
        "dialog.show_error(str(error))",
        "window.failure.emit(str(error))",
    ],
)
def test_nonlocal_outcomes_are_not_guessed_or_automatically_waived(body: str) -> None:
    findings = scan_python_source(_source("", "Exception as error", body), rel_path=REL_PATH)
    assert [finding.category for finding in findings] == [
        "broad_except_total",
        "broad_except_unlogged",
    ]
    message = findings[-1].message.lower()
    assert "no recognized local diagnostic" in message
    assert "suppresses failure" not in message
    assert "silent" not in message
    assert "without a diagnostic footprint" not in message


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("raise", ["broad_except_total"]),
        ("raise RuntimeError('failed') from error", ["broad_except_total"]),
        ("logger.exception('failed')", ["broad_except_total", "broad_except_traceback_logged"]),
        (
            "logger.error('failed', exc_info=True)",
            ["broad_except_total", "broad_except_traceback_logged"],
        ),
        ("print(error)", ["broad_except_total", "broad_except_logged_no_traceback"]),
    ],
)
def test_existing_reraise_and_local_diagnostic_classifications(
    body: str, expected: list[str]
) -> None:
    findings = scan_python_source(_source("", "Exception as error", body), rel_path=REL_PATH)
    assert [finding.category for finding in findings] == expected


def test_baseexception_cleanup_is_a_review_candidate_not_a_blanket_ban() -> None:
    findings = scan_python_source(
        _source("", "BaseException", "release_grabs()\nraise"), rel_path=REL_PATH
    )
    assert [finding.category for finding in findings] == [
        "baseexception_catch",
        "broad_except_total",
    ]
    message = findings[0].message.lower()
    assert "cleanup" in message
    assert "too broad for normal control flow" not in message


@pytest.mark.parametrize(
    "template",
    [
        '"""Example:\n# {tag}\n"""\n',
        "fixture = '''Example:\n# {tag}\n'''\n",
        'fixture = "# {tag}\\n"\n',
        'fixture = "escaped \\"# {tag}\\n"\n',
        'fixture = f"# {tag}"\n',
        'def example():\n    """\n    # {tag}\n    """\n',
    ],
)
def test_exception_annotation_inventory_rejects_fixture_text(template: str) -> None:
    source = template.format(tag=TAG)
    ast.parse(source)
    assert python_comments(source) == {}
    inventory = scan_annotation_inventory(source, rel_path=REL_PATH)
    assert inventory.total == 0
    assert inventory.by_subtree == ()


@pytest.mark.parametrize(
    "handler_source",
    [
        f"# {TAG}\nexcept Exception:\n    pass\n",
        f"# {TAG}\n# Additional boundary context.\nexcept Exception:\n    pass\n",
        f"except Exception:  # {TAG}\n    pass\n",
        f'except Exception: value = "#"; pass  # {TAG}\n',
    ],
)
def test_real_preceding_and_inline_comments_waive_handlers(handler_source: str) -> None:
    source = "try:\n    operation()\n" + handler_source
    handler = next(
        node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ExceptHandler)
    )
    assert has_quality_exception_waiver(source.split("\n"), handler)
    inventory = scan_annotation_inventory(source, rel_path=REL_PATH)
    assert inventory.total == 1
    assert inventory.by_subtree == (("tests", 1),)
    assert scan_python_source(source, rel_path=REL_PATH) == []


@pytest.mark.parametrize(
    "handler_source",
    [
        f'except Exception: value = "# {TAG}"; pass\n',
        f'except Exception: value = "# {TAG}"; pass  # ordinary comment\n',
        f'except Exception: value = "# {TAG}"; pass  # @quality-exception loc-check: other\n',
    ],
)
def test_hash_inside_handler_string_cannot_create_a_waiver(handler_source: str) -> None:
    source = "try:\n    operation()\n" + handler_source
    handler = next(
        node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ExceptHandler)
    )
    assert not has_quality_exception_waiver(source.split("\n"), handler)
    assert scan_annotation_inventory(source, rel_path=REL_PATH).total == 0
    findings = scan_python_source(source, rel_path=REL_PATH)
    assert [finding.category for finding in findings] == [
        "broad_except_total",
        "broad_except_unlogged",
    ]


def test_real_comment_after_fake_tag_supplies_the_actual_waiver() -> None:
    source = f'try:\n    operation()\nexcept Exception: value = "# {TAG}"; pass  # {TAG}\n'
    assert python_comments(source) == {3: TAG}
    assert scan_annotation_inventory(source, rel_path=REL_PATH).total == 1
    assert scan_python_source(source, rel_path=REL_PATH) == []


@pytest.mark.parametrize("waived", [False, True])
def test_formfeed_in_string_preserves_physical_handler_lines(tmp_path: Path, waived: bool) -> None:
    comment = f"# {TAG}\n" if waived else "# ordinary comment\n"
    source = (
        f'fixture = "# {TAG}\f copied fixture"\n'
        "try:\n    operation()\n" + comment + "except Exception:\n    pass\n"
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    path = tests / "synthetic.py"
    path.write_text(source, encoding="utf-8", newline="\n")
    source = path.read_text(encoding="utf-8")
    assert "\f" in source
    handler = next(
        node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ExceptHandler)
    )
    assert handler.lineno == 5
    assert python_comments(source) == {4: TAG if waived else "ordinary comment"}
    assert has_quality_exception_waiver(source.split("\n"), handler) is waived
    inventory = scan_annotation_inventory(source, rel_path=REL_PATH)
    assert inventory.total == int(waived)
    assert inventory.by_subtree == ((("tests", 1),) if waived else ())
    findings = scan_python_source(source, rel_path=REL_PATH)
    if waived:
        assert findings == []
    else:
        assert [finding.category for finding in findings] == [
            "broad_except_total",
            "broad_except_unlogged",
        ]
        assert all(
            finding.line == 5 and finding.snippet == "except Exception:" for finding in findings
        )
    assert count_broad_waivers(tmp_path) == int(waived)


def test_fixture_tree_counts_only_real_builtin_exception_waivers(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    cases = [
        ("", "Exception", 1),
        ("import builtins", "builtins.Exception", 1),
        ("import builtins as core", "core.Exception", 1),
        ("from builtins import Exception as Failure", "Failure", 1),
        ("import builtins as core\nbuiltins = object()", "core.Exception", 1),
        ("import builtins as core\nbuiltins = object()", "core.BaseException", 0),
        ("from builtins import Exception as Failure\nException = ValueError", "Failure", 1),
        ("from builtins import BaseException as Failure\nBaseException = ValueError", "Failure", 0),
        ("from .builtins import Exception as Failure", "Failure", 0),
        ("from .builtins import BaseException as Failure", "Failure", 0),
        ("from ..builtins import Exception as Failure", "Failure", 0),
        ("from ..builtins import BaseException as Failure", "Failure", 0),
        ("import pytest\nFailure = pytest.skip.Exception", "Failure", 0),
        ("import library\nFailures = (library.Exception,) + (OSError,)", "Failures", 0),
        ("import builtins", "builtins.BaseException", 0),
        ("import builtins as core", "core.BaseException", 0),
        ("from builtins import BaseException as Failure", "Failure", 0),
        ("", "", 0),
    ]
    for index, (declarations, caught, expected) in enumerate(cases):
        case_root = tmp_path / f"case_{index}"
        case_tests = case_root / "tests"
        case_tests.mkdir(parents=True)
        source = _source(declarations, caught)
        source = source.replace(":\n        pass", f":  # {TAG}\n        pass")
        ast.parse(source)
        (case_tests / "synthetic.py").write_text(source, encoding="utf-8", newline="\n")
        assert count_broad_waivers(case_root) == expected, caught
        (tests / f"case_{index}.py").write_text(source, encoding="utf-8", newline="\n")
    (tests / "fixture.py").write_text(
        _source("", "Exception", f'value = "# {TAG}"'), encoding="utf-8", newline="\n"
    )
    assert count_broad_waivers(tmp_path) == 6


@pytest.mark.parametrize("report", ["stdout", "json", "csv", "md"])
def test_reports_do_not_equate_no_local_log_with_silent_failure(
    tmp_path: Path, report: str
) -> None:
    source = _source("", "Exception as error", "future.set_exception(error)")
    findings = scan_python_source(source, rel_path=REL_PATH)
    counts = Counter(finding.category for finding in findings)
    inventory = scan_annotation_inventory(source, rel_path=REL_PATH)
    if report == "stdout":
        text = "\n".join(build_stdout(findings, counts, 0, inventory))
    else:
        write_reports(tmp_path, findings, counts, 0, inventory)
        text = (buildlog_dir(tmp_path) / f"exception-transparency.{report}").read_text(
            encoding="utf-8"
        )
    assert "no recognized local diagnostic" in text.lower()
    assert "suppresses failure" not in text.lower()
    assert "silent" not in text.lower()
    assert "without a diagnostic footprint" not in text.lower()
