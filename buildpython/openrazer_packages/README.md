# Pinned OpenRazer Arch Packages

`pin.conf` is the canonical data-only pin for builds, validation and generated
release prerequisites. The authorized source is `Rainexn0b/openrazer` commit
`26b0eeb5ed70d638fa3528851adcd5e58369a7f5`, branch `test-pr-2904-edualb`, packaged
as `3.12.1.pr2904.fix2-1`. Parsing rejects unknown/duplicate fields and shell
expansion before any environment export; do not manually `source pin.conf`.
The recipe checks the exact Git HEAD before the known Arch group-name transform.

The recipe and helpers originated in the fork's `packaging/arch-canonical/`.
They are **not verbatim** anymore: downstream guards consume the validated pin,
require the regression compilers, reject skipped/missing tests, bound Python
compatibility, and preflight Clang-kernel tools. OpenRazer still owns hardware
operations; these changes are packaging, not a replacement hardware backend.

## Build and validation

Run only as a non-root build user, with `base-devel`, `git`, `python-setuptools`,
`libarchive`, `clang`, `llvm`, `lld`, and these full unittest dependencies:

- `python-daemonize`, `python-pyudev`, `python-setproctitle`
- `python-gobject`, `dbus-python`, `xautomation`, `python-numpy`

From the repository root, for an explicitly requested manual build:

```bash
cd buildpython/openrazer_packages
makepkg --verifysource
makepkg --cleanbuild --log
cd ../..
python scripts/validate_release_assets.py buildpython/openrazer_packages \
  --packages-only --create-checksums --check-imports
```

`check()` requires both `cc` and `clang`. All 55 pinned focused tests must run
successfully with **zero skips**. A count change requires deliberate review,
not a claim that a partially skipped suite passed. No daemon is started.

The three `*-local` packages must have exactly the canonical version, source
stamp at `usr/share/doc/<pkgname>/source-commit`, and `.BUILDINFO`. Daemon-to-driver
and client-to-daemon dependencies are exact. Both Python packages declare the
builder minor floor and next-minor ceiling (for example `python>=3.14` and
`python<3.15`), matching their site-packages paths. Validation stages only safe
Python source bytes and imports the client and daemon package in an isolated
interpreter; it never constructs `DeviceManager` or contacts hardware. This
does not guarantee compatibility across different Python minors: rebuild and
review for an Arch Python-minor transition.

The sidecar `openrazer-arch-packages.sha256` uses exact `sha256sum` text syntax
and exactly three safe canonical basenames, all ending in `-any.pkg.tar.zst`.
It is corruption detection, **not independent authentication**. Retain the
archives' `.BUILDINFO` and source stamps when investigating provenance.

CI installs Arch mainline and LTS headers and includes compile-only gates for
both, choosing `LLVM=1` for a Clang-configured kernel. No modules are loaded.
Clang kernels need `clang`, `lld` and LLVM tools (`llvm-ar`, `llvm-nm`,
`llvm-objcopy`, `llvm-objdump`, `llvm-readelf`, `llvm-strip`); `dkms-make` reports
missing tools or headers explicitly. Those representative headers do not cover
every downstream kernel. The new CI/package/kernel builds have **not been run
by this fake-only implementation wave**; actual CI success and host DKMS
compatibility remain release/operator gates.

## Publication and reproducibility limits

Metadata validation blocks both read-only artifact builds on an invalid push
tag. Dispatches (including dispatches on a tag) build validation artifacts only.
One publisher waits for both successful builds, validates exactly six assets
(AppImage, its checksum, three packages, package checksum), then uploads to a
draft and verifies every remote byte before publication. Draft reruns discard
all stale/partial assets. An identical public release is a verified no-op;
divergent public releases are immutable and require a new tag, never `--clobber`.
An upload/verification failure leaves the draft unpublished. External concurrent
release edits are not transactional; workflow concurrency serializes this
workflow, not manual GitHub operations.

Fixed source pinning is **not bit reproducibility**: `archlinux:base` and pacman
repositories move, including Python/compiler/header versions. `.BUILDINFO`
captures build dependencies but does not freeze the base image or repositories.
This explicitly opt-in Arch prerequisite bridge is temporary experimental
support, not an automatic indefinite security freeze. Review upstream/security
changes and retire the bridge when an accepted upstream build provides the
required capabilities and recovery behavior; any pin change needs coordinated
review and new package/hardware acceptance.

## Installation and exact-pin hardware caveat

Install only the coherent three-package set selected from the strictly
validated sidecar, together in one visible privileged `pacman -U` transaction.
The opt-in installer owns host compatibility and conflict checks; do not select
arbitrary wildcard assets or mix versions. Never run the GUI/service as root.
A reboot is the conservative activation option. Coordinate daemon restart and
driver reload, and compare loaded module versions with installed modules.
Reloading udev rules alone may not restore permissions on existing attributes.

Long-term physical acceptance for **this exact fix2 pin** remains outstanding:
natural idle/wake without daemon restarts, F17 down/up delivery, receiver
reconnect, and responsive pointer/dock behavior, on one supported transport
(`1532:00E7` or `1532:00E8`) at a time. Older baseline evidence, fake tests,
compile checks, clean imports or a fresh daemon startup do not prove it.
