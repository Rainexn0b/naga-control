"""Complete archive-path/layout checks and data-only pin grammar regressions."""

from pathlib import Path

import pytest

from buildpython.openrazer_packages.pin import read_pin
from tests.openrazer_installer_fakes import NAMES, ROLES, TAG, harness, operation_name


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize(
    "path",
    [
        "/absolute",
        "../traversal",
        "usr/../traversal",
        "usr/./ambiguous",
        "usr//ambiguous",
        "././ambiguous",
        "usr/back\\slash",
        "usr/control\tchar",
        "usr/control\rchar",
        "usr/control\x7fchar",
    ],
)
def test_every_archive_rejects_unsafe_paths(tmp_path: Path, name: str, path: str) -> None:
    fake = harness(tmp_path)
    metadata = fake.metadata()
    metadata[name]["members"].append(path)
    fake.configure(metadata=metadata)
    result, commands = fake.run("--yes", "--version", TAG)
    assert result.returncode != 0
    assert "unsafe or duplicate archive member" in result.stderr
    assert not any(operation_name(command) in {"sudo", "systemctl"} for command in commands)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("duplicate", ["./unrelated", "unrelated/"])
def test_duplicate_normalized_paths_not_only_required_members(
    tmp_path: Path, name: str, duplicate: str
) -> None:
    fake = harness(tmp_path)
    metadata = fake.metadata()
    metadata[name]["members"].extend(["unrelated", duplicate])
    fake.configure(metadata=metadata)
    result, commands = fake.run("--yes", "--version", TAG)
    assert result.returncode != 0
    assert "unsafe or duplicate archive member" in result.stderr
    assert not any(operation_name(command) in {"sudo", "systemctl"} for command in commands)


@pytest.mark.parametrize("name", NAMES)
def test_all_archives_require_buildinfo(tmp_path: Path, name: str) -> None:
    fake = harness(tmp_path)
    metadata = fake.metadata()
    metadata[name]["members"].remove(".BUILDINFO")
    fake.configure(metadata=metadata)
    result, commands = fake.run("--yes", "--version", TAG)
    assert result.returncode != 0
    assert "missing package metadata/provenance" in result.stderr
    assert not any(operation_name(command) in {"sudo", "systemctl"} for command in commands)


@pytest.mark.parametrize("name", NAMES[1:])
@pytest.mark.parametrize("problem", ["missing", "wrong-minor", "extra-minor", "extra-minor-dir"])
def test_python_payload_must_match_declared_bounds(tmp_path: Path, name: str, problem: str) -> None:
    fake = harness(tmp_path)
    metadata = fake.metadata()
    item = metadata[name]
    init = next(member for member in item["members"] if member.endswith("/__init__.py"))
    if problem == "missing":
        item["members"].remove(init)
    elif problem == "wrong-minor":
        item["members"][item["members"].index(init)] = init.replace("3.14", "3.13")
    elif problem == "extra-minor":
        item["members"].append("usr/lib/python3.13/site-packages/other.py")
    else:
        item["members"].append("usr/lib/python3.13/site-packages/")
    fake.configure(metadata=metadata)
    result, commands = fake.run("--yes", "--version", TAG)
    assert result.returncode != 0
    assert "invalid package metadata or host Python" in result.stderr
    assert not any(operation_name(command) in {"sudo", "systemctl"} for command in commands)


def test_optional_dot_prefix_and_directory_suffix_are_normalized(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    metadata = fake.metadata()
    for item in metadata.values():
        item["members"] = ["./", "./usr/", *["./" + name for name in item["members"]]]
    fake.configure(metadata=metadata)
    result, _ = fake.run("--yes", "--version", TAG)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "branch", ["feature/recipe-1", "release_safe.1", "bad..branch", "../bad", "bad+branch"]
)
def test_branch_grammar_matches_canonical_pin_parser(tmp_path: Path, branch: str) -> None:
    fake = harness(tmp_path)
    path = fake.remote / "pin.conf"
    path.write_text(path.read_text().replace("test-pr-2904-edualb", branch))
    accepted = ".." not in branch and "+" not in branch
    if accepted:
        assert read_pin(path)["OPENRAZER_BRANCH"] == branch
    else:
        with pytest.raises(ValueError):
            read_pin(path)
    result, commands = fake.run("--yes", "--version", TAG)
    assert (result.returncode == 0) == accepted, result.stderr
    if not accepted:
        assert not any(
            operation_name(command) in {"sudo", "systemctl", "bsdtar"} for command in commands
        )


def test_plus_pkgver_is_valid_grammar_but_fixed_guard_needs_deliberate_review(
    tmp_path: Path,
) -> None:
    fake = harness(tmp_path)
    path = fake.remote / "pin.conf"
    path.write_text(
        path.read_text().replace(
            'OPENRAZER_PKGVER="3.12.1.pr2904.fix2"', 'OPENRAZER_PKGVER="3.12.1.pr2904.fix2+fixture"'
        )
    )
    assert read_pin(path)["OPENRAZER_PKGVER"].endswith("+fixture")
    result, commands = fake.run("--yes", "--version", TAG)
    assert result.returncode != 0
    assert "source pin mismatch" in result.stderr
    assert not any(
        operation_name(command) in {"sudo", "systemctl", "bsdtar"} for command in commands
    )
    assert ROLES[0] in result.stdout
