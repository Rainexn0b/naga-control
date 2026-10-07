from __future__ import annotations

import json
import re
from pathlib import Path

from ._architecture_validation_integrity import validate_rule_payload
from ._architecture_validation_load_calls import (
    load_call_rules,
    load_forbidden_under_lock_rules,
)
from ._architecture_validation_models import (
    _FLAG_MAP,
    ArchitectureAssignmentRule,
    ArchitectureAttributeRule,
    ArchitectureImportRule,
    ArchitectureLock,
    ArchitectureLockOrderRule,
    ArchitecturePattern,
    ArchitectureRule,
)


def load_architecture_rules(config_path: Path) -> list[ArchitectureRule]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    validate_rule_payload(payload)
    raw_rules = payload.get("rules", [])

    rules: list[ArchitectureRule] = []
    for raw_rule in raw_rules:
        rule_id = str(raw_rule.get("id", "")).strip()
        description = str(raw_rule.get("description", "")).strip()
        severity = str(raw_rule.get("severity", "error")).strip().lower()
        corpus = raw_rule.get("corpus", {}) or {}
        include_globs = tuple(str(item) for item in (corpus.get("include", []) or []))
        exclude_globs = tuple(str(item) for item in (corpus.get("exclude", []) or []))

        if not rule_id:
            raise ValueError("architecture rule missing 'id'")
        if severity not in {"error", "warning"}:
            raise ValueError(f"architecture rule {rule_id!r} has invalid severity {severity!r}")
        if not include_globs:
            raise ValueError(f"architecture rule {rule_id!r} has no corpus include globs")

        patterns: list[ArchitecturePattern] = []
        for raw_pattern in raw_rule.get("patterns", []) or []:
            regex = str(raw_pattern.get("regex", "")).strip()
            message = str(raw_pattern.get("message", "")).strip()
            flags = str(raw_pattern.get("flags", "")).strip().lower()
            if not regex or not message:
                raise ValueError(f"architecture rule {rule_id!r} has an invalid pattern entry")
            patterns.append(
                ArchitecturePattern(
                    regex=regex,
                    message=message,
                    flags=flags,
                    compiled=re.compile(regex, _regex_flags(flags)),
                )
            )

        imports: list[ArchitectureImportRule] = []
        for raw_import in raw_rule.get("imports", []) or []:
            module = str(raw_import.get("module", "")).strip()
            message = str(raw_import.get("message", "")).strip()
            if not module or not message:
                raise ValueError(f"architecture rule {rule_id!r} has an invalid import entry")
            imports.append(ArchitectureImportRule(module=module, message=message))

        attributes: list[ArchitectureAttributeRule] = []
        for raw_attribute in raw_rule.get("attributes", []) or []:
            name = str(raw_attribute.get("name", "")).strip()
            message = str(raw_attribute.get("message", "")).strip()
            if not name or not message:
                raise ValueError(f"architecture rule {rule_id!r} has an invalid attribute entry")
            attributes.append(ArchitectureAttributeRule(name=name, message=message))

        assignments: list[ArchitectureAssignmentRule] = []
        raw_assignments = raw_rule.get("assignments", raw_rule.get("assignment_rules", []))
        if raw_assignments is None:
            raw_assignments = []
        if not isinstance(raw_assignments, list):
            raise ValueError(f"architecture rule {rule_id!r} has invalid assignment rules")
        for raw_assignment in raw_assignments:
            if not isinstance(raw_assignment, dict):
                raise ValueError(f"architecture rule {rule_id!r} has an invalid assignment entry")
            targets = _load_assignment_string_values(
                raw_assignment.get("targets", []), rule_id=rule_id, field="targets"
            )
            target_suffixes = _load_assignment_string_values(
                raw_assignment.get("target_suffixes", []), rule_id=rule_id, field="target_suffixes"
            )
            raw_message = raw_assignment.get("message", "")
            if not isinstance(raw_message, str) or not raw_message.strip():
                raise ValueError(f"architecture rule {rule_id!r} has an invalid assignment entry")
            message = raw_message.strip()
            if not targets and not target_suffixes:
                raise ValueError(f"architecture rule {rule_id!r} has an invalid assignment entry")
            assignments.append(
                ArchitectureAssignmentRule(
                    targets=targets,
                    target_suffixes=target_suffixes,
                    message=message,
                )
            )

        calls = load_call_rules(raw_rule, rule_id)
        forbidden_under_locks = load_forbidden_under_lock_rules(raw_rule, rule_id)

        lock_orders = _load_lock_order_rules(raw_rule=raw_rule, rule_id=rule_id)
        if (
            not patterns
            and not imports
            and not attributes
            and not assignments
            and not calls
            and not forbidden_under_locks
            and not lock_orders
        ):
            raise ValueError(
                f"architecture rule {rule_id!r} has no patterns, import rules, attribute rules, call rules, "
                "assignment rules, forbidden-under-lock call rules, or lock-order rules"
            )

        rules.append(
            ArchitectureRule(
                rule_id=rule_id,
                description=description,
                severity=severity,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                patterns=tuple(patterns),
                imports=tuple(imports),
                attributes=tuple(attributes),
                assignments=tuple(assignments),
                calls=tuple(calls),
                forbidden_under_locks=tuple(forbidden_under_locks),
                lock_orders=tuple(lock_orders),
            )
        )

    return rules


def _regex_flags(raw_flags: str) -> int:
    flags = 0
    for flag in raw_flags:
        flags |= _FLAG_MAP.get(flag, 0)
    return flags


def _load_assignment_string_values(
    raw_values: object, *, rule_id: str, field: str
) -> tuple[str, ...]:
    if raw_values is None:
        return ()
    if not isinstance(raw_values, list) or any(
        not isinstance(value, str) or not value.strip() for value in raw_values
    ):
        raise ValueError(f"architecture rule {rule_id!r} has invalid assignment {field}")
    return tuple(value.strip() for value in raw_values)


def _load_lock_order_rules(*, raw_rule: object, rule_id: str) -> list[ArchitectureLockOrderRule]:
    if not isinstance(raw_rule, dict):
        raise ValueError(f"architecture rule {rule_id!r} must be an object")
    raw_lock_orders = raw_rule.get(
        "lock_orders",
        raw_rule.get("lock_order", raw_rule.get("lock_order_rules", [])),
    )
    if raw_lock_orders is None:
        return []
    if isinstance(raw_lock_orders, dict):
        raw_lock_orders = [raw_lock_orders]
    if not isinstance(raw_lock_orders, list):
        raise ValueError(f"architecture rule {rule_id!r} has invalid lock-order rules")

    lock_orders: list[ArchitectureLockOrderRule] = []
    for raw_lock_order in raw_lock_orders:
        if not isinstance(raw_lock_order, dict):
            raise ValueError(f"architecture rule {rule_id!r} has an invalid lock-order entry")
        raw_locks = raw_lock_order.get(
            "locks", raw_lock_order.get("levels", raw_lock_order.get("order"))
        )
        raw_alias_map = raw_lock_order.get("aliases", {})
        message = str(raw_lock_order.get("message", "")).strip()
        if not isinstance(raw_locks, list) or len(raw_locks) < 2 or not message:
            raise ValueError(f"architecture rule {rule_id!r} has an invalid lock-order entry")
        if not isinstance(raw_alias_map, (dict, list)):
            raise ValueError(f"architecture rule {rule_id!r} has an invalid lock alias map")

        locks: list[ArchitectureLock] = []
        seen_names: set[str] = set()
        for raw_lock in raw_locks:
            if isinstance(raw_lock, str):
                name = raw_lock.strip()
                mapped_aliases = (
                    raw_alias_map.get(name, []) if isinstance(raw_alias_map, dict) else []
                )
                if not isinstance(mapped_aliases, list):
                    raise ValueError(
                        f"architecture rule {rule_id!r} has an invalid lock alias list"
                    )
                aliases = tuple(str(alias).strip() for alias in mapped_aliases)
            elif isinstance(raw_lock, dict):
                name = str(raw_lock.get("name", "")).strip()
                raw_aliases = raw_lock.get("aliases", [])
                if not isinstance(raw_aliases, list):
                    raise ValueError(
                        f"architecture rule {rule_id!r} has an invalid lock alias list"
                    )
                aliases = tuple(str(alias).strip() for alias in raw_aliases)
            else:
                raise ValueError(f"architecture rule {rule_id!r} has an invalid lock entry")
            if not name or any(not alias for alias in aliases):
                raise ValueError(f"architecture rule {rule_id!r} has an invalid lock entry")
            names = (name, *aliases)
            if len(set(names)) != len(names) or seen_names.intersection(names):
                raise ValueError(
                    f"architecture rule {rule_id!r} has duplicate lock names or aliases"
                )
            seen_names.update(names)
            locks.append(ArchitectureLock(name=name, aliases=aliases))
        lock_orders.append(ArchitectureLockOrderRule(locks=tuple(locks), message=message))
    return lock_orders
