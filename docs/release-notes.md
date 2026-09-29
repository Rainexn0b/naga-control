# Release Notes

## v0.2.0

First hardware-validated release with the full remapping GUI. Includes the
unpublished v0.1.5 AppImage openrazer-path fix.

### Hardware validation

The HyperSpeed 12-button first slice now passes end to end on real hardware:
F13/F14 change the OpenRazer DPI stage up/down, F17 emits exactly
LEFTALT down/up, and teardown releases the grab and removes the virtual
devices. Fixes found during validation: OpenRazer `dbus.Int32` identifiers
were rejected in the backend, numeric scroll modes were mishandled, and
modifier keys repeated while held. Remaining validation work (wired
transport, sleep/wake, reconnect, disconnect-while-held) is tracked in
`docs/hardware-validation.md`.

### GUI

- System tray icon with a battery percentage overlay on the bottom half,
  status/transport/charging tooltip, click-to-toggle, and close-to-tray
- Interactive mapping illustration on the Buttons page: click a highlighted
  zone (DPI pair, wheel tilts, top front/rear, ring finger, side grid 1–12)
  to jump to and highlight its binding row; zones show the current binding
  on hover and gray out when the attached plate does not match
- Application icon for the KDE start menu / desktop entry, installed in
  hicolor sizes 64–512 by `--install`

### Required OpenRazer

Unchanged from v0.1.0: the custom OpenRazer
`add-razer-naga-v3-pro-support` baseline at commit
`2416bfebf0175db6aae519a450f55fe9eba255e9`. Without this baseline the Naga
V3 Pro is not recognized and the service stays `absent`.

## v0.1.5

Fix: adding the host site-packages to `PYTHONPATH` shadowed the bundled
`evdev` build. The AppImage now exposes only the host's openrazer package
through an isolated symlink directory.

## v0.1.4

Fix: AppRun added the openrazer package directory itself to `PYTHONPATH`
instead of its parent, so `import openrazer` still failed. Reinstall with
the one-line installer.

## v0.1.3

Fix: the AppRun host-openrazer probe crashed because `PYTHONHOME` pointed
at the bundled interpreter, so the service still could not reach OpenRazer.
The probe now sanitizes `PYTHONHOME`/`PYTHONPATH`/`LD_LIBRARY_PATH`.

## v0.1.2

Fix: the AppImage could not import the host's `openrazer.client`
(pure Python) because the bundled interpreter lacked the `dbus` bindings.
The AppImage now bundles `dbus-python` and points `PYTHONPATH` at the
host's openrazer package, so the service reaches the hardware from inside
the AppImage.

## v0.1.1

Fix: the AppImage `service` command exited immediately because
`service_cli` lacked its `__main__` guard, so the installed user service
never came up and the GUI showed "service unreachable". Reinstall with the
one-line installer or rerun `install.sh`.

## v0.1.0

First usable release of Naga Control, a personal control panel for the Razer
Naga V3 Pro on Linux.

### Scope

- Razer Naga V3 Pro only, HyperSpeed (`1532:00E8`) and wired (`1532:00E7`)
- 12-, 6-, and 2-button side plates (6/2-button translation tables are
  HyperSpeed-only until wired captures exist)
- Button remapping to keyboard keys, mouse buttons, and device actions
- Hardware-backed settings: DPI stages, scroll mode/acceleration/Smart Reel,
  idle and low-battery thresholds, poll rate, and all three lighting zones
- Calibration mode that forwards everything as passthrough and adopts the
  observed DPI stages and scroll settings into the active profile
- Session D-Bus service with revision-checked configuration updates plus a
  PySide6 GUI (overview, buttons, DPI, scroll, lighting, power, profiles)
- AppImage packaging with host integration install/uninstall

### Required OpenRazer

The custom OpenRazer `add-razer-naga-v3-pro-support` baseline at commit
`2416bfebf0175db6aae519a450f55fe9eba255e9` (see
`docs/hardware-validation.md` for the tested package version). Without this
baseline the Naga V3 Pro is not recognized and the service stays `absent`.

### Known behavior

- Driver mode `3:0` is required for mapped button events; the mouse
  sometimes silently regresses to `0:0` (observed after idle periods),
  which suppresses F13-F18 and side-grid codes until the mode is reasserted
- Stale kernel pressed-state (a lost release) blocks session startup at the
  held-key gate; physically tapping the held button clears it
- Scroll acceleration and Smart Reel ship off by default; enable them on the
  Scroll page if wanted
