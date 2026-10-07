from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from . import _architecture_validation_helpers as _helpers
from ._architecture_validation_call_scan import _scan_python_calls
from ._architecture_validation_models import (
    ArchitectureFinding,
    ArchitectureRule,
    ArchitectureScanResult,
)
from ._architecture_validation_scan_calls import (
    emit_call_findings,
    emit_forbidden_under_lock_findings,
    emit_lock_order_findings,
)


def scan_architecture(root: Path, rules: Iterable[ArchitectureRule]) -> ArchitectureScanResult:
    findings: list[ArchitectureFinding] = []
    seen_findings: set[tuple[str, str, int, str, str]] = set()
    scanned_files: set[str] = set()
    scanned_python_signals: dict[
        str, tuple[tuple[_helpers._ScannedImport, ...], tuple[_helpers._ScannedAttribute, ...]]
    ] = {}
    scanned_python_assignments: dict[str, tuple[_helpers._ScannedAssignment, ...]] = {}
    scanned_python_calls: dict[str, tuple[_helpers._ScannedCall, ...]] = {}
    scanned_python_lock_acquisitions: dict[str, tuple[_helpers._ScannedLockAcquisition, ...]] = {}
    rules_list = list(rules)
    source_cache: dict[str, str] = {}

    for rule in rules_list:
        for path in _helpers._iter_rule_files(root=root, rule=rule):
            rel = _helpers._rel_path(root, path)
            scanned_files.add(rel)
            text = source_cache.get(rel)
            if text is None:
                try:
                    text = path.read_text(encoding="utf-8")
                    if path.suffix == ".py":
                        ast.parse(text, filename=rel)
                except (OSError, UnicodeError, SyntaxError) as exc:
                    raise ValueError(
                        f"Architecture scan cannot read or parse {rel}: {exc}"
                    ) from exc
                source_cache[rel] = text

            lines = text.splitlines()
            for pattern in rule.patterns:
                for match in pattern.compiled.finditer(text):
                    line = _helpers._line_number(text=text, offset=match.start())
                    snippet = _helpers._line_snippet(lines=lines, line=line)
                    finding_key = (rule.rule_id, rel, line, pattern.message, pattern.regex)
                    if finding_key in seen_findings:
                        continue
                    seen_findings.add(finding_key)
                    findings.append(
                        ArchitectureFinding(
                            rule_id=rule.rule_id,
                            severity=rule.severity,
                            path=rel,
                            line=line,
                            message=pattern.message,
                            snippet=snippet,
                            regex=pattern.regex,
                        )
                    )

            if rule.imports or rule.attributes:
                signals = scanned_python_signals.get(rel)
                if signals is None:
                    signals = _helpers._scan_python_signals(text, relative_path=rel)
                    scanned_python_signals[rel] = signals
                imports, attributes = signals

            assignments: tuple[_helpers._ScannedAssignment, ...] = ()
            if rule.assignments:
                cached_assignments = scanned_python_assignments.get(rel)
                if cached_assignments is None:
                    cached_assignments = _helpers._scan_python_assignments(text)
                    scanned_python_assignments[rel] = cached_assignments
                assignments = cached_assignments

            calls: tuple[_helpers._ScannedCall, ...] = ()
            if rule.calls or rule.forbidden_under_locks:
                cached_calls = scanned_python_calls.get(rel)
                if cached_calls is None:
                    cached_calls = _scan_python_calls(text, relative_path=rel)
                    scanned_python_calls[rel] = cached_calls
                calls = cached_calls

            if rule.imports:
                for import_rule in rule.imports:
                    finding_token = f"import:{import_rule.module}"
                    for scanned_import in imports:
                        if not _helpers._module_matches_import_rule(
                            scanned_import.module, import_rule.module
                        ):
                            continue

                        line = scanned_import.line
                        snippet = _helpers._line_snippet(lines=lines, line=line)
                        finding_key = (rule.rule_id, rel, line, import_rule.message, finding_token)
                        if finding_key in seen_findings:
                            continue
                        seen_findings.add(finding_key)
                        findings.append(
                            ArchitectureFinding(
                                rule_id=rule.rule_id,
                                severity=rule.severity,
                                path=rel,
                                line=line,
                                message=import_rule.message,
                                snippet=snippet,
                                regex=finding_token,
                            )
                        )

            if rule.attributes:
                for attribute_rule in rule.attributes:
                    finding_token = f"attribute:{attribute_rule.name}"
                    for scanned_attribute in attributes:
                        if scanned_attribute.name != attribute_rule.name:
                            continue

                        line = scanned_attribute.line
                        snippet = _helpers._line_snippet(lines=lines, line=line)
                        finding_key = (
                            rule.rule_id,
                            rel,
                            line,
                            attribute_rule.message,
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
                                line=line,
                                message=attribute_rule.message,
                                snippet=snippet,
                                regex=finding_token,
                            )
                        )

            for assignment_rule in rule.assignments:
                for scanned_assignment in assignments:
                    target_matches = scanned_assignment.target in assignment_rule.targets or any(
                        scanned_assignment.target.endswith(suffix)
                        for suffix in assignment_rule.target_suffixes
                    )
                    if not target_matches:
                        continue

                    finding_token = f"assignment:{scanned_assignment.target}"
                    finding_key = (
                        rule.rule_id,
                        rel,
                        scanned_assignment.line,
                        assignment_rule.message,
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
                            line=scanned_assignment.line,
                            message=assignment_rule.message,
                            snippet=_helpers._line_snippet(
                                lines=lines, line=scanned_assignment.line
                            ),
                            regex=finding_token,
                        )
                    )

            if rule.lock_orders:
                acquisitions = scanned_python_lock_acquisitions.get(rel)
                if acquisitions is None:
                    acquisitions = _helpers._scan_python_lock_acquisitions(text)
                    scanned_python_lock_acquisitions[rel] = acquisitions
                emit_lock_order_findings(rule, rel, lines, acquisitions, findings, seen_findings)

            emit_call_findings(rule, rel, lines, calls, findings, seen_findings)
            emit_forbidden_under_lock_findings(rule, rel, lines, calls, findings, seen_findings)

    findings.sort(key=lambda item: (item.severity != "error", item.path, item.line, item.rule_id))
    return ArchitectureScanResult(
        findings=tuple(findings),
        scanned_files=len(scanned_files),
        rules_checked=len(rules_list),
    )
