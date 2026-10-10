"""FUSE prerequisite guidance: SONAME diagnostic plus exact manual references."""

from pathlib import Path

from tests.installer_app_fakes import app_harness, installed_image, mutations, stamp
from tests.installer_ldconfig_fakes import assert_cache_query, ldconfig_harness, write_ldconfig
from tests.openrazer_installer_fakes import ROOT, TAG


def test_library_missing_names_soname_and_readme_reference(tmp_path: Path) -> None:
    fake, script, _fixed = ldconfig_harness(tmp_path)
    preferred = fake.root / "bin/ldconfig"
    write_ldconfig(fake, preferred, output="")
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode != 0
    assert "FUSE2 library missing" in result.stderr
    assert "libfuse.so.2" in result.stderr
    assert "x86_64" in result.stderr
    assert "troubleshooting.md#installer-prerequisites" in result.stderr
    assert "older Debian/Ubuntu libfuse2" not in result.stderr
    assert "Fedora fuse-libs" not in result.stderr
    assert "install fuse/fuse2" not in result.stderr
    assert_cache_query(fake, preferred, commands)
    assert mutations(commands) == []
    assert not installed_image(fake).exists()
    assert not stamp(fake).exists()


def test_runtime_failure_keeps_device_gate_without_package_guess(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    fake.configure(fuse_runtime_missing=True)
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode != 0
    assert "FUSE runtime unavailable" in result.stderr
    assert "no device was opened" in result.stderr
    assert "install fuse/fuse2" not in result.stderr
    assert mutations(commands) == []
    assert not installed_image(fake).exists()


def test_kernel_failure_keeps_generic_capability_remedy(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    (fake.root / "filesystems").write_text("nodev\tfusectl\n")
    result, commands = fake.run("--version", TAG, script=script)
    assert result.returncode != 0
    assert "kernel FUSE support unavailable" in result.stderr
    assert "install fuse" not in result.stderr
    assert mutations(commands) == []
    assert not installed_image(fake).exists()


def test_readme_lists_exact_verified_fuse_references() -> None:
    text = (ROOT / "README.md").read_text()
    text.encode("ascii")
    assert "main/install.sh -o install.sh && bash install.sh" in text
    assert "--ref <tag> --version <tag>" in text
    assert "app-only" in text and "--install-openrazer" in text
    for token in (
        "Ubuntu 22.04",
        "Ubuntu 24.04",
        "Fedora 44",
        "sudo apt install libfuse2",
        "sudo apt install libfuse2t64",
        "sudo pacman -S fuse2",
        "sudo dnf install fuse-libs",
        "https://packages.ubuntu.com/jammy/libfuse2",
        "https://packages.ubuntu.com/noble/libfuse2t64",
        "https://archlinux.org/packages/extra/x86_64/fuse2/",
        "https://packages.fedoraproject.org/pkgs/fuse/fuse-libs/fedora-44.html",
        "2.9.9-25.fc44",
    ):
        assert token in text, token
    normalized = " ".join(text.split())
    assert "finished-artifact static gate" in normalized
    assert "208 objects" in normalized
    assert "22.04 baseline plus 24.04 userspace smoke checks" in normalized
    assert (
        "Scope is bundled runtime imports, offscreen QApplication, CLI `--help`, and "
        "temporary integration payload only;" in normalized
    )
    assert (
        "no full install, upgrade, remove, FUSE, user units, D-Bus, sudo, udev, "
        "desktop, service, or hardware certification is claimed" in normalized
    )
    assert "Only these four package references are verified" in normalized
    assert (
        "not a claim of complete prerequisites, AppImage launch, install, "
        "or hardware support" in normalized
    )


def _anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        slug = "".join(
            char if char.isalnum() else "-" for char in stripped.lstrip("#").strip().lower()
        )
        while "--" in slug:
            slug = slug.replace("--", "-")
        anchors.add(slug.strip("-"))
    return anchors


def test_readme_prerequisite_anchors_resolve_locally() -> None:
    text = (ROOT / "README.md").read_text()
    assert "docs/troubleshooting.md#installer-prerequisites" in text
    assert "docs/troubleshooting.md#installer-upgrades-and-rollback" in text
    anchors = _anchors(ROOT / "docs/troubleshooting.md")
    assert "installer-prerequisites" in anchors
    assert "installer-upgrades-and-rollback" in anchors
