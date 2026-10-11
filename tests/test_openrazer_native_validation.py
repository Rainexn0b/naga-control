"""Validation and archive tests for the native builder (fakes only)."""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from buildpython.openrazer_native import archive_audit, recipes, rpm_audit, validation
from tests.openrazer_native_fakes import (
    COMMIT,
    PIN,
    FakeRunner,
    completed_stdout,
    deb_listing_lines,
    make_cpio_bytes,
    make_pin_file,
    make_tar_bytes,
    make_valid_stages,
)

MINOR = "3.10"
VERSION = "3.12.1.pr2904.fix2-1"
PKGVER = "3.12.1.pr2904.fix2"


class _GitRunner(FakeRunner):
    def __init__(self, commit: str, dirty: bool, ignored: bool = False) -> None:
        super().__init__()
        self.commit = commit
        self.dirty = dirty
        self.ignored = ignored

    def __call__(self, cmd: Sequence[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
        items = list(cmd)
        self.calls.append(items)
        if "rev-parse" in items:
            return completed_stdout(self.commit + "\n")
        if "--ignored" not in items:
            raise AssertionError("status must include --ignored")
        if "--untracked-files=all" not in items:
            raise AssertionError("status must include --untracked-files=all")
        if self.dirty or self.ignored:
            return completed_stdout("!! ignored.so\n" if self.ignored else "M file\n")
        return completed_stdout("")


def test_pin_accepts_both_branch_aliases(tmp_path: Path) -> None:
    pin_path = make_pin_file(tmp_path)
    assert validation.read_and_check_pin(pin_path)["OPENRAZER_BRANCH"] == "naga-v3-pro-compat"
    text = pin_path.read_text(encoding="ascii").replace("naga-v3-pro-compat", "test-pr-2904-edualb")
    pin_path.write_text(text, encoding="ascii")
    assert validation.read_and_check_pin(pin_path)["OPENRAZER_BRANCH"] == "test-pr-2904-edualb"


def test_pin_rejects_wrong_cohort(tmp_path: Path) -> None:
    pin_path = make_pin_file(tmp_path)
    bad = pin_path.read_text(encoding="ascii").replace(COMMIT, "0" * 40)
    pin_path.write_text(bad, encoding="ascii")
    with pytest.raises(ValueError, match="commit"):
        validation.read_and_check_pin(pin_path)


def test_family_and_root_guards() -> None:
    with pytest.raises(ValueError, match="Unsupported family"):
        validation.check_family("arch")
    with pytest.raises(ValueError, match="root"):
        validation.check_not_root(0)
    validation.check_not_root(1000)


def test_verify_source_rejects_ignored_and_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    with pytest.raises(ValueError, match="commit"):
        validation.verify_source(source, PIN, _GitRunner("0" * 40, False))
    with pytest.raises(ValueError, match="dirty"):
        validation.verify_source(source, PIN, _GitRunner(COMMIT, True))
    with pytest.raises(ValueError, match="dirty"):
        validation.verify_source(source, PIN, _GitRunner(COMMIT, False, ignored=True))
    link = tmp_path / "linksrc"
    try:
        link.symlink_to(source)
    except OSError:
        return
    with pytest.raises(ValueError, match=r"symlink|real directory"):
        validation.verify_source(link, PIN, _GitRunner(COMMIT, False))


def test_verify_source_rejects_unsafe_tree(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "evil").symlink_to("/etc/passwd")
    with pytest.raises(ValueError, match="symlink"):
        validation.check_source_tree_safe(source)


def test_verify_output_dir_guards(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    output = tmp_path / "out"
    output.mkdir()
    owner = output.stat().st_uid
    validation.verify_output_dir(output, source, owner)
    (output / "unexpected.deb").write_text("x", encoding="ascii")
    with pytest.raises(ValueError, match="empty"):
        validation.verify_output_dir(output, source, owner)


def test_verify_output_dir_rejects_group_writable_ancestor(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    ancestor = tmp_path / "ancestor"
    ancestor.mkdir()
    output = ancestor / "out"
    output.mkdir()
    owner = output.stat().st_uid
    os.chmod(ancestor, 0o775)
    try:
        with pytest.raises(ValueError, match=r"ancestor|permissions|writable"):
            validation.verify_output_dir(output, source, owner)
    finally:
        os.chmod(ancestor, 0o755)


def test_verify_output_dir_rejects_other_writable_output(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    output = tmp_path / "out"
    output.mkdir()
    owner = output.stat().st_uid
    os.chmod(output, 0o777)
    try:
        with pytest.raises(ValueError, match="writable"):
            validation.verify_output_dir(output, source, owner)
    finally:
        os.chmod(output, 0o755)


def test_verify_output_dir_rejects_root_group_writable_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    output = tmp_path / "out"
    output.mkdir()
    owner = output.stat().st_uid
    real_stat = Path.stat
    real_tmp_uid = tmp_path.stat().st_uid
    real_tmp_mode = stat.S_IMODE(tmp_path.stat().st_mode)

    class _Stat:
        def __init__(self, wrapped: os.stat_result, mode: int, uid: int) -> None:
            self._wrapped = wrapped
            self.st_mode = mode
            self.st_uid = uid

        def __getattr__(self, name: str) -> object:
            return getattr(self._wrapped, name)

    def _fake_stat(  # type: ignore[return]
        self: Path, *, follow_symlinks: bool = True
    ) -> os.stat_result:
        result = real_stat(self, follow_symlinks=follow_symlinks)
        if self == tmp_path:
            mode = (result.st_mode & ~0o777) | 0o775
            return _Stat(result, mode, 0)  # type: ignore[return-value]
        return result  # type: ignore[return-value]

    monkeypatch.setattr(Path, "stat", _fake_stat)
    with pytest.raises(ValueError, match=r"ancestor|permissions|writable"):
        validation.verify_output_dir(output, source, owner)
    # Regression for Python 3.12 pathlib, which calls Path.stat with an
    # explicit follow_symlinks keyword (Path.lstat and Path.exists both
    # delegate to stat). Without the keyword the fake raises TypeError and
    # pytest failure formatting crashes with INTERNALERROR, hiding the
    # real result. Exercise both spellings so Python 3.14 catches it too.
    for faked in (
        tmp_path.stat(),
        tmp_path.stat(follow_symlinks=True),
        tmp_path.stat(follow_symlinks=False),
    ):
        assert faked.st_uid == 0
        assert stat.S_IMODE(faked.st_mode) & 0o020 != 0
    # Untargeted paths must delegate with either spelling.
    assert output.stat(follow_symlinks=True).st_uid == owner
    assert output.stat(follow_symlinks=False).st_uid == owner
    assert source.stat(follow_symlinks=False).st_uid == owner
    # The global Path.stat patch must not leak past this test.
    monkeypatch.undo()
    assert Path.stat is real_stat
    assert tmp_path.stat().st_uid == real_tmp_uid
    assert stat.S_IMODE(tmp_path.stat().st_mode) == real_tmp_mode
    assert tmp_path.stat(follow_symlinks=False).st_uid == real_tmp_uid


def test_audit_payload_stages_valid_and_modes(tmp_path: Path) -> None:
    old_umask = os.umask(0o077)
    try:
        stages = make_valid_stages(tmp_path, "debian", MINOR, PIN)
    finally:
        os.umask(old_umask)
    validation.audit_payload_stages(stages, "debian", PIN, MINOR)
    bad_stamp = (
        stages["openrazer-driver-dkms-local"]
        / "usr/share/doc/openrazer-driver-dkms-local/source-commit"
    )
    bad_stamp.write_text("bad\n", encoding="ascii")
    with pytest.raises(ValueError, match="stamp"):
        validation.audit_payload_stages(stages, "debian", PIN, MINOR)


def test_audit_payload_rejects_plugdev_and_xdg(tmp_path: Path) -> None:
    stages = make_valid_stages(tmp_path, "debian", MINOR, PIN)
    rule = stages["openrazer-driver-dkms-local"] / "usr/lib/udev/rules.d/99-razer.rules"
    rule.write_text('GROUP="plugdev"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="group"):
        validation.audit_payload_stages(stages, "debian", PIN, MINOR)


def test_audit_scripts_reject_forbidden() -> None:
    good = recipes.deb_postinst("openrazer-driver-dkms-local", PKGVER)
    validation.audit_script_text("openrazer-driver-dkms-local", good, PKGVER)
    for fragment in ("modprobe x", "udevadm trigger", "systemctl start x"):
        bad = (
            "#!/bin/sh\nset -e\ngetent group openrazer >/dev/null || groupadd -r openrazer\n"
            + fragment
            + "\n"
        )
        with pytest.raises(ValueError, match="forbidden"):
            validation.audit_script_text("openrazer-driver-dkms-local", bad, PKGVER)


def test_deb_root_entry_allowed_once() -> None:
    role = "openrazer-daemon-local"
    members = archive_audit.audit_member_listing(
        deb_listing_lines(role), role, "debian", MINOR, False
    )
    assert f"usr/share/doc/{role}/source-commit" in members
    root_only = ["drwxr-xr-x root/root         0 2026-01-01 00:00 ./"]
    with pytest.raises(ValueError, match="stamp"):
        archive_audit.audit_member_listing(root_only, role, "debian", MINOR, False)
    file_root = ["-rw-r--r-- root/root        41 2026-01-01 00:00 ./"]
    with pytest.raises(ValueError, match=r"root|Unsafe"):
        archive_audit.audit_member_listing(file_root, role, "debian", MINOR, False)


def test_member_listing_rejects_etc_and_special() -> None:
    role = "openrazer-daemon-local"
    evil = ["-rw-r--r-- root/root        41 2026-01-01 00:00 ./etc/evil"]
    with pytest.raises(ValueError, match="/usr"):
        archive_audit.audit_member_listing(evil, role, "debian", MINOR, False)
    block = ["brw-r--r-- root/root         0 2026-01-01 00:00 ./usr/share/block"]
    with pytest.raises(ValueError, match="special"):
        archive_audit.audit_member_listing(block, role, "debian", MINOR, False)
    suid = ["-rwsr-xr-x root/root         0 2026-01-01 00:00 ./usr/bin/evil"]
    with pytest.raises(ValueError, match="setuid"):
        archive_audit.audit_member_listing(suid, role, "debian", MINOR, False)


def test_cpio_parses_entire_payload_with_odd_entry() -> None:
    role = "openrazer-daemon-local"
    parsed = rpm_audit.cpio_parse_all(make_cpio_bytes(role, COMMIT))
    assert parsed[f"usr/share/doc/{role}/source-commit"] == (COMMIT + "\n").encode("ascii")
    assert parsed["a"] == b"xyy"


def test_deb_tar_listing_fileset_must_match() -> None:
    role = "openrazer-daemon-local"
    listing_files = archive_audit.audit_member_listing(
        deb_listing_lines(role), role, "debian", MINOR, False
    )
    tar_files = archive_audit.parse_deb_data_tar(make_tar_bytes(role, COMMIT), role, COMMIT, PKGVER)
    assert listing_files == tar_files
