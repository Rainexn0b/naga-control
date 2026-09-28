# Starter Prompt: Linux Razer Naga V3 Pro Control App

## Project Goal

Build a new open-source Linux application specifically for managing the **Razer Naga V3 Pro**, using **OpenRazer as the hardware backend**.

The goal is to **replace Polychromatic entirely for this mouse**, while also adding the button-binding functionality Polychromatic does not provide.

This should be an opinionated, native Linux control application rather than a generic frontend for every Razer device.

## Hardware Target

Initial support is exclusively:

- Razer Naga V3 Pro wired: `1532:00E7`
- Razer Naga V3 Pro HyperSpeed/wireless: `1532:00E8`

Both interfaces represent the same physical mouse and should behave consistently.

The current OpenRazer upstream implementation already supports the mouse and should be treated as the hardware abstraction layer. **Do not reimplement HID commands that OpenRazer already exposes.**

The existing OpenRazer implementation supports functionality including:

- DPI configuration up to 50,000 DPI
- DPI stages
- X/Y DPI
- polling rate
- battery/power information
- lighting
- scroll-wheel functionality
- tactile/free-spin/precision-tactile modes
- scroll acceleration
- Smart Reel
- suspend/resume and receiver recovery

First inspect the installed/current OpenRazer Python API and D-Bus capabilities rather than assuming method names.

---

# Standard Stack Guidance

Use a conventional, boring stack. Boring is good here. The mouse already provides enough chaos.

## Language

- **Python 3.12+**

## UI

- **PySide6 / Qt6**
- Native widgets first
- Avoid QML unless there is a specific reason it materially improves the UI
- No Electron
- No browser/web frontend

## Hardware Backend

- `openrazer.client`
- OpenRazer D-Bus API where needed
- OpenRazer remains responsible for supported hardware operations

## Input / Remapping

- `evdev` for reading physical input events
- Linux `uinput` for emitting virtual keyboard/mouse events

## Configuration

Prefer:

- `tomllib` for reading TOML
- `tomli-w` or another small TOML writer if required

Use TOML for persisted user configuration unless investigation exposes a strong reason not to.

## IPC

Prefer the simplest robust option:

1. in-process service + UI if the background process can remain cleanly separated, or
2. local D-Bus / Unix socket IPC if a separate long-running service is justified.

Do not introduce a network server, REST API, embedded HTTP service, database, message broker, or other infrastructure theatre.

## Packaging

Prefer standard Python packaging:

- `pyproject.toml`
- `src/` package layout
- editable development install

Do not require Poetry unless the project materially benefits from it.

## Testing

- `pytest`
- use mocks/fakes around OpenRazer and evdev boundaries
- integration tests where practical

## Code Quality

Recommended tooling:

- Ruff for linting/formatting
- Pyright or mypy for type checking
- pytest for tests

Avoid piling on overlapping linters that mostly argue about commas.

---

# Architecture Guidance

Use a **layered modular architecture** with explicit boundaries between hardware access, domain logic, input processing, configuration, and UI.

The intended dependency direction is:

```text
UI
 ↓
Application / Services
 ↓
Domain
 ↓
Ports / Interfaces
 ↓
Adapters
 ↓
OpenRazer / evdev / uinput / filesystem
```

The UI must not directly contain hardware logic.

The OpenRazer adapter must not know about Qt widgets.

The input event loop must not contain UI state management.

## Suggested Package Layout

```text
src/
  naga_control/
    app/
      application.py
      lifecycle.py
      commands.py

    domain/
      device.py
      bindings.py
      dpi.py
      profiles.py
      scroll.py
      lighting.py
      power.py

    ports/
      device_backend.py
      input_source.py
      output_sink.py
      config_store.py
      event_bus.py

    adapters/
      openrazer/
        backend.py
        discovery.py
        capability_map.py
      evdev/
        input_monitor.py
        device_matcher.py
      uinput/
        emitter.py
      config/
        toml_store.py

    service/
      remapping_service.py
      device_service.py
      profile_service.py
      dpi_service.py

    ui/
      main_window.py
      overview/
      buttons/
      dpi/
      scroll/
      lighting/
      power/
      profiles/

    models/
      ui_state.py
      device_state.py

    util/
      logging.py
      paths.py

    __main__.py

tests/
  unit/
  integration/
  hardware/
```

This is guidance, not scripture. Change it if a cleaner structure emerges, but preserve the dependency boundaries.

---

# File and LoC Limits

Keep files small enough that both humans and coding agents can reason about them without spelunking through a swamp.

## Hard Limit

- **400 lines of code per Python file maximum**

This excludes generated code and trivial data files.

If a file approaches 400 LOC, split it by responsibility before adding more behaviour.

## Preferred Size

- Typical implementation file: **80–220 LOC**
- Small domain/helper modules: **30–150 LOC**
- Qt views/widgets: ideally **under 250 LOC**
- Test files: ideally **under 350 LOC**

Do not split files mechanically just to hit a number. Split when a file contains multiple responsibilities, unrelated state, or distinct reasons to change.

## Function / Method Guidance

Prefer:

- functions under roughly **40 LOC**
- methods that do one conceptual job
- shallow control flow
- explicit names over clever abstraction

If a function requires extensive scrolling to understand, it is probably doing too much.

## Class Guidance

Avoid mega-classes such as:

```text
NagaManager
MouseController
ApplicationManager
EverythingService
```

that become dumping grounds for discovery, input handling, DPI, profiles, lighting, and UI state.

One class should generally represent one cohesive responsibility.

---

# Core Architecture

Conceptually split the application into two responsibilities:

```text
naga-service
    ├── discovers the Naga V3 Pro
    ├── interfaces with OpenRazer
    ├── monitors raw mouse button events
    ├── performs device actions
    ├── emits remapped keyboard/mouse events through uinput
    ├── manages profiles/configuration
    └── continues working when the GUI is closed

naga-ui
    ├── displays device status
    ├── edits settings
    ├── edits button bindings
    ├── edits profiles
    └── communicates with naga-service
```

Do not force this exact process boundary if investigation shows that a simpler robust architecture is better, but **button remapping and hardware behaviour must continue working when the GUI is closed**.

Keep hardware/backend logic separate from Qt widgets.

---

# Core Feature Areas

## 1. Device Overview

Display:

- connection state
- wired / wireless mode
- battery percentage
- charging state if available
- firmware/device identifiers where OpenRazer exposes them

Device discovery must survive:

- unplug/replug
- switching wired ↔ wireless
- receiver reconnect
- mouse sleep/wake

Do not require restarting the application.

---

## 2. DPI Management

Implement full DPI configuration:

- current DPI
- X DPI
- Y DPI
- lock X/Y option where appropriate
- configurable DPI stages
- current active stage
- add/remove/edit stages within hardware/backend limits

Implement first-class actions:

```text
DPI Stage Up
DPI Stage Down
```

These should operate on the configured OpenRazer DPI stages.

For the Naga V3 Pro factory-style configuration:

```text
F13 / front left-click edge button -> DPI Stage Up
F14 / rear left-click edge button  -> DPI Stage Down
```

The application should handle these directly. Do not require KDE shortcuts, shell scripts, or Input Remapper.

---

## 3. Button Remapping

This is a major feature, not an afterthought.

Detect the physical controls exposed by the mouse through Linux input events.

Known examples currently include:

```text
F13     front left-click edge button
F14     rear left-click edge button
F17     ring-finger / Hypershift button
F18     top rear button
KPSLASH top front button
```

Do not assume this list is complete. Inspect the device and create a clean abstraction for discovered/known controls.

Allow a physical control to map to:

- keyboard key
- keyboard modifier
- mouse button
- simple key combination
- OpenRazer/device action
- disabled/no-op

Initial device actions should include at least:

```text
DPI Stage Up
DPI Stage Down
Scroll Mode Next
Scroll Mode Previous
Tactile Scroll
Precision Tactile Scroll
Free Spin
```

If practical, also support:

- profile next/previous
- lighting toggle
- arbitrary DPI stage selection

Use `uinput` for generated keyboard/mouse events.

Prevent loops where the virtual device's generated events are accidentally consumed again by the remapping service.

Modifier keys must behave correctly while held. For example:

```text
physical F17 down -> KEY_LEFTALT down
physical F17 up   -> KEY_LEFTALT up
```

Do not implement held modifiers as a macro that taps the key.

---

## 4. Side Plates

The Naga V3 Pro has interchangeable side plates.

Support sensible mappings for:

- 2-button plate
- 6-button plate
- 12-button plate

Where possible, automatically detect or infer which controls are currently available.

Provide useful Windows/Synapse-like defaults.

Expected default concept:

```text
2-button:
    Back
    Forward

6-button:
    1 2 3
    4 5 6

12-button:
    1 2 3
    4 5 6
    7 8 9
    0 - =
```

The GUI should visually distinguish these plate layouts rather than presenting an anonymous list of event codes.

Do not make fancy plate artwork a blocker for v0.1.

---

## 5. Scroll Wheel

Expose every Naga V3 Pro scroll feature supported by the current OpenRazer backend.

This includes, where available:

- Tactile
- Precision Tactile
- Free Spin
- scroll acceleration
- Smart Reel
- related parameters exposed by OpenRazer

The UI should present this more cleanly than Polychromatic currently does.

Do not silently hide supported OpenRazer functionality just because Polychromatic does not expose it.

---

## 6. Lighting

Replace the Polychromatic functionality needed for this mouse.

Expose independently where supported:

- scroll-wheel lighting
- logo lighting

And applicable effects such as:

- Off
- Static
- Spectrum
- Breathing
- Reactive
- Wave

Only expose effects actually supported by the OpenRazer device backend.

Do not fake unsupported combinations in the UI.

---

## 7. Power

Expose OpenRazer-supported power configuration:

- sleep/idle timeout
- low-battery warning threshold
- battery information

---

# Profiles

Implement application profiles/configurations.

A profile should be capable of storing at least:

- button mappings
- DPI stages
- active/default DPI stage
- scroll settings
- lighting settings

Keep the initial implementation simple.

Start with:

- manual profile selection
- default profile

Design the profile layer so automatic per-application profiles can be added later, but **do not make application detection a prerequisite for v0.1**.

---

# GUI Guidance

Use PySide6 and build a native Qt6 interface.

Aim for a compact utility rather than a gaming-company dashboard.

Suggested layout:

```text
Naga V3 Pro

Overview
Buttons
DPI
Scroll
Lighting
Power
Profiles
```

Priorities:

- clean native layout
- fast startup
- no giant decorative graphics
- no account
- no telemetry
- no web services
- no ads
- no AI button nonsense

The mouse should be understandable from the UI without requiring knowledge of `F13`, `F17`, `BTN_*`, etc.

Internally retaining those identifiers is fine.

## UI Architecture Rules

- Widgets should render state and emit user intent.
- Widgets should not directly call OpenRazer.
- Keep stateful hardware operations in services/application logic.
- Prefer small feature-specific widgets over one giant main-window implementation.
- Keep model/state objects independent of Qt where practical.

---

# Permissions

Investigate the cleanest supported Linux mechanism for accessing the relevant evdev devices and creating uinput devices.

Do not instruct users to run the GUI as root.

Prefer proper:

- udev rules
- groups
- system permissions

Document whatever installation steps are actually required.

Avoid unnecessarily broad permissions.

---

# Reliability

Treat the following as normal operating conditions:

- mouse sleeps
- receiver temporarily disappears
- USB cable gets connected/disconnected
- device switches between wired and wireless
- OpenRazer daemon restarts
- GUI opens/closes

The software should recover where reasonably possible rather than requiring a restart.

## State Rules

- Keep authoritative hardware state separate from UI state.
- Re-query capabilities after reconnect.
- Do not assume device paths remain stable across reconnects.
- Do not assume wired and wireless interfaces appear at the same path.
- Avoid using UI widget state as the source of truth.

---

# Testing

Tests are useful where they protect actual behaviour.

Prioritize:

- config serialization
- profile loading
- mapping translation
- held-key state handling
- DPI stage navigation
- event-loop prevention
- reconnect state handling where mockable
- capability detection
- wired/wireless device normalization

Do not waste large amounts of implementation time snapshot-testing Qt pixels.

Hardware integration should also support a useful debug/log mode so behaviour can be verified on the real Naga.

## Test Boundaries

Make OpenRazer, evdev, uinput, and filesystem access injectable behind small interfaces so core logic can be unit-tested without hardware.

Do not mock half the Python standard library to compensate for poor boundaries.

---

# Logging and Diagnostics

Implement structured, useful logging from the beginning.

At minimum log:

- device discovery/removal
- selected OpenRazer device
- input-device binding
- profile changes
- mapping activation
- OpenRazer operation failures
- reconnects
- uinput setup failures

Provide a CLI/debug option such as:

```bash
naga-control --debug
```

Avoid noisy per-event logs by default.

---

# Open-Source Considerations

This will be published publicly.

Therefore:

- no machine-specific absolute paths
- no personal data
- no API keys
- clear README
- install instructions
- dependency list
- architecture summary
- development instructions

Do **not** copy Polychromatic source code.

It may be studied to understand existing OpenRazer interactions or supported behaviour, but this project should have its own architecture and implementation.

Do not choose a final software license without flagging that decision for review.

---

# Scope Discipline

**Do not turn this into a generic OpenRazer frontend yet.**

The product is:

> A good Linux control application for the Razer Naga V3 Pro.

Supporting arbitrary Razer mice/keyboards is explicitly out of scope for the initial project.

However, keep backend interfaces clean enough that additional devices would not require rewriting the entire application later.

Likewise, do not reimplement OpenRazer.

If OpenRazer already performs a hardware operation, use it.

The unique value of this project is:

1. a better Naga-specific frontend,
2. complete access to the Naga V3 Pro functionality OpenRazer exposes,
3. proper button remapping,
4. mapping physical buttons directly to device actions such as DPI-stage switching,
5. one coherent application instead of requiring Polychromatic + Input Remapper + scripts + desktop shortcuts.

---

# Anti-Patterns to Avoid

Do not:

- put device discovery, OpenRazer calls, evdev loops, and Qt code into one class
- create a generic plugin framework before a second device exists
- create a repository/data-access layer around simple local TOML config unless it adds real value
- introduce dependency injection frameworks
- build a database for profiles
- expose internal Linux event names directly as the primary UX
- poll hardware aggressively when event-driven or reconnect-aware approaches are available
- duplicate state across UI widgets, services, and config with no clear authority
- create abstractions solely because another mature project uses them
- overengineer v0.1 around hypothetical future keyboards

---

# First Task

Do **not** immediately implement the entire application.

Start by investigating the environment and produce a short implementation plan based on actual available APIs.

Specifically:

1. Inspect the current OpenRazer Naga V3 Pro implementation.
2. Inspect the Python client/D-Bus API for every capability exposed by this device.
3. Determine the Linux input devices/events generated by the mouse.
4. Determine the cleanest evdev/uinput architecture for remapping.
5. Identify permissions/udev requirements.
6. Identify how wired and HyperSpeed instances appear and how to avoid treating them as two unrelated mice.
7. Define a minimal v0.1 architecture and directory layout.
8. List which desired features OpenRazer supports directly and which require application-side handling.
9. Flag any uncertain hardware behaviour that needs testing on the physical mouse.
10. Confirm the proposed architecture respects the 400 LOC/file hard limit before implementation begins.

Then implement the project incrementally, beginning with:

```text
device discovery
      ↓
OpenRazer status/control
      ↓
raw button event monitor
      ↓
F13/F14 -> DPI stage up/down
      ↓
generic remapping through uinput
      ↓
Qt configuration UI
      ↓
remaining OpenRazer controls
```

Keep each stage working before expanding scope.

Before making assumptions about OpenRazer APIs or device behaviour, inspect the actual implementation.

---

# First Vertical Slice

The first meaningful end-to-end milestone should prove both major execution paths.

## Hardware Action Path

```text
physical F13/F14
      ↓
evdev
      ↓
input mapping
      ↓
action dispatcher
      ↓
DPI service
      ↓
OpenRazer
      ↓
mouse DPI stage changes
```

## Remapped Input Path

```text
physical F17
      ↓
evdev
      ↓
input mapping
      ↓
action dispatcher
      ↓
uinput
      ↓
KEY_LEFTALT down/up
      ↓
Linux application/game
```

Do not spend significant time polishing lighting UI before both paths work reliably.
