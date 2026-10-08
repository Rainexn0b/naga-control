from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".opencode", ".venv", "build", "dist", "generated"}


def discover_python_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in root.rglob("*.py")
        if EXCLUDED_PARTS.isdisjoint(path.relative_to(root).parts)
        and "__pycache__" not in path.parts
        and "node_modules" not in path.relative_to(root).parts[:-1]
    )


PYTHON_FILES = discover_python_files(ROOT)


@pytest.mark.parametrize("path", PYTHON_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_python_files_do_not_exceed_400_lines(path: Path) -> None:
    line_count = len(path.read_text(encoding="utf-8").splitlines())
    assert line_count <= 400, f"{path.relative_to(ROOT)} has {line_count} lines"
