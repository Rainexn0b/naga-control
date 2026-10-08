# Release Notes

The root [changelog.md](../changelog.md) is the authoritative versioned release
history. It contains Unreleased and the dated 0.5.0, 0.4.0, 0.3.0, 0.2.0,
and 0.1.4 entries. See GitHub releases for current publication status.
Release publishing extracts only the
matching version section via `scripts/prepare_release.py`, not this overview
or the entire changelog. The v0.5.0 GitHub body comes from the
`## [0.5.0] - 2026-10-08` section in the root changelog.

## v0.5.0

The release body is the matching
`## [0.5.0] - 2026-10-08` section in [changelog.md](../changelog.md),
extracted by `scripts/prepare_release.py`. This overview is not the release
body, and the checkout installer notes below are not retroactive to already
published tags. On committed `84d77df`, validation-only run `37840267274`
passed AppImage assembly but the static finished-artifact gate failed at
extraction staging before inspecting any payload. The extraction staging fix
is in the reviewed working tree and awaits a real CI rerun. The 22.04 baseline
and 24.04 smoke checks, staging, and upload were not reached. This overview
claims no real ABI, distro install, or launch acceptance.

### Changes in 0.5.0

- GUI profile and mode clarity: Device > Software profiles owns the single
  dropdown with explicit Activate; selectors distinguish editing selection from
  activation and show names plus IDs; the tray shows a bold disabled
  **Software controls** header with **Active software profile** plus
  **Scroll wheel** directly under it (no Software controls submenu), then
  read-only Onboard / firmware status and an independently discoverable
  read-only Device mode. Requested policy, observed mode, and remapping
  readiness stay separate; software mutations require verified driver mode.
  The closed gate reads **Switch mode (safety validation required)** and
  firmware/driver switching stays blocked pending interactive held-output,
  wake, failure, and reconnect checks.
- Installer portability: PATH-robust `ldconfig` discovery, x86_64
  `libfuse.so.2` capability checks with exact per-release manual references,
  `/dev/fuse` and kernel FUSE gates, and an interpreter-free safely locked
  uninstaller. Source safety keeps checksums before execution, read-only
  preflight, stable locks, private staging with atomic replacement,
  consent-based Naga-only upgrades with verified rollback pairs, and deferred
  activation. Ordinary installs stay app-only; the experimental OpenRazer path
  stays a separate exact-pin Arch-only opt-in cohort at
  `26b0eeb5ed70d638fa3528851adcd5e58369a7f5` (`3.12.1.pr2904.fix2-1`).
- Portability candidate: controlled Ubuntu 22.04 / glibc 2.35 / x86_64 plus
  CPython 3.12 build candidate with a finished static audit of the AppImage
  outer runtime and extracted bundled ELF/provider closure (inspection only,
  nothing executed). No real ABI, distro install, or launch acceptance is
  claimed; on `84d77df` assembly passed but the static gate failed at
  extraction staging before payload inspection, and the corrected working tree
  awaits a real CI rerun; representative-environment checks are pending.
- Runtime robustness: teardown retains ownership and joins through cancellation
  and close failures, held-output cleanup attempts each release independently,
  provisional input/capture and OpenRazer/D-Bus acquisitions roll back, the
  D-Bus name is reserved before startup with a readiness gate, diagnostics
  redact identifiers, and failed scroll/power reads never report stale values.
  No new hardware acceptance is claimed.
- Checkout-only `scripts/distro_report.sh` remains a read-only offline
  diagnostic, not installer integration and not a support certificate.
- Test-suite CI compatibility: Python 3.12-safe annotations and deterministic
  offscreen Qt widget teardown with strict deletion verification. Test-only
  improvement; no product behavior change.

### Known limits for 0.5.0

- Exact-pin natural idle/wake, held-output handoff, and interactive mode-switch
  tests are unverified; wired 6- and 2-button signatures remain uncaptured.
- Manual extraction is launch-only, not managed FUSEless installation.
- Representative distro install and launch are not yet verified.
- Safety pins and the exact-pin OpenRazer cohort are unchanged; see the
  matching changelog section for the full prerequisite and limitation list.

## Checkout installer safety

The current checkout installer adds exact-tag AppImage checksum verification,
read-only desktop/FUSE/tool preflight, a stable per-user install lock, private
staging and atomic replacement, consent-based Naga-only upgrades, and verified
image/tag rollback pairs. These changes are **not retroactive** to installer
scripts at already published tags. The README keeps v0.4.0 as its existing
published example with matched script/ref/version selection, not a claim that
it contains these new protections or that a future tag has been published.

The new installer rejects older releases missing the canonical AppImage
`.sha256` sidecar; it never falls back to unverified bytes. HTTPS sidecars are
corruption checks, not signatures or independent authentication. App-only
completion distinguishes a running service (not hardware readiness) from
staged udev/OpenRazer prerequisites. Backups preserve the previous verified
AppImage and installed tag, not packages/system state or application profiles.
Read [installer recovery](troubleshooting.md#installer-upgrades-and-rollback)
before upgrading; a partial opt-in transaction leaves Naga stopped.

## Required OpenRazer

The prerequisite is the custom baseline at commit
`26b0eeb5ed70d638fa3528851adcd5e58369a7f5` (fork branch
`test-pr-2904-edualb`), packaged as `3.12.1.pr2904.fix2-1`. No released
upstream OpenRazer minimum replaces this baseline. The kernel module, daemon,
Python client, udev rules, and metadata must come from a compatible build; a
daemon version string alone is not proof of support.

Release packaging provides an optional set of three experimental Arch packages
(`openrazer-driver-dkms-local`, `openrazer-daemon-local`, and
`python-openrazer-local`) and `openrazer-arch-packages.sha256`. Older releases
may lack these assets or the helper. Ordinary app installation works without
the optional helper and **never** offers or modifies OpenRazer. Explicit opt-in
to a release lacking prerequisites fails visibly; it does not report success.

### Experimental Arch/pacman installer

This path requires Linux x86_64 Arch-compatible pacman packaging, `bash`, `curl`, `/usr/bin/python3`,
`bsdtar` (libarchive), `sha256sum`, `sudo`, `flock` (util-linux), and a working
user systemd/session D-Bus (`systemctl`, `busctl`). Opt-in checks their read-only
status before its package downloads/changes. The data parser requires host Python 3.9+ even before
package minor compatibility is checked.
The daemon/client packages declare the builder's Python minor bounds (for
example `python>=3.14` and `python<3.15`). The helper rejects other host minors
**before sudo**, using the isolated system interpreter `/usr/bin/python3 -I -B`
for inventory, data parsing, and minor checks. An activated virtualenv or PATH
`python` alias cannot alter acceptance. This is narrow experimental support,
not a compatibility promise for every Arch derivative. Never use these packages or pacman
instructions on Debian, Fedora, or another packaging system.

From a checkout, a read-only inventory needs no network, device access, or
running daemon:

```bash
bash scripts/install_openrazer.sh --check
```

The helper's default is the same read-only inventory. Consistent exact source
stamps and package versions are labeled `KNOWN PINNED COHORT`; older fix1,
partial, mixed, upstream, and unstamped builds are `UNVERIFIED`, not declared
unsupported. Host import **discoverability** is reported separately. A PID in
source files, a daemon version, or a successful import is not runtime support.
The app's actual capabilities and recovery checks remain authoritative.

The separate `bash scripts/install_openrazer.sh --preflight` mode checks install
environment prerequisites read-only: Python minimum, active-kernel headers/build
metadata/tools and user systemd/session D-Bus. It needs no terminal and makes no
network calls, lock/state writes, group/package changes or unit configuration.
It takes precedence over install flags/`=1`; `=0` remains a hard skip and invalid
environment values remain errors. Default/`--check` inventory is unchanged and
has no install-environment gate. Preflight is not release manifest/Python-minor
validation, DKMS success, or hardware acceptance; actual install repeats the gates.

For an explicitly permitted replacement, first close the GUI and coordinate
stopping Naga and other OpenRazer clients. Save a version list and **all three
previous package archives** outside disposable caches before replacing them:

```bash
pacman -Q | grep -E '^(openrazer-|python-openrazer)' > openrazer-before.txt
# Copy the matching previous driver/daemon/client archives from your package
# cache or build output to a backup directory; abort if rollback is unavailable.
bash scripts/install_openrazer.sh --version <release-tag> --install
```

Alternatively `./install.sh --version <release-tag> --install-openrazer`
from a reviewed checkout verifies the AppImage and obtains the local or tagged helper,
runs its read-only `--preflight`, then obtains consent to stop an active Naga
service before the actual package install and app execution/activation.
Missing helper downloads, failed install-environment preflight, or older helpers
without `--preflight` make opt-in fail closed before stopping Naga, with no unchecked fallback.
Only explicit opt-in requires this helper support; app-only/older bootstrap
operation remains independent of the optional helper. Setting
`NAGA_CONTROL_INSTALL_OPENRAZER=1` opts in but does **not** bypass confirmation.
`=0` overrides install flags as a hard skip; any other set value is invalid.
Standalone `--check` stays read-only even with install flags or `=1`.
Standalone `--yes` opts in and skips **only** the helper's summary confirmation,
never pacman's conflict/replacement prompts. Group addition requires separate
consent (`--add-openrazer-group` or its separate terminal prompt) and uses the
actual `id -un` user, not inherited `$USER`. A fresh login is required for new
group membership.

The entire sidecar is validated before using its filenames: exactly three
canonical sha256sum rows, one safe basename per role, one pinned version.
All three checksums, archive `.PKGINFO` names/versions/architecture, required
`.BUILDINFO`, exact driver-to-daemon-to-client dependency links, embedded source
stamps, and system Python bounds must agree. All archive paths must be safe and
unique after optional `./` and directory-suffix normalization. Daemon/client
payloads must include their actual Python package `__init__.py` at the declared
minor's `usr/lib/python<minor>/site-packages/`, with no other-minor site-packages
payloads. Selection uses the sidecar, not API asset order;
unused older assets on the release cannot be selected accidentally. The expected
five-field source repo/SHA/branch/pkgver/pkgrel pin comes from the
**same release tag's**
`buildpython/openrazer_packages/pin.conf`, parsed only as data and checked against
the fixed authorized repo/SHA/version baseline. All five fields are required
and checked against the canonical safe data grammar. A future canonical pin
update requires deliberate review/update of the installer's fixed baseline
guard; changing only `pin.conf` will not permit an unreviewed new cohort.
Neither fetched shell configuration nor package contents are executed during validation.

Hashes detect corruption and manifest mismatch; they do **not** authenticate
the publisher independently of the GitHub/tag trust boundary. Source stamps
and metadata assert build provenance, not a reproducible-build or signed-source
proof. Review the tagged recipe, CI evidence, and source pin before trusting
packages. Package installation itself runs normal privileged pacman hooks.

The only replacement operation is one visible interactive
`sudo pacman -U <driver-archive> <daemon-archive> <client-archive>`.
Explicit opt-in deliberately reinstalls **all three**, even if the version and
source stamp already match: same-version archives can differ in recipe metadata,
DKMS wrapper, or builder Python minor. No skip flag is used; pacman's own
transaction/replacement prompts remain visible and interactive.
No blind removal, forced overwrite, dependency bypass, or unattended conflict
acceptance is used. Read the transaction and cancel if it would remove unrelated
software. The helper does not save rollback archives for you. Roll back with
one equivalent `pacman -U` transaction containing the **three backed-up
matching archives**, reviewing conflicts again, then reboot and verify. Keep the
saved version list and logs; a failed hook/transaction requires inventory before
any activation, not an assumption that everything rolled back.

Install matching headers for **each intended kernel**, DKMS, and that kernel's
required toolchain before proceeding. The new helper checks only the **active
kernel** (`uname -r`): readable build tree, Makefile and `.config`, `cc`, `make`,
and `dkms`; `CONFIG_CC_IS_CLANG=y` additionally requires `clang`, `ld.lld`,
`llvm-ar`, `llvm-nm`, `llvm-objcopy`, `llvm-objdump`, `llvm-readelf`, and
`llvm-strip` (Arch: `base-devel dkms`, matching headers, and `clang llvm lld`).
Preflight only discovers metadata/tools; it never compiles or probes devices.
It does not cover other installed kernels, guess derivative-specific header
package names, check Secure Boot signing, or guarantee DKMS hook success.
Supply all other intended kernels' headers/toolchains yourself and inspect
pacman's DKMS hook output and native DKMS status/logs. `--check`/default inventory
does not require these build prerequisites.

The helper configures only `systemctl --user daemon-reload` and
`systemctl --user enable openrazer-daemon.service`, never a system daemon or a
live restart. Configuration failure exits nonzero even after packages install.
The app opt-in path also enables Naga **without `--now`**. The new app installer
stops active Naga only with consent; GUI/OpenRazer processes and loaded modules
are never killed or restarted. Reboot is the conservative
driver/daemon activation; re-login refreshes group/session permissions. Do not
restart the new daemon against an old loaded module. Reloading udev rules alone
does not prove permissions on existing nodes.

### Verification, upgrades, and removal

After reboot/re-login, repeat `--check` and an actual host import check:

```bash
/usr/bin/python3 -I -B -c 'import openrazer.client; import openrazer_daemon; print("imports OK")'
systemctl --user status openrazer-daemon.service
journalctl --user -u openrazer-daemon.service -b
```

These do not prove hardware recovery. With one transport only, no held mouse
keys, and the precautions in [Hardware Validation](hardware-validation.md),
verify the app's runtime capabilities/status, F13/F14 DPI-stage actions, and
held F17-to-LEFTALT down/up. Then perform an **interactive** natural idle/wake
and reconnect/recovery check on this exact pin. Fix2's idle/wake gate is still
open; the [recurrence recovery](binding-recurrence-2026-10-06.md) is not a
natural sleep/wake pass. Do not run opt-in hardware tests unattended.

Review upgrades as a complete matching package cohort and repeat Python/module
activation and recovery checks. Do not indefinitely freeze security updates via
`IgnorePkg`; re-evaluate the custom baseline as upstream and host Python/kernel
change. Naga uninstall retains OpenRazer packages, its group membership, and
its user daemon; dependency removal is a separate operator decision using native
package management. Migrate back to an upstream **matching driver/daemon/client
set** only after its released capabilities and recovery behavior for `00E7` and
`00E8` have been validated. A version bump or PID listing alone is insufficient.

### Other distributions: manual matching-source native build

No automated Debian/Fedora prerequisite install is provided or claimed tested.
Obtain your distribution's OpenRazer source-package recipe and adapt **all**
components to the same immutable source. Start with this concrete source and
unprivileged staging route (not a root installation command):

```bash
git clone https://github.com/Rainexn0b/openrazer.git openrazer-naga-pinned
cd openrazer-naga-pinned
git checkout --detach 26b0eeb5ed70d638fa3528851adcd5e58369a7f5
git rev-parse HEAD   # must equal the SHA above
stage="$PWD/package-stage"
mkdir -p "$stage"
make DESTDIR="$stage" PREFIX=/usr DKMS_VER=3.12.1.pr2904.fix2 setup_dkms udev_install appstream_install
make -C daemon DESTDIR="$stage" PREFIX=/usr install
make -C pylib DESTDIR="$stage" PREFIX=/usr install
```

Use that pinned source/staged payload in the native `.deb`/`.rpm` (or other)
recipe, not `sudo make install` or an overlay onto upstream files. Consult the
pinned Makefiles and [reference recipe](../buildpython/openrazer_packages/README.md)
for DKMS version/compiler-wrapper setup; adapt paths, group/udev policy, user
unit/session D-Bus assets, native dependency metadata, and Python minor install
locations to your distribution. Build with its installed Python and matching
kernel headers/toolchain, stamp each component with the SHA, and retain the
previous native packages/version list. Install the matching native set in one
reviewed package-manager transaction, then reboot/re-login and perform the same
runtime/hardware verification. Staging alone neither builds/loads the kernel
module nor establishes distribution compatibility; a packager/operator must
complete and validate the native recipe.

See [Integration Findings](integration-findings.md) for the custom-build context
and [Hardware Validation](hardware-validation.md) for dated test environments
and results. Run neither the GUI nor the service as root.

## Hardware Limits

- Only Razer Naga V3 Pro wired `1532:00E7` and HyperSpeed `1532:00E8` are
  supported. Use one transport at a time; simultaneous attachment causes an
  OpenRazer serial-identity conflict. Bluetooth and other devices are excluded.
- The 12-button plate has captured signatures for both transports. The 6- and
  2-button tables are HyperSpeed-only; wired alternate-plate signatures remain
  uncaptured and are not enabled.
- Attached-plate selection is manual under **Device > Profiles** in 0.4.0.
  Editing every plate's bindings does not detect the attached plate or enable
  an uncaptured wired mapping. The 6- and 2-button plates are unlit by design.
- Primary clicks and wheel scrolling remain passthrough, not editable bindings.
- Driver mode `3:0` is required for mapped events. Idle can silently revert it
  to `0:0`, suppressing special-button and grid events until it is reasserted.
- Stale kernel pressed-state can block the held-key startup gate. Physically
  tapping the affected control clears a lost release.
- Scroll acceleration and Smart Reel default to off; enable them in Settings
  if wanted. Settings Apply is atomic for the configuration document, not for
  the sequence of OpenRazer hardware writes.
- v0.4.0 includes an experimental service-wide firmware/driver mode policy in
  configuration, but no tray switch. Held-output and wireless wake safety
  checks are inconclusive; do not rely on firmware-mode persistence for daily
  use until those checks pass. Software mode remains the default.
- Guided source-only mode handoffs passed on wired and HyperSpeed, but held-output
  ordering, natural wireless sleep/wake, and recovery from a real device-mode
  drift remain unverified. Consult [Hardware Validation](hardware-validation.md)
  for dated evidence and safety instructions; v0.4.0 does not claim full
  hardware validation.

## Historical Notes

GitHub publication dates in UTC are **2026-09-28** for
[v0.1.4](https://github.com/Rainexn0b/naga-control/releases/tag/v0.1.4) and
**2026-09-29** for
[v0.2.0](https://github.com/Rainexn0b/naga-control/releases/tag/v0.2.0).
These historical releases and tags were verified before preparing 0.3.0.

Earlier versions of this document, also copied into GitHub release bodies,
listed development iterations 0.1.0 through 0.1.3 as separate headings. Those
changes are now consolidated into the first published release, 0.1.4. The
unpublished 0.1.5 fix that isolates the host OpenRazer Python package from
bundled `evdev` is recorded under 0.2.0, where it was actually shipped.
Removing duplicated history here does not change the existing GitHub release
bodies or imply that those intermediate versions were published.
