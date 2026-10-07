# v0.1 Architecture

This document records the architecture selected after inspecting the current
OpenRazer implementation, the attached wireless device, Polychromatic, and
Input Remapper. It is the implementation contract for v0.1.

## Decision Summary

Use one long-running, unprivileged `systemd --user` service and one optional
PySide6 GUI process. Communicate over the session D-Bus.

```text
PySide6 GUI
    |
    | org.nagacontrol.Service1 (session D-Bus)
    v
Naga Control user service
    |-- application coordinator and profile authority
    |-- mapping engine and held-output state
    |-- OpenRazer adapter -> org.razer on session D-Bus
    |-- pyudev discovery -> physical USB/input hierarchy
    |-- evdev readers -> selected physical event nodes
    `-- uinput outputs -> proxy devices + replacement keyboard/mouse
```

This process boundary is required because mappings must continue when the GUI
is closed. A system service account was rejected for v0.1 because OpenRazer is
a per-user daemon on the session bus. A system daemon would require a second
user-session bridge for every device action and would add failure modes without
improving the first release.

## Authority And State

The service is authoritative for:

- loaded configuration and active profile
- mapping resolution and generated held-key state
- selected side-plate layout
- evdev grabs and all uinput devices
- serialized hardware action requests

OpenRazer/hardware is authoritative for observed device state such as current
DPI, battery, charging, scroll mode, and connection health. The GUI renders a
service snapshot and sends intent. Widget state is never authoritative.

Desired profile settings and observed hardware state must be separate types.
Reconnect applies the desired active profile, then refreshes observed state.

## Runtime Concurrency

Use an asyncio service core:

- pyudev monitor file descriptor registered with the event loop
- one ordered reader task per grabbed evdev node
- one serialized hardware-operation worker
- one session D-Bus service using `dbus-next`
- OpenRazer Python client access isolated behind the hardware adapter

OpenRazer calls can block while the wireless mouse sleeps. They must never run
on the evdev read path or D-Bus event-loop callback. Serialize them through a
bounded worker queue. Recreate OpenRazer client objects after daemon ownership
or device-list changes; `DeviceManager` is a snapshot, not a live collection.

## Device Discovery And Identity

Enumerate initialized `input` devices with pyudev. For each `event*` node:

1. Find its `usb` parent with device type `usb_device`.
2. Require vendor `1532` and product `00e7` or `00e8`.
3. Find the `usb_interface` parent and read `bInterfaceNumber`.
4. Open with evdev and inspect actual capabilities.
5. Group siblings by physical USB ancestor sysfs path for that connection.

Never persist `eventN` or a sysfs path. Persist logical control identifiers.
The runtime source signature is transport PID, USB interface number, event
type, event code, and optional `MSC_SCAN` value.

Virtual uinput devices have no physical USB ancestor and are rejected by this
algorithm. Also give every virtual device deterministic `name` and `phys`
markers as defense in depth.

v0.1 supports one logical Naga V3 Pro over one transport at a time. Hardware
tests confirmed that wired and HyperSpeed report the same serial, while
OpenRazer uses that serial as a unique D-Bus identity. If both matching USB
ancestors are present, report a transport conflict and do not grab either
device or issue hardware mutations. Do not silently prefer wired: OpenRazer may
already be unable to represent both devices safely. Resume discovery after one
transport disappears and OpenRazer has settled.

If two distinct responsive serials are found, report unsupported multiple-mouse
ambiguity rather than silently controlling one.

## Input Capture And Forwarding

`EVIOCGRAB` is per event node, not per key. Only grab a node when a configured
source control originates there. Every grabbed node needs its own forwarding
uinput clone so unrelated events continue to work.

Startup order for a source node:

1. Open and inspect the source.
2. Create a forwarding device with copied capabilities and input properties.
3. Wait until udev has initialized the virtual device.
4. Drain complete pending frames and verify no relevant key is held.
5. Grab the physical node.
6. Re-query key state and abort if the transition raced a key press.
7. Begin ordered frame forwarding.

Copy source bus, vendor, product, version, properties, absolute-axis metadata,
and supported input capabilities. Exclude `EV_SYN`, `EV_FF`, and output-only
capabilities that are not explicitly proxied. Do not blindly use
`UInput.from_device()` because identity and properties must be controlled.

The application also owns two stable replacement devices:

- `Naga Control Virtual Keyboard`
- `Naga Control Virtual Mouse`

Use `BUS_VIRTUAL`, application-specific non-Razer IDs, deterministic `phys`
markers, and fixed supported output capabilities. Separate devices produce
more predictable desktop classification than one combined device.

## Frame Pipeline

Buffer each source through `SYN_REPORT`; do not dispatch individual events to
independent tasks. Buffering allows an `MSC_SCAN` event preceding a mapped key
to be suppressed with that key.

For each complete normal frame:

1. Associate scan codes with key events.
2. Convert raw signatures to logical controls.
3. Resolve and store an action on key-down.
4. Use the stored action for repeat and key-up.
5. Suppress handled source events and associated scan events.
6. Forward every unhandled event to that source's proxy.
7. Flush proxy and replacement devices at the source `SYN_REPORT` boundary.

Device actions fire on key-down and consume their release. Held keyboard or
mouse mappings emit down and up transitions. Use output reference counts so
two physical controls mapped to one output cannot release each other.

For a key combination, press modifiers before the primary key and release in
reverse order. A held modifier is a stateful mapping, not a tap macro.

## Overflow And Failure Behavior

On `SYN_DROPPED`, discard events through the next `SYN_REPORT`, query current
key and absolute-axis state, release generated outputs whose source state is
uncertain, reconcile proxy state, and resume. Lost relative motion cannot be
recovered. Preventing a stuck modifier takes priority over preserving a hold.

On source removal, uinput write failure, an unrecoverable parse error, or
shutdown:

1. Emit releases for all generated held outputs.
2. Flush replacement devices.
3. Stop source processing.
4. Ungrab or close every physical descriptor.
5. Destroy forwarding devices.
6. Destroy replacement devices last during full shutdown.

If forwarding safety cannot be established, fail open by releasing grabs. Loss
of remapping is preferable to loss of ordinary mouse input.

## OpenRazer Adapter

The adapter selects devices by exact VID/PID and verifies capabilities through
D-Bus introspection. Do not gate support on the daemon version string because
custom and unsupported builds can report the same upstream version. A
compatible custom OpenRazer baseline is an intentional prerequisite until the
required support and recovery behavior are released upstream.

Subscribe to:

- `razer.devices.device_added`
- `razer.devices.device_removed`
- `org.freedesktop.DBus.NameOwnerChanged` for `org.razer`

All three events trigger a debounced rescan and replacement of stale client
objects. Hardware actions are serialized and bounded. Retry only operations
known to be safe after a wireless wake; never retry an unbounded mutation.
The adapter retains the last validated physical topology so an action received
after wake can reacquire a client before starting the mutation. It does not
repeat a mutation after an uncertain write or refresh failure. Completed action
state is published back to the service snapshot.

DPI stage up/down reads the current active stage and stage list, clamps at the
first/last stage, and writes the same list with the new one-based active index.
Do not invent a hardware command outside OpenRazer.

## Configuration

Use one versioned TOML file under the XDG config directory for v0.1. The
service is the sole writer. Writes use a temporary sibling, flush, fsync, and
atomic replace. File mode should be `0600`.

Store logical controls and actions, never transient event paths. A profile owns
button mappings, DPI stages and active stage, scroll settings, lighting, and
power settings. Manual profile selection and a default profile are v0.1 scope.
Application matching is explicitly deferred.

Configuration updates over IPC use an expected revision and replace a complete
validated configuration atomically. Reject stale revisions rather than merging
partial widget state.

## IPC

Provisional session-bus identity:

```text
bus name:  org.nagacontrol.Service1
path:      /org/nagacontrol/Service1
interface: org.nagacontrol.Service1
```

Keep the first contract narrow:

```text
GetSnapshot
GetConfiguration
ApplyConfiguration(expected_revision, document)
SelectProfile
BeginCalibration
EndCalibration
ReleaseAll
```

Signals cover snapshot changes, calibration events, and actionable errors.
There is no arbitrary event-injection, command-execution, path-access, or raw
OpenRazer method in the IPC surface.

The CLI exports a startup-gated interface and reserves the public bus name with
`DO_NOT_QUEUE` before hardware-owning service or auxiliary startup. It never
replaces an incumbent or uses a separate private singleton name. All seven
exported application methods wait until service and auxiliary initialization
complete; initialization readiness is distinct from mouse availability.

Startup failure and shutdown terminally close the gate with a fixed
`org.nagacontrol.Service1.Error.Unavailable` error. Queued methods cannot enter
an uninitialized provider. Existing non-exported Python helpers retain their
direct-call contract; they are not a remote readiness boundary. CLI cleanup
remains owned and joined despite caller cancellation, and disconnects the public
connection after entered owners finish teardown. Failed resource-release attempts
are not proof of kernel cleanup; transport loss can beat delivery of a queued
unavailable reply. Connection-factory acquisition before ownership transfer and
prompt interruption of blocked startup remain separate boundaries. After the
constructor returns a dedicated raw bus, factories own it until connect and
wrapper creation succeed; a pre-transfer failure attempts to disconnect that raw
once and preserves the primary error. Constructor failure has no raw to
disconnect; secondary non-ordinary interruption during disconnect is a separate
limit.

The service unit is enabled at login so mappings work without opening the GUI.
D-Bus activation may additionally start it when the GUI opens.

## Permissions

Run both processes as the logged-in user. OpenRazer already requires access to
its device nodes. The packaged udev rule adds `uaccess` only to event nodes
under the two target USB IDs and to `/dev/uinput`.

Access to uinput allows session-wide input injection and must be documented as
a security-sensitive permission. No component should run as root, be setuid,
or join the broad `input` group solely for this application.

## Package Layout

Create modules as each milestone needs them; do not prebuild empty frameworks.
The intended end state is:

```text
src/naga_control/
  application/       orchestration, actions, lifecycle
  domain/            immutable device, binding, profile, and state types
  ports/             small protocols for device, input, output, and config
  adapters/
    openrazer/        discovery, capability mapping, hardware operations
    evdev/            USB-parent discovery and ordered frame readers
    uinput/           source proxies and replacement outputs
    config/           TOML validation and atomic storage
  ipc/                versioned D-Bus service and Qt-side client contract
  service/            background process composition root
  ui/                 PySide6 windows and feature widgets
```

Dependencies always point inward. Domain and ports import neither Qt nor Linux
adapter libraries. Composition roots construct concrete adapters explicitly;
do not add a dependency-injection framework.
