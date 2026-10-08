# Distro Portability Execution Tracker

Status (2026-10-08, HEAD `154b308`): **revised plan approved; implementation open**.
The user approved [Distro Portability Plan (Revised)](distro-portability-plan-revised.md)
with "then follow the revised plan. please continue". That read-only plan controls
the sequence and scope; it supersedes this file's former execution waves.
This is its compact evidence/register tracker, not another plan or support promise.
pyproject is 0.5.0 preparing; latest published remains v0.4.0 with no tag/publication yet.
Guidance, portable builder, artifact gate, and workflow wiring are FAKE-ACCEPTED locally;
real CI build/ABI/smoke remain PENDING and undispatched; no commit/push/dispatch yet (see below).

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

## Standard checkpoints (never sum scoped runs)

Parent exit-0 checkpoint before the guidance wave (source-hash-stable snapshot):
- `.venv/bin/ruff check .`: `All checks passed!`
- `.venv/bin/ruff format --check .`: `394 files already formatted`
- `.venv/bin/pyright`: 0 errors, 0 warnings, 0 infos.
- `.venv/bin/pytest`: **3263 passed**, 2 skipped (missing coverage), 5 hardware deselected, 8 dependency warnings, 213.03s; actual full-suite count, not a scoped sum.
- `bash -n scripts/install_user.sh`; `bash -n scripts/uninstall.sh`; `bash -n scripts/distro_report.sh`: separate invocations, exit 0 silent.
- `shellcheck scripts/install_user.sh scripts/uninstall.sh scripts/distro_report.sh`: exit 0 silent.
Post-guidance supervisor checkpoint: Ruff pass, format 395, Pyright 0, default pytest **3269 passed**,
2 coverage skips, 5 hardware deselected, 8 dependency warnings, 207.92s; source/README/troubleshooting
stable. It predates the NEW portable builder/gate and current GUI final tweaks.
Stable full-source snapshot (supervisor rerun, exit 0): Ruff pass, format 415, Pyright 0/0/0,
offscreen pytest **3411 passed**, 2 coverage skips, 5 hardware deselected, 8 warnings, 248.81s;
tracked/untracked hashes identical before/after, no code writers active. A prior 2-minute tool
timeout gave no result (not a failure); the rerun completed exit 0.
Fresh supervisor scoped runs today (not full acceptance, never summed): `bash -n` on
install_user/uninstall/distro_report plus ShellCheck: exit 0 silent.
- Installer scope `.venv/bin/pytest -q` (ldconfig, prerequisite guidance, cleanup,
  failures, lock): **136 passed, 47.26s**.
- `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q` GUI scope under `tests/` (profile mode/controls,
  tray mode/controls, mode guards, app, device/profiles pages, draft reconciliation, switch
  revisions, tray profiles/scroll/reconcile, source-limit discovery): **240 passed, 8 warnings, 12.26s**.

## Independent fake acceptance (supervisor, 2026-10-08)

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
  Fake-only; executable bits 0755 (`--help` both pass, no content change). Nothing dispatched.

## A1-A10 assumption register

Unchanged chain/build references use HEAD `154b308`; uninstall/PATH/guidance conclusions
include the current reviewed working-tree fixes. Acceptance is fake-only.

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
| A9 | [Existing release workflow](../.github/workflows/release.yml) uses an Arch helper container but builds AppImage on ubuntu-latest. [smoke.py](../buildpython/steps/appimage/smoke.py) defaults to 24.04/apt/extracted userspace; local Docker/Podman/unsquashfs absent. | Existing platform reuse feasible, execution BLOCKED locally; runner wiring/final static gate pending. No full install/desktop or 22.04/Fedora matrix pass. |
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

1. Uninstall/PATH/guidance fake reviews and the dated checkpoints above are complete;
   none accepts portable builds, distro installs, or hardware.
2. FAKE-ACCEPTED locally: portable 22.04/3.12 build plus finished-artifact ABI gate
   (static inspection only, no execution-based `ldd` audit) and existing workflow
   driver/static-gate wiring. Real CI build/ABI/smoke PENDING; nothing dispatched yet.
4. Then representative ordinary install -> CLI/launch -> upgrade -> remove paths
   with safe fakes and available authorized environments; fix proven gaps only.
5. Then README support claims only from actual evidence; hand off existing physical
   checks to an attentive operator. Known hardware gates (exact-pin wake,
   held-output handoff, wired alternate plates) remain open; no new device campaign.
6. Git/CI/release (user-authorized, nothing done yet): parent next commits/pushes a review
   branch covering everything in the current tree, committed or uncommitted (including the
   GUI edits this worker leaves untouched), then dispatches the EXISTING validation-only
   Release workflow. Then concrete CI followups; authorized v0.5.0 tag/publication only
   when green. Latest published stays v0.4.0; v0.5.0 preparing.
   Release body comes from the root changelog extractor, not older skill body text;
   [release notes](release-notes.md) and [changelog](../changelog.md) match 0.5.0 preparing.

## Checks and unchanged boundaries

Use focused fakes then the exact standard commands above, hardware excluded; changed scripts
need Bash/ShellCheck. Guidance/builder/gate/workflow FAKE-ACCEPTED locally; real CI/ABI/smoke
PENDING; never sum scoped runs.
Doc-only checks: ASCII, line count, local links/anchors, read-only Git diff/untracked-file state.
Keep all Python files <=400 physical lines and follow milestone/first-slice gates.
Target only `1532:00E7`/`1532:00E8`, one transport at a time; OpenRazer only, no
raw HID; never run GUI/service as root. Qt stays outside domain/service/hardware
adapters; GUI owner remains `src/naga_control/gui/`. Require physical USB ancestry
and forwarding readiness before grabs; retain key-down actions through key-up.
Unsafe states/write failures release grabs/generated held outputs. Keep filesystem,
GUI and blocking OpenRazer work off the evdev read/forwarding path.
This worker writes only this tracker; the revised plan and concurrent GUI, troubleshooting,
changelog and UI-tracker edits are untouched. This worker performs no Git mutations and runs
no builds/tests/services; the parent acts on the above authorization only after the CI wiring
checks pass. No version bump or publication is claimed or done here.
