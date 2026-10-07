# Integration Findings

Snapshot date: 2026-09-20.

These findings combine upstream source inspection, checks against the running
API, and the project's earlier wired, HyperSpeed, and side-plate hardware test
records. Physical behavior still needing a reproducible capture is listed
separately.

## OpenRazer Baseline

Naga V3 Pro support is not in OpenRazer master or a released OpenRazer version.
It is currently proposed by open, unmerged
[PR #2904](https://github.com/openrazer/openrazer/pull/2904) at commit
`7a6d39784cfc22c07205a8e43f5f64cf03399710`.

The inspected host runs a local `3.12.1.pr2904.fix1` build derived from that
commit. Its fixes add retry/readiness and shutdown behavior not represented by
the daemon's reported version, which remains `3.12.1`.

The current host baseline is `3.12.1.pr2904.fix2-1` at fork commit
`26b0eeb5ed70d638fa3528851adcd5e58369a7f5` (branch
`test-pr-2904-edualb`), which adds probe/mouse-activity lifetime fixes over
the PR head `7a6d39784cfc22c07205a8e43f5f64cf03399710`. This is the revision
pinned in `buildpython/openrazer_packages/pin.conf` for optional CI-built Arch
release assets; older release tags may lack them. Earlier complete
hardware validation used the custom `add-razer-naga-v3-pro-support` branch at
known-good commit `2416bfebf0175db6aae519a450f55fe9eba255e9`, packaged as
`3.12.4.nagav3.1-9`.

Using a custom OpenRazer baseline is intentional for this project. Therefore:

- no released minimum OpenRazer version can currently be declared
- kernel module, daemon, Python client, udev rules, and generated metadata must
  come from one compatible build
- runtime support must be detected by VID/PID and D-Bus introspection, not by
  version string
- upstream PR movement must be rechecked before packaging or release

The unmerged status does not block development or personal use on the current
test system. Release documentation must pin the exact custom revision or a
future released version that provides the same capabilities and recovery
behavior.

Focused daemon/pylib tests pass on the fix2 baseline (55 tests run during the
Arch package build), but long-term idle/wake hardware acceptance for fix2 is
not yet recorded.

The optional prerequisite installer now recognizes only a consistently stamped
exact pinned package cohort as known inventory. Older fix1/mixed/unstamped or
other builds are **UNVERIFIED**, not unsupported by a source PID grep or daemon
version. It checks host import discoverability without contacting OpenRazer or
devices; runtime capabilities/recovery remain the application's authority.
Ordinary app installs never fetch the optional helper or modify OpenRazer.
Explicit opt-in validates the complete three-package manifest, tagged source
pin, hashes, archive metadata/source stamps, dependency links, and builder Python
minor bounds and matching Python package paths before sudo, using isolated
`/usr/bin/python3` rather than a virtualenv/PATH alias. It rejects unsafe or
duplicate normalized archive paths and requires `.BUILDINFO` alongside package
metadata. Explicit opt-in reinstalls all three archives even at the same version
in one interactive pacman transaction and enables
only user units without live activation. Reboot/re-login and exact-pin natural
idle/wake verification remain pending, not implied by installer/fake-test success.
See [release prerequisites](release-notes.md#required-openrazer) for the narrow
experimental Arch support, provenance limits, native-build route, and rollback.

## OpenRazer Device Classes

The proposed daemon hierarchy is:

```text
RazerDevice
  -> RazerDeviceBrightnessSuspend
    -> RazerNagaV2ProWired
      -> RazerNagaV3ProWired       1532:00E7
        -> RazerNagaV3ProWireless  1532:00E8
```

Verified constants:

| Capability | Value |
| --- | --- |
| Maximum DPI | 50,000 |
| DPI stages | one-based active index, maximum 5 stages |
| DPI hardware range | 100 to 50,000 per axis |
| Poll rates | 125, 500, 1000 Hz |
| Matrix | 1 x 3 thumb-grid zone |
| Scroll protocol | version 2 |
| Scroll modes | tactile, free spin, precision tactile |
| Driver mode | enabled |

The generic OpenRazer Python `RazerMouse` class is used. There is no
Naga-specific client class and there is no button-remapping D-Bus API.

## Verified D-Bus And Python API

OpenRazer uses service `org.razer`. A device is exposed at
`/org/razer/device/<serial>`. The APIs below are D-Bus methods, not D-Bus
properties.

### Device And Lifecycle

Interface `razer.device.misc`:

```text
getSerial() -> s
getFirmware() -> s
getDeviceName() -> s
getDeviceType() -> s
getDriverVersion() -> s
getVidPid() -> ai
getDeviceMode() -> s
setDeviceMode(y, y)
getDeviceImage() -> s
getRazerUrls() -> s
hasMatrix() -> b
getMatrixDimensions() -> ai
hasDedicatedMacroKeys() -> b
suspendDevice()
resumeDevice()
getPollRate() -> i
setPollRate(q)
```

`hasDedicatedMacroKeys()` is true, but `razer.device.macro` is not exposed.
Treat it only as a layout hint. The inherited image is for the Naga V2 Pro and
must not be used as a model identifier.

### DPI

Interface `razer.device.dpi`:

```text
maxDPI() -> i
getDPI() -> ai
setDPI(q x, q y)
getDPIStages() -> (y active, a(qq) stages)
setDPIStages(y active, a(qq) stages)
```

Python properties are `max_dpi`, `dpi`, and `dpi_stages`. The Python client
accepts values below 100, while the driver clamps them to 100. Validate the
actual hardware range in this application rather than relying on client-side
validation.

There is no direct next-stage command. Stage actions must preserve the stage
list and call `setDPIStages` with a changed active index.

### Power

Interface `razer.device.power`:

```text
getBattery() -> d
isCharging() -> b
getIdleTime() -> q
setIdleTime(q seconds)
getLowBatteryThreshold() -> y
setLowBatteryThreshold(y percentage)
```

The driver clamps idle time to 60 through 900 seconds. The tested low-battery
setter supports thresholds only through 25%; a 31% test quantized an existing
30% setting to 25%. Battery and charging are exposed on both device classes.
Charge-light methods are not exposed.

### Mechanical Scroll

Interface `razer.device.scroll`:

```text
getScrollMode() -> y
setScrollMode(y)
getScrollModeOptions() -> as
getScrollAcceleration() -> b
setScrollAcceleration(b)
getScrollSmartReel() -> b
setScrollSmartReel(b)
```

Mode values are `0=tactile`, `1=free_spin`, and `2=precision_tactile`.
Acceleration and Smart Reel are Boolean in the current backend; no tunable
parameters are exposed.

### Lighting

Verified zones and method support:

| Zone | Effects | Brightness |
| --- | --- | --- |
| thumb-grid/chroma | off, static, spectrum, reactive, random/single/dual breathing, custom frame | yes |
| logo | off, static, spectrum, reactive, wave, random/single/dual breathing | yes |
| scroll wheel | off, static, spectrum, reactive, wave, random/single/dual breathing | yes |

The 1 x 3 matrix represents the thumb-grid. Upstream discussion reports that
only the 12-button plate is illuminated. OpenRazer exposes no side-plate
identity method, so the UI must not infer plate presence from lighting APIs.

Effect getter values are daemon persistence/cache state, not guaranteed
hardware readback. RGB channels are bytes, brightness is 0 through 100, wave
directions are 1 and 2, and reactive speeds are the OpenRazer values 1 through
4.

## Runtime API Behavior

Root object `/org/razer` exposes:

```text
razer.devices.getDevices() -> as
razer.devices.device_added signal
razer.devices.device_removed signal
```

Signals contain no device argument, so clients must rescan. The Python
`DeviceManager` captures a list only in its constructor and does not subscribe
or refresh. Reconstruct it after add/remove and after `org.razer` changes owner.

There are no value-change signals for DPI, power, lighting, or scroll state.
Use conservative refreshes after writes and a slow battery refresh only while
the GUI is interested. Do not continuously poll all hardware values.

The wireless implementation and local logs show normal command latency around
100 ms and possible timeouts while asleep. Upstream PR behavior includes a
daemon startup/restart stall when the mouse is asleep. The local OpenRazer fix
adds bounded device-readiness retries, but the application must still tolerate
an unavailable or restarting daemon.

## Observed Input Topology And Controls

The attached `1532:00E8` receiver exposed one USB device with four interfaces.
Event numbers are deliberately omitted because they are unstable.

| USB interface | Event role and static capabilities |
| --- | --- |
| `00` | pointer: X/Y, vertical and horizontal wheel including high-resolution axes, five normal mouse buttons, F15, F16 |
| `01` | hybrid: broad keyboard range, mouse buttons, pointer/wheel axes, scan codes, LEDs, ABS_VOLUME |
| `02` | keyboard: broad keyboard range including F13-F24 and KPSLASH, scan codes, LEDs |
| `03` | hidraw only; ignore in this application |

All three event nodes shared the same physical USB ancestor, serial, and device
name. They were distinguishable by USB interface number and capabilities. The
wired `1532:00E7` transport was also observed with four HID interfaces and
three event interfaces. Its HID report descriptor lengths differ from the
wireless transport, so interface routing must not be assumed identical without
capture evidence.

Both transports report the same real serial. Connecting the cable while the
HyperSpeed receiver remains attached makes both USB devices appear, but they
collide because OpenRazer uses the serial as its D-Bus object path and lookup
identity. v0.1 must require one transport at a time and report the dual-attached
state rather than choosing one silently.

The proposed OpenRazer driver rewrites special reports in driver mode:

| Physical function | Linux key |
| --- | --- |
| DPI up | F13 |
| DPI down | F14 |
| wheel tilt left | F15 |
| wheel tilt right | F16 |
| ring-finger/Hypershift control | F17 |
| rear top/AI button | F18 |

Existing hardware tests captured the following mappings from all three event
interfaces with the 12-button plate on both wired and HyperSpeed transports:

| Physical function | Wired | HyperSpeed |
| --- | --- | --- |
| DPI up | `KEY_F13` | `KEY_F13` |
| DPI down | `KEY_F14` | `KEY_F14` |
| wheel tilt left | `KEY_F15` | `KEY_F15` |
| wheel tilt right | `KEY_F16` | `KEY_F16` |
| ring-finger/Hypershift control | `KEY_F17` | `KEY_F17` |
| side buttons 1 through 10 | `KEY_1` through `KEY_0` | `KEY_1` through `KEY_0` |
| side button 11 | `KEY_MINUS` | `KEY_MINUS` |
| side button 12 | `KEY_EQUAL` | `KEY_EQUAL` |

Wheel tilt produced only the F-key event; no duplicate `REL_HWHEEL` event was
observed. HyperSpeed tests additionally found `KEY_1` through `KEY_6` in
physical order on the 6-button plate, and `BTN_EXTRA` then `BTN_SIDE` on the
front and rear controls of the 2-button plate. Every tested plate control had
clean press and release transitions. The 12-button plate is illuminated; the
6- and 2-button plates are unlit by design.

### Full 12-Button Signature Capture (HyperSpeed, 2026-09-28)

A guided read-only capture resolved the remaining per-interface and scan
signatures for the HyperSpeed 12-button plate. The production translation
table carries all 19 controls from the sanitized fixture:

| Logical control | Interface | `MSC_SCAN` | Linux key |
| --- | --- | ---: | --- |
| DPI up | `01` | 458856 | `KEY_F13` (183) |
| DPI down | `01` | 458857 | `KEY_F14` (184) |
| Ring finger | `01` | 458860 | `KEY_F17` (187) |
| Top front | `01` | 458836 | `KEY_KPSLASH` (98) |
| Top rear | `01` | 458861 | `KEY_F18` (188) |
| Wheel tilt left | `00` | none | `KEY_F15` (185) |
| Wheel tilt right | `00` | none | `KEY_F16` (186) |
| Side 1 through 10 | `02` | 458782-458791 | `KEY_1` through `KEY_0` (2-11) |
| Side 11 | `02` | 458797 | `KEY_MINUS` (12) |
| Side 12 | `02` | 458798 | `KEY_EQUAL` (13) |

A 2026-09-28 wired capture produced identical signatures for every 12-button
control, so both transports share the table. The same day's alternate-plate
captures found `KEY_1` through `KEY_6` (scans 458782-458787, interface `02`)
for the 6-button plate and `BTN_EXTRA` front / `BTN_SIDE` rear (scans
589829/589828, interface `00`) for the 2-button plate, on HyperSpeed. Wired
alternate-plate signatures remain uncaptured.

### 12-Button First-Slice Captures

A read-only capture on 2026-09-20 recorded the first-slice controls on
HyperSpeed with the 12-button plate. A separate wired capture on 2026-09-23
confirmed the same signatures for `1532:00E7`. Each control appeared on USB
interface `01` with a clean press/release pair and no duplicate sibling report:

| Logical control | `MSC_SCAN` | Linux key |
| --- | ---: | --- |
| DPI up | 458856 | `KEY_F13` (183) |
| DPI down | 458857 | `KEY_F14` (184) |
| Ring finger | 458860 | `KEY_F17` (187) |

The fixtures contain only this sanitized signature data. Full local captures
remain untracked because they can contain incidental input activity.

## evdev And uinput Conclusions

An evdev grab is exclusive for an entire node. Selective suppression of one key
is impossible. If a mapped control is on a node, clone and forward all
unhandled events from that node through uinput.

Linux input events are stateful and packetized by `SYN_REPORT`. Process complete
frames in order. On `SYN_DROPPED`, ignore through the next `SYN_REPORT` and
query current state. python-evdev does not provide complete policy-level
recovery for the application's held mappings.

Loop prevention must primarily require a physical matching USB parent. Virtual
uinput devices live under `/sys/devices/virtual/input` and do not have one.
Names and `phys` markers are secondary diagnostics, not the trust boundary.

Input Remapper confirms that preserving source identity, input properties, and
capabilities matters for libinput/hwdb behavior. Its source also demonstrates
the need for forwarding devices after grabbing. Naga Control should implement
its own smaller frame-ordered pipeline and explicitly handle `SYN_DROPPED`,
held-output reference counts, and fail-open cleanup.

## Permissions Observed

The OpenRazer udev rule assigns matching Razer `usb`, `hid`, and `input` nodes
to its package group. The current user can read all Naga event nodes through
that group.

`/dev/uinput` is `root:root` and mode `0660` on the inspected host, with an ACL
granted through a standard `TAG+="uaccess"` rule installed by desktop software.
This validates an active-session user-service model without root.

The project udev rule:

- grants `uaccess` only to event nodes under the two supported USB IDs
- grants active-session access to `/dev/uinput`
- does not alter OpenRazer's ownership or group
- does not grant access to unrelated keyboards or mice

## Feature Ownership

| Feature | Owner |
| --- | --- |
| discovery of OpenRazer device/capabilities | application OpenRazer adapter |
| DPI, stages, polling | OpenRazer |
| battery, charging, idle timeout, low threshold | OpenRazer |
| mechanical scroll settings | OpenRazer |
| lighting | OpenRazer |
| physical button observation | evdev adapter |
| source suppression and passthrough | evdev/uinput adapters |
| replacement keyboard/mouse output | uinput adapter |
| button-to-device actions | application services calling OpenRazer port |
| profiles and side-plate selection | application/config service |

## Deliberately Unsupported In v0.1

- arbitrary Razer devices
- raw HID access
- application-triggered profiles
- command or shell-script mappings
- macro recording/playback
- automatic plate switching without proven hardware evidence
- Bluetooth transport not represented by `00E7` or `00E8`
- OpenRazer charge-light controls, which are not exposed for this model

## Sources

- [Naga V3 Pro support tracker](https://github.com/Rainexn0b/openrazer/blob/c92d148a5a3bcba50d855dcc06c375307439c4d0/docs/naga-v3-pro-support.md)
- [Naga V3 Pro upstream branch testing](https://github.com/Rainexn0b/openrazer/blob/c92d148a5a3bcba50d855dcc06c375307439c4d0/docs/naga-v3-pro-upstream-branch-testing-2026-09-12.md)
- [OpenRazer PR #2904](https://github.com/openrazer/openrazer/pull/2904)
- [OpenRazer PR device classes](https://github.com/openrazer/openrazer/blob/7a6d39784cfc22c07205a8e43f5f64cf03399710/daemon/openrazer_daemon/hardware/mouse.py)
- [OpenRazer PR scroll API](https://github.com/openrazer/openrazer/blob/7a6d39784cfc22c07205a8e43f5f64cf03399710/daemon/openrazer_daemon/dbus_services/dbus_methods/mouse_scroll_wheel.py)
- [Linux input event protocol](https://www.kernel.org/doc/html/latest/input/event-codes.html)
- [Linux uinput documentation](https://www.kernel.org/doc/html/latest/input/uinput.html)
- [python-evdev API](https://python-evdev.readthedocs.io/en/latest/apidoc.html)
- [pyudev guide](https://pyudev.readthedocs.io/en/latest/guide.html)
- [udev rules manual](https://man7.org/linux/man-pages/man7/udev.7.html)
