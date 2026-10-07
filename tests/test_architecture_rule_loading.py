"""Characterize architecture call/forbidden loading before DEBT-06 extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from buildpython.steps.architecture_validation import load_architecture_rules


def _write_config(tmp_path: Path, rules: object) -> Path:
    path = tmp_path / "architecture.json"
    path.write_text(json.dumps({"rules": rules}), encoding="utf-8")
    return path


def _base_rule(rule_id: str) -> dict[str, object]:
    return {
        "id": rule_id,
        "description": "characterization",
        "severity": "error",
        "corpus": {"include": ["**/*.py"]},
    }


def test_primary_call_and_forbidden_keys_preserve_values(tmp_path: Path) -> None:
    rule = _base_rule("primary")
    rule["calls"] = [
        {
            "receivers": ["service"],
            "receiver_suffixes": ["Proxy"],
            "methods": ["danger"],
            "allowed_files": ["allowed/*.py"],
            "required_locks": ["guard"],
            "skip_if_keywords": [{"name": "flag", "equals": False}],
            "message": "do not call danger",
            "lock_message": "needs guard",
            "forbid_all": False,
        }
    ]
    rule["forbidden_under_locks"] = [
        {
            "receivers": ["service"],
            "receiver_suffixes": [],
            "methods": ["unsafe"],
            "required_locks": ["guard"],
            "match_any_receiver": False,
            "message": "unsafe under guard",
        }
    ]
    rule["lock_orders"] = [
        {"locks": [{"name": "outer"}, {"name": "inner"}], "message": "order violated"}
    ]
    rules = load_architecture_rules(_write_config(tmp_path, [rule]))
    loaded = rules[0]
    assert loaded.calls[0].receivers == ("service",)
    assert loaded.calls[0].receiver_suffixes == ("Proxy",)
    assert loaded.calls[0].methods == ("danger",)
    assert loaded.calls[0].allowed_files == ("allowed/*.py",)
    assert loaded.calls[0].required_locks == ("guard",)
    assert loaded.calls[0].skip_if_keywords[0].name == "flag"
    assert loaded.calls[0].skip_if_keywords[0].equals is False
    assert loaded.calls[0].message == "do not call danger"
    assert loaded.calls[0].lock_message == "needs guard"
    assert loaded.calls[0].forbid_all is False
    assert loaded.forbidden_under_locks[0].receivers == ("service",)
    assert loaded.forbidden_under_locks[0].required_locks == ("guard",)
    assert loaded.forbidden_under_locks[0].match_any_receiver is False
    assert loaded.lock_orders[0].locks[0].name == "outer"
    assert loaded.lock_orders[0].locks[1].name == "inner"
    # Compatibility aliases stay bound to the same tuples.
    assert loaded.call_rules == loaded.calls
    assert loaded.forbidden_call_rules == loaded.forbidden_under_locks
    assert loaded.forbidden_calls == loaded.forbidden_under_locks


def test_call_rules_fallback_key_loads(tmp_path: Path) -> None:
    rule = _base_rule("legacy-call")
    rule["call_rules"] = [
        {
            "receivers": ["svc"],
            "methods": ["run"],
            "allowed_files": [],
            "message": "blocked everywhere",
            "forbid_all": True,
        }
    ]
    rules = load_architecture_rules(_write_config(tmp_path, [rule]))
    assert rules[0].calls[0].receivers == ("svc",)
    assert rules[0].calls[0].forbid_all is True
    assert rules[0].call_rules == rules[0].calls


@pytest.mark.parametrize(
    "key",
    [
        "forbidden_under_locks",
        "forbidden_calls_under_locks",
        "forbidden_calls_under_lock",
        "forbidden_calls",
    ],
)
def test_forbidden_key_aliases_load(tmp_path: Path, key: str) -> None:
    rule = _base_rule("forbidden-alias")
    rule[key] = [
        {
            "receivers": ["svc"],
            "methods": ["op"],
            "locks": ["guard"],
            "message": "no op under guard",
        }
    ]
    rules = load_architecture_rules(_write_config(tmp_path, [rule]))
    forbidden = rules[0].forbidden_under_locks[0]
    assert forbidden.receivers == ("svc",)
    assert forbidden.required_locks == ("guard",)
    assert forbidden.message == "no op under guard"


def test_keyword_exemption_literal_types_preserved(tmp_path: Path) -> None:
    rule = _base_rule("literals")
    rule["calls"] = [
        {
            "receivers": ["svc"],
            "methods": ["run"],
            "allowed_files": [],
            "forbid_all": True,
            "message": "blocked",
            "skip_if_keywords": [
                {"name": "a", "equals": False},
                {"name": "b", "equals": 0},
                {"name": "c", "equals": None},
                {"name": "d", "equals": "x"},
            ],
        }
    ]
    loaded = load_architecture_rules(_write_config(tmp_path, [rule]))[0]
    equals = {item.name: item.equals for item in loaded.calls[0].skip_if_keywords}
    assert equals["a"] is False
    assert equals["b"] == 0 and type(equals["b"]) is int
    assert equals["c"] is None
    assert equals["d"] == "x"


@pytest.mark.parametrize("field", ["forbid_all", "match_any_receiver"])
@pytest.mark.parametrize("bad", [1, 0, "true", 1.0])
def test_strict_bool_rejects_non_bool(tmp_path: Path, field: str, bad: object) -> None:
    rule = _base_rule("strict-bool")
    if field == "forbid_all":
        rule["calls"] = [
            {
                "receivers": ["svc"],
                "methods": ["run"],
                "allowed_files": ["a.py"],
                "message": "m",
                "forbid_all": bad,
            }
        ]
    else:
        rule["forbidden_under_locks"] = [
            {
                "receivers": ["svc"],
                "methods": ["run"],
                "required_locks": ["g"],
                "message": "m",
                "match_any_receiver": bad,
            }
        ]
    with pytest.raises(ValueError, match=r"invalid (call|forbidden-under-lock call) entry"):
        load_architecture_rules(_write_config(tmp_path, [rule]))


@pytest.mark.parametrize("bad_equals", [["x"], {"k": 1}, [1, 2], {"nested": {"x": 1}}])
def test_non_literal_exemption_rejected(tmp_path: Path, bad_equals: object) -> None:
    rule = _base_rule("non-literal")
    rule["calls"] = [
        {
            "receivers": ["svc"],
            "methods": ["run"],
            "allowed_files": [],
            "forbid_all": True,
            "message": "m",
            "skip_if_keywords": [{"name": "flag", "equals": bad_equals}],
        }
    ]
    with pytest.raises(ValueError, match="non-literal keyword exemption"):
        load_architecture_rules(_write_config(tmp_path, [rule]))


@pytest.mark.parametrize("mutation", ["receivers", "methods", "allowed", "message", "lock"])
def test_malformed_call_entries_rejected(tmp_path: Path, mutation: str) -> None:
    entry: dict[str, object] = {
        "receivers": ["svc"],
        "methods": ["run"],
        "allowed_files": ["a.py"],
        "message": "m",
    }
    if mutation == "receivers":
        entry = {"methods": ["run"], "allowed_files": ["a.py"], "message": "m"}
    elif mutation == "methods":
        entry = {"receivers": ["svc"], "allowed_files": ["a.py"], "message": "m"}
    elif mutation == "allowed":
        entry = {"receivers": ["svc"], "methods": ["run"], "message": "m"}
    elif mutation == "message":
        entry = {"receivers": ["svc"], "methods": ["run"], "allowed_files": ["a.py"]}
    else:
        entry = {
            "receivers": ["svc"],
            "methods": ["run"],
            "allowed_files": ["a.py"],
            "required_locks": ["g"],
            "message": "m",
        }
    rule = _base_rule("bad-call")
    rule["calls"] = [entry]
    with pytest.raises(ValueError, match="invalid call entry"):
        load_architecture_rules(_write_config(tmp_path, [rule]))


@pytest.mark.parametrize("mutation", ["receiver", "methods", "locks", "message"])
def test_malformed_forbidden_entries_rejected(tmp_path: Path, mutation: str) -> None:
    entry: dict[str, object] = {
        "receivers": ["svc"],
        "methods": ["run"],
        "required_locks": ["g"],
        "message": "m",
    }
    if mutation == "receiver":
        entry = {"methods": ["run"], "required_locks": ["g"], "message": "m"}
    elif mutation == "methods":
        entry = {"receivers": ["svc"], "required_locks": ["g"], "message": "m"}
    elif mutation == "locks":
        entry = {"receivers": ["svc"], "methods": ["run"], "message": "m"}
    else:
        entry = {"receivers": ["svc"], "methods": ["run"], "required_locks": ["g"]}
    rule = _base_rule("bad-forbidden")
    rule["forbidden_under_locks"] = [entry]
    with pytest.raises(ValueError, match="invalid forbidden-under-lock call entry"):
        load_architecture_rules(_write_config(tmp_path, [rule]))


def test_invalid_forbidden_string_list_message(tmp_path: Path) -> None:
    rule = _base_rule("bad-strings")
    rule["forbidden_under_locks"] = [
        {"receivers": [""], "methods": ["run"], "required_locks": ["g"], "message": "m"}
    ]
    with pytest.raises(ValueError, match="invalid forbidden-under-lock receivers"):
        load_architecture_rules(_write_config(tmp_path, [rule]))


def test_duplicate_rule_ids_rejected(tmp_path: Path) -> None:
    first = _base_rule("dup")
    first["calls"] = [
        {
            "receivers": ["a"],
            "methods": ["m"],
            "allowed_files": [],
            "forbid_all": True,
            "message": "x",
        }
    ]
    second = _base_rule("dup")
    second["calls"] = [
        {
            "receivers": ["b"],
            "methods": ["m"],
            "allowed_files": [],
            "forbid_all": True,
            "message": "y",
        }
    ]
    with pytest.raises(ValueError, match="Duplicate architecture rule id"):
        load_architecture_rules(_write_config(tmp_path, [first, second]))


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"other": []}, "only 'rules'"),
        ({"rules": []}, "non-empty rules list"),
        ({"rules": [{"id": "x"}]}, "must have a corpus object"),
        ({"rules": [{"id": "", "corpus": {"include": ["a.py"]}}]}, "missing 'id'"),
    ],
)
def test_schema_rejections(tmp_path: Path, payload: object, match: str) -> None:
    path = tmp_path / "architecture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        load_architecture_rules(path)


def test_unknown_rule_field_rejected(tmp_path: Path) -> None:
    rule = _base_rule("unknown")
    rule["bogus_field"] = []
    with pytest.raises(ValueError, match="Unknown fields in architecture rule"):
        load_architecture_rules(_write_config(tmp_path, [rule]))


@pytest.mark.parametrize("outer", ["lock_orders", "lock_order", "lock_order_rules"])
@pytest.mark.parametrize("inner", ["locks", "levels", "order"])
def test_lock_order_key_aliases(tmp_path: Path, outer: str, inner: str) -> None:
    rule = _base_rule("lock-alias")
    if outer == "lock_order":
        rule[outer] = {inner: ["first", "second"], "message": "bad order"}
    else:
        rule[outer] = [{inner: ["first", "second"], "message": "bad order"}]
    rules = load_architecture_rules(_write_config(tmp_path, [rule]))
    assert [lock.name for lock in rules[0].lock_orders[0].locks] == ["first", "second"]


def test_lock_aliases_and_duplicate_rejected(tmp_path: Path) -> None:
    rule = _base_rule("lock-alias-map")
    rule["lock_orders"] = [
        {
            "locks": ["first", "second"],
            "aliases": {"first": ["f-alias"]},
            "message": "bad order",
        }
    ]
    loaded = load_architecture_rules(_write_config(tmp_path, [rule]))[0]
    assert loaded.lock_orders[0].locks[0].aliases == ("f-alias",)
    dup = _base_rule("lock-dup")
    dup["lock_orders"] = [{"locks": ["a", "a"], "message": "bad order"}]
    with pytest.raises(ValueError, match="duplicate lock names or aliases"):
        load_architecture_rules(_write_config(tmp_path, [dup]))
    single = _base_rule("lock-single")
    single["lock_orders"] = [{"locks": ["only"], "message": "bad order"}]
    with pytest.raises(ValueError, match="invalid lock-order entry"):
        load_architecture_rules(_write_config(tmp_path, [single]))
