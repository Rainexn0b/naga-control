# Debt Paydown Campaign

## Purpose

This is the planning and tracking document for reducing Naga Control's technical
debt after the build-layout consolidation. Prioritize recovery diagnostics,
behavioral coverage, and maintainable ownership boundaries over making scanner
scores look better. This campaign does not add product features or replace the
[architecture](architecture.md), [implementation plan](implementation-plan.md),
or [hardware validation](hardware-validation.md) contracts.

Campaign status: **started; DEBT-01/02/11/04/03/05/14/13/15/12/06 complete; DEBT-09 ShellCheck subset complete (whole item blocked on Docker), DEBT-07 in progress (types committed `643d791`; campaign acceptance blocked: active shared build-report ownership prevents full/extended/package gate start; focused 477 plus Ruff/format/Pyright pass; no completion claimed); DEBT-08/10 queued**.
Baseline commit: `4baf4e8` (`Build: consolidate AppImage packaging and validation`).
Baseline date: 2026-10-05.

## Commit Checkpoint (2026-10-07)

This checkpoint records implementation being committed in small logical groups,
including DEBT-07 types (`643d791`), and supervisor-run standard safety checks:

- `.venv/bin/ruff check .`: passed; `.venv/bin/ruff format --check .`: passed
  (371 files formatted); `.venv/bin/pyright`: 0 errors, 0 warnings.
- `.venv/bin/pytest -q`: 2,718 passed, 2 optional coverage skips (coverage
  unavailable), 5 hardware deselected, 8 dependency warnings, 151.31 seconds.
  Explicit release/package-tool Pyright, Bash syntax, and ShellCheck also passed.
- Approved installer work resolved the historical extraction-preflight failure:
  managed installs require FUSE; extraction is manual-only. A later focused
  installer run passed 328 tests, resolving the earlier 120-second repeat timeout.
  Dated delivery records, failed-gate evidence, and counts below remain historical.
- DEBT-07 remains in progress: buildpython default/extended 17-step campaign and
  package gates have not been rerun here; no new coverage/debt/ratchet measurements
  or campaign completion are claimed. DEBT-08/10 stay queued, Docker stays blocked,
  and physical gates stay open. The supervisor's final standard rerun passed;
  its results are recorded above, not as extended or hardware acceptance.
- The user's v0.5.0 is a future checkpoint only: no version bump, tag, or release
  is created by this checkpoint; no deployment or live-service change is included.

## Baseline

The default buildpython run passed all nine checks, with 955 tests passed and two
optional coverage tests skipped. An extended run using temporary Coverage and
Vulture tools passed 16 checks, skipped ShellCheck, and passed all 957 tests.
Its run ID was `7a15fa98-2a0b-4233-a74c-91632ec85a04`.

| Area | Starting Measurement | Interpretation |
| --- | --- | --- |
| Product statement coverage | 90.06%; 5,616 / 6,236 statements, 89 files | Measures `src/naga_control`, not buildpython or scripts; not branch coverage |
| Architecture | 0 errors, 0 warnings | Preserve the existing headless/domain/GUI boundaries |
| Python file limit | 0 files above 400 physical lines | Hard invariant, including tests and tooling |
| Size watchlist | 18 files at 350-400 lines | 5 product modules, 4 tooling modules, 9 test files |
| Broad exception catches | 63 total; 35 classified as unlogged; 5 catch `BaseException` | Static classifications, not 35 confirmed silent failures |
| Code hygiene | 38 flags: 1 silent, 10 logged, 21 fallback catches, 6 `Any` annotations | Overlaps the exception report; do not add these counts together |
| Import blocks | 19 warning-level, 5 critical-level hotspots | Heuristics, not architectural violations |
| Flat directories | 7 hotspots | Includes 75 direct Python files under `tests/` |
| Dead code | 7 candidates, all in tests; 0 actionable unused-symbol findings | Review intentional test sentinels before deleting anything |
| TODO/FIXME/HACK | 0 markers | Absence of markers is not absence of debt |
| Structural candidates | 0 delegation, middle-man, or unreferenced-file candidates | No cleanup queue justified by these scanners currently |

Debt budgets in `buildpython/config/debt_baselines.json` are unset. Therefore,
"no regressions" does not establish a ratchet against these starting counts.
Penalty-based health scores, including saturated 0% scores, are not a calibrated
measure of application correctness or a campaign target.

Generated evidence lives under `buildlog/naga-control/`: `debt-index.md`,
`build-summary.md`, `coverage-summary.md`, `code-hygiene.md`,
`exception-transparency.md`, `file-size-analysis.md`, and `dead-code-vulture.md`.
These files are ignored, local, and overwritten by later runs. Keep historical
measurements and decisions in this document; do not commit raw logs or captures.

## Working Rules

- Keep only one item in progress. Use small, reviewable changes with regression
  tests; do not refactor the input state machine in parallel.
- Preserve supported USB IDs, physical USB-parent discovery, proxy-before-grab,
  held-action resolution, output reference counts, and fail-open cleanup.
- Keep filesystem, GUI, and blocking OpenRazer operations off the evdev read and
  forwarding path. OpenRazer remains the hardware-control backend.
- Do not narrow safety-cleanup catches merely to remove a warning. Preserve
  cancellation, release, disconnect, and shutdown behavior; prove changes with fakes.
- Do not turn transient failures into log floods. Diagnostics must be actionable,
  identifier-redacted, and outside the event forwarding hot path.
- Split by responsibility, not by line count alone. Do not add forwarding facades,
  compatibility shims, or a new framework to move debt elsewhere.
- Do not remove reachable behavior, inflate coverage with assertion-free tests,
  add blanket coverage exclusions, or waive the 400-line maximum.
- Default checks must not read, grab, or write real devices. Hardware checks stay
  opt-in and follow the existing interactive safety gates.
- Do not install an AppImage, restart the live service, run as root, or publish a
  release as part of debt work without explicit approval.
- Classification and budgets need evidence. An intentional boundary is not a
  bug; an annotation is not a substitute for diagnostics or a regression test.

## Queue

Statuses: **queued**, **in progress**, **blocked**, **complete**, **deferred**.
Complete means acceptance and verification evidence are recorded. Deferral needs
a reason and an explicit decision, not a skipped check disguised as completion.

| ID | Priority | Work Item | Status | Dependency |
| --- | --- | --- | --- | --- |
| DEBT-01 | P1 | Lifecycle rescan diagnostics | complete | Verified 2026-10-05; delivery record below |
| DEBT-02 | P1 | Exception inventory and scanner confidence | complete | Verified 2026-10-05; inventory and delivery record below |
| DEBT-03 | P2 | Capture CLI behavioral coverage | complete | Verified 2026-10-05; CLI 99.15%, source ownership 98.08% |
| DEBT-04 | P1 | OpenRazer backend failure/recovery coverage | complete | Verified 2026-10-05; backend 92.68%, capabilities 100% |
| DEBT-05 | P2 | IPC, service CLI, and uinput boundary coverage | complete | Verified 2026-10-06; all four target files exceed 85% |
| DEBT-06 | P2 | Source and test file headroom | complete | Verified 2026-10-07; closure decision below; 3 reviewed retained exceptions plus 1 concurrent externally owned file |
| DEBT-07 | P3 | Concrete Qt event/future annotations | in progress (campaign acceptance blocked) | Types committed `643d791`; active shared build-report ownership prevents full/extended/package gate start; focused 477 plus Ruff/format/Pyright pass; dated 2026-10-08 external uninstaller lint/type failure records retained below; no completion or new measurements claimed |
| DEBT-08 | P3 | Structure and dead-code disposition | queued | DEBT-02 scanner review; DEBT-06 |
| DEBT-09 | P1 | Docker and ShellCheck verification gaps | blocked (ShellCheck subset complete; Docker pending) | ShellCheck now available and passing; Docker still unavailable per DEBT-15 package check and 2026-10-06 packaging check |
| DEBT-10 | P2 | Reviewed, reproducible debt ratchets | queued | DEBT-02 through DEBT-08 reviewed |
| DEBT-11 | P1 | Interrupted lifecycle startup ownership | complete | Verified 2026-10-05; delivery record below |
| DEBT-12 | P2 | Presenter error-propagation characterization | complete | DEBT-02 identified missing direct failure tests; verified 2026-10-06; delivery record below |
| DEBT-13 | P2 | Capture error-text privacy review | complete | Verified 2026-10-06; CLI/stdout/JSON error payloads excluded with both metadata modes |
| DEBT-14 | P1 | Singleton reservation before hardware startup | complete | Verified 2026-10-06; early public reservation, wire readiness, joined cleanup |
| DEBT-15 | P2 | Pre-transfer D-Bus connection cleanup | complete | Verified 2026-10-06; delivery record below |

Delivery order: DEBT-01, DEBT-02, DEBT-11, DEBT-04, DEBT-03, DEBT-05, DEBT-14, DEBT-13, DEBT-15, DEBT-12, DEBT-09 (ShellCheck subset; Docker component still blocked), DEBT-06,
DEBT-07, DEBT-08, DEBT-10. Docker verification remains blocked until a suitable environment is
available. Test-only splits may precede an item if its test file lacks headroom.

## Work Specifications

### DEBT-01: Lifecycle Diagnostics

Confirmed gap: `OpenRazerLifecycleMonitor._run()` in
`src/naga_control/adapters/openrazer/lifecycle_monitor.py` catches rescan failures
with `except Exception: pass` (baseline line 173). A provider or controller
failure disappears without a diagnostic.

- Add useful diagnostics without changing topology fencing, debounce, or recovery
  policy. Do not couple a diagnostic fix to retry or device-mode redesign.
- Add fake provider-failure and controller-failure tests that assert the diagnostic
  and demonstrate that a later rescan can succeed.
- Preserve cancellation and shutdown behavior, and redact device identifiers.
- Acceptance: no silent catch remains on this rescan path; targeted lifecycle
  tests and standard checks pass. Record the reviewed remaining cleanup catches.

### DEBT-02: Exception Classification

Review findings in the lifecycle monitor, hardware worker, service runtime,
OpenRazer backend/capabilities, GUI presenter, and build runner. Separate product,
tooling, and test findings rather than treating the combined count as production
risk. The scanner does not follow failure propagation through futures or GUI
model updates; those can be mislabeled as unlogged.

- Classify each reviewed catch as a diagnostic gap, intentional cleanup/rethrow,
  intentional error propagation/fallback, or scanner false positive.
- Preserve `BaseException` cleanup paths that re-raise and release resources.
  Assess the five catches individually; do not globally replace them.
- Add small scanner regression fixtures where classification is demonstrably
  wrong. The file-size report also mistakes an exception-tag string in
  `tests/test_buildpython_analysis.py` for a real waiver; verify comment parsing.
- Acceptance: every one of the 35 baseline "unlogged" findings has a disposition;
  confirmed gaps have follow-up IDs. Corrected scanner counts have a new labeled
  measurement, not a claim that code debt vanished through refactoring.

Completed dispositions and confidence limitations are in the
[Exception Boundary Inventory](debt-exception-inventory.md). Coverage follow-ups
feed DEBT-03/04/05/12; the separate startup ownership concern remains DEBT-11.

### DEBT-03: Capture CLI Coverage

Baseline: `src/naga_control/diagnostics/capture_cli.py` has 50.00% statement
coverage. Inspect missing statements before choosing cases.

- Cover argument validation, list versus capture dispatch, redacted output,
  output-file failures, and interruption/error exits with injected fakes and
  temporary paths where those branches are uncovered.
- Assert observable exit codes and output, not just execution. No real discovery,
  filesystem access under `/dev`, or physical capture is permitted.
- DEBT-02 follow-up: characterize accumulated-source rollback under interruption
  and close failure before altering the retained `BaseException` cleanup catches.
- Acceptance: meaningful missing behaviors are characterized; aim for at least
  80% statement coverage in this file. Any remaining physical-only path has a
  documented verification gap rather than a blanket coverage exclusion.

### DEBT-04: OpenRazer Recovery Coverage

Baseline: `adapters/openrazer/backend.py` has 72.91% coverage and
`adapters/openrazer/capabilities.py` has 78.57%, under `src/naga_control/`.

- Prioritize malformed/missing capability replies, daemon/device disappearance,
  stale clients, wireless reacquisition, and uncertain write/refresh failures.
- Assert resulting state/errors and hardware-call order. Verify that uncertain
  mutations are not retried and conflicts do not mutate hardware.
- Use the existing fake ports; tests must not instantiate a real hardware owner.
- Acceptance: reviewed missing safety-relevant branches have behavioral tests;
  aim for at least 85% backend coverage. Changes to recovery policy need their
  own scoped item and hardware gate, not an incidental test-driven rewrite.

### DEBT-05: Boundary Coverage

Starting files: `ipc/server.py` (72.22%), `service/service_cli.py` (73.13%),
`adapters/uinput/mouse.py` (75.68%), and `adapters/uinput/keyboard.py` (76.40%),
under `src/naga_control/`.

- Deliver separately scoped tests for startup failures, bus publication/disconnect,
  cancellation/teardown, output-write failure, and held-output cleanup as indicated
  by the missing-line report.
- Fake the session bus, signals, and device descriptors; do not start or disturb
  the installed service. Maintain event ordering and release behavior.
- DEBT-02 follow-ups: worker exception/future-cancellation propagation, interrupted
  session startup, pre-registration reader ownership, and independent cleanup
  attempts after release/close errors. Reproduce concerns before asserting leaks.
- Acceptance: targeted failure contracts are asserted, with a provisional 85%
  coverage goal per file. Record any evidence-backed exclusions or remaining gaps.

### DEBT-06: File Headroom

Immediate watchlist: `tests/test_service_runtime.py` (400), GUI tray/version tests
(399 each), `tests/test_appimage_build.py` (392), and product capture (392),
buttons page (390), service runtime (390), OpenRazer backend (380), and GUI app
(379). Full file paths and other candidates are in the baseline file-size report.

- Begin with test responsibilities to create space for new failure cases.
- Split product code only where distinct responsibilities and dependencies justify
  extraction; characterize behavior before moving it, especially forwarding state.
- Review tooling hotspots as well; adding a large analysis framework creates its
  own maintenance burden. Prefer deletion/simplification of unused machinery over
  multiplying helpers, but prove reachability first.
- Acceptance: every watchlist item touched by this campaign has usable headroom;
  aim for under 350 lines where a coherent split exists. Exceptions below the hard
  maximum need a written rationale. All Python files remain at or below 400 lines.

### DEBT-07: Qt Types

The six `Any` flags are in `src/naga_control/gui/app.py` and `mapping_map.py`.
Use concrete Qt event types and the actual future contract where appropriate.

- Retain correct Qt override signatures and GUI ownership boundaries.
- Acceptance: the six baseline annotations are replaced or individually justified;
  strict Pyright and the relevant offscreen GUI tests pass.

### DEBT-08: Structure And Dead Code

Review the 24 long import blocks, seven flat directories, and seven test-only
Vulture candidates. No production unused-symbol deletion is currently justified.

- Keep deliberate test sentinels and fail-fast fakes. Remove only proven redundancy.
- Treat import length and directory flatness as navigation signals, not reasons to
  introduce barrel imports, facades, or cosmetic directory churn.
- Acceptance: candidates have keep/remove/refactor dispositions, with regression
  evidence for changes. Record why retained warnings are acceptable.

### DEBT-09: Verification Environment

Docker and ShellCheck were unavailable at baseline. A host AppImage build and
runtime checks passed, but these do not establish clean Ubuntu compatibility.

- Use an approved development or CI environment with the required tools; do not
  assume permission to install system packages or start privileged Docker services.
- Run the ShellCheck step and the existing Ubuntu 24.04 Docker smoke against an
  artifact built for a compatible host baseline. No device mounts or live service.
- Acceptance: both checks pass and tool/container versions are recorded. Aarch64
  execution and interactive hardware validation remain separate verification gaps.

### DEBT-10: Debt Ratchets

After classification and stabilization, choose small, reviewed budgets in
`buildpython/config/debt_baselines.json`. Do not freeze today's raw findings as
acceptable merely to establish a green gate.

- Select reproducible file-specific coverage floors and genuinely actionable
  diagnostic/structure categories; preserve the existing hard architecture/LOC gates.
- Demonstrate that a synthetic regression fails and legitimate boundary handling
  remains allowed. Avoid absolute paths and machine-specific budgets.
- Acceptance: selected budgets and rationale are documented, default/relevant
  profiles enforce them as intended, and baseline-exceeding fixtures fail.
- A changing coverage denominator or scanner definition requires an explicit
  baseline update, never a silent reset of campaign history.

### DEBT-11: Interrupted Lifecycle Startup

Code review during DEBT-01 identified a pre-existing ownership gap: cancellation
while `OpenRazerLifecycleMonitor.start()` awaits `add_match()` bypasses its
ordinary-exception cleanup. A handler, partial subscriptions, and possibly a
signal-triggered runner could remain attached. The CLI previously only stopped a
lifecycle monitor after its `start()` returned. Fakes reproduced both gaps;
owned-startup rollback and CLI cleanup responsibility now cover them.

- Reproduce cancellation at first/later subscriptions and a signal during partial
  startup. Account for a remotely completed match whose reply was interrupted.
- Clean up the owned bus, handler, known matches, and any runner while preserving
  the original cancellation/exception and a deliberate restart/stopped contract.
- Acceptance: fake boundary and CLI tests demonstrate cleanup without orphaned
  work. Do not broaden rescan catches or change retry, mode, or debounce policy.
  Bus-factory cancellation before ownership transfer is a separate boundary.

### DEBT-12: Presenter Propagation Tests

DEBT-02 traced six presenter catch paths to visible unreachable state, but only
snapshot-read failure is directly tested. Use fake clients to fail release-all,
begin/end calibration, select-profile, and generic configuration apply.

- Assert outcomes, model detail, client disposal/reacquisition, and visible failure.
- Acceptance: each direct failure branch has a behavioral test; preserve typed
  configuration errors and Qt ownership. No GUI redesign or blanket local logging.

### DEBT-13: Capture Error-Text Privacy

Default metadata redaction was tested, but input-error diagnostics printed raw
exception messages, and frame-reader errors persisted them in `end_reason`.
Injected identifier-bearing errors reproduced those paths; DEBT-13 now uses
class/validated-errno summaries for normal output and owned read-error reasons.
No physical identifier leak was exercised.

- Review phase/type/errno diagnostics versus raw text, including persisted JSON and
  identifier opt-in. Preserve useful disconnect/error outcomes and source ordering.
- Acceptance: fake sensitive-message regressions prove the chosen default privacy
  contract for error paths, not only metadata. No raw identifiers enter fixtures.

### DEBT-14: Singleton Startup Reservation

DEBT-05 rejects unsuccessful publication without stealing or queueing the name,
but previously initialized the service before requesting that name. DEBT-14 now
exports a gated interface and reserves the existing public name before startup.
Fake traces verify zero hardware-owning startup calls on duplicate rejection;
physical duplicate effects were not exercised.

- Define reservation versus ready/publication ordering before hardware-owning
  startup. Account for early GUI requests and rollback of an acquired reservation.
- Acceptance: fake duplicate-owner cases prove zero hardware-owning startup calls;
  failure/cancellation releases reservation ownership and successful publication
  preserves the IPC readiness contract. No replacement flags or root process.
- Do not describe DEBT-05's publication fix as prevention of duplicate hardware
  initialization. This is a separate startup-policy change and verification item.

### DEBT-15: Connection Factory Rollback

Default service/OpenRazer bus factories construct a raw connection and then await
`connect()` before transferring ownership. Cancellation in that await is not the
CLI's owned-connection/reservation boundary. Source inspection found incomplete
pre-transfer rollback; descriptor leakage has not been fake-reproduced yet.

- Fake constructor/connect failures and interruption; establish who owns the raw
  connection and prove rollback preserves the primary failure against close errors.
- Acceptance: every returned or partially acquired connection has a defined owner;
  no real bus/device access, accidental shared-connection disconnect, or namespace
  replacement. Keep public readiness and hardware startup policy unchanged.

## Verification Routine

Run the standard checks after each implementation item:

```bash
.venv/bin/python -m buildpython
```

For the campaign-wide measurement, make optional analysis tools available in a
development environment. One explicit installation option is
`.venv/bin/python -m pip install 'coverage>=7,<8' 'vulture>=2,<3'`; the baseline
instead supplied them from a temporary tools directory. ShellCheck is a separate
system tool. Run tests and coverage in the same invocation so the capture is fresh:

```bash
.venv/bin/python -m buildpython --run-steps "Compile,Ruff,Ruff Format,Type Check,Pytest,Import Validation,Import Scan,Code Markers,File Size,LOC Check,Repo Validation,Code Hygiene,Architecture Validation,Coverage,Exception Transparency,Dead Code,ShellCheck" --continue-on-error
```

`--profile debt` alone is static analysis: it does not capture coverage or run
tests. A skipped check means unverified, even if the command exits zero. Record
tool availability, test counts, source scopes, and scanner-definition changes.
Build/smoke an AppImage when runtime imports, installation assets, or assembly
change; do not automatically deploy it. Hardware assertions require the separate
opt-in validation process, not an API-driven unattended run.

## Tracking

For each item, update the queue and append a delivery record with: ID, owner,
start/completion date, baseline and resulting commit, affected paths, findings
and dispositions, acceptance evidence, exact commands/results, before/after
measurements, remaining risks, and follow-up IDs. Record blocked/deferred work
with its blocker or approval. Do not mark implementation complete on intent.

| Date | Commit / Run | Outcome | Coverage | Files >400 / Watchlist | Diagnostic Gap Status |
| --- | --- | --- | --- | --- | --- |
| 2026-10-05 | `4baf4e8`; extended run `7a15fa98-2a0b-4233-a74c-91632ec85a04` | 16 passed, ShellCheck skipped; 957 tests passed | 90.06% product statements | 0 / 18 | DEBT-01 confirmed and queued |
| 2026-10-05 | DEBT-01 uncommitted work on `4baf4e8`; run `ed5d0519-3a96-45d8-897c-cbb87c835680` | 16 passed, ShellCheck skipped; 966 tests passed | 90.07%; 5,625 / 6,245 statements | 0 / 18 | Silent rescan catch resolved; 34 scanner-classified unlogged catches remain |
| 2026-10-05 | DEBT-02 uncommitted work on `4baf4e8`; run `386a8c55-43ee-430f-84a8-8b4bfad66f0b` | 16 passed, ShellCheck skipped; 1,090 tests passed | 90.07%; product denominator unchanged | 0 / 18 | All 35 original findings classified; 34 heuristic candidates retained; corrected broad total 61 |
| 2026-10-05 | DEBT-11 uncommitted work on `4baf4e8`; run `a22aed1f-4516-4297-aff8-fdd120edd45a` | 16 passed, ShellCheck skipped; 1,119 tests passed | 90.17%; 5,642 / 6,257 statements | 0 / 18 | Interrupted owned-startup rollback tested; 34 local-diagnostic candidates retained |
| 2026-10-05 | DEBT-04 uncommitted work on `4baf4e8`; run `70dc0f3c-7c43-4f73-b19a-9b555ca14bef` | 16 passed, ShellCheck skipped; 1,309 tests passed | 91.15%; 5,705 / 6,259 statements | 0 / 18 | Initial scroll read now clears stale state; malformed optional battery remains unknown |
| 2026-10-05 | DEBT-03 uncommitted work on `4baf4e8`; run `fd97ef15-008a-4245-bbe6-f54390192e52` | 16 passed, ShellCheck skipped; 1,452 tests passed | 92.01%; 5,794 / 6,297 statements, 90 files | 0 / 17 | Capture cleanup preserves primary failures; CLI rejects non-finite duration and separates output errors |
| 2026-10-06 | DEBT-05 uncommitted work on `4baf4e8`; run `5fe76d34-5b89-4255-aded-09bee54e0bc0` | 16 passed, ShellCheck skipped; 1,915 tests passed | 93.53%; 6,083 / 6,504 statements, 92 files | 0 / 17 | Independent cleanup, owned shutdown, retained unsafe-session barrier, and publication rejection verified |
| 2026-10-06 | DEBT-14 uncommitted work on `4baf4e8`; run `b79601c6-7a64-4b8d-b4a7-94df7f808a77` | 16 passed, ShellCheck skipped; 2,030 tests passed | 93.70%; 6,145 / 6,558 statements, 92 files | 0 / 17 | Duplicate reservation blocks startup; queued wire calls and cancelled cleanup preserve ownership/readiness |
| 2026-10-06 | DEBT-13 uncommitted work on `4baf4e8`; run `91e15f8d-bf04-4890-b462-a47c32c614ac` | 16 passed, ShellCheck skipped; 2,156 tests passed | 93.75%; 6,164 / 6,575 statements, 92 files | 0 / 17 | Capture errors exclude messages/filenames/chains; explicit metadata opt-in and library causes remain |
| 2026-10-06 | DEBT-15 uncommitted work on `bb32ac9` (historical baseline `4baf4e8`); run `1c9d2b67-009a-4ecc-9c53-9d02e8192b6f` | 16 passed, ShellCheck skipped; 2,177 tests passed | 94.04%; 6,196 / 6,589 statements, 92 files | 0 / 17 | Pre-transfer raw rollback tested; constructor-return ownership and primary preservation verified |
| 2026-10-06 | DEBT-12 uncommitted work on `bb32ac9` (historical baseline `4baf4e8`); run `0f12a195-8203-4652-a7f5-7294db479b70` | 16 passed, ShellCheck FAILED exit 1 (not skipped); 2,191 tests passed | 94.29%; 6,213 / 6,589 statements, 92 files | 0 / 17 | Presenter direct branches characterized; ShellCheck baseline failure separate, standard profile still passing |
| 2026-10-06 | DEBT-09 ShellCheck subset on `bb32ac9`; extended run `ae12bf1a-e3fe-48eb-b862-331e3d2a1a32` | 17 passed, 0 failed, 0 skipped; 2,200 tests passed | 94.29%; 6,213 / 6,589 statements, 92 files | 0 / 17 | ShellCheck subset complete; whole item blocked on Docker |
| 2026-10-06 | DEBT-06 cohort1 uncommitted work on `bb32ac9` (historical baseline `4baf4e8`); run `f37f8d93-36e8-4bad-ae38-58dd9c857f16` | 17 passed, 0 failed, 0 skipped; 2,201 tests passed | 94.29%; 6,213 / 6,589 statements, 92 files | 0 / 16 | Runtime fakes split verified; whole DEBT-06 not complete |
| 2026-10-07 | DEBT-06 cohort2 uncommitted work on `bb32ac9` (historical baseline `4baf4e8`); run `2bdd2c82-7b63-4422-ac64-bac239a31150` | 17 passed, 0 failed, 0 skipped; 2,203 tests passed | 94.29%; 6,213 / 6,589 statements, 92 files | 0 / 14 | Tray/version fakes splits verified; whole DEBT-06 not complete |
| 2026-10-07 | DEBT-06 cohort3 uncommitted work on `bb32ac9` (historical baseline `4baf4e8`); run `ced65ff4-0670-4752-b8c5-304860ee3ab0` | 17 passed, 0 failed, 0 skipped; 2,205 tests passed | 94.29%; 6,213 / 6,589 statements, 92 files | 0 / 12 | AppImage/service-mode fakes splits verified; whole DEBT-06 not complete |
| 2026-10-07 | DEBT-06 cohort4 uncommitted work on `bb32ac9` (historical baseline `4baf4e8`); run `1a14843a-4e50-45b2-be98-442d0911bae2` | 17 passed, 0 failed, 0 skipped; 2,208 tests passed | 94.29%; 6,213 / 6,589 statements, 92 files | 0 / 9 | Mouse/buttons/tray-profile splits verified; whole DEBT-06 not complete |
| 2026-10-07 | DEBT-06 cohort5 uncommitted work on `bb32ac9` (historical baseline `4baf4e8`); run `f6601f24-1814-4e25-8407-b785f56f3ee4` | 17 passed, 0 failed, 0 skipped; 2,218 tests passed | 94.29%; 6,213 / 6,589 statements, 92 files | 0 / 7 | Exception-transparency/debt-index tooling splits verified; whole DEBT-06 not complete |
| 2026-10-07 | DEBT-06 cohort6 uncommitted work on `bb32ac9` (historical baseline `4baf4e8`); run `f0e5ccb8-bd76-4232-ae00-f1bda1f02e7c` | 17 passed, 0 failed, 0 skipped; 2,469 tests passed | 94.29%; 6,213 / 6,589 statements, 92 files | 0 / 5 | Architecture rule-loading/call-findings tooling splits verified; whole DEBT-06 not complete |
| 2026-10-07 | DEBT-06 cohort7 uncommitted work on `bb32ac9` (historical baseline `4baf4e8`); run `682d0254-4e2a-4101-b98a-fad1ec89792a` | 17 passed, 0 failed, 0 skipped; 2,562 tests passed | 94.31%; 6,227 / 6,603 statements, 94 files | 0 / 4 | GUI ownership splits verified; whole DEBT-06 not complete |

Preserve the starting row and append measurements rather than overwriting it.

### DEBT-01 Delivery Record

- Owner: main implementation agent, with separate regression-test and safety-review
  sub-agents. Started and completed 2026-10-05.
- Baseline: `4baf4e8`. Result: uncommitted changes; no delivery commit created.
- Changed paths: `src/naga_control/adapters/openrazer/lifecycle_monitor.py`,
  `tests/test_openrazer_lifecycle_diagnostics.py`, and this campaign tracker.
- Diagnostics: warning includes only the failing phase and exception class; no
  exception message, device identity, traceback, or exception object is logged.
  Distinct phase/class pairs warn once per unsuccessful sequence. Suppression
  resets after a complete non-raising rescan attempt, not merely discovery success.
  There are no timed reminders; absence of further warnings does not imply recovery.
- Behavioral scope: no retry, topology-fencing, debounce, cancellation, or
  hardware/input ownership policy changed. The catch remains `Exception`.
- Regression evidence: eight new fake test cases cover both failure sources,
  later-signal recovery, duplicate suppression, changed phase/class diagnostics,
  reset after complete recovery, in-flight controller cancellation, listener
  teardown, immediate fencing, and burst coalescing. Sub-agent review found no
  blocking regression. Initial tests failed on missing warnings before the fix.
- Targeted command: `.venv/bin/pytest -q tests/test_openrazer_lifecycle_monitor.py tests/test_openrazer_lifecycle_diagnostics.py`;
  14 passed.
- Standard commands: `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`,
  and `.venv/bin/pyright`; all passed (0 type errors/warnings).
  `.venv/bin/python -m buildpython`: 9/9 checks passed, 964 tests passed,
  2 optional coverage tests skipped, 8 warnings.
- Extended command: the exact 17-step command in Verification Routine prefixed
  with `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools`. Temporary tools were
  Coverage 7.16.2 and Vulture 2.16. Result: 16 passed, ShellCheck skipped,
  966 tests passed, 8 warnings; run status correctly remains partial.
- Measurements: product statement coverage 90.06% -> 90.07%; current lifecycle
  module coverage 80.28% (114/142 statements). Silent hygiene catches 1 -> 0;
  unlogged broad catches 35 -> 34; total broad catches remain 63. Total hygiene
  flags remain 38 because the rescan catch is now classified as logged, not removed.
  No scanner definitions or budgets changed. Architecture remains 0 violations;
  source/test files are 251/326 physical lines, respectively; size watchlist stays 18.
- Remaining cleanup dispositions: startup ordinary exceptions clean up and rethrow;
  `stop()` deliberately consumes its requested runner cancellation; handler/match
  removal and disconnect are best-effort so one teardown error does not stop the
  rest. These catches are retained, not narrowed for scanner scores. This does
  not guarantee successful detachment under every failure.
- Follow-ups: DEBT-02 reviews the remaining classifications; DEBT-11 tracks the
  separately identified startup-cancellation ownership gap. Cancellation during
  threaded discovery does not terminate the underlying thread and remains outside
  the new in-flight controller-cancellation test. Privacy improvement is local to
  this diagnostic, not a service-wide exception sanitizer. No hardware validation,
  AppImage rebuild/install, live service restart, or release action was performed.

### DEBT-02 Delivery Record

- Owner: main agent with disjoint product/tooling/hardware-source inventory,
  comment-parser implementation, scanner-test, and independent review sub-agents.
  Started and completed 2026-10-05; baseline `4baf4e8`, result uncommitted.
- Inventory: [35 original handlers and all five BaseException catches](debt-exception-inventory.md).
  No additional wholly silent failure found among those handlers; intentional
  propagation/fallback remains a review disposition, not a waiver or proof of safety.
- Changed tooling: `quality_exceptions.py`, `step_loc_check.py`,
  `file_size_analysis/scanning.py`, `exception_transparency/scanner.py`, and
  `exception_transparency/reporting.py`, under `buildpython/steps/`.
- Added `tests/test_buildpython_quality_exceptions.py` and
  `tests/test_buildpython_exception_transparency.py`. Actual COMMENT tokens replace
  string-based extraction; original source and physical handler alignment survive
  source separators. Genuine builtin aliases/tuples remain recognized while
  `pytest.skip.Exception` and foreign/relative exception identities are excluded.
- Review caught imported-origin shadowing and reconstructed-source regressions;
  both were fixed and covered before delivery. Independent re-review found no new
  concrete issues. No product or hardware-test behavior changed in this item.
- Exact targeted command: `.venv/bin/pytest -q tests/test_buildpython_exception_transparency.py tests/test_buildpython_quality_exceptions.py tests/test_buildpython_analysis.py tests/test_buildpython_runner.py tests/test_buildpython_safety.py`;
  158 passed, 2 optional coverage tests skipped. New scanner files alone: 122 passed.
- `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, and
  `.venv/bin/pyright` passed using the configured project scopes.
  `.venv/bin/python -m buildpython`: 9/9 checks passed, 1,088 tests passed,
  2 optional coverage tests skipped, 8 warnings.
- Extended command: exact Verification Routine command with
  `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools`; Coverage 7.16.2 and Vulture
  2.16. Result: 16 passed, ShellCheck skipped, 1,090 tests passed, 8 warnings.
  Run `386a8c55-43ee-430f-84a8-8b4bfad66f0b` remains partial, not fully verified.
- Revised-definition measurements: broad total 63 -> 61 solely from excluding the
  two specific pytest skip catches. Unlogged remains 34, `BaseException` remains 5,
  waivers/valid annotations remain 0, hygiene remains 38, product coverage remains
  90.07%. This is scanner correction, not removal of two runtime safety boundaries.
- File-size waivers 1 -> 0: fixture strings no longer exempt the analysis test.
  Import warnings 19 -> 21: the restored analysis import block and the new
  quality-comment test import block are now visible. Critical imports remain 5;
  flat-directory hotspots 7, with 78 direct test files; size watchlist remains 18.
  Architecture violations and files above 400 remain 0. Largest changed scanner
  is 368 lines; its coherent extraction/headroom review remains DEBT-06.
- Remaining limitations: local diagnostics and file-wide aliases are heuristics;
  no future/GUI dataflow inference, full symbol resolution, blanket annotations,
  budget reset, or global privacy guarantee was introduced. Explicit whole-module
  Pyright inspection also exposed pre-existing allowlist-loader typing issues
  outside its configured check scope; retain for tooling review in DEBT-06/08.
- Follow-ups: DEBT-11 next; backend coverage DEBT-04; capture interruption DEBT-03;
  worker/session cleanup characterization DEBT-05; presenter failures DEBT-12.
  No hardware operations, AppImage rebuild/install, live-service restart, or commit.

### DEBT-11 Delivery Record

- Owner: main agent with separate ownership-design/test sub-agents and independent
  re-review. Started/completed 2026-10-05; baseline `4baf4e8`, result uncommitted.
- Changed product paths: `adapters/openrazer/lifecycle_monitor.py` and
  `service/service_cli.py`, under `src/naga_control/`. Added
  `tests/test_openrazer_lifecycle_startup.py`,
  `tests/test_openrazer_lifecycle_startup_races.py`, and
  `tests/test_service_cli_startup.py`; tracker/inventory updated.
- Reproduced first/later interrupted AddMatch, including remotely installed but
  unacknowledged rules, and a CLI that omitted cleanup after entered startup.
  Initial combined tests showed 24 failures while 17 existing tests remained green.
- Rollback now includes initial fencing/scheduling, accounts for attempted rules
  before their awaits, disables callbacks, cancels/awaits any signal-created runner,
  detaches in reverse order, and attempts disconnect even when removal is cancelled.
  Bookkeeping clears before asynchronous detach. Late factory/subscription return
  cannot resurrect a stopped monitor. CLI takes responsibility before awaiting start.
- Deliberate contract: failed startup after bus acquisition is terminal, like stop;
  ordinary factory failure/cancellation before transfer is separate. The factory
  must provide a dedicated connection. Starts are serialized; stop does not join
  an independently pending factory/start task. Successful-start rescan recovery,
  debounce, diagnostics, topology fencing, and mutation policy are unchanged.
- 26 new fake cases assert primary exception identity, terminal/idempotent behavior,
  uncertain match cleanup, joined in-flight or not-yet-entered runner cancellation,
  retained callbacks, independent ordinary teardown attempts, stop races, and CLI
  ordering/no publication. Review found no blocking scoped regression.
- Targeted command: `.venv/bin/pytest -q tests/test_openrazer_lifecycle_monitor.py tests/test_openrazer_lifecycle_diagnostics.py tests/test_openrazer_lifecycle_startup.py tests/test_openrazer_lifecycle_startup_races.py tests/test_service_cli.py tests/test_service_cli_startup.py`;
  43 passed, 8 dependency deprecation warnings. Ruff lint/format and configured
  Pyright passed; `.venv/bin/python -m buildpython`: 9/9 checks passed,
  1,117 tests passed, 2 optional coverage tests skipped, 8 warnings.
- Extended Verification Routine command with
  `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools` (Coverage 7.16.2, Vulture
  2.16): 16 passed, ShellCheck skipped, 1,119 tests passed, 8 warnings;
  run `a22aed1f-4516-4297-aff8-fdd120edd45a` is partial.
- Coverage: product 90.07% -> 90.17%; lifecycle 80.28% -> 85.06% (131/154).
  Broad total 61 -> 63 solely from two test interruption/rethrow boundaries.
  `BaseException` 5 -> 8: one existing production rollback boundary now includes
  interruption, and two new test boundaries capture/rethrow interruption identity.
  These are justified cleanup/testing contracts, not three new silent failures.
  Unlogged remains 34, hygiene 38, waivers 0, watchlist 18, architecture/over-limit
  files 0. Product files 270/122 lines; new test files 338/216/136 lines.
- Limitations: disconnect is attempted, not acknowledged. A second cancellation
  during asynchronous removal can interrupt remaining explicit removals and replace
  the original cancellation; the tested guarantee is final disconnect/bookkeeping
  reset. Cancelling discovery does not stop its underlying thread. Factory-internal
  cleanup before transfer remains separate. Arbitrary auxiliary/service-stop errors
  can still replace CLI's primary failure or skip later cleanup: DEBT-05.
- No real bus/device operations, live-service restart, AppImage build/install,
  hardware validation, release action, or commit. Proceed to DEBT-04.

### DEBT-04 Delivery Record

- Owner: separate backend/capability fake-test sub-agents, main agent for product
  fixes, independent review. Started/completed 2026-10-05; result uncommitted on
  `4baf4e8`. Product changes are two lines in `adapters/openrazer/backend.py` and
  one line in `adapters/openrazer/capabilities.py`, under `src/naga_control/`.
- Added `tests/test_openrazer_backend_failures.py`,
  `tests/test_openrazer_backend_operation_failures.py`, and
  `tests/test_openrazer_capabilities.py`: 187 cases with asserted error/state,
  generation, client choice, call order, write counts, and optional/required values.
- Reproduced/fixed two gaps: initial scroll-cycle read timeouts previously escaped
  while retaining available state/client; malformed extreme battery integers raised
  on float conversion and hid valid required state. Required regressions were red
  before the fixes and now pass; no xfails or skips remain in these new files.
- Scroll failure now uses the established unavailable-state/client-invalidation
  route. Battery is range-checked before conversion. No mutation is retried; a later
  distinct request safely reacquires a fresh client from validated topology.
  Conflict tests guard every device access, including same-value/nested writes and
  direct mode lookup. Missing/malformed scroll options cover both read boundaries.
- Targeted command: `.venv/bin/pytest -q tests/test_openrazer_backend.py tests/test_openrazer_backend_failures.py tests/test_openrazer_backend_operation_failures.py tests/test_openrazer_capabilities.py tests/test_openrazer_mode.py tests/test_openrazer_settings.py`;
  212 passed. Ruff lint/format and configured Pyright passed.
  `.venv/bin/python -m buildpython`: 9/9 checks passed, 1,307 tests passed,
  2 optional coverage tests skipped, 8 dependency warnings.
- Extended Verification Routine command with
  `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools` (Coverage 7.16.2, Vulture
  2.16): 16 passed, ShellCheck skipped, 1,309 tests passed, 8 warnings;
  run `70dc0f3c-7c43-4f73-b19a-9b555ca14bef` is partial.
- Fresh full-suite coverage: backend 72.91% -> 92.68% (190/205 statements),
  capabilities 78.57% -> 100% (98/98), product 90.17% -> 91.15%. Confirmed with
  `.venv/bin/python -m coverage report --data-file buildlog/naga-control/.coverage.buildpython --precision=2 --show-missing src/naga_control/adapters/openrazer/backend.py src/naga_control/adapters/openrazer/capabilities.py src/naga_control/diagnostics/capture_cli.py src/naga_control/diagnostics/capture.py`
  using the same temporary-tool `PYTHONPATH`.
- Broad total 63 -> 64 and local-unlogged candidates 34 -> 35 reflect the new
  necessary scroll failure-to-state boundary, not a silent failure. Hygiene 38 -> 39
  (fallback 21 -> 22); `BaseException` remains 8. No waivers, scanner definitions,
  or budgets changed. Architecture/over-limit files remain 0; watchlist 18.
- Headroom disposition: backend 382 lines retains its existing cohesive selection,
  operation, and failure-state owner for this two-line fix; responsibility-based
  extraction is deferred to DEBT-06 rather than a mechanical split. Capabilities
  stays 163; test files are 332/280/345 lines, all below preferred 350.
- Remaining backend statements include validation/default-factory/close branches;
  coverage is statements, not proof of every branch or physical recovery. Optional
  poll-rate type-only reads and verbatim nonblank firmware contracts are unchanged.
  Fake state routing does not establish real held-output/grab cleanup; DEBT-05 and
  existing opt-in hardware gates remain necessary. No live hardware/service,
  AppImage build/install, release, or commit. Proceed to DEBT-03.

### DEBT-03 Delivery Record

- Owner: separate CLI/ownership implementation and test sub-agents, main-agent
  verification, independent review. Started/completed 2026-10-05; baseline
  `4baf4e8`, result uncommitted.
- Product paths: `diagnostics/capture.py`, `diagnostics/capture_cli.py`, and new
  `diagnostics/capture_sources.py`, under `src/naga_control/`. Added
  `tests/test_capture_cli_behavior.py`, `tests/test_capture_cli_errors.py`,
  `tests/test_capture_cli_validation.py`, and `tests/test_diagnostic_capture_rollback.py`.
- Fakes reproduced rollback close failures replacing interruption/skipping siblings,
  non-finite duration acceptance, misleading output-file udev advice, and combined
  CLI body/close failures losing the primary error. These are fixed with normal
  regressions, not skips/xfails. Standalone cleanup raises the first ordinary error
  after all independent attempts; rollback preserves primary failures. CLI cleanup
  attempts once and retains primary output/interruption failures against ordinary
  secondary close errors, while surfacing standalone cleanup errors.
- Source ownership/protocols moved out of the 392-line capture module before adding
  behavior. Direct re-exports preserve concrete existing imports; no forwarding
  facades or circular dependencies. Physical USB identity validation, descriptor
  ancestry, read-only opens, source IDs, frame ordering, and no-grab policy remain.
  This delivers one DEBT-06 headroom slice, not the whole headroom item.
- CLI durations must be finite/positive. Output write errors retain output-path and
  exception-class context without raw cause text in the normal diagnostic; source
  permission failures retain existing advice. JSON schema and identifier opt-in
  are unchanged. Error tests were split by responsibility to retain test headroom.
- 138 new cases cover parser/dispatch, temporary JSON outputs, metadata redaction,
  opt-in identifiers, conflicts/disappearance/identity mismatch, source interruption,
  ordinary close failure, exception precedence, and independent cleanup attempts.
  Review's combined-failure finding was fixed and re-reviewed before completion.
- Exact targeted command: `.venv/bin/pytest -q tests/test_capture_cli.py tests/test_capture_cli_behavior.py tests/test_capture_cli_errors.py tests/test_capture_cli_validation.py tests/test_diagnostic_capture.py tests/test_diagnostic_capture_rollback.py`;
  149 passed. Repository Ruff lint/format and configured Pyright passed.
  `.venv/bin/python -m buildpython`: 9/9 checks passed, 1,450 tests passed,
  2 optional coverage tests skipped, 8 dependency warnings.
- Extended Verification Routine command with
  `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools` (Coverage 7.16.2, Vulture
  2.16): 16 passed, ShellCheck skipped, 1,452 tests passed, 8 warnings;
  run `fd97ef15-008a-4245-bbe6-f54390192e52` remains partial.
- Fresh full-suite coverage: CLI 50% -> 99.15% (117/118; only module entry missing),
  extracted source owner 98.08% (51/52), frame/metadata module 94.49% (120/127).
  Product 91.15% -> 92.01%; denominator increased with extraction/cleanup and CLI
  code. No exclusions or budgets changed. Watchlist 18 -> 17; product files
  capture/source-owner/CLI are 260/168/217 lines; new tests 282/214/60/300.
- Broad total 64 -> 67: explicit CLI primary/secondary cleanup boundaries and the
  source close-error aggregation boundary. `BaseException` 8 -> 9; two original
  capture rollback catches moved unchanged in role. Local-unlogged 35 -> 36 is
  delayed close-error rethrow after all attempts, not silence. Hygiene 39 -> 40,
  fallback 22 -> 23. Waivers/architecture/over-limit files remain 0; import hotspots
  21 warning/5 critical. Eight test-only Vulture candidates, zero actionable; the
  added candidate is an intentional fail-fast async-generator sentinel. DEBT-08.
- Packaging after the new runtime import: `.venv/bin/python -m buildpython --run-steps "AppImage,AppImage Smoke" --continue-on-error` built
  `dist/Naga-Control-0.4.0-x86_64.AppImage`. Run
  `f3c79db4-fa9e-4177-874e-57b5dfe076f6` failed the Docker smoke with exit 2:
  Docker unavailable. This is still DEBT-09, not a passing release profile.
- Hardware-free host checks ran the actual rebuilt image with
  `XDG_CACHE_HOME=/tmp/opencode TMPDIR=/tmp/opencode` and
  `--appimage-extract-and-run`: bundled dependencies, host OpenRazer import (no
  manager construction), packaged source-module path/re-export identity, offscreen
  Qt construction, and `capture --help` passed. Exact commands follow below.
  Host checks do not substitute for clean Ubuntu/container verification.
- Limits: secondary `BaseException` during cleanup can replace a primary failure
  and stop later cleanup; failed close/disconnect attempts do not prove release.
  Input/read exception text is not globally sanitized: DEBT-13. Existing frame
  read/physical discovery behavior remains hardware-unverified by these fake cases.
  The local artifact is from an uncommitted workspace; no installed image was
  replaced, no live service restarted, no real capture or GUI session started,
  and no release/commit performed. Proceed to DEBT-05.

DEBT-03 host smoke commands (imports/help only, no hardware owner):

```bash
XDG_CACHE_HOME=/tmp/opencode TMPDIR=/tmp/opencode QT_QPA_PLATFORM=offscreen dist/Naga-Control-0.4.0-x86_64.AppImage --appimage-extract-and-run python -c "import os; import dbus, dbus_next, evdev, pyudev, tomli_w, packaging, numpy, openrazer.client; from naga_control.diagnostics import capture, capture_sources; from naga_control.diagnostics.capture_cli import CaptureOutputError; from naga_control.adapters.openrazer.lifecycle_monitor import OpenRazerLifecycleMonitor; from PySide6.QtWidgets import QApplication; from naga_control.gui.app import main; assert capture_sources.__file__.startswith(os.environ['APPDIR']); assert capture.open_sources is capture_sources.open_sources; app = QApplication([]); print('packaged-source-imports-and-qt-offscreen-ok')"
XDG_CACHE_HOME=/tmp/opencode TMPDIR=/tmp/opencode dist/Naga-Control-0.4.0-x86_64.AppImage --appimage-extract-and-run capture --help
```

### DEBT-05 Delivery Record

- Owner: main agent for pipeline/CLI/IPC changes; separate IPC, uinput, worker,
  session/runtime, lower-source, and configuration implementation/test sub-agents;
  independent reviews and concrete integration tests. Started/completed 2026-10-06;
  baseline `4baf4e8`, delivery uncommitted.
- Product scope: IPC server; service CLI, runtime, hardware worker, source forwarding
  and frame consumer; remapping/session composition; evdev source opening; keyboard,
  mouse, and forwarding-proxy adapters. Added `service/configuration_authority.py`
  and `service/session_lifecycle.py`, under `src/naga_control/`.
- Reproduced skipped independent cleanup, masked primary errors/cancellation,
  provisional source/output ownership gaps, abandoned/cancelled shutdown, repeated
  worker close, unsuccessful name ownership treated as publication, and construction
  failures outside CLI handling. Required fake regressions are green; no xfails.
- IPC exports before claiming, uses `DO_NOT_QUEUE`, and accepts only primary/already
  owned replies; it never steals or queues the name. Existing CLI fake was updated
  to the actual flags/reply contract. Reservation before hardware startup remains
  DEBT-14; no duplicate physical startup-prevention claim is made here.
- Cleanup attempts reader stops, both output releases/closes, action shutdown,
  polling, session shutdown, worker shutdown, and disconnect independently after
  ordinary errors. Active callers receive the first ordinary cleanup error after
  attempts; an existing startup/body failure remains primary. Pre-transfer opening
  and proxy readiness include interruption rollback, without changing identity,
  proxy-before-grab, or held-key safety gates.
- Session, runtime, and worker shutdown are owned and shielded from caller
  cancellation. Concurrent callers join the same cleanup. Session stop reawaits a
  cached failure without repeating destruction; completed service/worker stops are
  no-ops. Terminal service/worker startup is rejected. Already accepted work may
  finish under the lock before shutdown; new known-unsafe/stopped mutations cannot
  persist configuration, advance revision, change calibration, or create a session.
- Review found and fixed a concrete-session/runtime mismatch that hid an internally
  failed rollback, plus mutation ordering and ancillary-join error precedence.
  The session lifecycle owner retains failed detached cleanup, fences before stop,
  and blocks recovery/mutations until successful cleanup. Late session errors are
  retrieved and diagnosed even after the last waiter cancels. Actual-worker/fake-
  backend integration verifies action/mode fencing during and after failed cleanup.
- Configuration authority and session ownership were extracted by responsibility,
  not through a mixin or generic cleanup framework. Persistence-before-own-rebuild,
  read-only stale-revision precedence, public error identities, source signatures,
  held-action/refcount logic, and serialized hardware calls remain. Five new cleanup
  log sites use phase/class only; DEBUG-level tests exclude raw payloads, causes,
  tracebacks, and identifier sentinels. This is not global exception sanitization.
- Added 445 cases across 16 new test files, all below preferred 350 lines. Stateful
  uinput fakes distinguish accepted effects/successful simulated destruction from
  failed cleanup attempts. Tests prove simulated state and real queue fencing with
  fake hardware, not actual kernel-held-state/grab release.
- Exact new-file verification command:

```bash
.venv/bin/pytest -q tests/test_configuration_authority.py tests/test_hardware_worker_failures.py tests/test_ipc_server.py tests/test_service_cli_failures.py tests/test_service_cli_main.py tests/test_service_lifecycle_failures.py tests/test_service_session_barrier.py tests/test_service_session_lifecycle.py tests/test_service_worker_fencing.py tests/test_session_ownership.py tests/test_session_teardown.py tests/test_source_cleanup_failures.py tests/test_uinput_creation_failures.py tests/test_uinput_output_failures.py tests/test_uinput_proxy_failures.py tests/test_uinput_stateful_failures.py
```

- Result: 445 passed, 8 dependency deprecation warnings. Worker cases also passed
  with asyncio debug and warnings treated as errors. Repository Ruff lint/format
  and configured Pyright passed. `.venv/bin/python -m buildpython`: 9/9 checks
  passed, 1,913 tests passed, 2 optional coverage tests skipped, 8 warnings.
- Extended Verification Routine command with
  `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools` (Coverage 7.16.2, Vulture
  2.16): 16 passed, ShellCheck skipped, 1,915 tests passed, 8 warnings;
  run `5fe76d34-5b89-4255-aded-09bee54e0bc0` is partial.
- Full-suite statement coverage: IPC 72.22% -> 100% (21/21), service CLI 73.13% ->
  97.70% (85/87), keyboard 76.40% -> 98.96% (95/96), mouse 75.68% -> 100% (83/83).
  Runtime 96.43%, worker 97.04%, session lifecycle 95.59%, configuration authority
  100%, remapping 86.26%, proxy/frame consumer 100%. Product 92.01% -> 93.53%;
  extraction/cleanup changed the denominator. No exclusions, budgets, or scanner
  definitions changed. Remaining CLI wiring/module-entry statements are not a
  physical test substitute.
- Raw broad catches 67 -> 93, local-unlogged 36 -> 55, `BaseException` 9 -> 19,
  hygiene 40 -> 55. These reflect necessary independent cleanup, first-error
  aggregation, owned interruption rollback, and assertion-oriented test catches;
  [current dispositions](debt-exception-inventory.md#debt-05-additions) explain the
  added boundaries. No blanket waivers. Counts alone are not safety regressions.
- Architecture/over-limit files remain 0; watchlist 17, imports 24 warning/5 critical,
  flat directories 7 (104 direct test files), dead-code candidates 8 test-only/0
  actionable. Runtime is 377 lines with 23 below the hard cap; its remaining mode,
  status, lock, and shutdown orchestration is not split cosmetically. Authority/
  session-owner modules are 77/88 lines. Further under-350 work remains DEBT-06.
- Packaging: `.venv/bin/python -m buildpython --run-steps "AppImage,AppImage Smoke" --continue-on-error`
  rebuilt `dist/Naga-Control-0.4.0-x86_64.AppImage`. Run
  `beb63cdf-2757-40a1-8a69-ec037786b9e7`: build passed, Docker smoke failed with
  exit 2 because Docker is unavailable. DEBT-09 remains blocked; no passing release
  profile or clean-container compatibility claim.
- Host rebuilt-image checks passed: packaged owner-module paths, error re-export
  identity, bundled dependencies, host OpenRazer import without constructing a
  manager, offscreen Qt, and service/capture help. Exact commands follow below.
- Limits: failed close/ungrab/disconnect means attempts, not confirmed release.
  Secondary non-ordinary interruptions and repeated cancellation during outer CLI
  cleanup are not given an all-resource completion guarantee. Cancelling a hardware
  consumer does not undo an already executing backend operation or cause retry.
  Factory-internal acquisition before transfer remains separate. No real device
  nodes, installed-image replacement, live-service restart, GUI session, release,
  or commit. Next: singleton reservation DEBT-14, then capture privacy DEBT-13.

DEBT-05 host smoke commands (imports/help only):

```bash
XDG_CACHE_HOME=/tmp/opencode TMPDIR=/tmp/opencode QT_QPA_PLATFORM=offscreen dist/Naga-Control-0.4.0-x86_64.AppImage --appimage-extract-and-run python -c "import os; import dbus, dbus_next, evdev, pyudev, tomli_w, packaging, numpy, openrazer.client; from naga_control.service import runtime, configuration_authority, session_lifecycle; from naga_control.application.remapping import FirstSliceSession; from naga_control.adapters.uinput.keyboard import VirtualKeyboard; from naga_control.adapters.uinput.mouse import VirtualMouse; from naga_control.ipc.server import publish_service; assert configuration_authority.__file__.startswith(os.environ['APPDIR']); assert session_lifecycle.__file__.startswith(os.environ['APPDIR']); assert runtime.StaleConfigurationRevisionError is configuration_authority.StaleConfigurationRevisionError; from PySide6.QtWidgets import QApplication; from naga_control.gui.app import main; app = QApplication([]); print('packaged-service-owners-and-qt-offscreen-ok')"
XDG_CACHE_HOME=/tmp/opencode TMPDIR=/tmp/opencode dist/Naga-Control-0.4.0-x86_64.AppImage --appimage-extract-and-run service --help
XDG_CACHE_HOME=/tmp/opencode TMPDIR=/tmp/opencode dist/Naga-Control-0.4.0-x86_64.AppImage --appimage-extract-and-run capture --help
```

### DEBT-14 Delivery Record

- Owner: main implementation agent, separate reservation/readiness test sub-agents,
  startup assertion migration, and independent design/re-review. Started/completed
  2026-10-06; baseline `4baf4e8`, delivery uncommitted.
- Product scope: `ipc/service.py`, `ipc/server.py`, and `service/service_cli.py`,
  under `src/naga_control/`. Architecture contract updated. Added
  `tests/test_ipc_readiness.py`, `tests/test_service_reservation.py`,
  `tests/test_service_reservation_cleanup.py`, and `tests/service_reservation_fakes.py`.
  Updated three existing CLI test files to deliberately reflect acquisition order
  and cleanup only of entered owners, preserving cancellation/error assertions.
- Reused the public name and existing export-before-claim helper with exactly
  `DO_NOT_QUEUE`. A separate private name would not exclude an older public-name
  incumbent. Hardware-owning service/auxiliary startup is now after successful
  arbitration; unsuccessful name/export/connect outcomes do not enter or stop an
  unattempted hardware owner. Lazy composition remains allowed before reservation.
- All seven registered wire implementations are async and await an interface-local
  event. Names/input/output signatures are unchanged. Explicit gated mode is used
  by the CLI; default construction remains ready for existing concrete consumers.
  Non-exported Python helpers retain their direct-call behavior and are not gates.
  READY means initialized service/auxiliary, not mouse availability or watcher
  initialization. Watcher scheduling is not a new handshake.
- Failure/shutdown marks the gate terminally unavailable before cleanup yields;
  waiting calls fail with fixed `.Error.Unavailable` text and suppressed active
  exception context, never startup payloads. `mark_ready()` cannot reopen it.
  Stop requests observed at startup checkpoints skip subsequent startup/READY.
- Review found cancellation first delivered during cleanup could abandon outer
  cleanup and strand the name while concrete service shutdown continued. CLI now
  owns a cleanup task, synchronously cancels the watcher before yielding, and rejoins
  despite single/repeated caller cancellation. Entered auxiliary/service stops
  finish before disconnect. Existing body failure stays primary; otherwise first
  cleanup-time cancellation propagates after join, then standalone cleanup error.
- Added 111 cases: 64 readiness, 21 reservation, 26 cleanup. Registered dbus-next
  method metadata is exercised, not its return-discarding Python decorators.
  Cases include both successful ownership replies, duplicate/public-only incumbent
  simulation, unacknowledged remote reservation, queued-method isolation, stage
  stops, terminal shutdown, typed IPC errors, and first/repeated cleanup cancellation.
  Real `NagaService` with fake resources verifies its internal shielding interaction.
  No new skips/xfails; initial readiness/reservation regressions were red, and the
  review-added cleanup suite reproduced 26 failures before its ownership fix.
- Targeted command: `.venv/bin/pytest -q tests/test_service_reservation_cleanup.py tests/test_service_reservation.py tests/test_ipc_readiness.py tests/test_ipc_service.py tests/test_ipc_server.py tests/test_service_cli.py tests/test_service_cli_startup.py tests/test_service_cli_failures.py tests/test_service_cli_main.py`;
  191 passed, 8 dependency deprecation warnings. Ruff lint/format and configured
  Pyright passed. `.venv/bin/python -m buildpython`: 9/9 checks passed,
  2,028 tests passed, 2 optional coverage tests skipped, 8 warnings.
- Extended Verification Routine command with
  `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools` (Coverage 7.16.2, Vulture
  2.16): 16 passed, ShellCheck skipped, 2,030 tests passed, 8 warnings;
  run `b79601c6-7a64-4b8d-b4a7-94df7f808a77` remains partial.
- Full-suite statement coverage: IPC interface/server 100% (82/82 and 21/21),
  CLI 97.48% (116/119), product 93.53% -> 93.70% with added gate/cleanup statements.
  CLI's physical-discovery bridge, stopper-origin cancellation branch, and module
  entry remain uncovered; there is no blanket exclusion or physical verification
  claim. Broad/local-unlogged/BaseException counts stay 93/55/19; hygiene 55,
  watchlist 17, imports 24 warning/5 critical, architecture/over-limit files 0.
  No budgets, waivers, or scanner definitions changed. Existing CLI aggregation
  catches moved into owned cleanup; their dispositions are unchanged.
- Product files are 149/46/177 lines (interface/server/CLI). New test/helper files
  are 349/240/226/169, below preferred 350. Flat-directory hotspots remain 7 with
  108 direct test files; Vulture still has 8 test-only candidates, 0 actionable.
- Packaging: `.venv/bin/python -m buildpython --run-steps "AppImage,AppImage Smoke" --continue-on-error`
  rebuilt the local v0.4.0 image. Run `e6dabb0c-b6a1-4de3-9d72-c646573ba1bb`:
  build passed; Docker smoke failed with exit 2 because Docker is unavailable.
  The actual image passed packaged dependency/GUI imports, offscreen Qt, service/
  capture help, and all seven async signature/unavailable-gate checks against a
  provider with no implementation. No bus or hardware owner was constructed.
  Host checks do not substitute for clean-container verification; DEBT-09 remains.
- Limits: factories must return dedicated owned connections; pre-transfer raw-bus
  acquisition is DEBT-15. Stage stop checks do not promptly interrupt a blocked
  startup operation. Stopper-origin non-ordinary interruption/hanging cleanup and
  process death are not all-resource guarantees. Failed disconnect means an attempt,
  not confirmed release. Remote transport loss can beat sending the fixed error.
  Already-owned older processes are excluded; an older process still in its own
  pre-publication startup cannot be retroactively fenced by this implementation.
- No private lock/name, additional exported methods, hardware retry, real device access,
  installed-image replacement, live-service restart, GUI session, release, or commit.
  Proceed to capture error-text privacy DEBT-13, then factory rollback DEBT-15.

DEBT-14 host smoke commands (imports/metadata/gate/help only):

```bash
XDG_CACHE_HOME=/tmp/opencode TMPDIR=/tmp/opencode QT_QPA_PLATFORM=offscreen dist/Naga-Control-0.4.0-x86_64.AppImage --appimage-extract-and-run python -c "import asyncio, inspect, os; import dbus, dbus_next, evdev, pyudev, tomli_w, packaging, numpy, openrazer.client; from types import SimpleNamespace; from dbus_next.errors import DBusError; from dbus_next.service import ServiceInterface; from naga_control.ipc import service; from naga_control.gui.app import main; from PySide6.QtWidgets import QApplication; assert service.__file__.startswith(os.environ['APPDIR']); interface = service.NagaControlInterface(SimpleNamespace(), ready=False); interface.mark_unavailable(); methods = ServiceInterface._get_methods(interface); expected = {'GetSnapshot': ('', 's', ()), 'GetConfiguration': ('', 's', ()), 'ReleaseAll': ('', '', ()), 'ApplyConfiguration': ('qs', 'q', (0, '')), 'SelectProfile': ('s', 'q', ('default',)), 'BeginCalibration': ('', 'b', ()), 'EndCalibration': ('', 'b', ())}; assert {m.name for m in methods} == set(expected)
async def verify():
    for method in methods:
        assert inspect.iscoroutinefunction(method.fn)
        assert (method.in_signature, method.out_signature) == expected[method.name][:2]
        try:
            await method.fn(interface, *expected[method.name][2])
        except DBusError as error:
            assert error.type == 'org.nagacontrol.Service1.Error.Unavailable'
            assert error.text == 'Naga Control service is unavailable.'
        else:
            raise AssertionError('unavailable provider was reached')
asyncio.run(verify()); app = QApplication([]); print('packaged-readiness-and-qt-offscreen-ok')"
XDG_CACHE_HOME=/tmp/opencode TMPDIR=/tmp/opencode dist/Naga-Control-0.4.0-x86_64.AppImage --appimage-extract-and-run service --help
XDG_CACHE_HOME=/tmp/opencode TMPDIR=/tmp/opencode dist/Naga-Control-0.4.0-x86_64.AppImage --appimage-extract-and-run capture --help
```

### DEBT-13 Delivery Record

- Owner: main agent, separate capture-reader and CLI privacy-test sub-agents,
  read-only assessment and independent review. Started/completed 2026-10-06;
  baseline `4baf4e8`, delivery uncommitted.
- Product scope: `diagnostics/capture.py` and `diagnostics/capture_cli.py`, under
  `src/naga_control/`; troubleshooting and this tracker/inventory updated. Added
  `tests/test_capture_error_privacy.py`, `tests/test_capture_cli_error_privacy.py`,
  and `tests/test_capture_error_formatting.py`; old CLI diagnostic assertions were
  updated without weakening exit, exception-identity, write, or cleanup assertions.
- Fakes reproduced raw error payloads in normal stderr, reader `end_reason`,
  stdout, and persisted JSON under both metadata settings. Initial reader/CLI
  privacy suites had 36/40 required failures, without skips/xfails.
- One formatter in the existing capture module emits exception class and optional
  validated errno/static symbolic name. It never renders exception instances,
  arguments, messages, filename fields, cause/context, or tracebacks. Integer
  subclasses are normalized through the native implementation before formatting;
  booleans, non-integers, and values outside signed C-int range are omitted. This
  avoids arbitrary rendering and huge-integer conversion failures, without regex
  redaction or a new diagnostics framework.
- Reader-generated errors retain source/operation context. Normal permission/input
  exits retain their fixed labels, useful errno, exit 2, and permission-only udev/
  non-root advice. Read failures still return a capture/result and CLI exit 0;
  interruption remains 130. No catch widths, identity/grab behavior, source order,
  frame boundaries, callback order, sibling drain, or cleanup ownership changed.
- The application output wrapper stores the requested path and a safe summary.
  Exact wrappers use those fields; subclasses use generic safe formatting rather
  than arbitrary rendering/fields. Original write exceptions remain causes, and
  the controlled direct-library string stays path/class-only. Other library I/O
  exceptions retain their original identity/chains; this is normal-output privacy,
  not mutation of caller-owned exception objects or forensic tracebacks.
- `--include-identifiers` still affects only explicit serial/physical/phys/uniq
  metadata. It never opts arbitrary error text back in. JSON schema/version and
  string-valued `end_reason` remain unchanged. Existing captures are not rewritten.
- Added 123 cases: 37 reader/integration, 63 CLI, 23 formatting. Rendering spies,
  cause-free errors/wrappers, invalid/unknown/subclass/huge errno, subclass output
  errors, direct-library identity, and actual-reader stdout/JSON paths are covered.
  Ordered complete frames and discarded partial tails, joined sibling finalizers,
  and owner close counts are asserted. Review found no blocking product issue;
  explicit absent-cause coverage was added before completion.
- Exact targeted command: `.venv/bin/pytest -q tests/test_capture_error_privacy.py tests/test_capture_cli_error_privacy.py tests/test_capture_error_formatting.py tests/test_capture_cli.py tests/test_capture_cli_behavior.py tests/test_capture_cli_errors.py tests/test_capture_cli_validation.py tests/test_diagnostic_capture.py tests/test_diagnostic_capture_rollback.py`;
  272 passed. Ruff lint/format and configured Pyright passed.
  `.venv/bin/python -m buildpython`: 9/9 checks passed, 2,154 tests passed,
  2 optional coverage tests skipped, 8 dependency warnings.
- Extended Verification Routine command with
  `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools` (Coverage 7.16.2, Vulture
  2.16): 16 passed, ShellCheck skipped, 2,156 tests passed, 8 warnings;
  run `91e15f8d-bf04-4890-b462-a47c32c614ac` remains partial.
- Full-suite statement coverage: capture module 96.40% (134/139), capture CLI
  99.19% (122/123), source owner 98.08% (51/52); product 93.70% -> 93.75% with
  added formatting/wrapper statements. No exclusions or debt budgets changed.
  Broad/local-unlogged/BaseException counts remain 93/55/19, hygiene 55, watchlist
  17, architecture/over-limit files 0, flat hotspots 7 (111 direct test files).
  Import warnings remain 24; critical blocks 5 -> 6 include the new reader privacy
  test's long import block. Informational penalty saturation is not a correctness
  gate. Vulture remains 8 test-only candidates/0 actionable. DEBT-08 triage remains.
- Product files are 275/228 lines; new tests 341/332/227, all below preferred 350.
  No new runtime module, filesystem/GUI/logging/hardware operation in the error
  formatter, per-event formatting, or global service sanitizer was added.
- Packaging: `.venv/bin/python -m buildpython --run-steps "AppImage,AppImage Smoke" --continue-on-error`
  rebuilt the local v0.4.0 image. Run `16a2a8c1-8f27-44c7-8678-48a0a7f6a52a`:
  build passed; Docker smoke failed with exit 2 because Docker is unavailable.
  Host checks on the actual image passed packaged formatter/wrapper behavior,
  dependency imports, offscreen Qt, and service/capture help; commands follow below.
  This is not clean-container or physical device verification; DEBT-09 remains.
- Privacy limits are now explicit in troubleshooting: input events/incidental keys,
  scans/motion/timestamps, environment strings, device names, live terminal event
  paths, and requested destinations are not whole-capture anonymized. Arbitrary
  caller-created source IDs/results/exception class names or mutated wrapper fields
  are not sanitized. Native errno/class provenance is assumed; no adversarial
  metaprogramming policy or new source-ID taxonomy was introduced. Original library
  exceptions, service logs, and historic captures remain caller-review surfaces.
- No real device nodes, capture/grab, installed-image replacement, live-service
  restart, GUI session, release, or commit. Proceed to factory rollback DEBT-15.

DEBT-13 host smoke commands (imports/synthetic error formatting/help only):

```bash
XDG_CACHE_HOME=/tmp/opencode TMPDIR=/tmp/opencode QT_QPA_PLATFORM=offscreen dist/Naga-Control-0.4.0-x86_64.AppImage --appimage-extract-and-run python -c "import os; import dbus, dbus_next, evdev, pyudev, tomli_w, packaging, numpy, openrazer.client; from pathlib import Path; from naga_control.diagnostics import capture; from naga_control.diagnostics.capture_cli import CaptureOutputError; from PySide6.QtWidgets import QApplication; from naga_control.gui.app import main; assert capture.__file__.startswith(os.environ['APPDIR']); error = OSError(19, 'PRIVATE_PAYLOAD', '/sys/usb/PRIVATE_PORT'); error.__cause__ = RuntimeError('PRIVATE_CAUSE'); error.__context__ = RuntimeError('PRIVATE_CONTEXT'); assert capture.format_capture_error(error) == 'OSError (errno 19 ENODEV)'; output = CaptureOutputError(Path('/requested/capture.json'), error); assert output.error_summary == 'OSError (errno 19 ENODEV)'; assert str(output) == '/requested/capture.json: OSError'; app = QApplication([]); print('packaged-capture-error-privacy-and-qt-offscreen-ok')"
XDG_CACHE_HOME=/tmp/opencode TMPDIR=/tmp/opencode dist/Naga-Control-0.4.0-x86_64.AppImage --appimage-extract-and-run capture --help
XDG_CACHE_HOME=/tmp/opencode TMPDIR=/tmp/opencode dist/Naga-Control-0.4.0-x86_64.AppImage --appimage-extract-and-run service --help
```

### DEBT-15 Delivery Record

- Owner: executor implementation, supervisor acceptance. Started/completed 2026-10-06;
  historical baseline `4baf4e8`, current base `bb32ac9` (`License: match OpenRazer
  with GPL-2.0-only`), delivery uncommitted. The license commit and the external
  `tests/test_buildpython_runner.py` 10-line fixture change are concurrent state,
  neither attributed to nor reverted by DEBT-15. No Git mutations by this wave.
- Product scope: `ipc/server.py` (54 lines) and
  `adapters/openrazer/lifecycle_monitor.py` (276 lines), under `src/naga_control/`.
  After the constructor returns a dedicated raw bus, each factory owns it until
  connect and wrapper creation succeed; a pre-transfer `BaseException` attempts a
  single synchronous raw `disconnect()` and rethrows the original error. Ordinary
  secondary disconnect errors are suppressed and never replace the primary.
  Constructor raising before return has no raw to disconnect. No shared
  framework/helper, cross-dependency import, diagnostic payload, readiness, name
  flag, rescan retry/debounce, or hardware-control change.
- Added `tests/test_dbus_connection_rollback.py` (291 lines),
  `tests/test_openrazer_connection_factory.py` (249 lines), and
  `tests/test_openrazer_factory_monitor.py` (151 lines): 18 new cases. Fakes use
  injected modules/factories only; no real `MessageBus`, raw sockets, `/dev`,
  or sysfs. Coverage: IPC constructor failure/successful transfer, connect
  ordinary errors, first gated-connect cancellation, primary preservation against
  ordinary secondary disconnect failure (ordinary, `KeyboardInterrupt`,
  `SystemExit`), lifecycle wrapper failure including wrapper-plus-secondary
  disconnect, CLI cancellation through the real `connect_session_bus`
  (zero hardware start, raw disposed once), and monitor retry through the real
  `_default_bus_factory` (fail-then-healthy connect, callable message factory,
  Events/runner join bounded 2s, no fixed sleeps). Red baseline was 11 failed /
  5 passed before the fix, then all 18 new cases passed.
- Exact targeted command: `.venv/bin/pytest -q tests/test_dbus_connection_rollback.py tests/test_openrazer_connection_factory.py tests/test_openrazer_factory_monitor.py tests/test_ipc_server.py tests/test_openrazer_lifecycle_monitor.py tests/test_openrazer_lifecycle_startup.py tests/test_openrazer_lifecycle_startup_races.py tests/test_service_reservation.py tests/test_service_reservation_cleanup.py`;
  104 passed, 8 dependency warnings. `.venv/bin/ruff check .`,
  `.venv/bin/ruff format --check .`, and `.venv/bin/pyright` passed.
  `.venv/bin/python -m buildpython`: 9/9 checks passed, 2,175 tests passed,
  2 optional coverage tests skipped, 8 warnings.
- Extended Verification Routine command with
  `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools` (Coverage 7.16.2, Vulture
  2.16): 16 passed, ShellCheck skipped, 2,177 tests passed, 8 warnings;
  run `1c9d2b67-009a-4ecc-9c53-9d02e8192b6f` remains partial.
- Full-suite statement coverage: 94.04% (6,196 / 6,589 statements, 92 files).
  `ipc/server.py` 100% (28/28); lifecycle monitor 96.89% (156/161, missing
  lines 102 121 138 256 259). Broad catches 95 vs 93, `BaseException` 21 vs 19,
  unlogged 55 unchanged, hygiene 55, no waivers/budgets/scanner-definition change.
  Watchlist 17, imports 24 warning / 6 critical, flat directories 7 (114 direct
  test files), dead-code 8 all test-only / 0 actionable, architecture 0.
- Packaging: `.venv/bin/python -m buildpython --run-steps "AppImage,AppImage Smoke" --continue-on-error`
  rebuilt the local image. Run `5e1109f2-379a-42f6-be82-df0ca20cd1a2`: build passed,
  Docker smoke failed with exit 2 because Docker is unavailable. Host checks on the
  actual image used a Python shim with a fake import module whose `Raw.connect`
  raises `OSError` and whose `disconnect` appends once, asserting primary identity
  for both factories (`packaged-factory-rollback-and-qt-offscreen-ok`); dependency
  imports including host OpenRazer ran without constructing a manager (no live bus),
  plus offscreen `QApplication` and `service`/`capture --help`. No installs, service
  changes, hardware operation, release, or commit.
- Limits: a disconnect attempt is not proof of kernel/socket release; read-only
  inspection found installed `dbus.disconnect` only calls socket shutdown, so no
  fd-close/finalize claim is made. Constructors failing before object return are
  library-internal and separate. Primary identity is preserved only against
  ordinary secondary disconnect errors; secondary non-ordinary interruption is a
  separate limit. No hardware D-Bus or socket acknowledgement was exercised.
  Next: presenter propagation DEBT-12.

### DEBT-12 Delivery Record

- Owner: executor docs-only completion, supervisor inspection and acceptance.
  Started 2026-10-06 as in progress; completed 2026-10-06 UTC. Historical
  baseline `4baf4e8`, current HEAD `bb32ac9` (`License: match OpenRazer with
  GPL-2.0-only`), delivery uncommitted. No Git staging, commit, or branch
  change. No credentials, root, network install, or product/test edit in this
  wave. Many concurrent external installer/release changes preserved without
  attribution or staging (`.github/workflows/release.yml`, `install.sh`,
  `scripts/install_user.sh`, `scripts/install_openrazer.sh`,
  `scripts/prepare_release.py`, `buildpython/openrazer_packages/`,
  `tests/test_installer_layout.py`, `tests/test_release_preparation.py`,
  `tests/test_buildpython_runner.py` fixture, `docs/release-notes.md`,
  `docs/troubleshooting.md`, `changelog.md`, and related source churn from
  `git status`); DEBT-12 claims only its test file and these tracker/inventory
  notes.
- Product scope: none in this wave. `src/naga_control/gui/presenter.py`
  (146 lines) unchanged. Prior wave added `tests/test_gui_presenter_failures.py`
  (349 lines): 10 new cases in 1 new file. Total default count moved
  2,175 -> 2,189, which includes 10 DEBT-12 cases plus 3 concurrent installer
  tests and other concurrent churn; do not attribute the full 14-test delta to
  DEBT-12 alone. No second presenter test file was needed. No extra AppImage
  build was required for this test-only item; the DEBT-15 package check stands
  for the older current source package, not all concurrent installer changes.
- Behavior characterized GREEN first; no false RED claim. Existing presenter
  propagation was already correct, so new tests document rather than fix:

  | Case | Failure injected | Observable contract |
  | --- | --- | --- |
  | refresh control | snapshot `RuntimeError("snapshot gone")` | one close, `reachable False` + reason, revision unchanged, listener notified |
  | release_all | `RuntimeError("release boom")` | op not recorded, no readback, one close, `reachable False` + reason |
  | begin_calibration | `RuntimeError("begin boom")` | same close/unreachable/no-readback contract |
  | end_calibration | empty `RuntimeError()` | `detail == "RuntimeError"` type fallback, same close/unreachable contract |
  | select_profile generic | `RuntimeError("select boom")` | `UNREACHABLE`, `selected None`, one close, no readback |
  | apply_configuration generic | `RuntimeError("apply boom")` | `UNREACHABLE`, `applied None`, one close, revision unchanged |
  | fresh-client recovery | release failure then healthy client generation 9/revision 7 | new open, published snapshot/config/revision, old client unused |
  | shared close error | close raises `RuntimeError("close boom")` | primary release reason kept, still unreachable, later reacquisition works |
  | offscreen overview label | release failure with `OverviewPage` | model `offline: release boom` reaches visible `connection_label`, Qt offscreen only |
  | typed controls | `UnknownProfile`/`StaleRevision`/`InvalidConfiguration` | `INVALID`/`STALE`/`INVALID`, remain reachable, no close (no blanket unreachable) |

- Typed outcomes and Qt ownership preserved. No GUI redesign, no blanket local
  logging, no global model-text redaction in this item. Fakes subclass the
  public `NagaControlClient` port with per-op failure and call counts; healthy
  initial snapshot/config read connects the provider before each failure. No
  real bus, daemon, GUI service, device node, or hardware test. Bounded
  `asyncio.run` only; no timing polling, skips, xfails, waivers, budgets, or
  error suppression.
- Acceptance evidence (supervisor-run):
  `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/test_gui_presenter_failures.py tests/test_gui_presenter.py tests/test_gui_device_page.py tests/test_gui_app.py`;
  46 passed, 8 dependency warnings. Supervisor independent review found no
  blocking issue with the 349-line test file.
- Standard profile: `.venv/bin/python -m buildpython`; 9/9 checks passed,
  2,189 tests passed, 2 optional coverage tests skipped, 8 warnings.
- Extended profile (exact 17-step Verification Routine command with
  `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools`): run
  `0f12a195-8203-4652-a7f5-7294db479b70` FAILED overall because ShellCheck is
  now available and failed exit 1 (not skipped); 2,191 tests passed,
  8 warnings; product coverage 94.29% (6,213 / 6,589 statements, 92 files);
  presenter 96.40% (107/111, missing lines 75, 84, 114, 115) versus 81.08%
  baseline from DEBT-02. DEBT-12 is therefore complete on its standard gates
  but NOT passing the full extended profile; the ShellCheck failure is an
  existing baseline outside DEBT-12. Exact failing step:
  `/usr/bin/shellcheck -x install.sh uninstall.sh scripts/install_user.sh scripts/install_openrazer.sh scripts/uninstall.sh buildpython/steps/appimage/AppRun`;
  `SC2012` at `buildpython/steps/appimage/AppRun` line 7 for
  `PYLIB="$(ls -d "$APPDIR"/usr/lib/python3.* 2>/dev/null | head -n 1)"`.
  Supervisor will delegate the AppRun fix to a fresh worker; this wave does not
  modify source outside the two allowed docs.
- Root metrics unchanged in this wave: broad 95, `BaseException` 21, unlogged
  55, hygiene 55, watchlist 17, imports 24 warning / 6 critical, flat
  directories 7 (115 direct test files), dead-code 8 all test-only /
  0 actionable, architecture 0. No scanner definitions, budgets, or gates
  changed. Historical tracking rows that say ShellCheck skipped remain dated
  and accurate for their runs.
- Inventory: the six presenter rows (`gui/presenter.py:53,63,72,81,93,124`)
  now have completed direct-failure coverage; original source handlers kept, no
  product catch narrowed. See [Exception Boundary Inventory](debt-exception-inventory.md).
- Limits: fake reacquisition does not prove kernel grab/release; disconnect
  attempts are attempts, not confirmed release. Physical device, sleep/wake,
  and desktop passthrough remain opt-in hardware gates. Next: DEBT-09
  ShellCheck corrective wave (Docker component still blocked), then DEBT-06.

### DEBT-09 Progress Note (ShellCheck subset, executor 2026-10-06, pending supervisor)

- Scope: existing folder selection only. Changed paths:
  `buildpython/steps/appimage/AppRun` and new
  `tests/test_apprun_python_lib_selection.py` (182 lines). No edits to
  `tests/test_buildpython_runner.py`, installer/release scripts, workflows,
  buildpython steps, license, config, or plugins. Concurrent user changes
  preserved.
- Fix: replaced `PYLIB="$(ls -d "$APPDIR"/usr/lib/python3.* 2>/dev/null
  | head -n 1)"` (SC2012) with a quoted glob loop over
  `"$APPDIR"/usr/lib/python3.*` that keeps `PYLIB=""` on no match, skips
  non-directories, and breaks on the first directory (lexicographic glob
  order). `PYTHON`, `PYTHONHOME`, `LD_LIBRARY_PATH`, `QT_PLUGIN_PATH`,
  CLI dispatch, and host OpenRazer atomic links unchanged. No helper
  framework and no ShellCheck disable comments.
- Preservation: single `python3.14` selects the same directory as legacy
  `ls`; multiple directories select the same lexicographic first as legacy
  `ls`; decoy regular files are now correctly skipped. Spaces in `APPDIR`
  remain quoted; the same quoting covers newlines by construction.
- Tests: 8 new fake-only cases launch a patched copy of `AppRun` with a
  fake bundled `python3` logger and a fake host interpreter replacing only
  `/usr/bin/python3 -c` discovery. No real D-Bus, OpenRazer, client, GUI,
  device, sysfs, network, service, image install, or privileged command.
  Covers single `python3.14`, multiple lex-first, decoy skip, none/file-only
  base path, whitespace `APPDIR`, static no-`ls` glob check, and `bash -n`.
- Executor checks: focused pytest 56 passed; `ruff check` passed;
  `ruff format --check` passed after formatting; `pyright` 0 errors;
  `shellcheck -x` on all six scripts passed. Old ShellCheck RED was
  `SC2012` at `AppRun` line 7; new gate is green.
- Not complete: Docker still unavailable and clean Ubuntu smoke never run.
  Supervisor reruns full checks/package and records final evidence. Do not
  mark whole DEBT-09 complete on this ShellCheck subset alone.

### DEBT-09 ShellCheck Gate Record (subset complete, whole item blocked)

- Status: DEBT-09 ShellCheck subset COMPLETE on 2026-10-06. Whole DEBT-09 remains BLOCKED on Docker. This is not a release-profile pass. Next is DEBT-06 as a separate bounded cohort; no DEBT-06 work starts here.
- Scope from the prior implementation wave (this docs wave changes only this tracker): `buildpython/steps/appimage/AppRun` (78 lines, quoted glob selects first DIRECTORY, skips files, empty on no match, quoted whitespace/spaces) and `tests/test_apprun_python_lib_selection.py` (180 lines, 8 new fake-only cases). Routine glob behavior only; no executed newline APPDIR claim, quoting supports it by construction. New-test static assertions cover implementation details and are not a core finding.
- Corrective gate: old run `0f12a195-8203-4652-a7f5-7294db479b70` stays historical FAILED exit 1 via `/usr/bin/shellcheck -x install.sh uninstall.sh scripts/install_user.sh scripts/install_openrazer.sh scripts/uninstall.sh buildpython/steps/appimage/AppRun` with `SC2012` at `buildpython/steps/appimage/AppRun` line 7 for `PYLIB="$(ls -d ... | head -n 1)"`. Current gate passes with empty output. ShellCheck was installed externally, not by this work; no gate suppressed or weakened.
- Supervisor verification on HEAD `bb32ac9` (external GPL commit plus concurrent user installer/release edits preserved): focused `.venv/bin/pytest -q tests/test_apprun_python_lib_selection.py tests/test_buildpython_runner.py tests/test_appimage_build.py` plus `/usr/bin/shellcheck -x ...` gave 56 passed and empty ShellCheck, both EXIT 0. Standard `.venv/bin/python -m buildpython` gave 9/9 PASS, 2,198 tests, 2 optional coverage skips, 8 warnings. Extended 17-step campaign command with `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools` gave ALL 17 PASS, 0 fail/skip, 2,200 tests, 8 warnings, run `ae12bf1a-e3fe-48eb-b862-331e3d2a1a32` status passed. Coverage 94.29% (6,213 / 6,589 statements, 92 files), unchanged since DEBT-12. Roots: 95 broad / 21 Base / 55 unlogged, hygiene 55, watchlist 17, imports 24 warning / 6 critical, flat directories 7 with 116 test files, dead code 8 test-only / 0 actionable, architecture 0.
- Packaging support on the same HEAD: `.venv/bin/python -m buildpython --run-steps "AppImage,AppImage Smoke" --continue-on-error` built PASS in 20.3 sec; Docker smoke FAILED exit 2 for missing Docker, run `2d44f097-d26b-44a4-b558-06d796cebeba`. Fresh image checks with `XDG_CACHE_HOME=/tmp/opencode`, same `TMPDIR`, and `QT_QPA_PLATFORM=offscreen` imported dbus, dbus_next, evdev, pyudev, tomli_w, packaging, numpy, and host openrazer.client without constructing a manager, imported GUI main and ipc server connect plus lifecycle class without calling, asserted `LD_LIBRARY_PATH` contains `/site-packages/PySide6/Qt/lib`, constructed `QApplication`, printed `packaged-glob-launcher-and-qt-offscreen-ok`, and passed `service`/`capture --help`. No live bus, devices, service start, installed image, root, package installs, model config, or commit.

### DEBT-06 Cohort1 Record (in progress, not complete)

- Status: DEBT-06 remains IN PROGRESS on 2026-10-06. Cohort1 verified only; whole item not complete. Historical baseline `4baf4e8`; current HEAD `bb32ac9`.
- Scope (docs wave changes only this tracker; implementation wave already landed): `tests/test_service_runtime.py` 400 -> 305 lines, new `tests/service_runtime_fakes.py` 101 lines with direct Worker/Session/Store plus `connection`/`available` builders and same-name re-exports preserving `test_service_session_lifecycle.py` and `test_service_session_barrier.py` consumers; 11 runtime tests collected before/after with no new behavior cases. No product, GUI, domain, runtime event-state, or other test edits in this docs wave.
- Supervisor verification on HEAD `bb32ac9` (external GPL plus concurrent installer/release edits preserved, not ours): focused `.venv/bin/pytest -q tests/test_service_runtime.py tests/test_service_mode.py tests/test_service_mode_recovery.py tests/test_service_lifecycle_failures.py tests/test_service_session_barrier.py tests/test_service_session_lifecycle.py tests/test_service_worker_fencing.py` gave 83 passed, and `.venv/bin/pytest --collect-only -q tests/test_service_runtime.py` gave 11 collected, same. Standard `.venv/bin/python -m buildpython` gave 9/9 PASS, 2,199 tests, 2 optional coverage skips, 8 warnings. Extended 17-step campaign command with `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools` gave ALL 17 PASS, 2,201 tests, 8 warnings, run `f37f8d93-36e8-4bad-ae38-58dd9c857f16` on 2026-10-06T22:00UTC status passed. Coverage 94.29% (6,213 / 6,589 statements, 92 files), unchanged. Watchlist 17 -> 16 (runtime test removed from monitor), imports 24 -> 23 warning / 6 critical same, flat directories 7 with 117 test files, broad 95 / Base 21 / unlogged 55, hygiene 55, dead code 8 test-only / 0 actionable, architecture 0, max files 399 now none at 400 (largest GUI 399). Standard 2,198 -> 2,199 is the new physical-limit param in the new fakes-adjacent file, not new behavior cases. No new product and no AppImage rebuild needed, test only. Prior AppRun ShellCheck subset accepted as 17 checks; Docker last package FAILED exit 2 run `2d44f097-d26b-44a4-b558-06d796cebeba`, so whole DEBT-09 stays blocked, not complete.
- Remaining: 16 watchlist items. Next bounded DEBT-06 cohort2 assesses GUI tray/version test modules (399 each) via disjoint read-only scout then executor responsibility split; remaining touched sources runtime 377, backend 382, and exception scanner 368 need later-cohort rationale with no giant mixins or mechanical splits. Keep one campaign item in progress.
- Handoff: context/execution limits force current primary reviewed checkpoint HANDOFF after this cohort, not a user pause/ask. Continuation is next bounded DEBT-06 cohort2 as above. Git mutations forbidden; current tree extensive user work stays unstaged/uncommitted.

### DEBT-06 Cohort2 Record (in progress, not complete)

- Status: DEBT-06 remains IN PROGRESS on 2026-10-07. Cohort2 verified only; whole item not complete. Historical baseline `4baf4e8`; current HEAD `bb32ac9`. Do not mark whole DEBT-06 complete on this cohort.
- Scope (this docs wave changes only this tracker; implementation waves already landed): 4 paths `tests/test_gui_tray_scroll.py` 399 -> 324 lines plus new `tests/gui_tray_scroll_fakes.py` 96 lines, and `tests/test_gui_version_panel.py` 399 -> 336 lines plus new `tests/gui_version_panel_fakes.py` 88 lines. Tray fakes hold `_document`, `ScrollClient`, `GatedScrollClient`, `qapp`, `window` with direct `as`-same fixture re-exports and no forwarding functions; supervisor diff read verifies assertions moved with no behavior change, same 9 funcs and 16 cases. Version fakes hold `qapp`, autouse `no_http`/`browser`, `settings`, `worker`, plus `make_releases`/`make_panel`/`check_panel` with explicit `as`-same imports preserving autouse scope and no HTTP. Extra guards/worker behavior files not created; minimal fixture/setup extraction kept all test funcs in original modules. No product, runtime, service-mode, AppImage, config, or other test edits in these waves.
- Supervisor verification on HEAD `bb32ac9` (concurrent user license/installer/release diffs preserved without attribution, not ours): focused `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/test_gui_tray_scroll.py tests/test_gui_tray_scroll_reconcile.py tests/test_gui_tray_profiles.py tests/test_gui_version_panel.py tests/test_gui_releases.py tests/test_gui_worker.py tests/test_gui_app.py` gave 128 passed, 8 warnings; `pytest --collect-only` tray plus version gave 33 collected (16 plus 17) SAME before/after. Standard `.venv/bin/python -m buildpython` gave 9/9 PASS, 2,201 tests, 2 optional coverage skips, 8 warnings. Extended exact 17-step campaign command with temporary `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools` gave ALL 17 PASS, 2,203 tests, 8 warnings, run `2bdd2c82-7b63-4422-ac64-bac239a31150` UTC 2026-10-07T07:50 status passed.
- Measurements: product coverage 94.29% (6,213 / 6,589 statements, 92 files) UNCHANGED; broad 95 / Base 21 / local-unlogged 55, hygiene 55 same; architecture 0; max line 397; watchlist 16 -> 14 (tray and version tests removed from monitor); imports 23 warning / 6 critical unchanged; flat directories 7 with 119 test files; dead code 8 test-only / 0 actionable. Standard rose 2,199 -> 2,201 from the 2 new helper physical-limit params, not new behavior cases; extended 2,203 is standard plus the 2 optional coverage tests that run only with coverage available in the temporary PYTHONPATH. No runtime imports, no AppImage build needed for this test-only split, Docker still blocked, no hardware, no live GUI/service, no main-window show. Forwarding root none; quiesce with no message pins.
- Remaining: 14 watchlist items. Next bounded DEBT-06 cohort3 covers AppImage/service-mode tests as the already authorized next small wave; both next code workers will write only disjoint other tests, not docs. This tracker remains the sole doc-owner path for that wave. Keep one campaign item in progress.
- Docs-worker checks: rerun not needed from this docs worker; supervisor already verified focused, standard, and extended gates above. No Git mutations, no credentials, no installs, no root, no hardware, no deployments in this docs wave.

### DEBT-06 Cohort3 Record (in progress, not complete)

- Status: DEBT-06 remains IN PROGRESS on 2026-10-07. Cohort3 verified only; whole item not complete. Historical baseline `4baf4e8`; current HEAD `bb32ac9`. Do not mark whole DEBT-06 complete on this cohort.
- Scope (this docs wave changes only this tracker; implementation waves already landed): 2 diffs plus 2 new helpers. `tests/test_appimage_build.py` 392 -> 320 lines plus new `tests/appimage_assembly_fakes.py` 81 lines with verbatim `write`, `asset_sources`, `probe_data`, and `FakeAssembly`; fixture stays local with no forwarding wrappers. `tests/test_service_mode.py` 386 -> 263 lines plus new `tests/service_mode_fakes.py` 133 lines with concrete `Worker`/`Session`, `connection`/`available`, and `service_for`; direct re-exports preserve 6 actual consumers with the same worker identities and no merge with runtime fakes. Supervisor read both diffs and both helpers verbatim; no behavior change. No product, config, GUI, or other test edits in these waves. Time and handoff scoping only; no new safety claims are inferred from fixture class differences.
- Supervisor verification on HEAD `bb32ac9` (concurrent user work untouched, not attributed here): focused `.venv/bin/pytest -q tests/test_appimage_build.py tests/test_buildpython_runner.py tests/test_appimage_payload.py tests/test_service_mode.py tests/test_service_mode_recovery.py tests/test_service_lifecycle_failures.py tests/test_service_session_barrier.py tests/test_service_session_lifecycle.py tests/test_service_worker_fencing.py tests/test_service_reservation_cleanup.py tests/test_service_runtime.py` gave 159 passed, 8 warnings; `pytest --collect-only` AppImage plus mode gave 50 collected (36 plus 14) SAME before and after. Standard `.venv/bin/python -m buildpython` gave 9/9 PASS, 2,203 tests, 2 optional coverage skips, 8 warnings. Extended exact 17-step campaign command with temporary `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools` gave ALL 17 PASS, 2,205 tests, 8 warnings, run `ced65ff4-0670-4752-b8c5-304860ee3ab0` UTC 2026-10-07T08:11 status passed.
- Measurements: product coverage 94.29% (6,213 / 6,589 statements, 92 files) UNCHANGED; broad 95 / Base 21 / local-unlogged 55, hygiene 55 same; architecture 0; watchlist 14 -> 12 (AppImage and mode tests removed from monitor); imports 23 warning / 6 critical; flat directories 7 with 121 test files; dead code 8 test-only / 0 actionable. Standard rose 2,201 -> 2,203 from the 2 new helper physical-limit params, not new behavior cases; extended 2,205 is standard plus the 2 optional coverage tests that run only with coverage available in the temporary PYTHONPATH. No AppImage rebuild required for this test-only split, no hardware, no live GUI or service, Docker still blocked.
- Remaining: 12 watchlist items. Next bounded DEBT-06 cohort4 covers the remaining GUI tests (mouse settings, buttons page, and tray profiles) through disjoint responsibility fakes extraction; next workers own only their disjoint tests and this tracker remains the sole doc-owner path. Keep one campaign item in progress.
- Docs-worker checks: guide-only ASCII, local links, and shared-tree diff review. No Git mutations, no secrets, no models, no installs, no root, no hardware, no deployments in this docs wave. Both source writers are done with no concurrent doc writer.

### DEBT-06 Cohort4 Record (in progress, not complete)

- Status: DEBT-06 remains IN PROGRESS on 2026-10-07. Cohort4 verified only; whole item not complete. Historical baseline `4baf4e8`; current HEAD `bb32ac9`. Do not mark whole DEBT-06 complete on this cohort.
- Scope (this docs wave changes only this tracker; implementation waves already landed): 3 diffs plus 3 new helpers, all test-only, no production changes. `tests/test_gui_mouse_settings_page.py` 388 -> 326 lines plus new `tests/gui_mouse_settings_support.py` 72 lines with public `edited`/`edit_all`/`assert_values` and direct `as`-same alias imports preserving calls. `tests/test_gui_buttons_page.py` 369 -> 309 lines plus new `tests/gui_buttons_fakes.py` 68 lines with canonical public defs and unnecessary aliases removed. `tests/test_gui_tray_profiles.py` 355 -> 305 lines plus new `tests/gui_tray_profiles_fakes.py` 62 lines. All six paths are under 350 lines with no file above 400. Existing `tests/gui_support.py` fakes stay distinct with no consolidation. Supervisor read all three diffs and all three helpers verbatim; moved assertions and doubles are unchanged.
- Supervisor verification on HEAD `bb32ac9` (concurrent user license/installer/release changes preserved without attribution, not ours): focused `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/test_gui_mouse_settings_page.py tests/test_gui_settings_pages.py tests/test_gui_draft_reconciliation.py tests/test_gui_buttons_page.py tests/test_gui_mapping_map.py tests/test_gui_tray_profiles.py tests/test_gui_profile_switch_revisions.py tests/test_gui_profiles_page.py tests/test_gui_tray_scroll.py tests/test_gui_app.py` gave 130 passed, 8 warnings; `pytest --collect-only` on the three targets gave 38 collected (13 plus 15 plus 10) SAME before and after with original names and params unchanged. Standard `.venv/bin/python -m buildpython` gave 9/9 PASS, 2,206 tests, 2 optional coverage skips, 8 warnings. Extended exact 17-step campaign command with temporary `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools` gave ALL 17 PASS, 2,208 tests, 8 warnings, run `1a14843a-4e50-45b2-be98-442d0911bae2` UTC 2026-10-07T08:38 status passed.
- Measurements: product coverage 94.29% (6,213 / 6,589 statements, 92 files) UNCHANGED; broad 95 / Base 21 / local-unlogged 55, hygiene 55 same; architecture 0; watchlist 12 -> 9; imports 23 warning / 6 critical; flat directories 7 with 124 test files; dead code 8 test-only / 0 actionable. Standard rose 2,203 -> 2,206 from the 3 new helper physical-limit params, not new behavior cases; extended 2,208 is standard plus the 2 optional coverage tests that run only with coverage available in the temporary PYTHONPATH. No AppImage rebuild, hardware, package, or live GUI/service required for this test-only split; DEBT-09 Docker remains blocked.
- Remaining: 9 watchlist items, all verified at or below 400 lines with the largest at 397: `tests/hardware/test_ui06_guided.py` 397 (opt-in, do not run), `src/naga_control/gui/buttons_page.py` 390, `src/naga_control/adapters/openrazer/backend.py` 382, `src/naga_control/gui/app.py` 379, `src/naga_control/service/runtime.py` 377, `buildpython/steps/exception_transparency/scanner.py` 368, `buildpython/steps/_architecture_validation_load.py` 365, `buildpython/core/debt_index.py` 357, `buildpython/steps/_architecture_validation_scan.py` 351. Next bounded DEBT-06 cohort5 is a read-only tooling scout for `scanner.py` plus `debt_index.py` preserving existing report contracts, with debt-analysis tests `tests/test_buildpython_analysis.py` and exception-transparency tests as the consumer list; no new feature, waivers, hardware, worker pins, or cohort5 code in this wave. Keep one campaign item in progress.
- Handoff: context and execution limits force a primary yield after reviewed passing cohorts 2, 3, and 4, not a user pause or status question. Continuation is a fresh-scope cohort5 scout with new worker sessions, not a task resume. No Git staging, commit, branch, or destructive operation in this docs wave. This tracker is the sole doc-owner path for the wave.
- Docs-worker checks: ASCII-only, local links, and shared-tree diff review only. No product or test writes, no Git mutations, no credentials, no installs, no root, no hardware, no deployments in this docs wave.

### DEBT-06 Cohort5 Record (in progress, not complete)

- Status: DEBT-06 remains IN PROGRESS on 2026-10-07. Cohort5 verified only; whole item not complete. Historical baseline `4baf4e8`; current HEAD `bb32ac9`. Do not mark whole DEBT-06 complete on this cohort. All other campaign statuses unchanged. Preexisting and concurrent state at HEAD `bb32ac9` preserved without attribution or reverts.
- Scope (this docs wave changes only this tracker; implementation wave already landed): build-tooling responsibility splits only, no product/service/GUI/hardware-adapter changes. `buildpython/steps/exception_transparency/scanner.py` 368 -> 227 lines plus new `buildpython/steps/exception_transparency/handler_identity.py` 68 lines and new `buildpython/steps/exception_transparency/diagnostic_signals.py` 87 lines under the existing exception-transparency owner; `buildpython/core/debt_index.py` 357 -> 122 lines plus new `buildpython/core/debt_index_markdown.py` 236 lines; new `tests/test_debt_index.py` 334 lines with 6 meaningful cases GREEN pre/post. No shared common edits, no facades, no unused re-exports.
- Design: original API, counts, schema, and report formatting preserved. Extracted AST definitions kept verbatim; the new Markdown writer is a pure MD formatter. `code_markers` output intentionally remains JSON only. No new waivers, exclusions, budgets, scanners, or gates.
- Worker method: the implementation worker used manual edit/write because `apply_patch` was unavailable in that worker session. Cohort5 S+D was independently reviewed, and the supervisor reviewed the resulting files and diffs before acceptance.
- Tests: the 6 new debt-index cases are meaningful behavior assertions, not inflated coverage. Do not overclaim a full-JSON every-field test: the main case asserts schema/order plus selected values and exact representative Markdown, with JSON round-trip comparison for the remainder.
- Supervisor verification on HEAD `bb32ac9` (concurrent user work preserved without attribution, not ours): focused `.venv/bin/pytest -q tests/test_debt_index.py tests/test_buildpython_exception_transparency.py tests/test_buildpython_quality_exceptions.py tests/test_buildpython_analysis.py tests/test_buildpython_runner.py` gave 156 passed. Standard `.venv/bin/python -m buildpython` gave 9/9 PASS, 2,216 tests passed, 2 optional coverage tests skipped, 8 warnings. Extended exact 17-step campaign Verification Routine command with temporary `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools` gave ALL 17 PASS, 0 failed, 0 skipped, 2,218 tests passed, 8 warnings, run `f6601f24-1814-4e25-8407-b785f56f3ee4` UTC 2026-10-07T19:00:56.186Z status passed.
- Measurements: product coverage 94.29% (6,213 / 6,589 statements, 92 product files) UNCHANGED. Broad 95 / Base 21 / local-unlogged 55, hygiene 55 same; architecture 0; max 397 with no file over 400; watchlist 9 -> 7; imports 23 warning / 6 critical unchanged; flat directories 7 -> 8 because exception-transparency now reaches 8 direct Python files; tests-direct 124 -> 125. Vulture 8 all test-only / 0 actionable. Standard 2,216 - 2,206 = 10 is 6 behavior cases plus 4 new Python physical-limit params (3 tooling helpers plus 1 test file), not optional coverage; same-wave extended +2 is optional-coverage availability with the temporary tools PYTHONPATH.
- Flat-directory note: the 7 -> 8 change is an honestly recorded informational warning from the tooling split, not a regression gate failure. Disposition of that structure signal belongs to DEBT-08 later.
- Packaging/operations: no AppImage rebuild needed (build tooling and tests only). Docker remains blocked on the prior package run `2d44f097-d26b-44a4-b558-06d796cebeba` exit 2 for missing Docker. No hardware, deployment, live GUI/service, install, or commit in this wave.
- Remaining: 7 watchlist items, all verified at or below 400 lines with the largest at 397: `tests/hardware/test_ui06_guided.py` 397 (opt-in, do NOT run), `src/naga_control/gui/buttons_page.py` 390, `src/naga_control/adapters/openrazer/backend.py` 382, `src/naga_control/gui/app.py` 379, `src/naga_control/service/runtime.py` 377, `buildpython/steps/_architecture_validation_load.py` 365, `buildpython/steps/_architecture_validation_scan.py` 351. Keep DEBT-06 in progress, not completed.
- Handoff: next authorized DEBT-06 cohort6 is a read-only scout then a bounded architecture-tooling refactor if coherent. A cohort6 scout may already be running concurrently; treat that concurrent work as scout only, not delivery. No Git staging, commit, branch, or destructive operation in this docs wave. This tracker is the sole doc-owner path for the wave.
- Docs-worker checks: ASCII-only, local link targets, stale counts, and name consistency review only. No product, test, or other-docs writes; no Git mutations, delegation, credentials, models, root, live operations, or hardware in this docs wave.

### DEBT-06 Cohort6 Record (in progress, not complete)

- Status: DEBT-06 remains IN PROGRESS on 2026-10-07. Cohort6 verified only; whole item not complete. Historical baseline `4baf4e8`; current HEAD `bb32ac9`. Do not mark whole DEBT-06 complete on this cohort. All other campaign statuses unchanged. Preexisting and concurrent state at HEAD `bb32ac9` preserved without attribution or reverts.
- Scope (this docs wave changes only this tracker; implementation wave already landed): architecture-tooling responsibility splits only, no product/service/GUI/hardware-adapter changes. `buildpython/steps/_architecture_validation_load.py` 365 -> 224 lines plus new `buildpython/steps/_architecture_validation_load_calls.py` 159 lines; `buildpython/steps/_architecture_validation_scan.py` 351 -> 201 lines plus new `buildpython/steps/_architecture_validation_scan_calls.py` 186 lines, all under the existing `buildpython/steps` owner; new `tests/test_architecture_rule_loading.py` 331 lines with 45 cases and new `tests/test_architecture_call_findings.py` 344 lines with 11 cases. Canonical original load size is 365, not worker-reported 366. No shared models/helpers/integrity/call-AST/public-facade/schema/config/gate edits; exact bool/exemption types, alias validation, messages, caches, dedup, findings, and sort preserved.
- Design: verbatim move of rule-loading and call-findings logic into the new call modules; retained AST definitions and exact reporting contracts. No new waivers, exclusions, budgets, scanners, or gates. Optional review gaps (receiver-suffix scanning, cache explicit check) are nonblocking for this wave due to the verbatim move and retained AST; no extra tests needed for this wave.
- Worker method: characterization is GREEN pre/post, not a product RED. Initial 2 test-authoring failures (JSON set and sort expectation) were fixed before extraction; do not claim a product RED from those authoring failures.
- Supervisor verification on HEAD `bb32ac9` (concurrent user work preserved without attribution, not ours): focused `.venv/bin/pytest -q tests/test_architecture_rule_loading.py tests/test_architecture_call_findings.py tests/test_buildpython_analysis.py tests/test_buildpython_runner.py tests/test_debt_index.py` gave 90 passed. Standard `.venv/bin/python -m buildpython` gave 9/9 PASS, 2,467 tests passed, 2 optional coverage tests skipped, 8 warnings. Extended exact 17-step campaign Verification Routine command with temporary `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools` gave ALL 17 PASS, 0 failed, 0 skipped, 2,469 tests passed, 8 warnings, run `f0e5ccb8-bd76-4232-ae00-f1bda1f02e7c` UTC 2026-10-07T19:29:27.144Z status passed.
- Measurements: product coverage 94.29% (6,213 / 6,589 statements, 92 product files) UNCHANGED. Broad 95 / Base 21 / local-unlogged 55, hygiene 55 same; architecture 0; max 397 with no file over 400; watchlist 7 -> 5; imports 24 warning / 6 critical; flat directories 8 unchanged; tests-direct 125 -> 137; Vulture 8 all test-only / 0 actionable. Standard 2,216 -> 2,467 = 251 is 56 new behavior cases plus 4 new physical-limit params from this cohort AND 191 concurrent changes not ours; do not attribute the full increase to this cohort. Same-wave extended +2 is optional-coverage availability with the temporary tools PYTHONPATH.
- Concurrent changes (not ours, preserved unattributed): user work grew `.github/workflows/release.yml`, `README.md`, `install.sh`, `scripts/install_user.sh`, `scripts/prepare_release.py`, `scripts/uninstall.sh`, new `scripts/publish_release_assets.py` / `scripts/validate_release_assets.py`, release/installer helpers and tests including new `test_openrazer_packages.py` and related installer/release churn. This record claims only the 6 architecture tooling/test paths above plus this tracker.
- Packaging/operations: no AppImage build required for this tooling/tests split. Docker remains blocked on the prior package run `2d44f097-d26b-44a4-b558-06d796cebeba` exit 2 for missing Docker. No hardware, deployment, live GUI/service, install, or commit in this wave.
- Remaining: 5 watchlist items, all verified at or below 400 lines with the largest at 397: `tests/hardware/test_ui06_guided.py` 397 (opt-in, do NOT run), `src/naga_control/gui/buttons_page.py` 390, `src/naga_control/adapters/openrazer/backend.py` 382, `src/naga_control/gui/app.py` 379, `src/naga_control/service/runtime.py` 377. Keep DEBT-06 in progress, not completed. Runtime/backend/hardware exception rationales are a future decision, not complete in this doc wave.
- Handoff: next authorized DEBT-06 cohort7 GUI ownership splits are scouted and about to be implemented by a separate worker; no cohort7 delivery is claimed now. No Git staging, commit, branch, or destructive operation in this docs wave. This tracker is the sole doc-owner path for the wave.
- Docs-worker checks: ASCII-only, local link targets, stale counts, and name consistency review only. No product, test, or other-docs writes; no Git mutations, delegation, credentials, models, root, live operations, or hardware in this docs wave.

### DEBT-06 Cohort7 Record (in progress, not complete)

- Status: DEBT-06 remains IN PROGRESS on 2026-10-07. Cohort7 verified only; whole item not complete. Historical baseline `4baf4e8`; current HEAD `bb32ac9`. Do not mark whole DEBT-06 complete on this cohort. All other campaign statuses unchanged. Preexisting and concurrent state at HEAD `bb32ac9` preserved without attribution or reverts, including all historical records and other statuses.
- Scope (this docs wave changes only this tracker; implementation waves already landed): GUI ownership splits only, no test writes and no new behavior cases. `src/naga_control/gui/buttons_page.py` 390 -> 309 lines plus new `src/naga_control/gui/buttons_rows.py` 109 lines; `src/naga_control/gui/app.py` 379 -> 70 lines plus new `src/naga_control/gui/main_window.py` 323 lines, all under the existing `gui/` owner. Explicit callback factory plus concrete `ButtonRow` with pure row-option state; the page retains dirty/profile/calibration apply. `MainWindow` wholesale extraction plus `app_icon_path` move from entry; app retains `main`/log failure; concrete used-bindings imports preserve actual test-consumer identity with no facades or cycles. One nonfunctional logger-category change `gui.app` -> `gui.main_window` for tray-unavailable info. `Any` unchanged; the moved follow-up is DEBT-07.
- Supervisor inspected the full actual diff and the new helper contents before acceptance.
- Focused: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/test_gui_buttons_page.py tests/test_gui_click_wheel.py tests/test_gui_draft_reconciliation.py tests/test_gui_mapping_map.py tests/test_gui_app.py tests/test_gui_tray_scroll.py tests/test_gui_tray_profiles.py tests/test_gui_profile_switch_revisions.py tests/test_gui_tray_scroll_reconcile.py` gave 119 passed, 8 warnings. Worker collected before/after 119 identical with the same existing names/params.
- Standard: `.venv/bin/python -m buildpython` gave 9/9 PASS, 2,560 passed, 2 optional coverage skips, 8 warnings.
- Extended: the exact 17-step campaign Verification Routine command with temporary `PYTHONPATH=/tmp/opencode/naga-build-analysis-tools` gave ALL 17 PASS, 0 failed, 0 skipped, 2,562 passed, 8 warnings, run `682d0254-4e2a-4101-b98a-fad1ec89792a` UTC 2026-10-07T19:45:29.361Z status passed.
- Measurements: product coverage 94.31% (6,227 / 6,603 statements, 94 product files) versus previous 94.29% (6,213 / 6,589, 92 files); 14 additional covered statements from import/callback-wiring refactor, not new behavior; uncovered 376 unchanged. App 44.44% (24/54) now entry only; main window 88.46% (184/208); avoid direct old-file coverage comparison because the denominator changed. Broad 95 / Base 21 / local-unlogged 55, hygiene 55 same; no exclusions, budgets, waivers, scanners, or gates changed; architecture 0 errors/warnings with 81 headless files scanned.
- Watchlist 5 -> 4 total: 2 GUI entries removed, but concurrent user `tests/test_release_preparation.py` now 354 added; not ours, do not edit that active ownership. Originals 3 remaining: `tests/hardware/test_ui06_guided.py` 397 (opt-in, do NOT run), `src/naga_control/adapters/openrazer/backend.py` 382, `src/naga_control/service/runtime.py` 377; 3/18 original scoped residual, not zero.
- Imports 25 warning / 5 critical (previous 24/6); flat directories 8; tests-direct 137 -> 139 concurrent (NONE test files added here). Default 2,467 -> 2,560 = 93 includes only 2 ours new-product physical-limit params plus 91 concurrent changes; no GUI behavior cases added. Extended +2 is optional-coverage availability in the same wave. Vulture 8 test-only / 0 actionable; max 397; no file above 400.
- Concurrent external release/installer work preserved; do not attribute the full suite growth to the GUI wave.
- Packaging: `.venv/bin/python -m buildpython --run-steps "AppImage,AppImage Smoke" --continue-on-error` gave build PASS in 22 sec; Docker smoke FAILED exit 2 ("Docker is required for AppImage smoke checks"), run `bc95fa0e-589e-4670-862b-a31fe29c5887` UTC 2026-10-07T19:47:54.215Z. Local `dist/Naga-Control-0.4.0-x86_64.AppImage` rebuilt, not installed/released.
- Host actual-image checks with `XDG_CACHE_HOME=/tmp/opencode TMPDIR=/tmp/opencode QT_QPA_PLATFORM=offscreen`: imported dbus/dbus_next/evdev/pyudev/tomli_w/packaging/numpy/openrazer.client (no DeviceManager constructed); entry plus new window/buttons modules (assert `__file__` inside APPDIR, same class identities, icon exists); `QApplication([])`; synthetic `build_button_row` (control ring_finger, action None, noop callbacks); assert passthrough/detail-edit disabled, select key plus sync detail edit enabled; close root; no main-window construction/show/app.exec; printed `packaged-gui-ownership-and-qt-offscreen-ok`; service/capture `--help` EXIT 0. No bus/service/hardware instantiated. Host checks are not a clean-container/hardware claim; DEBT-09 remains blocked.
- Handoff: current primary context/execution-limit HANDOFF (not user pause/status ask): all writers done, HEAD `bb32ac9`, all changed paths unstaged/uncommitted, concurrent user work preserved, no Git mutation.
- Next bounded authorized wave: DEBT-06 retained-owner rationale assessment before any source edits. Scout found runtime lock/fence/epoch state coupled already ConfigurationAuthority/SessionLifecycle/snapshot/calibration owners, 377 allows 23 lines; backend selection/operation client generation failure state already capabilities/settings/mode owners, 382 allows 18 lines; hardware interactive gates/restore whole procedure 397 allows 3 lines plus test_ui06_sleep shared imports and requires real interactive acceptance for changed procedure -- do not run or edit now. Record these as provisional risk/rationale candidates, NOT final accepted closure/waivers (especially tight 18/23/3); future growth must precede safety review/coherent extraction. External release-test 354 not authorized parallel owned path; routing ownership resolution, not automatic split. DEBT-07 six-Any follow-up queued, now app/main_window/mapping_map locations changed; no work done yet.
- Docs-worker checks: ASCII, local Markdown link-target checks, name counts, and shared-tree diff only; no product/test/full reruns. No Git mutations, delegation, secrets, models, install, root, deploy, live GUI/service, real device nodes, or hardware in this docs wave.

### DEBT-06 Closure Decision (review-only, 2026-10-07)

- Status: DEBT-06 COMPLETE on 2026-10-07 by independent read-only docs review.
  No product, test, tooling, or other-docs edits in this wave; only this tracker
  changed. No Git mutations, credentials, installs, root, deployments, live
  GUI/service, real device nodes, or hardware tests in this wave.
- Basis (no fresh checks): the last supervisor-verified cohort7 evidence on HEAD
  `bb32ac9` stands unchanged: standard `.venv/bin/python -m buildpython` 9/9
  PASS, 2,560 tests passed, 2 optional coverage tests skipped; extended exact
  17-step campaign command ALL 17 PASS, 0 failed, 0 skipped, 2,562 tests passed,
  run `682d0254-4e2a-4101-b98a-fad1ec89792a`; product coverage 94.31%
  (6,227 / 6,603 statements, 94 files); 0 files above 400 lines, largest 397;
  watchlist 4. This docs-only review reran no tests and adds no new measurement
  row; all historical tracking rows and numbers are preserved unchanged.
- Acceptance applied: per the DEBT-06 work specification, every watchlist item
  touched by this campaign has usable headroom (aim under 350 lines where a
  coherent split exists); exceptions below the hard 400-line maximum carry the
  written rationale below. This is not a claim that all files are below 350 or
  that no debt remains. There are no waivers, exclusions, budgets, or line-gate
  loosening.
- Campaign arithmetic: the original 18-item watchlist resolves as 15 files below
  350 lines via earlier DEBT-03/05 ownership extractions (capture/sources and
  configuration-authority/session-lifecycle owners) plus 7 DEBT-06 cohorts,
  plus 3 reviewed retained exceptions below 400 lines.
  The current watchlist of 4 is 3 original retained exceptions plus 1 concurrent
  externally owned file, not a zero list.
- Retained exception 1: `src/naga_control/service/runtime.py`, 377 lines
  (23 below the hard maximum). ConfigurationAuthority (77 lines),
  SessionLifecycle (88 lines), snapshot (58 lines), and calibration (53 lines)
  are already extracted coherent owners. The remainder is lock-serialized
  poll/rescan/shutdown orchestration owning `_lock`/sessions/worker/config/
  topology epoch/observed mode. Moving the predicate (~6 lines net) yields no
  savings; extracting recovery would split fence epoch/lock ownership and invite
  mixins. Accepted exception: no extra runtime behavior growth without first a
  characterized coherent-owner extraction plus fake-based regression checks.
  An interactive hardware gate applies only to changed physical behavior or
  procedure, not to comment/import-level growth in this file.
- Retained exception 2: `src/naga_control/adapters/openrazer/backend.py`,
  382 lines (18 below the hard maximum). Capabilities (163 lines), settings
  (135 lines), and mode (61 lines) are existing owners. The remainder (client
  selection/generation/failure invalidation plus single DPI/scroll operations)
  is cohesive. Extracting the pure `_matches`/`_issue` helpers (~18 lines)
  would yield ~364 lines, still not 350, plus a micromodule; a bigger coupled
  extract risks client-generation/no-uncertain-write-retry policy. Accepted
  exception: no new capability logic in backend; existing owners come first,
  with prior characterized extraction before growth.
- Retained exception 3: `tests/hardware/test_ui06_guided.py`, 397 lines
  (3 below the hard maximum), UNTOUCHED. Shared imports by `test_ui06_sleep`
  prove a possible `ui06_support` owner, which does not deny a coherent split;
  extraction is deliberately DEFERRED until explicitly authorized interactive
  acceptance with TTY, backup keyboard, single transport, and cleanup/mode
  restore proved on both transports. No static/fake proof substitutes for a
  physical pass. Do not run or edit now.
- Concurrent external file: `tests/test_release_preparation.py`, 354 lines
  (46 below the hard maximum), remains under concurrent external ownership, out
  of campaign scope: no edit and no ratchet freeze on that file. The hard
  400-line limit still applies globally.
- Growth rule: any growth in a retained file must first support helper
  extraction plus fake-based regression checks. An interactive hardware gate is
  required only for changed physical behavior or procedure; it is not a
  mandatory gate for comment/import-level growth in backend/runtime. The
  hardware-procedure extract (ui06) still requires explicit interactive
  acceptance and remains deferred.
- Transparency: all cohort deliveries remain unstaged/uncommitted with
  preexisting retention-log rationale; nothing was staged, committed, or
  reverted by this wave.
- Follow-up: DEBT-07 is now in progress; a code worker is authorized to
  implement the type replacements for the actual 6 `Any` annotations relocated
  to `app`/`main_window`/`mapping_map` by cohort7. No DEBT-07 completion and no
  new measurements are claimed here.

### DEBT-07 Delivery Progress Record (in progress, full verification blocked, 2026-10-07)

- Status: DEBT-07 IN PROGRESS WITH FULL VERIFICATION BLOCKED on 2026-10-07.
  No completion claimed. DEBT-06 remains complete; DEBT-08/10 remain queued;
  DEBT-09 remains blocked (ShellCheck subset complete; Docker pending). This is
  a docs-only handoff wave; only this tracker changed here. HEAD `bb32ac9`
  preserved with extensive prior plus active external release/installer/CI/
  screenshots/docs work untouched, not ours. No Git mutations, credentials,
  paid models, installs, root, live GUI/service, real device nodes, or
  hardware in this docs wave.
- Implementation scope (already landed uncommitted/unstaged, not by this docs
  wave): 5 paths plus this tracker. Under `src/naga_control/gui/`: `app.py`
  71 lines, `main_window.py` 322 lines, `mapping_map.py` 152 lines,
  `worker.py` 61 lines; plus new `tests/test_gui_log_failure.py` 41 lines
  with 3 cases. Bodies and lifetime unchanged; imports and signatures only.
  No type guards, protocol shim, cast for weakening, or product ignore added.
- Annotation disposition: the 6 baseline `Any` flags are now concrete:
  `Future[object]`; `QCloseEvent`; 2 `QGraphicsSceneHoverEvent`;
  `QGraphicsSceneMouseEvent`; `QResizeEvent`. `LoopWorker.submit` uses the
  existing `CoroFactory` -> `Future[object]` contract; `Coro` protocol
  `Any`/`Any` retained as legitimate outside the 6. No fresh `Any` hygiene,
  LOC, or architecture counts are claimed here; worker-verified source
  physical counts are noted above but the latest full LOC gate did NOT run.
- Test-only exception, supervisor decision: one test-only
  `#pyright:ignore[reportPrivateUsage]` on the private-callback import is
  allowed to characterize without a public API rename. This does NOT waive
  future type checking. Record as an exact-scope exception, not a generic
  permit.
- Focused gate (supervisor-run):
  `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/test_gui_log_failure.py tests/test_gui_worker.py tests/test_gui_app.py tests/test_gui_mapping_map.py tests/test_gui_update_shutdown.py tests/test_gui_version_panel.py`
  gave 50 passed, 8 warnings. Worker-scoped Ruff, format, and Pyright were
  green in the implementation wave.
- Standard gate, latest actual: supervisor `.venv/bin/python -m buildpython`
  run `834e2db3-3fa5-415b-93d4-f79d3723e2ed` UTC 2026-10-07T20:50:11.341Z
  overall FAIL exit 1: 4 pass, 1 fail, 4 not run; tests 1 failed, 2641
  passed, 2 skips, 8 warnings. Compile, Ruff, Format, and Pyright PASSED;
  Pytest FAILED on one external test; remaining 4 checks NOT RUN.
- Initial standard attempt in this sequence failed 4 lint findings in
  externally owned `tests/installer_app_fakes.py`,
  `tests/test_installer_bootstrap.py`, `tests/test_installer_layout.py`, and
  `tests/test_installer_upgrade.py`. Those were externally corrected, not
  ours; subsequent Ruff showed 0 findings and the default lint step passed.
- Exact blocking failure:
  `tests/test_installer_preflight.py::test_extraction_is_only_used_when_explicitly_requested`.
  With `fake.environment APPIMAGE_EXTRACT_AND_RUN='1'`, the install result
  was successful but `assert not any(c[0] in {'ldconfig','stat'} for
  commands)` fails (full-run line 96; isolated line 97 in current owned
  churn). This path is not a DEBT-07 path and is not ours. Supervisor bounded
  isolated rerun `.venv/bin/pytest -q
  tests/test_installer_preflight.py::test_extraction_is_only_used_when_explicitly_requested`
  gave 1 failed, exit 1, confirming a repeated external gate failure under
  active ownership. No fix, no assert weakening, no skip, and no gate
  bypass was applied.
- Not run after the failed standard: the extended 17-step check and any new
  package build, help, or offscreen verification were intentionally NOT RUN.
  Latest known passing coverage 94.31% from cohort7 run
  `682d0254-4e2a-4101-b98a-fad1ec89792a` is historical, NOT an 07
  measurement. Last packaging `bc95fa0e-589e-4670-862b-a31fe29c5887` (prior
  GUI package build PASS, Docker FAIL on missing Docker) and host smoke are
  historical, not this changed-type build.
- Suite size note: current partial 2641 passed is NOT compared to the older
  2560 as a delivery delta. Growth includes other new installer files not
  attributable here (3 cases plus 1 physical param); no delivery delta is
  claimed.
- DEBT-08 read-only scout finished but NOT implemented or completed: 8
  historical test-only Vulture candidates remain 0 actionable; 3
  async-generator structural sentinels must be retained; 5 duplicate
  second-raises are confirmed redundancy (recommended keep, optional remove)
  awaiting disposition only after 07 passes; long imports and 8 flat
  directories keep concrete owners with no facade or churn. Metrics cited
  are cohort7 historical, not a new current gate.
- DEBT-10: no budgets, scanners, waivers, or coverage changes in this wave.
  Queue stays pending on 07/08 dependency.
- Ownership blocker: do NOT solicit authorization to edit the external file
  or fix it automatically. Report the ownership blocker as fact and stop at
  the failed gate.
- Handoff: all implementation workers are done; DEBT-07 source remains
  uncommitted/unstaged with the exact 5 changed paths above plus this
  tracker. Next bounded wave ONLY after the external installer owner
  resolves the failure: reread the tree and ownership, then rerun the full
  standard and extended checks and accept 07 only if they pass, then take
  08 dispositions plus the 10 scout.
- Docs-worker checks: ASCII, local link targets, headline/queue status, and
  shared-tree path review only. No product tests or full reruns in this
  docs wave.

### DEBT-07 Acceptance Checkpoint (blocked, 2026-10-08)

- Status: DEBT-07 remains IN PROGRESS, campaign acceptance BLOCKED. Current
  HEAD `154b308`; historical campaign baseline `4baf4e8`. Types implementation
  is committed in `643d791`, not currently uncommitted. The 2026-10-07 records
  above describe their dated state; the 2,718-test standard pass and cohort7
  94.31% coverage remain historical, not current acceptance. DEBT-06 remains
  COMPLETE with its retained exceptions; DEBT-08/10 stay QUEUED. The read-only
  DEBT-08 scout is not delivery or completion.
- Owner/scope: prior executor implemented the bounded source-limit discovery
  correction; supervisor reviewed the actual diff/new file and shared-tree
  status/stat/diff check and reran checks below. This fresh docs-only executor
  changes ONLY `docs/debt-paydown-campaign.md`. The only new implementation
  changes from this campaign session are `tests/test_source_limits.py` (25
  physical lines) and new `tests/test_source_limit_discovery.py` (96 lines),
  both uncommitted/unstaged. No product/type implementation was added here.
- Initial supervisor default command: `.venv/bin/python -m buildpython`, run
  `c854fd6e-a311-4623-92b6-e4f8489d0917`, UTC
  `2026-10-08T16:32:45.255Z`, EXIT 1: 4 passed, 1 failed, 4 not run. Compile,
  Ruff, Format, and Pyright passed; Pytest failed: 22 failed, 3,109 passed,
  2 optional coverage skips, 8 warnings. ALL 22 failures were source-limit
  cases scanning third-party `.opencode/node_modules/node-gyp/gyp` Python
  files, not 22 product bugs. This triggered the narrow correction below.
- Discovery correction: exclude exact `node_modules` DIRECTORY components
  anywhere, not `.opencode` wholesale or similar names. Existing exclusions
  are preserved; owned hidden/custom/root/scripts/src/buildpython/tests and
  hardware-test source files remain statically checked. Hard 400 stays intact;
  scanning hardware-test source does not run hardware tests. No installed
  dependency, OpenCode configuration, scanner, budget, or coverage gate changed.
  The 39 synthetic cases prove exclusions versus similar names and 400-pass /
  401-fail across eight ownership locations. Worker RED before correction was
  4 failed, 35 passed; focused post-fix was 407 passed (physical-file parameters
  can vary with concurrent additions). Worker initial full Ruff/format/Pyright
  passes were advisory, not supervisor acceptance or current global passes.
- Supervisor focused command, EXIT 0: 460 passed, 8 warnings:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q tests/test_source_limits.py tests/test_source_limit_discovery.py tests/test_gui_log_failure.py tests/test_gui_worker.py tests/test_gui_app.py tests/test_gui_mapping_map.py tests/test_gui_update_shutdown.py tests/test_gui_version_panel.py
```

- Supervisor default rerun: `.venv/bin/python -m buildpython`, run
  `74e92468-400d-43f0-b1ac-eaff93c7dc56`, UTC
  `2026-10-08T16:41:04.827Z`, EXIT 1: 1 passed, 1 failed, 7 NOT RUN. Compile
  passed; Ruff FAILED `F401` unused `os` at `tests/uninstaller_fakes.py:4`, an
  externally active untracked file, not ours. The remaining checks, including
  Pytest, did not run. No external fix, skip, suppression, or bypass applied;
  the campaign stopped at the owner blocker.
- Follow-up supervisor scoped checks:

```bash
.venv/bin/ruff check tests/test_source_limits.py tests/test_source_limit_discovery.py
.venv/bin/ruff format --check tests/test_source_limits.py tests/test_source_limit_discovery.py
.venv/bin/pyright
```

  Ruff EXIT 0: `All checks passed!`; format EXIT 0: `2 files already formatted`.
  Global Pyright EXIT 1, CURRENT 4 external errors:
  `tests/test_uninstaller_cleanup.py:61` `inode` possibly unbound,
  `:64` `result` possibly unbound, `:65` `commands` possibly unbound;
  `tests/uninstaller_fakes.py:4` unused `os`. No type errors reported in our
  two test paths. Global Pyright is NOT passing; the latest complete suite
  is NOT passing and there is no current full-suite coverage capture.
- Unrun: extended 17-check campaign and required package gates intentionally
  NOT RUN after the failed standard gate. No new scanner, coverage, watchlist,
  or ratchet measurements claimed. Docker remains BLOCKED as previously
  recorded, not rechecked physically. No package build/install, live GUI/service,
  bus/device/sysfs/raw-HID operation, root, network deployment, staging, commit,
  credential read, or paid-model call in this checkpoint.
- Shared-tree handoff from `git status --short` at this docs wave's start:
  campaign-owned implementation paths are the two tests above. ALL other paths
  below are externally active GUI/device-mode, portability, and uninstaller
  work, preserved without attribution or edits. This is a changing snapshot,
  not acceptance of those external changes. `M` means tracked modified; `??`
  means untracked (the fixture directory entry is as reported by Git):

```text
 M changelog.md
 M docs/post-0.3-ui-tracker.md
 M docs/troubleshooting.md
 M scripts/uninstall.sh
 M src/naga_control/gui/device_page.py
 M src/naga_control/gui/main_window.py
 M src/naga_control/gui/overview_page.py
 M src/naga_control/gui/profiles_page.py
 M src/naga_control/gui/tray_icon.py
 M tests/test_gui_app.py
 M tests/test_gui_device_page.py
 M tests/test_gui_profiles_page.py
 M tests/test_gui_tray_profiles.py
 M tests/test_source_limits.py
?? buildpython/steps/appimage/abi.py
?? buildpython/steps/appimage/elf.py
?? docs/distro-portability-plan-revised.md
?? docs/distro-portability-plan.md
?? scripts/distro_report.sh
?? src/naga_control/gui/profile_mode_view.py
?? src/naga_control/gui/tray_device_mode.py
?? tests/appimage_abi_fakes.py
?? tests/distro_report_fakes.py
?? tests/fixtures/os-release/
?? tests/test_appimage_abi.py
?? tests/test_appimage_abi_inventory.py
?? tests/test_appimage_elf.py
?? tests/test_distro_report_parsing.py
?? tests/test_distro_report_plans.py
?? tests/test_distro_report_sandbox.py
?? tests/test_gui_profile_mode.py
?? tests/test_gui_tray_mode.py
?? tests/test_source_limit_discovery.py
?? tests/test_uninstaller_cleanup.py
?? tests/test_uninstaller_failures.py
?? tests/uninstaller_fakes.py
```

- Later docs-check status additionally showed external modified
  `scripts/install_user.sh` and new `tests/installer_ldconfig_fakes.py`,
  `tests/test_installer_ldconfig.py`, and `tests/test_uninstaller_lock.py`.
  These concurrent additions are also preserved without attribution; reread
  status before resuming. The tracker itself is now modified by this docs wave.
- Next bounded authorized wave ONLY after the external uninstaller owner fixes
  the lint/type errors: reread current state and ownership, rerun the focused
  DEBT-07 suite and full standard checks, then the exact extended 17-step
  campaign command and required package gates. Accept DEBT-07 only on passing
  required gates, with Docker's existing blocker separately explicit; then
  proceed to DEBT-08 docs dispositions and DEBT-10 read-only scout. Do not
  solicit new authorization to fix external files or silently fix them here.
- Docs-only validation: ASCII, local Markdown link targets, header/queue status,
  shared-tree status, and `git diff --check` only; no Python workload reruns.
  This checkpoint is a handoff, not campaign completion or release acceptance.

### DEBT-07/08/10 Parallel Prep Checkpoint (docs-only, 2026-10-08)

- Status: DEBT-06 COMPLETE (unchanged); DEBT-07 IN PROGRESS, campaign
  acceptance BLOCKED; DEBT-08/10 QUEUED (unchanged); DEBT-09 BLOCKED on
  Docker (unchanged, not rechecked). No completion claimed; no new
  measurement row (no fresh full/extended run started, so no new
  coverage/ratchet numbers).
- Scope: this fresh docs-only executor changed ONLY
  `docs/debt-paydown-campaign.md` via manual edit. No code changes by us
  this turn. Campaign-owned `tests/test_source_limits.py` and
  `tests/test_source_limit_discovery.py` remain uncommitted/unstaged and
  untouched here. HEAD `154b308` confirmed; all other changed/untracked
  paths in `git status --short` are concurrent external
  GUI/device-mode/portability/uninstaller/installer work, preserved
  without attribution, edits, or ownership claims. No commits, stages,
  branches, root/model pins, credentials, hardware, live GUI/service
  operations, package installs, or network in this wave.
- Supervisor-run evidence (advisory, not executor runs): first fresh Ruff
  still `F401` at externally owned `tests/uninstaller_fakes.py:4`; during
  two parallel read-only scouts the external owner removed `os`, then
  supervisor `.venv/bin/pyright` EXIT 0 with 0 errors, 0 warnings,
  0 informations. Supervisor `.venv/bin/python -m buildpython` EXIT 2 with
  `Build not started: another buildpython run owns
  /home/cyril/Projects/Naga-controlpanel/buildlog/naga-control.`; it did
  NOT start, so NO new run ID, no lock overwrite/tamper, no poll/remove,
  and externally owned existing reports were not read/reinterpreted for a
  new campaign snapshot. Supervisor then `.venv/bin/ruff check .` EXIT 0
  (`All checks passed!`), `.venv/bin/ruff format --check .` EXIT 0 (394
  files already formatted), and `QT_QPA_PLATFORM=offscreen
  .venv/bin/pytest -q tests/test_source_limits.py
  tests/test_source_limit_discovery.py tests/test_gui_log_failure.py
  tests/test_gui_worker.py tests/test_gui_app.py
  tests/test_gui_mapping_map.py tests/test_gui_update_shutdown.py
  tests/test_gui_version_panel.py` EXIT 0 with 477 passed, 8 warnings,
  2.21s. The 477 count reflects concurrent new-file physical guards, NOT
  17 new campaign behaviors. Full standard, extended 17-step, and package
  gates were NOT executed this turn.
- DEBT-07 note: types committed in `643d791`, pending acceptance. Shared
  build-report ownership prevents full verification; no ownership or
  acceptance claim is made here; the historical external uninstaller
  lint/type failure records are retained unchanged until the external
  owner finishes.
- DEBT-08 read-only prep (NOT complete, no dispositions applied): 8
  HISTORICAL Vulture candidates verified in source. Five duplicate
  second-raises are retain-or-optional-remove redundancy only
  (`tests/gui_buttons_fakes.py:36`, `tests/gui_support.py:37`,
  `tests/test_gui_app.py:47`, `tests/test_gui_dpi_page.py:44`,
  `tests/test_gui_presenter.py:108`). Three async-generator sentinels MUST
  be retained because deletion changes the coroutine interface:
  `tests/test_capture_cli_behavior.py:69` fail-fast unreachable yield,
  `tests/test_evdev_source_adapter.py:89`
  `if False` yield, `tests/test_first_slice_session.py:181`
  `if False` yield. No barrel imports, facades, flat-directory churn, or
  scanner waivers. Import/flat-scan counts need a fresh valid run; do NOT
  freeze the historical 25-warning/5-critical/8-directory snapshot. The
  externally modified `tests/test_gui_app.py` sentinel is unchanged and
  remains externally owned.
- DEBT-10 read-only prep (NOT complete, no budgets adopted): per-file
  floors EXIST as `coverage_step.models.CoverageBaseline.per_file_minimums`
  with `payload.py build_coverage_report` supporting
  `per_file`/`per_file_missing`; reviewed budgets remain unset and none
  adopted. Future work
  needs synthetic pass-at-floor, fail-below, and missing-file tests plus a
  `coverage_runner` exit-1 test preserving legitimate cleanup; note
  `tests/test_buildpython_analysis.py` currently asserts the baseline is
  EMPTY and must change when reviewed budgets are adopted. Do NOT invent
  floors from historical 94.31 or from any incomplete current capture.
  Prefer 6-8 stabilized boundary-file floors after a fresh measurement
  over total-only or freezing all raw broad counts; profile wiring for
  explicit extended invocation versus default no-floor behavior without
  coverage must be proved as intended. No baseline config, product, or
  test changes were authorized or made in this docs wave.
- Handoff: shared-report ownership is UNSAFE to use until the other build
  owner is done; no polling or auto-bypass. Next bounded wave (fresh
  context, not a resume): reread ownership/tree, then run default and
  extended 17-step campaign invocations only once exclusive ownership is
  available, plus package checks if required with the Docker blocker kept
  distinct. Accept 07 only on passing required gates, then take 08
  dispositions in docs and 10 tests/budgets as a small reviewed wave.
- Docs-worker checks: ASCII, local link targets, header/queue consistency,
  and `git diff --check` only (EXIT 0); no product workloads run here.

## Exit Criteria

- The confirmed silent lifecycle-rescan gap is resolved and regression-tested.
- Reviewed exception findings have dispositions; no confirmed runtime diagnostic
  gap is closed solely through suppression or scanner changes.
- Priority failure/recovery contracts have fake-based coverage and documented
  remaining physical-only gaps; any unmet provisional targets are explicitly deferred.
- Changed files have sustainable headroom, with no violation of the 400-line limit
  or loss of input safety, hardware ownership, or architecture boundaries.
- Any adopted ratchet is justified and tested; raw metric decreases are explained.
- Standard gates pass. Docker/ShellCheck gaps are verified or remain explicitly
  blocked/deferred; unresolved hardware checks are not represented as complete.
- This document contains final measurements, delivery commits, and the next queue.
