# Naga Control

Naga Control is a native Linux control service and Qt application for the
Razer Naga V3 Pro. It is intentionally limited to the wired `1532:00E7` and
HyperSpeed `1532:00E8` variants.

**This is a personal off-project.** It exists to support one specific mouse
on the maintainer's desktop, built as a best effort alongside other work.
There is no support commitment, no roadmap, and no guarantee of timely
fixes — issues and PRs are welcome but may sit. It works well for the
hardware and distro it was validated on (see
[hardware validation](docs/hardware-validation.md)); anywhere else you are
your own QA.

The goal is one coherent application for hardware settings and button
remapping, backed by OpenRazer, evdev, and uinput. It is not a generic Razer
frontend and it does not reimplement OpenRazer's HID protocol.

## Install

Requires a Linux desktop, OpenRazer with the Naga V3 Pro baseline (see
[release notes](docs/release-notes.md)), and `curl`. Standard install:

```bash
curl -fsSL https://raw.githubusercontent.com/Rainexn0b/naga-control/main/install.sh -o install.sh && bash install.sh
```

Pinned release:

```bash
curl -fsSL https://raw.githubusercontent.com/Rainexn0b/naga-control/main/install.sh -o install.sh && bash install.sh --version v0.1.0
```

Uninstall:

```bash
curl -fsSL https://raw.githubusercontent.com/Rainexn0b/naga-control/main/uninstall.sh -o uninstall.sh && bash uninstall.sh --yes --purge-config
```

This installs the AppImage to `~/.local/bin`, the systemd user unit,
D-Bus activation, the desktop entry, and (with sudo) the udev rule, then
enables the service at login. Removal: `scripts/uninstall.sh --yes
--purge-config`.

## Status

The repository has hardware-independent coverage for read-only capture, strict
profile configuration, OpenRazer control, physical USB-parent discovery,
ordered frame parsing, proxy-before-grab activation, forwarding clones,
replacement outputs, session D-Bus, and the native Qt configuration UI. The
12-button first slice has passed on both wired and HyperSpeed hardware for
F13/F14 DPI stage changes and held F17-to-LEFTALT output. All 19 12-button
controls are captured and remapped on both transports — including verified
top buttons (`KPSLASH`/`F18`), scan-less wheel tilt, and the full thumb grid —
plus the 6- and 2-button plates on HyperSpeed. Motion, clicks, and
high-resolution wheel are validated through the forwarding proxies, and the
2-button plate validates virtual-mouse back/forward output. HyperSpeed daemon
restart, sleep/wake, receiver reconnect, disconnect-while-held cleanup, and a
live wired-to-HyperSpeed switch have also passed. The service now applies
desired DPI stages, scroll settings, power settings, poll rate, and all three
lighting zones to the hardware with per-setting failure reporting, and the
snapshot publishes observed DPI, scroll, poll-rate, battery, charging, and
firmware values for the GUI overview, the buttons page selects the side-plate
layout (12/6/2) with revision-checked apply, and a calibration mode rebuilds
forwarding as pure passthrough and adopts the observed DPI stages and scroll
settings into the active profile on end. Broader passthrough and wired
alternate-plate capture remain.

Naga V3 Pro support is intentionally developed against a compatible custom
OpenRazer build while
[PR #2904](https://github.com/openrazer/openrazer/pull/2904) remains unmerged.
This is a project prerequisite, not a development blocker. See
[integration findings](docs/integration-findings.md) for the tested baselines,
required capabilities, and known wireless behavior. Release notes pin the
exact tested OpenRazer revision in [release notes](docs/release-notes.md);
see also [troubleshooting](docs/troubleshooting.md).

## Design

- A `systemd --user` service owns device discovery, profiles, remapping, and
  OpenRazer access.
- A PySide6 GUI is a client of that service and may be closed without stopping
  mappings.
- OpenRazer remains the only hardware-control backend.
- evdev reads physical controls and uinput emits remapped events.
- Only event nodes belonging to `1532:00E7` or `1532:00E8` are considered.
- Wired and HyperSpeed must not be connected simultaneously because both
  transports currently collide on the same OpenRazer D-Bus identity.
- The service fails open: it releases evdev grabs if safe forwarding cannot be
  guaranteed.

The detailed design is in [architecture](docs/architecture.md). The staged
delivery plan is in [implementation plan](docs/implementation-plan.md).

## Prerequisites

- Linux with uinput enabled
- Python 3.12 or newer
- Qt 6 and PySide6
- OpenRazer kernel module, daemon, and Python client from a build that supports
  both target product IDs
- Membership in the group required by the OpenRazer package
- Read access to the Naga event nodes and write access to `/dev/uinput`

`openrazer.client` is a system integration dependency and is deliberately not
declared as a PyPI dependency. The OpenRazer kernel module, daemon, and client
must come from the same compatible build.

## Development

On distributions that install OpenRazer and PySide6 into the system Python,
create the virtual environment with access to system packages:

```bash
python -m venv --system-site-packages .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Run the baseline checks with:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pyright
.venv/bin/pytest
```

Hardware tests must be opt-in and must never run as part of the default test
suite. Read [hardware validation](docs/hardware-validation.md) before capturing
or grabbing real input devices.

The Milestone 0 diagnostic can list matching physical event nodes or record a
short, read-only capture without grabbing them:

```bash
naga-control-capture --list
naga-control-capture --duration 60 --plate 12 \
  --output hardware-captures/wireless-12-button.json
```

Only connect one Naga transport during capture. Serial numbers and physical USB
paths are redacted unless `--include-identifiers` is explicitly supplied. Run
the command as the desktop user, never with `sudo`.

## User Service

The first-slice service entry point is `naga-control-service`. Packaging must
install `packaging/systemd/user/naga-control.service` under the user systemd
unit directory and `packaging/dbus-1/services/org.nagacontrol.Service1.service`
under the session D-Bus service directory. Enable the user unit after installing
the scoped udev rule; neither the service nor the GUI should run as root.

## AppImage

Build the self-contained AppImage (bundled CPython, PySide6, and Python
dependencies; OpenRazer stays on the host):

```bash
bash packaging/appimage/build-appimage.sh   # writes dist/Naga-Control-<version>-x86_64.AppImage
```

Usage:

```bash
./Naga-Control-*.AppImage                 # GUI (default)
./Naga-Control-*.AppImage service         # D-Bus remapping service
./Naga-Control-*.AppImage capture         # hardware capture CLI
./Naga-Control-*.AppImage --install       # install udev rule (sudo), user unit,
                                          # D-Bus activation, desktop entry;
                                          # unit/D-Bus Exec point back into the AppImage
./Naga-Control-*.AppImage --uninstall     # remove all integration files
./Naga-Control-*.AppImage integration status
```

`--install` asks for sudo only for `/etc/udev/rules.d/70-naga-control.rules`;
the systemd user unit, D-Bus activation file, and desktop entry install under
`~/.config` and `~/.local/share`. After installing, run
`systemctl --user daemon-reload && systemctl --user enable --now naga-control`.

## Repository Guide

- `docs/naga-linux-control-agent-starter.md`: product goal and scope
- `docs/integration-findings.md`: verified OpenRazer and Linux input facts
- `docs/architecture.md`: selected v0.1 architecture and invariants
- `docs/implementation-plan.md`: milestones and acceptance criteria
- `docs/hardware-validation.md`: completed evidence and outstanding hardware tests
- `packaging/udev/70-naga-control.rules`: least-scope device access rules
- `src/naga_control/`: application package
- `tests/`: non-hardware test suite

## License

Naga Control is licensed under the [MIT License](LICENSE) and is provided
without warranty. Reference implementations may be studied for behavior, but
no Polychromatic or Input Remapper source is copied into this project.
