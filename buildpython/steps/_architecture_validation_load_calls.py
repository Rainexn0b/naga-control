"""Call-vocabulary loading for architecture rules (DEBT-06 cohort6)."""

from __future__ import annotations

from ._architecture_validation_models import (
    ArchitectureCallRule,
    ArchitectureForbiddenUnderLockCallRule,
    ArchitectureKeywordExemption,
)


def load_call_rules(raw_rule: dict[str, object], rule_id: str) -> list[ArchitectureCallRule]:
    raw_calls = raw_rule.get("calls", raw_rule.get("call_rules", [])) or []
    calls: list[ArchitectureCallRule] = []
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            raise ValueError(f"architecture rule {rule_id!r} has an invalid call entry")
        receivers = tuple(
            str(item).strip() for item in (raw_call.get("receivers", []) or []) if str(item).strip()
        )
        receiver_suffixes = tuple(
            str(item).strip()
            for item in (raw_call.get("receiver_suffixes", []) or [])
            if str(item).strip()
        )
        methods = tuple(
            str(item).strip() for item in (raw_call.get("methods", []) or []) if str(item).strip()
        )
        allowed_files = tuple(
            str(item).strip()
            for item in (raw_call.get("allowed_files", []) or [])
            if str(item).strip()
        )
        required_locks = tuple(
            str(item).strip()
            for item in (raw_call.get("required_locks", []) or [])
            if str(item).strip()
        )
        skip_if_keywords = _load_keyword_exemptions(raw_call, rule_id=rule_id)
        message = str(raw_call.get("message", "")).strip()
        lock_message = str(raw_call.get("lock_message", "")).strip()
        forbid_all = raw_call.get("forbid_all", False)
        if (
            (not receivers and not receiver_suffixes)
            or not methods
            or (not allowed_files and forbid_all is not True)
            or not message
            or (required_locks and not lock_message)
            or type(forbid_all) is not bool
        ):
            raise ValueError(f"architecture rule {rule_id!r} has an invalid call entry")
        calls.append(
            ArchitectureCallRule(
                receivers=receivers,
                receiver_suffixes=receiver_suffixes,
                methods=methods,
                allowed_files=allowed_files,
                required_locks=required_locks,
                skip_if_keywords=tuple(skip_if_keywords),
                message=message,
                lock_message=lock_message,
                forbid_all=forbid_all,
            )
        )
    return calls


def _load_keyword_exemptions(
    raw_call: dict[str, object], *, rule_id: str
) -> list[ArchitectureKeywordExemption]:
    skip_if_keywords: list[ArchitectureKeywordExemption] = []
    raw_exemptions = raw_call.get("skip_if_keywords", []) or []
    if not isinstance(raw_exemptions, list):
        raise ValueError(f"architecture rule {rule_id!r} has invalid keyword exemptions")
    for raw_exemption in raw_exemptions:
        if not isinstance(raw_exemption, dict):
            raise ValueError(f"architecture rule {rule_id!r} has an invalid keyword exemption")
        name = str(raw_exemption.get("name", "")).strip()
        if not name or "equals" not in raw_exemption:
            raise ValueError(f"architecture rule {rule_id!r} has an invalid keyword exemption")
        equals = raw_exemption["equals"]
        if equals is not None and not isinstance(equals, (bool, int, float, str)):
            raise ValueError(f"architecture rule {rule_id!r} has a non-literal keyword exemption")
        skip_if_keywords.append(ArchitectureKeywordExemption(name=name, equals=equals))
    return skip_if_keywords


def load_forbidden_under_lock_rules(
    raw_rule: dict[str, object], rule_id: str
) -> list[ArchitectureForbiddenUnderLockCallRule]:
    raw_forbidden = (
        raw_rule.get(
            "forbidden_under_locks",
            raw_rule.get(
                "forbidden_calls_under_locks",
                raw_rule.get("forbidden_calls_under_lock", raw_rule.get("forbidden_calls", [])),
            ),
        )
        or []
    )
    if not isinstance(raw_forbidden, list):
        raise ValueError(
            f"architecture rule {rule_id!r} has invalid forbidden-under-lock call rules"
        )
    forbidden_under_locks: list[ArchitectureForbiddenUnderLockCallRule] = []
    for raw_forbidden_call in raw_forbidden:
        if not isinstance(raw_forbidden_call, dict):
            raise ValueError(
                f"architecture rule {rule_id!r} has an invalid forbidden-under-lock call entry"
            )
        receivers = _load_string_values(
            raw_forbidden_call.get("receivers", []), rule_id=rule_id, field="receivers"
        )
        receiver_suffixes = _load_string_values(
            raw_forbidden_call.get("receiver_suffixes", []),
            rule_id=rule_id,
            field="receiver_suffixes",
        )
        methods = _load_string_values(
            raw_forbidden_call.get("methods", []), rule_id=rule_id, field="methods"
        )
        required_locks = _load_string_values(
            raw_forbidden_call.get("required_locks", raw_forbidden_call.get("locks", [])),
            rule_id=rule_id,
            field="required_locks",
        )
        match_any_receiver = raw_forbidden_call.get("match_any_receiver", False)
        message = str(raw_forbidden_call.get("message", "")).strip()
        if (
            (not receivers and not receiver_suffixes and match_any_receiver is not True)
            or not methods
            or not required_locks
            or not message
            or type(match_any_receiver) is not bool
        ):
            raise ValueError(
                f"architecture rule {rule_id!r} has an invalid forbidden-under-lock call entry"
            )
        forbidden_under_locks.append(
            ArchitectureForbiddenUnderLockCallRule(
                receivers=receivers,
                receiver_suffixes=receiver_suffixes,
                methods=methods,
                match_any_receiver=match_any_receiver,
                required_locks=required_locks,
                message=message,
            )
        )
    return forbidden_under_locks


def _load_string_values(raw_values: object, *, rule_id: str, field: str) -> tuple[str, ...]:
    if raw_values is None:
        return ()
    if not isinstance(raw_values, list) or any(
        not isinstance(value, str) or not value.strip() for value in raw_values
    ):
        raise ValueError(f"architecture rule {rule_id!r} has invalid forbidden-under-lock {field}")
    return tuple(value.strip() for value in raw_values)
