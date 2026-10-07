# Exception Boundary Inventory

DEBT-02 evidence for the [Debt Paydown Campaign](debt-paydown-campaign.md).
Reviewed 2026-10-05 against `4baf4e8` and the uncommitted DEBT-01/DEBT-02 work.
This is a disposition record, not a waiver list or proof that cleanup cannot fail.
Line references identify the reviewed source; future edits may move handlers.

## Scope And Findings

- All 35 baseline `broad_except_unlogged` handlers have a disposition: one confirmed
  lifecycle diagnostic gap fixed in DEBT-01, 30 retained propagation/reporting
  boundaries, and four retained optional-value fallbacks.
- The 34 remaining findings have no recognized handler-local diagnostic according
  to the scanner. Source review finds downstream failure reporting or intentional
  unknown-value fallback, not 34 confirmed silent failures.
- All five `BaseException` handlers attempt rollback and rethrow. Retain their
  cancellation/interruption coverage; characterize cleanup failures separately.
- Two `pytest.skip.Exception` rethrow handlers were incorrectly counted as broad
  builtin catches. They are specific pytest outcomes, not catch-all handlers.
- No product or hardware-test catch was narrowed, removed, or annotated in DEBT-02.
  No hardware tests were executed. No reviewed boundary was automatically waived.

Disposition **propagation** means the error has an inspected caller-visible route;
it does not mean a traceback is logged or every failure branch is already tested.
**Fallback** means optional data becomes unknown, intentionally losing the cause.
**Cleanup** means an attempt continues or rolls back ownership, not guaranteed success.

## Product Handlers

Paths below are relative to `src/naga_control/`. The first row is the original
baseline gap, now resolved; the other 19 remain review candidates in the scanner.

| Path / Line | Function | Disposition | Evidence / Follow-Up |
| --- | --- | --- | --- |
| `adapters/openrazer/lifecycle_monitor.py:173` baseline, now `179` | `OpenRazerLifecycleMonitor._run` | Resolved diagnostic gap | DEBT-01 phase/type warning; fake provider/controller recovery, privacy, suppression, cancellation, and debounce tests |
| `service/hardware_worker.py:150` | `HardwareWorker._run` | Propagation | Sets exception on the request future awaited by `_submit`; callers log or publish failure. `test_hardware_worker.py` covers stale requests; direct backend failure and cancelled-future cases feed DEBT-05 |
| `service/runtime.py:111` | `NagaService._poll_observed_state` | Propagation | Stores mode error, clears observation, latches uncertain-write failure; snapshot/UI expose unready mode. `test_service_mode.py` asserts no repeated uncertain write |
| `service/runtime.py:272` | `NagaService._rescan` | Propagation | Stores mode error and stops the session; snapshot reports unready/unavailable. Unknown-mode cases in `test_service_mode.py` assert no session activation and no repeated uncertain mode write |
| `gui/version_panel.py:123` | `VersionPanel._fetch.fetch` | Propagation | Future result becomes queued Qt signal and visible generic error. `test_gui_version_panel.py` verifies unexpected-error privacy, disabled stale result, and retry |
| `gui/presenter.py:53` | `GuiPresenter.refresh` | Propagation | Drops client and calls `mark_unreachable(reason)`; overview displays offline detail. Direct snapshot-failure test in `test_gui_presenter.py`; refresh control also in `tests/test_gui_presenter_failures.py` |
| `gui/presenter.py:63` | `GuiPresenter.release_all` | Propagation | Same client/model route; direct failure characterized in `tests/test_gui_presenter_failures.py`; DEBT-12 complete 2026-10-06 |
| `gui/presenter.py:72` | `GuiPresenter.begin_calibration` | Propagation | Same client/model route; direct failure characterized in `tests/test_gui_presenter_failures.py`; DEBT-12 complete 2026-10-06 |
| `gui/presenter.py:81` | `GuiPresenter.end_calibration` | Propagation | Same client/model route; direct failure characterized in `tests/test_gui_presenter_failures.py`; DEBT-12 complete 2026-10-06 |
| `gui/presenter.py:93` | `GuiPresenter.select_profile` | Propagation | Marks unreachable and returns `ApplyOutcome.UNREACHABLE`; direct generic failure characterized in `tests/test_gui_presenter_failures.py`; DEBT-12 complete 2026-10-06 |
| `gui/presenter.py:124` | `GuiPresenter.apply_configuration` | Propagation | Marks unreachable and returns `UNREACHABLE`; typed-error tests exist, direct generic failure characterized in `tests/test_gui_presenter_failures.py`; DEBT-12 complete 2026-10-06 |
| `adapters/openrazer/capabilities.py:106` | `_optional_int` | Fallback | Optional poll-rate getter failure returns `None`; missing/raising/malformed getter tests feed DEBT-04 |
| `adapters/openrazer/capabilities.py:114` | `_optional_bool` | Fallback | Optional charging getter failure returns `None`, independently of battery; DEBT-04 |
| `adapters/openrazer/capabilities.py:122` | `_optional_battery` | Fallback | Optional battery getter failure returns `None`; invalid range/type also becomes unknown; DEBT-04 |
| `adapters/openrazer/capabilities.py:132` | `_optional_firmware` | Fallback | Optional firmware getter failure returns `None`; blank/non-string also unknown; DEBT-04 |
| `adapters/openrazer/backend.py:123` | `OpenRazerBackend.rescan` | Propagation | Returns cleared unavailable state with `backend_unavailable` issue; manager/enumeration failure coverage feeds DEBT-04 |
| `adapters/openrazer/backend.py:156` | `OpenRazerBackend.rescan` | Propagation | Required-read failure returns `device_unavailable` and retains no client. `test_openrazer_backend.py` asserts cleared observed state |
| `adapters/openrazer/backend.py:219` | `OpenRazerBackend.move_dpi_stage` | Propagation | `_operation_failure` invalidates client and publishes unavailable state; uncertain read/write and no-retry tests feed DEBT-04 |
| `adapters/openrazer/backend.py:290` | `OpenRazerBackend._change_scroll_mode` | Propagation | Same unavailable-state route without mutation retry; failure coverage feeds DEBT-04 |
| `adapters/openrazer/backend.py:317` | `OpenRazerBackend._refresh_after_operation` | Propagation | Failed post-write readback clears state without repeating the mutation; DEBT-04 |

Propagation was traced beyond helper names: worker futures are awaited; production
composition publishes backend states to the runtime; service snapshots serialize
hardware/mode issues through IPC; presenter model notifications reach queued Qt
updates and visible overview detail. Optional-property errors are different:
they deliberately become unknown values rather than detailed error state.

## Tooling Handlers

| Path / Line | Function | Disposition | Evidence |
| --- | --- | --- | --- |
| `buildpython/core/runner.py:102` | `run_step` | Propagation | Produces exit-1 `RunResult` with traceback stderr, writes step log, records failed outcome/summary, and returns nonzero build status. Synthetic runner-failure test in `tests/test_buildpython_runner.py` |
| `buildpython/steps/appimage/build.py:92` | `build_appimage` | Propagation | Appends assembly-failure label/class/message to captured stderr and returns exit-1 result; runner writes it to the AppImage step log. Asset/spawn failure tests in `tests/test_appimage_build.py` preserve prior output and failed-artifact cleanup |

## Hardware-Test Handlers

Paths below are relative to `tests/hardware/`. These are static dispositions of
opt-in test source, not passing hardware evidence. Shared cleanup reports its
accumulated problems through `pytest.fail` only if subsequent teardown reaches
that boundary; aborts, cancellation, or hangs can prevent it. Lower-level suppression
can hide failures so they never enter the accumulated problems.

| Path / Line | Function / Phase | Disposition | Evidence |
| --- | --- | --- | --- |
| `test_ui06_guided.py:90` | `preflight`, discovery | Propagation | `pytest.fail` before hardware-operation body; generic message loses cause detail |
| `test_ui06_guided.py:112` | `prompt.receive` | Propagation | Sets exception on the response future awaited by `prompt`; prevents unresolved wakeup, not a success fallback |
| `test_ui06_guided.py:185` | `cleanup`, monitor stop | Cleanup with reporting | Adds monitor-stop problem, continues independent cleanup, then aggregate pytest failure |
| `test_ui06_guided.py:190` | `cleanup`, service stop | Cleanup with reporting | Adds service-stop problem and continues; does not establish worker ownership ended |
| `test_ui06_guided.py:195` | `cleanup`, session stop | Cleanup with reporting | Adds session-stop problem and continues to later sessions |
| `test_ui06_guided.py:199` | `cleanup`, first grab check | Cleanup with reporting | Adds grab-check problem before restore; open/ungrab/close failure can cause it, not only a retained grab |
| `test_ui06_guided.py:212` | `cleanup`, original mode restoration | Cleanup with reporting | Adds explicit manual-restore warning; uncertain write is not retried, backend close follows |
| `test_ui06_guided.py:218` | `cleanup`, final grab check | Cleanup with reporting | Adds final check problem then aggregate pytest failure; does not verify held-output release |
| `test_ui06_guided.py:295` | held-F17 test, saved profile load | Propagation | `pytest.fail` before worker/service creation; specific pytest skip escapes ordinary `Exception` |
| `test_ui06_guided.py:306` | held-F17 test, original mode read | Propagation | `pytest.fail` before service start; temporary backend has `finally` cleanup |
| `test_ui06_guided.py:389` | held-F17 test, main boundary | Propagation | Phase/class pytest failure, then cleanup and logging-level restoration; raw cause intentionally omitted |
| `test_ui06_sleep.py:47` | sleep/wake test, original mode read | Propagation | `pytest.fail` before worker/service creation; no invented fallback original mode |
| `test_ui06_sleep.py:120` | sleep/wake test, main boundary | Propagation | Phase/class pytest failure, then shared cleanup; inconclusive natural-sleep skip is a separate outcome |

The specific rethrow handlers at `test_ui06_guided.py:387` and
`test_ui06_sleep.py:118` catch `pytest.skip.Exception`, which is pytest's `Skipped`
outcome. Qualified identity now prevents these from being counted as builtin broad
catches. This corrects scanner definitions, not runtime debt or hardware behavior.

## BaseException Review

All paths below are relative to `src/naga_control/`. The five handlers are retained.
Existing tests mostly establish ordinary-failure rollback; interruption and
cleanup-error cases need fake characterization rather than narrower catches.

| Path / Line | Function | Safety Contract / Evidence | Follow-Up |
| --- | --- | --- | --- |
| `diagnostics/capture.py:196` | `open_sources`, inner rollback | Closes the just-opened descriptor on interrupted validation, then rethrows. Identity-mismatch ordinary failure tested in `test_diagnostic_capture.py` | DEBT-03 interruption and close-failure characterization |
| `diagnostics/capture.py:200` | `open_sources`, accumulated rollback | Closes prior siblings when a later open/validation fails, then rethrows. Partial multi-source interruption is not directly tested | DEBT-03 |
| `service/runtime.py:75` | `NagaService.start` | Stops owned startup on cancellation/failure, without stopping an already-active duplicate start; rethrows | DEBT-05 interrupted startup/cleanup evidence |
| `service/runtime.py:164` | `NagaService._start_session` | Clears provisional session, records forwarding error, awaits stop and rethrows. Ordinary activation failure tested in `test_service_mode.py` | DEBT-05 |
| `application/remapping.py:153` | `FirstSliceSession.start` | Rolls back started readers, actions, and shared outputs; rethrows. First-reader activation failure tests shared-output/action rollback in `test_first_slice_session.py`; later-reader failure rollback remains untested | DEBT-05 interruption, reader registration, and independent-cleanup failures |

## Scanner Confidence

- Local call-name and raise detection remain heuristics. Futures, returned state,
  GUI notifications, accumulated problems, and externally logged results are not
  guessed from arbitrary names or automatically marked safe.
- Imported builtin origins are terminal identities; qualified foreign names are
  not classified by their final attribute. Assignment scope/order and dynamic
  type resolution remain limitations; this is not a symbol-table analyzer.
- Waivers require real COMMENT tokens from original source. String/docstring
  examples no longer count. Lexical errors reject all partial comment results;
  tokenization does not otherwise validate syntax.
- Real tag placement, first-marker/explanation semantics, and the non-waivable
  400-line maximum remain unchanged. No budgets or waiver tags were added.
- Markdown is a sampled report; the original inventory used complete JSON and
  source inspection to account for nested handlers omitted from that sample.

## Remaining Risks

Subsequent DEBT-04 added `backend.py:246`, an intentional failure-to-state boundary
for the initial scroll-cycle read. It invalidates the stale client and publishes
`device_unavailable`; fake regressions verify no mutation retry and fresh-client
reacquisition on a later request. It is not part of the original 35-handler baseline.
DEBT-04 also characterized the four optional fallbacks and the backend failure
paths listed above; see its delivery record for current coverage and remaining gaps.

DEBT-03 moved the two original capture rollback catches to
`diagnostics/capture_sources.py:133,138` and tested interrupted accumulated opens,
identity mismatch, and ordinary close failures. The new close boundary at line
155 stores the first error for rethrow after every independent ordinary-error
cleanup attempt; its local-unlogged flag is propagation, not silence. CLI cleanup
at `diagnostics/capture_cli.py:126,132` preserves a propagating primary failure
against ordinary secondary errors and surfaces standalone close errors. Secondary
interruptions remain unsuppressed; failed close attempts are not proof of release.
The original review table remains historical, not current handler line numbers.

- Fixed backend issue messages and optional-value fallbacks lose cause detail.
  They are observable contracts, not proof of comprehensive diagnostics.
- Future cancellation can leave a late worker failure without a waiting consumer.
  Presenter direct branches now have direct failure tests (DEBT-12 complete
  2026-10-06); worker/future limits remain as documented in DEBT-05.
- At this baseline review, cleanup failures could replace primary errors or skip
  later resources. DEBT-05 subsequently reproduced and fixed ordinary-error
  ownership/precedence paths, provisional reader registration, and joinable stop.
  Failed attempts and secondary interruptions still do not prove physical release.
- Lower-level `suppress(Exception)` release/ungrab/close operations are outside
  this baseline catch inventory. Preserve best-effort teardown while DEBT-05
  characterizes failures and considers safe diagnostics outside the evdev hot path.
- Interrupted lifecycle subscription ownership was separately queued as DEBT-11
  at this review. DEBT-11 subsequently reproduced and fixed the owned-startup gap;
  see the campaign delivery record for current contracts, counts, and limitations.
  This inventory preserves the original five rollback-catch review dispositions.
- Raw exception-text diagnostics elsewhere are not made identifier-safe by this
  campaign's local lifecycle warning fix. No service-wide sanitizer is claimed.

DEBT-13 subsequently reproduced identifier-bearing capture I/O error text using
fakes and replaced normal input/read/output rendering with class/validated-errno
summaries. The existing read `OSError` boundary still returns an error result;
only its text construction changed. Normal stdout/JSON no longer receives that
payload, with either metadata setting. Direct library exception identity/chains,
the output wrapper's original cause, and existing cleanup dispositions remain.
This does not anonymize incidental input, metadata/environment fields outside the
explicit redaction list, intentional paths, historical files, or service logs.

## DEBT-05 Additions

Reviewed 2026-10-06 after implementation, fake regression tests, and independent
reviews. Original tables remain historical. The 19 added local-unlogged candidates
below are intentional error aggregation/primary precedence or test observation,
not 19 new confirmed silent failures. No scanner waiver or budget was introduced.

Product paths are relative to `src/naga_control/`:

| Path / Lines | Disposition | Evidence |
| --- | --- | --- |
| `service/source_frame_consumer.py:67` | Independent release, delayed rethrow | Planner, keyboard, and mouse release attempts continue; first error reaches the outer fail-open cleanup boundary. Lower-source fake matrix verifies all attempts |
| `service/service_cli.py:120,128,134` | Cleanup aggregation / primary precedence | Watcher join, lifecycle/service stops, and disconnect are independent; standalone first error surfaces, secondary ordinary errors deliberately do not replace a primary body failure |
| `service/runtime.py:362,367,372` | Owned shutdown result propagation | Poll, session, and worker errors accumulate; shutdown returns first error to active stop callers after joining cleanup. Cancelled callers leave cleanup owned; completed stops do not replay destruction |
| `application/remapping.py:199,204` | Session teardown aggregation | Every reader/output operation and action shutdown is attempted; first error is raised and remains cached for repeat session-stop callers and the runtime barrier |
| `application/remapping.py:216` | Independent output release | Both replacement outputs get a release attempt; first error reaches the caller after both attempts |
| `adapters/uinput/keyboard.py:142,148` | Release/SYN aggregation and fail-closed propagation | Held releases and SYN continue after ordinary failures; first error survives fallback cleanup, close is attempted once, adapter stays logically closed |
| `adapters/uinput/mouse.py:84,90` | Release/SYN aggregation and fail-closed propagation | Same contract; stateful fakes distinguish successful simulated destruction from uncertain failed close |

Test paths are relative to `tests/`:

| Path / Lines | Disposition | Evidence |
| --- | --- | --- |
| `test_service_cli_failures.py:140,165,202,265` | Intentional assertion observation | Captures primary interruption/body/cleanup outcomes for identity, ordering, and independent-attempt assertions; not success fallbacks |
| `test_service_cli_main.py:103` | Intentional assertion observation | Captures an injected main-loop outcome while validating CLI exit/error handling without running a real owner |

Seven production additions/conversions require interruption-wide rollback or
primary tracking: CLI body, session startup owner, provisional reader factory,
session factory, evdev opening, forwarding activation, and proxy readiness.
Three test observations also catch `BaseException`. This explains the count
9 -> 19; no catch-all was added to ordinary frame processing.

Five new cleanup diagnostics use fixed phase and class only, outside the frame
path, with payload/cause/traceback privacy tests. The remaining 55 raw local-
unlogged candidates include the previously reviewed boundaries; scope, naming,
and handler locations have changed. Raw increase 67 -> 93 broad catches is not
a calibrated increase in application debt: cancellation-safe ownership and
independent cleanup necessarily add reviewable boundaries.

DEBT-05 runtime and worker failure concerns are now fake-reproduced and regression-
tested, including real worker fencing with fake hardware. Failed-barrier and
terminal mutation requests cannot persist configuration, change calibration, or
construct replacement sessions. Accepted updates retain persistence-before-own-
rebuild. At DEBT-05, duplicate name replies prevented publication, not preceding
hardware initialization. DEBT-14 subsequently added early public reservation,
seven-endpoint readiness gating, and joined outer cleanup before disconnect.
The CLI aggregation handlers are now at lines 136/146/152 inside that owned
cleanup task; primary precedence and standalone first-error propagation remain.
Caller cancellation is retained/rethrown after cleanup rather than abandoning the
reservation. Stopper-origin non-ordinary interruption remains a declared limit.

DEBT-15 complete: after the constructor returns a dedicated raw bus, IPC and
OpenRazer connection factories own it until connect and wrapper creation succeed;
a pre-transfer `BaseException` attempts to disconnect that raw once while preserving
the primary error. Constructor failure has no raw to disconnect; secondary
non-ordinary interruption during disconnect is a separate limit.

## DEBT-15 Additions

Reviewed 2026-10-06 after supervisor acceptance. Original tables remain historical.
The two added boundaries are intentional pre-transfer cleanup/rethrow contracts,
not two new silent failures. No scanner waiver or budget was introduced.

Product paths are relative to `src/naga_control/`:

| Path / Lines | Disposition | Evidence |
| --- | --- | --- |
| `ipc/server.py:43` | Cleanup with rethrow | Owns the constructed raw bus until `connect()` succeeds; a pre-transfer `BaseException` attempts one synchronous raw `disconnect()` and rethrows the original error. Ordinary secondary disconnect errors are suppressed. Fake constructor/connect/cancellation/interruption and CLI-through-factory regressions in `tests/test_dbus_connection_rollback.py` |
| `adapters/openrazer/lifecycle_monitor.py:239` | Cleanup with rethrow | Owns the constructed raw bus until `connect()` and wrapper creation succeed; a pre-transfer `BaseException` attempts one synchronous raw `disconnect()` and rethrows the original error. Ordinary secondary disconnect errors are suppressed. Fake connect/cancellation/interruption/wrapper-failure and real-factory monitor-retry regressions in `tests/test_openrazer_connection_factory.py` and `tests/test_openrazer_factory_monitor.py` |

A disconnect attempt is not proof of socket release; constructors failing before
object return are library-internal and separate. Primary identity is preserved
only against ordinary secondary errors; secondary non-ordinary interruption is a
separate limit.

## DEBT-12 Additions

Reviewed 2026-10-06 UTC after supervisor inspection and independent review
with no blocking issues. Original product table rows above remain historical;
the six presenter handlers are unchanged source. Direct-failure coverage is now
complete for `gui/presenter.py:53,63,72,81,93,124` in
`tests/test_gui_presenter_failures.py` (349 lines, 10 cases). No product catch
was narrowed, removed, or annotated; no waiver or budget was introduced.

Product paths are relative to `src/naga_control/`:

| Path / Lines | Disposition | Evidence |
| --- | --- | --- |
| `gui/presenter.py:53` | Propagation, now covered | Healthy-then-failing refresh control: one close, `reachable False` + reason, revision unchanged, listener notified |
| `gui/presenter.py:63` | Propagation, now covered | Release-all failure: op not recorded, no readback, one close, `reachable False` + reason, offscreen overview `offline` detail |
| `gui/presenter.py:72` | Propagation, now covered | Begin-calibration failure: same close/unreachable/no-readback contract |
| `gui/presenter.py:81` | Propagation, now covered | End-calibration failure with empty `RuntimeError()`: `detail == "RuntimeError"` type fallback |
| `gui/presenter.py:93` | Propagation, now covered | Generic select-profile failure returns `UNREACHABLE` with no `selected` and no readback; typed `UnknownProfile` still returns `INVALID` and stays reachable |
| `gui/presenter.py:124` | Propagation, now covered | Generic apply failure returns `UNREACHABLE` with no `applied` and unchanged revision; typed `Stale`/`Invalid` still return `STALE`/`INVALID` and stay reachable |

Fresh-client recovery and shared close-error recovery are covered: after a
dropped client, the next `refresh` opens a new healthy client, publishes the
new snapshot/config/revision, and leaves the old client unused; an ordinary
close error still marks unreachable and permits reacquisition. Existing
behavior was already correct (GREEN first, no false RED). Standard gates
passed; the extended run failure is a separate pre-existing ShellCheck
baseline (`SC2012` at `buildpython/steps/appimage/AppRun` line 7), not a
presenter regression.

## DEBT-12 Characterization Notes (complete 2026-10-06, supervisor accepted)

Replaces the earlier in-progress note. See the DEBT-12 Additions table above
for per-handler evidence. No product, logging, or redaction change was made.
