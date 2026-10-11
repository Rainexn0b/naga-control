"""Offer fixtures: Arch identities and backend states for hermetic tests."""

from pathlib import Path

from tests.installer_app_fakes import app_harness
from tests.openrazer_installer_fakes import InstallerHarness

ARCH_OS = 'NAME="Arch Linux"\nID=arch\nBUILD_ID=rolling\n'
DERIVATIVE_OS = 'NAME="EndeavourOS"\nID=endeavouros\nID_LIKE=arch\n'
UBUNTU_OS = 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\n'
DEBIAN_OS = 'NAME="Debian GNU/Linux"\nVERSION_ID="12"\nID=debian\n'
FEDORA_OS = 'NAME="Fedora Linux"\nVERSION_ID="42"\nID=fedora\n'
LEAP_OS = 'NAME="openSUSE Leap"\nVERSION_ID="15.6"\nID=opensuse-leap\nID_LIKE="opensuse suse"\n'
TUMBLEWEED_OS = 'NAME="openSUSE Tumbleweed"\nID=opensuse-tumbleweed\nID_LIKE="opensuse suse"\n'
OPENSUSE_OS = 'NAME="openSUSE"\nID=opensuse\nID_LIKE="suse"\n'
RHEL_OS = 'NAME="Red Hat Enterprise Linux"\nVERSION_ID="9.5"\nID=rhel\nID_LIKE="fedora"\n'
SLES_OS = 'NAME="SLES"\nVERSION_ID="15.6"\nID=sles\nID_LIKE="suse opensuse"\n'
NATIVE_HELPER_OK = '#!/usr/bin/env bash\nexec installer-helper "$@" 9>&-\n'


def offer_harness(tmp_path: Path, *, helper: str | None = None) -> tuple[InstallerHarness, Path]:
    fake, script = app_harness(tmp_path, helper=helper)
    return fake, script


def write_os(fake: InstallerHarness, text: str | bytes, vendor: str | bytes | None = None) -> None:
    etc = fake.root / "os-release"
    vendor_path = fake.root / "vendor-os-release"
    if isinstance(text, bytes):
        etc.write_bytes(text)
    else:
        etc.write_text(text)
    if vendor is None:
        vendor_path.write_text(UBUNTU_OS)
    elif isinstance(vendor, bytes):
        vendor_path.write_bytes(vendor)
    else:
        vendor_path.write_text(vendor)


def make_arch(fake: InstallerHarness) -> None:
    write_os(fake, ARCH_OS)


def make_derivative(fake: InstallerHarness) -> None:
    write_os(fake, DERIVATIVE_OS)


def make_absent(fake: InstallerHarness) -> None:
    fake.configure(
        installed={},
        stamps={},
        python_root=False,
        python_client=False,
        python_daemon=False,
        dpkg_installed={},
        rpm_installed={},
    )


def make_arch_absent(fake: InstallerHarness) -> None:
    make_arch(fake)
    make_absent(fake)


def make_derivative_absent(fake: InstallerHarness) -> None:
    make_derivative(fake)
    make_absent(fake)


def make_native_absent(fake: InstallerHarness, os_text: str) -> None:
    write_os(fake, os_text)
    make_absent(fake)


def make_ubuntu_absent(fake: InstallerHarness) -> None:
    make_native_absent(fake, UBUNTU_OS)


def make_debian_absent(fake: InstallerHarness) -> None:
    make_native_absent(fake, DEBIAN_OS)


def make_fedora_absent(fake: InstallerHarness) -> None:
    make_native_absent(fake, FEDORA_OS)


def make_leap_absent(fake: InstallerHarness) -> None:
    make_native_absent(fake, LEAP_OS)


def make_tumbleweed_absent(fake: InstallerHarness) -> None:
    make_native_absent(fake, TUMBLEWEED_OS)


def stage_native_helper_local(fake: InstallerHarness, script: Path) -> None:
    (script.parent / "install_openrazer_native.sh").write_text(NATIVE_HELPER_OK)


def stage_native_helper_remote(fake: InstallerHarness) -> None:
    (fake.remote / "install_openrazer_native.sh").write_text(NATIVE_HELPER_OK)
