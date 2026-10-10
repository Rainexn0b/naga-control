"""App installer state/fixtures on the closed-PATH installer harness."""

import hashlib
from pathlib import Path

from tests.openrazer_installer_fakes import InstallerHarness, harness, stage_app_installer

ASSET = "Naga-Control-x86_64.AppImage"
HELPER_OK = '#!/usr/bin/env bash\nexec installer-helper "$@" 9>&-\n'
PREVIOUS_TAG = "v0.3.0"
USER_FILES = (
    ".local/bin/naga-control",
    ".config/systemd/user/naga-control.service",
    ".local/share/dbus-1/services/org.nagacontrol.Service1.service",
    ".local/share/applications/org.nagacontrol.NagaControl.desktop",
    *(
        f".local/share/icons/hicolor/{size}x{size}/apps/org.nagacontrol.NagaControl.png"
        for size in (64, 128, 256, 512)
    ),
)


def app_harness(tmp_path: Path, *, helper: str | None = None) -> tuple[InstallerHarness, Path]:
    fake = harness(tmp_path)
    return fake, stage_app_installer(fake, helper=helper)


def mutations(commands: list[list[str]]) -> list[list[str]]:
    return [
        command
        for command in commands
        if command[0] in {"sudo", "naga-control.AppImage", ASSET}
        or (command[0] == "systemctl" and command[2] != "show")
    ]


def installed_image(fake: InstallerHarness) -> Path:
    return fake.root / "home/.local/bin/naga-control.AppImage"


def stamp(fake: InstallerHarness) -> Path:
    return fake.root / "home/.local/share/naga-control/installed-tag"


def seed_previous(fake: InstallerHarness, *, tag: str = PREVIOUS_TAG, active: bool = True) -> bytes:
    # The remote fixture supplies this previous tag's digest; the new fixture
    # deliberately differs. No real image is ever executed.
    old = fake.remote.joinpath(ASSET).read_bytes()
    image = installed_image(fake)
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(old)
    image.chmod(0o755)
    stamp(fake).parent.mkdir(parents=True, exist_ok=True)
    stamp(fake).write_text(tag + "\n")
    for relative in USER_FILES:
        target = fake.root / "home" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("previous integration\n")
    fake.remote.joinpath(ASSET).write_bytes(old + b"\n# updated fixture\n")
    # URL-specific previous checksums are handled by the curl fake.
    fake.configure(previous_tag=tag, previous_digest=hashlib.sha256(old).hexdigest())
    fake.remote.joinpath(ASSET + ".sha256").write_text(
        hashlib.sha256(fake.remote.joinpath(ASSET).read_bytes()).hexdigest() + "  " + ASSET + "\n"
    )
    fake.configure(service_state="active" if active else "inactive", unit_state="enabled")
    return old


def assert_private_cleanup(fake: InstallerHarness) -> None:
    assert not list((fake.root / "temporary").iterdir())
    assert not list((fake.root / "home").rglob(".naga-install.*"))
    assert not list((fake.root / "home").rglob(".rollback.*"))
    assert not list((fake.root / "home").rglob(".quarantine.*"))


def quarantines(fake: InstallerHarness) -> list[Path]:
    parent = stamp(fake).parent
    return sorted(parent.glob("quarantine.*")) if parent.is_dir() else []


def rollbacks(fake: InstallerHarness) -> list[Path]:
    parent = stamp(fake).parent
    return sorted(parent.glob("rollback.*")) if parent.is_dir() else []


def seed_altered_previous(
    fake: InstallerHarness, *, tag: str = PREVIOUS_TAG, active: bool = True
) -> tuple[bytes, bytes]:
    old = seed_previous(fake, tag=tag, active=active)
    altered = old + b"\n# locally rebuilt\n"
    installed_image(fake).write_bytes(altered)
    return old, altered
