# Non-systemd desktop sessions

Candidate v0.5.2 source feature only, pending portable artifact and attended
validation. No live Devuan install or hardware certification is claimed. It
needs a matching new build/release; older published AppImages (for example
v0.5.1) lack the session integration and lifecycle API. A new installer must
fail clearly against an old binary rather than pretend the feature is present.

See [installation](installation.md#service-manager-selection),
[architecture](architecture.md),
[desktop startup controls](desktop-startup-controls.md), and
[troubleshooting](troubleshooting.md#session-mode).

## Service manager selection

The managed shell installer owns one flag:

```text
--service-manager auto|systemd|session   (default: auto)
```

- On a FRESH install, `auto` prefers a usable user systemd manager and
  otherwise uses `session` when a live session D-Bus is available.
  Executable `systemctl` or shim presence alone is not enough.
- A persisted mode wins over `auto` on later runs.
- A legacy existing image or unit with a missing mode file means
  `systemd`; the installer does not silently migrate it.
- An explicit mode change across a known install is refused with a
  manual-migration message.
- Existing systemd stop/restart behavior, `KillMode=mixed` handling,
  and rollback handling are unchanged.

The core service CLI is already init-independent and has NO new
`--service-manager` flag. The flag is installer/integration only.
Raw AppImage integration accepts `systemd|session` (default
`systemd`); AppImage `service` and `gui` commands are unchanged.

## What session mode is

- An unprivileged logged-in desktop process, started at login
  independently of the GUI.
- Started by direct session D-Bus activation `Exec` plus a distinct
  service XDG login entry:

```text
org.nagacontrol.Service.desktop   (X-NagaControl-Service=true)
```

- No systemd user unit is used in session mode.
- The existing GUI tray checkbox entry
  `org.nagacontrol.NagaControl.desktop` stays optional, off by
  default, and unchanged. Closing the GUI does not stop mappings.
- There is NO root SysV init or system-boot service.
- There is no full init-framework, supervisor, or crash-restart
  guarantee in session mode. A later GUI or bus call can reactivate
  the service; the login entry starts it at the next login.

## Requirements

- A live SESSION D-Bus shared with the GUI and OpenRazer (a system
  bus alone is not enough). Use the existing desktop-provided
  `DBUS_SESSION_BUS_ADDRESS`; the session helper fails closed before
  `dbus-send` when the address is unset or empty, or when any autolaunch
  fallback would apply. Autolaunch would start a private bus through
  libdbus, so no private bus is fabricated as a workaround.
- Linux x86_64 and FUSE2 requirements are unchanged.
- Scoped evdev/uinput permissions under a compatible session
  seat/access provider. For example, an elogind/uaccess setup must
  be verified on Devuan; installing a systemctl shim does not provide
  seat ACLs.
- No root GUI/service, no broad `input` group or chmod, no raw HID.
- Only `1532:00E7` and `1532:00E8`, one transport at a time.

A compatible custom OpenRazer kernel module, daemon, and client are
still required manually on Devuan/session mode. There is no
automatic backend offer in session mode; an explicit backend opt-in
fails with manual guidance. Native helper distro eligibility,
`ID_LIKE` handling, and published-package certification are
unchanged and not expanded here.

## Owned files and controls

Installer-owned, private, canonical paths:

```text
~/.local/share/naga-control/service-manager
~/.local/share/naga-control/session-service.sh
```

- `service-manager` contains exactly `systemd` plus newline or
  `session` plus newline.
- The session helper is shipped from source/tag/bootstrap, not from
  the AppImage binary.
- From source, a manual user runs the service in the foreground and
  uses the checked-out helper after direct activation is configured:

```bash
bash scripts/session_service.sh status
bash scripts/session_service.sh start
bash scripts/session_service.sh stop
bash scripts/session_service.sh restart
```

- Installed helper controls:

```bash
bash ~/.local/share/naga-control/session-service.sh status
bash ~/.local/share/naga-control/session-service.sh start
bash ~/.local/share/naga-control/session-service.sh stop
bash ~/.local/share/naga-control/session-service.sh restart
```

`status` is a read that does not activate the service. `start`
reports ownership, not hardware readiness. Profile TOML is unchanged.

The GUI restart control branches on the canonical mode file:

- legacy/systemd: fixed `systemctl --user restart naga-control.service`
- canonical session: fixed bash helper `restart`

A malformed mode file or a missing helper is reported with no
fallback to the other manager.

## Safe lifecycle API

Two no-argument, no-result methods are added to the SAME interface
and path:

```text
bus:       org.nagacontrol.Service1
path:      /org/nagacontrol/Service1
interface: org.nagacontrol.Service1
methods:   PrepareShutdown, Exit
```

The existing seven application methods are unchanged:

```text
GetSnapshot, GetConfiguration, ApplyConfiguration, SelectProfile,
BeginCalibration, EndCalibration, ReleaseAll
```

- `PrepareShutdown` closes the application gate and joins the
  one-owned cached cleanup (watcher, auxiliary, service). It returns
  a clean ACK ONLY after success WHILE still owning the bus name and
  staying connected.
- On failure it answers with fixed `Unavailable`; `Exit` is then not
  permitted. There is no retry and no false cleanup claim.
- `Exit` is allowed only after a successful `PrepareShutdown`. It
  asks the CLI to exit. The reply may be lost because the process is
  exiting; the helper checks that both the unique name and the
  well-known name are gone. No PID guessing or signalling is used.
- Broker loss after an initialized run triggers the same cleanup
  path.

## Install, update, and removal fence

Install/update/removal fences direct D-Bus activation with a
temporary owned blocker and `ReloadConfig` before a clean stop and
verified replace/delete.

- Active upgrades still need consent/`--restart-service`, a quit GUI,
  and released controls.
- Checksum verification before execute/sudo, atomic image inode
  handling, and lock/symlink guards are retained.
- Failed or uncertain cleanup retains files, backups, and the fence
  for operator recovery. Never delete the fence or restart blindly.
- A session `udev-pending` state does not start the service now;
  install success is not physical readiness.
- Profiles are preserved unless purged. The GUI-owned and service-owned
  autostart entries are handled separately; both owned entries are removed
  on uninstall.
- Session removal needs only generic coreutils plus `mktemp`/`mv` and
  `dbus-send`/`sleep` in its branch; it runs no `systemctl`, `busctl`,
  Python, or image execution. It backs up the original activation file
  and the owned service autostart entry to private unique state files
  (`.session-uninstall.activation.SUFFIX` and
  `.session-uninstall.autostart.SUFFIX`), atomically blocks activation
  plus `Hidden=true` before `PrepareShutdown`, keeps backups and fences
  on uncertain failure, removes assets then runs a final `ReloadConfig`
  before removing mode/helper state, and deletes only the current
  invocation backups on success; older unknown recovery copies are
  preserved. Logged paths support manual operator recovery; there is no
  blind restore and no executable control.
- Trusted persistent rollback v1 stays the strict original 4 files
  (image, tag, hash, marker) for BOTH modes. Transaction metadata and
  operator recovery copies are separate and are not part of the v1
  trusted schema or a migration.
- Session metadata meeting an unexpected user unit refuses with
  manual-migration guidance in both install and remove; nothing is
  silently deleted.

XDG config root must be absolute, else `~/.config` is used; only
safe paths are accepted. The session installer may reject external
`HOME` roots rather than weaken path ownership. Broad external-path
support is not promised.

Raw AppImage integration (`--install --service-manager session`)
supports the mode but does not install manager/helper metadata; the
managed shell installer owns that metadata. The GUI restart does not
auto-detect an unmanaged source checkout.

## Attended Devuan handoff (all PENDING, not passed)

Default tests use fakes with no real devices and never touch the host user
session bus. No unattended real service/GUI test is authorized. A practical
attended check, once a matching build and backend exist, covers:

1. Matching OpenRazer backend works.
2. Seat ACLs are ready for evdev/uinput.
3. The login service runs independently of the GUI.
4. The GUI connects and its restart control works.
5. A clean stop releases held outputs.
6. Safe upgrade and removal work.
7. Reboot/relogin behavior is checked.

Record results in hardware validation when actually observed. Until attended
validation and artifact checks complete, this feature stays candidate-only,
unreleased and uncertified; publication remains pending the final gate.
