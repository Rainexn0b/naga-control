"""Characterize architecture call/lock findings before DEBT-06 extraction."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
from pathlib import Path

import pytest

from buildpython.steps._architecture_validation_integrity import validate_rule_corpora
from buildpython.steps.architecture_validation import load_architecture_rules, scan_architecture


def _write_config(tmp_path: Path, rules: object) -> Path:
    path = tmp_path / "architecture.json"
    path.write_text(json.dumps({"rules": rules}), encoding="utf-8")
    return path


def _write_sources(tmp_path: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def _base_rule(rule_id: str, severity: str = "error") -> dict[str, object]:
    return {
        "id": rule_id,
        "description": "characterization",
        "severity": severity,
        "corpus": {"include": ["**/*.py"]},
    }


def test_forbid_all_reports_with_exact_finding(tmp_path: Path) -> None:
    rule = _base_rule("forbid-call")
    rule["calls"] = [
        {
            "receivers": ["svc"],
            "methods": ["danger"],
            "allowed_files": [],
            "forbid_all": True,
            "message": "no danger",
        }
    ]
    _write_sources(tmp_path, {"pkg/sample.py": "svc.danger()\n"})
    rules = load_architecture_rules(_write_config(tmp_path, [rule]))
    result = scan_architecture(tmp_path, rules)
    assert result.rules_checked == 1
    assert result.scanned_files == 1
    (finding,) = result.findings
    assert finding.rule_id == "forbid-call"
    assert finding.path == "pkg/sample.py"
    assert finding.line == 1
    assert finding.message == "no danger"
    assert finding.snippet == "svc.danger()"
    assert finding.regex == "call:svc.danger"
    assert finding.lock == ""
    assert finding.outer_locks == ()


def test_allowed_files_starstar_matches_zero_dirs(tmp_path: Path) -> None:
    rule = _base_rule("allow-glob")
    rule["calls"] = [
        {
            "receivers": ["svc"],
            "methods": ["run"],
            "allowed_files": ["src/**/allowed.py"],
            "message": "only allowed",
        }
    ]
    _write_sources(
        tmp_path,
        {
            "src/allowed.py": "svc.run()\n",
            "src/nested/allowed.py": "svc.run()\n",
            "src/other.py": "svc.run()\n",
        },
    )
    rules = load_architecture_rules(_write_config(tmp_path, [rule]))
    result = scan_architecture(tmp_path, rules)
    assert [item.path for item in result.findings] == ["src/other.py"]
    assert result.scanned_files == 3


def test_required_lock_precedence_and_messages(tmp_path: Path) -> None:
    rule = _base_rule("needs-lock")
    rule["calls"] = [
        {
            "receivers": ["svc"],
            "methods": ["op"],
            "allowed_files": ["allowed/*.py"],
            "required_locks": ["guard"],
            "message": "blocked",
            "lock_message": "needs guard",
        }
    ]
    _write_sources(
        tmp_path,
        {
            "allowed/guarded.py": "with guard:\n    svc.op()\n",
            "allowed/unguarded.py": "svc.op()\n",
            "other.py": "svc.op()\n",
        },
    )
    rules = load_architecture_rules(_write_config(tmp_path, [rule]))
    result = scan_architecture(tmp_path, rules)
    by_path = {item.path: item for item in result.findings}
    assert "allowed/guarded.py" not in by_path
    assert by_path["allowed/unguarded.py"].message == "needs guard"
    assert by_path["other.py"].message == "blocked"


def test_false_exemption_does_not_skip_zero(tmp_path: Path) -> None:
    rule = _base_rule("exempt-false")
    rule["calls"] = [
        {
            "receivers": ["svc"],
            "methods": ["run"],
            "allowed_files": [],
            "forbid_all": True,
            "message": "blocked",
            "skip_if_keywords": [{"name": "flag", "equals": False}],
        }
    ]
    _write_sources(
        tmp_path,
        {"pkg/calls.py": "svc.run(flag=False)\nsvc.run(flag=0)\nsvc.run()\n"},
    )
    rules = load_architecture_rules(_write_config(tmp_path, [rule]))
    result = scan_architecture(tmp_path, rules)
    assert [(item.line, item.message) for item in result.findings] == [
        (2, "blocked"),
        (3, "blocked"),
    ]
    assert all(item.regex == "call:svc.run" for item in result.findings)


def test_forbidden_under_lock_and_match_any(tmp_path: Path) -> None:
    specific = _base_rule("no-wipe")
    specific["forbidden_under_locks"] = [
        {
            "receivers": ["svc"],
            "methods": ["wipe"],
            "required_locks": ["guard"],
            "message": "no wipe under guard",
        }
    ]
    wildcard = _base_rule("no-nuke")
    wildcard["forbidden_under_locks"] = [
        {
            "methods": ["nuke"],
            "required_locks": ["guard"],
            "match_any_receiver": True,
            "message": "no nuke under guard",
        }
    ]
    _write_sources(
        tmp_path,
        {
            "guarded.py": "with guard:\n    svc.wipe()\n    other.nuke()\n    svc.safe()\n",
            "unguarded.py": "svc.wipe()\n",
        },
    )
    rules = load_architecture_rules(_write_config(tmp_path, [specific, wildcard]))
    result = scan_architecture(tmp_path, rules)
    assert len(result.findings) == 2
    wipe, nuke = sorted(result.findings, key=lambda item: item.line)
    assert wipe.message == "no wipe under guard"
    assert wipe.regex == "forbidden-under-lock:svc.wipe"
    assert wipe.lock == "guard"
    assert wipe.line == 2
    assert wipe.snippet == "svc.wipe()"
    assert nuke.message == "no nuke under guard"
    assert nuke.regex == "forbidden-under-lock:other.nuke"
    assert nuke.lock == "guard"
    assert nuke.line == 3


def test_lock_order_alias_violation_reports_canonical_lock(tmp_path: Path) -> None:
    rule = _base_rule("bad-order")
    rule["lock_orders"] = [
        {
            "locks": [{"name": "outer", "aliases": ["o_alias"]}, {"name": "inner"}],
            "message": "bad nesting",
        }
    ]
    _write_sources(
        tmp_path,
        {
            "good.py": "with outer:\n    with inner:\n        pass\n",
            "good_alias.py": "with o_alias:\n    with inner:\n        pass\n",
            "bad.py": "with inner:\n    with outer:\n        pass\n",
            "bad_alias.py": "with inner:\n    with o_alias:\n        pass\n",
        },
    )
    rules = load_architecture_rules(_write_config(tmp_path, [rule]))
    result = scan_architecture(tmp_path, rules)
    by_path = {item.path: item for item in result.findings}
    assert set(by_path) == {"bad.py", "bad_alias.py"}
    assert by_path["bad.py"].lock == "outer"
    assert by_path["bad.py"].outer_locks == ("inner",)
    assert by_path["bad.py"].regex == "lock-order:outer"
    assert by_path["bad.py"].line == 2
    assert by_path["bad_alias.py"].lock == "outer"
    assert by_path["bad_alias.py"].regex == "lock-order:o_alias"
    assert by_path["bad_alias.py"].outer_locks == ("inner",)


def test_dedup_sort_and_unique_files(tmp_path: Path) -> None:
    dup = _base_rule("dup-error")
    entry: dict[str, object] = {
        "receivers": ["svc"],
        "methods": ["hit"],
        "allowed_files": [],
        "forbid_all": True,
        "message": "hit blocked",
    }
    dup["calls"] = [dict(entry), dict(entry)]
    warn = _base_rule("warn-second", severity="warning")
    warn["calls"] = [
        {
            "receivers": ["svc"],
            "methods": ["hit"],
            "allowed_files": [],
            "forbid_all": True,
            "message": "hit warn",
        }
    ]
    _write_sources(tmp_path, {"a.py": "svc.hit()\n", "b.py": "x = 1\nsvc.hit()\n"})
    rules = load_architecture_rules(_write_config(tmp_path, [dup, warn]))
    result = scan_architecture(tmp_path, rules)
    assert result.rules_checked == 2
    assert result.scanned_files == 2
    assert len(result.findings) == 4
    assert [(item.path, item.line, item.rule_id) for item in result.findings] == [
        ("a.py", 1, "dup-error"),
        ("b.py", 2, "dup-error"),
        ("a.py", 1, "warn-second"),
        ("b.py", 2, "warn-second"),
    ]


def test_invalid_python_gate(tmp_path: Path) -> None:
    rule = _base_rule("any-call")
    rule["calls"] = [
        {
            "receivers": ["svc"],
            "methods": ["hit"],
            "allowed_files": [],
            "forbid_all": True,
            "message": "hit blocked",
        }
    ]
    _write_sources(tmp_path, {"broken.py": "def broken(:\n"})
    rules = load_architecture_rules(_write_config(tmp_path, [rule]))
    with pytest.raises(ValueError, match="cannot read or parse"):
        scan_architecture(tmp_path, rules)


def test_getattr_canonical_call_detected(tmp_path: Path) -> None:
    rule = _base_rule("getattr-call")
    rule["calls"] = [
        {
            "receivers": ["svc"],
            "methods": ["danger"],
            "allowed_files": [],
            "forbid_all": True,
            "message": "no danger",
        }
    ]
    _write_sources(tmp_path, {"pkg/dynamic.py": 'getattr(svc, "danger")()\n'})
    rules = load_architecture_rules(_write_config(tmp_path, [rule]))
    result = scan_architecture(tmp_path, rules)
    (finding,) = result.findings
    assert finding.regex == "call:svc.danger"
    assert finding.line == 1


def test_generator_body_does_not_inherit_lock(tmp_path: Path) -> None:
    rule = _base_rule("needs-guard")
    rule["calls"] = [
        {
            "receivers": ["svc"],
            "methods": ["op"],
            "allowed_files": ["**/*.py"],
            "required_locks": ["guard"],
            "message": "blocked",
            "lock_message": "needs guard",
        }
    ]
    _write_sources(
        tmp_path,
        {
            "pkg/scopes.py": (
                "with guard:\n"
                "    svc.op(1)\n"
                "    vals = (svc.op(x) for x in items)\n"
                "    fetched = (x for x in svc.fetch(items))\n"
            ),
        },
    )
    guarded = _base_rule("fetch-guard")
    guarded["calls"] = [
        {
            "receivers": ["svc"],
            "methods": ["fetch"],
            "allowed_files": ["**/*.py"],
            "required_locks": ["guard"],
            "message": "blocked",
            "lock_message": "needs guard",
        }
    ]
    _write_sources(tmp_path, {"pkg/unused.py": "x = 1\n"})
    rules = load_architecture_rules(_write_config(tmp_path, [rule, guarded]))
    result = scan_architecture(tmp_path, rules)
    op_findings = [item for item in result.findings if item.regex == "call:svc.op"]
    fetch_findings = [item for item in result.findings if item.regex == "call:svc.fetch"]
    assert [item.line for item in op_findings] == [3]
    assert op_findings[0].message == "needs guard"
    assert fetch_findings == []


def test_corpus_validation_stays_separate(tmp_path: Path) -> None:
    rule = _base_rule("empty-corpus")
    rule["corpus"] = {"include": ["no-such-dir/**/*.py"]}
    rule["calls"] = [
        {
            "receivers": ["svc"],
            "methods": ["hit"],
            "allowed_files": [],
            "forbid_all": True,
            "message": "hit blocked",
        }
    ]
    rules = load_architecture_rules(_write_config(tmp_path, [rule]))
    result = scan_architecture(tmp_path, rules)
    assert result.scanned_files == 0
    assert result.findings == ()
    with pytest.raises(ValueError, match="matches no files"):
        validate_rule_corpora(tmp_path, rules)
