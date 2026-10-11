"""Fedora/openSUSE RPM cohort build tests (realistic fakes only)."""

from __future__ import annotations

import fnmatch
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from buildpython.openrazer_native import build, recipes, validation
from tests.openrazer_native_fakes import COMMIT, GPL_TEXT, PIN, completed_stdout, make_pin_file

VERSION = "3.12.1.pr2904.fix2-1"
PKGVER = "3.12.1.pr2904.fix2"
_EGG = ("PKG-INFO", "SOURCES.txt", "dependency_links.txt", "requires.txt", "top_level.txt")


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
        target.write_text("plugdev\n", encoding="utf-8")
    (source / "Makefile").write_text("all:\n", encoding="ascii")
    (source / "daemon").mkdir(parents=True, exist_ok=True)
    (source / "daemon/setup.py").write_text("x\n", encoding="ascii")
    (source / "pylib").mkdir(parents=True, exist_ok=True)
    (source / "pylib/setup.py").write_text("x\n", encoding="ascii")
    (source / "LICENSES").mkdir(parents=True, exist_ok=True)
    (source / "LICENSES/GPL-2.0-or-later.txt").write_text(GPL_TEXT, encoding="utf-8")
    return source


class RpmBuildFake:
    def __init__(self, family: str, minor: str) -> None:
        self.calls: list[list[str]] = []
        self.family = family
        self.minor = minor
        self.spec_text = ""
        self.merged: Path | None = None
        self.topdir: Path | None = None

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
                encoding="utf-8",
            )
            (dkms_dir / "Makefile").write_text("all:\n", encoding="utf-8")
            (dest / "usr/lib/udev/rules.d").mkdir(parents=True, exist_ok=True)
            (dest / "usr/lib/udev/rules.d/99-razer.rules").write_text(
                'GROUP="openrazer"\n', encoding="utf-8"
            )
            (dest / "usr/lib/udev/razer_mount").parent.mkdir(parents=True, exist_ok=True)
            (dest / "usr/lib/udev/razer_mount").write_text("# openrazer\n", encoding="utf-8")
            (dest / "usr/share/metainfo").mkdir(parents=True, exist_ok=True)
            (dest / "usr/share/metainfo/io.github.openrazer.openrazer.metainfo.xml").write_text(
                "<x/>\n", encoding="utf-8"
            )
            return completed_stdout("")
        if items[0] == "make" and "install-resources" in items:
            dest = Path(next(a for a in items if a.startswith("DESTDIR=")).split("=", 1)[1])
            (dest / "usr/lib/systemd/user").mkdir(parents=True, exist_ok=True)
            (dest / "usr/lib/systemd/user/openrazer-daemon.service").write_text(
                "[Unit]\n[Service]\nType=dbus\nBusName=org.razer\nExecStart=/usr/bin/openrazer-daemon -F\n[Install]\nWantedBy=default.target\n",
                encoding="utf-8",
            )
            (dest / "usr/share/dbus-1/services").mkdir(parents=True, exist_ok=True)
            (dest / "usr/share/dbus-1/services/org.razer.service").write_text(
                "[D-BUS Service]\nName=org.razer\nExec=/usr/bin/openrazer-daemon\nSystemdService=openrazer-daemon.service\n",
                encoding="utf-8",
            )
            (dest / "usr/bin").mkdir(parents=True, exist_ok=True)
            (dest / "usr/bin/openrazer-daemon").write_text("#!/usr/bin/python3\n", encoding="utf-8")
            (dest / "usr/share/openrazer").mkdir(parents=True, exist_ok=True)
            (dest / "usr/share/openrazer/razer.conf.example").write_text(
                "# example\n", encoding="utf-8"
            )
            (dest / "usr/share/man/man5").mkdir(parents=True, exist_ok=True)
            (dest / "usr/share/man/man8").mkdir(parents=True, exist_ok=True)
            (dest / "usr/share/man/man5/razer.conf.5.gz").write_bytes(b"fake-gz")
            (dest / "usr/share/man/man8/openrazer-daemon.8.gz").write_bytes(b"fake-gz")
            return completed_stdout("")
        if "setup.py" in items:
            root = Path(next(a for a in items if a.startswith("--root=")).split("=", 1)[1])
            lib = next(a for a in items if a.startswith("--install-lib=")).split("=", 1)[1]
            assert cwd is not None
            package = "openrazer_daemon" if cwd.name == "daemon" else "openrazer"
            mod = root / lib.removeprefix("/") / package
            mod.mkdir(parents=True, exist_ok=True)
            (mod / "__init__.py").write_text("# fixture\n", encoding="utf-8")
            egg = root / lib.removeprefix("/") / f"{package}-3.12.1-py{self.minor}.egg-info"
            egg.mkdir(parents=True, exist_ok=True)
            for leaf in _EGG:
                (egg / leaf).write_text("Name\n", encoding="utf-8")
            return completed_stdout("")
        if items[0] == "rpmbuild":
            topdir = Path(next(a for a in items if a.startswith("_topdir ")).split(" ", 1)[1])
            stagedir = Path(next(a for a in items if a.startswith("stagedir ")).split(" ", 1)[1])
            tmppath = Path(next(a for a in items if a.startswith("_tmppath ")).split(" ", 1)[1])
            if not tmppath.is_dir() or (tmppath.stat().st_mode & 0o777) != 0o700:
                raise AssertionError("_tmppath must be an owned 0700 workdir")
            if tmppath.parent != topdir.parent:
                raise AssertionError("_tmppath must stay inside the owned workdir")
            spec_path = Path(items[-1])
            self.spec_text = spec_path.read_text(encoding="ascii")
            self.merged = stagedir
            self.topdir = topdir
            staged_files = {
                p.relative_to(stagedir).as_posix()
                for p in stagedir.rglob("*")
                if p.is_file() and not p.is_symlink()
            }
            spec_files = _spec_file_set(self.spec_text)
            for covered in spec_files:
                if (
                    "*" not in covered
                    and covered not in staged_files
                    and not any(s == covered or s.startswith(covered + "/") for s in staged_files)
                ):
                    return subprocess.CompletedProcess(
                        args=[], returncode=1, stdout="", stderr=f"missing {covered}\n"
                    )
            for staged in staged_files:
                covered_prefix = any(
                    staged == p.rstrip("/") or staged.startswith(p.rstrip("/") + "/")
                    for p in spec_files
                    if "*" not in p
                )
                covered_glob = any(
                    fnmatch.fnmatch(staged, p) or fnmatch.fnmatch(staged, p + "*")
                    for p in spec_files
                    if "*" in p
                )
                if not (covered_prefix or covered_glob):
                    return subprocess.CompletedProcess(
                        args=[], returncode=1, stdout="", stderr=f"unowned {staged}\n"
                    )
            rpmdir = topdir / "RPMS" / "noarch"
            rpmdir.mkdir(parents=True, exist_ok=True)
            for _role, filename in zip(
                recipes.LOCAL_ROLES, recipes.expected_filenames(self.family, PIN), strict=True
            ):
                (rpmdir / filename).write_bytes(b"fake-rpm")
            return completed_stdout("")
        if items[0] == "rpm" and items[1] == "-qp":
            role = Path(items[-1]).name.split("-local")[0] + "-local"
            if items[2] == "--queryformat":
                query = items[3]
                if query == "%{NAME}":
                    return completed_stdout(role + "\n")
                if query == "%{VERSION}":
                    return completed_stdout(PKGVER + "\n")
                if query == "%{RELEASE}":
                    return completed_stdout("1\n")
                if query == "%{ARCH}":
                    return completed_stdout("noarch\n")
            if items[2] == "--requires":
                reqs = list(recipes.rpm_requires(self.family, role, VERSION, self.minor))
                reqs.extend(
                    [
                        "rpmlib(CompressedFileNames) <= 3.0.4-1",
                        "rpmlib(FileDigests) <= 4.6.0-1",
                        "rpmlib(PayloadFilesHavePrefix) <= 4.0-1",
                        "rpmlib(PayloadIsZstd) <= 5.4.18-1",
                    ]
                )
                if role != "openrazer-driver-dkms-local":
                    reqs.append("rpmlib(PartialHardlinkSets) <= 4.0.4-1")
                if role == "openrazer-driver-dkms-local":
                    reqs.append("/bin/sh")
                    if self.family == "fedora":
                        reqs.append("/usr/bin/sh")
                if role == "openrazer-daemon-local":
                    reqs.append("/usr/bin/python3")
                    if self.family == "opensuse":
                        reqs.append(f"python(abi) = {self.minor}")
                elif role == "python-openrazer-local" and self.family == "opensuse":
                    reqs.append(f"python(abi) = {self.minor}")
                return completed_stdout("\n".join(reqs) + "\n")
            if items[2] == "--provides":
                upstream = recipes.UPSTREAM_RPM[role]
                lines = [f"{role} = {VERSION}", upstream]
                if role == "openrazer-driver-dkms-local":
                    lines.append("metainfo()")
                    lines.append("metainfo(io.github.openrazer.openrazer.metainfo.xml)")
                elif self.family == "opensuse":
                    dist = "openrazer-daemon" if role == "openrazer-daemon-local" else "openrazer"
                    lines.append(f"python{self.minor}dist({dist}) = 3.12.1")
                    lines.append(f"python3dist({dist}) = 3.12.1")
                return completed_stdout("\n".join(lines) + "\n")
            if items[2] in ("--conflicts", "--obsoletes"):
                return completed_stdout(recipes.UPSTREAM_RPM[role] + "\n")
            if items[2] == "--scripts":
                if role == "openrazer-driver-dkms-local":
                    return completed_stdout(
                        "getent group openrazer\n groupadd -r openrazer\ndkms install openrazer-driver/3.12.1.pr2904.fix2\n$1\n"
                    )
                return completed_stdout("")
            if items[2] == "--triggers":
                return completed_stdout("")
        if items[0] == "rpm" and items[1] == "-qplv":
            role = Path(items[-1]).name.split("-local")[0] + "-local"
            assert self.merged is not None
            pylib = f"usr/lib/python{self.minor}/site-packages"
            dist = "openrazer_daemon" if role == "openrazer-daemon-local" else "openrazer"
            egg = f"{dist}-3.12.1-py{self.minor}.egg-info"
            if role == "openrazer-driver-dkms-local":
                rels = [
                    f"usr/src/openrazer-driver-{PKGVER}/dkms.conf",
                    f"usr/src/openrazer-driver-{PKGVER}/Makefile",
                    f"usr/src/openrazer-driver-{PKGVER}/dkms-make",
                    "usr/lib/udev/rules.d/99-razer.rules",
                    "usr/lib/udev/razer_mount",
                    "usr/share/metainfo/io.github.openrazer.openrazer.metainfo.xml",
                    f"usr/share/doc/{role}/source-commit",
                    f"usr/share/doc/{role}/copyright",
                ]
            elif role == "openrazer-daemon-local":
                rels = [
                    "usr/bin/openrazer-daemon",
                    "usr/share/openrazer/razer.conf.example",
                    "usr/share/dbus-1/services/org.razer.service",
                    "usr/lib/systemd/user/openrazer-daemon.service",
                    "usr/share/man/man5/razer.conf.5.gz",
                    "usr/share/man/man8/openrazer-daemon.8.gz",
                    f"{pylib}/{dist}/__init__.py",
                ]
            else:
                rels = [f"{pylib}/{dist}/__init__.py"]
            if role != "openrazer-driver-dkms-local":
                rels += [f"{pylib}/{egg}/{leaf}" for leaf in _EGG]
                rels += [f"usr/share/doc/{role}/source-commit", f"usr/share/doc/{role}/copyright"]
            lines = ["drwxr-xr-x    1 root     root            0 Jan  1  2026 /usr"]
            for rel in rels:
                lines.append(f"-rw-r--r--    1 root     root           41 Jan  1  2026 /{rel}")
            return completed_stdout("\n".join(lines) + "\n")
        raise AssertionError(f"unexpected rpm command: {items}")


def _spec_file_set(spec: str) -> set[str]:
    files: set[str] = set()
    in_files = False
    for line in spec.splitlines():
        if line.startswith("%files"):
            in_files = True
            continue
        if line.startswith("%defattr"):
            continue
        if line.startswith("%") and in_files:
            in_files = False
            continue
        if in_files and line.startswith("/"):
            files.add(line.strip().removeprefix("/").removesuffix("/"))
    return files


class RpmByteFake:
    def __init__(self, fake: RpmBuildFake) -> None:
        self.fake = fake
        self.calls: list[list[str]] = []

    def __call__(self, cmd: Sequence[str], cwd: Path | None) -> subprocess.CompletedProcess[bytes]:
        from tests.openrazer_native_fakes import cpio_entry

        items = list(cmd)
        self.calls.append(items)
        role = Path(items[-1]).name.split("-local")[0] + "-local"
        stamp = (COMMIT + "\n").encode("ascii")
        out = cpio_entry(f"usr/share/doc/{role}/source-commit".encode(), stamp, 0o100644)
        pylib = f"usr/lib/python{self.fake.minor}/site-packages"
        dist = "openrazer_daemon" if role == "openrazer-daemon-local" else "openrazer"
        egg = f"{dist}-3.12.1-py{self.fake.minor}.egg-info"
        if role == "openrazer-driver-dkms-local":
            rels = [
                (f"usr/src/openrazer-driver-{PKGVER}/dkms.conf", b"conf\n"),
                (f"usr/src/openrazer-driver-{PKGVER}/Makefile", b"all:\n"),
                (f"usr/src/openrazer-driver-{PKGVER}/dkms-make", b"#!/bin/sh\n"),
                ("usr/lib/udev/rules.d/99-razer.rules", b'GROUP="openrazer"\n'),
                ("usr/lib/udev/razer_mount", b"# openrazer\n"),
                ("usr/share/metainfo/io.github.openrazer.openrazer.metainfo.xml", b"<x/>\n"),
                (f"usr/share/doc/{role}/copyright", b"license\n"),
            ]
        elif role == "openrazer-daemon-local":
            rels = [
                ("usr/bin/openrazer-daemon", b"#!/usr/bin/python3\n"),
                ("usr/share/openrazer/razer.conf.example", b"# example\n"),
                ("usr/share/dbus-1/services/org.razer.service", b"[D-BUS Service]\n"),
                ("usr/lib/systemd/user/openrazer-daemon.service", b"[Unit]\n"),
                ("usr/share/man/man5/razer.conf.5.gz", b"fake-gz"),
                ("usr/share/man/man8/openrazer-daemon.8.gz", b"fake-gz"),
                (f"{pylib}/{dist}/__init__.py", b"# fixture\n"),
                (f"usr/share/doc/{role}/copyright", b"license\n"),
            ]
        else:
            rels = [
                (f"{pylib}/{dist}/__init__.py", b"# fixture\n"),
                (f"usr/share/doc/{role}/copyright", b"license\n"),
            ]
        if role != "openrazer-driver-dkms-local":
            for leaf in _EGG:
                rels.append((f"{pylib}/{egg}/{leaf}", b"Name\n"))
        for rel, content in rels:
            out += cpio_entry(rel.encode(), content, 0o100644)
        out += cpio_entry(b"TRAILER!!!", b"", 0)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=out, stderr=b"")


@pytest.mark.parametrize("family", ["fedora", "opensuse"])
def test_rpm_cohort_build_success(tmp_path: Path, family: str) -> None:
    source = _make_source(tmp_path)
    output = tmp_path / "out"
    output.mkdir()
    pin_path = make_pin_file(tmp_path)
    minor = validation.current_python_minor()
    fake = RpmBuildFake(family, minor)
    manifest = build.build_native_packages(
        source=source,
        output=output,
        pin_path=pin_path,
        family=family,
        euid=output.stat().st_uid,
        runner=fake,
        byte_runner=RpmByteFake(fake),
    )
    expected = recipes.expected_filenames(family, PIN)
    assert sorted(p.name for p in output.iterdir() if p.suffix == ".rpm") == sorted(expected)
    assert manifest["family"] == family
    assert len(manifest["packages"]) == 3  # type: ignore[union-attr]


def test_rpm_incomplete_files_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _make_source(tmp_path)
    output = tmp_path / "out"
    output.mkdir()
    pin_path = make_pin_file(tmp_path)
    minor = validation.current_python_minor()
    old_spec = recipes.rpm_spec

    def _bad_spec(family: str, version: str, minor_arg: str, pkgver: str) -> str:
        assert minor_arg == minor
        text = old_spec(family, version, minor_arg, pkgver)
        lines = [
            line
            for line in text.splitlines()
            if "razer.conf.example" not in line and "openrazer_daemon" not in line
        ]
        return "\n".join(lines) + "\n"

    monkeypatch.setattr(recipes, "rpm_spec", _bad_spec)
    fake = RpmBuildFake("fedora", minor)
    with pytest.raises(ValueError, match=r"missing|Mismatch|disagree|lacks|unowned|rpmbuild"):
        build.build_native_packages(
            source=source,
            output=output,
            pin_path=pin_path,
            family="fedora",
            euid=output.stat().st_uid,
            runner=fake,
            byte_runner=RpmByteFake(fake),
        )
    assert not list(output.iterdir())
