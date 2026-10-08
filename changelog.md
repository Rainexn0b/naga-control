# Changelog

All notable changes to Naga Control are documented here. This is the
authoritative release history, following the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Release dates below use UTC, not commit dates. Historical entries were
backfilled from the verified GitHub publication records.
See [release prerequisites and hardware limits](docs/release-notes.md) before
installing or upgrading.

## [Unreleased]

## [0.5.0] - 2026-10-08

This release improves installer portability, GUI profile/mode clarity, and
release-pipeline safety.

### Added

- Read-only **Device mode** tray status distinguishes requested mode, observed
  hardware mode and software-remapping readiness, including offline and errors.
  Physical firmware/driver switching remains blocked pending interactive safety
  validation; this clarification does not enable it.
- Releases now include CI-built pinned OpenRazer Arch packages
  (driver-dkms/daemon/Python client from fork commit `26b0eeb5...`) plus a
  sha256 sidecar, installable as one pacman transaction.
- OpenRazer replacement is explicitly opt-in: the installer validates the
  release's pinned Arch packages before one interactive sudo pacman transaction;
  other distributions keep the manual matching-source procedure.
- Installer portability diagnostics check the actual capability first: a
  PATH-robust `ldconfig` lookup for an x86_64 `libfuse.so.2` cache entry, a
  usable `/dev/fuse` character device, and kernel FUSE support. Exact
  per-release manual package references live in the README and troubleshooting
  guide; the ordinary app-only path never installs distro dependencies and never
  guesses a package name from branding or `ID_LIKE` (the explicit Arch
  OpenRazer helper remains the only opt-in package path).
- Checkout-only `scripts/distro_report.sh` gives read-only offline distro
  advice with no network, device access, prompts, or filesystem changes and no
  host Python requirement. It parses `os-release` as data, reports reviewed
  manual FUSE2 rows only for Ubuntu 22.04, Ubuntu 24.04, and Arch, and stays a
  diagnostic: it is not installer integration, eligibility, or a support
  certificate, and it never checks prerequisite presence.
- Controlled portable-build candidate: `buildpython/steps/appimage/` pins an
  Ubuntu 22.04 (glibc 2.35) x86_64 toolchain with CPython 3.12.15
  (`Dockerfile.portable` plus `portable-build.sh`), alongside a finished static
  audit of the AppImage outer runtime and extracted bundled ELF/provider
  closure (inspection only, nothing executed). This is a build candidate and
  static gate only; it does not establish real ABI, distro install, or launch
  acceptance.
- Interpreter-free safe uninstaller `scripts/uninstall.sh` needs no AppImage
  and no host Python. It reuses the stable per-user install lock, verifies HOME
  ownership and symlink safety, removes only known installer-owned files,
  refuses unsafe state with files retained, keeps profiles unless
  `--purge-config` is passed, retains OpenRazer packages/group/daemon, and
  still asks consent for udev rule removal.

### Changed

- Device > Software profiles now owns the single profile dropdown with
  New/Rename/Delete, an authoritative active indicator, and explicit Activate;
  the header shows only the mouse title. Dropdown selection edits the selected
  profile (stable IDs disambiguate duplicates) while Buttons/Settings/Power
  follow the active profile; per-profile plate drafts survive selection changes
  with concise pending feedback. The tray shows a bold disabled **Software
  controls** header with **Active software profile** plus **Scroll wheel**
  directly under it (no Software controls submenu), then read-only native
  behavior under Onboard / firmware with Device mode independently
  discoverable; software actions stay greyed and blocked unless driver mode is
  verified, and the closed gate reads **Switch mode (safety validation
  required)**, distinguishing software-mode readiness from switching safety.
  Requested policy, observed hardware mode,
  and remapping readiness are shown separately using existing snapshots; this
  presentation clarification opens no hardware gate and claims no new hardware
  validation.
- Profile selectors now say **Active software profile** and show names plus IDs;
  **Software profiles** management explains selection for editing versus activation.
  These are Naga Control saved profiles, not onboard slots. Device mode uses
  **Software / driver** and **Onboard / firmware**, separately from scroll mode.
- The project license changes from MIT to GPL-2.0-only to match OpenRazer,
  which the project uses for all hardware operations.
- Checkout installer safety: exact-tag AppImage checksum verification before
  execution, replacement, service stop, or sudo; read-only desktop/FUSE/tool
  preflight; stable per-user install lock; private staging with atomic
  replacement; consent-based Naga-only upgrades with verified image/tag
  rollback pairs; and deferred activation without `--now`. App-only completion
  means a running service, not hardware readiness. Ordinary installation stays
  app-only and never offers or modifies OpenRazer; the experimental Arch helper
  remains a separate exact-pin opt-in cohort with isolated `/usr/bin/python3`
  checks, active-kernel preflight, and reboot/re-login activation.

### Fixed

- The user service now signals the main process first during graceful shutdown,
  keeping the AppImage's FUSE filesystem alive until Python exits. Previously,
  stopping the whole control group could remove image-backed library pages
  during native cleanup and cause SIGBUS.
- Installer FUSE errors no longer assume `ldconfig` is on PATH and no longer
  guess per-release package names; missing-library, runtime, and kernel
  failures report the SONAME/capability check plus the README and
  troubleshooting references.
- Profile activation and tray scroll requests now gate on verified
  software/driver mode, reachability, and pending apply state, rechecking after
  confirmation and at deferred execution. Blocked requests fail cleanly without
  false success, preserve all drafts, and reconcile tray checkmarks.
- Runtime teardown hardening: session, reader, and hardware-worker teardown
  retains ownership and joins through cancellation and close failures;
  generated-output cleanup attempts each held release independently; and
  provisional input/capture plus OpenRazer/D-Bus acquisitions roll back on
  failure instead of leaving partial state.
- The service reserves the public D-Bus name before startup and gates wire
  calls on readiness; failed startup closes the gate with an unavailable error
  rather than entering uninitialized providers.
- Diagnostics preserve CLI failures while redacting identifier and I/O error
  payloads, lifecycle failures report without identifier payloads, and failed
  scroll reads invalidate cached state with bounded battery conversion so no
  stale readback is reported.
- Test-suite CI compatibility: Python 3.12-safe annotations avoid a runtime
  `CoroutineType` subscription, and offscreen Qt widget teardown uses
  deterministic close/deleteLater with strict deletion verification. This
  covers the test suite only and changes no product behavior.
- The controlled portable-build toolchain installs the `file` utility, so
  AppImage assembly no longer fails with `file command is missing`. The
  finished-artifact static gate leaves the extraction staging child absent for
  the trusted extractor while keeping the private parent directory and
  fail-closed checks. These are build-pipeline fixes only and establish no
  real ABI, distro install, or launch acceptance.

### Known Limitations

- Requires the custom OpenRazer baseline at
  `26b0eeb5ed70d638fa3528851adcd5e58369a7f5`
  (fork `Rainexn0b/openrazer`, branch `test-pr-2904-edualb`, Arch packages
  `3.12.1.pr2904.fix2-1` attached to this release); no released upstream
  minimum replaces it. Use compatible kernel module, daemon, Python client,
  udev rules, and metadata. The temporary Arch prerequisite bridge is
  explicitly opt-in; source pinning is not an indefinite security freeze.
- Only Razer Naga V3 Pro wired `1532:00E7` and HyperSpeed `1532:00E8` are
  supported, one transport at a time. Bluetooth and other devices are excluded.
- Do not run the GUI or service as root.
- Exact-pin natural idle/wake, held-output handoff, and interactive
  firmware/driver mode-switch checks remain unverified; firmware mode is not
  for daily use and the tray switch stays unavailable.
- Wired 6- and 2-button plate signatures remain uncaptured and are not enabled.
- Manual AppImage extraction remains launch-only; it is not a managed FUSEless
  installation.
- Representative distro install, launch, upgrade, and uninstall checks are not
  yet verified; the controlled build candidate and static outer-runtime and
  bundled ELF/provider-closure audit do not imply real ABI or distro
  acceptance.

## [0.4.0] - 2026-10-05

This release adds direct key recording, cleaner button artwork, lighting color
editing, and profile/scroll tray shortcuts.

### Added

- The Buttons tab can record a key or shortcut without requiring manual token
  syntax. Direct entry remains available, and native Linux key information
  distinguishes right- and left-side modifiers when Qt provides it.
- A second GUI launch now activates the existing window, including when it is
  hidden in the tray or minimized, without creating a second service client.
- Each lighting zone now has a color swatch and hue/saturation wheel with a
  separate value control. The manual RGB field remains available for precise
  entry. Colors are staged per zone and only written on Apply Settings.
- The system tray now includes an Active profile submenu. It shows the
  service-selected profile and uses the same unsaved-edit confirmation as the
  window header before switching profiles.
- The tray's Scroll wheel submenu can change the active profile's saved scroll
  mode, acceleration, and Smart Reel settings. It distinguishes desired values
  from observed hardware status and displays scroll-related write failures.
- Experimental service-wide firmware/driver mode policy in configuration, with
  OpenRazer mode readback, fail-open input handoff, and desired/observed mode
  status. Software mode remains the default; no tray mode switch is exposed.

### Fixed

- KDE Plasma/Wayland can match the running GUI to its desktop launcher instead
  of treating a source launch as a generic `python3` window.
- The Buttons list and artwork use the same natural button-number order, with
  click regions matched to the aligned mask, preview, and sidecar assets.
- Buttons-tab action and binding editors now require a direct click before
  mouse-wheel gestures can change their values. Unarmed gestures scroll the
  binding list instead, and leaving the editor resets wheel editing.
- Profile switches only report success after readback confirms the new active
  profile; tray entries refresh when profiles are changed by another client.
- A rejected profile switch or tray scroll write no longer discards confirmed
  drafts. A successful tray scroll change reconciles only the Scroll editor,
  preserving unrelated Settings edits.
- An older background configuration refresh cannot overwrite a newer saved
  revision in the GUI.
- Remapping session teardown now closes grabbed readers even when their read
  tasks are cancelled before their first event-loop turn.

### Known Limitations

- The mode policy's held-output and wireless wake hardware checks remain
  inconclusive. Do not rely on firmware-mode persistence for daily use or
  enable a tray switch before those checks are complete.
- Wired 6- and 2-button signatures remain uncaptured, so those wired plate
  layouts are not enabled. Attached-plate selection remains manual.

## [0.3.0] - 2026-10-03

This release brings a simpler control panel, safer editing, and manual update
checks with pre-release support.

### Added

- A shared active-profile selector above all three tabs, with confirmation
  before discarding unsaved edits when switching profiles or deleting the
  active profile.
- One **Apply Settings** action for DPI stages, polling rate, scroll mode,
  acceleration, Smart Reel, and lighting. These edits are submitted as one
  revision-checked configuration update; this does not make separate OpenRazer
  hardware writes transactional.
- Explicit **Discard changes** actions for button bindings, Settings, and power
  drafts.
- Manual update checking under **Device > Updates**, showing the installed
  version, latest stable release, and latest prerelease. A persistent
  **Include pre-releases** preference selects the comparison channel, with
  proper version ordering rather than text or publication-date ordering.
  This is a version checker, not an automatic installer.
- A root changelog as the release-note source. The release workflow extracts
  only the tagged version's section for GitHub release notes and
  classifies future prerelease tags as prereleases, rather than publishing the
  entire release history for every tag.
- README screenshots showing Device, Buttons, and Settings.

### Changed

- Consolidated the seven-page GUI into **Device**, **Buttons**, and
  **Settings**. Device groups connection and battery status, power controls,
  profiles, and updates; Settings groups sensitivity, polling, scrolling, and
  lighting.
- Replaced grouped binding sections with a compact, flat numbered list matching
  illustration regions 1 through 30. Primary clicks and the wheel remain
  clearly marked as passthrough rather than editable bindings.
- Updated the mapping illustration with exact clickable polygon regions for
  the mouse and all three side plates. Every supported plate's bindings can
  be edited without first selecting that plate as attached.
- Moved the manual attached-plate selector to **Device > Profiles**, with an
  explicit **Apply plate** action for the selected profile. Editing an inactive
  plate's bindings does not change the plate used for input translation.
- Made forms more compact and responsive, with two-column sections that stack
  at narrow widths, screen-aware opening size, bounded field widths, and more
  room for the mapping artwork. Detailed service diagnostics are collapsible.
- Reduced the default launch width and height by 25% while preserving the
  window's aspect ratio and screen-aware sizing.
- Refresh observed hardware state through the service every 30 seconds,
  including battery and DPI, even while the window is hidden. This change was
  added after 0.2.0; GUI snapshot polling is separate from hardware reads.
- Reduced the tray battery overlay to text only, without the opaque background
  patch.

### Fixed

- Corrected physical side-plate numbering: the 12-button plate runs
  column-by-column from bottom to top, from 1 at bottom-left to 12 at top-right;
  the 6-button plate runs 1 through 3 left-to-right on top, then 4 through 6
  right-to-left below.
- Keep unsaved button, Settings, power, and plate drafts across unrelated saves,
  status refreshes, stale-revision responses, and remote configuration changes.
  Retained editor drafts stay associated with their original profile and show
  a warning when the service's active profile changes.
- Returning edits to their original values clears the dirty state and reloads
  the latest active profile, so the next Apply cannot target an obsolete draft.
- Freeze the profile selector and editors immediately during asynchronous
  profile switching, restoring them only after completion reaches the GUI.
  Unrelated notifications cannot re-enable editing during the switch.
- Anchor queued configuration writes to the revision used to build their
  document, so a later model refresh cannot silently bypass stale-write checks.
- Cancel pending GUI worker tasks cleanly on exit. A stalled update request
  runs in a daemon thread and cannot keep the application alive after quitting.
- Install application icon directories with world-readable traversal
  permissions so desktop environments can resolve the installed icons.
- Support repeat asset uploads to an existing GitHub release. New releases
  remain drafts until both the AppImage and its checksum have been uploaded.
- Keep older stable-release retries from replacing a newer release as GitHub's
  latest download, and use tag-pinned documentation links in release notes.

### Known Limitations

- The custom OpenRazer prerequisite is unchanged:
  `add-razer-naga-v3-pro-support` at
  `2416bfebf0175db6aae519a450f55fe9eba255e9`.
- Only Razer Naga V3 Pro wired `1532:00E7` and HyperSpeed `1532:00E8` are
  supported, one transport at a time. Bluetooth and other Razer devices are
  outside this scope.
- Do not run the GUI or service as root.
- Plate selection remains manual; making all plate bindings editable is not
  automatic plate detection. Wired 6- and 2-button signatures remain uncaptured
  and are not enabled in the wired translation table.
- Primary clicks and wheel scrolling are passthrough, not newly remappable
  controls. The 6- and 2-button plates are unlit by design.
- This release scope does not claim new hardware validation. Existing results
  and remaining checks are recorded in
  [Hardware Validation](docs/hardware-validation.md), including plate removal
  while held and broader passthrough coverage.

## [0.2.0] - 2026-09-29

[Published as v0.2.0](https://github.com/Rainexn0b/naga-control/releases/tag/v0.2.0).
Carries the cumulative functionality and fixes published in 0.1.4.

### Added

- System tray integration with a battery percentage overlay,
  status/transport/charging tooltip, click-to-toggle, and close-to-tray.
- An interactive Buttons-page illustration: clicking a highlighted control
  jumps to its binding row, with current-binding hover text and attached-plate
  availability cues.
- Application icons for the desktop entry and KDE start menu, installed in
  hicolor sizes 64 through 512 by `--install`.

### Fixed

- Bundled the unpublished 0.1.5 AppImage fix: expose only the host's OpenRazer
  Python package through an isolated symlink directory, avoiding host
  site-packages shadowing the bundled `evdev` build.

### Known Limitations

- The published notes describe the hardware-validated remapping milestone:
  F13/F14 change DPI stages, held F17 emits LEFTALT down/up, and teardown removes
  virtual devices and releases grabs. Earlier validation fixes and settings
  support are cumulative, not all newly introduced by the 0.2.0 tag.
- The custom OpenRazer baseline and device/plate limits remain unchanged. See
  [Hardware Validation](docs/hardware-validation.md) for dated evidence rather
  than treating the original release's remaining-work summary as current.

## [0.1.4] - 2026-09-28

[Published as v0.1.4](https://github.com/Rainexn0b/naga-control/releases/tag/v0.1.4).
First published release; includes the cumulative work previously labeled
0.1.0 through 0.1.3, which were not separately published releases.

### Added

- A Linux control panel exclusively for Razer Naga V3 Pro wired `1532:00E7`
  and HyperSpeed `1532:00E8`, using OpenRazer for hardware operations.
- Keyboard-key, held-modifier, key-combination, mouse-button, device-action,
  disabled, and passthrough bindings, with manual profiles and side-plate
  selection. The 12-button plate has translation tables for both transports;
  the 6- and 2-button tables are HyperSpeed-only.
- Hardware-backed DPI stages and X/Y settings, polling rate, scroll modes,
  acceleration, Smart Reel, idle timeout, low-battery threshold, and three
  lighting zones.
- Calibration passthrough that adopts observed DPI stages and scroll settings
  into the active profile.
- An unprivileged session D-Bus service with revision-checked configuration
  writes and a PySide6 GUI for overview, buttons, DPI, scroll, lighting, power,
  and profiles. Mappings continue without an open GUI.
- AppImage packaging and SHA-256 sidecars, a one-line installer,
  and host integration install/uninstall support.

### Fixed

- Start the AppImage service command correctly instead of exiting immediately
  without the service entrypoint's `__main__` guard.
- Bundle `dbus-python` so the AppImage can use the host's OpenRazer client.
- Sanitize `PYTHONHOME`, `PYTHONPATH`, and `LD_LIBRARY_PATH` for the host
  OpenRazer probe, and put the OpenRazer package's parent directory on
  `PYTHONPATH` so `import openrazer` succeeds.
- Refresh the installed AppImage when the resolved release version changes.
- Accept OpenRazer `dbus.Int32` device identifiers, translate numeric scroll
  modes correctly, and suppress physical repeats for held modifier mappings.

### Known Limitations

- Requires the custom OpenRazer baseline at
  `2416bfebf0175db6aae519a450f55fe9eba255e9`; no released upstream minimum
  replaces this prerequisite.
- Driver mode `3:0` is required for mapped events and can silently regress to
  `0:0` after idle, suppressing special-button and side-grid events until
  reasserted. Stale kernel pressed-state can block startup; physically tapping
  the affected control clears a lost release.
- Scroll acceleration and Smart Reel default to off. Automatic plate detection,
  wired alternate-plate mappings, and simultaneous wired/HyperSpeed attachment
  are not supported.
