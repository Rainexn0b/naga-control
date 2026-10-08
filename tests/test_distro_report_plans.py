"""Identity hints never become inherited package rows or distro validation."""

from pathlib import Path

import pytest

from tests.distro_report_fakes import fields, harness


@pytest.mark.parametrize(
    "fixture,package,url",
    [
        ("ubuntu-22.04", "libfuse2 (universe)", "https://packages.ubuntu.com/jammy/libfuse2"),
        ("ubuntu-24.04", "libfuse2t64 (universe)", "https://packages.ubuntu.com/noble/libfuse2t64"),
        ("arch-rolling", "fuse2 (extra)", "https://archlinux.org/packages/extra/x86_64/fuse2/"),
    ],
)
def test_reviewed_exact_rows_are_conditional_manual_references_only(
    tmp_path: Path, fixture: str, package: str, url: str
) -> None:
    fake = harness(tmp_path)
    fake.fixture(fixture)
    result = fake.run()
    assert result.returncode == 0 and result.stderr == ""
    report = fields(result.stdout)
    assert report["Report status"] == "CONDITIONAL"
    assert report["FUSE2 package reference"] == package
    assert report["FUSE2 reference URL"] == url
    assert report["FUSE2 reference reviewed"] == "2026-10-08"
    assert "actual architecture" in report["Plan note"]
    assert "NOT checked" in report["FUSE2 plan"]
    assert "VALIDATED" not in result.stdout.upper()
    assert fake.uname_calls() == ["-s", "-m"]


@pytest.mark.parametrize(
    "version",
    [
        "22",
        "22.4",
        "22.04.1",
        "022.04",
        "24.10",
        "26.04",
        "99.99",
        "999999999999999999999999999999.04",
        "rolling",
    ],
)
def test_future_or_nonexact_ubuntu_release_never_uses_numeric_comparison(
    tmp_path: Path, version: str
) -> None:
    result = harness(tmp_path, f"ID=ubuntu\nVERSION_ID={version}\n".encode()).run()
    report = fields(result.stdout)
    assert result.returncode == 0 and result.stderr == ""
    assert report["VERSION_ID"] == version
    assert report["Report status"] == report["FUSE2 package reference"] == "UNKNOWN"


@pytest.mark.parametrize(
    "fixture,family",
    [
        ("linuxmint-22", "ubuntu"),
        ("cachyos-rolling", "arch"),
        ("debian-12", "debian"),
        ("fedora-43", "fedora"),
        ("opensuse-tumbleweed", "opensuse"),
    ],
)
def test_recognized_family_without_reviewed_row_remains_unknown(
    tmp_path: Path, fixture: str, family: str
) -> None:
    fake = harness(tmp_path)
    fake.fixture(fixture)
    result = fake.run()
    report = fields(result.stdout)
    assert result.returncode == 0 and result.stderr == ""
    assert report["Family"] == family
    assert report["Report status"] == report["FUSE2 package reference"] == "UNKNOWN"
    assert "manual" in report["Plan note"]
    assert "distribution context" in report["OpenRazer native plan"]


@pytest.mark.parametrize(
    "identity", ["linuxmint", "pop", "cachyos", "manjaro", "endeavouros", "future-derivative"]
)
@pytest.mark.parametrize("version", ["22.04", "24.04", None])
def test_derivative_version_is_never_parent_release_or_package_plan(
    tmp_path: Path, identity: str, version: str | None
) -> None:
    like = "arch" if identity in {"cachyos", "manjaro", "endeavouros"} else "ubuntu debian"
    data = f"ID={identity}\nID_LIKE='{like}'\n"
    if version is not None:
        data += f"VERSION_ID={version}\n"
    result = harness(tmp_path, data.encode()).run()
    report = fields(result.stdout)
    assert result.returncode == 0 and result.stderr == ""
    assert report["ID"] == identity
    assert report["VERSION_ID"] == (version or "UNKNOWN")
    assert report["Family provenance"] == "ID_LIKE (hint only)"
    assert report["Report status"] == report["FUSE2 package reference"] == "UNKNOWN"
    assert report["FUSE2 reference URL"] == "UNKNOWN"


@pytest.mark.parametrize(
    "identity,family",
    [
        ("ubuntu", "ubuntu"),
        ("debian", "debian"),
        ("arch", "arch"),
        ("fedora", "fedora"),
        ("opensuse-leap", "opensuse"),
        ("alpine", "alpine"),
    ],
)
def test_known_exact_id_wins_over_conflicting_parent_hints(
    tmp_path: Path, identity: str, family: str
) -> None:
    data = f"ID={identity}\nID_LIKE='arch debian fedora'\nVERSION_ID=22.04\n".encode()
    report = fields(harness(tmp_path, data).run().stdout)
    assert report["Family"] == family
    assert report["Family provenance"] == "ID"
    assert report["Report status"] == ("CONDITIONAL" if identity == "ubuntu" else "UNKNOWN")


@pytest.mark.parametrize(
    "like,family,provenance",
    [
        ("ubuntu debian", "ubuntu", "ID_LIKE (hint only)"),
        ("debian ubuntu", "debian", "ID_LIKE (hint only)"),
        ("rhel fedora centos", "fedora", "ID_LIKE (hint only)"),
        ("suse opensuse", "opensuse", "ID_LIKE (hint only)"),
        ("irrelevant arch archlinux", "arch", "ID_LIKE (hint only)"),
        ("arch ubuntu", "UNKNOWN", "UNKNOWN (ambiguous ID_LIKE)"),
        ("debian fedora", "UNKNOWN", "UNKNOWN (ambiguous ID_LIKE)"),
        ("opensuse alpine", "UNKNOWN", "UNKNOWN (ambiguous ID_LIKE)"),
        ("newparent", "UNKNOWN", "UNKNOWN"),
    ],
)
def test_ordered_related_parent_aliases_and_ambiguous_lineages(
    tmp_path: Path, like: str, family: str, provenance: str
) -> None:
    data = f"ID=fixture\nID_LIKE='{like}'\nVERSION_ID=22.04\n".encode()
    report = fields(harness(tmp_path, data).run().stdout)
    assert report["Family"] == family
    assert report["Family provenance"] == provenance
    assert report["Report status"] == report["FUSE2 package reference"] == "UNKNOWN"


@pytest.mark.parametrize(
    "data",
    [
        b"ID=futureos\nVERSION_ID=1\n",
        b"ID=ubuntu\n",
        b"ID=arch\nVERSION_ID=20261008\n",
        b"ID=arch\nVERSION_ID=UNKNOWN\n",
    ],
)
def test_unknown_or_missing_version_and_arch_snapshot_are_not_validated(
    tmp_path: Path, data: bytes
) -> None:
    result = harness(tmp_path, data).run()
    assert result.returncode == 0 and result.stderr == ""
    assert fields(result.stdout)["Report status"] == "UNKNOWN"
    assert "VALIDATED" not in result.stdout.upper()
    assert "immutable current artifact/snapshot UNKNOWN" in result.stdout


@pytest.mark.parametrize(
    "os_name,arch",
    [
        ("Linux", "aarch64"),
        ("Linux", "armv7l"),
        ("Linux", "i686"),
        ("Linux", "unknown-arch"),
        ("Darwin", "x86_64"),
        ("FreeBSD", "x86_64"),
    ],
)
def test_outside_current_platform_never_gets_a_package_row(
    tmp_path: Path, os_name: str, arch: str
) -> None:
    fake = harness(tmp_path)
    fake.environment.update(FAKE_OS=os_name, FAKE_ARCH=arch)
    result = fake.run()
    report = fields(result.stdout)
    assert result.returncode == 0 and result.stderr == ""
    assert report["OS"] == os_name and report["Architecture"] == arch
    assert report["Report status"] == report["FUSE2 package reference"] == "UNKNOWN"
    assert "outside current managed" in report["Plan note"]


@pytest.mark.parametrize("failure", ["FAKE_OS_FAILURE", "FAKE_ARCH_FAILURE"])
def test_uname_failure_is_unknown_not_report_failure(tmp_path: Path, failure: str) -> None:
    fake = harness(tmp_path)
    fake.environment[failure] = "1"
    result = fake.run()
    assert result.returncode == 0 and result.stderr == ""
    assert fields(result.stdout)["Report status"] == "UNKNOWN"


@pytest.mark.parametrize("value", ["", "x86_64\nprivate", "\x1bprivate", "a" * 65, "$(curl)"])
def test_hostile_uname_text_is_not_echoed(tmp_path: Path, value: str) -> None:
    fake = harness(tmp_path)
    fake.environment["FAKE_ARCH"] = value
    result = fake.run()
    assert result.returncode == 0 and result.stderr == ""
    assert fields(result.stdout)["Architecture"] == "UNKNOWN"
    assert fields(result.stdout)["Report status"] == "UNKNOWN"
    assert "private" not in result.stdout and "$(curl)" not in result.stdout


def test_alpine_musl_is_outside_managed_target_not_native_support_claim(tmp_path: Path) -> None:
    fake = harness(tmp_path)
    fake.fixture("alpine-3.22")
    result = fake.run()
    report = fields(result.stdout)
    assert result.returncode == 0 and result.stderr == ""
    assert report["Report status"] == report["FUSE2 package reference"] == "UNKNOWN"
    assert "musl distribution outside" in report["Plan note"]
    assert "experimental native" not in result.stdout


def test_report_separates_unexamined_runtime_from_all_install_plans(tmp_path: Path) -> None:
    result = harness(tmp_path).run()
    report = fields(result.stdout)
    assert report["Approved build target"] == (
        "Ubuntu 22.04 / glibc 2.35 / x86_64 (not artifact acceptance)"
    )
    for name in (
        "Artifact audit",
        "Host libc",
        "Qt platform libraries",
        "Desktop session / user systemd / session D-Bus",
        "FUSE library / runtime / kernel access",
        "udev / input permissions",
        "Kernel / DKMS / Secure Boot",
        "Actual OpenRazer runtime",
        "Installed package presence",
    ):
        assert report[name] == "NOT EXAMINED"
    assert "ordinary installation is app-only" in report["AppImage plan"]
    assert "optional Python >=3.12" in report["Source development plan"]
    assert "not a host-report" in report["Source development plan"]
    assert "explicit opt-in and matching driver/daemon/client" in report["OpenRazer policy"]
    assert "every intended kernel" in report["OpenRazer prerequisites"]
    assert "actual host daemon/client Python minor" in report["OpenRazer prerequisites"]
    assert "no Arch archive conversion" in report["OpenRazer native plan"]
    assert "docs/troubleshooting.md#installer-prerequisites" in result.stdout
    slug = "other-distributions-manual-matching-source-native-build"
    assert "docs/release-notes.md#" + slug in result.stdout
    release = (Path(__file__).parents[1] / "docs/release-notes.md").read_text()
    assert "### Other distributions: manual matching-source native build" in release
    assert all(
        command not in result.stdout
        for command in ("apt install", "pacman -", "sudo ", "dnf install", "zypper install")
    )
