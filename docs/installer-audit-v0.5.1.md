# Installer Audit v0.5.1 (Source Audit Timing Is Historical)

Scope at audit time: HEAD `d878e99` versus published `v0.5.0`. This note adds
source coverage only. It changes no installer behavior and no release asset
layout. Audit-time source implemented is not the old published image. Actual
release publication (commit/push, CI, tag pipeline, six public assets) remains
pending with the parent; this note claims no published artifact verification.

## Recent implemented fixes (main/checkout only)

Published `v0.5.0` scripts and body are immutable history. The following are
implemented on current checkout and described in Unreleased and the release
overview. They are not retroactive to already published tags.

- Unverified old image quarantine with verified replacement: a strictly
  verified new image replaces an unverified previous image. The old bytes are
  held as a private unverified quarantine until committed success, then
  removed with other owned quarantines. See [changelog](../changelog.md) and
  [README](../README.md).
- One verified rollback retention: after a successful install only the newest
  verified rollback pair is kept. Older verified pairs plus all owned
  quarantines are removed. Failed installs preserve recovery files. Unsafe or
  unknown operator files are never automatically removed.
- Explicit missing OpenRazer UI prerequisite notice: the Device tab reports a
  setup notice and installation-guide button, distinguishes missing clients
  from broken imports, and explains that the AppImage does not install
  OpenRazer. No automatic install or new hardware acceptance is implied.
- Entirely absent backend consented first-install only: eligible Arch/pacman
  uses prebuilt release assets, while exact named Ubuntu/Debian, Fedora, and
  openSUSE Leap/TW build local unsigned `openrazer-*-local` packages from the
  same pinned source. Existing, partial, manual, or unknown backends are left
  unchanged. Native routes stay first-install only even when explicit. Only
  Arch keeps a reviewed explicit reinstall path.
- Optional missing DKMS default no: on eligible Arch pinned opt-in, absent
  `dkms` has a separate default-no terminal consent for interactive
  `sudo pacman -S --needed dkms` before helper preflight and Naga stop. See
  [release notes](release-notes.md).
- Branch rename exact SHA and package version unchanged: active baseline is
  now `naga-v3-pro-compat` (formerly `test-pr-2904-edualb`) and earlier
  baseline is `naga-v3-pro-legacy` (formerly
  `add-razer-naga-v3-pro-support`) mapping in
  [integration findings](integration-findings.md). Full commit pin
  `26b0eeb5ed70d638fa3528851adcd5e58369a7f5` and package version
  `3.12.1.pr2904.fix2-1` are unchanged.
- `--version` selects the immutable AppImage release tag separately, while
  native `--code-ref` selects the Naga helper and builder source SHA. With no
  `--version`, the installer resolves the latest published AppImage release
  separately from the code checkout.
- Checkout-only `scripts/distro_report.sh` remains a read-only offline
  diagnostic. It is not installer integration, not eligibility, and not a
  support certificate. It is not shipped in the AppImage.

Tests referenced here are actual existing tests. No new distro or hardware
acceptance is claimed.

## Bundle and tag contract (unchanged)

- The AppImage bundles the app plus system icons and templates only, per
  `buildpython/steps/appimage`. Installer helpers are not AppImage binaries.
  They ship in the source tag, fetched immutable version, or resolved
  bootstrap SHA.
- Actual local 0.5.1 candidate extraction verified 105/105 Python files plus 4
  GUI assets byte-equal to the reviewed source; new `async_reader` plus all
  new GUI helpers present; source installer/native payload and tag set present
  (new uninstaller helper is 339 lines in source/tag only, not an AppImage
  helper). Eight integration payload files carry `KillMode=mixed`. This is
  local source/tag presence plus local image-module presence, not published
  artifact verification.
- The current one-liner follows the `main` bootstrap but installs the latest
  published AppImage and sidecar, not `main` app source. For a reproducible
  install, fetch the outer bootstrap from the same published tag and pin both
  `--ref` and `--version`. See [README](../README.md).
- Six release assets stay unchanged: the AppImage, its `.sha256` sidecar,
  three Arch packages, and the Arch manifest. No Deb or RPM binary assets are
  introduced. Local native packages are built on the host and never published
  as release binaries. The six public assets for v0.5.1 remain pipeline
  pending; final exact published artifact verification will be done by the
  parent after CI, and no such verification is claimed here.
- The v0.5.1 helper matrix is a SOURCE matrix by intent, not an image matrix:
  Arch/pacman uses prebuilt release assets while exact named Ubuntu/Debian,
  Fedora, and openSUSE build local unsigned packages from the same pinned
  source. No portable certification is claimed.
- Version, tag, and dated changelog match is still gated pending the release
  owner. The actual release body is the matching dated root changelog section
  via `scripts/prepare_release.py`, not the whole overview. This differs from
  a stale skill description; the skill is not modified here. The actual current
  pipeline/changelog contract above governs, not the stale skill-body claim.

## Validation list gap fixed here

- `buildpython/steps/step_shellcheck.py` now lists both
  `scripts/install_openrazer_native.sh` and `scripts/distro_report.sh`.
  The parent ran explicit `--run-steps ShellCheck --verbose` (1/1 PASS,
  all 8 shell scripts); `ci`/`full` profiles do not select that step
  automatically. Required payload coverage in the release `full` profile is
  provided by repo validation, not by implicit ShellCheck selection.
- `buildpython/steps/step_repo_validation.py` now requires both scripts plus
  the eight native builder modules (`__init__`, `__main__`, `archive_audit`,
  `build`, `payload`, `recipes`, `rpm_audit`, `validation`) and the native
  builder `README.md`. The fetch manifest in
  `scripts/install_openrazer_native.sh` was verified to select the same eight
  modules plus `buildpython/__init__.py`, `pin.py`, `pin.conf`, `dkms-make`,
  and package `__init__.py`.
- New fake-only tests are `tests/test_buildpython_installer_validation.py`.
  They assert each new entry exactly once, fail clearly before ShellCheck
  spawn when a new script is missing, and fail repo validation when any new
  native component is missing.
- Local full-profile build `python --profile full --skip-steps Pytest
  --verbose` passed 8/8 (compile, lint, format, type, imports, LOC, repo,
  architecture). All Python files stay at or below 400 physical lines.

Artifact, bundle, tag, install, distro, and hardware validation remain pending
with the parent for the exact published artifacts. See [hardware validation](hardware-validation.md) for dated
evidence. No full install, desktop, sudo, udev, service, or hardware pass is
claimed here. Final exact published artifact verification will be done by the
parent after CI; no such verification is claimed here.
