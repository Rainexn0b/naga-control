"""Main inventory byte safety and explicit native first-install gate."""

from pathlib import Path

import pytest

from tests.installer_app_fakes import (
    assert_private_cleanup,
    installed_image,
    seed_previous,
)
from tests.installer_openrazer_offer_fakes import (
    OPENSUSE_OS,
    UBUNTU_OS,
    offer_harness,
    write_os,
)
from tests.openrazer_installer_fakes import TAG, InstallerHarness

ARCH_OS = 'NAME="Arch Linux"\nID=arch\nBUILD_ID=rolling\n'
FEDORA_OS = 'NAME="Fedora Linux"\nVERSION_ID="42"\nID=fedora\n'


def _ubuntu_absent(fake: InstallerHarness, script: Path) -> None:
    write_os(fake, UBUNTU_OS)
    fake.configure(
        installed={},
        stamps={},
        python_root=False,
        python_client=False,
        python_daemon=False,
        dpkg_installed={},
        rpm_installed={},
    )


def _fedora_absent(fake: InstallerHarness, script: Path) -> None:
    write_os(fake, FEDORA_OS)
    fake.configure(
        installed={},
        stamps={},
        python_root=False,
        python_client=False,
        python_daemon=False,
        dpkg_installed={},
        rpm_installed={},
    )


def _arch_absent(fake: InstallerHarness) -> None:
    write_os(fake, ARCH_OS)
    fake.configure(
        installed={},
        stamps={},
        python_root=False,
        python_client=False,
        python_daemon=False,
    )


def test_dpkg_nul_row_unknown(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _ubuntu_absent(fake, script)
    fake.configure(dpkg_malformed="install ok installed unrelated 1\x00")
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "unknown or host not eligible" in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_dpkg_nul_name_unknown(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _ubuntu_absent(fake, script)
    fake.configure(dpkg_malformed="install ok installed bad\x00name 1.0")
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "unknown or host not eligible" in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_dpkg_nul_version_unknown(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _ubuntu_absent(fake, script)
    fake.configure(dpkg_malformed="install ok installed pkg 1.0\x00")
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "unknown or host not eligible" in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_dpkg_malformed_rows_unknown(tmp_path: Path) -> None:
    for row in (
        "bad-row-without-status",
        "install ok installed pkg 1.0 extra",
        "bogus status here pkg 1.0",
        "install ok installed bad!name 1.0",
    ):
        case = tmp_path / str(abs(hash(row)) % 100000)
        case.mkdir()
        fake, script = offer_harness(case)
        _ubuntu_absent(fake, script)
        fake.configure(dpkg_malformed=row)
        result, commands = fake.run("--version", TAG, script=script)
        assert result.returncode == 0, result.stderr
        assert "unknown or host not eligible" in result.stdout
        assert not any(c[0] == "installer-helper" for c in commands)
        assert_private_cleanup(fake)


def test_dpkg_error_unknown(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _ubuntu_absent(fake, script)
    fake.configure(dpkg_error=1)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "unknown or host not eligible" in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_dpkg_small_unrelated_absent_eligible(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _ubuntu_absent(fake, script)
    fake.configure(dpkg_installed={"unrelated": "1.0", "other": "2.0"})
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "OpenRazer is not installed" in result.stdout
    assert any(c[0] == "dpkg-query" for c in commands)
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_dpkg_metapackage_present(tmp_path: Path) -> None:
    for pkg in ("openrazer-meta", "razer-kernel-modules", "openrazer-daemon"):
        case = tmp_path / pkg.replace("-", "_")
        case.mkdir()
        fake, script = offer_harness(case)
        write_os(fake, UBUNTU_OS)
        fake.configure(
            installed={},
            stamps={},
            python_root=False,
            python_client=False,
            python_daemon=False,
            dpkg_installed={pkg: "1.0"},
            rpm_installed={},
        )
        result, commands = fake.run("--version", TAG, script=script)
        assert result.returncode == 0, result.stderr
        assert "leaving it unchanged" in result.stdout
        assert not any(c[0] == "installer-helper" for c in commands)
        assert_private_cleanup(fake)


def test_dpkg_oversize_tail_unknown(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _ubuntu_absent(fake, script)
    fillers = {f"filler{i:05d}": "1.0" for i in range(30000)}
    fillers["openrazer-daemon"] = "3.12.1-1"
    fake.configure(dpkg_installed=fillers)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "unknown or host not eligible" in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_rpm_nul_unknown(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _fedora_absent(fake, script)
    fake.configure(rpm_malformed="openrazer-daemon\x00 1.0")
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "unknown or host not eligible" in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_rpm_malformed_unknown(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _fedora_absent(fake, script)
    fake.configure(rpm_malformed="bad row with three columns here")
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "unknown or host not eligible" in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_rpm_small_unrelated_absent(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _fedora_absent(fake, script)
    fake.configure(rpm_installed={"unrelated": "1.0"})
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "OpenRazer is not installed" in result.stdout
    assert any(c[0] == "rpm" for c in commands)
    assert_private_cleanup(fake)


def test_rpm_oversize_tail_unknown(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _fedora_absent(fake, script)
    fillers = {f"filler{i:05d}": "1.0" for i in range(70000)}
    fillers["openrazer-daemon"] = "3.12.1-1"
    fake.configure(rpm_installed=fillers)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "unknown or host not eligible" in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_pacman_nul_unknown(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _arch_absent(fake)
    fake.configure(pacman_malformed="pkg\x00 1.0")
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "unknown or host not eligible" in result.stdout
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


def test_pacman_trailing_columns_unknown(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _arch_absent(fake)
    fake.configure(pacman_malformed="pkg 1.0 extra")
    result, _ = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "unknown or host not eligible" in result.stdout
    assert_private_cleanup(fake)


def test_pacman_metapackage_present(tmp_path: Path) -> None:
    for pkg in ("openrazer-meta", "razer-kernel-modules"):
        case = tmp_path / pkg.replace("-", "_")
        case.mkdir()
        fake, script = offer_harness(case)
        write_os(fake, ARCH_OS)
        fake.configure(installed={pkg: "1.0"}, stamps={})
        fake.configure(python_client=False, python_daemon=False)
        fake.configure(python_root=False)
        result, commands = fake.run("--version", TAG, script=script)
        assert result.returncode == 0, result.stderr
        assert "leaving it unchanged" in result.stdout
        assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
        assert_private_cleanup(fake)


def test_pacman_small_unrelated_absent(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _arch_absent(fake)
    fake.configure(installed={"unrelated": "1.0"})
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert ["pacman", "-Q"] in commands
    assert_private_cleanup(fake)


def test_pacman_oversize_tail_unknown(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _arch_absent(fake)
    fillers = {f"filler{i:05d}": "1.0" for i in range(70000)}
    fillers["openrazer-daemon"] = "3.12.1-1"
    fake.configure(installed=fillers)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "unknown or host not eligible" in result.stdout
    assert not any(c[:2] == ["sudo", "pacman"] for c in commands)
    assert_private_cleanup(fake)


def test_plain_opensuse_default_app_only(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, OPENSUSE_OS)
    fake.configure(
        installed={},
        stamps={},
        python_root=False,
        python_client=False,
        python_daemon=False,
        dpkg_installed={},
        rpm_installed={},
    )
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "app-only install" in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_plain_opensuse_explicit_refused(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, OPENSUSE_OS)
    fake.configure(
        installed={},
        stamps={},
        python_root=False,
        python_client=False,
        python_daemon=False,
        dpkg_installed={},
        rpm_installed={},
    )
    result, commands = fake.run("--version", TAG, "--install-openrazer", script=script)
    assert result.returncode != 0
    assert "unsupported on this host" in result.stderr
    assert "Naga unchanged" in result.stderr
    assert not any(c[0] == "installer-helper" for c in commands)
    assert not any("api.github.com" in i for c in commands for i in c if c[0] == "curl")
    assert_private_cleanup(fake)


def test_explicit_native_present_refused(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    write_os(fake, UBUNTU_OS)
    fake.configure(
        installed={},
        stamps={},
        python_root=False,
        python_client=False,
        python_daemon=False,
        dpkg_installed={"openrazer-daemon": "3.12.1-1"},
        rpm_installed={},
    )
    result, commands = fake.run("--version", TAG, "--install-openrazer", script=script)
    assert result.returncode != 0
    assert "native first install refused" in result.stderr
    assert "Naga unchanged" in result.stderr
    assert not any(c[0] == "installer-helper" for c in commands)
    assert ["systemctl", "--user", "stop", "naga-control.service"] not in commands
    assert_private_cleanup(fake)


def test_explicit_native_unknown_refused(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _ubuntu_absent(fake, script)
    fake.configure(dpkg_malformed="bad-row")
    result, commands = fake.run("--version", TAG, "--install-openrazer", script=script)
    assert result.returncode != 0
    assert "native first install refused" in result.stderr
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


@pytest.mark.parametrize(
    "marker",
    [
        "OFFER-PROBE openrazer=False client=False daemon=False\x00",
        "\x00OFFER-PROBE openrazer=False client=False daemon=False",
        "OFFER-PROBE openrazer=False client=False daemon=False\x01",
        "OFFER-PROBE openrazer=False client=False daemon=False" + chr(0xE9),
        "X" * 1048577,
    ],
    ids=["nul-end", "nul-start", "control", "non-ascii", "oversize-1MiB"],
)
def test_offer_probe_bytes_never_absent(tmp_path: Path, marker: str) -> None:
    fake, script = offer_harness(tmp_path)
    _ubuntu_absent(fake, script)
    fake.configure(offer_malformed=marker)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode == 0, result.stderr
    assert "unknown or host not eligible" in result.stdout
    assert "OpenRazer is not installed" not in result.stdout
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)


def test_explicit_probe_unknown_fails_before_stop(tmp_path: Path) -> None:
    fake, script = offer_harness(tmp_path)
    _ubuntu_absent(fake, script)
    previous = seed_previous(fake)
    profile = fake.root / "home/.config/naga-control/profiles.toml"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("user profile untouched\n")
    fake.configure(offer_malformed="OFFER-PROBE openrazer=False client=False daemon=False\x00")
    result, commands = fake.run("--version", TAG, "--install-openrazer", script=script)
    assert result.returncode != 0
    assert "native first install refused" in result.stderr
    assert "Naga unchanged" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert profile.read_text() == "user profile untouched\n"
    assert ["systemctl", "--user", "stop", "naga-control.service"] not in commands
    assert not any(c[0] == "installer-helper" for c in commands)
    assert_private_cleanup(fake)
