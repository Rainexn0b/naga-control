"""Session fence groups + restore-begins-fenced (fake only)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from tests.installer_app_fakes import (
    ASSET,
    app_harness,
    assert_private_cleanup,
    installed_image,
    stamp,
)
from tests.openrazer_installer_fakes import TAG, InstallerHarness

ACTIVATION = ".local/share/dbus-1/services/org.nagacontrol.Service1.service"
MARKER = ".local/share/naga-control/service-manager"
HELPER = ".local/share/naga-control/session-service.sh"


def _autostart(fake: InstallerHarness) -> Path:
    return fake.root / "home/.config/autostart/org.nagacontrol.Service.desktop"


def _seed_session(fake: InstallerHarness, *, autostart: str | None = None) -> bytes:
    old: bytes = fake.remote.joinpath(ASSET).read_bytes()
    image: Path = installed_image(fake)
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(old)
    image.chmod(0o755)
    stamp(fake).parent.mkdir(parents=True, exist_ok=True)
    stamp(fake).write_text("v0.3.0\n")
    marker: Path = fake.root / "home" / MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("session\n")
    marker.chmod(0o600)
    helper_src: Path = fake.root / "checkout/scripts/session_service.sh"
    helper_dst: Path = fake.root / "home" / HELPER
    helper_dst.parent.mkdir(parents=True, exist_ok=True)
    helper_dst.write_bytes(helper_src.read_bytes())
    helper_dst.chmod(0o700)
    activation: Path = fake.root / "home" / ACTIVATION
    activation.parent.mkdir(parents=True, exist_ok=True)
    activation.write_text(
        "[D-BUS Service]\nName=org.nagacontrol.Service1\nExec=" + str(image) + " service\n"
    )
    auto: Path = _autostart(fake)
    auto.parent.mkdir(parents=True, exist_ok=True)
    if autostart is None:
        autostart = (
            "[Desktop Entry]\nType=Application\nName=Naga Control background service\nExec="
            + str(image)
            + " service\nHidden=false\nX-NagaControl-Service=true\n"
        )
    auto.write_text(autostart)
    fake.remote.joinpath(ASSET).write_bytes(old + b"\n# updated fixture\n")
    fake.configure(previous_tag="v0.3.0", previous_digest=hashlib.sha256(old).hexdigest())
    fake.remote.joinpath(ASSET + ".sha256").write_text(
        hashlib.sha256(fake.remote.joinpath(ASSET).read_bytes()).hexdigest() + "  " + ASSET + "\n"
    )
    fake.configure(has_owner=True, bus_available=True)
    fake.configure(service_state="inactive", unit_state="")
    return old


def _section(text: str, header: str) -> str:
    lines = text.splitlines(keepends=False)
    active: str | None = None
    collected: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            active = stripped
            continue
        if active == header:
            collected.append(line)
    return "\n".join(collected)


def test_group_aware_hide_preserves_action_group(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    image_hint = str(installed_image(fake))
    original = (
        "[Desktop Entry]\nType=Application\nName=Naga Control background service\nExec="
        + image_hint
        + " service\nHidden=false\nX-NagaControl-Service=true\n"
        + "StartupNotify=false\n"
        + "[Desktop Action Foo]\nName=Foo\nExec=/bin/false\nHidden=false\n"
    )
    _seed_session(fake, autostart=original)
    fake.configure(prepare_fail=True)
    result, _ = fake.run(
        "--version", TAG, "--service-manager", "session", "--restart-service", script=script
    )
    assert result.returncode != 0
    live: str = _autostart(fake).read_text()
    entry = _section(live, "[Desktop Entry]")
    action = _section(live, "[Desktop Action Foo]")
    assert "Hidden=true" in entry
    assert "Hidden=false" not in entry
    assert "X-NagaControl-Service=true" in entry
    assert "StartupNotify=false" in entry
    assert "Hidden=false" in action
    assert "Hidden=true" not in action
    assert "Exec=/bin/false" in action
    recoveries = sorted((fake.root / "home/.local/share/naga-control").glob("session-recovery.*"))
    assert len(recoveries) == 1
    assert (recoveries[0] / "autostart.desktop").read_text() == original
    assert "operator recovery snapshot retained" in result.stderr
    assert_private_cleanup(fake)


def test_restore_begins_fenced_at_old_image_replace(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    previous = _seed_session(fake)
    orig_activation = (fake.root / "home" / ACTIVATION).read_text()
    orig_autostart = _autostart(fake).read_text()
    real_mv = shutil.which("mv")
    assert real_mv is not None
    target = fake.root / "bin/mv"
    if target.is_symlink() or target.is_file():
        target.unlink()
    observer = fake.root / "mv-observer.log"
    observer.write_text("")
    target.write_text(
        "#!/bin/bash\n"
        f'REAL="{real_mv}"\n'
        f'OBS="{observer}"\n'
        f'HOME_DIR="{fake.root / "home"}"\n'
        'last="${@: -1}"\n'
        'case "$last" in\n'
        "  *naga-control.AppImage)\n"
        '    act="$HOME_DIR/.local/share/dbus-1/services/org.nagacontrol.Service1.service"\n'
        '    auto="$HOME_DIR/.config/autostart/org.nagacontrol.Service.desktop"\n'
        "    blocker=no; hidden=no\n"
        '    if grep -qF "Exec=/bin/false" "$act" 2>/dev/null; then blocker=yes; fi\n'
        '    if grep -qx "Hidden=true" "$auto" 2>/dev/null || grep -q "^Hidden=true$" "$auto" 2>/dev/null; then hidden=yes; fi\n'
        '    printf "appimage blocker=%s hidden=%s\\n" "$blocker" "$hidden" >> "$OBS"\n'
        "    ;;\n"
        "esac\n"
        'exec "$REAL" "$@"\n'
    )
    target.chmod(0o755)
    fake.configure(start_fail_once=True)
    result, _ = fake.run(
        "--version", TAG, "--service-manager", "session", "--restart-service", script=script
    )
    assert result.returncode != 0
    assert "start failed" in result.stderr
    assert installed_image(fake).read_bytes() == previous
    assert (fake.root / "home" / ACTIVATION).read_text() == orig_activation
    assert _autostart(fake).read_text() == orig_autostart
    lines = observer.read_text().splitlines()
    assert lines, "mv observer saw no AppImage replacement"
    assert any("blocker=yes" in line and "hidden=yes" in line for line in lines)
    assert_private_cleanup(fake)


def test_failed_entry_fence_blocks_restore_and_resume(tmp_path: Path) -> None:
    fake, script = app_harness(tmp_path)
    previous = _seed_session(fake)
    new_bytes = fake.remote.joinpath(ASSET).read_bytes()
    assert new_bytes != previous
    dbus_path = fake.root / "bin/dbus-send"
    real_dbus = fake.root / "bin/dbus-send.real"
    dbus_path.rename(real_dbus)
    counter = fake.root / "reload-count"
    counter.write_text("0\n")
    dbus_path.write_text(
        "#!/bin/bash\n"
        f'REAL="{real_dbus}"\n'
        f'COUNT="{counter}"\n'
        "is_reload=0\n"
        'for arg in "$@"; do\n'
        '  if [ "$arg" = "org.freedesktop.DBus.ReloadConfig" ]; then is_reload=1; fi\n'
        "done\n"
        'if [ "$is_reload" -eq 1 ]; then\n'
        '  n=$(cat "$COUNT" 2>/dev/null || echo 0)\n'
        "  n=$((n + 1))\n"
        '  printf "%s\\n" "$n" > "$COUNT"\n'
        '  if [ "$n" -eq 3 ]; then\n'
        '    echo "Error org.freedesktop.DBus.Error.Failed: injected restore fence reload" >&2\n'
        "    exit 1\n"
        "  fi\n"
        "fi\n"
        'exec "$REAL" "$@"\n'
    )
    dbus_path.chmod(0o755)
    fake.configure(start_fail_once=True)
    result, _ = fake.run(
        "--version", TAG, "--service-manager", "session", "--restart-service", script=script
    )
    assert result.returncode != 0
    assert "RESTORATION FAILED" in result.stderr
    assert "fence" in result.stderr.lower()
    assert installed_image(fake).read_bytes() != previous
    assert "Exec=/bin/false" in (fake.root / "home" / ACTIVATION).read_text()
    recoveries = sorted((fake.root / "home/.local/share/naga-control").glob("session-recovery.*"))
    assert len(recoveries) == 1
    assert "operator recovery snapshot retained" in result.stderr
    assert_private_cleanup(fake)
