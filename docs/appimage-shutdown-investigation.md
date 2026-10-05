# AppImage Shutdown Investigation

Investigation date: 2026-10-05. No mouse reads, grabs, mode writes, or live
remapping-service restarts were required for the reproduction.

## Evidence

Three saved service cores report SIGBUS during shutdown. The most recent core
(PID 1683784) reports `BUS_ADRERR` at offset `0x133a8` in the `_socket` native
extension, called from libc `exit()`. Disassembly of the matching host extension
places its `_fini` entry at exactly that offset: the fault occurs while entering
native library finalization, not in an F17 mapping callback.

The effective service unit used systemd's default `KillMode=control-group`.
Its cgroup contained both the main Python process and the AppImage's FUSE
process. On stop, both receive SIGTERM. The FUSE process can unmount/disconnect
the filesystem before Python finishes exiting. A later page fault against an
image-backed library can then produce SIGBUS.

A disposable transient user service, using only bundled Python and an unused
mapped Qt library, reproduced this mechanism with the installed AppImage:

| KillMode | Image readable after SIGTERM | Uncached mapped-page access | Python exit |
| --- | --- | --- | --- |
| `control-group` | no, `FileNotFoundError` | SIGBUS | dumped, signal 7 |
| `mixed` | yes | succeeded | normal, status 0 |

This deliberately forces a cold-page access; an ordinary small Python process
can exit cleanly under either mode when all needed pages are already cached.
The reproduction establishes a shutdown hazard matching the original core.
It does not prove that every historical crash had this cause.

Both units reported `Result=timeout` because `RuntimeMaxSec` initiated their
stops. The distinguishing evidence is `ExecMainCode`/`ExecMainStatus` and probe
output, not the overall unit result. Both cgroups were empty afterward.

## Fix

The packaged user service now uses `KillMode=mixed`: initial SIGTERM goes only
to the main process, allowing normal Python teardown while FUSE remains alive.
The AppImage keepalive mechanism then releases its mount when the application
exits. systemd still applies SIGKILL to remaining cgroup processes after the
main process exits or the stop timeout expires; this is not `KillMode=process`
or an exemption from bounded cleanup.

An integration test installs the real packaged unit with an AppImage command
and verifies that the shutdown setting survives command rewriting. No Python
service teardown changes are needed for this targeted fix.

A local user-unit drop-in, `naga-control.service.d/appimage-shutdown.conf`, was
installed with the same setting and systemd reloaded. Effective `KillMode` is
now `mixed`; the running main PID remained unchanged. This does not update the
running Python build. A separate hardware-free probe that ignored SIGTERM
was killed after a one-second stop timeout, with no residual cgroup processes.

The installer normally replaces the image through a temporary sibling and
rename, rather than truncating the inode used by a running mount. The known
old-mounted-image behavior is a deployment/provenance issue, not evidence of
in-place truncation causing these crashes.

## Reproduction

Run as the desktop user with a built, mounted AppImage. The explicit `python`
command does not start the GUI, service, device discovery, or OpenRazer manager.
The probe intentionally crashes under the old shutdown policy. Its core limit
is zero to avoid storing diagnostic cores. Choose unique disposable unit names
if the example units already exist.

```bash
systemd-run --user --unit=naga-shutdown-control --wait --pipe \
  -p Type=exec -p KillMode=control-group -p RuntimeMaxSec=3s \
  -p TimeoutStopSec=10s -p LimitCORE=0 \
  --setenv=PYTHONDONTWRITEBYTECODE=1 \
  "$HOME/.local/bin/naga-control.AppImage" python -B -s -u -X faulthandler \
  "$PWD/scripts/probe_appimage_shutdown.py"

systemd-run --user --unit=naga-shutdown-mixed --wait --pipe \
  -p Type=exec -p KillMode=mixed -p RuntimeMaxSec=3s \
  -p TimeoutStopSec=10s -p LimitCORE=0 \
  --setenv=PYTHONDONTWRITEBYTECODE=1 \
  "$HOME/.local/bin/naga-control.AppImage" python -B -s -u -X faulthandler \
  "$PWD/scripts/probe_appimage_shutdown.py"

systemctl --user show naga-shutdown-control.service naga-shutdown-mixed.service \
  -p Id -p Result -p ExecMainCode -p ExecMainStatus -p MainPID -p ControlGroup
```

The probe requires Linux, the normal FUSE-mounted runtime, and the bundled
PySide6 library. It is not a default pytest test and does not validate actual
remapping teardown. A coordinated real-service stop/start remains a follow-up.

## Checks

The retained probe reproduced SIGBUS under `control-group` and exited normally
under `mixed`. Packaged unit verification and Pyright passed. Ruff lint and
format checks passed for `src`, `tests`, and `packaging`. The application suite
and source-limit checks passed with the unrelated `buildpython` tree excluded:
765 passed, 103 deselected (including five opt-in hardware tests).

Repository-wide Ruff/format encountered pre-existing failures in the concurrently
added, untracked `buildpython` tree. The unrestricted pytest run also encountered
two source-limit failures there: a file removed during the run and a 445-line
file. Those files were not modified as part of this investigation.
