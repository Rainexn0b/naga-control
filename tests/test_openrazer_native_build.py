"""Build orchestration tests for the native builder (fake runners only)."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from buildpython.openrazer_native import build, recipes, validation
from tests.openrazer_native_fakes import (
    COMMIT,
    GPL_TEXT,
    PIN,
    completed_stdout,
    deb_listing_lines,
    make_control_tar_bytes,
    make_pin_file,
    make_tar_bytes,
)

VERSION = "3.12.1.pr2904.fix2-1"
PKGVER = "3.12.1.pr2904.fix2"
PRIVILEGED = (
    "sudo",
    "apt",
    "apt-get",
    "dnf",
    "zypper",
    "pacman",
    "dkms",
    "systemctl",
    "busctl",
    "modprobe",
    "depmod",
    "udevadm",
)


class DebBuildFake:
    """Simulate git/make/setup/dpkg-deb for a Debian cohort build."""

    def __init__(self, minor: str) -> None:
        self.calls: list[list[str]] = []
        self.minor = minor

    def __call__(self, cmd: Sequence[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
        items = list(cmd)
        self.calls.append(items)
        if items[0] == "git" and "rev-parse" in items:
            return completed_stdout(COMMIT + "\n")
        if items[0] == "git":
            if "status" in items and "--ignored" not in items:
                raise AssertionError("status must include --ignored")
            return completed_stdout("")
        if items[0] == "make" and "setup_dkms" in items:
            dest = Path(next(a for a in items if a.startswith("DESTDIR=")).split("=", 1)[1])
            dkms_dir = dest / f"usr/src/openrazer-driver-{PKGVER}"
            dkms_dir.mkdir(parents=True, exist_ok=True)
            (dkms_dir / "dkms.conf").write_text(
                'PACKAGE_NAME="openrazer-driver"\nPACKAGE_VERSION="3.12.1"\nMAKE="make"\n',
                encoding="ascii",
            )
            (dkms_dir / "Makefile").write_text("all:\n", encoding="ascii")
            udev = dest / "usr/lib/udev/rules.d"
            udev.mkdir(parents=True, exist_ok=True)
            (udev / "99-razer.rules").write_text('GROUP="openrazer"\n', encoding="ascii")
            (dest / "usr/lib/udev/razer_mount").parent.mkdir(parents=True, exist_ok=True)
            (dest / "usr/lib/udev/razer_mount").write_text("# openrazer\n", encoding="ascii")
            (dest / "usr/share/metainfo").mkdir(parents=True, exist_ok=True)
            (dest / "usr/share/metainfo/io.github.openrazer.openrazer.metainfo.xml").write_text(
                "<x/>\n", encoding="utf-8"
            )
            return completed_stdout("")
        if items[0] == "make" and "install-resources" in items:
            dest = Path(next(a for a in items if a.startswith("DESTDIR=")).split("=", 1)[1])
            (dest / "usr/lib/systemd/user").mkdir(parents=True, exist_ok=True)
            (dest / "usr/lib/systemd/user/openrazer-daemon.service").write_text(
                "[Unit]\n[Service]\nType=dbus\nBusName=org.razer\n"
                "ExecStart=/usr/bin/openrazer-daemon -F\n[Install]\nWantedBy=default.target\n",
                encoding="ascii",
            )
            (dest / "usr/share/dbus-1/services").mkdir(parents=True, exist_ok=True)
            (dest / "usr/share/dbus-1/services/org.razer.service").write_text(
                "[D-BUS Service]\nName=org.razer\nExec=/usr/bin/openrazer-daemon\n"
                "SystemdService=openrazer-daemon.service\n",
                encoding="ascii",
            )
            (dest / "usr/bin").mkdir(parents=True, exist_ok=True)
            (dest / "usr/bin/openrazer-daemon").write_text("#!/usr/bin/python3\n", encoding="utf-8")
            (dest / "usr/share/openrazer").mkdir(parents=True, exist_ok=True)
            (dest / "usr/share/openrazer/razer.conf.example").write_text(
                "# example\n", encoding="utf-8"
            )
            (dest / "usr/share/man/man5").mkdir(parents=True, exist_ok=True)
            (dest / "usr/share/man/man8").mkdir(parents=True, exist_ok=True)
            (dest / "usr/share/man/man5/razer.conf.5.gz").write_bytes(b"fake")
            (dest / "usr/share/man/man8/openrazer-daemon.8.gz").write_bytes(b"fake")
            return completed_stdout("")
        if "setup.py" in items:
            assert "-I" in items and "-B" in items
            root = Path(next(a for a in items if a.startswith("--root=")).split("=", 1)[1])
            lib = next(a for a in items if a.startswith("--install-lib=")).split("=", 1)[1]
            assert cwd is not None
            package = "openrazer_daemon" if cwd.name == "daemon" else "openrazer"
            mod = root / lib.removeprefix("/") / package
            mod.mkdir(parents=True, exist_ok=True)
            (mod / "__init__.py").write_text("# fixture\n", encoding="utf-8")
            egg = root / lib.removeprefix("/") / f"{package}-3.12.1-py{self.minor}.egg-info"
            egg.mkdir(parents=True, exist_ok=True)
            for leaf in (
                "PKG-INFO",
                "SOURCES.txt",
                "dependency_links.txt",
                "requires.txt",
                "top_level.txt",
            ):
                (egg / leaf).write_text("Name\n", encoding="utf-8")
            return completed_stdout("")
        if items[0] == "dpkg-deb" and "--build" in items:
            stage = Path(items[-2])
            debian_dir = stage / "DEBIAN"
            assert (debian_dir.stat().st_mode & 0o777) == 0o755
            assert ((debian_dir / "control").stat().st_mode & 0o777) == 0o644
            for script in ("postinst", "prerm"):
                assert ((debian_dir / script).stat().st_mode & 0o777) == 0o755
            Path(items[-1]).write_bytes(b"fake-deb")
            return completed_stdout("")
        if items[0] == "dpkg-deb" and items[1] == "-f":
            field, role = items[-1], Path(items[2]).name.split("_")[0]
            version = VERSION
            values = {
                "Package": role,
                "Version": version,
                "Architecture": "all",
                "Depends": recipes.debian_depends(role, version, self.minor),
                "Provides": recipes.UPSTREAM_DEB[role],
                "Conflicts": recipes.UPSTREAM_DEB[role],
                "Replaces": recipes.UPSTREAM_DEB[role],
            }
            return completed_stdout(values[field] + "\n")
        if items[0] == "dpkg-deb" and items[1] == "-c":
            role = Path(items[2]).name.split("_")[0]
            return completed_stdout("\n".join(deb_listing_lines(role, self.minor)) + "\n")
        raise AssertionError(f"unexpected build command: {items}")


class DebByteFake:
    def __init__(self, minor: str = "3.10") -> None:
        self.calls: list[list[str]] = []
        self.minor = minor

    def __call__(self, cmd: Sequence[str], cwd: Path | None) -> subprocess.CompletedProcess[bytes]:
        items = list(cmd)
        self.calls.append(items)
        role = Path(items[-1]).name.split("_")[0]
        if "--ctrl-tarfile" in items:
            payload = make_control_tar_bytes(role, VERSION, self.minor, PKGVER)
        else:
            payload = make_tar_bytes(role, COMMIT, self.minor)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=payload, stderr=b"")


def _make_source(tmp_path: Path) -> Path:
    source = tmp_path / "src"
    source.mkdir()
    for relative in (
        "daemon/openrazer_daemon/daemon.py",
        "install_files/udev/99-razer.rules",
        "install_files/udev/razer_mount",
    ):
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("plugdev\n", encoding="ascii")
    (source / "Makefile").write_text("all:\n", encoding="ascii")
    (source / "daemon").mkdir(parents=True, exist_ok=True)
    (source / "daemon/setup.py").write_text("x\n", encoding="ascii")
    (source / "pylib").mkdir(parents=True, exist_ok=True)
    (source / "pylib/setup.py").write_text("x\n", encoding="ascii")
    (source / "LICENSES").mkdir(parents=True, exist_ok=True)
    (source / "LICENSES/GPL-2.0-or-later.txt").write_text(GPL_TEXT, encoding="utf-8")
    return source


def test_build_refuses_bad_inputs_before_commands(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    output = tmp_path / "out"
    output.mkdir()
    pin_path = make_pin_file(tmp_path)
    owner = output.stat().st_uid
    fake = DebBuildFake(validation.current_python_minor())
    with pytest.raises(ValueError, match="root"):
        build.build_native_packages("debian", source, output, pin_path, 0, fake, DebByteFake())
    with pytest.raises(ValueError, match="Unsupported family"):
        build.build_native_packages("arch", source, output, pin_path, owner, fake, DebByteFake())
    assert fake.calls == []


def test_build_rejects_dirty_source_without_build(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    output = tmp_path / "out"
    output.mkdir()
    pin_path = make_pin_file(tmp_path)
    owner = output.stat().st_uid

    def _dirty(cmd: Sequence[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
        items = list(cmd)
        if "rev-parse" in items:
            return completed_stdout(COMMIT + "\n")
        if items[0] == "git":
            return completed_stdout(" M dirty\n")
        raise AssertionError("must not reach make/packaging")

    with pytest.raises(ValueError, match="dirty"):
        build.build_native_packages(
            "debian", source, output, pin_path, owner, _dirty, DebByteFake()
        )
    assert list(output.iterdir()) == []


def test_build_rejects_nonempty_output(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    output = tmp_path / "out"
    output.mkdir()
    (output / "stale.deb").write_text("x", encoding="ascii")
    pin_path = make_pin_file(tmp_path)
    fake = DebBuildFake(validation.current_python_minor())
    with pytest.raises(ValueError, match="empty"):
        build.build_native_packages(
            "debian", source, output, pin_path, output.stat().st_uid, fake, DebByteFake()
        )
    assert fake.calls == []


def test_debian_build_writes_cohort_and_manifest(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    output = tmp_path / "out"
    output.mkdir()
    pin_path = make_pin_file(tmp_path)
    minor = validation.current_python_minor()
    fake = DebBuildFake(minor)
    manifest = build.build_native_packages(
        "debian", source, output, pin_path, output.stat().st_uid, fake, DebByteFake(minor)
    )
    expected = recipes.expected_filenames("debian", PIN)
    for name in expected:
        target = output / name
        assert target.is_file() and not target.is_symlink()
        assert name.startswith(tuple(recipes.LOCAL_ROLES))
        assert name.endswith("_all.deb")
    sidecar = (output / recipes.SIDECAR_NAME).read_text(encoding="ascii")
    assert build.parse_sidecar(sidecar, expected)
    data = json.loads((output / recipes.MANIFEST_NAME).read_text(encoding="ascii"))
    assert data == manifest
    assert manifest["schema"] == 1 and manifest["family"] == "debian"
    assert manifest["source_commit"] == COMMIT and manifest["python_minor"] == minor
    assert [p["role"] for p in manifest["packages"]] == list(recipes.LOCAL_ROLES)  # type: ignore[union-attr]
    for call in fake.calls:
        assert call[0] not in PRIVILEGED
        assert "sudo" not in call


class _FailingDebBuild(DebBuildFake):
    def __call__(self, cmd: Sequence[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
        items = list(cmd)
        if items[0] == "dpkg-deb" and "--build" in items:
            return completed_stdout("", code=1)
        return super().__call__(cmd, cwd)


def test_build_failure_leaves_no_half_manifest(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    output = tmp_path / "out"
    output.mkdir()
    pin_path = make_pin_file(tmp_path)
    minor = validation.current_python_minor()
    fake = _FailingDebBuild(minor)
    with pytest.raises(ValueError, match="dpkg-deb failed"):
        build.build_native_packages(
            "debian", source, output, pin_path, output.stat().st_uid, fake, DebByteFake(minor)
        )
    assert list(output.iterdir()) == []


def test_publish_refuses_clobber_race_and_keeps_foreign(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    victim = output / "openrazer-native-packages.sha256"
    victim.write_text("foreign\n", encoding="ascii")
    created: list[Path] = []
    with pytest.raises(OSError):
        build._publish_text(victim, "new\n", created)  # pyright: ignore[reportPrivateUsage]
    assert victim.read_text(encoding="ascii") == "foreign\n"
    assert created == []


def test_publish_failure_cleans_own_partial_only(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    target = output / "native-build.json"
    created: list[Path] = []
    build._publish_bytes(target, b"partial", created)  # pyright: ignore[reportPrivateUsage]
    assert target.is_file()
    foreign = output / "foreign.kept"
    foreign.write_text("keep\n", encoding="ascii")
    with pytest.raises(OSError):
        build._publish_text(foreign, "clobber\n", created)  # pyright: ignore[reportPrivateUsage]
    assert foreign.read_text(encoding="ascii") == "keep\n"
    assert target in created and foreign not in created


def test_expected_filenames_and_rpm_spec(tmp_path: Path) -> None:
    assert recipes.expected_filenames("debian", PIN)[0].endswith("_all.deb")
    fedora_names = recipes.expected_filenames("fedora", PIN)
    assert fedora_names[0].endswith(".noarch.rpm")
    assert fedora_names[0].startswith("openrazer-driver-dkms-local-")
    spec = recipes.rpm_spec("fedora", VERSION, "3.10", PKGVER)
    assert "Source0:" not in spec or "http" not in spec
    assert "getent group openrazer" in spec and "$1" in spec
    assert "systemctl" not in spec and "udevadm" not in spec
    _ = sys.version_info
