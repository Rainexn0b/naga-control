# Release Notes

The root [changelog.md](../changelog.md) is the authoritative versioned release
history. It contains Unreleased changes and the 0.4.0, 0.3.0, 0.2.0, and 0.1.4 entries.
Release publishing extracts only the
matching version section, not this overview or the entire changelog.

## Required OpenRazer

The prerequisite is unchanged: the custom
`add-razer-naga-v3-pro-support` baseline at commit
`2416bfebf0175db6aae519a450f55fe9eba255e9`, tested as package
`3.12.4.nagav3.1-9`. No released upstream OpenRazer minimum replaces this
baseline. The kernel module, daemon, Python client, udev rules, and metadata
must come from a compatible build; a daemon version string alone is not proof
of support. Without the required support the mouse is not recognized and the
service stays `absent`.

See [Integration Findings](integration-findings.md) for the custom-build context
and [Hardware Validation](hardware-validation.md) for dated test environments
and results. Run neither the GUI nor the service as root.

## Hardware Limits

- Only Razer Naga V3 Pro wired `1532:00E7` and HyperSpeed `1532:00E8` are
  supported. Use one transport at a time; simultaneous attachment causes an
  OpenRazer serial-identity conflict. Bluetooth and other devices are excluded.
- The 12-button plate has captured signatures for both transports. The 6- and
  2-button tables are HyperSpeed-only; wired alternate-plate signatures remain
  uncaptured and are not enabled.
- Attached-plate selection is manual under **Device > Profiles** in 0.4.0.
  Editing every plate's bindings does not detect the attached plate or enable
  an uncaptured wired mapping. The 6- and 2-button plates are unlit by design.
- Primary clicks and wheel scrolling remain passthrough, not editable bindings.
- Driver mode `3:0` is required for mapped events. Idle can silently revert it
  to `0:0`, suppressing special-button and grid events until it is reasserted.
- Stale kernel pressed-state can block the held-key startup gate. Physically
  tapping the affected control clears a lost release.
- Scroll acceleration and Smart Reel default to off; enable them in Settings
  if wanted. Settings Apply is atomic for the configuration document, not for
  the sequence of OpenRazer hardware writes.
- v0.4.0 includes an experimental service-wide firmware/driver mode policy in
  configuration, but no tray switch. Held-output and wireless wake safety
  checks are inconclusive; do not rely on firmware-mode persistence for daily
  use until those checks pass. Software mode remains the default.
- Guided source-only mode handoffs passed on wired and HyperSpeed, but held-output
  ordering, natural wireless sleep/wake, and recovery from a real device-mode
  drift remain unverified. Consult [Hardware Validation](hardware-validation.md)
  for dated evidence and safety instructions; v0.4.0 does not claim full
  hardware validation.

## Historical Notes

GitHub publication dates in UTC are **2026-09-28** for
[v0.1.4](https://github.com/Rainexn0b/naga-control/releases/tag/v0.1.4) and
**2026-09-29** for
[v0.2.0](https://github.com/Rainexn0b/naga-control/releases/tag/v0.2.0).
These historical releases and tags were verified before preparing 0.3.0.

Earlier versions of this document, also copied into GitHub release bodies,
listed development iterations 0.1.0 through 0.1.3 as separate headings. Those
changes are now consolidated into the first published release, 0.1.4. The
unpublished 0.1.5 fix that isolates the host OpenRazer Python package from
bundled `evdev` is recorded under 0.2.0, where it was actually shipped.
Removing duplicated history here does not change the existing GitHub release
bodies or imply that those intermediate versions were published.
