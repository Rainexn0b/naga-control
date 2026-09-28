# Release Notes

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
