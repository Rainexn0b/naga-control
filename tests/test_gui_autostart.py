"""Autostart file truth: enable/disable, ownership, quoting, launchers."""

import os
import stat
from pathlib import Path

import pytest

from naga_control.gui import autostart as az
from naga_control.gui import desktop_exec as dx
from tests.gui_application_fakes import make_store, tmp_autostart_path

VENV_ARGV = ["/tmp/venv space/bin/python", "-m", "naga_control.gui.app", "--start-hidden"]


def _venv_store(tmp_path: Path) -> az.AutostartStore:
    return make_store(tmp_path, VENV_ARGV)


def test_default_off_without_file(tmp_path: Path) -> None:
    store = _venv_store(tmp_path)
    status = store.load()
    assert status.enabled is False
    assert status.error is None
    assert not store.path.exists()


def test_enable_creates_owned_entry(tmp_path: Path) -> None:
    store = _venv_store(tmp_path)
    status = store.apply(True)
    assert status.enabled is True
    assert status.error is None
    text = store.path.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in text
    assert "Type=Application" in text
    assert "Name=Naga Control" in text
    assert "Icon=org.nagacontrol.NagaControl" in text
    assert "X-NagaControl-Owned=true" in text
    assert "Hidden=false" in text
    assert "--start-hidden" in text
    mode = stat.S_IMODE(os.stat(store.path).st_mode)
    assert mode in (0o600, 0o644)
    leftovers = list(store.path.parent.glob("*.tmp")) + list(store.path.parent.glob(".*.tmp"))
    assert leftovers == []


def test_disable_removes_only_owned(tmp_path: Path) -> None:
    store = _venv_store(tmp_path)
    assert store.apply(True).enabled is True
    status = store.apply(False)
    assert status.enabled is False
    assert status.error is None
    assert not store.path.exists()


def test_disable_missing_is_clean(tmp_path: Path) -> None:
    store = _venv_store(tmp_path)
    status = store.apply(False)
    assert status.enabled is False
    assert status.error is None


def test_symlink_is_preserved(tmp_path: Path) -> None:
    store = _venv_store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "real.desktop"
    target.write_text("[Desktop Entry]\n", encoding="utf-8")
    store.path.symlink_to(target)
    enabled = store.apply(True)
    assert enabled.enabled is False
    assert "symlink" in (enabled.error or "").lower()
    assert store.path.is_symlink()
    disabled = store.apply(False)
    assert disabled.enabled is False
    assert store.path.is_symlink()


def test_foreign_entry_is_preserved(tmp_path: Path) -> None:
    store = _venv_store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        "[Desktop Entry]\nType=Application\nExec=/usr/bin/other\n", encoding="utf-8"
    )
    enabled = store.apply(True)
    assert enabled.enabled is False
    assert "another" in (enabled.error or "").lower()
    assert store.path.read_text(encoding="utf-8").count("other") == 1
    disabled = store.apply(False)
    assert disabled.enabled is False
    assert store.path.is_file()


def test_directory_conflict_is_preserved(tmp_path: Path) -> None:
    store = _venv_store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.mkdir()
    status = store.apply(True)
    assert status.enabled is False
    assert status.error is not None
    assert store.path.is_dir()


def test_hidden_true_means_disabled(tmp_path: Path) -> None:
    store = _venv_store(tmp_path)
    assert store.apply(True).enabled is True
    text = store.path.read_text(encoding="utf-8").replace("Hidden=false", "Hidden=true")
    store.path.write_text(text, encoding="utf-8")
    status = store.load()
    assert status.enabled is False
    assert "hidden" in (status.error or "").lower()


def test_moved_entry_needs_reenable(tmp_path: Path) -> None:
    first = make_store(tmp_path, ["/opt/a/python", "-m", "naga_control.gui.app", "--start-hidden"])
    assert first.apply(True).enabled is True
    second = az.AutostartStore(
        first.path,
        launcher=lambda: (["/opt/b/python", "-m", "naga_control.gui.app", "--start-hidden"], None),
    )
    status = second.load()
    assert status.enabled is False
    assert (
        "different" in (status.error or "").lower() or "elsewhere" in (status.error or "").lower()
    )


def test_missing_target_invalidates(tmp_path: Path) -> None:
    missing = str(tmp_path / "gone" / "python")
    store = make_store(tmp_path, [missing, "-m", "naga_control.gui.app", "--start-hidden"])
    assert store.apply(True).enabled is True
    assert not Path(missing).exists()
    assert store.load().enabled is False


def test_appimage_command_is_stable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "Naga Control.AppImage"
    image.write_bytes(b"x")
    argv, error = az.resolve_launch_argv(
        appimage=str(image), appdir=None, executable="/usr/bin/python3"
    )
    assert error is None
    assert argv == [str(image), "gui", "--start-hidden"]
    store = make_store(tmp_path, argv)
    assert store.apply(True).enabled is True
    text = store.path.read_text(encoding="utf-8")
    assert "gui" in text and "--start-hidden" in text
    assert "APPDIR" not in text and "python3" not in text.split("Exec=")[1].split("\n")[0][:40]


def test_appdir_without_appimage_refuses(tmp_path: Path) -> None:
    argv, error = az.resolve_launch_argv(
        appimage=None, appdir="/tmp/.mount_ABC123", executable="/usr/bin/python3"
    )
    assert argv is None
    assert error is not None and "APPIMAGE" in error
    store = az.AutostartStore(tmp_autostart_path(tmp_path), launcher=lambda: (None, error))
    status = store.apply(True)
    assert status.enabled is False
    assert status.error is not None
    assert not store.path.exists()


def test_venv_preserves_symlink_identity() -> None:
    argv, error = az.resolve_launch_argv(
        appimage=None, appdir=None, executable="/tmp/venv/bin/python"
    )
    assert error is None
    assert argv == ["/tmp/venv/bin/python", "-m", "naga_control.gui.app", "--start-hidden"]


def test_desktop_exec_quoting() -> None:
    line = dx.format_exec_line(["/opt/My App/run", "--start-hidden"])
    assert line.startswith('"/opt/My App/run"')
    quoted = dx.format_exec_line(["/bin/x", 'a"b\\c$d`e%f'])
    assert (
        '\\"' in quoted
        and "\\\\" in quoted
        and "\\$" in quoted
        and "\\`" in quoted
        and "%%" in quoted
    )
    pct = dx.format_exec_line(["/bin/x", "100%"])
    assert "%%" in pct
    assert dx.format_exec_line(["/bin/x", "a b"]) == '/bin/x "a b"'


def test_reject_nul_and_newline() -> None:
    with pytest.raises(ValueError):
        dx.format_exec_line(["/bin/x", "a\0b"])
    with pytest.raises(ValueError):
        dx.format_exec_line(["/bin/x", "a\nb"])
    argv, error = az.resolve_launch_argv(appimage=None, appdir=None, executable="/bin/x\0y")
    assert argv is None and error is not None


def test_xdg_path_selection(tmp_path: Path) -> None:
    home = tmp_path / "home"
    custom = tmp_path / "xdg"
    assert (
        az.autostart_path_for(config_home=str(custom), home=home)
        == custom / "autostart" / az.AUTOSTART_FILENAME
    )
    assert (
        az.autostart_path_for(config_home="relative/path", home=home)
        == home / ".config" / "autostart" / az.AUTOSTART_FILENAME
    )
    assert (
        az.autostart_path_for(config_home=None, home=home)
        == home / ".config" / "autostart" / az.AUTOSTART_FILENAME
    )


def test_launch_failure_does_not_claim_enabled(tmp_path: Path) -> None:
    store = az.AutostartStore(
        tmp_autostart_path(tmp_path), launcher=lambda: (None, "Portable launcher unavailable.")
    )
    status = store.apply(True)
    assert status.enabled is False
    assert status.error is not None
    assert not store.path.exists()
