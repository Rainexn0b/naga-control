# Installation

Detailed install, update, and removal notes for Naga Control. For
prerequisite failures and recovery procedures, see
[Troubleshooting](troubleshooting.md#installer-prerequisites) and
[upgrades and recovery](troubleshooting.md#installer-upgrades-and-rollback).
For the required backend revision, see
[required OpenRazer](release-notes.md#required-openrazer).

## Install and update

Download the installer to a file, then run it. Do not pipe it into bash:

```bash
curl -fsSL https://raw.githubusercontent.com/Rainexn0b/naga-control/main/install.sh -o install.sh && bash install.sh
```

Rerun the same command to update. With no `--version`, the installer
resolves the latest published release and installs only the fixed
`Naga-Control-x86_64.AppImage` plus its `.sha256` sidecar; it never installs
unreleased `main` source. From a checkout, run `./install.sh` for the same
default.

For a reproducible install, download the outer bootstrap from the same
published tag, then pin both the bootstrap and the artifact:

```bash
curl -fsSL https://raw.githubusercontent.com/Rainexn0b/naga-control/<tag>/install.sh -o install.sh && bash install.sh --ref <tag> --version <tag>
```

Flags alone do not pin the bootstrap: running with `--ref <tag>
--version <tag>` on a file downloaded from `main` is not a pinned
bootstrap. Native helper/builder source follows `--ref`, resolved to a full
commit before download, independently of the AppImage release selected by
`--version`.

The app installer also accepts `--version <tag>`, `--install-openrazer`,
and `--restart-service`. `--restart-service` only consents to a graceful
Naga-only stop and resume during upgrade; it does not make the install fully
noninteractive or sudo-free.

Before upgrading, quit the GUI and release held controls; remapping pauses
briefly during a consented service stop. The installer verifies the exact
release's canonical `.sha256` sidecar and AppImage bytes before execution,
replacement, or `sudo`, and keeps at most one verified rollback pair. See
[upgrades and recovery](troubleshooting.md#installer-upgrades-and-rollback).

A successful install enables and starts the user service, which is not
hardware readiness: replug the target mouse after any udev reload, then
verify with this read-only snapshot (it can D-Bus-activate the service; the
installer only prints it):

```bash
busctl --user call org.nagacontrol.Service1 /org/nagacontrol/Service1 org.nagacontrol.Service1 GetSnapshot
```

Require `status` = `available`, then perform physical F13/F14 DPI-stage and
F17 held-ALT down/up checks with one transport attached. Installation alone
establishes none of these checks.

## App-only default and backend opt-in

The ordinary install is app-only by default. On eligible Arch/pacman and
exact named Ubuntu/Debian/Fedora/openSUSE hosts with an entirely absent
backend, it offers consented first-install setup of the pinned cohort:
Arch/pacman uses optional prebuilt release assets, while exact named
Ubuntu/Debian/Fedora/openSUSE hosts build local unsigned
`openrazer-*-local` packages from the same pinned source. Existing, partial,
manual, or unknown backends are left unchanged and other hosts stay
app-only. Declining, EOF, or no TTY stays app-only with hardware
prerequisites reported as not ready.
`NAGA_CONTROL_INSTALL_OPENRAZER` unset offers when entirely absent; `=1` is
explicit opt-in; `=0` skips even with `--install-openrazer`; any other value
is an error. Native routes are first-install only even when explicit; only
Arch keeps a reviewed explicit reinstall path. Activation is deferred (units
are enabled without starting them), so reboot or re-login and verify
OpenRazer first. Never fetch and execute a helper directly
(`scripts/install_openrazer.sh` or `scripts/install_openrazer_native.sh`).

## FUSE2 runtime (manual per-release references)

Managed service and desktop integration always require FUSE: an x86_64
`libfuse.so.2` in the `ldconfig` cache, a usable `/dev/fuse`, kernel FUSE
support, and a normal user systemd/session D-Bus desktop session. FUSE 3
alone does not satisfy the FUSE 2 library check. Leave
`APPIMAGE_EXTRACT_AND_RUN` unset (or `0`); extraction is manual launch-only,
not a supported FUSEless managed installation.

Install the library yourself with your distribution's package management;
the installer never installs FUSE packages. Only these four package
references are verified (2026-10-08); they are package names, not a claim of
complete prerequisites, AppImage launch, install, or hardware support:

| Release | Package (repository) | Manual command | Reference |
| --- | --- | --- | --- |
| Ubuntu 22.04 | `libfuse2` (universe) | `sudo apt install libfuse2` | https://packages.ubuntu.com/jammy/libfuse2 |
| Ubuntu 24.04 | `libfuse2t64` (universe) | `sudo apt install libfuse2t64` | https://packages.ubuntu.com/noble/libfuse2t64 |
| Arch (rolling) | `fuse2` (extra) | `sudo pacman -S fuse2` | https://archlinux.org/packages/extra/x86_64/fuse2/ |
| Fedora 44 | `fuse-libs` | `sudo dnf install fuse-libs` | https://packages.fedoraproject.org/pkgs/fuse/fuse-libs/fedora-44.html |

The Fedora 44 package provides `libfuse.so.2()(64bit)` as version
`2.9.9-25.fc44` on x86_64. Enable `universe` manually if your Ubuntu setup
needs it; the installer never configures repositories. Other releases and
derivatives need their official native package context for the exact
release; release branding or `ID_LIKE` alone never selects a package.

## Portable build target

The approved portable build target is Ubuntu 22.04 (glibc 2.35) on x86_64.
Dated validation evidence is tracked in the
[portability tracker](distro-portability-plan.md); see
[GitHub releases](https://github.com/Rainexn0b/naga-control/releases) for
current publication status. Scope is bundled runtime imports, offscreen
QApplication, CLI `--help`, and temporary integration payload only; no full
install, upgrade, remove, FUSE, user units, D-Bus, sudo, udev, desktop,
service, or hardware certification is claimed.

## AppImage integration

Usage for a downloaded AppImage:

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

`--install` asks for sudo only for
`/etc/udev/rules.d/70-naga-control.rules`; the systemd user unit, D-Bus
activation file, and desktop entry install under `~/.config` and
`~/.local/share`. After installing, run
`systemctl --user daemon-reload && systemctl --user enable --now naga-control`.
Under Device > Application, enable start at login (tray) to launch the GUI
at login without changing mapping-service startup; see
[desktop startup controls](desktop-startup-controls.md).

## Uninstall

Checkout-free removal of a standalone install (needs no AppImage and no host
Python). It removes installer-owned app and user integration files:

```bash
curl -fsSL https://raw.githubusercontent.com/Rainexn0b/naga-control/main/uninstall.sh -o uninstall.sh && bash uninstall.sh
```

From a checkout:

```bash
./uninstall.sh --yes
```

Quit the GUI and release held controls first. Removal prompts before udev
rule deletion, which needs `sudo`. `--yes` only skips that udev-removal
confirmation; `sudo` authentication is still required and all ownership and
service checks remain. Profiles stay unless `--purge-config` is passed.
OpenRazer packages, group membership, and daemon stay. Unsafe or
unverifiable service state refuses with files retained for manual recovery;
see [upgrades and
recovery](troubleshooting.md#installer-upgrades-and-rollback).
