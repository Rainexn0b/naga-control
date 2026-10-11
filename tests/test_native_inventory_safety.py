"""Native helper inventory byte safety and family guards."""

from pathlib import Path

import pytest

from tests.native_openrazer_installer_fakes import harness, write_os


def test_debian_nul_check_unknown(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\n')
    fake.configure(query_malformed="install ok installed pkg 1.0\x00")
    result, commands = fake.run("--family", "debian", "--check")
    assert result.returncode == 0
    assert "UNVERIFIED" in result.stdout
    assert "ABSENT" not in result.stdout
    assert not any(c[0] == "sudo" for c in commands)


def test_debian_nul_install_refused(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\n')
    fake.configure(query_malformed="install ok installed unrelated 1\x00")
    result, commands = fake.run("--family", "debian", "--yes")
    assert result.returncode != 0
    assert "refused" in result.stderr
    assert not any(c[0] == "sudo" for c in commands)


def test_rpm_nul_unknown(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, 'NAME="Fedora Linux"\nVERSION_ID="42"\nID=fedora\n')
    fake.configure(query_malformed="pkg\x00 1.0")
    result, commands = fake.run("--family", "fedora", "--check")
    assert result.returncode == 0
    assert "UNVERIFIED" in result.stdout
    assert "ABSENT" not in result.stdout
    assert not any(c[0] == "sudo" for c in commands)


def test_malformed_no_space_unknown(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\n')
    fake.configure(query_malformed="no-space")
    result, _ = fake.run("--family", "debian", "--check")
    assert result.returncode == 0
    assert "UNVERIFIED" in result.stdout
    assert "ABSENT" not in result.stdout


def test_query_fail_unknown(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\n')
    fake.configure(query_fail=1)
    result, commands = fake.run("--family", "debian", "--check")
    assert result.returncode == 0
    assert "UNVERIFIED" in result.stdout
    assert not any(c[0] == "sudo" for c in commands)


def test_small_unrelated_absent(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\n')
    fake.configure(installed={"unrelated": "1.0"})
    result, _ = fake.run("--family", "debian", "--check")
    assert result.returncode == 0
    assert "ABSENT" in result.stdout


def test_metapackage_refused(tmp_path: Path) -> None:
    for pkg in ("openrazer-meta", "razer-kernel-modules"):
        fake = harness(tmp_path / pkg.replace("-", "_"))
        write_os(fake, 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\n')
        fake.configure(installed={pkg: "1.0"})
        result, commands = fake.run("--family", "debian", "--check")
        assert result.returncode == 0
        assert "UNVERIFIED" in result.stdout
        result, commands = fake.run("--family", "debian", "--yes")
        assert result.returncode != 0
        assert not any(c[0] == "sudo" for c in commands)


def test_debian_oversize_tail_unknown(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\n')
    fillers = {f"filler{i:05d}": "1.0" for i in range(30000)}
    fillers["openrazer-daemon"] = "3.12.1-1"
    fake.configure(installed=fillers)
    result, commands = fake.run("--family", "debian", "--check")
    assert result.returncode == 0
    assert "UNVERIFIED" in result.stdout
    assert "ABSENT" not in result.stdout
    assert not any(c[0] == "sudo" for c in commands)


def test_rpm_oversize_tail_unknown(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, 'NAME="Fedora Linux"\nVERSION_ID="42"\nID=fedora\n')
    fillers = {f"filler{i:05d}": "1.0" for i in range(70000)}
    fillers["openrazer-daemon-local"] = "3.12.1.pr2904.fix2-1"
    fake.configure(installed=fillers)
    result, commands = fake.run("--family", "fedora", "--check")
    assert result.returncode == 0
    assert "UNVERIFIED" in result.stdout
    assert not any(c[0] == "sudo" for c in commands)


def test_plain_opensuse_preflight_rejected(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, 'NAME="openSUSE"\nID=opensuse\nID_LIKE="suse"\n')
    result, commands = fake.run("--family", "opensuse", "--preflight")
    assert result.returncode != 0
    assert "unsupported host" in result.stderr
    assert not any(c[0] == "sudo" for c in commands)


def test_plain_opensuse_install_rejected(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, 'NAME="openSUSE"\nID=opensuse\nID_LIKE="suse"\n')
    result, commands = fake.run("--family", "opensuse", "--yes")
    assert result.returncode != 0
    assert not any(c[0] == "sudo" for c in commands)


def test_wrong_family_blocked(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    write_os(fake, 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\n')
    result, commands = fake.run("--family", "fedora", "--yes")
    assert result.returncode != 0
    assert "unsupported host" in result.stderr
    assert not any(c[0] == "sudo" for c in commands)


@pytest.mark.parametrize(
    "marker",
    [
        "OPENRAZER-PROBE p=False client=False daemon=False\x00",
        "\x00OPENRAZER-PROBE p=False client=False daemon=False",
        "OPENRAZER-PROBE p=False client=False daemon=False\x01",
        "OPENRAZER-PROBE p=False client=False daemon=False" + chr(0xE9),
        "X" * 1048577,
    ],
    ids=["nul-end", "nul-start", "control", "non-ascii", "oversize-1MiB"],
)
def test_probe_bytes_never_absent(tmp_path: Path, marker: str) -> None:
    fake = harness(tmp_path)
    write_os(fake, 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\n')
    fake.configure(python_malformed=marker)
    result, commands = fake.run("--family", "debian", "--check")
    assert result.returncode == 0
    assert "UNVERIFIED" in result.stdout
    assert "ABSENT" not in result.stdout
    assert not any(c[0] == "sudo" for c in commands)
