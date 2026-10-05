"""Explicit artwork and host-integration payload for the Naga AppDir."""

from pathlib import Path
from shutil import copy2

APP_ID = "org.nagacontrol.NagaControl"
ICON_SIZES = (64, 128, 256, 512)
SYSTEM_TEMPLATES = (
    f"desktop/{APP_ID}.desktop",
    "udev/70-naga-control.rules",
    "systemd/user/naga-control.service",
    "dbus-1/services/org.nagacontrol.Service1.service",
)


def copy_assets(*, root: Path, appdir: Path) -> Path:
    """Return the integration source directory, with sibling assets as in checkout."""
    payload = appdir / "usr/share/naga-control"
    copies = [(root / "system" / name, payload / "system" / name) for name in SYSTEM_TEMPLATES]
    for size in ICON_SIZES:
        name = f"icons/hicolor/{size}x{size}/apps/{APP_ID}.png"
        copies.extend(
            (
                (root / "assets" / name, payload / "assets" / name),
                (root / "assets" / name, appdir / "usr/share" / name),
            )
        )
    icon = root / f"assets/icons/hicolor/256x256/apps/{APP_ID}.png"
    copies.extend(
        (
            (icon, appdir / ".DirIcon"),
            (icon, appdir / f"{APP_ID}.png"),
            (root / f"assets/{APP_ID}.svg", appdir / f"{APP_ID}.svg"),
            (root / f"system/desktop/{APP_ID}.desktop", appdir / f"{APP_ID}.desktop"),
            (root / "buildpython/steps/appimage/AppRun", appdir / "AppRun"),
        )
    )
    for source, target in copies:
        target.parent.mkdir(parents=True, exist_ok=True)
        copy2(source, target)
    apprun = appdir / "AppRun"
    apprun.chmod(apprun.stat().st_mode | 0o111)
    return payload / "system"
