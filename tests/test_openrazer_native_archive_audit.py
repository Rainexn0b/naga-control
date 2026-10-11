"""Negative archive tests: root, foreign payloads, metadata rejects (fakes only)."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from buildpython.openrazer_native import archive_audit, rpm_audit
from tests.openrazer_native_fakes import COMMIT, PKGVER, VERSION, tar_add, tar_add_dir

MINOR = "3.10"
ROLE = "openrazer-daemon-local"


def test_control_tar_real_root_layout_passes() -> None:
    from tests.openrazer_native_fakes import make_control_tar_bytes

    raw = make_control_tar_bytes(ROLE, VERSION, MINOR, PKGVER)
    archive_audit.parse_deb_control_tar(raw, ROLE, VERSION, MINOR, PKGVER)


def test_control_tar_duplicate_root_rejected() -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        tar_add_dir(tar, "./")
        tar_add_dir(tar, "./")
    with pytest.raises(ValueError, match=r"root|Duplicate"):
        archive_audit.parse_deb_control_tar(buffer.getvalue(), ROLE, VERSION, MINOR, PKGVER)


def test_control_tar_file_root_rejected() -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        tar_add(tar, "./", b"file-root\n", 0o644)
    with pytest.raises(ValueError, match=r"root|Invalid"):
        archive_audit.parse_deb_control_tar(buffer.getvalue(), ROLE, VERSION, MINOR, PKGVER)


def test_control_tar_rejects_trigger_member() -> None:
    from tests.openrazer_native_fakes import make_control_tar_bytes

    raw = make_control_tar_bytes(ROLE, VERSION, MINOR, PKGVER)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as src:
        members: list[tuple[tarfile.TarInfo, bytes]] = []
        for info in src.getmembers():
            if info.isreg():
                extracted = src.extractfile(info)
                assert extracted is not None
                members.append((info, extracted.read()))
            else:
                members.append((info, b""))
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        for member, data in members:
            if member.isdir():
                tar_add_dir(tar, member.name)
            else:
                tar_add(
                    tar,
                    member.name,
                    data,
                    0o755 if member.name.endswith(("postinst", "prerm")) else 0o644,
                )
        tar_add(tar, "./triggers", b"activate\n", 0o644)
    with pytest.raises(ValueError, match="unexpected"):
        archive_audit.parse_deb_control_tar(out.getvalue(), ROLE, VERSION, MINOR, PKGVER)


def test_data_tar_rejects_foreign_etc_path() -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        tar_add_dir(tar, "./")
        tar_add(tar, "./etc/evil", b"x\n", 0o644)
    with pytest.raises(ValueError, match=r"foreign|usr|payload"):
        archive_audit.parse_deb_data_tar(buffer.getvalue(), ROLE, COMMIT, PKGVER)


def test_listing_rejects_foreign_minor_and_role_egg() -> None:
    bad_minor = [
        "drwxr-xr-x root/root         0 2026-01-01 00:00 ./",
        f"-rw-r--r-- root/root        41 2026-01-01 00:00 ./usr/share/doc/{ROLE}/source-commit",
        "-rw-r--r-- root/root        10 2026-01-01 00:00 ./usr/lib/python3/dist-packages/openrazer_daemon/__init__.py",
        "-rw-r--r-- root/root        10 2026-01-01 00:00 ./usr/lib/python3/dist-packages/openrazer_daemon-3.12.1-py3.11.egg-info/PKG-INFO",
    ]
    with pytest.raises(ValueError, match=r"egg|Foreign|minor"):
        archive_audit.audit_member_listing(bad_minor, ROLE, "debian", MINOR, False)
    cross_role = [
        "drwxr-xr-x root/root         0 2026-01-01 00:00 ./",
        f"-rw-r--r-- root/root        41 2026-01-01 00:00 ./usr/share/doc/{ROLE}/source-commit",
        "-rw-r--r-- root/root        10 2026-01-01 00:00 ./usr/lib/python3/dist-packages/openrazer_daemon/__init__.py",
        "-rw-r--r-- root/root        10 2026-01-01 00:00 ./usr/lib/python3/dist-packages/openrazer-3.12.1-py3.10.egg-info/PKG-INFO",
    ]
    with pytest.raises(ValueError, match=r"egg|Foreign|mismatch"):
        archive_audit.audit_member_listing(cross_role, ROLE, "debian", MINOR, False)


def test_rpm_rejects_foreign_abi_dist_metainfo(tmp_path: Path) -> None:
    actual_abi = {"python(abi) = 3.11", "python3 >= 3.10"}
    with pytest.raises(ValueError, match=r"unexpected|ABI"):
        rpm_audit.check_requires(actual_abi | {"x"}, "fedora", ROLE, VERSION, MINOR)
    provides = {
        ROLE,
        f"{ROLE} = {VERSION}",
        "openrazer-daemon",
        "python3.11dist(openrazer_daemon) = 3.12.1",
    }
    with pytest.raises(ValueError, match=r"upstream|Provides"):
        rpm_audit.check_provides(provides, ROLE, "fedora", MINOR, VERSION)
    bad_meta = {ROLE, f"{ROLE} = {VERSION}", "openrazer-daemon", "metainfo(evil.xml)"}
    with pytest.raises(ValueError, match=r"upstream|Provides|metainfo"):
        rpm_audit.check_provides(bad_meta, ROLE, "fedora", MINOR, VERSION)
    _ = tmp_path


def test_control_tar_rejects_symlink_duplicate_and_bad_mode() -> None:
    from tests.openrazer_native_fakes import make_control_tar_bytes

    raw = make_control_tar_bytes(ROLE, VERSION, MINOR, PKGVER)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as src:
        dup_members: list[tuple[tarfile.TarInfo, bytes]] = []
        for info in src.getmembers():
            if info.isreg():
                extracted = src.extractfile(info)
                assert extracted is not None
                dup_members.append((info, extracted.read()))
            else:
                dup_members.append((info, b""))
    dup = io.BytesIO()
    with tarfile.open(fileobj=dup, mode="w") as tar:
        for member, data in dup_members:
            if member.isdir():
                tar_add_dir(tar, member.name)
            else:
                tar_add(tar, member.name, data, 0o644)
        tar_add(tar, "./control", b"dup\n", 0o644)
    with pytest.raises(ValueError, match=r"Duplicate|unexpected|Invalid"):
        archive_audit.parse_deb_control_tar(dup.getvalue(), ROLE, VERSION, MINOR, PKGVER)
    link_buf = io.BytesIO()
    with tarfile.open(fileobj=link_buf, mode="w") as tar:
        tar_add_dir(tar, "./")
        info = tarfile.TarInfo(name="./control")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        info.mode = 0o777
        info.uid = 0
        info.gid = 0
        info.mtime = 0
        tar.addfile(info)
    with pytest.raises(ValueError, match=r"special|Invalid|symlink"):
        archive_audit.parse_deb_control_tar(link_buf.getvalue(), ROLE, VERSION, MINOR, PKGVER)


def test_data_tar_rejects_duplicate_root_and_file_modes() -> None:
    dup_root = io.BytesIO()
    with tarfile.open(fileobj=dup_root, mode="w") as tar:
        tar_add_dir(tar, "./")
        tar_add_dir(tar, "./")
    with pytest.raises(ValueError, match=r"root|Duplicate|Invalid"):
        archive_audit.parse_deb_data_tar(dup_root.getvalue(), ROLE, COMMIT, PKGVER)
    file_root = io.BytesIO()
    with tarfile.open(fileobj=file_root, mode="w") as tar:
        tar_add(tar, "./", b"file-root\n", 0o644)
    with pytest.raises(ValueError, match=r"root|Invalid|Duplicate"):
        archive_audit.parse_deb_data_tar(file_root.getvalue(), ROLE, COMMIT, PKGVER)


def test_listing_rejects_foreign_version_and_py_tree() -> None:
    bad_version = [
        "drwxr-xr-x root/root         0 2026-01-01 00:00 ./",
        f"-rw-r--r-- root/root        41 2026-01-01 00:00 ./usr/share/doc/{ROLE}/source-commit",
        "-rw-r--r-- root/root        10 2026-01-01 00:00 ./usr/lib/python3/dist-packages/openrazer_daemon/__init__.py",
        "-rw-r--r-- root/root        10 2026-01-01 00:00 ./usr/lib/python3/dist-packages/openrazer_daemon-9.9.9-py3.10.egg-info/PKG-INFO",
    ]
    with pytest.raises(ValueError, match=r"egg|Foreign|minor"):
        archive_audit.audit_member_listing(bad_version, ROLE, "debian", MINOR, False)
    evil_tree = [
        "drwxr-xr-x root/root         0 2026-01-01 00:00 ./",
        f"-rw-r--r-- root/root        41 2026-01-01 00:00 ./usr/share/doc/{ROLE}/source-commit",
        "-rw-r--r-- root/root        10 2026-01-01 00:00 ./usr/lib/python3/dist-packages/openrazer_daemon/__init__.py",
        "-rw-r--r-- root/root        10 2026-01-01 00:00 ./usr/lib/python3/dist-packages/openrazer_daemon-3.12.1-py3.10.egg-info/PKG-INFO",
        "-rw-r--r-- root/root        10 2026-01-01 00:00 ./usr/lib/python3/dist-packages/evil_package/__init__.py",
    ]
    with pytest.raises(ValueError, match=r"Foreign|egg"):
        archive_audit.audit_member_listing(evil_tree, ROLE, "debian", MINOR, False)


def test_rpm_rejects_unknown_dep_and_wrong_role_dist() -> None:
    from buildpython.openrazer_native import recipes

    expected = set(recipes.rpm_requires("opensuse", ROLE, VERSION, MINOR))
    with pytest.raises(ValueError, match="unexpected"):
        rpm_audit.check_requires(expected | {"evil-new-dep = 1"}, "opensuse", ROLE, VERSION, MINOR)
    provides = {
        ROLE,
        f"{ROLE} = {VERSION}",
        "openrazer-daemon",
        "python3.13dist(openrazer) = 3.12.1",
    }
    with pytest.raises(ValueError, match=r"upstream|Provides"):
        rpm_audit.check_provides(provides, ROLE, "opensuse", "3.13", VERSION)
    bad_version = {
        ROLE,
        f"{ROLE} = {VERSION}",
        "openrazer-daemon",
        "python3.13dist(openrazer_daemon) = 9.9.9",
    }
    with pytest.raises(ValueError, match=r"upstream|Provides"):
        rpm_audit.check_provides(bad_version, ROLE, "opensuse", "3.13", VERSION)
    assert (
        rpm_audit.egg_info_dir("openrazer_daemon", "3.13")
        == "openrazer_daemon-3.12.1-py3.13.egg-info"
    )


def test_rpm_rejects_unknown_rpmlib_generator() -> None:
    from buildpython.openrazer_native import recipes

    expected = set(recipes.rpm_requires("fedora", ROLE, VERSION, MINOR))
    with pytest.raises(ValueError, match="unexpected"):
        rpm_audit.check_requires(
            expected | {"rpmlib(EvilGenerator) <= 1-1"}, "fedora", ROLE, VERSION, MINOR
        )
