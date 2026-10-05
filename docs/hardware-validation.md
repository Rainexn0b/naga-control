# Hardware Validation

Earlier OpenRazer work tested both transports and all three side plates. Those
records establish the control mappings below, but they do not retain all the
per-interface and `MSC_SCAN` details needed as sanitized automated-test
fixtures. This document separates accepted evidence from the remaining capture
and remapping work.

## First-Slice Validation Status (2026-09-22, HyperSpeed, 12-button, Wayland)

The complete HyperSpeed first slice passed with the real service composition
and `tests/hardware/test_first_slice.py`. Because test-process output is not
visible while an API-driven command is running, the passing run used an
unbuffered transient user service and synchronized each physical press only
after the corresponding journal prompt appeared. The test supports a longer
interactive window through `NAGA_HARDWARE_PRESS_WINDOW`.

Verified end to end on hardware:

- a synchronized read-only capture confirmed F13, F14, and F17 on interface
  `01`, including F17's fixture signature `MSC_SCAN 458860 + KEY_F17`
- F13 traversed the grabbed evdev reader, mapping planner, action executor, and
  OpenRazer adapter, changing the real active DPI stage from 3 to 4
- F14 followed the same path and restored the active stage from 4 to 3
- F17 emitted exactly `KEY_LEFTALT` down plus `SYN_REPORT`, remained held while
  physical repeat reports arrived, and emitted exactly `KEY_LEFTALT` up plus
  `SYN_REPORT` on release
- forwarding-proxy creation, udev readiness, and grab acquisition worked
- teardown removed all virtual devices, reported no session errors, and
  released the physical grab, verified by an immediate test-side `EVIOCGRAB`

Passing-run environment:

```text
date: 2026-09-22
kernel: 7.2.4-1-cachyos
OpenRazer: 3.12.1.pr2904.fix1 packages; daemon reports 3.12.1
python-evdev: 2.0.0
mouse firmware: v1.0
transport: HyperSpeed 1532:00E8
plate: 12 button
OpenRazer driver mode: 3:0
desktop: Wayland
```

Root causes found and fixed during validation:

- udev stores `NAME`/`PHYS` database properties with surrounding quotes; the
  proxy readiness waiter now reads unquoted sysfs `name`/`phys` attributes
- uinput-created event nodes had no test-observer ACL; the scoped udev rule now
  grants `uaccess` to `ATTRS{name}=="Naga Control *"` event nodes
- the mouse had silently left driver mode (`0:0`), which prevents F13/F14/F17
  emission; the hardware test now verifies and restores mode `3:0`
- the OpenRazer adapter required exact built-in `int` identifiers and rejected
  the client's `dbus.Int32` VID/PID values, leaving the backend unsupported and
  making queued DPI actions no-ops
- the adapter expected string scroll modes, while the inspected OpenRazer
  client reads and writes numeric modes `0`, `1`, and `2`; the adapter now
  translates those values at its boundary
- standalone modifier mappings forwarded physical repeat reports; modifier
  repeats are now suppressed so F17 produces held LEFTALT down/up semantics
- the hardware test leaked observer descriptors during polling and cancellation;
  it now closes them deterministically before virtual-device teardown
- the production CLI did not compose the existing OpenRazer lifecycle monitor;
  daemon ownership and OpenRazer device changes now fence stale actions and
  rescan hardware without rebuilding evdev forwarding
- uinput creation triggered the broad input udev monitor, which repeatedly
  rebuilt an unchanged topology; the supervisor now ignores snapshots equal to
  the last successfully applied topology while retaining retry after failures
- a service started while the wireless mouse was asleep could not reacquire an
  OpenRazer client after wake; the adapter now retains the validated topology,
  reacquires before a safe new mutation, and publishes the resulting state
- source activation originally happened only after the reader task was
  scheduled, so an existing `EVIOCGRAB` owner left shared keyboard/mouse uinput
  devices alive; activation is now part of synchronous session startup and a
  grab conflict tears down the complete session

The event-node inode remained stable across a same-value driver-mode write, and
the grabbed reader delivered frames once the backend and test synchronization
problems were corrected. The earlier stale-fd hypothesis was not reproduced.

Additional HyperSpeed lifecycle validation passed with the production CLI:

- stopping OpenRazer advanced the service generation from 2 to 4 and recovered
  automatically after D-Bus activation restarted the daemon; the physical node
  and all three virtual-device inodes remained unchanged, and F13/F14 still
  changed stage 3 to 4 and back
- unplugging the receiver while F17 was held emitted exactly LEFTALT down and
  LEFTALT up before virtual-device removal; the service reached `absent`, then
  rebuilt the session and returned to `available` after receiver reconnect
- a 60-second temporary idle timeout produced a visually confirmed wireless
  sleep; after starting the service asleep, wake plus the next service-delivered
  DPI action reacquired OpenRazer, changed state from `unavailable` generation 2
  to `available` generation 3, and restored stage 4 to 3
- OpenRazer can briefly handle the first DPI control in firmware immediately
  after wake, before it reapplies driver mode and F13/F14 return to evdev; the
  subsequent service-delivered action completed recovery
- SIGKILL of the live service immediately removed all three uinput devices and
  let a new process acquire the physical grab, relying only on kernel fd cleanup
- with a separate process owning the physical grab, startup reported the
  underlying `EBUSY` as a source activation failure, exited nonzero, and left no
  partial forwarding proxy, keyboard, or mouse uinput device

Passthrough-scope observation found ordinary X/Y motion and left/right/middle
buttons on ungrabbed interface `00`. Wheel tilt emitted clean F15/F16 down/up
only on interface `00`, and the tested 12-button thumb-grid key emitted clean
KEY_1 down/up on ungrabbed interface `02`. Neither appeared on the interface
`01` forwarding proxy. A live HyperSpeed proxy audit confirmed its bus/vendor/
product/version, input properties, and key, relative, absolute, and scan
capabilities match the physical interface `01` snapshot. Udev classified both
as keyboard and mouse; their libinput device-group identifiers differ because
the proxy has its own `phys`. Broader passthrough checks across every control
and desktop context remain. Input Remapper remained stopped throughout.

## Full 12-Button HyperSpeed Plate (2026-09-28)

A guided read-only capture resolved every remaining 12-button control signature
on HyperSpeed. `top_front` is `KEY_KPSLASH` (code 98, scan 458836) and
`top_rear` is `KEY_F18` (code 188, scan 458861), both on interface `01` — the
two longest-standing mapping unknowns are now verified. Wheel tilt emits
`KEY_F15`/`KEY_F16` on interface `00` with no `MSC_SCAN`, so their signatures
match on code alone. Side buttons 1 through 12 sit on interface `02` as codes
2 through 13 with scans 458782 through 458791 and 458797/458798; scans
458792-458796 are simply unused by the hardware. The sanitized fixture is
`tests/fixtures/hyperspeed-12-full.json` and the production table now carries
all 19 controls for `00E8`; wired remains first-slice-only until captured.

With all three interfaces grabbed and proxied for the first time:

- pointer motion (tens of thousands of events), left/right/middle clicks, and
  vertical wheel including `REL_WHEEL_HI_RES` accumulation (±120 per detent)
  forwarded through the interface `00` proxy; the cursor felt normal
- wheel tilt dispatched as `wheel_tilt_left/right` and, having no binding,
  forwarded unchanged through the proxy
- all twelve side buttons dispatched in order; the virtual keyboard emitted
  exactly `KEY_1` through `KEY_0`, `KEY_MINUS`, and `KEY_EQUAL` down/up while
  the interface `02` proxy stayed completely silent
- the opt-in first-slice test re-passed under the three-grab configuration
  (F13 3->4, F14 4->3, held F17 -> LEFTALT down/up, no session errors)
- teardown removed all five virtual devices and released every physical grab

The replacement virtual keyboard now emits a fixed 73-token key set (all
modifiers, digits, `minus`/`equal`, letters, navigation, and F1-F12) instead
of only `left_alt`; unmapped tokens still fail closed at creation.

The mouse left driver mode `3:0` silently twice more during these runs
(overnight idle). Each regression suppressed F13-F18 and grid codes while
plain clicks kept working, which can masquerade as a remapping failure; the
test harness re-asserts mode `3:0` before action checks.

## Wired First Slice And Transport Switch (2026-09-23)

With the HyperSpeed receiver removed first, a read-only capture of the wired
`1532:00E7` 12-button plate found F13, F14, and F17 exclusively on interface
`01`, with `MSC_SCAN` values 458856, 458857, and 458860 respectively. Each had
one down/up pair; F17 also had physical repeat frames. The sanitized wired
signature fixture is `tests/fixtures/wired-12-first-slice.json`. Other wired
controls have not been added to the remapping table without individual captures.

The opt-in `tests/hardware/test_first_slice.py` passed with the real wired
service composition: F13 moved DPI stage 3 to 4, F14 restored 4 to 3, and F17
produced exactly LEFTALT down/up plus two synchronization frames, with no
virtual-keyboard repeats. There were no reader errors. Teardown removed the
proxy and replacement devices and released the physical grab.

The production service then started on wired (`available`, generation 2). On
cable removal, it reported `absent` (generation 4) and destroyed the virtual
devices. Inserting only the receiver rebuilt the HyperSpeed proxy. OpenRazer
initially reported the wireless mouse serial was not ready because the mouse
was asleep; the service temporarily reported `unsupported` while the daemon
retried. After waking the mouse, OpenRazer published the device, the same
service reached `available` on HyperSpeed (generation 6), and F13/F14 again
changed stage 3 to 4 and back without restarting Naga Control.

The mouse was left on HyperSpeed in driver mode `3:0`, at stage 3 of
(400, 800, 1600, 3200, 6400), with its 300-second idle timeout restored.
Input Remapper remained stopped. Remaining hardware checks include alternate
plates on wired, broad passthrough across desktops, and other scenarios listed
below; this does not claim full release readiness.

## Hardware-Backed Settings Application (2026-09-28)

The service now applies desired profile settings through OpenRazer whenever a
session is built: after startup, after every configuration or profile change,
and after reconnect-driven topology rebuilds. Writes run in a fixed order —
DPI stage list with active index, scroll mode, scroll acceleration, Smart
Reel, idle timeout, low-battery threshold, poll rate, then the three lighting
zones (thumb grid via the matrix FX and `device.brightness`, logo and scroll
wheel via `fx.misc`) with `off/static/spectrum/breathing/reactive/wave`
mapping onto `none/static/spectrum/breath_single/reactive/wave`. Each step's
failure is collected instead of aborting the rest. The D-Bus snapshot exposes
`settings_failures`, and observed state optionally includes poll rate,
battery percent, charging, and firmware version. `poll_rate` is a new
optional profile field validated to 125/500/1000 with a 1000 default so
existing documents keep parsing.

Validated on hardware: a profile with a custom three-stage DPI list (active
2), `precision_tactile`, acceleration and Smart Reel off, idle 120, and
threshold 15 was applied by the running service with no failures; direct
OpenRazer reads confirmed every value. A second run applied poll rate 500 and
distinctive lighting — thumb-grid breathing red at 60, logo wave at 45,
scroll-wheel static `(0,200,30)` at 30 — with every zone's effect, brightness,
and color confirmed by readback. Original mouse state was restored afterward.

The held-key startup gate blocked two starts because the kernel retained
stale pressed-state for `BTN_LEFT` and side button 4 (lost releases from
earlier sessions); physically tapping each control cleared it, and the
service then started cleanly. This is a recovery step worth automating or
surfacing in diagnostics later.

## Alternate Plates And Wired Full Table (2026-09-28)

Guided read-only captures completed the remaining signature work. The
6-button plate maps buttons 1 through 6 to `KEY_1` through `KEY_6` on
interface `02` with scans 458782 through 458787 — the same physical scan codes
as the 12-button grid's first six columns. The 2-button plate maps its front
control to `BTN_EXTRA` (276, scan 589829) and its rear control to `BTN_SIDE`
(275, scan 589828), both on interface `00`. Sanitized fixtures are
`tests/fixtures/hyperspeed-6-plate.json` and `hyperspeed-2-plate.json`; the
common controls stay identical across plates, so each plate table carries the
seven shared controls plus its own.

A wired full-plate capture found signatures identical to HyperSpeed for every
control: tilt (no scan) on `00`, `KPSLASH`/`F18` on `01`, and the side grid on
`02` with the same scans. `tests/fixtures/wired-12-full.json` carries all 19
controls and the wired table now matches HyperSpeed for the 12-button plate.

Hardware validation with the production service:

- with a plate-2 profile the service correctly opened only interfaces `00`
  and `01`; the front control emitted exactly `BTN_BACK` and the rear exactly
  `BTN_FORWARD` through the virtual mouse with no proxy leak — the first
  hardware validation of the virtual-mouse path — and F13 still changed the
  DPI stage on the alternate plate
- the opt-in first-slice test passed on wired with all three interfaces
  grabbed (F13 3->4, F14 4->3, held F17 -> LEFTALT, no session errors, clean
  teardown of every proxy and grab)

Wired 6- and 2-button plates remain uncaptured and stay out of the wired
translation table until evidence exists.

## Desktop Passthrough Soak (2026-09-28, HyperSpeed, 12-button, Wayland)

Interactive desktop soak over the live service with all three interfaces
grabbed and proxied (fresh config defaults, then revision-checked
`ApplyConfiguration` for scroll settings):

- X/Y motion incl. fast flicks and slow precise movement: correct
- left, double, right, and middle click: correct
- vertical wheel, detents and fast flicks: correct after the finding below
- wheel tilt left/right: dispatched and forwarded, nothing stuck
- side 1-10 typed `1234567890`, side 11/12 typed `-`/`=` via virtual keyboard
- dpi_up/dpi_down stepped hardware DPI stages; ring-finger held ALT+Tab
- combined hold/release orderings left no stuck keys; Wayland lock/unlock
  kept forwarding working
- journal clean (no errors, warnings, held-key trips); exactly the expected
  five virtual devices during the run; snapshot `available`, no settings
  failures; clean teardown (no proxies, grabs, or services left)

Finding: first-run defaults shipped scroll acceleration and Smart Reel ON,
which the user perceived as the wheel being "stuck in auto-fast scroll"; DPI
buttons do not toggle it by design. Applied `acceleration=false,
smart_reel=false` over IPC (the Scroll-page path) and the user confirmed the
wheel felt normal. The shipped `default_configuration()` was changed to
`acceleration=False, smart_reel=False` so first run matches the standard
tactile wheel.

Latency measurement and Xorg/XWayland/virtual-console sessions were skipped
by decision (2026-09-28): the project targets the owner's Wayland desktop
only, and extended daily use including gaming showed no perceptible proxy
latency.

## Existing Baseline Evidence

The custom OpenRazer `add-razer-naga-v3-pro-support` baseline at commit
`2416bfebf0175db6aae519a450f55fe9eba255e9` was tested as package version
`3.12.4.nagav3.1-9`. Relevant results:

| Area | Wired `00E7` | HyperSpeed `00E8` |
| --- | --- | --- |
| discovery and daemon restart | pass | pass |
| DPI, stages, poll rate, RGB, and scroll controls | pass | pass |
| 12-button plate input mapping | pass | pass |
| suspend/resume | pass | pass |
| 6- and 2-button plate input mapping | not recorded | pass |

The 12-button plate produced `KEY_F13` through `KEY_F17` for DPI, wheel tilt,
and Hypershift on both transports. Its side controls produced `KEY_1` through
`KEY_0`, `KEY_MINUS`, and `KEY_EQUAL`. No duplicate `REL_HWHEEL` accompanied
wheel tilt. Over HyperSpeed, the 6-button plate produced `KEY_1` through
`KEY_6`, and the 2-button plate's front and rear controls produced `BTN_EXTRA`
and `BTN_SIDE`. All recorded plate controls had clean press/release transitions.

The 12-button plate illuminates; the 6- and 2-button plates are unlit by design.
Clean `KEY_F17` transitions were also confirmed after wireless idle/wake with
driver mode restored. The rear top button's proposed `0xD2` to `KEY_F18`
translation was not exercised and remains unverified.

## First-Slice Fixture Capture

Read-only 12-button captures resolved the first-slice source signatures on
HyperSpeed (2026-09-20) and wired (2026-09-23). `KEY_F13` (183), `KEY_F14`
(184), and `KEY_F17` (187) appeared only on USB interface `01`, with `MSC_SCAN`
values 458856, 458857, and 458860 respectively. Each had a clean press/release
pair and no duplicate report on interfaces `00` or `02`.

The sanitized three-control fixtures are under `tests/fixtures/`; full captures
are intentionally kept out of tracked files.

## Safety Rules

- Stop Input Remapper before grab/proxy testing.
- Keep a second keyboard available during early grab tests.
- Begin with read-only capture and no evdev grabs.
- Never run the GUI as root.
- Redact serial numbers and physical USB port paths from committed fixtures.
- Keep raw captures under ignored `hardware-captures/` until sanitized.
- Test release-all and fail-open behavior before long-running use.

## Environment Record

For each capture, record:

```text
date
kernel version
OpenRazer source revision and local patch identifier
python-evdev version
mouse firmware
transport: wired or HyperSpeed
plate: 2, 6, or 12 button
OpenRazer driver mode
desktop: Wayland, Xorg, or console
```

Do not store the device serial.

## Topology Capture

For both `00E7` and `00E8`, generate reproducible sanitized records that:

1. Enumerate every input child under the matching physical USB parent.
2. Record USB interface number, evdev identity, properties, and capabilities.
3. Record the state while awake, asleep, powered off, and after reconnect.
4. Confirm virtual devices have no matching USB parent.
5. Confirm receiver-present/mouse-asleep is distinguishable from USB removal.

Expected wireless baseline is three evdev nodes on interfaces `00`, `01`, and
`02`, plus hidraw-only interface `03`. Wired was also observed with four HID
interfaces and three event interfaces, but its report descriptor layout differs.
Any difference is evidence, not an error to hard-code around.

## Control Capture Procedure

Capture complete frames from all sibling event nodes concurrently to turn the
existing mapping evidence into fixtures. For each physical control, perform one
isolated press and release, then one short hold. Record `MSC_SCAN`, `EV_KEY`,
repeat values, and `SYN_REPORT` boundaries.

Use this order for each plate:

```text
left click
right click
middle click
wheel up/down
wheel tilt left/right
front and rear left-edge buttons
ring-finger/Hypershift button
front and rear top buttons
every side-plate button in physical order
```

Repeat the first-slice controls after wireless sleep/wake and after OpenRazer
daemon restart. Capture each transport separately; never leave the receiver
attached during a wired test.

Questions each capture must answer:

- Which USB interface emits each control?
- Does one control appear on more than one event node?
- Does `MSC_SCAN` distinguish otherwise identical key codes?
- What do the front and rear top controls emit, and can `KEY_F18` be verified?
- Do side-plate changes alter capabilities or emit any insertion event?
- Do the 2- and 6-button mappings remain identical over wired mode?
- Does OpenRazer driver mode change any code or interface?

## Plate Validation

Input codes and clean transitions are already established for every plate over
HyperSpeed and for the 12-button plate over wired. Remaining plate validation:

- produce fixture-quality captures with interface and scan signatures
- confirm the 2- and 6-button mappings over wired
- remove and insert the plate while all sibling nodes are monitored
- inspect udev, evdev, and OpenRazer state for a plate-change signal
- verify whether a held side button receives a release when the plate is removed

Until a reliable signal is proven, plate selection remains manual. Optional
inference may narrow candidates only after a uniquely identifying side button
is pressed; it must not silently switch based on static capabilities.

## Passthrough Integrity

When a mapped control forces a node to be grabbed, verify all other behavior
from that node through its proxy:

- X/Y motion and acceleration feel
- left, right, middle, back, and forward buttons
- vertical and horizontal wheel
- high-resolution wheel events and accumulated detents
- key press, release, and repeat
- input properties and libinput/hwdb classification
- lock screen, Wayland, XWayland, Xorg, and virtual console behavior

Measure event latency with and without proxying. The service must not schedule
one async task per individual event.

## Remapping Reliability

Verify these scenarios:

| Scenario | Expected result |
| --- | --- |
| F17 held as LEFTALT | output remains down until physical release |
| profile changes while F17 held | release uses the action resolved on press |
| two controls produce LEFTALT | first release does not release output |
| device unplugged while held | all generated outputs released |
| plate removed while held | generated output released or explicit recovery works |
| service receives SIGTERM | releases, flushes, then ungrabs |
| service receives SIGKILL | kernel drops grabs and physical input resumes |
| uinput write fails | service immediately fails open |
| another process owns grab | clear error, no partial proxy activation |
| synthetic `SYN_DROPPED` | uncertain outputs release, state reconciles |
| daemon-generated virtual event | discovery rejects it |

## OpenRazer Coexistence

While relevant event nodes are grabbed and proxied:

- read and change DPI
- change the active DPI stage repeatedly
- read battery and charging state
- switch all three mechanical scroll modes
- toggle scroll acceleration and Smart Reel
- change each lighting zone
- allow the mouse to sleep and wake
- restart OpenRazer while the mouse is awake and asleep
- switch wireless to wired and back without restarting Naga Control, removing
  the active transport before attaching the other

An evdev grab should not block OpenRazer sysfs/control-transfer operations, but
this must be demonstrated on hardware.

An earlier test already confirmed that attaching both transports causes an
OpenRazer serial collision. Do not repeat that physical test unless OpenRazer's
identity design changes. Simulated discovery of the recorded state must produce
a clear Naga Control conflict without grabbing either transport.

## Device-Mode Handoff (UI-06, Not Yet Validated)

Do not enable the tray firmware/driver switch or rely on experimental firmware
mode for daily use until these opt-in tests have been performed with a second
keyboard available and Input Remapper stopped. Use only one transport at a
time; repeat the sequence separately for `00E7` and `00E8`. Keep the physical
serial and USB path out of committed results.

1. Record the current device mode and DPI/profile state through OpenRazer.
   With the Naga Control service running, hold F17 and request the revisioned
   service-wide `mode = "firmware"` configuration. Confirm the generated
   LEFTALT release, disappearance of all forwarding proxies and grabs, and
   readback `0:0` *in that order*. Test wheel, click, and onboard buttons.
2. Request `mode = "software"`. Confirm readback `3:0` before new forwarding
   proxies and grabs appear, then verify F13/F14 stage changes and held F17
   LEFTALT down/up. Repeat with a queued hardware action and a deliberately
   failed/uncertain OpenRazer write; failed handoffs must stay ungrabbed and
   show desired versus observed/error separately.
3. With firmware requested, test OpenRazer daemon restart, receiver reconnect,
   cable reconnect (receiver removed first), wireless sleep/wake, and service
   restart. Record whether OpenRazer reasserts `3:0`, how soon the service
   detects it, and whether/how it recovers `0:0`. Confirm that no remapping
   session is rebuilt while firmware is requested.
4. Repeat lifecycle tests with software requested. Confirm that uncertain
   mode readback drops grabs and releases held outputs, and that recovery does
   not grab a source before proxy readiness or mode verification. Exercise
   calibration rejection while firmware is requested and check both clean
   shutdown and service crash cleanup.
5. Restore the original mode and user profile settings. Decide with OpenRazer
   ownership evidence whether firmware policy can be maintained through wake
   without an interval of unexpected driver mode. Document any unavoidable
   interval before presenting the tray switch as persistent.

The default test suite uses fakes and must not read or change real device mode.
The guided results below cover only a subset of these checks.

### UI-06 Guided Results (2026-10-04)

- A source-only opt-in test passed the firmware/driver handoff on HyperSpeed
  `00E8` and wired `00E7` separately. Firmware readback confirmed `0:0` after
  release of all source grabs; returning to `3:0` established fresh forwarding
  sessions. Each test restored its initial hardware mode without saving config.
- A test switching modes immediately after service startup exposed a real
  cancellation-before-first-read race: a started reader's task could be
  cancelled without entering its cleanup `finally`, leaving the evdev grab
  alive until process exit. Session teardown now explicitly stops every
  started reader. A fake regression and repeat HyperSpeed handoff passed.
- OpenRazer daemon restart while firmware was requested passed on wired and
  HyperSpeed using the live lifecycle monitor. The service re-read/reapplied
  `0:0` without establishing remapping grabs.
- Wireless idle/wake remains **unverified**. The first guided attempt changed
  the idle timeout to 60 seconds after the mouse had already been idle long
  enough to sleep immediately. A later 75-second attempt observed an
  unavailable mode and no successful lifecycle rescan before its timeout;
  test-output timing did not reliably synchronize the physical wake. This
  neither proves nor rules out recovery after a correctly timed wake. The
  60-second timeout was manually restored to 300 after waking, the mouse's
  original `0:0` mode was confirmed, and the installed user service restarted
  successfully. At the user's request the mouse was then placed in verified
  driver mode `3:0` for daily remapping, with the idle timeout still 300.
  Do not automate this idle test unattended.
- A held physical `KEY_0` and later `BTN_RIGHT` blocked two test activations;
  the no-held-keys gate correctly declined to grab. After tapping/releasing
  those buttons, HyperSpeed handoff passed. Tests of a *generated held output*
  during handoff, uncertain writes, sleep/wake, and reconnect are still needed
  before the tray control is enabled. At the time, no UI-06 AppImage was installed.

### Next Guided Checks

Source-only regression tests now cover recovery from an unavailable startup,
transient mode reads, lost hardware during a device action, and a lifecycle
signal whose provider never completes a rescan. Generated outputs are released
and the worker is fenced before the old session releases its grabs. A later
recovery attempts verified mode/readback and proxy-before-grab startup; an
uncertain mode write is still not retried by periodic polling.

The remaining physical checks require an **interactive terminal**, a backup
keyboard, one transport at a time, the installed Naga Control service stopped,
the GUI quit, and other remappers stopped. The tests refuse to run without a
TTY and `NAGA_UI06_HARDWARE=1`, use only in-memory configuration, and attempt
to restore the original mode on cleanup. Read each test's prompt/timeout notes
before running; do not run these through an API command that hides live output.

```bash
NAGA_UI06_HARDWARE=1 .venv/bin/pytest -m hardware -s tests/hardware/test_ui06_guided.py
NAGA_UI06_HARDWARE=1 .venv/bin/pytest -m hardware -s tests/hardware/test_ui06_sleep.py
```

The first check observes a genuinely held F17-to-LEFTALT output, requires its
release and removal of grabs before the firmware-mode write, then verifies
software mode only after all physical buttons are released. The second waits
for *visually confirmed natural* HyperSpeed sleep; it never changes idle time
and requires an explicit keyboard acknowledgement before waking the mouse.
Neither guided check has passed yet. Restore the installed
user service only after the test has stopped and mode readback is checked;
if the original mode was firmware but daily remapping is desired, explicitly
select driver mode `3:0` through OpenRazer before using the older installed
service. A failed cleanup or lost transport requires manual recovery.

On 2026-10-05, the guided held-F17 check was attempted on HyperSpeed but did
not reach a verified handoff. Two runs timed out at operator prompts. A later
run observed generated LEFTALT down and a held physical F17, then failed its
strict event-order assertion before recording the actual sequence. Another run
found physical F17 held *before* forwarding startup; the no-held-keys safety
gate correctly refused the grab. The test now advances automatically after
LEFTALT down, prints a preparation prompt, and reports sanitized event order
if the handoff assertion fails. No new guided test has passed. The installed
user service was restarted, with OpenRazer reporting available HyperSpeed in
verified driver mode `3:0` and no held physical keys before startup.

Later on 2026-10-05, F17 stopped remapping during normal HyperSpeed use.
OpenRazer read back onboard firmware mode `0:0` despite the service requesting
software mode. The service was running, but its snapshot reported unavailable,
no observed mode, and `hardware topology rescan is pending`. A verified
OpenRazer write restored `3:0`; the service still lacked a forwarding session
until it was restarted with no mouse keys held. After restart its snapshot
reported available, mode ready, and no settings failures; the user confirmed
F17 worked again. The old AppImage process dumped core during shutdown, as it
has on earlier stops. There is no timestamped evidence of the exact trigger
that returned the device to firmware mode. Source-only follow-up fixes a
recovery loop: stopping a session fences the worker, so the next periodic
mode read cannot succeed until the service requests a rescan. A fake-worker
  regression covers that path. v0.4.0 includes the source fix, but physical
  recovery after a mode drift still needs confirmation.

## Exit Criteria For First Slice

The first vertical slice is complete only when:

- exact F13, F14, and F17 source signatures are captured
- F13/F14 reliably clamp through configured DPI stages
- F17 reliably emits held LEFTALT down/up
- normal mouse behavior remains intact on every grabbed node
- sleep/wake and reconnect recover without restarting Naga Control
- disconnect and shutdown produce no stuck keys
- all failures release grabs or clearly leave remapping inactive
