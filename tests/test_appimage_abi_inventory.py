"""Confined, deterministic payload inventory; only temporary synthetic files."""

import os
import socket
from pathlib import Path
from typing import NoReturn

import pytest
from appimage_abi_fakes import FakeInspector, write_elf

from buildpython.steps.appimage import abi


def test_magic_not_extension_execute_bit_or_hidden_path_and_deterministic_order(
    tmp_path: Path,
) -> None:
    write_elf(tmp_path, ".hidden/native.data")
    write_elf(tmp_path, "usr/plugins/libqt-plugin")
    decoy = tmp_path / "usr/plugins/decoy.so"
    decoy.write_text("not ELF")
    decoy.chmod(0o755)
    fake = FakeInspector()
    report = abi.audit(tmp_path, inspector=fake)
    assert report.status == "pass"
    assert [item.paths for item in report.payloads] == [
        (".hidden/native.data",),
        ("usr/plugins/libqt-plugin",),
    ]
    assert len(fake.contents) == 2


def test_file_directory_symlinks_and_hardlinks_account_aliases_once(tmp_path: Path) -> None:
    original = write_elf(tmp_path, "usr/lib/object.so.1")
    (tmp_path / "usr/lib/object.so").symlink_to("object.so.1")
    (tmp_path / "usr/lib64").symlink_to("lib", target_is_directory=True)
    (tmp_path / "absolute-alias").symlink_to(original)
    os.link(original, tmp_path / "hardlink")
    fake = FakeInspector()
    report = abi.audit(tmp_path, inspector=fake)
    assert report.status == "pass", report.errors
    assert len(fake.contents) == 1
    assert report.payloads[0].paths == (
        "absolute-alias",
        "hardlink",
        "usr/lib/object.so",
        "usr/lib/object.so.1",
        "usr/lib64/object.so",
        "usr/lib64/object.so.1",
    )


@pytest.mark.parametrize("target", ["../../outside", "/unapproved/outside", "missing", "loop"])
def test_external_dangling_or_cyclic_links_are_errors(tmp_path: Path, target: str) -> None:
    root = tmp_path / "AppDir"
    write_elf(root)
    (root / "loop").symlink_to(target)
    fake = FakeInspector()
    report = abi.audit(root, inspector=fake)
    assert report.status == "fail" and not report.inventory_complete
    assert "loop:" in " ".join(report.errors)
    assert "/unapproved/" not in " ".join(report.errors)
    assert len(fake.contents) == 1


def test_no_external_payload_or_directory_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "AppDir"
    write_elf(root)
    outside = write_elf(tmp_path / "outside")
    (root / "external-file").symlink_to(outside)
    (root / "external-dir").symlink_to(outside.parent)
    opened: list[str] = []
    original_open = abi.open_relative

    def guarded(root_fd: int, relative: str, *, directory: bool = False) -> int:
        opened.append(relative)
        assert "outside" not in relative
        return original_open(root_fd, relative, directory=directory)

    monkeypatch.setattr(abi, "open_relative", guarded)
    report = abi.audit(root, inspector=FakeInspector())
    assert report.status == "fail" and opened
    assert "external-file: symlink escapes" in " ".join(report.errors)
    assert "external-dir: symlink escapes" in " ".join(report.errors)


def test_directory_cycle_and_nondirectory_link_components_fail(tmp_path: Path) -> None:
    write_elf(tmp_path)
    (tmp_path / "usr/lib/parent").symlink_to("..")
    (tmp_path / "bad-component").symlink_to("usr/lib/payload/../payload")
    report = abi.audit(tmp_path, inspector=FakeInspector())
    assert report.status == "fail"
    assert "cyclic directory link" in " ".join(report.errors)
    assert "non-directory" in " ".join(report.errors)


@pytest.mark.parametrize("target", ["usr/lib/payload/", "usr/lib/payload/."])
def test_file_link_with_directory_suffix_is_dangling_not_an_alias(
    tmp_path: Path, target: str
) -> None:
    write_elf(tmp_path)
    (tmp_path / "dangling").symlink_to(target)
    report = abi.audit(tmp_path, inspector=FakeInspector())
    assert report.status == "fail"
    assert "dangling: symlink traverses a non-directory" in " ".join(report.errors)


@pytest.mark.parametrize("kind", ["missing", "file", "symlink"])
def test_invalid_root_is_sanitized(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "AppDir"
    if kind == "file":
        root.write_text("not a directory")
    elif kind == "symlink":
        target = tmp_path / "target"
        target.mkdir()
        root.symlink_to(target)
    report = abi.audit(root, inspector=FakeInspector())
    assert report.status == "fail"
    assert str(tmp_path) not in " ".join(report.errors)


def test_empty_noelf_or_truncated_elf_is_not_success(tmp_path: Path) -> None:
    assert abi.audit(tmp_path, inspector=FakeInspector()).status == "fail"
    (tmp_path / "fake.so").write_bytes(b"ELF but not actual magic")
    assert abi.audit(tmp_path, inspector=FakeInspector()).status == "fail"
    (tmp_path / "broken").write_bytes(b"\x7fELF")
    report = abi.audit(tmp_path, inspector=FakeInspector())
    assert report.status == "fail" and not report.inventory_complete


@pytest.mark.parametrize("magic", [b"!<arch>\n", b"!<thin>\n"])
def test_archives_fail_instead_of_silent_coverage_claim(tmp_path: Path, magic: bytes) -> None:
    write_elf(tmp_path)
    (tmp_path / "native.archive").write_bytes(magic + b"synthetic member")
    report = abi.audit(tmp_path, inspector=FakeInspector())
    assert report.status == "fail"
    assert "native ar archive unsupported; inventory is incomplete" in " ".join(report.errors)


def test_fifo_and_socket_are_rejected_without_opening_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_elf(tmp_path)
    os.mkfifo(tmp_path / "fifo")
    original = abi.open_relative

    def guarded(root_fd: int, relative: str, *, directory: bool = False) -> int:
        assert relative not in ("fifo", "socket")
        return original(root_fd, relative, directory=directory)

    monkeypatch.setattr(abi, "open_relative", guarded)
    with socket.socket(socket.AF_UNIX) as connection:
        connection.bind(str(tmp_path / "socket"))
        report = abi.audit(tmp_path, inspector=FakeInspector())
    assert report.status == "fail"
    assert "fifo: nonregular" in " ".join(report.errors)
    assert "socket: nonregular" in " ".join(report.errors)


def test_read_and_scandir_failures_are_not_empty_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_elf(tmp_path)
    original = abi.open_relative

    def unreadable(root_fd: int, relative: str, *, directory: bool = False) -> int:
        if not directory:
            raise PermissionError("/private/device/path")
        return original(root_fd, relative, directory=directory)

    monkeypatch.setattr(abi, "open_relative", unreadable)
    report = abi.audit(tmp_path, inspector=FakeInspector())
    assert report.status == "fail"
    assert "PermissionError" in " ".join(report.errors)
    assert "/private/" not in " ".join(report.errors)

    def no_scan(_fd: int) -> NoReturn:
        raise PermissionError("/private/device/path")

    monkeypatch.setattr(abi.os, "scandir", no_scan)
    report = abi.audit(tmp_path, inspector=FakeInspector())
    assert report.status == "fail"
    assert "scan failed (PermissionError)" in " ".join(report.errors)


def test_entry_and_elf_size_bounds_are_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_elf(tmp_path)
    monkeypatch.setattr(abi, "MAX_ELF_BYTES", 64)
    assert "ELF size limit exceeded" in " ".join(
        abi.audit(tmp_path, inspector=FakeInspector()).errors
    )
    monkeypatch.setattr(abi, "MAX_ENTRIES", 1)
    assert "inventory entry limit exceeded" in " ".join(
        abi.audit(tmp_path, inspector=FakeInspector()).errors
    )


def test_replaced_file_and_changed_directory_inventory_are_unsafe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_elf(tmp_path)
    original = abi.inspect_payload

    def replaced(
        root_fd: int, item: abi.FileEntry, inspector: abi.Inspector
    ) -> tuple[abi.Payload | None, str]:
        path.unlink()
        path.write_bytes(b"replacement non-ELF")
        (tmp_path / "new-entry").write_text("new data")
        return original(root_fd, item, inspector)

    monkeypatch.setattr(abi, "inspect_payload", replaced)
    report = abi.audit(tmp_path, inspector=FakeInspector())
    assert report.status == "fail"
    assert "payload changed" in " ".join(report.errors)
    assert "inventory mutated" in " ".join(report.errors)


def test_raced_fifo_fails_before_any_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_elf(tmp_path)
    original = abi.open_relative

    def swap(root_fd: int, relative: str, *, directory: bool = False) -> int:
        if not directory:
            path.unlink()
            os.mkfifo(path)
        return original(root_fd, relative, directory=directory)

    def forbidden(_fd: int, _size: int) -> bytes:
        raise AssertionError("must not read a raced nonregular file")

    monkeypatch.setattr(abi, "open_relative", swap)
    monkeypatch.setattr(abi.os, "read", forbidden)
    report = abi.audit(tmp_path, inspector=FakeInspector())
    assert report.status == "fail"
    assert "became nonregular before read" in " ".join(report.errors)


@pytest.mark.parametrize("relative", ["../outside", "/external"])
def test_relative_open_rejects_escape_even_for_direct_call(relative: str) -> None:
    with pytest.raises(ValueError, match="escapes"):
        abi.open_relative(123, relative)
