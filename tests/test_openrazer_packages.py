from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import unittest
from collections.abc import Sequence
from pathlib import Path

import pytest

from buildpython.openrazer_packages import check_tests
from buildpython.openrazer_packages.pin import main, package_filenames, read_pin
from tests.release_assets_fakes import PIN_PATH, ROOT

RECIPE = ROOT / "buildpython/openrazer_packages"


def test_pin_exact_authorized_baseline_and_safe_export(tmp_path: Path) -> None:
    pin = read_pin(PIN_PATH)
    assert pin == {
        "OPENRAZER_FORK_REPO": "Rainexn0b/openrazer",
        "OPENRAZER_COMMIT": "26b0eeb5ed70d638fa3528851adcd5e58369a7f5",
        "OPENRAZER_BRANCH": "test-pr-2904-edualb",
        "OPENRAZER_PKGVER": "3.12.1.pr2904.fix2",
        "OPENRAZER_PKGREL": "1",
    }
    assert main(["--pin", str(PIN_PATH), "--github-env", str(tmp_path / "env")]) == 0
    assert (tmp_path / "env").read_text() == "".join(f"{k}={v}\n" for k, v in pin.items())
    assert len(package_filenames(pin)) == 3


@pytest.mark.parametrize(
    "mutation",
    [
        'OPENRAZER_COMMIT="$(touch BAD)"',
        'OPENRAZER_FORK_REPO="../openrazer"',
        'OPENRAZER_PKGVER="3.0-1"',
        'OPENRAZER_PKGREL="0"',
        'OPENRAZER_BRANCH="a`id`"',
        'EXTRA="value"',
        'export OPENRAZER_COMMIT="a"',
    ],
)
def test_malformed_pin_rejected_before_any_export(tmp_path: Path, mutation: str) -> None:
    path = tmp_path / "pin.conf"
    key = mutation.split("=", 1)[0]
    lines = PIN_PATH.read_text().splitlines()
    if key in read_pin(PIN_PATH):
        lines = [mutation if line.startswith(key + "=") else line for line in lines]
    else:
        lines.append(mutation)
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(SystemExit):
        main(["--pin", str(path), "--shell", "--github-env", str(tmp_path / "env")])
    assert not (tmp_path / "env").exists()


def test_missing_pin_field_rejected(tmp_path: Path) -> None:
    path = tmp_path / "pin.conf"
    path.write_text("\n".join(PIN_PATH.read_text().splitlines()[:-1]))
    with pytest.raises(ValueError, match="Missing"):
        read_pin(path)


def test_duplicate_pin_assignment_is_not_silently_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "pin.conf"
    path.write_text(PIN_PATH.read_text() + 'OPENRAZER_PKGREL="2"\n')
    with pytest.raises(ValueError, match="duplicate"):
        read_pin(path)


def recipe_shell(script: str, directory: Path) -> subprocess.CompletedProcess[str]:
    # Source recipe metadata only. Fake make/install prevent all package build/install work.
    environment = {
        **os.environ,
        "startdir": str(RECIPE),
        "srcdir": str(directory),
        "pkgdir": str(directory / "pkg"),
        "PATH": f"{Path(sys.executable).parent}:{os.environ['PATH']}",
    }
    return subprocess.run(
        ["bash", "-c", 'set -eu; source "$startdir/PKGBUILD"; ' + script],
        env=environment,
        cwd=directory,
        text=True,
        capture_output=True,
    )


def test_recipe_consumes_canonical_fields_and_bounds_both_python_packages(tmp_path: Path) -> None:
    result = recipe_shell(
        'printf "%s\\n" "$url" "$pkgver-$pkgrel" "${source[0]}"; '
        "make() { :; }; _record_source() { :; }; "
        'package_openrazer-daemon-local; printf "%s\\n" "${depends[@]}"; '
        'package_python-openrazer-local; printf "%s\\n" "${depends[@]}"',
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    pin = read_pin(PIN_PATH)
    assert f"https://github.com/{pin['OPENRAZER_FORK_REPO']}" in result.stdout
    assert f"#commit={pin['OPENRAZER_COMMIT']}" in result.stdout
    assert f"{pin['OPENRAZER_PKGVER']}-{pin['OPENRAZER_PKGREL']}" in result.stdout
    minor = sys.version_info.minor
    assert result.stdout.count(f"python>=3.{minor}\n") == 2
    assert result.stdout.count(f"python<3.{minor + 1}\n") == 2


def test_recipe_local_helper_digests_match_current_bytes(tmp_path: Path) -> None:
    result = recipe_shell('printf "%s\\n" "${source[@]}" "${sha256sums[@]}"', tmp_path)
    assert result.returncode == 0, result.stderr
    source, dkms_helper, sysusers_helper, git_checksum, dkms_checksum, sysusers_checksum = (
        result.stdout.splitlines()
    )
    assert source.startswith("openrazer::git+")
    assert git_checksum == "SKIP"
    assert (dkms_helper, sysusers_helper) == ("dkms-make", "openrazer.conf")
    for helper, expected in ((dkms_helper, dkms_checksum), (sysusers_helper, sysusers_checksum)):
        assert hashlib.sha256((RECIPE / helper).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("valid", [True, False])
def test_source_sha_verified_before_known_arch_transforms(tmp_path: Path, valid: bool) -> None:
    paths = (
        "daemon/openrazer_daemon/daemon.py",
        "install_files/udev/99-razer.rules",
        "install_files/udev/razer_mount",
    )
    for relative in paths:
        path = tmp_path / "openrazer" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("plugdev\n")
    sha = read_pin(PIN_PATH)["OPENRAZER_COMMIT"] if valid else "0" * 40
    result = recipe_shell(f"git() {{ printf '%s\\n' {sha}; }}; prepare", tmp_path)
    assert result.returncode == (0 if valid else 1)
    for relative in paths:
        assert (tmp_path / "openrazer" / relative).read_text() == (
            "openrazer\n" if valid else "plugdev\n"
        )


@pytest.mark.parametrize("missing", ["cc", "clang"])
def test_regression_compiler_is_required(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing: str,
) -> None:
    def find(tool: str) -> str | None:
        return None if tool == missing else "/fake"

    monkeypatch.setattr(check_tests.shutil, "which", find)
    assert check_tests.main() == 1
    assert f"Required regression compiler missing: {missing}" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("count", "skip", "exit_code"), [(55, False, 0), (55, True, 1), (54, False, 1)]
)
def test_focused_suite_cannot_pass_with_silent_skips_or_missing_tests(
    monkeypatch: pytest.MonkeyPatch,
    count: int,
    skip: bool,
    exit_code: int,
) -> None:
    result = unittest.TestResult()
    result.testsRun = count
    if skip:
        result.addSkip(unittest.FunctionTestCase(lambda: None), "compiler absent")

    def find(tool: str) -> str:
        return "/fake"

    def load(_self: unittest.TestLoader, names: Sequence[str]) -> unittest.TestSuite:
        assert tuple(names) == check_tests.TEST_MODULES
        return unittest.TestSuite()

    def run(_self: unittest.TextTestRunner, suite: unittest.TestSuite) -> unittest.TestResult:
        return result

    monkeypatch.setattr(check_tests.shutil, "which", find)
    monkeypatch.setattr(unittest.TestLoader, "loadTestsFromNames", load)
    monkeypatch.setattr(unittest.TextTestRunner, "run", run)
    assert check_tests.main() == exit_code


def test_downstream_dkms_helper_and_recipe_declare_compiler_prerequisites() -> None:
    recipe = (RECIPE / "PKGBUILD").read_text()
    helper = (RECIPE / "dkms-make").read_text()
    assert "'clang' 'llvm' 'lld'" in recipe
    assert 'install -m755 "$srcdir/dkms-make"' in recipe
    for tool in (
        "clang",
        "ld.lld",
        "llvm-ar",
        "llvm-nm",
        "llvm-objcopy",
        "llvm-objdump",
        "llvm-readelf",
        "llvm-strip",
    ):
        assert tool in helper
    assert "Missing kernel headers/config" in helper
    result = subprocess.run(["sh", str(RECIPE / "dkms-make")], capture_output=True, text=True)
    assert result.returncode == 1
    assert "Usage:" in result.stderr


def test_clang_kernel_missing_llvm_tool_is_clear_preflight_error(tmp_path: Path) -> None:
    headers = tmp_path / "modules/fixture/build"
    headers.mkdir(parents=True)
    (headers / ".config").write_text("CONFIG_CC_IS_CLANG=y\n")
    script = tmp_path / "dkms-make"
    script.write_text(
        (RECIPE / "dkms-make").read_text().replace("/lib/modules", str(tmp_path / "modules"))
    )
    tools = tmp_path / "tools"
    tools.mkdir()
    # Only fake clang and ld.lld exist. The helper must stop before invoking make.
    for tool in ("clang", "ld.lld", "grep"):
        path = tools / tool
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    result = subprocess.run(
        ["/bin/sh", str(script), "fixture"],
        env={"PATH": str(tools)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "Clang kernel requires llvm-ar (install clang, llvm and lld)." in result.stderr
