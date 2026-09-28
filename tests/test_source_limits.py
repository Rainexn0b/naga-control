from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".venv", "build", "dist", "generated"}
PYTHON_FILES = tuple(
    path
    for path in ROOT.rglob("*.py")
    if EXCLUDED_PARTS.isdisjoint(path.relative_to(ROOT).parts) and "__pycache__" not in path.parts
)


@pytest.mark.parametrize("path", PYTHON_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_python_files_do_not_exceed_400_lines(path: Path) -> None:
    line_count = len(path.read_text(encoding="utf-8").splitlines())
    assert line_count <= 400, f"{path.relative_to(ROOT)} has {line_count} lines"
