# Distro Portability Plan (Revised)

Status: **implementation plan; repository assumptions require verification**.
Original request: **"Make installer support as many distros as possible."**
Scope: Naga Control's **existing Linux installer and the runtime compatibility needed to make its installs usable**. This plan supersedes the execution waves in the earlier `docs/distro-portability-plan.md`; it does not imply their in-progress code has been accepted or discarded.

## 1. Outcome and limits

The normal installer should work across the widest practical range of **x86_64, glibc-based Linux distributions**, with minimal distribution-specific code. Users should be able to install, launch, upgrade, and remove the application through the existing supported workflow, subject to documented desktop/session and hardware requirements.

Prioritize actual working installs over classification, reports, provenance infrastructure, or theoretical coverage. Prefer capability detection and reuse of existing installer paths to per-distro implementations.

**In scope**
- Find and remove concrete distro-dependent installer failures.
- Detect prerequisites and provide correct, actionable, version-appropriate remedies; allow explicitly consented prerequisite setup where safe and justified.
- Make the shipped AppImage usable against the **already approved Ubuntu 22.04 / glibc 2.35, x86_64** baseline.
- Validate a representative selection of package-manager families and derivatives, and document which configurations actually work.
- Investigate a narrow FUSEless managed-install fallback if FUSE2 is a major blocker, without bypassing existing installation security/rollback rules.

**Out of scope**
- Rewriting the installer, creating a generic package-manager/provider framework, or introducing `.deb`, `.rpm`, Snap, Flatpak, or other new distribution formats.
- General Linux portability beyond the present x86_64/glibc product target (e.g., musl/Alpine, ARM64, non-Linux).
- Broad service, evdev, GUI, hardware, OpenRazer, kernel/DKMS, release governance, or CI-platform redesign.
- Promising operation without required user systemd, session D-Bus, usable desktop integration, and device permissions unless an existing supported alternative is discovered.
- Broad package installation, privileged operations, or external helper downloads without explicit interactive user consent.

## 2. Facts carried from the prior plan (recheck in the current checkout)

These are **prior-plan evidence, not fresh verification**:

- The approved portable build target is **Ubuntu 22.04 (glibc 2.35), x86_64**, using a separately controlled pinned **CPython 3.12** toolchain. Ubuntu 24.04 was considered but not chosen as the build floor.
- A previously inspected local AppDir bundled CPython 3.14 `math`/`cmath` extensions requiring `GLIBC_2.44`; that says nothing conclusive about the full current or published artifact.
- Managed installation previously assumed FUSE2, user systemd, session D-Bus, x86_64/glibc, tools, and permissions. Extraction existed only as a manual alternative.
- Ordinary installation was application-only. The experimental OpenRazer helper remained separate and restricted to the existing Arch/pacman opt-in, exact-pin/consent/rollback policy.
- A bounded static ABI-audit foundation was **in progress** in `buildpython/steps/appimage/{elf,abi}.py` and related tests. A checkout-only `scripts/distro_report.sh` foundation was also **in progress**. Neither was accepted as a completed compatibility solution.
- Docker/Podman were unavailable in the earlier local environment. The reported `154b308` HEAD and test results are historical snapshots, not assumed current state.
- Previously checked package-name examples: Ubuntu 22.04 `libfuse2`, Ubuntu 24.04 `libfuse2t64`, Arch `fuse2`. **Verify against current supported versions and repositories before suggesting commands**; no other names are established by this plan.

Consult `AGENTS.md`, the existing installer/README guidance, `docs/release-notes.md`, relevant `docs/architecture.md`, current build tooling, and applicable `naga-guided` instructions. Load further documents only when they answer a concrete implementation question. Existing Qt code lives under `src/naga_control/gui/`, not `ui/`.

## 3. Assumption register: agent must fill from evidence

**Do not invent answers.** First inspect the current repository, record each answer with a file path/test/command, and update only the conclusions that affect implementation. If still unknown, record the blocker and continue with independent work.

| ID | Working assumption or question | Evidence the agent must find | Decision rule |
| --- | --- | --- | --- |
| A1 | There is one canonical normal install entry point. | Entrypoint(s), caller chain, README command, install/upgrade/uninstall paths. | Extend the canonical path; do not create a second installer. |
| A2 | Most installer failures come from prerequisite/distro assumptions rather than application behavior. | Actual checks and commands for FUSE, systemd, D-Bus, package managers, paths, permissions. | Fix demonstrated blockers first; no speculative abstractions. |
| A3 | The bundled application does not require host Python. | AppImage/runtime composition and invocation. | Preserve app-only installation; do not add system Python by default. |
| A4 | `/etc/os-release` plus available tools can guide prerequisite instructions. | Existing parser/report, distro-specific command paths, hostile-input handling. | Treat `ID_LIKE` as a hint; never execute sourced os-release fields or guess package names. |
| A5 | apt, dnf, pacman, and zypper cover the useful initial package-manager paths. | Existing support, real targeted distros/versions, package lookup. | Add only the missing small adapters/branches required by an observed target. |
| A6 | The current install can remain app-only without installing optional OpenRazer. | Installer source and release-note policy. | Keep helper opt-in separate; no expanded helper cohort. |
| A7 | An older-build AppImage can meet the approved ABI floor. | Toolchain/image source, actual bundled ELF requirements, outer runtime. | Correct the build source/dependencies; do not claim portability from host version alone. |
| A8 | A safe FUSEless managed-install path might reuse existing extraction machinery. | Existing `--appimage-extract` use, install layout, launcher/service paths, update/removal semantics. | Implement only if small and contract-preserving; otherwise document limitation and defer separately. |
| A9 | Test execution can use existing CI, containers, or VMs without introducing a new testing platform. | Current CI/reproducible environments and available runners. | Use what exists; if absent, report validation gap, not fabricated passes. |
| A10 | A distro install does not imply working mouse hardware. | OpenRazer/device dependencies and hardware guide. | Separate installer/app validation from hardware support claims. |

After discovery, create a **short compatibility-gap ledger**: `environment -> existing failure -> smallest fix -> verification`. Do not turn the register or ledger into a permanent framework unless the repo already has one.

## 4. Execution plan

### Phase 1: Inspect and establish the baseline (no new architecture)

1. Read current installer, distribution/bootstrap scripts, README install command, upgrade/uninstall code, AppImage builder, and relevant tests. Check working-tree changes before touching files.
2. Locate any active ABI-audit and `scripts/distro_report.sh` changes. Preserve good in-progress work; merge/repurpose instead of duplicating or starting over.
3. Trace one normal install end-to-end, including executable permissions, desktop integration, user services, udev/setup prompts, checksum checks, rollback, and uninstall.
4. Check the real AppImage/build inputs and compare actual artifact requirements with the approved glibc target. Flag whether older-build work is a launch blocker.
5. Fill A1-A10 and rank **observed** failures by coverage impact. State which limitations belong to the installer versus runtime versus optional hardware.

**Exit:** An evidence-based, short implementation delta. Start fixing failures; do not gate all work on a long research report or unneeded approvals.

### Phase 2: Extend the existing installer for distro families

1. Use existing detection code if present; otherwise add a small, testable detection routine. Parse os-release as **data**. Use available commands to detect capabilities; never evaluate or source untrusted os-release content.
2. Make normal app install/upgrade/uninstall paths package-manager agnostic where they do not actually require package installation.
3. Handle missing prerequisites as follows:
   - Check the **actual capability** first (e.g., runtime/library present, user systemd/D-Bus available, integration command available), not only distro branding.
   - For known distro/version combinations, show verified, actionable package names and commands. Map apt/dnf/pacman/zypper only when needed and confirmed. No unsupported guessed fallback commands.
   - Default to an explanation and preview. Any `sudo`, package install, udev rule deployment, service activation, or similar privileged mutation requires existing explicit consent/policy. If safe optional automation is already part of the installer, reuse it; do not silently add it.
   - An unknown distro/derivative should still use generic install steps when capabilities are present. If a missing prerequisite cannot be resolved safely, fail with a useful message rather than a false support claim.
4. Treat `ID_LIKE` as advisory, not proof of binary/package compatibility. Avoid version-specific hardcoded branches where a capability check can solve the problem.
5. Inspect FUSE2 as a cross-distro bottleneck. Prefer a present, working FUSE route. If absent, assess whether the existing manual extraction path can be made a **small, reversible, managed fallback** without breaking verification, launchers, updates, permission/ownership safety, or clean removal. If this requires a second deployment architecture or a security-policy change, **do not implement it in this campaign**; report the trade-off.
6. Keep ordinary installation independent of experimental OpenRazer setup. Do not extend OpenRazer automatic installation beyond its existing approved cohort.

**Exit:** The installer follows one coherent path across the targeted distro families, with correct prerequisite handling and no unrelated setup side effects.

### Phase 3: Make the AppImage portable enough to launch

1. Retain the approved **Ubuntu 22.04/glibc 2.35/x86_64 + pinned CPython 3.12** build target. Discover and pin required toolchain/runtime inputs consistent with the existing build system; avoid inventing new release infrastructure.
2. Finish or simplify the in-progress static ELF audit so it checks the **actual finished artifact**, including the outer AppImage runtime and bundled native objects. Check architecture, required `GLIBC`, `GLIBCXX`, `CXXABI`, and unresolved essential dependencies. Report offending object and requirement. Avoid turning this into a generic ELF analysis library.
3. Keep inspection static: do not run untrusted native executables or use execution-based `ldd` to inspect artifacts. Preserve the existing fake fixtures for concrete ABI-failure cases.
4. Add the **smallest reliable invocation point** that prevents an incompatible artifact from being treated as a portable build. Integrate into existing build/check workflow; no publication-system redesign.
5. Verify real build output independently of synthetic fixtures. A passing parser unit test is not ABI evidence.

**Exit:** A real artifact is shown to meet the selected target's relevant ABI requirements, or the exact remaining incompatibility is reported. Do not claim every distro will run based on GLIBC alone.

### Phase 4: Validate representative distros and fix only proven failures

Initial target coverage (select concrete current versions/snapshots during discovery, then record exact versions):

| Family | Representative test | Purpose |
| --- | --- | --- |
| Ubuntu / Debian | Ubuntu 22.04 baseline, newer Ubuntu, current Debian | Old glibc floor; apt derivatives; FUSE naming differences |
| Fedora | Current supported Fedora | dnf/RPM family and desktop prerequisite behavior |
| Arch | Current Arch snapshot | pacman/rolling release, existing user environment |
| openSUSE | One currently available Leap or Tumbleweed target | zypper and service/prerequisite differences |
| Derivative | At least one realistic Mint/EndeavourOS/other derivative, if available | Confirm `ID_LIKE` handling without blanket inheritance |

Test **ordinary install -> launch/CLI -> upgrade (where applicable) -> uninstall** on as many representative environments as available. Use isolated temporary homes or safe test VMs for filesystem/desktop behavior; a container can cover only userspace/CLI portions. Mock any package-manager mutation, permission changes, user services, and device access in automated unit tests. No live hardware tests from unattended workers.

Validation levels may be simply recorded as **install tested**, **launch tested**, **blocked/conditional**, or **not tested**, with exact distro version and blocker. Do not imply hardware compatibility or test results for untested derivatives. Avoid elaborate immutable-image/receipt machinery; existing CI and a compact result table are sufficient.

If local Docker/Podman is unavailable, use an existing authorized runner or VM. **Do not install/start a daemon, invent a new CI platform, or claim a smoke pass** to satisfy the matrix.

**Exit:** Representative checks pass or yield precise, documented blockers. Fix blockers that can be corrected within installer/runtime scope; don't start separate system, kernel, or hardware projects.

### Phase 5: User-facing install guidance and handoff

1. Update README install instructions with one canonical command, supported/tested configurations, required host capabilities, and optional prerequisite steps.
2. Clearly distinguish: **installer works**, **application launched**, and **hardware/OpenRazer validated**. Never equate them.
3. Update relevant current packaging tests and keep the existing release/upgrade/rollback and consent contracts intact.
4. Summarize exactly which distros/versions were tested, what changed, what remains conditional, and why anything was deferred. No publication/tag/version bump unless separately requested.

## 5. Tests and guardrails

- Test detection and prerequisite decisions using controlled PATH/os-release fixtures: known versions, unknown derivatives, missing tools, malformed data, and hostile input. No network, `sudo`, package install, service activation, or filesystem mutation during read-only detection/tests.
- Test install/uninstall idempotency and non-destructive failure recovery. Preserve existing security, checksum, path handling, copy/permissions, activation, and rollback controls.
- Run focused tests first, then existing repository checks as applicable: Bash syntax/ShellCheck for changed shell scripts, Ruff/format, Pyright, and default pytest with hardware excluded. Follow the repository's **<=400 physical-line Python file** convention.
- Preserve existing architecture and service/hardware boundaries, including OpenRazer-only device access, current USB target scope, Qt ownership, and evdev/grab/release safety. Do not modify them absent a demonstrated installer regression.
- Maintain the experimental OpenRazer Arch/pacman exact-pin, explicit opt-in, deferred activation, rollback, and validation restrictions in existing release notes.
- No unapproved `sudo` or system mutations by an agent; no automatic tag/push/deploy/publish. Interactive user consent in an installed product is separate from agent permission to change the development machine.

## 6. Scope control and stopping rules

**KEEP:** Current installer; approved old-glibc baseline; bounded ELF verification; reusable distro detection; existing tests and safety contracts.

**SIMPLIFY / REPURPOSE:** Existing distro reporter becomes a reusable prerequisite diagnostic for the installer, if it helps. Use a small smoke matrix, not a portability-certification system.

**DEFER / REMOVE:** Full cross-distro OpenRazer helper support; new package formats; general package-provider abstractions; broad FUSE deployment redesign; ARM64/musl; exhaustive distro/snapshot certification; new CI platform; separate device/firmware validation campaign; release governance changes.

**Escalate rather than expand** if a fix would require: a new installation architecture, revised privilege/consent/security policy, a new platform target, a change to the experimental OpenRazer cohort, or a release format change. Provide the concrete blocker and the smallest proposed separate task; continue other scoped work.

**Definition of done:**
- The existing installer supports the chosen major distro/package-manager families through its normal flow, subject to clearly stated prerequisites.
- Missing dependencies produce correct instructions or an explicitly consented, safe setup path, not crashes or silent privileged changes.
- A verified artifact meets the approved build compatibility target and can launch in representative environments.
- Install/upgrade/remove behavior is covered by applicable tests or named human-run validation; regressions are addressed.
- Unknown environments fail clearly or install generically when capabilities are satisfied.
- README support claims match observed tests; optional hardware constraints remain separate.

**STOP when these conditions are satisfied for the chosen representative environments.** Do not extend the campaign just to enlarge the test matrix, create more policy machinery, or certify every derivative. Record unsupported edge cases as follow-up issues, not required prerequisites to shipping the installer improvements.
