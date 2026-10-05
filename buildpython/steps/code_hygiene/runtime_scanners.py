from __future__ import annotations

import ast
from pathlib import Path

from .models import HygieneIssue

_SOURCE_PARSE_ERRORS = (OSError, SyntaxError, ValueError)

_RUNTIME_COPY_WATCH_PATHS = [
    "src/naga_control/application/",
    "src/naga_control/adapters/evdev/",
    "src/naga_control/adapters/uinput/",
    "src/naga_control/service/",
]

_RUNTIME_COPY_FUNCTION_PREFIXES = (
    "run_",
    "read_",
    "process_",
    "handle_",
    "forward_",
    "consume_",
    "dispatch_",
    "apply_",
    "_apply_",
    "create_",
    "_create_",
    "refresh_",
    "update_",
    "start_",
    "_start_",
    "poll_",
    "_poll_",
)

_RUNTIME_COPY_SOURCE_TOKENS = (
    "frame",
    "event",
    "mapping",
    "binding",
    "profile",
    "capabilities",
    "state",
    "buffer",
)


_LOOP_NODES = (ast.For, ast.AsyncFor, ast.While)


def _detect_runtime_copy_hotspots(path: Path, root: Path) -> list[HygieneIssue]:
    issues: list[HygieneIssue] = []
    rel = str(path.relative_to(root))

    if not any(rel.startswith(prefix) for prefix in _RUNTIME_COPY_WATCH_PATHS):
        return issues

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
    except _SOURCE_PARSE_ERRORS:
        return issues

    lines = text.splitlines()

    def visit(node: ast.AST, *, current_function: str | None, loop_depth: int) -> None:
        next_function = current_function
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            next_function = node.name

        next_loop_depth = loop_depth + 1 if isinstance(node, _LOOP_NODES) else loop_depth

        if isinstance(node, ast.Call):
            issue = _runtime_copy_issue_for_call(
                call=node,
                rel=rel,
                text=text,
                lines=lines,
                current_function=next_function,
                loop_depth=next_loop_depth,
            )
            if issue is not None:
                issues.append(issue)

        for child in ast.iter_child_nodes(node):
            visit(child, current_function=next_function, loop_depth=next_loop_depth)

    visit(tree, current_function=None, loop_depth=0)
    return issues


def _runtime_copy_issue_for_call(
    *,
    call: ast.Call,
    rel: str,
    text: str,
    lines: list[str],
    current_function: str | None,
    loop_depth: int,
) -> HygieneIssue | None:
    if current_function is None:
        return None

    if loop_depth <= 0 and not _is_runtime_hot_function(current_function):
        return None

    copy_kind, source_text, call_text = _runtime_copy_signature(call=call, text=text)
    if copy_kind is None or source_text is None or call_text is None:
        return None

    source_lower = source_text.lower()
    if not any(token in source_lower for token in _RUNTIME_COPY_SOURCE_TOKENS):
        return None

    line = lines[call.lineno - 1].strip() if 0 < call.lineno <= len(lines) else ""
    return HygieneIssue(
        category="runtime_copy_hotspot",
        path=rel,
        line=call.lineno,
        message=(
            f"{copy_kind} inside runtime path `{current_function}` on `{source_text}` - "
            "consider reference reuse or reusable buffers"
        ),
        snippet=line[:120],
    )


def _runtime_copy_signature(
    *, call: ast.Call, text: str
) -> tuple[str | None, str | None, str | None]:
    call_text = ast.get_source_segment(text, call) or ast.unparse(call)

    if (
        isinstance(call.func, ast.Name)
        and call.func.id == "dict"
        and len(call.args) == 1
        and not call.keywords
    ):
        source = ast.get_source_segment(text, call.args[0]) or ast.unparse(call.args[0])
        return "dict(...) copy", source, call_text

    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "copy"
        and not call.args
        and not call.keywords
    ):
        source = ast.get_source_segment(text, call.func.value) or ast.unparse(call.func.value)
        return ".copy() clone", source, call_text

    return None, None, None


def _is_runtime_hot_function(name: str) -> bool:
    lowered = name.lower()
    return any(lowered.startswith(prefix) for prefix in _RUNTIME_COPY_FUNCTION_PREFIXES)
