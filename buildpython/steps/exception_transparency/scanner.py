from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from ..quality_exceptions import explanation_for_quality_exception_step, python_comments
from .baseline import iter_python_files
from .diagnostic_signals import contains_reraise, contains_signal, contains_traceback_logging
from .handler_identity import (
    _BASE_EXCEPTION_NAMES,
    collect_exception_aliases,
    handler_type_names,
    is_broad_handler,
)
from .models import ExceptionTransparencyAnnotationInventory, ExceptionTransparencyFinding

MESSAGE_BY_CATEGORY = {
    "naked_except": "Naked except catches KeyboardInterrupt/SystemExit; replace it with a specific exception type.",
    "baseexception_catch": "BaseException catch includes cancellation and process interrupts; review cleanup/rethrow before narrowing.",
    "broad_except_total": "Broad exception boundary; review its contract before narrowing.",
    "broad_except_traceback_logged": "Broad exception catch records a traceback; still a narrowing candidate.",
    "broad_except_logged_no_traceback": "Broad exception catch signals failure without recording a traceback.",
    "broad_except_unlogged": "Broad exception catch has no recognized local diagnostic; review downstream propagation or intentional fallback.",
}

QUALITY_EXCEPTION_STEP_SLUG = "exception-transparency"
_PARSE_SKIP_EXCEPTIONS = (SyntaxError, ValueError)
_SOURCE_READ_SKIP_EXCEPTIONS = (OSError,)


def make_finding(
    category: str, rel_path: str, handler: ast.ExceptHandler, lines: list[str]
) -> ExceptionTransparencyFinding:
    snippet = lines[handler.lineno - 1].strip() if 0 < handler.lineno <= len(lines) else ""
    return ExceptionTransparencyFinding(
        category=category,
        path=rel_path,
        line=handler.lineno,
        message=MESSAGE_BY_CATEGORY[category],
        snippet=snippet[:120],
    )


def line_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def inventory_subtree(rel_path: str) -> str:
    normalized = str(rel_path or "").replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return normalized
    if len(parts) >= 3 and parts[:2] == ["src", "naga_control"]:
        return "/".join(parts[:3])
    if len(parts) >= 2 and parts[0] == "buildpython":
        return "/".join(parts[:2])
    return parts[0]


def _sorted_inventory_rows(counter: Counter[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def scan_annotation_inventory(
    source: str, *, rel_path: str
) -> ExceptionTransparencyAnnotationInventory:
    subtree = inventory_subtree(rel_path) or str(rel_path)
    total = 0
    for comment in python_comments(source).values():
        explanation = explanation_for_quality_exception_step(
            comment,
            step_slug=QUALITY_EXCEPTION_STEP_SLUG,
        )
        if explanation:
            total += 1

    counter: Counter[str] = Counter()
    if total:
        counter[subtree] = total
    return ExceptionTransparencyAnnotationInventory(
        total=total, by_subtree=_sorted_inventory_rows(counter)
    )


def has_quality_exception_waiver(
    lines: list[str], handler: ast.ExceptHandler, *, comments: dict[int, str] | None = None
) -> bool:
    if not (0 < handler.lineno <= len(lines)):
        return False

    if comments is None:
        comments = python_comments("\n".join(lines))
    handler_line = lines[handler.lineno - 1]
    same_line_explanation = explanation_for_quality_exception_step(
        comments.get(handler.lineno),
        step_slug=QUALITY_EXCEPTION_STEP_SLUG,
    )
    if same_line_explanation is not None:
        return bool(same_line_explanation)

    # Scan back through any run of consecutive comment lines at the handler's
    # indent level (up to 10 lines).  This allows multi-line quality-exception
    # explanations: the tag may appear on the first line of a block comment
    # whose last line sits immediately before the `except`.
    handler_indent = line_indent(handler_line)
    for look_back in range(1, 11):
        preceding_index = handler.lineno - 1 - look_back
        if preceding_index < 0:
            break
        preceding_line = lines[preceding_index]
        if not preceding_line.lstrip().startswith("#"):
            break
        if line_indent(preceding_line) != handler_indent:
            break
        explanation = explanation_for_quality_exception_step(
            comments.get(preceding_index + 1),
            step_slug=QUALITY_EXCEPTION_STEP_SLUG,
        )
        if explanation is not None:
            return bool(explanation)
    return False


def scan_python_source(source: str, *, rel_path: str) -> list[ExceptionTransparencyFinding]:
    try:
        tree = ast.parse(source)
    except _PARSE_SKIP_EXCEPTIONS:
        return []

    lines = source.split("\n")
    comments = python_comments(source)
    aliases = collect_exception_aliases(tree)
    findings: list[ExceptionTransparencyFinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Try, ast.TryStar)):
            continue
        handlers = getattr(node, "handlers", [])
        for handler in handlers:
            if not isinstance(handler, ast.ExceptHandler) or not is_broad_handler(handler, aliases):
                continue

            if handler.type is None:
                findings.append(make_finding("naked_except", rel_path, handler, lines))
            else:
                type_names = handler_type_names(handler.type, aliases)
                if type_names & _BASE_EXCEPTION_NAMES:
                    findings.append(make_finding("baseexception_catch", rel_path, handler, lines))

            if has_quality_exception_waiver(lines, handler, comments=comments):
                continue

            findings.append(make_finding("broad_except_total", rel_path, handler, lines))

            if contains_reraise(handler.body):
                continue
            if contains_traceback_logging(handler.body):
                findings.append(
                    make_finding("broad_except_traceback_logged", rel_path, handler, lines)
                )
            elif contains_signal(handler.body):
                findings.append(
                    make_finding("broad_except_logged_no_traceback", rel_path, handler, lines)
                )
            else:
                findings.append(make_finding("broad_except_unlogged", rel_path, handler, lines))

    return findings


def collect_findings(root: Path) -> list[ExceptionTransparencyFinding]:
    findings: list[ExceptionTransparencyFinding] = []
    for path in iter_python_files(root):
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except _SOURCE_READ_SKIP_EXCEPTIONS:
            continue
        rel_path = str(path.relative_to(root))
        findings.extend(scan_python_source(source, rel_path=rel_path))
    return findings


def collect_annotation_inventory(root: Path) -> ExceptionTransparencyAnnotationInventory:
    total = 0
    subtree_counts: Counter[str] = Counter()
    for path in iter_python_files(root):
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except _SOURCE_READ_SKIP_EXCEPTIONS:
            continue
        rel_path = str(path.relative_to(root))
        inventory = scan_annotation_inventory(source, rel_path=rel_path)
        total += inventory.total
        for subtree, count in inventory.by_subtree:
            subtree_counts[subtree] += count
    return ExceptionTransparencyAnnotationInventory(
        total=total,
        by_subtree=_sorted_inventory_rows(subtree_counts),
    )


def count_broad_waivers(root: Path) -> int:
    """Count broad exception handlers with valid @quality-exception exception-transparency waivers."""
    total = 0
    for path in iter_python_files(root):
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (*_PARSE_SKIP_EXCEPTIONS, *_SOURCE_READ_SKIP_EXCEPTIONS):
            continue
        lines = source.split("\n")
        comments = python_comments(source)
        aliases = collect_exception_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Try, ast.TryStar)):
                continue
            for handler in getattr(node, "handlers", []):
                if not isinstance(handler, ast.ExceptHandler) or not is_broad_handler(
                    handler, aliases
                ):
                    continue
                names = handler_type_names(handler.type, aliases)
                if handler.type is None or names & _BASE_EXCEPTION_NAMES:
                    continue
                if has_quality_exception_waiver(lines, handler, comments=comments):
                    total += 1
    return total
