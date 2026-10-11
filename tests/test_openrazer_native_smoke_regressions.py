"""Smoke regressions for actual Ubuntu/SUSE failures plus inode cleanup."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from buildpython.openrazer_native import build, recipes, rpm_audit
from buildpython.openrazer_native.validation import audit_script_text

VERSION = "3.12.1.pr2904.fix2-1"
PKGVER = "3.12.1.pr2904.fix2"
MINOR = "3.10"
SUSE_MINOR = "3.13"


def test_debian_control_dir_modes_under_umask077(tmp_path: Path) -> None:
    old_umask = os.umask(0o077)
    try:
        for role in recipes.LOCAL_ROLES:
            stage = tmp_path / f"stage-{role}"
            stage.mkdir()
            build._write_debian_package_dir(  # pyright: ignore[reportPrivateUsage]
                stage, role, VERSION, MINOR
            )
    finally:
        os.umask(old_umask)
    for role in recipes.LOCAL_ROLES:
        debian_dir = tmp_path / f"stage-{role}" / "DEBIAN"
        assert stat.S_IMODE(debian_dir.stat().st_mode) == 0o755
        control_path = debian_dir / "control"
        assert stat.S_IMODE(control_path.stat().st_mode) == 0o644
        for script in ("postinst", "prerm"):
            assert stat.S_IMODE((debian_dir / script).stat().st_mode) == 0o755
        control_text = control_path.read_text(encoding="ascii")
        recipes.audit_deb_control(control_text, role, VERSION, MINOR)
        for script in ("postinst", "prerm"):
            audit_script_text(role, (debian_dir / script).read_text(encoding="ascii"), PKGVER)


def test_rpm_provides_hyphen_canonical_and_fail_closed() -> None:
    daemon_actual = {
        "openrazer-daemon",
        f"openrazer-daemon-local = {VERSION}",
        "python3.13dist(openrazer-daemon) = 3.12.1",
        "python3dist(openrazer-daemon) = 3.12.1",
    }
    rpm_audit.check_provides(
        daemon_actual, "openrazer-daemon-local", "opensuse", SUSE_MINOR, VERSION
    )
    client_actual = {
        f"python-openrazer-local = {VERSION}",
        "python3-openrazer",
        "python3.13dist(openrazer) = 3.12.1",
        "python3dist(openrazer) = 3.12.1",
    }
    rpm_audit.check_provides(
        client_actual, "python-openrazer-local", "opensuse", SUSE_MINOR, VERSION
    )
    assert (
        rpm_audit.egg_info_dir("openrazer_daemon", SUSE_MINOR)
        == "openrazer_daemon-3.12.1-py3.13.egg-info"
    )
    underscore = {
        "openrazer-daemon",
        f"openrazer-daemon-local = {VERSION}",
        "python3.13dist(openrazer_daemon) = 3.12.1",
        "python3dist(openrazer_daemon) = 3.12.1",
    }
    with pytest.raises(ValueError, match="Provides"):
        rpm_audit.check_provides(
            underscore, "openrazer-daemon-local", "opensuse", SUSE_MINOR, VERSION
        )
    foreign_minor = {
        "openrazer-daemon",
        f"openrazer-daemon-local = {VERSION}",
        "python3.11dist(openrazer-daemon) = 3.12.1",
        "python3dist(openrazer-daemon) = 3.12.1",
    }
    with pytest.raises(ValueError, match="Provides"):
        rpm_audit.check_provides(
            foreign_minor, "openrazer-daemon-local", "opensuse", SUSE_MINOR, VERSION
        )
    wrong_version = {
        "openrazer-daemon",
        f"openrazer-daemon-local = {VERSION}",
        "python3.13dist(openrazer-daemon) = 9.9.9",
        "python3dist(openrazer-daemon) = 3.12.1",
    }
    with pytest.raises(ValueError, match="Provides"):
        rpm_audit.check_provides(
            wrong_version, "openrazer-daemon-local", "opensuse", SUSE_MINOR, VERSION
        )
    wrong_role = {
        "openrazer-daemon",
        f"openrazer-daemon-local = {VERSION}",
        "python3.13dist(openrazer) = 3.12.1",
        "python3dist(openrazer) = 3.12.1",
    }
    with pytest.raises(ValueError, match="Provides"):
        rpm_audit.check_provides(
            wrong_role, "openrazer-daemon-local", "opensuse", SUSE_MINOR, VERSION
        )
    arbitrary = daemon_actual | {"evil-provides = 1"}
    with pytest.raises(ValueError, match="Provides"):
        rpm_audit.check_provides(
            arbitrary, "openrazer-daemon-local", "opensuse", SUSE_MINOR, VERSION
        )


def test_publish_write_failure_removes_own_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out"
    output.mkdir()
    target = output / "native-build.json"
    created: list[Path] = []

    class _Failing:
        def __init__(self, fd: int) -> None:
            self._fd = fd

        def __enter__(self) -> _Failing:
            return self

        def __exit__(self, *exc: object) -> bool:
            os.close(self._fd)
            return False

        def write(self, data: bytes) -> int:
            raise OSError("injected write failure")

    def _failing_fdopen(fd: int, mode: str) -> _Failing:
        return _Failing(fd)

    monkeypatch.setattr(os, "fdopen", _failing_fdopen)
    with pytest.raises(OSError, match="injected write failure"):
        build._publish_bytes(target, b"partial", created)  # pyright: ignore[reportPrivateUsage]
    assert not target.exists()
    assert created == []


def test_publish_write_failure_keeps_foreign_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out"
    output.mkdir()
    target = output / "native-build.json"
    created: list[Path] = []

    class _Replacing:
        def __init__(self, fd: int) -> None:
            self._fd = fd

        def __enter__(self) -> _Replacing:
            return self

        def __exit__(self, *exc: object) -> bool:
            os.close(self._fd)
            return False

        def write(self, data: bytes) -> int:
            os.unlink(target)
            wfd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            try:
                os.write(wfd, b"foreign\n")
            finally:
                os.close(wfd)
            raise OSError("injected failure after replacement")

    def _replacing_fdopen(fd: int, mode: str) -> _Replacing:
        return _Replacing(fd)

    monkeypatch.setattr(os, "fdopen", _replacing_fdopen)
    with pytest.raises(OSError, match="injected failure after replacement"):
        build._publish_bytes(target, b"partial", created)  # pyright: ignore[reportPrivateUsage]
    assert target.read_text(encoding="ascii") == "foreign\n"
    assert created == []
