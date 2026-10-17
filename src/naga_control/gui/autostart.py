"""Owned XDG autostart entry for tray login startup (file is truth)."""

import contextlib
import os
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from naga_control.gui.desktop_exec import (
    escape_value,
    file_value_to_argv,
    format_exec_line,
    unescape_value,
)

AUTOSTART_FILENAME = "org.nagacontrol.NagaControl.desktop"
OWNED_KEY = "X-NagaControl-Owned"
OWNED_VALUE = "true"
APP_NAME = "Naga Control"
APP_ICON = "org.nagacontrol.NagaControl"
_DESKTOP_GROUP = "[Desktop Entry]"

LauncherProbe = Callable[[], tuple[list[str] | None, str | None]]


@dataclass(frozen=True)
class AutostartStatus:
    enabled: bool
    error: str | None
    path: Path
    exec_line: str | None = None


def default_autostart_path() -> Path:
    return autostart_path_for(config_home=os.environ.get("XDG_CONFIG_HOME"), home=Path.home())


def autostart_path_for(*, config_home: str | None, home: Path) -> Path:
    if config_home:
        candidate = Path(config_home)
        if candidate.is_absolute():
            return candidate / "autostart" / AUTOSTART_FILENAME
    return home / ".config" / "autostart" / AUTOSTART_FILENAME


def resolve_launch_argv(
    *, appimage: str | None, appdir: str | None, executable: str
) -> tuple[list[str] | None, str | None]:
    if appimage:
        cand = Path(appimage)
        if not cand.is_absolute():
            return None, "Portable launcher path is not absolute. Launch from the AppImage file."
        try:
            ok = cand.is_file()
        except OSError:
            ok = False
        if not ok:
            if appdir:
                return None, "Portable launcher unavailable (APPDIR without valid APPIMAGE)."
            return (
                None,
                "Application image is no longer available. Re-enable from the new location.",
            )
        return [str(cand), "gui", "--start-hidden"], None
    if appdir:
        return None, "Portable launcher unavailable (APPDIR without APPIMAGE)."
    if not executable or "\0" in executable or "\n" in executable or "\r" in executable:
        return None, "Launch path is invalid; startup entry was not updated."
    exe = Path(executable)
    if not exe.is_absolute():
        exe = Path.cwd() / exe
    return [str(exe), "-m", "naga_control.gui.app", "--start-hidden"], None


def current_launch_argv() -> tuple[list[str] | None, str | None]:
    return resolve_launch_argv(
        appimage=os.environ.get("APPIMAGE"),
        appdir=os.environ.get("APPDIR"),
        executable=sys.executable,
    )


def render_entry(exec_single: str) -> str:
    stored = escape_value(exec_single)
    return (
        "\n".join(
            [
                _DESKTOP_GROUP,
                "Type=Application",
                f"Name={APP_NAME}",
                f"Icon={APP_ICON}",
                f"Exec={stored}",
                "Hidden=false",
                f"{OWNED_KEY}={OWNED_VALUE}",
            ]
        )
        + "\n"
    )


def parse_entry(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    in_group = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            in_group = line == _DESKTOP_GROUP
            continue
        if in_group and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def _kind(path: Path) -> str:
    try:
        if path.is_symlink():
            return "conflict"
        if path.is_dir():
            return "conflict"
        if path.is_file():
            return "file"
        if not path.exists():
            return "missing"
    except OSError:
        return "conflict"
    return "conflict"


def _read_owned(path: Path) -> tuple[dict[str, str] | None, str | None]:
    try:
        return parse_entry(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError):
        return None, "Could not read the startup entry."


def read_status(
    path: Path, *, current_exec: str | None, check_target: bool = True
) -> AutostartStatus:
    kind = _kind(path)
    if kind == "missing":
        return AutostartStatus(enabled=False, error=None, path=path)
    if kind == "conflict":
        try:
            if path.is_symlink():
                return AutostartStatus(
                    enabled=False,
                    error="Startup entry is a symlink; not changed. Remove it manually.",
                    path=path,
                )
            if path.is_dir():
                return AutostartStatus(
                    enabled=False,
                    error="Startup entry is a directory; not changed. Remove it manually.",
                    path=path,
                )
        except OSError:
            pass
        return AutostartStatus(
            enabled=False,
            error="Startup entry is blocked by an unmanaged file; not changed.",
            path=path,
        )
    values, err = _read_owned(path)
    if values is None:
        return AutostartStatus(enabled=False, error=err, path=path)
    if values.get(OWNED_KEY) != OWNED_VALUE:
        return AutostartStatus(
            enabled=False,
            error="Startup entry belongs to another app; not changed.",
            path=path,
            exec_line=values.get("Exec"),
        )
    if (values.get("Hidden") or "false").strip().lower() == "true":
        return AutostartStatus(
            enabled=False,
            error="Startup entry is disabled (Hidden=true). Re-enable.",
            path=path,
            exec_line=values.get("Exec"),
        )
    stored_raw = values.get("Exec")
    if not stored_raw:
        return AutostartStatus(
            enabled=False, error="Startup entry has no command. Re-enable.", path=path
        )
    decoded = unescape_value(stored_raw)
    if decoded is None:
        return AutostartStatus(
            enabled=False,
            error="Startup entry has invalid escaping. Re-enable.",
            path=path,
            exec_line=stored_raw,
        )
    if current_exec is not None and decoded != current_exec:
        return AutostartStatus(
            enabled=False,
            error="Startup entry points elsewhere. Re-enable.",
            path=path,
            exec_line=stored_raw,
        )
    if check_target:
        argv = file_value_to_argv(stored_raw)
        if argv is None or not argv:
            return AutostartStatus(
                enabled=False,
                error="Startup entry has an invalid command. Re-enable.",
                path=path,
                exec_line=stored_raw,
            )
        token = argv[0]
        if token and Path(token).is_absolute():
            try:
                exists = Path(token).is_file()
            except OSError:
                exists = False
            if not exists:
                return AutostartStatus(
                    enabled=False,
                    error="Startup launcher is missing. Re-enable.",
                    path=path,
                    exec_line=stored_raw,
                )
    return AutostartStatus(enabled=True, error=None, path=path, exec_line=stored_raw)


def enable_entry(path: Path, *, exec_line: str) -> AutostartStatus:
    single = exec_line
    if _kind(path) == "conflict":
        truth = read_status(path, current_exec=single, check_target=False)
        if truth.error is None:
            return AutostartStatus(
                enabled=truth.enabled,
                error="Startup entry is blocked; not changed.",
                path=path,
                exec_line=truth.exec_line,
            )
        return truth
    if _kind(path) == "file":
        values, err = _read_owned(path)
        if values is None:
            return AutostartStatus(enabled=False, error=err, path=path)
        if values.get(OWNED_KEY) != OWNED_VALUE:
            return AutostartStatus(
                enabled=False,
                error="Startup entry belongs to another app; not changed.",
                path=path,
                exec_line=values.get("Exec"),
            )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        truth = read_status(path, current_exec=single, check_target=False)
        return AutostartStatus(
            enabled=truth.enabled,
            error="Could not update the startup entry.",
            path=path,
            exec_line=truth.exec_line,
        )
    tmp: Path | None = None
    replaced = False
    try:
        fd, name = tempfile.mkstemp(prefix=".naga-autostart.", suffix=".tmp", dir=str(path.parent))
        tmp = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(render_entry(single))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        replaced = True
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
    except OSError:
        if tmp is not None and not replaced:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
        truth = read_status(path, current_exec=single, check_target=False)
        return AutostartStatus(
            enabled=truth.enabled,
            error="Could not update the startup entry.",
            path=path,
            exec_line=truth.exec_line,
        )
    stored_raw = escape_value(single)
    try:
        dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return AutostartStatus(
            enabled=True,
            error="Startup entry updated but durability unknown; check status.",
            path=path,
            exec_line=stored_raw,
        )
    try:
        os.fsync(dfd)
    except OSError:
        return AutostartStatus(
            enabled=True,
            error="Startup entry updated but durability unknown; check status.",
            path=path,
            exec_line=stored_raw,
        )
    finally:
        with contextlib.suppress(OSError):
            os.close(dfd)
    return read_status(path, current_exec=single, check_target=False)


def disable_entry(path: Path) -> AutostartStatus:
    if _kind(path) == "missing":
        return AutostartStatus(enabled=False, error=None, path=path)
    if _kind(path) == "conflict":
        return read_status(path, current_exec=None, check_target=False)
    values, err = _read_owned(path)
    if values is None:
        return AutostartStatus(enabled=False, error=err, path=path)
    if values.get(OWNED_KEY) != OWNED_VALUE:
        return AutostartStatus(
            enabled=False,
            error="Startup entry belongs to another app; not changed.",
            path=path,
            exec_line=values.get("Exec"),
        )
    prev_exec = values.get("Exec")
    try:
        path.unlink()
    except OSError:
        truth = read_status(path, current_exec=None, check_target=False)
        if truth.enabled:
            return AutostartStatus(
                enabled=True,
                error="Could not remove the startup entry.",
                path=path,
                exec_line=truth.exec_line or prev_exec,
            )
        if truth.exec_line is None and prev_exec is not None:
            return AutostartStatus(
                enabled=True,
                error="Could not remove the startup entry (state unknown).",
                path=path,
                exec_line=prev_exec,
            )
        return AutostartStatus(
            enabled=truth.enabled,
            error="Could not remove the startup entry.",
            path=path,
            exec_line=truth.exec_line,
        )
    return AutostartStatus(enabled=False, error=None, path=path)


class AutostartStore:
    """Blocking host operations; the panel calls these via to_thread."""

    def __init__(self, path: Path | None = None, *, launcher: LauncherProbe | None = None) -> None:
        self._path = path if path is not None else default_autostart_path()
        self._launcher = launcher if launcher is not None else current_launch_argv

    @property
    def path(self) -> Path:
        return self._path

    def current_exec_line(self) -> tuple[str | None, str | None]:
        argv, error = self._launcher()
        if argv is None:
            return None, error
        try:
            return format_exec_line(argv), None
        except ValueError:
            return None, "Launch path is invalid; startup entry was not updated."

    def load(self) -> AutostartStatus:
        exec_single, _ = self.current_exec_line()
        return read_status(self._path, current_exec=exec_single)

    def apply(self, enabled: bool) -> AutostartStatus:
        if not enabled:
            return disable_entry(self._path)
        exec_single, error = self.current_exec_line()
        if exec_single is None:
            truth = read_status(self._path, current_exec=None, check_target=True)
            return AutostartStatus(
                enabled=truth.enabled,
                error=error or "Startup update failed.",
                path=self._path,
                exec_line=truth.exec_line,
            )
        return enable_entry(self._path, exec_line=exec_single)
