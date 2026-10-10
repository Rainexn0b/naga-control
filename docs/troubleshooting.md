# Troubleshooting

## Installer prerequisites

The new checkout installer is app-only by default. It requires a **non-root
Linux x86_64 desktop user**, writable HOME/`.local`/user integration trees, and
no symlink file destinations or installation ancestors. Do not run the panel
as root or fix this by broadening device permissions. It checks user systemd
and session D-Bus with read-only manager/bus status queries, never by calling
Naga/OpenRazer or automatically activating a bus name during preflight.

Install missing prerequisites yourself using your distribution's normal package
management; the installer never invokes apt/pacman for an ordinary app install:

- Common tools: `bash`, `curl`, `sudo`, coreutils (`sha256sum`, `mktemp`, `stat`,
  `install`, `cp`, `mv`, etc.), `grep`, `cmp` (diffutils), `flock` (util-linux),
  systemd (`systemctl`, `busctl`), udev (`udevadm`), and `ldconfig` (glibc/libc-bin).
- Log in to a real desktop user session with a reachable user systemd manager
  and session D-Bus (Debian/Ubuntu: systemd user support and `dbus-user-session`;
  Arch/Fedora: systemd and dbus desktop session integration). Do not use sudo
  for the installer or borrow another user's bus credentials.
- FUSE2: an x86_64 `libfuse.so.2` library. Use the README's
  [exact-release package references](../README.md#install), not package guesses
  inherited from another release or derivative. Also provide FUSE runtime/kernel
  support and access to `/dev/fuse` through your normal distribution/session policy.
  Preflight discovers the library and checks runtime **metadata only**; it never
  opens/mounts `/dev/fuse`. Containers may lack usable FUSE even with the library.
  Managed installation always requires normal FUSE2/runtime support. Leave
  `APPIMAGE_EXTRACT_AND_RUN` unset (or `0`); any other set value is rejected before
  changes. Extraction is manual launch-only: the managed unit, desktop entry,
  D-Bus activation and wrapper do not persist a caller shell's extraction
  environment. Do not use it to bypass managed-install FUSE checks.

Optional Arch OpenRazer replacement also needs system `/usr/bin/python3` 3.9+
for parsing, the package builder's matching Python minor, `bsdtar` (libarchive),
`base-devel`, `dkms`, active-kernel headers/build Makefile/`.config`, and, for
Clang kernels, `clang llvm lld` tools. These checks cover **only the running
kernel**. Supply headers/toolchains for all other intended kernels yourself;
Secure Boot signing and DKMS hook success remain operator responsibilities.
See [exact prerequisites](release-notes.md#experimental-archpacman-installer).
Standalone default/`--check` remains read-only inventory without build gating.
For a separate read-only install-environment check, use
`bash scripts/install_openrazer.sh --preflight`. It checks the Python minimum,
active-kernel metadata/tools and session connectivity without networking,
lock/state writes, confirmation, group/package changes or unit configuration.
It overrides install flags/`=1`; `=0` still hard-skips everything, and invalid
environment values fail. It does not establish release archive/Python-minor
compatibility or hardware readiness. Actual installation repeats these gates.

## Installer checksums and older releases

The new installer requires the selected exact release tag's
`Naga-Control-x86_64.AppImage.sha256`: one lowercase 64-hex digest, two spaces,
the exact AppImage basename, and a newline, with no extra rows or paths. Both
downloaded and reused local bytes must match before execution, service stop,
sudo or image replacement. `installed-tag` alone is never trusted. An existing
previous image/tag must also verify before a rollback pair can be retained.

For the SELECTED new release, a missing or malformed sidecar, an empty
image, or a digest mismatch is always a hard failure before any execution,
service stop, privilege, or replacement, not a reason to fall back to an
unchecked download. A previous old checksum is not a prerequisite: an old
mismatch or a missing old sidecar quarantines while the strictly verified
new image still replaces it. An unverified previous image does not block a verified upgrade: a
mismatched, empty, or sidecar-missing old image is replaced by the strictly
verified new image and preserved as a private unverified quarantine, not a
verified rollback pair; only a previously verified old image keeps a
`rollback.*` pair. A selected release without its canonical sidecar still
cannot be installed, but a previous tag without a sidecar can be upgraded
from. Preserve the installed image on selected-release failures; use a
reviewed release that supplies the canonical sidecar, or arrange a separately
reviewed manual recovery. Do not bypass the
check by running the new installer as root or editing the hash to match.
GitHub HTTPS hashes detect corruption/mismatch but are not signatures or an
independent authenticity guarantee.

Matching outer bootstrap, `--ref`, and `--version` from the same published
tag is the only reproducible selection; older tags keep their original
behavior and checkout `main` fixes are not retroactive to the published
v0.5.0 tag. Review the actual tagged script; no unpublished future version
is recommended.

## Installer upgrades and rollback

Before an upgrade, **quit the GUI and release held controls**. The new installer
validates app bytes and all required app/rule/helper downloads first, runs the
optional helper's read-only `--preflight` when opted in, then asks
before gracefully stopping an active **Naga-only** user service. Remapping stops
temporarily. Default refusal or non-TTY execution cancels without replacement;
`--restart-service` is explicit consent, not consent to package conflict prompts.
It never kills GUI/OpenRazer processes. A synchronous stop must finish with
`ActiveState=inactive`; active/deactivating/failed remnants abort replacement.

App-only success starts/enables Naga. Opt-in checks the helper's install-environment
prerequisites before stop consent, so missing Python/headers/tools/session support
leaves the old running Naga and its files unchanged. A helper lacking
`--preflight` support fails closed with no legacy fallback; only explicit opt-in
needs that helper. The actual package/helper install runs after consented Naga
stop and verified app bytes, then enables **without starting**.
Package/helper failure can leave partial package changes: Naga remains stopped,
with no automatic restart of the previous app against that state. Inspect the
cohort and arrange reboot/re-login/runtime verification before activation.
A failed udev reload is explicitly **staged**, not ready: ask your administrator
to reload rules, then replug only the target mouse. No broad trigger is run.

A stable per-user `~/.local/share/naga-control/install.lock` serializes the new
app installer and standalone opt-in helper through integration/activation and
package completion. A second invocation fails rather than waits. Never delete
or recreate this inode to bypass a lock; retry after the owner exits. Downloads
and integration are privately staged and cleaned on ordinary failure/signals;
SIGKILL/power loss cannot run shell cleanup.

Atomic replacement preserves the old image inode for already-running readers.
Verified rollback pairs are published as private
`~/.local/share/naga-control/rollback.XXXXXX/` directories containing
`naga-control.AppImage`, `installed-tag`, `image.sha256`, and an installer ownership
marker. Forced same-version
downloads retain a pair too; unchanged reinstalls keep the newest existing
pair. After a successful install only the newest verified pair is kept;
older verified pairs are removed and owned quarantines are cleaned.
Backups do not persist indefinitely across successful upgrades; failed
installs preserve all prior snapshots. This is **not full-system
or package rollback**: profiles are never rewritten/backed up here, and udev/
OpenRazer package changes require separate operator recovery. User integration
and wrapper files are restored best effort on failed replacement/activation;
`RESTORATION FAILED` is a distinct error requiring inspection, not success.

An unverified previous image is held as a private
`~/.local/share/naga-control/quarantine.XXXXXX/` directory containing the
exact old bytes, tag, and an `UNVERIFIED` marker (never `image.sha256` or a
restore pair). It is not a verified backup and has no restore command; a
failed replacement leaves Naga stopped and disabled with new files partial
where the failure happened, so inspect and repair manually without resuming
an unverified image. A held quarantine is removed after a successful
install with other owned quarantines. A failure quarantine survives
uninstall for manual cleanup; remove it only after a verified replacement
is confirmed and working.

Manual image/tag restore (choose the remaining verified backup, quit the GUI, release
controls, and do not start Naga after a partial OpenRazer transaction):

```bash
systemctl --user stop naga-control.service
systemctl --user show naga-control.service --property=ActiveState --value
# Continue ONLY if the result is inactive. Substitute your retained backup.
backup="$HOME/.local/share/naga-control/rollback.XXXXXX"
(cd "$backup" && sha256sum -c image.sha256)
# Continue ONLY if verification succeeds. Use unique siblings on each target FS.
(umask 077; image=$(mktemp "$HOME/.local/bin/.naga-restore.XXXXXX") && tag=$(mktemp "$HOME/.local/share/naga-control/.tag-restore.XXXXXX") && trap 'rm -f "$image" "$tag"' EXIT && cp -p "$backup/naga-control.AppImage" "$image" && cp -p "$backup/installed-tag" "$tag" && mv -fT "$image" "$HOME/.local/bin/naga-control.AppImage" && mv -fT "$tag" "$HOME/.local/share/naga-control/installed-tag")
systemctl --user daemon-reload
# Inspect/repair user unit, D-Bus entry and wrapper if restoration reported failure.
# Only after the app and OpenRazer prerequisites are coherent/activated:
systemctl --user start naga-control.service
```

Do not run another installer concurrently with manual recovery. Stop and inspect
any failing step rather than continuing the snippet blindly. If the second move
fails, finish the image/tag pair while Naga remains stopped. The backup remains
available; user integration may need a reviewed reinstall. Uninstall removes
installer rollback pairs/stamp, retains failure quarantines for manual cleanup,
retains
the lock inode and OpenRazer, and preserves profiles
unless `--purge-config` is explicitly requested.

Completion distinguishes running service from staged prerequisites, cancellation
and failure/rollback. A running unit is **not hardware readiness**. The installer
prints, but does not execute, this read-only application snapshot command (it
can D-Bus-activate Naga, so use only after prerequisites are ready):

```bash
busctl --user call org.nagacontrol.Service1 /org/nagacontrol/Service1 org.nagacontrol.Service1 GetSnapshot
```

Require `status` = `available`, then perform physical F13/F14 DPI-stage and F17
held-ALT down/up checks with one transport and the precautions in
[Hardware Validation](hardware-validation.md). Installation never proves them.

## Service says `absent` or mappings do nothing

1. Check the receiver/cable: `busctl --user call org.nagacontrol.Service1
   /org/nagacontrol/Service1 org.nagacontrol.Service1 GetSnapshot` - `status`
   must be `available`.
2. Start with read-only installed inventory:
   `bash scripts/install_openrazer.sh --check`. `KNOWN PINNED COHORT` means
   consistent installed versions/source stamps, not hardware acceptance.
   `UNVERIFIED` means unknown/older/partial builds, not necessarily unsupported.
   Check host imports separately:
   `/usr/bin/python3 -I -B -c 'import openrazer.client; import openrazer_daemon'`.
   Inventory/minor checks always use this system interpreter, not an activated
   virtualenv or PATH alias. Explicit opt-in reinstalls all three selected
   archives even at the same version; pacman's own prompts are not skipped.
   Missing imports, a sleeping mouse, permissions, an old loaded module, or an
   unavailable daemon can all prevent runtime discovery; no PID grep/version
   string proves support. Inspect `systemctl --user status
   openrazer-daemon.service` and its user journal. Do not blindly restart a new
   daemon against a module left loaded from an older package cohort.
3. Ordinary app installation never repairs/replaces OpenRazer. Experimental
   Arch/pacman users can explicitly permit replacement with
   `bash scripts/install_openrazer.sh --version <release-tag> --install` or the
   app installer's `--install-openrazer`. See
   [prerequisites and rollback](release-notes.md#required-openrazer) first.
   Package/Python validation and user-unit failures are non-success; after a
   post-transaction failure, inspect inventory before activation. Group consent
   is separate; reboot/re-login and runtime verification remain required. Other
   distributions need matching-source native packages, not pacman commands.
4. Driver mode regression: clicks working without special-button mappings can
   indicate mode `0:0`, but this is not proof of its cause. Capture the app
   snapshot/journal before recovery. With compatible activated OpenRazer and no
   held mouse keys, a coordinated Naga-only restart may rebuild mappings; do not
   replace OpenRazer or restart it as the default response. See
   [dated recurrence evidence](binding-recurrence-2026-10-06.md) and
   [hardware gates](hardware-validation.md) for still-unverified idle/wake cases.

## Startup fails with "physical keys are held before grab"

A release event was lost earlier and the kernel still reports a pressed key.
Tap the affected button (usually the one last held, e.g. a side button or
left click) once; restart the service. The journal names the node.

## Mapped buttons emit digits instead of their mapping

The active profile's bindings are the defaults. Open the GUI Buttons page
and apply the desired bindings, or activate another profile using the
**Activate** button in **Device > Software profiles** or the tray's
**Active software profile** directly under the **Software controls**
header. Choosing a profile in the
Software profiles dropdown only selects it for editing; editors follow the
active profile. Entries show the display name and identifier, so identical
names remain distinguishable.

## Software profiles versus device mode

Naga Control profiles are saved application/software profiles with desired
hardware settings, not onboard mouse slots. **Onboard / firmware** device mode
uses the mouse's native behavior and does not apply the selected software
profile. No onboard-slot enumeration or binding upload is provided.

The tray shows a non-clickable **Software controls** header with **Active
software profile** and **Scroll wheel** directly under it, plus **Onboard /
firmware** read-only native-behavior status, with
**Device mode** independently discoverable offline. Software mutations require
verified driver mode plus saved software policy; unverified, offline,
mismatched, calibrating, or legacy states leave those actions greyed and their
handlers blocked with saved values reconciled. The **Device mode** submenu is
read-only and stays accessible offline. It separates the requested service-wide
policy, observed hardware mode, and software-remapping readiness, plus a neutral
disabled **Switch mode (safety validation required)**. **Software /
driver** readback alone is
not proof that mappings are active: readiness, matching modes, calibration and
errors also matter. Disconnected retained snapshots show unknown/offline
observations rather than current verified mode or activity. Scroll wheel mode
is a separate setting.

Firmware/driver switching is still unavailable pending the remaining interactive
held-output, wake, failure and reconnect safety checks in
[Device-Mode Handoff](hardware-validation.md#device-mode-handoff-ui-06-not-yet-validated).
This UI clarification does not open that gate or authorize live hardware tests.

## Inputs behave oddly while another remapper runs

Input Remapper and similar tools race for the same evdev nodes. Stop them:
`systemctl --user stop input-remapper.service`.

## Debug bundle

Inspect the diagnostic capture options with:

```bash
naga-control-capture --help   # from a pip install; or:
./dist/Naga-Control-*.AppImage capture --help
```

By default, captures redact explicit serial, physical-path, `phys`, and `uniq`
metadata fields. `--include-identifiers` opts those fields back in. Normal input
error diagnostics and application-generated read-error `end_reason` values show
only source/operation, exception class, and validated errno information, not
exception messages, filenames, or chains. Identifier opt-in does not enable raw
error text. Output-write diagnostics retain the destination you requested.

This is not whole-capture anonymization: frames can contain incidental keys,
scans, motion, and timestamps; device names and environment strings are retained.
Live event paths are printed to the terminal but not persisted in normal metadata.
Review captures and terminal transcripts before sharing. Older captures are not
rewritten, and library callers can still inspect original exceptions and causes.
For service logs use `journalctl --user -u naga-control.service -b`; capture-local
error formatting is not a sanitizer for those logs.

## Emergency release

If generated keys stick, press the GUI "Release generated outputs" button or
run `busctl --user call org.nagacontrol.Service1 /org/nagacontrol/Service1
org.nagacontrol.Service1 ReleaseAll`. Unplugging the receiver also releases
everything; SIGKILL drops all grabs via the kernel.
