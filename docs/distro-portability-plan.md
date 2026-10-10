# Distro Portability Execution Tracker

Status (2026-10-10 UTC, canonical `4f14ed3`): **source CI `38050625614` SUCCESS,
validation-only Release `38050625832` SUCCESS (controlled Ubuntu 22.04 build
plus finished-artifact static gate plus 22.04 baseline plus 24.04 smoke plus
one-image checksum staging plus upload; publisher skipped by dispatch design,
tag-only publication pending)**. Ready for final notes commit, tag-only
rebuild/publish, then six-asset verification plus safely isolated installer or
precise blocker; source feature code FROZEN, canonical includes all user work
with no exclusions. Runtime source hash is unchanged for this docs-only
commit.
The user approved [Distro Portability Plan (Revised)](distro-portability-plan-revised.md)
with "then follow the revised plan. please continue". That read-only plan controls
the sequence and scope; it supersedes this file's former execution waves.
This is its compact evidence/register tracker, not another plan or support promise.
By user decision ALL completed current codebase is canonical v0.5.0
(`4f14ed3` includes `1daa514` key/chord, `5d91ec9` README quickstart, `81dfa9b`
artwork, plus ratchet config/tests/debt docs, safe 24 smoke identity, and all
past approved runtime fixes) and further feature code is FROZEN until the
image is published. No new hardware acceptance is claimed. See
[GitHub releases](https://github.com/Rainexn0b/naga-control/releases) for
current publication status.

- CURRENT (canonical `4f14ed3`, validation-only `38050625832`
  https://github.com/Rainexn0b/naga-control/actions/runs/38050625832): source
  `38050625614` SUCCESS and validation `38050625832` SUCCESS. Metadata,
  OpenRazer build/metadata/cohort/imports/hashes, and full-profile source
  checks passed; controlled Ubuntu 22.04 / glibc 2.35 / x86_64 plus CPython
  3.12.15 build plus finished-artifact static gate passed (208 objects,
  providers_checked true, errors[]) 12:12:17-12:15:50Z, 22.04 baseline
  userspace passed (`runtime-imports-ok`, `qt-offscreen-ok`,
  `integration-payload-ok`, `portable artifact verified`), 24.04 smoke passed
  12:15:50-12:16:18Z (same imports, version 0.5 metadata, offscreen
  QApplication plus GUI app import only, CLI service/capture/integration
  `--help`, temporary integration assets; no live hardware, root GUI/service,
  or device access), one-image checksum staging passed 12:16:18Z, then upload
  passed. Publisher SKIPPED by dispatch design, so tag-only publication is
  pending. Finished artifact `Naga-Control-0.5.0-x86_64.AppImage` is 123202040
  bytes, squashFS offset 944632, sha256
  `57e4fa76520c5a75b08d98969d2ce4700f2d85ef51edb875f0adc53126febddf`; the
  validation receipt SHA is not the published identity (tagged rebuild may
  differ). Real reports: `canonical-artifact-gate.json` plus
  `canonical-appimage.raw.log`, `canonical-release.full.log`, and
  `canonical-release.jobs.json`. Smoke staging uses same-uid owned 0700 paths.
- Candidate asset receipt (run `38050625832`, independently downloaded): six
  candidate assets PASS both AppImage/packages checksum sidecars;
  `scripts/validate_release_assets.py` PASS for the complete pin cohort, and
  image bytes match the gate sha256
  `57e4fa76520c5a75b08d98969d2ce4700f2d85ef51edb875f0adc53126febddf`. This
  validation candidate is NOT a public release. Isolated environment probe only
  (`isolated-installer-environment.log`/`.status`, `env -i bwrap --unshare-all`
  with private etc/udev/home/run/tmp/proc/minimal dev) returned UID 1000;
  `systemctl --user show` failed with `Failed to connect to user scope bus via
  local transport: No such file or directory` (exit 1). Probe only checked the
  environment, not an installer attempt; no host services, udev, FUSE, or
  device nodes were touched. Missing private bus is the precise blocker; actual
  tag installer smoke runs parent post-pub, otherwise report blocker. No full
  pass or new hardware claim.
- Tag run (2026-10-10 UTC, `9789f54`, run `38054026464`): controlled build, static
  gate (208 objects, errors empty), 22.04 baseline, 24.04 userspace, staging, and
  upload PASS; publisher FAILED on draft tag lookup. Empty draft `408962506` for
  `v0.5.0` stays draft with no assets and no published binaries; tag endpoint 404s
  per API contract while ID lookup works. User-approved recovery is retag of ONLY
  the unpublished tag after the ID fix and green CI, then rerun all CI via the tag;
  feature payload stays frozen. See
  [GitHub releases](https://github.com/Rainexn0b/naga-control/releases) for status;
  v0.4 remains latest public.
- HISTORICAL before freeze (source `7e59003`, validation-only `38044500744`
  https://github.com/Rainexn0b/naga-control/actions/runs/38044500744): controlled
  Ubuntu 22.04 / glibc 2.35 / x86_64 plus CPython 3.12.15 build passed, finished-artifact
  static gate passed (208 native objects, providers_checked true, errors[]), and 22.04 baseline
  userspace checks passed (bundled runtime imports, offscreen QApplication, CLI help, temporary
  integration payload; `portable artifact verified` in the raw log). Ubuntu 24.04 smoke then FAILED
  after apt/pull success with `runuser: failed to execute /work/squashfs-root/AppRun: Permission denied`:
  root extraction under a private owned directory denies uid 10001. The delivered smoke-identity fix
  stages an owned 0700 private work directory and image, then the same uid extracts and runs all AppRun
  checks; it is not a root app run and does not recursively widen permissions. At that time the fix was UNRUN in CI.
  Staging and upload were unreached; publication skipped by dispatch design.
  Real reports: `desktop-artifact-gate.json` plus `desktop-appimage.raw.log` for the earlier `8bf093c`
  artifact, and the finished-artifact gate `smoke-diagnostic-artifact-gate.json` for `7e59003`. Earlier on source `8bf093c`: source `38043242149` SUCCESS and validation-only
  `38043242656` https://github.com/Rainexn0b/naga-control/actions/runs/38043242656 also observed the
  first real static pass plus 22.04 baseline pass, with 24.04 FAILED without
  recorded diagnostic output; the later `7e59003` rerun exposed the
  permission-denied cause. First passed artifact on `8bf093c` is 123202040 bytes, squashFS offset 944632, sha256
  `6a7d9b9743e261750add63ebd0f16fc97160c9bcf93ce25511cf9577e7a264e1`. Those
  pre-canonical passes do not certify the canonical payload.
- Local acceptance (current tree, not CI): supervisor full buildpython run with existing tools path
  passed all 11 steps in 306.7s; full pytest 3586 passed, 0 skipped, 8 warnings; Ruff 429 formatted,
  Pyright 0, LOC none over 400. Reports under `canonical-check-reports`
  (`canonical-standard-full.log`, `canonical-product-manifest.json`). Prior focused consumer 215 passed
  plus source-limits 409 passed also held. Canonical source CI plus real static, 22.04, and 24.04 validation
  are now GREEN on `4f14ed3` as recorded above.
- Historical (2026-10-10, `7661eb4` = `f48b3a4` plus approved 12-path checker/Qt-payload
  trim, committed/pushed): source CI `38040471530` SUCCESS on `7661eb4`;
  validation-only Release `38040471477`
  (https://github.com/Rainexn0b/naga-control/actions/runs/38040471477) assembled
  the trimmed AppImage in 31.2s (`Naga-Control-0.5.0-x86_64.AppImage`,
  123202040 bytes, sha256
  `7f1b636b76b54c487514e005b66b19ed30ecf926f8fcd4d64e2f66c91b29dc11`,
  squashFS offset 944632), then FAILED the static gate: 208 objects checked,
  providers_checked true, 70 errors. The 70 are missing normal desktop runtime
  prerequisites in the minimal 22.04 test image (Qt Wayland/XCB, xkb, GTK3
  theme, libcups) plus 2 trusted-baseline `libresolv.so.2` GLIBC_PRIVATE
  rejections with 2 cascading missing-resolv entries; this run reported no
  glibc/GLIBCXX floor violation, which does NOT mean ABI pass. Source
  full-profile, release metadata, and OpenRazer gates passed; 22.04 baseline
  and 24.04 smoke, staging, and upload were never reached, and publication was
  skipped by dispatch design. Actual report:
  `/tmp/opencode/naga-portability/trim-checker-artifact-gate.json`, jobs
  `trim-checker-release.jobs.json`, raw `trim-checker-appimage.raw.log`.
- Prior reviewed snapshot (`f48b3a4`, 16 tray/extraction/docs paths,
  committed/pushed): source CI `37847748963` SUCCESS; validation-only Release
  `37847748826`
  (https://github.com/Rainexn0b/naga-control/actions/runs/37847748826)
  assembled in 56.2s (269670904 bytes, offset 944632, sha256
  `ed394d235db6c970876d7b986efc9c63a43e71de0afdb6fbc7a54ebf70b6823a`),
  extraction SUCCESS with 589 native objects, providers_checked true, then
  FAILED with 2196 errors (singular GNU `contains 1 entry` parser case, private
  baseline libm, safe `$ORIGIN/` cases, plus genuine unused Qt
  QML/SQL/WebEngine/SDK payload). The child root-extraction bug is fixed.
  Source/meta/OpenRazer passed; 22/24 smokes, staging, upload UNREACHED.
  Actual records (not the truncated `gh` log view):
  `/tmp/opencode/naga-portability/reviewed-snapshot-artifact-gate.json`,
  `reviewed-snapshot-appimage.raw.log`. Local reviewed-tree acceptance at that
  point: 478 files, 3458 passed / 2 skipped / 5 hardware deselected, 8 warnings,
  223.30s; Ruff 420 formatted, Pyright 0.
- Trim basis (owner-approved "Trim unused payloads (Recommended)", 12 paths at
  `7661eb4`): retain Core/Gui/Widgets/Network plus XCB/Wayland/offscreen/image
  platforms, TLS/ICU, NumPy runtime, metadata/licenses; remove unused
  QML/SQL/WebEngine/tools/known-NumPy-static-SDK files in AppDir staging ONLY
  (no fake skipping, no gate weakening; sources/venv unchanged; `libqeglfs`
  embedded-only removal within unused scope; symlink/root-wildcard confinement
  fake-covered; singular-GNU 1-entry fix, libm trusted-PRIVATE-only, trailing
  `$ORIGIN` separators safe under existing traversal rules). Release-only
  archive `/tmp/opencode/naga-portability/release-acceptance.1QKC8n`
  (`f48b3a4` plus 12 ONLY, future work excluded): Ruff check PASS, format 423,
  Pyright 0, pytest 3496 passed / 2 coverage-unavailable skips / 5 hardware
  deselected / 8 warnings, 226.75s, exit 0; 481-file manifest unchanged
  pre/post, all Python <=400 lines; focused static/runtime/portable 16 files
  290 passed in 3.90s (never summed with 3496). Logs
  `trim-checker-standard-{ruff,format,pyright,pytest}.log` and
  `trim-checker-accepted-manifest.json`.
- Historical: validation-only `37840267274` on `84d77df` FAILED at extraction
  staging before payload inspection (pre-created destination); prior
  `37834701338` stays UNKNOWN (unprinted log, cause not inferred).
- HISTORICAL next note before canonical validation (kept labelled history): the desktop-prerequisite plus smoke-identity fixes above were delivered but at that time the
  smoke-identity rerun was still UNRUN. Historical bounded-fix note (kept, labelled history): the fix
  adds normal Qt Wayland/XCB, GTK, CUPS runtime prerequisites to the existing
  22/24 CI validation images ONLY (no host installers, bundling, provisioner,
  target, format, or pin change), plus a trusted EXACT `libresolv`
  PRIVATE-baseline allowance (payload still rejects). Parent independently
  passed the release-only archive (`7661eb4` plus exact 6 runtime/test paths
  plus 2 docs, 8 paths): 482 files hash-unchanged before/after, all Python
  <=400 lines; Ruff check PASS, format 424, Pyright 0, full pytest 3510 passed
  / 2 coverage-unavailable skips / 5 hardware deselected / 8 warnings,
  219.69s, exit 0; focused 266 passed in 1.86s (original 164 plus release
  consumers, not summed with 3510). Logs
  `desktop-standard-{ruff,format,pyright,pytest}.log`, manifest
  `desktop-accepted-manifest.json`. HISTORICAL at that time: local main was `81dfa9b`, remote main was `7e59003`, still no
  tag. Last completed CI before canonical validation was source `38044500620` SUCCESS and validation
  `38044500744` FAILED at the 24.04 smoke step after the real static plus 22.04 baseline passes;
  the new canonical payload awaited its own validation then. CURRENT canonical
  `4f14ed3` validation `38050625832` is now GREEN as recorded above; tag-only
  publication pending, status unknown pending real tag watch.
  Next: parent handles these final notes commit, push, CI, and publication; this receipt
  is updated to the GREEN validation run. Tag-only publication still pending; do not treat
  the validation receipt SHA as published. Local Docker/Podman/unsquashfs still missing; read-only
  `bwrap --unshare-all /usr/bin/true` presence probe exit 0
  (`installer-smoke-isolation-probe.log`/`.status`) is NOT private
  systemd-user/session-D-Bus/FUSE/sudo/udev installer validation. Throwaway
  HOME alone is unsafe; post-publish installer validation needs isolated
  HOME/user units/sudo/udev or a precise blocker, not system changes. No new
  hardware acceptance; fix2 natural wake, held handoff, remaining modes, wired
  2/6 signatures open; tray switch disabled. Then record final evidence notes
  and tag/publish v0.5.0 only when green.

## Verified baseline and limits

- **APPROVED build target:** Ubuntu 22.04/glibc 2.35, x86_64, with a separately
  controlled pinned CPython 3.12.15 toolchain and unpinned PySide6 `>=6.8,<7`. Ubuntu 24.04/glibc 2.39 was not selected
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
- CURRENT canonical artifact evidence (2026-10-10, `4f14ed3`): real finished-artifact
  inspection RAN and PASSED the static gate (208 bundled objects, providers_checked true,
  errors[]), followed by the 22.04 baseline userspace pass (bundled runtime imports,
  offscreen QApplication, CLI help, temporary integration payload) and the 24.04
  userspace smoke pass, then one-image checksum staging and upload. Publisher
  skipped by dispatch design; tag-only publication pending. Scope is userspace
  launch only; no ABI, install, desktop, or hardware certification is claimed.
- HISTORICAL pre-canonical artifact evidence (2026-10-10, `7e59003`/`8bf093c`): real finished-artifact
  inspection RAN and PASSED the static gate on both runs (208 bundled objects, providers_checked true,
  errors[]), followed by the 22.04 baseline userspace pass (bundled runtime imports,
  offscreen QApplication, CLI help, temporary integration payload). Both runs FAILED at the
  24.04 smoke step; the permission-denied diagnostic was recorded only on the
  later `7e59003` rerun. Staging, upload, and publication were never reached.
- Historical artifact evidence (2026-10-10, `7661eb4`, kept labelled history): real finished-artifact
  inspection RAN and FAILED, superseding the older zero-objects staging note.
  Validation-only `38040471477` audited 208 bundled objects
  (providers_checked true) with 70 missing normal desktop runtime prerequisite
  errors; no glibc/GLIBCXX floor violation was reported in that run, which
  does NOT mean ABI pass. Prior `37847748826` extracted and inspected 589
  native objects, then FAILED with 2196 errors. Neither run reached baseline,
  smoke, staging, upload, or publication. No ABI, install, or launch pass
  is claimed.
- A read-only GNU readelf scout of a local 0.4.0 outer runtime found ELF64 LE
  x86_64 DYN, static, no DT_NEEDED/GLIBC needs. Inner SquashFS/payload uninspected;
  this establishes neither a complete artifact ABI floor/identity nor launch acceptance.
- Local `.venv` is still host Python 3.14.7. Docker, Podman, and unsquashfs remain
  unavailable locally; readelf, objdump, and ShellCheck are available. Runner
  Docker succeeded for the canonical build/smoke above; no LOCAL 22.04
  build/container execution exists. CI static gate plus 22.04 baseline and 24.04
  userspace launch checks are GREEN with limited scope; no install, desktop, or
  hardware pass is claimed. The read-only `bwrap --unshare-all` presence probe
  (exit 0) is not installer validation; installer smoke needs isolated HOME,
  user units, bus, FUSE, sudo, and udev context, so a throwaway HOME alone is
  unsafe and smoke cannot run against the real host.
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
Load `naga-guided` and `publish-release`; no other skill is required for this documentation update.

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
| A7 | `runtime.py`:104-146 copies complete selected-host stdlib/extensions. Historical math/cmath needed 2.44; floor 2.35. HISTORICAL: `37847748826` inspected 589 objects then FAILED with 2196 errors; `38040471477` on trimmed `7661eb4` audited 208 objects with 70 missing-prerequisite errors. CURRENT canonical `4f14ed3` validation `38050625832` PASSED the finished-artifact static gate (208 objects, providers checked, errors empty) plus 22.04 baseline and 24.04 userspace launch checks with limited scope. | Static gate GREEN with limited scope; pinned 22.04/CPython 3.12 inputs fixed, gate keeps singular GNU fix, baseline PRIVATE-only trust, and safe `$ORIGIN` handling. No install/desktop/hardware certification. |
| A8 | Manual extraction changes root-folder/stable launcher, service, update and backup layout; HEAD `install_user.sh`:343-354 backs up image/tag pairs, not extracted trees. | INVESTIGATED contract risk; small reversible managed fallback unproven. DEFER implementation; keep FUSE required, no safety weakening. |
| A9 | [Existing release workflow](../.github/workflows/release.yml) validates source on ubuntu-latest, then runs a controlled Ubuntu 22.04 CPython 3.12 build/static gate/baseline check plus 24.04 userspace smoke; OpenRazer builds in an Arch container. [smoke.py](../buildpython/steps/appimage/smoke.py) defaults to 24.04/apt/extracted userspace; local Docker/Podman/unsquashfs absent but runner Docker succeeded. | CURRENT `38050625832` on `4f14ed3` PASSED controlled build, static gate, 22.04 baseline, 24.04 smoke, one-image staging, and upload; publisher skipped by dispatch design. HISTORICAL `38040471477` FAILED with 70 errors before baseline. Local execution remains BLOCKED; bwrap presence probe (exit 0) is not installer validation. No full install/desktop or 22.04/Fedora matrix pass. |
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
| Host-built image on old glibc target; trimmed 22.04/CPython 3.12 artifact | Historical math/cmath needed `GLIBC_2.44`; floor 2.35. HISTORICAL gates inspected the finished artifact and FAILED: 589 objects/2196 errors on `f48b3a4`, 208 objects/70 missing-prerequisite errors on trimmed `7661eb4` (no floor violation reported in the latest run, not an ABI pass). CURRENT canonical `4f14ed3` static gate PASSED (208 objects, errors empty) plus 22.04 baseline and 24.04 userspace launch checks with limited scope. | Rebuild inputs pinned; minimal finished-artifact static gate in existing workflow now GREEN with limited scope. | Reviewed fix validated in CI: normal desktop runtime prerequisites in existing 22/24 CI validation images plus EXACT libresolv PRIVATE-baseline allowance; tag-only publication pending. |
| Missing FUSE2; extraction only manual | Installer requires FUSE; extracted tree lacks proven managed update/rollback/removal contract. | Verified version-appropriate package instructions; preserve FUSE requirement. | Guidance FAKE-ACCEPTED (183); no automatic fallback/setup implemented or runtime pass. |
| Local container/extraction-tool gap | Docker/Podman/unsquashfs unavailable locally; existing smoke recipe is apt/extracted userspace only; runner Docker succeeded for canonical validation. | Existing authorized runner/VM, not daemon installation or a new test platform. | Local blocker remains; CI portable build plus 22.04/24.04 userspace launch checks GREEN with limited scope; full matrix acceptance absent. |

## Representative validation snapshot

| Family | Concrete target / snapshot | Install / launch / upgrade / remove evidence |
| --- | --- | --- | --- |
| Ubuntu | 22.04 approved build floor; selected smokes are 22.04 baseline and 24.04 userspace | CURRENT `4f14ed3`/`38050625832` GREEN: controlled build, static gate (208 objects, errors empty), 22.04 baseline and 24.04 smoke userspace launch PASS only; install/upgrade/remove NOT TESTED |
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
3. Historical: the Qt root-cause paths were pushed direct to main as `3b5d6c8`
   under the existing user authorization, then quality plus validation-only
   Release were rerun (source green, assembly red with the then-UNKNOWN log).
   `6ac962c` then committed the release notes plus step-14 diagnostic wrapper;
   source CI `37837268775` SUCCESS and validation-only Release `37837269798`
   FAILURE with the now-known missing-`file` assembly cause. Concrete
   pipeline results take precedence over manual package lookups.
4. Then representative ordinary install -> CLI/launch -> upgrade -> remove paths
   with safe fakes and available authorized environments; fix proven gaps only.
5. Then README support claims only from actual evidence; hand off existing physical
   checks to an attentive operator. Known hardware gates (exact-pin wake,
   held-output handoff, wired alternate plates) remain open; no new device campaign
   and no hardware evidence newly accepted here.
6. Git/CI/release: canonical `4f14ed3` is committed/pushed (includes `1daa514`
   key/chord, `5d91ec9` README, `81dfa9b` artwork, plus ratchets and safe smoke
   identity). Source `38050625614` SUCCESS and validation-only `38050625832`
   SUCCESS as recorded above. Next is parent handling of these final notes
   commit, push, source CI, then tag-only rebuild/publish under existing auth.
   Only when green: verify six assets (AppImage plus sha256 plus three Arch
   packages plus sidecar), then run a safely isolated installer test or name
   the precise blocker. Publication status unknown pending real tag watch. See
   [GitHub releases](https://github.com/Rainexn0b/naga-control/releases) for
   current status. Release body comes from the root changelog extractor, not
   older skill body text; [release notes](release-notes.md) and
   [changelog](../changelog.md) match 0.5.0 metadata.

## Checks and unchanged boundaries

Use focused fakes then the exact standard commands above, hardware excluded; changed scripts
need Bash/ShellCheck. Guidance/builder/gate/workflow are historical FAKE-ACCEPTED local
receipts; real CI on `4f14ed3` PASSED controlled build plus static gate plus 22.04 baseline
plus 24.04 smoke plus one-image staging plus upload (header evidence), with publisher
skipped by dispatch design; never sum scoped runs.
Doc-only checks for this edit: ASCII, local links/anchors, read-only `git diff --check` and
diff review. No Python suite is run for this docs change.
Keep all Python files <=400 physical lines and follow milestone/first-slice gates.
Target only `1532:00E7`/`1532:00E8`, one transport at a time; OpenRazer only, no
raw HID; never run GUI/service as root. Qt stays outside domain/service/hardware
adapters; GUI owner remains `src/naga_control/gui/`. Require physical USB ancestry
and forwarding readiness before grabs; retain key-down actions through key-up.
Unsafe states/write failures release grabs/generated held outputs. Keep filesystem,
GUI and blocking OpenRazer work off the evdev read/forwarding path.
This worker writes only this tracker and the release-notes overview; the revised plan and concurrent GUI, troubleshooting,
changelog and UI-tracker edits are untouched. This worker performs no Git mutations and runs
no builds/tests/services/devices; the parent owns commits/pushes/reruns under the user
authorization above. No version bump, tag, or publication is claimed or done here.
