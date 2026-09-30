"""Install or remove host integration files for AppImage and source runs."""

import argparse
import contextlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

SYSTEMD_UNIT = "naga-control.service"
UDEV_RULE = "70-naga-control.rules"
DBUS_SERVICE = "org.nagacontrol.Service1.service"
DESKTOP_ENTRY = "org.nagacontrol.NagaControl.desktop"
ICON_SIZES = (64, 128, 256, 512)


@dataclass(frozen=True)
class IntegrationFile:
    """One host file copied from the packaged integration directory."""

    name: str
    relative_source: str
    user_path: str
    system_path: str
    rewrite_command: str = ""


INTEGRATION_FILES: tuple[IntegrationFile, ...] = (
    IntegrationFile(
        name="systemd user unit",
        relative_source=f"systemd/user/{SYSTEMD_UNIT}",
        user_path=f".config/systemd/user/{SYSTEMD_UNIT}",
        system_path="",
        rewrite_command="service",
    ),
    IntegrationFile(
        name="D-Bus session service",
        relative_source=f"dbus-1/services/{DBUS_SERVICE}",
        user_path=f".local/share/dbus-1/services/{DBUS_SERVICE}",
        system_path="",
        rewrite_command="service",
    ),
    IntegrationFile(
        name="desktop entry",
        relative_source=f"appimage/{DESKTOP_ENTRY}",
        user_path=f".local/share/applications/{DESKTOP_ENTRY}",
        system_path="",
        rewrite_command="gui",
    ),
    *(
        IntegrationFile(
            name=f"application icon {size}x{size}",
            relative_source=(
                f"appimage/icons/hicolor/{size}x{size}/apps/org.nagacontrol.NagaControl.png"
            ),
            user_path=(
                f".local/share/icons/hicolor/{size}x{size}/apps/org.nagacontrol.NagaControl.png"
            ),
            system_path="",
            rewrite_command="",
        )
        for size in ICON_SIZES
    ),
    IntegrationFile(
        name="udev rule",
        relative_source=f"udev/{UDEV_RULE}",
        user_path="",
        system_path=f"/etc/udev/rules.d/{UDEV_RULE}",
        rewrite_command="",
    ),
)


class IntegrationError(RuntimeError):
    """An integration file could not be installed or removed."""


def install(
    source_dir: Path,
    *,
    home: Path,
    udev_dir: Path | None = None,
    exec_prefix: Path | None = None,
) -> list[str]:
    """Copy every integration file, rewriting Exec lines when bundled."""
    installed: list[str] = []
    for item in INTEGRATION_FILES:
        source = source_dir / item.relative_source
        if not source.is_file():
            raise IntegrationError(f"missing integration source {source}")
        target = _target(item, home=home, udev_dir=udev_dir)
        if target is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.relative_source.endswith(".png"):
            shutil.copyfile(source, target)
        else:
            content = _render(source.read_text(encoding="utf-8"), exec_prefix, item)
            target.write_text(content, encoding="utf-8")
        target.chmod(0o644)
        _open_icon_dirs(target)
        installed.append(str(target))
    return installed


def _open_icon_dirs(target: Path) -> None:
    """Icon theme directories are shared; they must be world-readable."""
    icons_dir = target.parent
    while icons_dir.name != "icons" and icons_dir != icons_dir.parent:
        with contextlib.suppress(OSError):
            icons_dir.chmod(0o755)
        icons_dir = icons_dir.parent


def remove(*, home: Path, udev_dir: Path | None = None) -> list[str]:
    """Delete every installed integration file that exists."""
    removed: list[str] = []
    for item in INTEGRATION_FILES:
        target = _target(item, home=home, udev_dir=udev_dir)
        if target is not None and target.exists():
            with contextlib.suppress(OSError):
                target.unlink()
            removed.append(str(target))
    return removed


def status(*, home: Path, udev_dir: Path | None = None) -> list[tuple[str, bool]]:
    """Report whether each integration file is present."""
    report: list[tuple[str, bool]] = []
    for item in INTEGRATION_FILES:
        target = _target(item, home=home, udev_dir=udev_dir)
        report.append((item.name, target is not None and target.exists()))
    return report


def _target(item: IntegrationFile, *, home: Path, udev_dir: Path | None) -> Path | None:
    if item.user_path:
        return home / item.user_path
    if udev_dir is not None:
        return udev_dir / UDEV_RULE
    return None


def _render(content: str, exec_prefix: Path | None, item: IntegrationFile) -> str:
    command = item.rewrite_command
    if exec_prefix is None or not command:
        return content
    lines: list[str] = []
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("ExecStart="):
            line = f"ExecStart={exec_prefix} {command}\n"
        elif stripped.startswith("Exec="):
            line = f"Exec={exec_prefix} {command}\n"
        lines.append(line)
    return "".join(lines)


def _require_writable_udev(udev_dir: Path) -> None:
    probe = udev_dir / ".naga-control-write-probe"
    try:
        udev_dir.mkdir(parents=True, exist_ok=True)
        probe.write_text("", encoding="utf-8")
    except OSError as exc:
        raise IntegrationError(
            f"cannot write to {udev_dir}; rerun with sudo or pass --udev-dir for testing"
        ) from exc
    finally:
        with contextlib.suppress(OSError):
            probe.unlink()


def default_source_dir() -> Path:
    """Return the integration directory for AppImage or source checkouts."""
    appdir = os.environ.get("APPDIR")
    if appdir:
        return Path(appdir) / "usr/share/naga-control/packaging"
    repo_packaging = Path(__file__).resolve().parents[2] / "packaging"
    if repo_packaging.is_dir():
        return repo_packaging
    return Path(__file__).resolve().parent.parent / "integration"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="naga-control-integration")
    parser.add_argument("command", choices=["install", "remove", "status"])
    parser.add_argument("--source-dir", type=Path, default=None)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--udev-dir", type=Path, default=Path("/etc/udev/rules.d"))
    parser.add_argument(
        "--exec-prefix",
        type=Path,
        default=None,
        help="AppImage path whose 'service' command runs the daemon",
    )
    args = parser.parse_args(argv)

    source = args.source_dir or default_source_dir()
    udev_dir = args.udev_dir if args.udev_dir else None
    try:
        if args.command == "install":
            _require_writable_udev(args.udev_dir)
            for path in install(
                source, home=args.home, udev_dir=udev_dir, exec_prefix=args.exec_prefix
            ):
                print(f"installed {path}")
        elif args.command == "remove":
            for path in remove(home=args.home, udev_dir=udev_dir):
                print(f"removed {path}")
        else:
            for name, present in status(home=args.home, udev_dir=udev_dir):
                print(f"{'installed' if present else 'missing ':9s} {name}")
    except IntegrationError as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
