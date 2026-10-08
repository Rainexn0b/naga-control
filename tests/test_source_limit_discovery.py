import re
from pathlib import Path

import pytest
import test_source_limits as source_limits


def write_python(root: Path, relative_path: str, line_count: int = 1) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# physical line\n" * line_count, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "dependency_directory",
    [
        "node_modules",
        ".opencode/node_modules",
        "src/nested/node_modules",
        "tests/vendor/node_modules/nested/node_modules",
    ],
)
def test_installed_dependencies_are_excluded_anywhere(
    tmp_path: Path, dependency_directory: str
) -> None:
    write_python(tmp_path, f"{dependency_directory}/node-gyp/gyp/oversized.py", 401)
    owned = write_python(tmp_path, "owned.py")

    assert source_limits.discover_python_files(tmp_path) == (owned,)


@pytest.mark.parametrize(
    "opencode_directory",
    [
        ".opencode",
        "nested/.opencode",
        "src/nested/.opencode",
        "tests/vendor/.opencode",
        "buildpython/steps/.opencode",
    ],
)
def test_opencode_directories_are_excluded_anywhere(
    tmp_path: Path, opencode_directory: str
) -> None:
    write_python(tmp_path, f"{opencode_directory}/custom/oversized.py", 401)
    write_python(tmp_path, f"{opencode_directory}/node_modules_custom/oversized.py", 401)
    owned = {
        write_python(tmp_path, "src/naga_control/owned.py", 400),
        write_python(tmp_path, "tests/owned.py", 400),
        write_python(tmp_path, "buildpython/steps/owned.py", 400),
    }

    assert set(source_limits.discover_python_files(tmp_path)) == owned


@pytest.mark.parametrize(
    "relative_path",
    [
        "node_modules.py",
        "node_modules_custom/owned.py",
        "custom_node_modules/owned.py",
        "node_modules-backup/owned.py",
        "Node_modules/owned.py",
        ".opencode_custom/node_modules_custom/owned.py",
        ".opencode_custom/owned.py",
        "custom_opencode/owned.py",
        ".opencode-backup/owned.py",
        ".Opencode/owned.py",
        ".opencode.py",
        "build.py",
        "__pycache__.py",
    ],
)
def test_similar_names_remain_checked(tmp_path: Path, relative_path: str) -> None:
    owned = write_python(tmp_path, relative_path)

    assert source_limits.discover_python_files(tmp_path) == (owned,)


@pytest.mark.parametrize("directory", ["node_modules.py", ".opencode.py"])
def test_python_suffix_directory_preserves_existing_glob_coverage(
    tmp_path: Path, directory: str
) -> None:
    owned = write_python(tmp_path, f"{directory}/owned.py")

    assert set(source_limits.discover_python_files(tmp_path)) == {owned.parent, owned}


@pytest.mark.parametrize(
    "excluded_directory", [".venv", "build", "dist", "generated", "__pycache__"]
)
@pytest.mark.parametrize("prefix", ["", "nested/"])
def test_existing_directory_exclusions_are_preserved(
    tmp_path: Path, excluded_directory: str, prefix: str
) -> None:
    write_python(tmp_path, f"{prefix}{excluded_directory}/oversized.py", 401)
    owned = write_python(tmp_path, "owned.py")

    assert source_limits.discover_python_files(tmp_path) == (owned,)


@pytest.mark.parametrize(
    "relative_path",
    [
        "root_tool.py",
        "scripts/maintenance.py",
        "src/naga_control/owned.py",
        "buildpython/steps/owned.py",
        "tests/owned.py",
        "tests/hardware/owned.py",
        ".opencode_custom/custom/owned.py",
        ".opencode.py",
        ".hidden/custom.py",
    ],
)
@pytest.mark.parametrize("line_count", [400, 401])
def test_owned_files_retain_the_physical_line_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative_path: str, line_count: int
) -> None:
    owned = write_python(tmp_path, relative_path, line_count)
    monkeypatch.setattr(source_limits, "ROOT", tmp_path)

    assert source_limits.discover_python_files(tmp_path) == (owned,)
    if line_count == 401:
        with pytest.raises(AssertionError, match=re.escape(f"{relative_path} has 401 lines")):
            source_limits.test_python_files_do_not_exceed_400_lines(owned)
    else:
        source_limits.test_python_files_do_not_exceed_400_lines(owned)
