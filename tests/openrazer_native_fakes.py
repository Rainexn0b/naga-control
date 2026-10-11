"""Fakes for native builder tests (no real git, builds, or package DB)."""

from __future__ import annotations

import io
import subprocess
import tarfile
from collections.abc import Sequence
from pathlib import Path

PIN: dict[str, str] = {
    "OPENRAZER_FORK_REPO": "Rainexn0b/openrazer",
    "OPENRAZER_COMMIT": "26b0eeb5ed70d638fa3528851adcd5e58369a7f5",
    "OPENRAZER_BRANCH": "naga-v3-pro-compat",
    "OPENRAZER_PKGVER": "3.12.1.pr2904.fix2",
    "OPENRAZER_PKGREL": "1",
}

PIN_TEXT = """# Pinned OpenRazer baseline.
OPENRAZER_FORK_REPO="Rainexn0b/openrazer"
OPENRAZER_COMMIT="26b0eeb5ed70d638fa3528851adcd5e58369a7f5"
OPENRAZER_BRANCH="naga-v3-pro-compat"
OPENRAZER_PKGVER="3.12.1.pr2904.fix2"
OPENRAZER_PKGREL="1"
"""

VERSION = "3.12.1.pr2904.fix2-1"
PKGVER = "3.12.1.pr2904.fix2"
COMMIT = "26b0eeb5ed70d638fa3528851adcd5e58369a7f5"
GPL_TEXT = "GNU GENERAL PUBLIC LICENSE Version 2\n" + "x\n" * 300


def make_pin_file(directory: Path) -> Path:
    target = directory / "pin.conf"
    target.write_text(PIN_TEXT, encoding="ascii")
    return target


def completed_stdout(text: str, code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=text, stderr="")


def completed_bytes(data: bytes, code: int = 0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=data, stderr=b"")


class FakeRunner:
    def __init__(self, pin: dict[str, str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.pin = pin if pin is not None else PIN

    def __call__(self, cmd: Sequence[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
        items = list(cmd)
        self.calls.append(items)
        if items[0] == "git" and "rev-parse" in items:
            return completed_stdout(self.pin["OPENRAZER_COMMIT"] + "\n")
        if items[0] == "git" and "status" in items:
            return completed_stdout("")
        if items[0] == "make":
            return completed_stdout("")
        if items[0] == "dpkg-deb" and items[1] == "-f":
            field = items[-1]
            mapping = {
                "Package": "x",
                "Version": VERSION,
                "Architecture": "all",
                "Depends": "depends",
                "Provides": "provides",
                "Conflicts": "conflicts",
                "Replaces": "replaces",
            }
            return completed_stdout(mapping.get(field, "") + "\n")
        if items[0] == "dpkg-deb" and items[1] == "-c":
            return completed_stdout("")
        if items[0] == "rpm" and "--requires" in items:
            return completed_stdout("requires\n")
        if items[0] == "rpm" and "--queryformat" in items:
            return completed_stdout("query\n")
        if items[0] == "rpm" and items[1] == "-qplv":
            return completed_stdout("")
        if items[0] == "rpmbuild":
            return completed_stdout("")
        if items[0].endswith("python") or items[0] == "python3":
            return completed_stdout("")
        return completed_stdout("")


class FakeByteRunner:
    def __init__(self, payload: bytes = b"") -> None:
        self.calls: list[list[str]] = []
        self.payload = payload

    def __call__(self, cmd: Sequence[str], cwd: Path | None) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(list(cmd))
        return completed_bytes(self.payload)


def _chmod_tree(root: Path, role: str, pkgver: str) -> None:
    execs: set[str] = set()
    if role == "openrazer-driver-dkms-local":
        execs = {f"usr/src/openrazer-driver-{pkgver}/dkms-make", "usr/lib/udev/razer_mount"}
    elif role == "openrazer-daemon-local":
        execs = {"usr/bin/openrazer-daemon"}
    for item in root.rglob("*"):
        if item.is_symlink():
            continue
        if item.is_dir():
            item.chmod(0o755)
        elif item.is_file():
            rel = item.relative_to(root).as_posix()
            item.chmod(0o755 if rel in execs else 0o644)


def make_valid_stages(base: Path, family: str, minor: str, pin: dict[str, str]) -> dict[str, Path]:
    commit, pkgver = pin["OPENRAZER_COMMIT"], pin["OPENRAZER_PKGVER"]
    roles = ("openrazer-driver-dkms-local", "openrazer-daemon-local", "python-openrazer-local")
    stages: dict[str, Path] = {role: base / f"stage-{role}" for role in roles}
    for role, root in stages.items():
        doc = root / "usr/share/doc" / role
        doc.mkdir(parents=True, exist_ok=True)
        (doc / "source-commit").write_text(commit + "\n", encoding="ascii")
        (doc / "copyright").write_text(GPL_TEXT, encoding="utf-8")
    driver = stages["openrazer-driver-dkms-local"]
    dkms_dir = driver / f"usr/src/openrazer-driver-{pkgver}"
    dkms_dir.mkdir(parents=True, exist_ok=True)
    (dkms_dir / "dkms.conf").write_text(
        f'PACKAGE_NAME="openrazer-driver"\nPACKAGE_VERSION="{pkgver}"\nMAKE="./dkms-make ${{kernelver}}"\n',
        encoding="utf-8",
    )
    (dkms_dir / "dkms-make").write_text("#!/bin/sh\nset -eu\nexit 0\n", encoding="utf-8")
    (dkms_dir / "Makefile").write_text("all:\n", encoding="utf-8")
    (driver / "usr/lib/udev/rules.d").mkdir(parents=True, exist_ok=True)
    (driver / "usr/lib/udev/rules.d/99-razer.rules").write_text(
        'GROUP="openrazer"\n', encoding="utf-8"
    )
    (driver / "usr/lib/udev/razer_mount").write_text("# openrazer helper\n", encoding="utf-8")
    (driver / "usr/share/metainfo").mkdir(parents=True, exist_ok=True)
    (driver / "usr/share/metainfo/io.github.openrazer.openrazer.metainfo.xml").write_text(
        "<x/>\n", encoding="utf-8"
    )
    daemon = stages["openrazer-daemon-local"]
    (daemon / "usr/lib/systemd/user").mkdir(parents=True, exist_ok=True)
    (daemon / "usr/lib/systemd/user/openrazer-daemon.service").write_text(
        "[Unit]\nDescription=x\n[Service]\nType=dbus\nBusName=org.razer\nExecStart=/usr/bin/openrazer-daemon -F\n[Install]\nWantedBy=default.target\n",
        encoding="utf-8",
    )
    (daemon / "usr/share/dbus-1/services").mkdir(parents=True, exist_ok=True)
    (daemon / "usr/share/dbus-1/services/org.razer.service").write_text(
        "[D-BUS Service]\nName=org.razer\nExec=/usr/bin/openrazer-daemon\nSystemdService=openrazer-daemon.service\n",
        encoding="utf-8",
    )
    (daemon / "usr/bin").mkdir(parents=True, exist_ok=True)
    (daemon / "usr/bin/openrazer-daemon").write_text("#!/usr/bin/python3\n", encoding="utf-8")
    (daemon / "usr/share/openrazer").mkdir(parents=True, exist_ok=True)
    (daemon / "usr/share/openrazer/razer.conf.example").write_text("# example\n", encoding="utf-8")
    (daemon / "usr/share/man/man5").mkdir(parents=True, exist_ok=True)
    (daemon / "usr/share/man/man8").mkdir(parents=True, exist_ok=True)
    (daemon / "usr/share/man/man5/razer.conf.5.gz").write_bytes(b"fake-gz")
    (daemon / "usr/share/man/man8/openrazer-daemon.8.gz").write_bytes(b"fake-gz")
    if family == "debian":
        daemon_mod = daemon / "usr/lib/python3/dist-packages/openrazer_daemon"
        client_mod = stages["python-openrazer-local"] / "usr/lib/python3/dist-packages/openrazer"
    else:
        daemon_mod = daemon / f"usr/lib/python{minor}/site-packages/openrazer_daemon"
        client_mod = (
            stages["python-openrazer-local"] / f"usr/lib/python{minor}/site-packages/openrazer"
        )
    for mod, egg in ((daemon_mod, "openrazer_daemon"), (client_mod, "openrazer")):
        mod.mkdir(parents=True, exist_ok=True)
        (mod / "__init__.py").write_text("# fixture\n", encoding="utf-8")
        egg_dir = mod.parent / f"{egg}-3.12.1-py{minor}.egg-info"
        egg_dir.mkdir(parents=True, exist_ok=True)
        for leaf in (
            "PKG-INFO",
            "SOURCES.txt",
            "dependency_links.txt",
            "requires.txt",
            "top_level.txt",
        ):
            (egg_dir / leaf).write_text("Name\n", encoding="utf-8")
    for role, root in stages.items():
        _chmod_tree(root, role, pkgver)
    return stages


def _tar_add(tar: tarfile.TarFile, name: str, data: bytes, mode: int, mtime: int = 0) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = mtime
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    tar.addfile(info, io.BytesIO(data))


def _tar_add_dir(tar: tarfile.TarFile, name: str) -> None:
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = 0
    tar.addfile(info)


tar_add = _tar_add
tar_add_dir = _tar_add_dir


def make_tar_bytes(role: str, commit: str, minor: str = "3.10") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        _tar_add_dir(tar, "./")
        files = [
            (f"./usr/share/doc/{role}/source-commit", (commit + "\n").encode("ascii"), 0o644),
            (f"./usr/share/doc/{role}/copyright", b"license\n", 0o644),
        ]
        if role == "openrazer-driver-dkms-local":
            files.extend(
                [
                    (f"./usr/src/openrazer-driver-{PKGVER}/dkms.conf", b"conf\n", 0o644),
                    (f"./usr/src/openrazer-driver-{PKGVER}/Makefile", b"all:\n", 0o644),
                    (f"./usr/src/openrazer-driver-{PKGVER}/dkms-make", b"#!/bin/sh\n", 0o755),
                    ("./usr/lib/udev/rules.d/99-razer.rules", b'GROUP="openrazer"\n', 0o644),
                    ("./usr/lib/udev/razer_mount", b"# openrazer\n", 0o755),
                    (
                        "./usr/share/metainfo/io.github.openrazer.openrazer.metainfo.xml",
                        b"<x/>\n",
                        0o644,
                    ),
                ]
            )
        dist = "openrazer_daemon" if role == "openrazer-daemon-local" else "openrazer"
        if role == "openrazer-daemon-local":
            files.extend(
                [
                    ("./usr/bin/openrazer-daemon", b"#!/usr/bin/python3\n", 0o755),
                    ("./usr/share/openrazer/razer.conf.example", b"# example\n", 0o644),
                    ("./usr/share/dbus-1/services/org.razer.service", b"[D-BUS Service]\n", 0o644),
                    ("./usr/lib/systemd/user/openrazer-daemon.service", b"[Unit]\n", 0o644),
                    ("./usr/share/man/man5/razer.conf.5.gz", b"fake-gz", 0o644),
                    ("./usr/share/man/man8/openrazer-daemon.8.gz", b"fake-gz", 0o644),
                ]
            )
        if role != "openrazer-driver-dkms-local":
            files.append(
                (f"./usr/lib/python3/dist-packages/{dist}/__init__.py", b"# fixture\n", 0o644)
            )
            egg = f"{dist}-3.12.1-py{minor}.egg-info"
            for leaf in (
                "PKG-INFO",
                "SOURCES.txt",
                "dependency_links.txt",
                "requires.txt",
                "top_level.txt",
            ):
                files.append((f"./usr/lib/python3/dist-packages/{egg}/{leaf}", b"Name\n", 0o644))
        for name, data, mode in files:
            _tar_add(tar, name, data, mode)
    return buffer.getvalue()


def make_control_tar_bytes(role: str, version: str, minor: str, pkgver: str) -> bytes:
    from buildpython.openrazer_native import recipes as _recipes

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        _tar_add_dir(tar, "./")
        _tar_add(
            tar, "./control", _recipes.deb_control(role, version, minor).encode("ascii"), 0o644
        )
        _tar_add(tar, "./md5sums", b"fake-md5", 0o644)
        _tar_add(tar, "./postinst", _recipes.deb_postinst(role, pkgver).encode("ascii"), 0o755)
        _tar_add(tar, "./prerm", _recipes.deb_prerm(role, pkgver).encode("ascii"), 0o755)
    return buffer.getvalue()


def _cpio_field(value: int) -> bytes:
    return f"{value:08x}".encode("ascii")


def cpio_entry(name: bytes, content: bytes, mode: int) -> bytes:
    namesize = len(name) + 1
    header = (
        b"070701"
        + _cpio_field(0)
        + _cpio_field(mode)
        + _cpio_field(0)
        + _cpio_field(0)
        + _cpio_field(1)
        + _cpio_field(0)
        + _cpio_field(len(content))
        + _cpio_field(0)
        + _cpio_field(0)
        + _cpio_field(0)
        + _cpio_field(0)
        + _cpio_field(namesize)
        + _cpio_field(0)
    )
    assert len(header) == 110
    out = header + name + b"\0"
    out += b"\0" * ((-(110 + namesize)) % 4)
    out += content
    out += b"\0" * ((-(len(content))) % 4)
    return out


def make_cpio_bytes(role: str, commit: str) -> bytes:
    odd_name = b"a"
    odd_content = b"xyy"
    stamp_name = f"usr/share/doc/{role}/source-commit".encode()
    stamp_content = (commit + "\n").encode("ascii")
    out = cpio_entry(odd_name, odd_content, 0o100644)
    out += cpio_entry(stamp_name, stamp_content, 0o100644)
    out += cpio_entry(b"TRAILER!!!", b"", 0)
    return out


def deb_listing_lines(role: str, minor: str = "3.10") -> list[str]:
    base_lines = [
        "drwxr-xr-x root/root         0 2026-01-01 00:00 ./",
        "drwxr-xr-x root/root         0 2026-01-01 00:00 ./usr/",
        "drwxr-xr-x root/root         0 2026-01-01 00:00 ./usr/share/",
        f"-rw-r--r-- root/root        41 2026-01-01 00:00 ./usr/share/doc/{role}/source-commit",
        f"-rw-r--r-- root/root        41 2026-01-01 00:00 ./usr/share/doc/{role}/copyright",
    ]
    if role == "openrazer-driver-dkms-local":
        base_lines.extend(
            [
                f"-rw-r--r-- root/root        41 2026-01-01 00:00 ./usr/src/openrazer-driver-{PKGVER}/dkms.conf",
                f"-rw-r--r-- root/root        41 2026-01-01 00:00 ./usr/src/openrazer-driver-{PKGVER}/Makefile",
                f"-rwxr-xr-x root/root        41 2026-01-01 00:00 ./usr/src/openrazer-driver-{PKGVER}/dkms-make",
                "-rw-r--r-- root/root        41 2026-01-01 00:00 ./usr/lib/udev/rules.d/99-razer.rules",
                "-rwxr-xr-x root/root        41 2026-01-01 00:00 ./usr/lib/udev/razer_mount",
                "-rw-r--r-- root/root        41 2026-01-01 00:00 ./usr/share/metainfo/io.github.openrazer.openrazer.metainfo.xml",
            ]
        )
        return base_lines
    dist = "openrazer_daemon" if role == "openrazer-daemon-local" else "openrazer"
    if role == "openrazer-daemon-local":
        base_lines.extend(
            [
                "-rwxr-xr-x root/root        41 2026-01-01 00:00 ./usr/bin/openrazer-daemon",
                "-rw-r--r-- root/root        41 2026-01-01 00:00 ./usr/share/openrazer/razer.conf.example",
                "-rw-r--r-- root/root        41 2026-01-01 00:00 ./usr/share/dbus-1/services/org.razer.service",
                "-rw-r--r-- root/root        41 2026-01-01 00:00 ./usr/lib/systemd/user/openrazer-daemon.service",
                "-rw-r--r-- root/root        41 2026-01-01 00:00 ./usr/share/man/man5/razer.conf.5.gz",
                "-rw-r--r-- root/root        41 2026-01-01 00:00 ./usr/share/man/man8/openrazer-daemon.8.gz",
            ]
        )
    if role != "openrazer-driver-dkms-local":
        base_lines.append(
            f"-rw-r--r-- root/root        10 2026-01-01 00:00 ./usr/lib/python3/dist-packages/{dist}/__init__.py"
        )
        egg = f"{dist}-3.12.1-py{minor}.egg-info"
        for leaf in (
            "PKG-INFO",
            "SOURCES.txt",
            "dependency_links.txt",
            "requires.txt",
            "top_level.txt",
        ):
            base_lines.append(
                f"-rw-r--r-- root/root        10 2026-01-01 00:00 ./usr/lib/python3/dist-packages/{egg}/{leaf}"
            )
    return base_lines


def rpm_listing_lines(role: str, minor: str) -> list[str]:
    base_lines = [
        "drwxr-xr-x    1 root     root            0 Jan  1  2026 /usr",
        "-rw-r--r--    1 root     root           41 Jan  1  2026 "
        f"/usr/share/doc/{role}/source-commit",
    ]
    if role == "openrazer-daemon-local":
        base_lines.append(
            "-rw-r--r--    1 root     root           10 Jan  1  2026 "
            f"/usr/lib/python{minor}/site-packages/openrazer_daemon/__init__.py"
        )
    elif role == "python-openrazer-local":
        base_lines.append(
            "-rw-r--r--    1 root     root           10 Jan  1  2026 "
            f"/usr/lib/python{minor}/site-packages/openrazer/__init__.py"
        )
    return base_lines
