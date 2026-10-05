from __future__ import annotations

import ast
import io
import re
import tokenize
from collections import Counter
from pathlib import Path

from ...utils.paths import repo_root
from .baseline import MARKERS, REF_EXTS

COMMENTED_CODE_RE = re.compile(
    r"^\s*#\s*(def |class |import |from |if |elif |else:|for |while |try:|except |with |return |raise )"
)
_MARKER_RES = {marker: re.compile(rf"\b{re.escape(marker)}\b") for marker in MARKERS}


def _comment_and_docstring_lines(text: str) -> list[tuple[int, str]]:
    """Exclude ordinary string constants, especially the analyzer's own vocabulary."""
    try:
        lines = [
            (token.start[0], token.string)
            for token in tokenize.generate_tokens(io.StringIO(text).readline)
            if token.type == tokenize.COMMENT
        ]
        tree = ast.parse(text)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []
    source_lines = text.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if ast.get_docstring(node, clean=False) is None:
            continue
        expression = node.body[0]
        if isinstance(expression, ast.Expr) and isinstance(expression.value, ast.Constant):
            lines.extend(
                (index + 1, source_lines[index])
                for index in range(
                    expression.lineno - 1, expression.end_lineno or expression.lineno
                )
            )
    return sorted(lines)


def iter_source_files() -> list[Path]:
    root = repo_root()
    files: list[Path] = []
    for name in ("src/naga_control", "buildpython", "scripts", "tests"):
        for path in (root / name).rglob("*.py"):
            if "__pycache__" not in path.parts:
                files.append(path)

    return files


def scan_one_file(
    *,
    file: Path,
    root: Path,
    counts: Counter[str],
    counts_by_file_marker: Counter[tuple[str, str]],
    marker_hits: list[str],
    commented_code_hits: list[str],
    max_marker_hits: int = 200,
    max_commented_hits: int = 200,
) -> None:
    try:
        text = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    rel = file.relative_to(root)
    rel_str = str(rel)
    source_lines = text.splitlines()
    for idx, line in _comment_and_docstring_lines(text):
        for marker in MARKERS:
            if _MARKER_RES[marker].search(line) is None:
                continue
            counts[marker] += 1
            counts_by_file_marker[(rel_str, marker)] += 1
            if len(marker_hits) < max_marker_hits:
                marker_hits.append(f"{rel}:{idx}: {source_lines[idx - 1].strip()}")

        if COMMENTED_CODE_RE.match(line) and len(commented_code_hits) < max_commented_hits:
            commented_code_hits.append(f"{rel}:{idx}: {line.strip()}")


def scan_source_files(
    files: list[Path], *, root: Path
) -> tuple[Counter[str], Counter[tuple[str, str]], list[str], list[str]]:
    counts: Counter[str] = Counter()
    counts_by_file_marker: Counter[tuple[str, str]] = Counter()
    marker_hits: list[str] = []
    commented_code_hits: list[str] = []
    for file in files:
        scan_one_file(
            file=file,
            root=root,
            counts=counts,
            counts_by_file_marker=counts_by_file_marker,
            marker_hits=marker_hits,
            commented_code_hits=commented_code_hits,
        )
    return counts, counts_by_file_marker, marker_hits, commented_code_hits


def top_marker_files(
    counts_by_file_marker: Counter[tuple[str, str]],
) -> dict[str, list[tuple[str, int]]]:
    grouped: dict[str, Counter[str]] = {marker: Counter() for marker in MARKERS}
    for (path_str, marker), count in counts_by_file_marker.items():
        grouped.setdefault(marker, Counter())[path_str] += count
    return {marker: grouped[marker].most_common(10) for marker in MARKERS if grouped.get(marker)}


def find_ref_files(*, root: Path) -> list[str]:
    ref_files: list[str] = []
    for name in ("src/naga_control", "buildpython", "scripts", "tests"):
        for ext in REF_EXTS:
            for path in (root / name).rglob(f"*{ext}"):
                if "__pycache__" not in path.parts:
                    ref_files.append(str(path.relative_to(root)))
    return ref_files
