# Implementation Plan

Each milestone must leave the service usable at its current level and keep the
default test suite hardware-independent. Do not parallelize changes that touch
the same event-state machine.

## Milestone 0: Hardware Capture Tool

Build a read-only diagnostic command before remapping.

Deliverables:

- enumerate only `1532:00E7` and `1532:00E8` event nodes by USB parent
- print transport, interface, stable metadata, properties, and capabilities
- capture complete frames from all sibling nodes without grabbing
- redact serial and physical port by default
- optionally write a versioned JSON capture suitable for test fixtures
- label `MSC_SCAN`, `EV_KEY`, `EV_REL`, and synchronization events

Acceptance:

- virtual devices and the Mouse Dock are excluded
- unplug during capture exits cleanly
- captures from 12-, 6-, and 2-button plates can be compared
- no root requirement on a correctly installed system

Earlier hardware tests establish the key-code mappings for the 12-button plate
on both transports and the alternate plates over HyperSpeed. This milestone
turns that evidence into sanitized fixtures and resolves the remaining
unknowns: exact interface/scan signatures, top-button behavior, and any
duplicate routing.

## Milestone 1: Domain And Configuration

Implement pure domain types and a versioned TOML store.

Deliverables:

- logical controls independent of Linux key names
- action variants for disabled, key, key combination, mouse button, and device
  action
- profile, DPI stage, scroll, lighting, and power settings
- validation for DPI 100..50000 and 1..5 stages
- default mappings for all three plate layouts
- atomic config writes and explicit schema version

Acceptance:

- round-trip tests preserve all settings
- malformed configuration produces field-specific errors
- unknown future fields are rejected or handled by an explicit migration
- no Qt, evdev, OpenRazer, or D-Bus imports in domain modules

Suggested agent boundary: one agent can own this milestone without touching
Linux adapters.

## Milestone 2: OpenRazer Adapter

Implement discovery, capability mapping, state reads, and device operations.

Deliverables:

- select exact target VID/PID through `openrazer.client`
- introspect and map actual D-Bus methods
- represent one logical mouse over exactly one active transport
- detect simultaneous wired/HyperSpeed attachment as a conflict
- refresh on OpenRazer add/remove and daemon owner changes
- serialized, non-event-loop hardware operation queue
- DPI stage navigation and mechanical scroll actions
- fake backend with the same port for tests

Acceptance:

- unsupported released OpenRazer reports a clear prerequisite error
- daemon absence/restart does not terminate the service
- stale client objects are never reused after reconnect
- a dual-transport conflict produces no grabs or hardware mutations
- stage up/down clamps safely and preserves X/Y stage pairs
- all hardware calls are absent from the evdev event-loop thread

Suggested agent boundary: this milestone can proceed in parallel with
Milestone 1 once port shapes are agreed.

## Milestone 3: evdev Discovery And Read Pipeline

Implement hotplug-aware physical source discovery and ordered frame parsing,
initially without grabs.

Deliverables:

- pyudev monitor started before initial enumeration
- USB-parent grouping and interface metadata
- add/remove debounce for composite interfaces
- complete-frame buffering with scan-code association
- logical-control translation based on capture fixtures
- `SYN_DROPPED` recovery state machine

Acceptance:

- reconnect may change every `eventN` path without breaking identity
- a virtual device cannot enter discovery
- duplicate reports can be collapsed by a tested rule
- disconnect while a control is held emits a logical release/reset

Do not infer plate identity from static capability sets. Keep manual plate
selection as the initial authority.

## Milestone 4: uinput And Mapping Engine

Add selective source-node grabs, passthrough clones, and replacement outputs.

Deliverables:

- per-source forwarding clone ready before `EVIOCGRAB`
- fixed virtual keyboard and virtual mouse
- frame-ordered suppression and passthrough
- held key/combo behavior and output reference counts
- profile-change behavior for already-held controls
- fail-open cleanup and explicit `ReleaseAll`

Acceptance:

- ordinary pointer, click, and high-resolution wheel behavior is unchanged
  when a pointer-capable node is proxied
- F17 down/up produces LEFTALT down/up with no tap behavior
- two controls mapped to LEFTALT cannot release each other
- unplug, service stop, and simulated overflow leave no stuck output
- an existing grab from another remapper gives a clear error and leaves the
  physical node unmodified
- virtual events are not consumed again

The forwarding state machine should be implemented by one agent at a time.
It is the most safety-critical code in the project.

## Milestone 5: First Hardware Vertical Slice

Compose the service without the full GUI.

Deliverables:

- service CLI with `--debug`
- active-profile loading
- F13/F14 mapped to DPI stage up/down
- F17 mapped to held LEFTALT
- useful status and error logging
- basic session D-Bus snapshot and release-all methods

Acceptance on both available transports, tested separately and never attached
simultaneously:

```text
F13 press -> next configured OpenRazer DPI stage
F14 press -> previous configured OpenRazer DPI stage
F17 down  -> KEY_LEFTALT down
F17 up    -> KEY_LEFTALT up
```

Also verify sleep/wake, cable/receiver switching, OpenRazer restart, GUI absence,
disconnect while held, and service crash behavior. Do not proceed to visual
polish until these paths are reliable.

## Milestone 6: Service IPC And Native GUI Shell

Stabilize the versioned session D-Bus contract and add a compact PySide6 UI.

Deliverables:

- user service unit enabled at login
- D-Bus activation file
- overview, buttons, DPI, scroll, lighting, power, and profiles navigation
- service snapshot model independent of widgets
- atomic configuration updates with revision checking
- calibration UI driven by service events

Acceptance:

- closing the GUI does not affect mappings
- opening multiple GUIs does not create multiple hardware owners
- service restarts are reflected without restarting the GUI
- interface works at narrow mobile-like widths and normal desktop sizes
- no widget directly imports OpenRazer or evdev

## Milestone 7: Remaining OpenRazer Controls

Add the remaining verified capability-driven pages.

Deliverables:

- X/Y DPI editing, lock option, stages, and polling
- all three mechanical scroll modes, acceleration, and Smart Reel
- thumb-grid, logo, and scroll lighting with only introspected effects
- battery, charging, idle timeout, and warning threshold
- manual profile and side-plate selection

Acceptance:

- unsupported effects are absent rather than disabled guesses
- profile application is ordered and reports partial hardware failures
- reconnect reapplies desired state and then refreshes observed state
- 2- and 6-button plates do not misleadingly advertise plate lighting

## Milestone 8: Packaging And Release Readiness

Deliverables:

- distro-neutral install layout for udev, systemd user, D-Bus, desktop, and icon
  assets
- at least one tested distribution package
- upgrade and uninstall behavior
- troubleshooting and debug-bundle documentation with identifier redaction
- packaged license metadata and notices

Acceptance:

- no root GUI or root service
- clean install starts mappings at user login after documented permission setup
- uninstall removes service and virtual devices cleanly
- release notes state the exact required OpenRazer revision/release

## Cross-Cutting Test Priorities

1. Mapping translation and held-output reference counts
2. Complete-frame passthrough and scan suppression
3. `SYN_DROPPED`, disconnect, shutdown, and failure cleanup
4. Config validation, migration, and atomic persistence
5. Capability introspection and OpenRazer restart
6. USB-parent grouping, transport switching, and dual-transport rejection
7. DPI stage navigation
8. Qt state binding, without pixel snapshots

## Deferred Work

Post-0.3 requests and their sequential delivery queue are tracked separately in
[Post-0.3 UI Implementation Tracker](post-0.3-ui-tracker.md). Plate identity and
mode switching retain their evidence and input-ownership safety gates.

- per-application profile detection
- macros and command execution
- generic OpenRazer devices
- plate artwork
- automatic plate switching unless hardware capture proves a reliable signal
- multi-seat and multiple-Naga support
