# Desktop Startup Controls

User behavior for the 0.5.1 login-start checkbox and background-service restart.
See [architecture](architecture.md), [implementation plan](implementation-plan.md),
and [integration findings](integration-findings.md) for ownership and scope.

## Login Startup Checkbox

- Device page, Application group: `Start Naga Control at login (tray)`.
- The checkbox applies immediately. There is no TOML field, D-Bus field, or
  settings cache. The file itself is the truth.
- Default is off. Installing or opening the GUI never enables it silently.
- The mapping-service enablement is untouched.

## Owned Autostart File

- File: `org.nagacontrol.NagaControl.desktop` under
  `$XDG_CONFIG_HOME/autostart` when that variable is absolute, else
  `~/.config/autostart`.
- Content carries an owned marker (`X-NagaControl-Owned=true`), `Type=Application`,
  `Name=Naga Control`, `Icon=org.nagacontrol.NagaControl`, `Exec=<launcher> --start-hidden`,
  and `Hidden=false`.
- Enable uses temp file plus flush/fsync plus atomic replace, mode 0600.
  Disable removes only the owned regular file.
- Foreign files, symlinks, and directories are preserved. The UI reports a clear
  error instead of overwriting them.
- `Hidden=true` shows as disabled and needs re-enable. An entry that points to a
  different location, has invalid escaping, or whose launcher no longer exists,
  shows as disabled with a re-enable prompt. Invalid UTF8 is a stable error with
  no crash and no clobber. There is no automatic wrapper or path guessing.
- Every mutating failure re-reads the file and reports its truth plus a stable
  error. A failed remove still shows checked when the file remains. A failed
  update never claims enabled, and an unreadable file keeps the last verified
  state with an explicit unknown-state error.

## Launch Commands

- Two layers, no shell quoting. Layer 1 quotes argv per Exec spec: backslash,
  double quote, backtick, and dollar are backslash-escaped, literal `%` is `%%`,
  and reserved characters (space, tab, quotes, `< > ~ | & ; * ? # ( )` and more)
  force double quotes. Layer 2 doubles every backslash for file storage, so a
  literal backslash needs four backslashes in the file. NUL and newline are rejected.
- AppImage run: absolute `$APPIMAGE` plus `gui --start-hidden`. The bundled
  `$APPDIR` Python path is never persisted. If `APPDIR` exists without a valid
  `APPIMAGE`, enabling is refused with a portable-launcher error.
- Source run: absolute `sys.executable` (symlink preserved, never resolved) plus
  `-m naga_control.gui.app --start-hidden`.
- Moving or removing the image or interpreter invalidates the entry. Re-enable
  from the current installed location. Roundtrip tests load the rendered file
  with GLib in memory and decode it with an independent spec parser.

## Hidden Startup

- `naga-control-gui --start-hidden` starts hidden only when the system tray is
  available. Otherwise the window is shown so the app is never stranded.
- A normal launch is visible. A duplicate hidden launch exits without creating
  another window and without hiding the existing one.

## Service Restart Button
- Application group: `Restart background service`.
- Confirmation defaults to No and does nothing when declined. The text states that
  mappings pause briefly, held outputs are released by the normal service stop,
  and OpenRazer is not restarted.
- Fixed command only: `systemctl --user restart naga-control.service`. No shell,
  sudo, enable, unit parameter, or other daemon. The unit is started at most once.
- The call runs off the Qt thread with a bounded timeout and one owned shielded
  cleanup that kills only the systemctl child and joins it boundedly. Timeout and
  unverified cleanup report outcome uncertain and ask to check status; they never
  claim success and never assert the service is unchanged. Nonzero, missing
  command, timeout, and cancel are stable without raw stderr. There is no retry.
- Restart refuses while a profile, settings, or scroll apply is in flight, and
  those applies refuse while a restart is pending. Pending work disables editing
  without discarding drafts. After the unit call the panel waits boundedly for
  the presenter reconnect; on timeout or error it marks the model unreachable
  with a fixed hint so mutations stay gated against a stale snapshot, and it
  reports the unit result separately as restarted plus connection unverified.
  A cancelled restart emits an uncertain completion so busy never wedges. No new
  IPC method is added. The button stays enabled when the
  snapshot is unreachable as long as no apply is running.

## Uninstall Lifecycle

Uninstall removes only the owned autostart file above, independent of `--purge-config`; profiles and settings follow the existing preserve-unless-purge policy. It never touches foreign files, symlinks, directories, or unsafe entries, never removes the autostart directory or other apps, and reports incomplete rather than claiming success when an owned entry cannot be honestly cleaned.

## Testing Limits

- Default tests use fakes and tmp autostart paths. They never write real
  `~/.config`, call real `systemctl`, or touch the session bus, OpenRazer, evdev,
  or device nodes.
- Offscreen rendering verifies checkbox truth, busy, success, error, confirmation,
  guard blocking with real drafts, hidden fallback, GLib roundtrip, and bounded
  cleanup with double cancel. Live GUI, live service, daemon restarts, and hardware
  tests are out of scope for unattended checks.

## Manual Receipt (2026-10-17, HyperSpeed, Local 0.5.1 Candidate)

Owner manual verification on the local 0.5.1 HyperSpeed candidate; see
[hardware validation](hardware-validation.md#manual-051-candidate-acceptance-2026-10-17-hyperspeed-12-button)
for the full startup/reconnect scope and limits. This is owner-desktop
HyperSpeed only.

- Checkbox on/off confirmed, Quit then
  `~/.local/bin/naga-control.AppImage gui --start-hidden` tray-only startup,
  normal launcher restore of the existing window.
- Restart No did nothing. The first post-check PID was still 966912, so the
  investigator did not accept the restart yet and asked for an explicit repeat
  Yes; the UI then answered `Background service restarted` and the actual
  service PID changed to 969822 at 17:15:11, ready at 17:15:16 generation 2
  with no errors. OpenRazer PID 1478 unchanged. The new PID log had zero
  warnings/errors.
- The owner then explicitly confirmed F17 still works after the actual restart
  and recording Shift+Tab/keypad was correct with Cancel and no Apply.
- Startup user preference ON was verified as the owned regular entry mode 0600
  using the actual store load; it was not silently enabled by the installer.
  No TOML changes were made. No permission-backend upgrade beyond the normal
  existing startup mode/profile path was performed. Normal startup may reapply
  the existing profile through that path.

## Uninstall Test Receipt (Fake Only)

- Owned-entry uninstall cleanup was approved separately with fake tests only;
  no live uninstall was run. Fake suite (101 tests) covers removal of only the
  owned autostart entry above, independent of `--purge-config`.
- Profiles follow the existing preserve-unless-purge policy. Foreign files,
  symlinks, directories, and unsafe entries are preserved or report an error;
  the autostart directory and other apps are never removed.
- The new uninstaller helper is 339 lines in source/tag only, fetched with the
  source tag; it is not an AppImage helper.
