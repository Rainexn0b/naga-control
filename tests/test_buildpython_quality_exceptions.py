"""Quality waivers use Python comments, never annotation-looking fixture text."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from buildpython.steps import quality_exceptions, step_loc_check
from buildpython.steps.exception_transparency.scanner import (
    has_quality_exception_waiver,
    scan_annotation_inventory,
    scan_python_source,
)
from buildpython.steps.file_size_analysis.scanning import (
    collect_hotspots,
    file_size_quality_exception_reason,
)
from buildpython.steps.quality_exceptions import (
    explanation_for_quality_exception_step,
    parse_quality_exception_tag,
    python_comments,
)

STEPS = ("file-size-analysis", "loc-check", "exception-transparency")


@pytest.mark.parametrize("step", STEPS)
@pytest.mark.parametrize(
    "template",
    [
        'fixture = "# @quality-exception {step}: copied exception\\n"\n',
        'fixture = "escaped \\"# @quality-exception {step}: copied exception\\n"\n',
        '"""Example:\n# @quality-exception {step}: copied exception\n"""\n',
        "fixture = '''Example:\n# @quality-exception {step}: copied exception\n'''\n",
        'def example():\n    """\n    # @quality-exception {step}: copied exception\n    """\n',
        'fixture = f"# @quality-exception {step}: copied {{1}}"\n',
    ],
)
def test_annotation_looking_strings_are_not_comments(
    tmp_path: Path, step: str, template: str
) -> None:
    path = tmp_path / "example.py"
    path.write_text(template.format(step=step), encoding="utf-8")
    source = path.read_text(encoding="utf-8")
    ast.parse(source)
    assert python_comments(source) == {}
    assert file_size_quality_exception_reason(source) is None
    assert step_loc_check.loc_check_quality_exception_reason(source) is None


def test_comment_lines_and_inline_comments_retain_their_text(tmp_path: Path) -> None:
    source = (
        '"""\n# @quality-exception file-size-analysis: example only\n"""\n'
        "# ordinary comment\n"
        "# @quality-exception LOC-CHECK: - first real reason\n"
        'value = "# @quality-exception loc-check: example" '
        "# @quality-exception file-size-analysis - actual inline reason\n"
        "# @quality-exception exception-transparency: handler policy\n"
        "#\n"
    )
    path = tmp_path / "comments.py"
    path.write_text(source, encoding="utf-8")
    source = path.read_text(encoding="utf-8")
    comments = python_comments(source)
    assert comments == {
        4: "ordinary comment",
        5: "@quality-exception LOC-CHECK: - first real reason",
        6: "@quality-exception file-size-analysis - actual inline reason",
        7: "@quality-exception exception-transparency: handler policy",
        8: "",
    }
    assert file_size_quality_exception_reason(source) == "actual inline reason"
    assert step_loc_check.loc_check_quality_exception_reason(source) == "- first real reason"
    assert (
        explanation_for_quality_exception_step(comments[7], step_slug="exception-transparency")
        == "handler policy"
    )


@pytest.mark.parametrize("step", STEPS)
def test_multiple_markers_and_empty_explanations_keep_existing_selection(step: str) -> None:
    source = (
        "# @quality-exception other-step: unrelated\n"
        f"# @quality-exception {step}:\n"
        f"# @quality-exception {step} - first explained reason\n"
        f"# @quality-exception {step}: later reason\n"
    )
    comments = python_comments(source)
    assert list(comments) == [1, 2, 3, 4]
    assert explanation_for_quality_exception_step(comments[2], step_slug=step) == ""
    if step == "file-size-analysis":
        assert file_size_quality_exception_reason(source) == "first explained reason"
    elif step == "loc-check":
        assert step_loc_check.loc_check_quality_exception_reason(source) == (
            "first explained reason"
        )
    else:
        assert scan_annotation_inventory(source, rel_path="tests/example.py").total == 2

    # The shipped parser recognizes the first marker per comment, not every marker.
    combined = f"@quality-exception {step}: first @quality-exception other-step: second"
    tag = parse_quality_exception_tag(combined)
    assert tag is not None
    assert tag.step_slug == step
    assert tag.explanation == "first @quality-exception other-step: second"
    assert explanation_for_quality_exception_step(combined, step_slug="other-step") is None


@pytest.mark.parametrize("step", ("file-size-analysis", "loc-check"))
@pytest.mark.parametrize("suffix", ["", ":", " - "])
def test_only_empty_explanations_do_not_waive_files(step: str, suffix: str) -> None:
    source = f"# @quality-exception {step}{suffix}"
    assert file_size_quality_exception_reason(source) is None
    assert step_loc_check.loc_check_quality_exception_reason(source) is None


@pytest.mark.parametrize(
    "invalid_tail",
    [
        'fixture = """unterminated\n# @quality-exception loc-check: example\n',
        "value = (\n",
        "if True:\n    value = 1\n  value = 2\n",
        'fixture = "unterminated # @quality-exception loc-check: example\n',
    ],
)
def test_lexical_errors_discard_even_earlier_real_comments(
    tmp_path: Path, invalid_tail: str
) -> None:
    path = tmp_path / "invalid.py"
    path.write_text(
        "# @quality-exception file-size-analysis: earlier real comment\n"
        "# @quality-exception loc-check: earlier real comment\n" + invalid_tail,
        encoding="utf-8",
    )
    source = path.read_text(encoding="utf-8")
    assert python_comments(source) == {}
    assert file_size_quality_exception_reason(source) is None
    assert step_loc_check.loc_check_quality_exception_reason(source) is None


@pytest.mark.parametrize("error_type", [SyntaxError, RuntimeError])
def test_only_known_tokenization_failures_are_suppressed(
    monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    def fail_tokenization(_readline: object) -> None:
        raise error_type("tokenization failed")

    monkeypatch.setattr(quality_exceptions.tokenize, "generate_tokens", fail_tokenization)
    if error_type is SyntaxError:
        assert python_comments("# real comment\n") == {}
    else:
        with pytest.raises(RuntimeError, match="tokenization failed"):
            python_comments("# real comment\n")


def test_syntax_validation_is_not_part_of_comment_extraction() -> None:
    source = "value =\n# @quality-exception loc-check: unambiguous comment\n"
    with pytest.raises(SyntaxError):
        ast.parse(source)
    assert python_comments(source) == {2: "@quality-exception loc-check: unambiguous comment"}


@pytest.mark.parametrize("real_comments", [False, True])
@pytest.mark.parametrize("line_count", [400, 401])
@pytest.mark.parametrize("separator", ["", "\f", "\u2028"])
def test_file_scanners_distinguish_fixtures_and_never_waive_above_400(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    real_comments: bool,
    line_count: int,
    separator: str,
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    path = tests / "test_example.py"
    source = (
        f'separator = "{separator}"\n'
        'fixture = "# @quality-exception loc-check: copied exception\\n"\n'
        '"""\n# @quality-exception file-size-analysis: docstring example\n"""\n'
    )
    if real_comments:
        source += (
            "# @quality-exception loc-check: real LOC rationale\n"
            'value = "#" # @quality-exception file-size-analysis: real size rationale\n'
        )
    source += "\n" * (line_count - len(source.splitlines()))
    ast.parse(source)
    assert len(source.split("\n")) - 1 == line_count - bool(separator)
    path.write_text(source, encoding="utf-8")
    assert len(path.read_text(encoding="utf-8").splitlines()) == line_count
    monkeypatch.setattr(step_loc_check, "repo_root", lambda: tmp_path)
    result = step_loc_check.loc_check_runner()
    payload = json.loads((tmp_path / "buildlog/naga-control/loc-check.json").read_text())
    rows, *_, waivers = collect_hotspots(tmp_path, roots=("tests",))
    if real_comments and line_count == 400:
        assert payload["files"] == []
        assert payload["waivers"][0]["reason"] == "real LOC rationale"
        assert rows == []
        assert waivers == [{"path": "tests/test_example.py", "reason": "real size rationale"}]
    else:
        assert payload["waivers"] == []
        assert payload["files"][0]["lines"] == line_count
        assert rows[0]["lines"] == line_count
        assert rows[0]["path"] == "tests/test_example.py"
        assert waivers == []
    assert result.exit_code == (1 if line_count > 400 else 0)


@pytest.mark.parametrize(
    "handler_annotation",
    [
        "# @quality-exception exception-transparency: boundary policy\n"
        "except Exception:\n    pass\n",
        "except Exception:  # @quality-exception exception-transparency: boundary policy\n"
        "    pass\n",
        'except Exception: value = "#"; pass '
        "# @quality-exception exception-transparency: boundary policy\n",
    ],
)
def test_real_exception_annotations_keep_existing_inventory_and_handler_contracts(
    tmp_path: Path, handler_annotation: str
) -> None:
    source = (
        "# @quality-exception exception-transparency: module policy\n"
        "try:\n    operation()\n" + handler_annotation
    )
    path = tmp_path / "handlers.py"
    path.write_text(source, encoding="utf-8")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler))
    comments = python_comments(source)
    assert len(comments) == 2
    assert (
        explanation_for_quality_exception_step(comments[1], step_slug="exception-transparency")
        == "module policy"
    )
    assert has_quality_exception_waiver(source.splitlines(), handler)
    inventory = scan_annotation_inventory(source, rel_path="tests/handlers.py")
    assert inventory.total == 2
    assert inventory.by_subtree == (("tests", 2),)
    assert scan_python_source(source, rel_path="tests/handlers.py") == []
