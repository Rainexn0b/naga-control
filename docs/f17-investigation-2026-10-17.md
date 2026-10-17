# F17 Investigation, 2026-10-17

Receipt for the Oct 17 F17 failure, code fix, local install, and manual port-move acceptance. The user approved the local install, coordinated hardware checks, and subsequent commit/push. A separate historical local Oct 14 investigation is not included here.

## Incident

- User reported F17 had no effect, and confirmed unplugging the mouse and plugging it into another USB port.
- Saved config rev24 intact: active default profile, 12-button plate, software mode, `ring_finger` mapped to `right_ctrl`.
- Running product was the installed local Oct 14 patch, not current HEAD; six mounted overlay hashes verified against local provenance.

## Failure evidence

- `2026-10-17 12:39:51 +02`: interface `00` reader raised `OSError` errno 19 `ENODEV`.
- Cleanup hit `ENODEV` on ungrab, cached first exception, still tried descriptor/proxy closes; `SessionLifecycle` stayed unsafe and a recovery warning repeated about every 30s.
- Snapshot showed `unavailable`, generation 8, observed mode null, `mode_ready` false, topology changed; no input/uinput handles left.
- This establishes a recovery blocker. No hardware mode-drift claim and no python-evdev `EBADF` trigger claim are made for this event.
- Port move matches operator report; no independent USB causal proof. Before recovery the primary used logs plus non-activating `GetSnapshot`/`GetConfiguration` only; no input observer/grab.

## First recovery

- User explicitly approved a Naga-only restart plus the code fix. Normal restart at 14:47:40 succeeded; new process `available` by 14:47:46 at generation 2, software/software, ready, no failures. OpenRazer PID unchanged; no config edits.
- Old process stop exited 1 on the same cached `ENODEV`, not SIGBUS. User explicitly confirmed RightCtrl holds/releases and normal pointer work. Normal startup may apply existing mode/profile/grabs.
- No hardware tests and no deliberate port-swap validation were run in that phase.

## Bounded code fix

- Changed product path only: `src/naga_control/adapters/evdev/source.py`. `ungrab` ignores only `OSError` with `ENODEV` as disconnected input; caller still closes the descriptor.
- Idempotent close flag is set only after successful `device.close`. Other ungrab/close errors propagate unchanged. No lifecycle/forwarder weakening, no discovery or schema change.
- Six local Oct 14 safety overlays remain absent from main and must be integrated before any release.
- New tests: `tests/test_evdev_source_removal.py`, 15 fake cases; baseline RED 5 failed / 10 passed, fixed tree 15 passed. Tests use an explicit fake strict wrapper because the repo forwarder suppresses cleanup errors while the deployed Oct 14 patch caches them.
- Supervisor isolated the actual installed product source under `/tmp/opencode` with no live device access, confirmed 6 overlay hashes, and exercised real installed `SourceForwarder`/`SessionLifecycle` with fakes: baseline `ENODEV` latched, patched `ENODEV` closed and a fresh changed-port source started; genuine `EIO` stayed unsafe.

## Final gates

- Full `.venv/bin/pytest -q`: exit 0, 4117 passed, 2 coverage-unavailable skips, 5 hardware deselected, 7 dbus_next deprecation warnings, 662.27s.
- Current-tree focused suite: 138 passed; isolated installed overlays with patched adapter: 103 passed.
- `ruff check .`: PASS. `ruff format --check .`: PASS, 472 files. `pyright`: PASS, 0 errors. Physical lines: source 234, tests 292.
- Actual extracted candidate: 103 focused passed by worker and independent supervisor 103 passed in 0.53s, origins asserted.

## Local install

- Candidate preserves installed `e081598` plus six Oct 14 overlays with only the product adapter change. Supervisor byte-compared all 99 `.py` files from the actual candidate against the previously running mounted package; only `source.py` differs.
- Candidate sha256 `a4b94786221db9067c5828e405e318ded201ea83d2a244eb6a705a5053dddc57`, size 107182584, build 19.7s. Dependencies unchanged; bundled Python 3.14.8 versus prior 3.14.7. Localhost-only build, no portable or clean-distro gate claimed.
- Permanent rollback sha `961029...` saved at `~/.local/share/naga-control/rollback.pre-hotplug-fix-20261017.AppImage`. Install used atomic `os.replace`, no in-place overwrite.
- Normal Naga-only stop/start at 15:06. OpenRazer PID 1478 unchanged throughout. Saved configuration document sha256 `25504df68ae1c465dc25649cc185cdd39d03aa107012ecad2b5c3491a8a0923e` unchanged, rev24 `right_ctrl`. Running mounted adapter matches the repo fix; all six overlay hashes unchanged.
- No release, tag, or version change was made. The installed app remains a local unreleased 0.5.0 patch, not 0.5.1; source commit/push follows receipt validation.

## Startup note, not clean

- Do not claim clean startup. At 15:06:36 the known python-evdev callback `OSError` `EBADF` followed by `InvalidStateError` appeared, with transient `unavailable` and no session; the same process then recovered automatically without another restart. That is a separate unresolved race, not the `ENODEV` blocker fixed here.

## Manual port-move acceptance

- After patched install the user moved only the HyperSpeed receiver to another USB port, with backup keyboard, buttons released, and GUI quit safeguards acknowledged.
- At 15:08:26 the interface `00` reader raised `ENODEV` and the service went cleanly `absent`; at 15:08:30 a transient `unsupported` state appeared, with no cached cleanup exception and no repeated recovery errors.
- The same PID 278042 later reported `available` at generation 6, software/software, ready, with no errors or failures.
- The user first answered `Fails after port move`, then after the snapshot recheck answered `Works now`, with no additional restart, investigator-issued mode write, or user config change between those answers. Normal service recovery may reapply mode/profile settings.
- This proves eventual autonomous reconnect recovery by manual observation, not instantaneous or within-30s latency; the exact delay was not captured. Both the initial failed observation and the later success are preserved here.
- No opt-in hardware pytest and no new device-node observers were run; only normal service operations under the approved restart and the manual plug event.

## Still pending

- Reconnect latency characterization and natural idle/wake checks; the separate evdev `EBADF` callback race.
- See [architecture](architecture.md), [hardware validation](hardware-validation.md), [troubleshooting](troubleshooting.md), and [implementation plan](implementation-plan.md).

## Safety overlay integration

- The six Oct 14 reader-failure and cleanup-barrier overlays are now integrated into main with exact deployed bytes. Product hashes `c17ab059`, `9256a05e`, `3bd27e74`, `04712e75`, `dea98e32`, `dc335bca` match the verified mounted candidate. The existing `ENODEV` adapter fix remains unchanged and now recovers cleanly through the strict forwarder instead of latching. No public IPC, schema, or required-protocol change; no GUI change.
- Fake regressions cover unexpected reader ends, once-only session failure, held-output release, fenced worker teardown, first-error cleanup barrier with primary preservation, and redacted warnings. The manual port-move observation above and its latency limits are retained unchanged; no new hardware acceptance is claimed here. No release, tag, or version change was made.
- Removal regressions now exercise the real strict forwarder rather than the earlier test mirror. Independent baseline RED checks reproduced phantom-healthy readers and swallowed cleanup failures with pytest exit 1; current-code focused checks passed 301 tests.
- Final integrated-source checks: `ruff check .`, `ruff format --check .` (478 files), and `pyright` passed. `.venv/bin/pytest -q` exited 0: 4170 passed, 2 coverage-unavailable skips, 5 hardware deselected, 7 dependency deprecation warnings, 651.85s. All Python files remain within 400 physical lines; all six product hashes still match the deployed safeguards.
