# Naga Control

Naga Control is a native Linux control service and Qt application for the
Razer Naga V3 Pro. It is intentionally limited to the wired `1532:00E7` and
HyperSpeed `1532:00E8` variants.

**This is a personal off-project.** It exists to support one specific mouse
on the maintainer's desktop, built as a best effort alongside other work.
There is no support commitment, no roadmap, and no guarantee of timely
fixes - issues and PRs are welcome but may sit. It works well for the
hardware and distro it was validated on (see
[hardware validation](docs/hardware-validation.md)); anywhere else you are
your own QA.

The goal is one coherent application for hardware settings and button
remapping, backed by OpenRazer, evdev, and uinput. It is not a generic Razer
frontend and it does not reimplement OpenRazer's HID protocol.

## Install

Requires an unprivileged Linux x86_64 desktop session, user systemd/session
D-Bus, FUSE2 library/runtime support, `curl`, `sudo`, and the standard tools
listed under [installer prerequisites](docs/troubleshooting.md#installer-prerequisites).
OpenRazer must already provide the [Naga baseline](docs/release-notes.md).
No missing OS prerequisites are automatically installed.
Managed service/desktop integration always requires FUSE; leave
`APPIMAGE_EXTRACT_AND_RUN` unset (or `0`). Extraction is manual launch-only,
not a supported FUSEless managed installation.

### Install and update

```bash
curl -fsSL https://raw.githubusercontent.com/Rainexn0b/naga-control/main/install.sh -o install.sh && bash install.sh
```

Download to a file and then run it: the installer needs the terminal for
confirmations, so do not pipe it into bash. Rerun the same command to
update. `main` is mutable, so this is not a reproducibly pinned install; it
does not install unreleased source. With no `--version`, the installer
resolves the latest **published** release via `/releases/latest` and
installs only the fixed `Naga-Control-x86_64.AppImage` plus its `.sha256`
sidecar. The dispatcher accepts `--ref <git-ref>`; the app installer accepts
`--version <tag>`, `--install-openrazer`, and `--restart-service`.

For a reproducible install, first download the outer bootstrap from the same
published tag, then pin both the bootstrap and the artifact: `curl -fsSL
https://raw.githubusercontent.com/Rainexn0b/naga-control/<tag>/install.sh -o
install.sh && bash install.sh --ref <tag> --version <tag>`. Running only
`bash install.sh --ref <tag> --version <tag>` on a file downloaded from `main`
is not a pinned bootstrap. From a
checkout, run `./install.sh` (same latest-published default).

Upgrades rerun the same command with the existing stop consent. By default
the current `main` installer replaces a mismatched local image with the
strictly verified new image: an unverified old image is held as a
private quarantine under `~/.local/share/naga-control/quarantine.*` until
a successful install, then removed with other owned quarantines,
while a verified old image keeps a `rollback.*` pair. After a successful
install only the newest verified rollback is kept; older verified pairs
and all owned quarantines are removed. Only a failed
replacement with an unverified previous image leaves Naga stopped and
disabled for manual repair; verified rollback and resume behavior is
unchanged. Failed installs preserve recovery files; unsafe or unknown
operator files are never automatically removed. A failure quarantine
survives uninstall for manual cleanup. See
[upgrades and recovery](docs/troubleshooting.md#installer-upgrades-and-rollback).

Notes:

- The installer creates `~/.local/bin/naga-control.AppImage` and
  `~/.local/bin/naga-control`, plus the user unit, D-Bus activation entry,
  desktop entry, and icons. Ordinary app-only use asks `sudo` only for the
  udev rule. The exact release's canonical `.sha256` sidecar and AppImage
  bytes are verified before execution, replacement, or `sudo`.
- Quit the GUI and release held controls before consenting to the temporary
  remapping outage. `--restart-service` only consents to a graceful
  Naga-only stop and resume; it does not make the install fully
  noninteractive or sudo-free.
- App-only success enables and starts the user service, which is not
  hardware readiness: replug the target mouse after the udev reload, then
  verify with this read-only snapshot (it can D-Bus-activate the service;
  the installer only prints it):

  ```bash
  busctl --user call org.nagacontrol.Service1 /org/nagacontrol/Service1 org.nagacontrol.Service1 GetSnapshot
  ```

  Require `status` = `available` and perform physical F13/F14 DPI-stage and
  F17 held-ALT down/up checks. These are not automatically established by
  installation.
- The ordinary install is **app-only**: it never offers, downloads,
  installs, or replaces OpenRazer. Explicit opt-in is an advanced topic,
  see below.

### Run

After a successful install, start the panel from your app menu or from a
terminal:

```bash
~/.local/bin/naga-control
```

`naga-control` alone works when `~/.local/bin` is in `PATH`.

<details><summary><b>Advanced install topics</b></summary>

OpenRazer opt-in is for experimental Arch/pacman hosts only: append
`--install-openrazer` to the same bash command, or set
`NAGA_CONTROL_INSTALL_OPENRAZER=1`. `NAGA_CONTROL_INSTALL_OPENRAZER=0` is a
hard skip even with the flag; any other value is an error. Activation is
deferred: units are enabled without starting them, so reboot or re-login
and verify OpenRazer first. Read [required
OpenRazer](docs/release-notes.md#required-openrazer) before opting in, and
never fetch and execute the Arch helper directly.

Manual FUSE2 library references (verified 2026-10-08; you run these yourself,
the installer never installs packages):

| Release | Package (repository) | Manual command | Reference |
| --- | --- | --- | --- |
| Ubuntu 22.04 | `libfuse2` (universe) | `sudo apt install libfuse2` | https://packages.ubuntu.com/jammy/libfuse2 |
| Ubuntu 24.04 | `libfuse2t64` (universe) | `sudo apt install libfuse2t64` | https://packages.ubuntu.com/noble/libfuse2t64 |
| Arch (rolling) | `fuse2` (extra) | `sudo pacman -S fuse2` | https://archlinux.org/packages/extra/x86_64/fuse2/ |
| Fedora 44 | `fuse-libs` | `sudo dnf install fuse-libs` | https://packages.fedoraproject.org/pkgs/fuse/fuse-libs/fedora-44.html |

Only these four package references are verified; they are package names, not
a claim of complete prerequisites, AppImage launch, install, or hardware
support. The Fedora 44 package provides `libfuse.so.2()(64bit)` as version
`2.9.9-25.fc44` on x86_64. Arch is rolling, so no snapshot validation is
claimed. Enable `universe` manually if your Ubuntu setup needs it; the
installer never configures repositories. Other releases and derivatives need
their official native package context for the exact release; release branding
or `ID_LIKE` alone never selects a package. Debian 13 and openSUSE names are
deliberately not listed here.

The installer separately requires the actual capabilities at install time: an
x86_64 `libfuse.so.2` in the `ldconfig` cache, a usable `/dev/fuse`
character device, kernel FUSE support, and a normal user systemd/session
D-Bus desktop session. FUSE 3 alone does not satisfy the FUSE 2 library
check, and installing the library alone does not guarantee `/dev/fuse` works.

The approved portable build target is Ubuntu 22.04 (glibc 2.35) on x86_64.
Canonical `4f14ed3` passed the controlled build plus finished-artifact static
gate (208 objects, providers checked, no missing-provider errors) and Ubuntu
22.04 baseline plus 24.04 userspace smoke checks; see the [portability
tracker](docs/distro-portability-plan.md) and validation run `38050625832`.
Scope is bundled runtime imports, offscreen QApplication, CLI `--help`, and
temporary integration payload only; no full install, upgrade, remove, FUSE,
user units, D-Bus, sudo, udev, desktop, service, or hardware certification is
claimed. See [GitHub releases](https://github.com/Rainexn0b/naga-control/releases)
for current publication status. With no `--version`, the installer resolves
the latest published release and never installs unreleased `main` source.

The installer verifies the exact release's canonical `.sha256` sidecar and
AppImage bytes before execution, replacement, service stop, or sudo, using
private temporary staging, same-filesystem atomic replacement, and a stable
per-user lock. At most one verified rollback pair is retained under
`~/.local/share/naga-control/rollback.*`: a successful install keeps only
the newest verified pair and removes owned quarantines and older pairs,
while failed installs preserve recovery files and unsafe or unknown files
are left for manual inspection. See [upgrades and
recovery](docs/troubleshooting.md#installer-upgrades-and-rollback).

</details>

### Uninstall

Checkout-free removal of a standalone install (needs no AppImage and no host
Python). It removes installer-owned app and user integration files:

```bash
curl -fsSL https://raw.githubusercontent.com/Rainexn0b/naga-control/main/uninstall.sh -o uninstall.sh && bash uninstall.sh
```

From a checkout:

```bash
./uninstall.sh --yes
```

Notes:

- Quit the GUI and release held controls first. Removal prompts before udev
  rule deletion, which needs `sudo`.
- `--yes` only skips that udev-removal confirmation; `sudo` authentication is
  still required and all ownership and service checks remain.
- Profiles stay unless `--purge-config` is passed. OpenRazer packages, group
  membership, and daemon stay.
- Unsafe or unverifiable service state refuses with files retained for manual
  recovery. See [upgrades and
  recovery](docs/troubleshooting.md#installer-upgrades-and-rollback).

## Status

The repository has hardware-independent coverage for read-only capture, strict
profile configuration, OpenRazer control, physical USB-parent discovery,
ordered frame parsing, proxy-before-grab activation, forwarding clones,
replacement outputs, session D-Bus, and the native Qt configuration UI. The
12-button first slice has passed on both wired and HyperSpeed hardware for
F13/F14 DPI stage changes and held F17-to-LEFTALT output. All 19 12-button
controls are captured and remapped on both transports - including verified
top buttons (`KPSLASH`/`F18`), scan-less wheel tilt, and the full thumb grid -
plus the 6- and 2-button plates on HyperSpeed. Motion, clicks, and
high-resolution wheel are validated through the forwarding proxies, and the
2-button plate validates virtual-mouse back/forward output. HyperSpeed daemon
restart, sleep/wake, receiver reconnect, disconnect-while-held cleanup, and a
live wired-to-HyperSpeed switch have also passed. The service now applies
desired DPI stages, scroll settings, power settings, poll rate, and all three
lighting zones to the hardware with per-setting failure reporting, and the
snapshot publishes observed DPI, scroll, poll-rate, battery, charging, and
firmware values for the GUI Device tab, profile management selects the side-plate
layout (12/6/2) with revision-checked apply, and a calibration mode rebuilds
forwarding as pure passthrough and adopts the observed DPI stages and scroll
settings into the active profile on end. Broader passthrough and wired
alternate-plate capture remain.

Naga V3 Pro support is intentionally developed against a compatible custom
OpenRazer build while
[PR #2904](https://github.com/openrazer/openrazer/pull/2904) remains unmerged.
This is a project prerequisite, not a development blocker. The pinned baseline
is fork commit `26b0eeb5ed70d638fa3528851adcd5e58369a7f5` on branch
`test-pr-2904-edualb`, packaged as `3.12.1.pr2904.fix2-1`. Release packaging
provides these optional prebuilt pinned Arch assets; older tags may lack them.
Installation is strictly
opt-in and restricted to experimental compatible Arch/pacman/Python hosts;
other distributions require a native matching-source build. Exact-pin natural
idle/wake acceptance remains open; older baseline passes do not establish fix2
hardware acceptance. See
[integration findings](docs/integration-findings.md) for the tested baselines,
required capabilities, and known wireless behavior. Release notes pin the
exact prerequisite OpenRazer revision in [release notes](docs/release-notes.md);
see also [troubleshooting](docs/troubleshooting.md).

## Control Panel

The native interface has three tabs and one shared active-profile selector:

- **Device:** connection and battery status, power settings, profile management,
  manual attached-plate selection, and update checks. Diagnostics and recovery tools are
  collapsed by default; hardware errors remain visible.
- **Buttons:** clickable mouse artwork and a flat binding list numbered to
  match the illustration. All three plate groups are editable.
- **Settings:** compact DPI stages and polling rate, scroll behavior, and all
  three lighting zones. One Apply Settings action saves these sections together
  in a single revision-checked update. Each lighting zone has a color wheel and
  manual RGB entry for effects that support color.

Device and Settings use two columns on desktop and stack vertically in a narrow
window. Unrelated saves and service refreshes retain unsaved drafts; changing
profiles asks before discarding them. Edits retained after an external profile
switch remain attached to their original profile until saved or discarded.
Plate identity is not detected automatically: select the attached plate under
Device's Profiles section before using that plate's bindings on hardware.
The tray menu includes Active profile and Scroll wheel submenus alongside Show
and Quit. Profile changes use the same unsaved-edit confirmation as the window
header. Tray scroll shortcuts save the active profile's desired mode,
acceleration, and Smart Reel settings; observed hardware state is displayed
separately and may take time to catch up.

**Device > Updates** shows the installed version and checks GitHub releases when
you click **Check for updates**. Stable releases are the default; **Include
pre-releases** is an optional saved preference. Checking runs in the background,
does not contact GitHub automatically, and does not install or downgrade the
application. **Release notes** opens the selected release in your browser.

See the root [changelog](changelog.md) for the formal release history and
[release prerequisites](docs/release-notes.md) before upgrading.

## Screenshots

The three-tab layout on the maintainer's desktop. In v0.3.0, update controls
also appear below Profiles on the Device tab.

### Device

![Device tab with connection status, power settings, and profiles](assets/screenshots/Device.png)

### Buttons

![Buttons tab with clickable mouse artwork and numbered bindings](assets/screenshots/Buttons.png)

### Settings

![Settings tab with DPI stages, polling rate, scroll behavior, and lighting](assets/screenshots/Settings.png)

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
- OpenRazer kernel module, daemon, and Python client from a build that supports
  both target product IDs
- Membership in the group required by the OpenRazer package
- Read access to the Naga event nodes and write access to `/dev/uinput`

No separate host Python/PySide6 installation is needed for the AppImage itself,
which bundles its own CPython runtime, PySide6/Qt, and Python dependencies.
OpenRazer retains its own host Python/daemon/client dependencies: the installed
OpenRazer Python client with matching host modules and daemon is a required
system integration. Host Python 3.12 or newer with Qt 6 and PySide6 is a
source-development and native-build requirement only (a native builder may bundle
its own CPython 3.14; the portable release toolchain is CPython 3.12.15); the
kernel module, daemon, and client must come from the same compatible build.

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

The fake archive tests also require `bsdtar`: install `libarchive` on Arch or
`libarchive-tools` on Debian/Ubuntu. These tests read fixture archives only;
they do not install packages or access hardware.

Run the baseline checks with:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pyright
.venv/bin/pytest
```

The repository-local `buildpython` runner combines these checks, writes per-step
logs and summaries under `buildlog/naga-control/`, and always excludes hardware
tests:

```bash
.venv/bin/python -m buildpython                  # full validation, no packaging
.venv/bin/python -m buildpython --profile quick  # compile, lint, formatting
.venv/bin/python -m buildpython --profile ci     # standard checks and pytest
.venv/bin/python -m buildpython --list-steps
.venv/bin/python -m buildpython --run-steps "Ruff,Type Check" --verbose
.venv/bin/python -m buildpython --profile release # validation, AppImage, Docker smoke
```

`--with-appimage` appends packaging and smoke checks to any selection.
The AppImage step assembles the image in Python under `buildpython/steps/appimage/`.
The smoke step requires Docker and network access, tests the exact versioned artifact in
Ubuntu 24.04, imports bundled dependencies, creates an offscreen Qt application,
checks CLI help, and installs integration assets only into temporary directories.
It never starts the service or accesses physical device nodes.
Set `NAGA_APPIMAGE_SMOKE_IMAGE` to use another compatible container image.
Missing required validation tools or Docker fail the selected check.

`--profile debt` runs generic static-analysis reports, not copied KeyRGB policies.
Coverage and dead-code reports additionally need the optional `coverage` and
`vulture` packages; ShellCheck is an optional system tool. Copied debt baselines
have been cleared. The 400-line limit applies to all Python files, including tests.

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
install `system/systemd/user/naga-control.service` under the user systemd
unit directory and `system/dbus-1/services/org.nagacontrol.Service1.service`
under the session D-Bus service directory. Enable the user unit after installing
the scoped udev rule; neither the service nor the GUI should run as root.

## AppImage

Build the self-contained AppImage (bundled CPython, PySide6, and Python
dependencies, including dbus-python and NumPy for the host OpenRazer client;
OpenRazer itself stays on the host):

```bash
.venv/bin/python -m buildpython --run-steps AppImage --verbose
```

The builder writes `dist/Naga-Control-<version>-<arch>.AppImage` and stages its
wheel, isolated runtime venv, and AppDir under `build/appimage/`. A local native
build proves the packaging step only, not the portable glibc floor: native
library and glibc compatibility still depend on the build host. Release
validation instead runs source checks with
`.venv/bin/python -m buildpython --profile full` on the host, then the
controlled `buildpython/steps/appimage/portable-build.sh` (Ubuntu 22.04 /
CPython 3.12.15, requires Docker and excludes host runtime influences), which
runs the static finished-artifact gate before bundled userspace smoke and asset
staging, followed by the Ubuntu 24.04 smoke step. No distribution support pass
is claimed from a local build alone.
Native Linux `x86_64` and `aarch64` builders are recognized; this is not a
cross-compiler. `PYTHON_BIN` optionally selects a native, GIL-enabled CPython 3.12+ runtime;
otherwise the invoking interpreter's base CPython is bundled. appimagetool 1.9.1 is checksum-verified.
Build-time Python commands are isolated from inherited Python paths; the runtime
disables user-site and current-directory imports and exposes only the intentional
host OpenRazer client/daemon-helper bridge alongside bundled dependencies.

Host templates live in `system/`, integration artwork in `assets/icons/hicolor/`,
and the AppRun dispatcher in `buildpython/steps/appimage/AppRun`. The bundled
integration payload uses `usr/share/naga-control/system/` and sibling
`assets/icons/hicolor/`; build tooling and diagnostic probes are not shipped.
For source-only integration, `--source-dir` points at `system/` with icons in
the sibling `assets/icons/hicolor/` tree.

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
- `docs/build-layout-consolidation.md`: build ownership standard and migration checks
- `docs/debt-paydown-campaign.md`: prioritized debt work, acceptance checks, and progress
- `buildpython/`: validation, AppImage construction, and release orchestration
- `system/udev/70-naga-control.rules`: least-scope device access rules
- `system/`: desktop, systemd user, D-Bus, and udev templates
- `assets/icons/hicolor/`: authoritative integration icons
- `src/naga_control/`: application package
- `tests/`: non-hardware test suite

## License

Naga Control is licensed under the [GNU General Public License v2.0 (GPL-2.0-only)](LICENSE),
matching OpenRazer which the project uses for all hardware operations, and is provided
without warranty as described in the license. Reference implementations may be studied
for behavior, but no Polychromatic or Input Remapper source is copied into this project.
