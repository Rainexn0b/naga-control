"""Call and lock-order finding emission for architecture scans (DEBT-06 cohort6)."""

from __future__ import annotations

from pathlib import Path

from . import _architecture_validation_helpers as _helpers
from ._architecture_validation_helpers import _ScannedCall, _ScannedLockAcquisition
from ._architecture_validation_models import (
    ArchitectureFinding,
    ArchitectureLockOrderRule,
    ArchitectureRule,
)


def emit_lock_order_findings(
    rule: ArchitectureRule,
    rel: str,
    lines: list[str],
    acquisitions: tuple[_ScannedLockAcquisition, ...],
    findings: list[ArchitectureFinding],
    seen_findings: set[tuple[str, str, int, str, str]],
) -> None:
    for lock_order in rule.lock_orders:
        levels = {
            alias: index
            for index, lock in enumerate(lock_order.locks)
            for alias in (lock.name, *lock.aliases)
        }
        for acquisition in acquisitions:
            inner_level = _lock_level(acquisition.lock, lock_order=lock_order, levels=levels)
            if inner_level is None:
                continue
            violating_outer_locks = tuple(
                outer_lock
                for outer_lock in acquisition.outer_locks
                if (outer_level := _lock_level(outer_lock, lock_order=lock_order, levels=levels))
                is not None
                and outer_level > inner_level
            )
            if not violating_outer_locks:
                continue
            inner_name = lock_order.locks[inner_level].name
            message = lock_order.message
            finding_token = f"lock-order:{acquisition.lock}"
            finding_key = (rule.rule_id, rel, acquisition.line, message, finding_token)
            if finding_key in seen_findings:
                continue
            seen_findings.add(finding_key)
            findings.append(
                ArchitectureFinding(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    path=rel,
                    line=acquisition.line,
                    message=message,
                    snippet=_helpers._line_snippet(lines=lines, line=acquisition.line),
                    regex=finding_token,
                    lock=inner_name,
                    outer_locks=acquisition.outer_locks,
                )
            )


def emit_call_findings(
    rule: ArchitectureRule,
    rel: str,
    lines: list[str],
    calls: tuple[_ScannedCall, ...],
    findings: list[ArchitectureFinding],
    seen_findings: set[tuple[str, str, int, str, str]],
) -> None:
    for call_rule in rule.calls:
        for scanned_call in calls:
            receiver_matches = scanned_call.receiver in call_rule.receivers or any(
                scanned_call.receiver.endswith(suffix) for suffix in call_rule.receiver_suffixes
            )
            if not receiver_matches or scanned_call.method not in call_rule.methods:
                continue
            if any(
                any(
                    name == exemption.name
                    and _literal_keyword_matches(actual=value, expected=exemption.equals)
                    for name, value in scanned_call.literal_keywords
                )
                for exemption in call_rule.skip_if_keywords
            ):
                continue
            if call_rule.forbid_all or not _path_matches_any(rel, call_rule.allowed_files):
                message = call_rule.message
            elif call_rule.required_locks and not any(
                lock in call_rule.required_locks for lock in scanned_call.lexical_locks
            ):
                message = call_rule.lock_message
            else:
                continue
            finding_token = f"call:{scanned_call.receiver}.{scanned_call.method}"
            finding_key = (rule.rule_id, rel, scanned_call.line, message, finding_token)
            if finding_key in seen_findings:
                continue
            seen_findings.add(finding_key)
            findings.append(
                ArchitectureFinding(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    path=rel,
                    line=scanned_call.line,
                    message=message,
                    snippet=_helpers._line_snippet(lines=lines, line=scanned_call.line),
                    regex=finding_token,
                )
            )


def emit_forbidden_under_lock_findings(
    rule: ArchitectureRule,
    rel: str,
    lines: list[str],
    calls: tuple[_ScannedCall, ...],
    findings: list[ArchitectureFinding],
    seen_findings: set[tuple[str, str, int, str, str]],
) -> None:
    for forbidden_rule in rule.forbidden_under_locks:
        for scanned_call in calls:
            receiver_matches = forbidden_rule.match_any_receiver or (
                scanned_call.receiver in forbidden_rule.receivers
                or any(
                    scanned_call.receiver.endswith(suffix)
                    for suffix in forbidden_rule.receiver_suffixes
                )
            )
            if not receiver_matches or scanned_call.method not in forbidden_rule.methods:
                continue
            matching_lock = next(
                (
                    lock
                    for lock in scanned_call.lexical_locks
                    if lock in forbidden_rule.required_locks
                ),
                None,
            )
            if matching_lock is None:
                continue
            finding_token = f"forbidden-under-lock:{scanned_call.receiver}.{scanned_call.method}"
            finding_key = (
                rule.rule_id,
                rel,
                scanned_call.line,
                forbidden_rule.message,
                finding_token,
            )
            if finding_key in seen_findings:
                continue
            seen_findings.add(finding_key)
            findings.append(
                ArchitectureFinding(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    path=rel,
                    line=scanned_call.line,
                    message=forbidden_rule.message,
                    snippet=_helpers._line_snippet(lines=lines, line=scanned_call.line),
                    regex=finding_token,
                    lock=matching_lock,
                )
            )


def _path_matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    posix_path = Path(path).as_posix()
    return any(_helpers._path_matches_glob(posix_path, pattern) for pattern in patterns)


def _literal_keyword_matches(*, actual: object, expected: object) -> bool:
    """Compare literal keyword values without treating ``False`` as ``0``."""

    return type(actual) is type(expected) and actual == expected


def _lock_level(
    lock_name: str,
    *,
    lock_order: ArchitectureLockOrderRule,
    levels: dict[str, int],
) -> int | None:
    return levels.get(lock_name)
