# Post-0.3 UI Implementation Tracker

Requested after v0.3.0 on 2026-10-03. Implement and validate one concern at a
time; do not ship a cosmetic control ahead of its service-side behavior.
This tracker supplements, rather than replaces, the architecture and hardware
validation contracts.

## Queue

| ID | Concern | Status | Dependency |
| --- | --- | --- | --- |
| UI-01 | Attached-plate identification | Investigation complete; implementation blocked | Reliable physical swap/identity evidence |
| UI-02 | Click-before-wheel binding editors | Implemented and installed; awaiting desktop confirmation | None; GUI-only |
| UI-03 | Per-zone color wheels and manual color entry | Implemented and installed; awaiting desktop confirmation | UI-02 verified |
| UI-04 | Tray menu ownership and active-profile shortcuts | Local polish installed; desktop confirmation pending | UI-03 verified |
| UI-05 | Tray scroll mode, acceleration, and Smart Reel | Local polish installed; desktop confirmation pending | UI-04 verified |
| UI-06 | Tray software versus hardware mode | Read-only Device mode status polished and installed locally; physical switch still blocked | Wireless wake recovery and remaining failure/ownership tests |

Delivery order: UI-02, UI-03, UI-04, UI-05. Revisit UI-01 when a guided hardware
capture is available. Resolve UI-06's meaning before implementing its service
operation. The tray items are separate because changing profiles, changing
settings, and transferring input ownership have different safety requirements.

## UI-01: Attached Plate

### Current Selection

Device > Software profiles owns the single profile dropdown (stable itemData
IDs), Activate, New/Rename/Delete, and the authoritative Active indicator;
there is no header selector or management list. The dropdown selects the
profile being edited (plate, rename, and other per-profile drafts), which
need not be the active profile; explicit Activate, or tray activation
through the same guard, switches the service-active profile. Buttons,
Settings, and Power editors follow the service-active profile. Per-profile
plate drafts are preserved across selection changes; the activate global
guard discards them only after a confirmed successful service switch. Apply
plate saves the selected profile's `plate_layout` without activating it.

At runtime, the active profile's layout selects raw-signature translations,
the binding group used on key-down, and the input interfaces to read/grab/proxy.
This is a manual declaration, not an attached-plate observation or an artwork
filter. All three plate groups remain editable on Buttons.

Relevant code: `gui/profiles_page.py`, `gui/profile_controls.py`,
`gui/profile_plate_drafts.py`, `gui/editors.py`,
`application/remapping.py`, `adapters/evdev/signatures.py`, and
`domain/profiles.py`, under `src/naga_control/`.

### Evidence and Blocker

- OpenRazer exposes no plate-identity method in the inspected Naga API.
- The 6- and 12-button plates share the first six key and scan signatures on
  interface `02`. Pressing only those buttons cannot distinguish the plates.
- Buttons 7-12 provide evidence for a 12-button plate after a press. Captured
  2-button signatures are distinct among these plate tables. Neither identifies
  an idle attachment or proves that a later swap did not occur.
- Static evdev capabilities, lighting state, device names, and `eventN` paths
  are not plate identity and must not be used as substitutes.
- Wired 6- and 2-button signatures remain uncaptured. Their wired translation
  lookup currently returns an empty table, not a supported alternate layout.
  Consider an explicit unsupported-layout guard alongside future plate UX work.

### Next Investigation

Use the existing read-only capture tool and a separately scoped udev/OpenRazer
signal observation to record removal/insertion of each plate, idle attachment,
press/release, removal while held, reconnect, and sleep/wake. Test wired and
HyperSpeed separately, never simultaneously. The capture tool's `--plate` and
`--driver-mode` flags are annotations, not hardware identity reads; its metadata
is a startup snapshot, not a continuous swap monitor.

Keep raw recordings private and add only sanitized evidence and fixtures.
No real-device capture or hardware mutation was performed for this initial
investigation. See [Plate Validation](hardware-validation.md#plate-validation)
and [Input Topology](integration-findings.md#observed-input-topology-and-controls).

### Acceptance

- Prove a reliable identity/swap signal before offering automatic selection.
- Expose unknown/ambiguous observations and preserve a manual fallback.
- Keep observed attachment separate from desired per-profile layout.
- Require the supported physical USB ancestor; never discover by names alone.
- Fence transitions and release generated held keys/grabs before unsafe changes.
- Do not add raw HID commands or unsupported wired tables to guess around gaps.

## UI-02: Binding Editor Wheel Guard

### Scope

Both Action and Binding combo boxes on Buttons require a direct mouse click
before wheel events can change their values. Hovering, tabbing into an editor,
or jumping to a row through the artwork must not arm wheel editing. Wheel
gestures over an unarmed editor should scroll the enclosing binding list.

Keep normal keyboard editing, explicit popup selection, and wheel scrolling of
an intentionally opened popup. Focus leaving the editor disarms it; returning
by keyboard or programmatic focus does not rearm it. Clicking an editable
combo's text field counts as an explicit click.

Do not change mouse hardware scroll settings, remapping behavior, or other tabs
in this concern.

### Acceptance

- Hover/programmatic/keyboard focus plus wheel leaves bindings and dirty state
  unchanged, while the list scrolls when there is room.
- Clicking either editor enables its normal wheel behavior while focused.
- Clicking the editable text field, popup interactions, and focus-out/reset
  behavior have offscreen regression coverage.
- A rebuilt row starts unarmed; explicit key navigation still works.
- Default tests use synthetic Qt events and fakes, not real device nodes.
- Run all standard checks, rebuild/install locally, and request desktop testing
  before starting the next concern.

## UI-03: Lighting Color Wheels

### Scope

Add a compact hue/color wheel with saturation/value controls and a color swatch
for each of Thumb grid, Logo, and Scroll wheel. Retain optional precise manual
RGB entry; support hex entry if it can share the same validated color model.
Manual override here means entering the color numerically, not bypassing the
profile or creating an undocumented temporary hardware override.

Keep brightness and effect settings independent. Disable color controls for
effects that do not accept a color and preserve existing per-zone effect
restrictions. Use the existing single Apply Settings operation; choosing or
typing a color must not issue immediate hardware writes.

### Acceptance

- Wheel, swatch, and manual entry stay synchronized without feedback loops.
- Each zone maintains an independent draft; RGB values remain integer 0-255.
- Invalid/incomplete manual input does not write hardware or discard other edits.
- Loading, cancelling, discarding, switching effects, and stale revisions behave
  consistently with the existing Settings draft protection.
- The three-zone layout remains compact and usable when columns stack.
- Fakes verify the serialized configuration and OpenRazer-facing settings path.

## UI-04: Tray Profiles and Menu

### Current State and Scope

`gui/tray_icon.py` already constructs a basic context menu with Show Naga Control
and Quit. Extend that menu, keeping explicit ownership of menu/action objects
and preserving tray battery updates, window toggling, and close-to-tray.

Add a checkable Active software profile submenu built from service configuration,
with the authoritative active profile marked. Use the existing asynchronous
SelectProfile path and the same unsaved-edit guard as the Software profiles
Activate button.

The window header shows only the mouse title; Device > Software profiles owns
the single dropdown, New/Rename/Delete, active indicator, and explicit
Activate. The dropdown manages selection for editing (stable itemData IDs);
editors follow the service-active profile. The tray remains a quick-activation
shortcut. These are Naga Control saved software profiles with desired hardware
settings, not onboard slots. Firmware mode does not apply the selected software
profile. The clarification preserves profile and scroll editing behavior.

### Acceptance

- The menu survives object lifetimes and is reachable by the desktop's context
  action; menu activation must not accidentally toggle the main window.
- Selecting a profile applies through the service, not widget-local state.
- Profile list/active marker update after remote changes, renames, and deletions.
- Offline, failed, pending, and stale operations cannot falsely show success.
- Hidden-window drafts are retained or discarded only after confirmation.
- Existing Show/Quit and battery behavior remain covered by tests.

## UI-05: Tray Scroll Shortcuts

### Scope

Add exclusive Tactile, Free spin, and Precision tactile actions, plus checkable
Acceleration and Smart Reel controls. The initial design edits the active
profile's persisted desired scroll settings through revision-checked service
configuration, matching Settings; it is not a separate untracked hardware state.
Keep desired choices and observed hardware/readback failures distinguishable.

### Acceptance

- UI calls remain asynchronous and serialized by the existing service path.
- Each action changes only its intended settings and preserves bindings,
  lighting, power, DPI, and unrelated GUI drafts.
- Menu state is reconciled after failures, stale revisions, profile changes,
  reconnects, and unsupported/unavailable hardware.
- No menu construction/refresh issues hardware mutations.
- Fakes cover every mode/toggle and failure path before desktop/hardware testing.

## UI-06: Software Versus Hardware Mode

### Decision And Current State

The requested shortcut switches the mouse between its onboard firmware profile
and OpenRazer driver mode; it is not a pause of software remapping. Calibration
is not hardware mode and must not be relabeled as such.

The inspected OpenRazer API exposes `getDeviceMode` / `setDeviceMode`:
`3:0` enables driver-mode reports used by software remapping; `0:0` lets firmware
handle native behavior and can suppress mapped special-button/grid reports.
There is no API here to upload arbitrary Naga Control bindings to onboard memory.
The source now has a service-wide, revisioned `mode` policy (existing TOML
defaults to `software`), verified OpenRazer mode operations on the hardware
worker, and desired/observed/error/readiness fields in service snapshots. In
firmware mode, the service releases generated outputs and grabs before the
mode write and skips profile hardware settings. In software mode it verifies
`3:0` before preparing any forwarding proxies or grabs; calibration rejects
firmware mode. A daemon rescan tears down old input ownership before checking
mode again. The Device summary shows mode readback and errors, but the tray
switch is deliberately not enabled. The service mode policy is included in
v0.4.0 as experimental functionality; earlier guided tests used source only.

The confirmed firmware/driver interpretation now has a persistent, **read-only
Device mode** tray submenu that stands alone at the tray root; it is not
nested under the Software or Onboard groups. The tray root holds Show Naga
Control, a non-clickable **Software controls** header with **Active software
profile** and **Scroll wheel** directly under it, a read-only **Onboard /
firmware** submenu stating native
mouse behavior with no onboard editing, the independent **Device mode** status
submenu, and Quit. Human labels are
**Software / driver** and **Onboard / firmware**. Requested policy, observed mode,
software-remapping readiness and errors are shown separately using existing
snapshots/configuration. The Device summary shares the same presentation. Offline
retained snapshots cannot claim current mode or mapping activity; mismatch,
unknown, not-ready and calibration states do not claim successful active mapping
or firmware handoff. Inactive mode groups are greyed, and software profile and
scroll actions run only through verified software-mode UI and entry guards,
including pending-write, deferred-execution, and modal-confirmation checks.
A short neutral disabled **Switch mode (safety validation required)**
keeps the still-closed switching gate discoverable even offline, with safety
reasons in tooltips and docs. There is no selectable mode action,
setter, new API or configuration behavior in this clarification.

These presentation changes are now installed locally; they do not prove
hardware acceptance. Held-output, wake, failure and reconnect checks remain
interactive prerequisites before enabling any physical mode switch.

OpenRazer also reasserts driver mode on startup/resume/wireless wake, so a single
device-mode write is not a durable policy. Resolve ownership with OpenRazer
before promising a persistent hardware-mode switch.

The service reapplies the desired mode after observed OpenRazer lifecycle
rescans. A 30-second poll fails open on an unknown mode and can reassert
firmware mode after a later read confirms driver-mode drift. It does not retry
an uncertain write; that still requires a later explicit lifecycle rescan.
This is not a guarantee of uninterrupted onboard mode after sleep/wake.
An unavailable startup or device-action failure now releases the software
session and retries safe topology/mode reconciliation on the slow poll; a
transient read failure can rebuild mapping only after verified software mode
and ready forwarding. Lifecycle signals also release generated outputs and
grabs even if their immediate rescan fails.

### Acceptance Before UI Delivery

- Define persistence, reconnect, sleep/wake, daemon-restart, and failure policy.
- Complete service-owned state/operations, observed status, hardware-port
  support, worker serialization, IPC/client/presenter support, and fake tests.
- Fence queued actions and release generated held keys and grabs before handing
  control to firmware. Re-enable mapping only after the correct mode and ready
  forwarding proxies are established.
- Use OpenRazer only; no raw HID and no GUI/service running as root.
- Fail open on unsafe state or uncertain write; report the actual result.
- Complete opt-in lifecycle/hardware validation before enabling the tray action.

## Verification Log

- Initial plate and mode investigation: source/documentation inspection only.
- UI-02: `gui/click_wheel_combo.py` is used for both binding editors. Its explicit
  click gate distinguishes temporary popup focus from leaving the editor.
  Seventeen targeted offscreen cases pass, including scrolling the enclosing
  list, editable-child clicks, popup selection, artwork focus, and rebuilt rows.
- UI-02: Ruff lint/format, Pyright, and the full default suite passed:
  588 tests passed, one opt-in hardware test deselected, eight dependency warnings.
  The AppImage was rebuilt, installed locally, and passed an offscreen startup
  smoke check. Desktop interaction confirmation is still pending.
- No hardware mode, plate detection, lighting, or tray changes were shipped in
  this first implementation. The fix is recorded under Unreleased in the root
  changelog; no new release or tag was published.
- UI-03: each lighting zone now offers a swatch button opening a hue/saturation
  wheel with a value slider. Manual RGB entry remains available; wheel Cancel
  leaves the draft alone and accepting a color updates only that zone's draft.
  Effects without color disable both entry points. Dedicated offscreen tests
  cover zone isolation, malformed RGB repair, atomic Settings Apply, remote
  changes, and stale/discard behavior. Ruff lint/format, Pyright, and the full
  default suite passed: 619 tests passed, one hardware test deselected, eight
  dependency warnings. The local AppImage was rebuilt and installed, and an
  offscreen startup and wheel-render smoke check passed. Desktop confirmation
  remains pending; no new tag or release was published.
- UI-04: the tray now owns a persistent Show / Active profile / Quit menu.
  Checkable profile entries are derived from the service configuration. The
  header and tray share one draft-confirmation and asynchronous selection path;
  a switch is considered successful only after service readback verifies the
  active profile. Targeted offscreen tests cover menu lifetime, hidden drafts,
  remote rename/deletion, offline and stale actions, pending switches, and
  success/failure recovery. Ruff lint/format, Pyright, and the full default
  suite passed: 636 tests passed, one hardware test deselected, eight dependency
  warnings. The local AppImage was rebuilt, installed, and passed an offscreen
  startup check. Desktop context-menu interaction remains to be confirmed;
  no new release or tag was published.
- UI-05: the tray now offers exclusive scroll modes plus Acceleration and Smart
  Reel toggles. Checkmarks reflect the active profile's saved desired settings;
  a separate observed-mode line and hardware-failure text do not pretend those
  settings reached the device. The service receives revision-checked writes
  through the existing GUI presenter. An unsaved Scroll draft is replaced only
  after a confirmed successful tray save; unrelated DPI/lighting drafts remain.
  Failed writes, unavailable hardware, remote profile changes, and late older
  refreshes are covered by fake/offscreen tests. Ruff lint/format, Pyright,
  and the full default suite passed: 686 tests passed, one hardware test
  deselected, eight dependency deprecation warnings. The AppImage was rebuilt,
  installed locally, and passed an offscreen startup check. Desktop tray-menu
  interaction remains to be confirmed; no new release or tag was published.
- UI-06: the firmware-versus-driver interpretation is confirmed. Source-only
  mode policy, verified OpenRazer adapter calls, serialized fail-open handoff,
  readback in snapshots, and fake/offscreen tests are implemented. A guided
  opt-in test passed both transports' mode handoffs and firmware mode recovery
  after OpenRazer restart, uncovering and fixing a reader-start cancellation
  grab leak. Wireless wake did not validate, and held-output/failure cases
  remain. Ruff lint/format, Pyright, and the full default suite passed:
  732 tests passed, three opt-in hardware tests deselected, eight dependency
  deprecation warnings. Local installation and tray mode switching are gated; no UI-06
  AppImage was installed. See [UI-06 Guided Results](hardware-validation.md#ui-06-guided-results-2026-10-04).
- UI-06 recovery follow-up: fake tests cover unavailable startup, temporary
  mode-read failure, unavailable device actions, and a lifecycle signal with
  no immediate provider rescan. Ruff lint/format, Pyright, and the full default
  suite passed: 741 tests passed, five opt-in hardware tests deselected, eight
  dependency deprecation warnings. New human-operated, opt-in held-F17 and
  natural-sleep tests require a TTY; natural sleep has not been run. The
  installed service and tray remain unchanged pending physical results.
- UI-06 guided follow-up: HyperSpeed held-F17 attempts on 2026-10-05 were
  inconclusive (operator prompt timeouts, one unrecorded event-order mismatch,
  and a safe rejection of an already-held F17 at startup). The installed
  service was restored in driver mode. The held-output and wake gates remain
  open; no mode-switching tray item was enabled. Ruff lint/format, Pyright,
  and the current default suite passed: 762 tests passed, five opt-in hardware
  tests deselected, eight dependency deprecation warnings.
- UI-06 recovery incident: later on 2026-10-05 the mouse was observed back in
  firmware mode `0:0` while the installed service requested software mode. A
  verified `3:0` OpenRazer write and service restart restored F17. The service
  snapshot had stayed unavailable with a fenced worker awaiting rescan. Source
  now requests a rescan when stopping a session fences that worker; a fake
  regression protects transient-read recovery. Current default checks pass:
  763 tests, five opt-in hardware tests deselected, Ruff and Pyright clean.
  The installed build has not been replaced, and the original device-mode
  drift trigger remains unknown. v0.4.0 includes the fake-tested recovery fix,
  but the remaining physical checks are still deferred.
- 2026-10-08 local install: rebuilt `Naga-Control-0.4.0-x86_64.AppImage`
  (SHA256 `f66f4efbc3ae7c7e03338ca2c03ef6204e6dc027f210a6f70801b6c6ebccab31`)
  and installed it atomically to the local GUI path with backup retained under
  a temporary `/tmp/opencode` directory; no new release, tag, or version bump.
  Source-line check exempts `.opencode` and retains the project 400-line guard
  (426 focused tests pass); `ruff check .`, `ruff format --check .`, and `pyright`
  passed, and full offscreen `pytest` passed (3263 passed, 2 skipped,
  5 hardware deselected, coverage unavailable). Hardware-free mounted-image,
  Qt offscreen/presentation, service/capture/integration `--help`, and
  temporary `KillMode=mixed` payload checks passed; clean-distro smoke not
  claimed. Only the Naga user service was restarted after GUI Quit with
  controls released and single transport; OpenRazer, saved config, and
  installed tag unchanged. Snapshot recovered to available HyperSpeed with
  desired/observed software, mode ready, and no mode/settings failures. GUI
  left closed for user desktop confirmation. No physical F13/F14/F17,
  held-output, wake, or mode-handoff tests were run; UI-06 switch stays blocked.
- GUI polish (source-only, not installed): unified Device > Software profiles
  dropdown with New/Rename/Delete, active indicator, and explicit Activate
  replaces the header selector and management list; per-profile plate drafts are
  preserved across selection and cleared only after confirmed service writes.
  The tray splits into Software controls (Active profile plus Scroll wheel) and
  Onboard / firmware read-only status, with Device mode independently
  discoverable; software mutations require verified driver mode and saved
  software policy, and the gate reads Switch mode (unavailable). Fake/offscreen
  coverage updated; no build, install, release, or hardware validation claimed.
- GUI polish correction (source-only, not installed): activation and scroll
  intents now also gate on pending `applying…`, revalidate after modal
  confirmation, and recheck verified software/reachability at deferred execution
  before any presenter call; blocked deferred intents emit clean completion,
  preserve all drafts, reconcile tray checkmarks, and never report false
  success. Tray profile requests use the shared software-allowed gate including
  scroll-pending. Plate drafts accept only exact `int` 12/6/2; Activate shows
  Already active when appropriate and pending reason while saving. No service,
  IPC, schema, hardware, or install changes; UI-06 switch stays blocked.
- 2026-10-08 polish supervisor verification: `ruff check .`,
  `ruff format --check .`, and `pyright` passed. Full fake/offscreen
  `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q` passed (3382 passed,
  2 skipped for unavailable coverage, 5 hardware deselected); the focused
  GUI suite passed 449 tests. Fake-only offscreen previews confirmed the
  consolidated desktop layout and inactive onboard tray greying. Changes
  remain source-only; no AppImage replacement, service restart, or new
  hardware evidence is claimed for this polish.
- 2026-10-08 local 0.5.0 polish install: `Naga-Control-0.5.0-x86_64.AppImage`
  SHA256 `26aeac622167d1d2cdc3755da60976f00f60af7f1500d625b3ea5b9d877aadc1`, installed
  to the local GUI path; prior image, config, installed tag, and Naga/OpenRazer
  PIDs (3261508/2054792) backed up under `/tmp/opencode/naga-polish-install.LZs6LV`.
- The 0.5.0 version came from a concurrent release-prep `pyproject.toml` change
  during the build, not this wave. The primary stopped before install, confirmed all
  9 GUI source hashes unchanged, and the user explicitly approved the local test build;
  no publish, tag, or new release authorized; release-prep docs/changelog untouched.
- User confirmed GUI Quit, released buttons, and one USB transport (hidden GUI on first
  check was quit and absence verified). Under the per-user installer lock with baseline
  rechecked unchanged, atomic replace ran with `KillMode=mixed` and hash verification;
  only `systemctl --user restart naga-control.service` executed afterwards.
- No integration files, config, OpenRazer, permissions, or installed tag changed
  (config/tag match backup; OpenRazer PID 2054792 unchanged). New Naga PID 3646324
  active/running; read-only snapshot at generation 2 HyperSpeed: available,
  desired/observed software, mode ready, no mode/hardware/settings failures. GUI left
  closed for user desktop launch.
- Checks: ruff, ruff format (412 files), pyright, full offscreen pytest (3382 passed,
  2 skipped, 5 hardware deselected) and focused GUI pytest (449 passed) passed.
  Mounted-image hardware-free checks (0.5.0 version, bundled imports, 9 GUI hashes,
  offscreen MainWindow/Tray, 360px layout, `--help` set, 8-file `KillMode=mixed`
  payload) passed. Clean-distro smoke not run (Docker unavailable); no physical
  F13/F14/F17, held-output, wake, firmware-handoff, or reconnect tests run. Not a
  published release or portable ABI acceptance; earlier source-only and 0.4.0 records
  above stand as then-true history.
- Tray flatten follow-up (source-only, not installed): the tray root now shows
  Show Naga Control, a bold disabled **Software controls** header, **Active
  software profile** and **Scroll wheel** directly under that header, then
  Onboard / firmware, Device mode, and Quit. No Software controls submenu
  remains. The safety gate now reads **Switch mode (safety validation
  required)** with held-output, wake, failure and reconnect reasons plus a note
  that software-mode readiness is separate from switching safety. Source
  0.5.0 plus this change is
  not installed; the installed local 0.5.0 image
  (`26aeac622167d1d2cdc3755da60976f00f60af7f1500d625b3ea5b9d877aadc1`) and its
  desktop proof above remain the last installed state.
- 2026-10-08 flat-tray local install: rebuilt and installed
  `Naga-Control-0.5.0-x86_64.AppImage` SHA256
  `d9d42f8d2cf643233b2575e29dfe256ca3b38c34951076430729d950df266182`
  (candidate and installed `~/.local/bin/naga-control.AppImage`
  match) with backup of prior image/config/stamp/PIDs plus 98-file SHA
  manifest retained under temporary `/tmp/opencode`; build log at
  `/tmp/opencode/naga-flat-tray-install.nsoEGK/build.log`. This installs the
  flattened root only (Show, bold disabled Software controls header, Active
  software profile and Scroll wheel directly at root, no wrapper submenu,
  Onboard / firmware, Device mode, Quit; gate reads Switch mode (safety
  validation required) with readiness-versus-safety tooltip); profile/scroll
  greying, entry guards, and read-only onboard/device-mode presentation are
  unchanged. The prior `26aeac62...` image record above remains the earlier
  install history.
- Install checks: `ruff check .`, `ruff format --check .` (420 files), and
  `pyright` passed; full offscreen `pytest` passed (3454 passed, 2 skipped,
  5 hardware deselected); focused tray/mode/profile tests passed (115
  passed). Hardware-free packaged checks passed: 0.5.0 runtime imports and
  all 98 packaged product Python files matched source byte hashes with no
  stale modules; offscreen Tray header/parents/mode-gating checks, `--help`
  set, and 8-file `KillMode=mixed` payload checks passed. Source/metadata
  manifests matched before and after build; no version bump, tag, publish,
  or new release. Only `systemctl --user restart naga-control.service` ran
  after verified GUI Quit, released controls, single transport, baseline
  recheck, and per-user install lock with atomic replace and hash match.
  New Naga PID 156169 active/running with `KillMode=mixed`; OpenRazer PID,
  saved config, installed tag, and stamp unchanged. Settled snapshot at
  generation 2: available HyperSpeed, desired/observed software, mode ready,
  not calibrating, no mode/hardware/settings failures. GUI left closed for
  user desktop confirmation; physical switch stays blocked. Clean-distro
  smoke (Docker unavailable), physical F13/F14/F17, held-output, natural
  wake, handoff, and reconnect checks were not run.
