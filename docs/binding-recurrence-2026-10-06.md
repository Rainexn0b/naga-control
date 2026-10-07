# Binding Recurrence Recovery, 2026-10-06

## Incident

The OpenRazer agent's report at
`/home/cyril/Projects/openrazer/.git/opencode-deployments/fix2-26b0eeb5/RECURRENCE-2026-10-06.md`
identified an old running panel image and a broken launcher in the newer image
on disk. Independent panel checks confirmed both problems:

- Naga Control PID 1694874 was still the October 5 process, with public status
  unavailable, generation 12, software requested, no observed mode, and
  `hardware topology rescan is pending`.
- The installed AppImage's hardware-free `openrazer.client` import raised
  `ModuleNotFoundError`. Restarting blindly into that image was not safe recovery.
- OpenRazer PID 2054792 remained running. Preflight reads later confirmed one
  HyperSpeed transport, no held mouse keys, and verified software/driver mode.

The initiating transient exception was not captured. The matching stale-worker
recovery defect is established, but this is not a complete trace of its trigger.

## Source And Build

Committed revision `4baf4e8` already contains both necessary production fixes:

- Session teardown marks the worker stale and requests a rescan with
  `_needs_rescan = True`.
- The canonical AppRun bridges the actual `openrazer` and `openrazer_daemon`
  package directories, not their parent site-packages directory. Native
  dependencies remain bundled rather than coming from the host package tree.

No additional runtime or OpenRazer edits were made for this incident. The
launcher regression test was strengthened to actually import a fake client and
its daemon helper and reject an unrelated host package, for both single and
concurrent launches.

A detached worktree at `/tmp/opencode/naga-recurrence-4baf4e8` built the committed
application with that test-only change. Concurrent debt-paydown and lifecycle
edits in the main worktree were excluded from the deployed payload.

Artifact: `dist/Naga-Control-0.4.0-x86_64.AppImage` in that worktree.
SHA-256:

```text
123f840e81601085bfbcbc0e9e7b42619036b666ec555606f2484daf946573c9
```

## Verification

- Isolated revision: 955 default tests passed, two coverage-dependent tests
  skipped because `coverage` is unavailable, five hardware tests deselected.
  Ruff lint/format and Pyright passed.
- Packaged application code: 19 fake mode/recovery tests passed against the
  assembled AppDir package rather than the dirty source tree.
- Mounted image: real host `openrazer.client` and daemon-package imports passed;
  dbus, evdev, and NumPy were verified to come from the bundle. The packaged
  teardown code was checked for the rescan assignment.
- Qt offscreen initialization, service help, and temporary integration
  installation passed. The integration payload retains `KillMode=mixed`.
- Docker smoke could not run because Docker is unavailable. Host checks are
  not a replacement for clean-distribution smoke or the full release gates.

The main worktree subsequently passed 2,175 default tests and Pyright, with
the same two coverage-dependent skips and five hardware tests deselected.
Its Ruff run reported one quoted-annotation issue in the concurrently added
`test_openrazer_factory_monitor.py`; format-check reported an unrelated change
in `test_openrazer_connection_factory.py`. Neither was changed by this work.

## Deployment And Observed Recovery

The user approved backing up and replacing the local image and restarting only
Naga Control, with the GUI closed and physical mouse buttons released.

- The previous installed file was backed up to
  `/tmp/opencode/naga-recurrence-installed-before-20261006.AppImage`.
- The candidate was staged next to the installed file and renamed atomically;
  no running image inode was truncated. Installed SHA-256 matches the candidate.
- The installed launcher import was rechecked before the restart.
- The old panel process stopped without SIGBUS under `KillMode=mixed`.
- New panel PID 2122018 started at 22:09:54 local time. Its mounted package
  metadata reports 0.4.0, and its actual runtime includes the rescan assignment.
- A held left click during the initial lifecycle rebuild correctly blocked
  forwarding startup. All physical keys were subsequently clear, and the
  next periodic poll rebuilt the session without another restart.
- The snapshot settled at generation 3, available, desired/observed software
  mode, mode ready, no mode error, and no settings failures. Five service-owned
  uinput handles were present. The user confirmed bindings and F17 worked.
- OpenRazer PID 2054792 remained unchanged. No OpenRazer restart, raw HID
  operation, idle-time change, or explicit mode write was performed. Normal
  panel startup reapplied saved profile settings.

No release, tag, or commit was created by this recovery deployment. The GUI
was left closed; later launches use the corrected installed launcher.

## Remaining Validation

Repeat genuine natural sleep/wake cycles with the same OpenRazer and panel
processes, observing physical F17 press/release and generated LEFTALT output.
Capture timestamps and snapshots before any restart if the failure recurs.
Deployment recovery and the held-key gate recovery do not establish sleep/wake
acceptance. The separate held-output firmware-handoff gate remains open, and
no tray mode switch was enabled.
