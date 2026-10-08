# Distro Portability Execution Tracker

Status (2026-10-08, HEAD `3b5d6c8` + 5 dirty paths): **source CI green, validation FAILED at AppImage assembly (cause UNKNOWN), step-14 diagnostic wrapper done and tested, ready to commit/push main and rerun quality + validation Release; v0.5.0 untagged/unpublished**.
The user approved [Distro Portability Plan (Revised)](distro-portability-plan-revised.md)
with "then follow the revised plan. please continue". That read-only plan controls
the sequence and scope; it supersedes this file's former execution waves.
This is its compact evidence/register tracker, not another plan or support promise.
`b6d6c71` holds the reviewed full tree with portable builder and finished
static gate plus release 0.5.0 metadata; `31ccc23` adds a diagnostic wrapper that
exposes the pytest log while retaining exit status; `3b5d6c8` adds Python
3.12-safe test annotations and deterministic Qt teardown (test-only, no product
change). All tree was included in the release approval, pushed direct to main,
and the review branch was deleted. Source CI `37834706341` is SUCCESS on this
SHA and remains valid. Validation-only Release `37834701338` is FAILURE:
metadata SUCCESS; pinned OpenRazer build/compiler/metadata/import/hash gates
SUCCESS; source full profile SUCCESS; pinned CPython 3.12.15 Ubuntu 22.04 image
build plus stdlib probe plus Qt 6.12 dependency install SUCCESS; then
buildpython AppImage assembly FAILED (21.8s, exit 1, 19:59:21 UTC).
`/workspace/buildlog/naga-control/step-14-appimage.log` was not printed and the
runner is gone, so the actual assembly error/log is UNKNOWN. Static
finished-artifact gate, 22.04 smoke, 24.04 smoke, staging, and upload were
never reached; no real ABI, smoke, or distro pass is claimed. Parent failed
log: `/tmp/opencode/naga-portability/ci-fix-release.failed.log` (~8334 lines).
v0.5.0 is untagged/unpublished; latest published remains v0.4.0 (see GitHub
releases for current publication status). Guidance, portable builder, artifact
gate, and workflow wiring below are historical FAKE-ACCEPTED local receipts; the
implemented portable-build/static gate is distinct from the still-pending real
portable artifact and representative distro install/launch evidence. Diagnostic
work is DONE: `portable-inner.sh` wrapper prints `step-14-appimage.log` on
failure while preserving the original status, with no fallthrough to gate or
smoke (Bash/ShellCheck PASS). Tested: focused 166 portable/release contracts
PASS in both venvs (3.20s, 3.62s); global Ruff PASS, format 419, Pyright 0;
full parent venv pytest 3439 passed, 2 skipped, 224.40s EXIT 0 with pre/post
hashes identical (cmp PASS). Current 5 dirty paths ready to commit/push main,
then rerun quality + validation Release: `buildpython/steps/appimage/portable-inner.sh`,
`changelog.md`, `docs/release-notes.md`, `docs/distro-portability-plan.md`,
`tests/test_appimage_portable_failure_logs.py` (5 tests). Tag only when green.

## Verified baseline and limits

- **APPROVED build target:** Ubuntu 22.04/glibc 2.35, x86_64, with a separately
  controlled pinned CPython 3.12 toolchain. Ubuntu 24.04/glibc 2.39 was not selected
  as the floor. Approval is not a portable build or distro compatibility pass.
- Historical scoped local `build/appimage/AppDir` snapshot: CPython 3.14
  `math`/`cmath` required `GLIBC_2.44` per readelf. This is not fresh current
  staging evidence or an audit of every object/any published artifact's ABI floor.
- Supervisor independently approved bounded ABI/report fake checks: **296 passed in 1.84s**
  (124 ABI, 172 report); ten Python files passed Ruff/format/Pyright, and the reporter
  passed Bash syntax/ShellCheck. Checkpoints below postdate that foundation.
- Historical snapshot after the hexadecimal version-index parser fix: one Qt6Core ELF metadata
  parse reported maximum required `GLIBC_2.34`. This is **one-object static parsing**,
  not ABI/provider closure, a finished-artifact audit, or launch acceptance.
- Supervisor's `.venv/bin/python -B -m buildpython.steps.appimage.abi build/appimage/AppDir`
  returned **exit 1**, fail-closed: AppDir is now absent (staging has only venv/wheel).
  **Zero objects inspected**; no artifact decoded/executed/imported. Full ABI unknown.
- A read-only GNU readelf scout of a local 0.4.0 outer runtime found ELF64 LE
  x86_64 DYN, static, no DT_NEEDED/GLIBC needs. Inner SquashFS/payload uninspected;
  this establishes neither a complete artifact ABI floor/identity nor launch acceptance.
- Local `.venv` is still host Python 3.14.7. Docker, Podman, and unsquashfs were
  confirmed unavailable on 2026-10-08; readelf, objdump, and ShellCheck are available.
  No Ubuntu 22.04 portable build, container, desktop, new hardware pass, ABI real
  output, Ubuntu build, or representative distro installed/launched evidence exists.
- Managed installs still require x86_64/glibc, FUSE2, user systemd, session D-Bus,
  existing tools and scoped permissions. Extraction remains manual launch-only;
  no automatic missing-package setup or managed FUSEless fallback is delivered.
- Checksums before execution, safe paths/permissions, private staging, atomic
  replacement, consent-based stops, verified image/tag backups and activation
  policy stay intact. HTTPS hashes are corruption checks, not independent signatures.
  Published v0.4.0 installers do not retroactively gain checkout safety changes.

Required context: [AGENTS.md](../AGENTS.md), [starter](naga-linux-control-agent-starter.md), [integration findings](integration-findings.md),
[architecture](architecture.md), [implementation plan](implementation-plan.md), [hardware validation](hardware-validation.md),
[README install](../README.md#install), and [release notes](release-notes.md).
Load `naga-guided`; no extra skill is required for this documentation update.

## Standard checkpoints (never sum scoped runs; historical receipts labelled)

Historical parent exit-0 checkpoint before the guidance wave (source-hash-stable snapshot):
- `.venv/bin/ruff check .`: `All checks passed!`
- `.venv/bin/ruff format --check .`: `394 files already formatted`
- `.venv/bin/pyright`: 0 errors, 0 warnings, 0 infos.
- `.venv/bin/pytest`: **3263 passed**, 2 skipped (missing coverage), 5 hardware deselected, 8 dependency warnings, 213.03s; actual full-suite count, not a scoped sum.
- `bash -n scripts/install_user.sh`; `bash -n scripts/uninstall.sh`; `bash -n scripts/distro_report.sh`: separate invocations, exit 0 silent.
- `shellcheck scripts/install_user.sh scripts/uninstall.sh scripts/distro_report.sh`: exit 0 silent.
Post-guidance supervisor checkpoint: Ruff pass, format 395, Pyright 0, default pytest **3269 passed**,
2 coverage skips, 5 hardware deselected, 8 dependency warnings, 207.92s; source/README/troubleshooting
stable. It predates the NEW portable builder/gate and current GUI final tweaks.
Stable full-source parent snapshot before wrappers (supervisor rerun, exit 0, historical):
Ruff pass, format 415, Pyright 0/0/0, offscreen pytest **3411 passed**, 2 coverage
skips, 5 hardware deselected, 8 warnings, 248.81s; tracked/untracked hashes identical
before/after, no code writers active. A prior 2-minute tool timeout gave no result
(not a failure); the rerun completed exit 0.
Historical supervisor scoped runs today (not full acceptance, never summed): `bash -n` on
install_user/uninstall/distro_report plus ShellCheck: exit 0 silent.
- Installer scope `.venv/bin/pytest -q` (ldconfig, prerequisite guidance, cleanup,
  failures, lock): **136 passed, 47.26s**.
- `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q` GUI scope under `tests/` (profile mode/controls,
  tray mode/controls, mode guards, app, device/profiles pages, draft reconciliation, switch
  revisions, tray profiles/scroll/reconcile, source-limit discovery): **240 passed, 8 warnings, 12.26s**.
- Focused wrapper checks after `31ccc23`: 70 passed, 2 skipped, 4.22s, plus global
  Ruff/format/Pyright passed.

## CI root-fix checkpoint (pushed to main; source CI green, validation build failed at AppImage assembly)

- Source fix is test-only across 7 reviewed paths: modified
  `tests/gui_version_panel_fakes.py`, `tests/test_gui_update_shutdown.py`,
  `tests/test_gui_version_panel.py`, `tests/test_service_cli_main.py`; new
  `tests/conftest.py`, `tests/gui_qt_lifetime.py`,
  `tests/test_gui_qt_lifetime.py`. No product/dependency/workflow changes.
  Those 8 paths are committed at `3b5d6c8` (historical); the current dirty set
  is 5 paths (see header).
- Root cause addressed: Qt 6.12 native proof showed test widgets
  garbage-collected/deleted inside a signal and a shared QObject destroyed at
  app shutdown. Tests now use test-scoped main-thread close/deleteLater,
  per-widget DeferredDelete deletion verification, and final session cleanup;
  preexisting module widgets preserved; unexpected cleanup failures propagate
  (no catch-all). New regression: 20 tests. `test_service_cli_main.py` uses
  future annotations to avoid `CoroutineType` runtime subscript on 3.12; no
  assertion or runtime-behavior relaxation.
- Parent independent verification: focused 481 GUI+CLI tests exit 0 on
  3.12/6.12 in 21.71s and on 3.14/6.12 in 19.94s; Ruff clean, format 418,
  Pyright 0/0/0.
- Full suites both exit 0: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q` ->
  3433 passed, 2 skipped, 5 hardware deselected, 8 warnings, 235.39s;
  matched-3.12 command with the coverage-safety plugin -> 3433 passed,
  2 skipped, 238.34s. The 3433 count is the unique full-suite total, not a
  sum. Receipts: `ci-fix-standard-pytest.log`,
  `ci-fix-matched312-pytest.log`. Tracked/untracked hashes identical pre/post
  full run (cmp pass); no code writers. No shared-QObject warning or native
  crash post-fix.
- Environment note: private 3.12 loader RUNPATH relinked under `/tmp` only so
  hermetic test children run without `LD_*`; parent uid 1000. Earlier 73
  failures traced to worker root/env loader, not a repo fix.
- CI status: source CI `37834706341` SUCCESS on `3b5d6c8`; validation-only
  Release `37834701338` FAILURE at buildpython AppImage assembly (21.8s, exit
  1, 19:59:21 UTC) after pinned image build, stdlib probe, and Qt 6.12 install
  passed. `step-14-appimage.log` was not printed and the runner is gone, so the
  assembly error is UNKNOWN. Earlier branch 12-error runs have unknown exact
  logs (no retroactive cause claim); main segfault runs are now historical
  evidence. Parent next: push these notes plus a step-14 diagnostic wrapper,
  then a bounded pipeline fix; tag only when green.
- Portable controlled build/static gate and 22.04/24.04 smoke: assembly FAILED
  before the static finished-artifact gate; 22.04/24.04 smoke, staging, and
  upload never reached. No ABI, smoke, hardware, or new distro evidence is
  claimed in this checkpoint.

## Dispatched CI failures (historical evidence; source fix now green, assembly blocker current)

- First review-branch runs failed source pytest with **3399 passed, 2 skipped,
  12 errors**; logs unavailable: quality `37826632305`, validation Release `37826632804`.
- Latest main runs both failed native segmentation fault (exit-11/shell 245) during
  `tests/test_gui_version_panel.py:89` update check:
  quality `37827963916` https://github.com/Rainexn0b/naga-control/actions/runs/37827963916
  and validation Release `37827964078` https://github.com/Rainexn0b/naga-control/actions/runs/37827964078
- Diagnostic logs: `/tmp/opencode/naga-portability/main-quality.failed.log` and
  `/tmp/opencode/naga-portability/main-validation.failed.log`; installs selected
  Python 3.12.15 and PySide6 6.12.0.
- Local existing venv is Python 3.14.7 with PySide6 6.11.2; isolated
  `/tmp/opencode/naga-ci-repro` (Python 3.14.7 with PySide6 6.12.0) ran
  `tests/test_gui_version_panel.py`: **17 passed, 7 warnings, 0.13s (exit 0)**,
  but this alone is not crash root cause. The full isolated 3.14/6.12 suite printed
  **3413 passed, 2 skipped, 7 warnings, 207.85s**, then crashed during shutdown
  (shell 139), warning that a shared QObject was deleted directly. Its pass summary
  is not a successful process exit; log: `/tmp/opencode/naga-portability/ci-repro-full.log`.
- Fresh local 3.12 repro: parent built official checksum-verified CPython 3.12.15 in
  `/tmp/opencode/naga-python312`; isolated `/tmp/opencode/naga-ci-repro312`
  (3.12.15/PySide6 6.12.0, pytest 9.1.1, asyncio 1.4.0) ran the exact safe CI command
  with `LD_LIBRARY_PATH` prefix and `QT_QPA_PLATFORM=offscreen` and reproduced the same
  native crash at `tests/test_gui_version_panel.py:89` (shell 139); log
  `/tmp/opencode/naga-portability/ci-repro312-full.log`. That local receipt showed
  additional earlier Fs unlike latest CI; do not infer root cause.
- Root-cause work is complete and verified locally per the checkpoint above; the
  earlier worker-active statement is superseded. This tracker makes no
  code/test/workflow change.
- Both Release runs passed metadata plus pinned OpenRazer package build validation;
  the AppImage build never reached controlled Ubuntu 22.04/static artifact/userspace
  smoke; publish skipped on validation dispatch.
- Existing Docker/Podman/unsquashfs remain unavailable locally; the user wants
  existing-pipeline concrete failures, not manual package lookups.
- No hardware evidence newly accepted in this checkpoint.

## Independent fake acceptance (supervisor, 2026-10-08; historical)

Historical scoped receipts below are fake-only local passes, not CI acceptance.

The parent reviewed bounded fixes and reran these passing commands:
- PATH fix: `bash -n scripts/install_user.sh`; `shellcheck scripts/install_user.sh`;
  `.venv/bin/pytest -q tests/test_installer_ldconfig.py tests/test_installer_preflight.py tests/test_installer_checksum.py tests/test_installer_layout.py` -> **179 passed in 43.89s**.
  New [fixture helper](../tests/installer_ldconfig_fakes.py) and [PATH tests](../tests/test_installer_ldconfig.py) passed Ruff/format/Pyright.
- Uninstall: `bash -n scripts/uninstall.sh`; `shellcheck scripts/uninstall.sh`;
  `.venv/bin/pytest -q tests/test_uninstaller_cleanup.py tests/test_uninstaller_failures.py tests/test_uninstaller_lock.py tests/test_installer_upgrade.py tests/test_installer_lock.py` -> **109 passed in 50.46s**.
  New [helper](../tests/uninstaller_fakes.py), [cleanup](../tests/test_uninstaller_cleanup.py), [failure](../tests/test_uninstaller_failures.py) and [lock](../tests/test_uninstaller_lock.py) passed Ruff/format/Pyright.
- Prerequisite guidance: focused **183 passed**, independently accepted earlier.
Do not sum these runs with the 296 foundation checks into a unique/full-suite total.
No live service cleanup/device/remap tests; real not-found-unit behavior remains
operator-validation pending. These fixes are not real-distro install/launch passes.
- Controlled portable builder (`Dockerfile.portable`/`portable-build.sh`): worker 71 fakes
  (2 coverage skips) plus parent portable/workflow scope **94 passed**, 2 skips, 3.95s;
  bash-n/ShellCheck on both scripts pass. FAKE-ACCEPTED locally; NOT a real build.
- Finished-artifact gate: corrections applied; focused **168 passed in 0.27s**, Ruff/format
  (16 files)/Pyright 0. The mid-refactor NameError is obsolete: line 279 calls `staging_base`.
  Fake-only; executable bits 0755 (`--help` both pass, no content change). Historical local
  receipt only; CI dispatch and failure are recorded above.

## A1-A10 assumption register (historical chain/build conclusions)

Chain/build references were verified at HEAD `154b308` and carried through the reviewed
`b6d6c71` full tree and `31ccc23` wrapper; uninstall/PATH/guidance conclusions
include those reviewed fixes. Acceptance is fake-only.

| ID | Evidence and conclusion | Execution status / smallest consequence |
| --- | --- | --- |
| A1 | [README command](../README.md#install); [install.sh](../install.sh):59-104 dispatches to local or ref-matched [install_user.sh](../scripts/install_user.sh). Its verified image stages seven user integration assets via [integration_cli.py](../src/naga_control/integration_cli.py):28-71, then atomically replaces files; upgrade uses the same path. [uninstall.sh](../uninstall.sh) dispatches to [scripts/uninstall.sh](../scripts/uninstall.sh). | CONFIRMED canonical chain; extend it, no second installer. |
| A2 | `install_user.sh`:90-122 uses generic capability checks. Stripped-PATH fixture reproduced exit 1/no mutations despite available ldconfig; the reviewed fix prefers a PATH executable, then `/usr/sbin/ldconfig`, then `/sbin/ldconfig`. | FAKE-reproduced/fix independently accepted (179 scoped tests); only C-locale `-p`, failed queries reject even valid partial stdout. No real-distro install pass. |
| A3 | [build.py](../buildpython/steps/appimage/build.py)/[runtime.py](../buildpython/steps/appimage/runtime.py) bundle CPython >=3.12; no host Python needed. Baseline no-image/no-Python fake exited 0 claiming completion while 7/7 user assets remained. Uninstall now removes the known Bash manifest without invoking image/wrapper/Python. | Independence/cleanup/lock/stop fixes independently FAKE-ACCEPTED (109 scoped tests); default profiles, unknown backups and OpenRazer retained. Real service cleanup untested. |
| A4 | New [distro_report.sh](../scripts/distro_report.sh) parses `ID`, `ID_LIKE`, `VERSION_ID` as Bash data; own release strings and UNKNOWN/CONDITIONAL statuses remain explicit. Its reviewed rows remain only Ubuntu 22.04/24.04 and Arch, not the newer Fedora reference below. | 172 fake checks approved; no installer integration or runtime proof. `ID_LIKE` is a hint, never package/version/validation inheritance. |
| A5 | Prerequisite guidance landed with capability-first errors and exact per-release manual references. No broad native-package provisioning need is confirmed; representative versions/snapshots beyond the build floor remain TBD. | FAKE-ACCEPTED (183 focused tests); add only a demonstrated small branch, never guessed packages or a provider framework. |
| A6 | App-only install never fetches the optional helper; [release prerequisites](release-notes.md#required-openrazer) restrict explicit opt-in to experimental Arch/pacman and the exact matching cohort. | CONFIRMED; preserve consent, deferred activation and rollback. No wider helper cohort. |
| A7 | `runtime.py`:104-146 copies complete selected-host stdlib/extensions. Historical math/cmath needed 2.44; current AppDir is absent, audit inspected zero objects. New [elf.py](../buildpython/steps/appimage/elf.py)/[abi.py](../buildpython/steps/appimage/abi.py) inspect staged AppDir only; outer-runtime scout leaves payload uninspected. | PARTIAL static foundation (124 fake checks); pinned 22.04/CPython 3.12 rebuild and finished-artifact ABI/provider validation PENDING/unknown. Fix build inputs, not the launcher. |
| A8 | Manual extraction changes root-folder/stable launcher, service, update and backup layout; HEAD `install_user.sh`:343-354 backs up image/tag pairs, not extracted trees. | INVESTIGATED contract risk; small reversible managed fallback unproven. DEFER implementation; keep FUSE required, no safety weakening. |
| A9 | [Existing release workflow](../.github/workflows/release.yml) validates source on ubuntu-latest, then runs a controlled Ubuntu 22.04 CPython 3.12 build/static gate/baseline check plus 24.04 userspace smoke; OpenRazer builds in an Arch container. [smoke.py](../buildpython/steps/appimage/smoke.py) defaults to 24.04/apt/extracted userspace; local Docker/Podman/unsquashfs absent. | Dispatched CI failed at ubuntu-latest source validation (segfault below); controlled 22.04 build/static gate/baseline check and 24.04 smoke were unreached. Local execution remains BLOCKED. No full install/desktop or 22.04/Fedora matrix pass. |
| A10 | [Prior hardware results](hardware-validation.md#existing-baseline-evidence) and CachyOS first-slice passes are separate from [current fix2 evidence](integration-findings.md#openrazer-baseline). Exact-pin natural wake acceptance remains open. | CONFIRMED separation: install/launch is not hardware support. Operator-only existing checks; no extra device/firmware campaign. |

Reporter package references (supervisor official-web inspection, 2026-10-08):
- Ubuntu 22.04: [libfuse2](https://packages.ubuntu.com/jammy/libfuse2), universe.
- Ubuntu 24.04: [libfuse2t64](https://packages.ubuntu.com/noble/libfuse2t64), universe.
- Arch: [fuse2](https://archlinux.org/packages/extra/x86_64/fuse2/), extra.
Separate new reference (same review date): [Fedora 44 fuse-libs](https://packages.fedoraproject.org/pkgs/fuse/fuse-libs/fedora-44.html)
2.9.9-25.fc44 x86_64 provides `libfuse.so.2()(64bit)` at `usr/lib64/libfuse.so.2`.
Package reference ONLY, not Fedora install/AppImage launch/runtime evidence; reporter unchanged.
Debian trixie official fetch met a bot challenge; openSUSE package lookup returned
HTTP 403. Neither yielded an accepted package fact; no derivative inheritance.
Candidate build inputs (CPython 3.12.15 source, Ubuntu 22.04 image metadata)
reverified 2026-10-08; immutable candidates are not accepted builds, sources, or runs.

## Compatibility-gap ledger

SOURCE means inspected risk; FAKE-ACCEPTED records parent-reviewed fake results, not real-distro
behavior. Historical facts are scoped, not a fresh AppDir audit or finished-artifact ABI acceptance.

| Environment | Existing failure / source evidence | Smallest fix | Verification state |
| --- | --- | --- | --- |
| Missing/uncallable installed image; no host Python/module | Baseline fake exited 0/claimed uninstall complete while 7/7 user integration assets remained. | Direct known-manifest Bash cleanup, independent of image/wrapper/Python; retain default profiles, unknown backups and OpenRazer. | FAKE-reproduced/fix independently accepted in 109 scoped tests; no live cleanup/device/remap pass. |
| Uninstall during install, or failed unit stop | Baseline source lacked install lock/suppressed stop failure; fake overlap and unsafe/failure cases now covered. | Same stable nonblocking install-lock inode, private owner/non-symlink paths; stop/disable/unknown unsafe state failures retain files/profiles/backups before cleanup. | FAKE-ACCEPTED in same 109-test run; partial filesystem/reload failures nonzero, no false completion. Real not-found-unit behavior pending. |
| Desktop PATH omits sbin | Parent's stripped-PATH baseline fixture failed exit 1 without mutations despite available ldconfig. | Prefer PATH executable, then `/usr/sbin/ldconfig`, then `/sbin/ldconfig`; C-locale `-p` only, query failure rejects valid partial stdout. | FAKE-reproduced/fix independently accepted in 179 scoped tests; NOT a real-distro install pass. |
| Host-built image on old glibc target; current staging absent | Historical math/cmath needed `GLIBC_2.44`; floor 2.35. Current AppDir audit exit 1/zero objects; local 0.4.0 outer runtime scout leaves payload uninspected. | Rebuild with pinned 22.04/CPython 3.12 inputs; minimal finished-artifact static gate in existing workflow. | Partial audit fakes approved; full ABI/provider closure unknown, no finished-artifact or launch acceptance. |
| Missing FUSE2; extraction only manual | Installer requires FUSE; extracted tree lacks proven managed update/rollback/removal contract. | Verified version-appropriate package instructions; preserve FUSE requirement. | Guidance FAKE-ACCEPTED (183); no automatic fallback/setup implemented or runtime pass. |
| Local container/extraction-tool gap | Docker/Podman/unsquashfs unavailable; existing smoke recipe is apt/extracted userspace only. | Existing authorized runner/VM, not daemon installation or a new test platform. | Environment blocker confirmed; portable build/matrix acceptance absent. |

## Representative validation snapshot

| Family | Concrete target / snapshot | Install / launch / upgrade / remove evidence |
| --- | --- | --- | --- |
| Ubuntu | 22.04 approved build floor; newer smoke target TBD | NOT TESTED in this campaign; 24.04 package reference only |
| Debian | Current supported version TBD | NOT TESTED; package lookup pending |
| Fedora | 44 package-only candidate; actual runner target pending | NOT TESTED; package reference only, no launch/runtime guarantee |
| Arch | Current immutable rolling snapshot TBD | NOT TESTED for new artifact; prior CachyOS hardware evidence separate |
| openSUSE | Available Leap/Tumbleweed target TBD | NOT TESTED |
| Derivative | Realistic available target/version TBD | NOT TESTED; no `ID_LIKE` inheritance |

Record exact environments, commands/results and named blockers as checks happen; keep fake,
install-tested, launch-tested, blocked/conditional and hardware evidence separate. Containers
cover userspace only, not FUSE desktop, permissions, DKMS, session services, or OpenRazer recovery.

## Next bounded work in the controlling sequence

1. Historical: uninstall/PATH/guidance fake reviews and the dated checkpoints above are
   complete; none accepts portable builds, distro installs, or hardware.
2. Historical FAKE-ACCEPTED locally: portable 22.04/3.12 build plus finished-artifact ABI
   gate (static inspection only, no execution-based `ldd` audit) and existing workflow
   driver/static-gate wiring. That wiring was dispatched; real CI build/ABI/smoke
   did not complete because both runs segfaulted before the AppImage stage
   (now historical evidence; fix verified locally above).
3. Historical: the 8 reviewed paths were pushed direct to main as `3b5d6c8`
   under the existing user authorization, then quality plus validation-only
   Release were rerun (source green, assembly red). Concrete
   pipeline results take precedence over manual package lookups.
4. Then representative ordinary install -> CLI/launch -> upgrade -> remove paths
   with safe fakes and available authorized environments; fix proven gaps only.
5. Then README support claims only from actual evidence; hand off existing physical
   checks to an attentive operator. Known hardware gates (exact-pin wake,
   held-output handoff, wired alternate plates) remain open; no new device campaign
   and no hardware evidence newly accepted here.
6. Git/CI/release (historical branch step superseded): the review-branch push/dispatch
   already happened and the branch was deleted remote/local. Current requirement is
   direct-to-main commit/push of the current 5 paths (wrapper + 3 docs + new
   failure test), with quality and validation-only
   Release reruns. Only when green: record final evidence notes, tag/publish v0.5.0 with
   6 assets, verify checksums, run a safe isolated installer test or name the blocker.
   Latest published stays v0.4.0 until then.
   Release body comes from the root changelog extractor, not older skill body text;
   [release notes](release-notes.md) and [changelog](../changelog.md) match 0.5.0 metadata.

## Checks and unchanged boundaries

Use focused fakes then the exact standard commands above, hardware excluded; changed scripts
need Bash/ShellCheck. Guidance/builder/gate/workflow are historical FAKE-ACCEPTED local
receipts; real CI was dispatched and segfaulted (now historical evidence; fix above
awaits CI rerun); never sum scoped runs.
Doc-only checks for this edit: ASCII, local links/anchors, read-only `git diff --check` and
diff review. No Python suite is run for this docs change.
Keep all Python files <=400 physical lines and follow milestone/first-slice gates.
Target only `1532:00E7`/`1532:00E8`, one transport at a time; OpenRazer only, no
raw HID; never run GUI/service as root. Qt stays outside domain/service/hardware
adapters; GUI owner remains `src/naga_control/gui/`. Require physical USB ancestry
and forwarding readiness before grabs; retain key-down actions through key-up.
Unsafe states/write failures release grabs/generated held outputs. Keep filesystem,
GUI and blocking OpenRazer work off the evdev read/forwarding path.
This worker writes only this tracker; the revised plan and concurrent GUI, troubleshooting,
changelog and UI-tracker edits are untouched. This worker performs no Git mutations and runs
no builds/tests/services/devices; the parent owns commits/pushes/reruns under the user
authorization above. No version bump, tag, or publication is claimed or done here.
