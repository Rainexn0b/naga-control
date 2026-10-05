# Build Layout Consolidation

## Goal

Align Naga Control with KeyRGB's build ownership model to reduce maintenance
overhead: build tooling in `buildpython/`, host integration in `system/`, artwork
in `assets/`, and installation orchestration in `scripts/`. Remove the repository
`packaging/` directory, not the unrelated Python `packaging` dependency.

This is a Naga-only migration. Do not change KeyRGB or introduce a configurable
cross-project build framework. The shared standard is layout and build commands;
runtime assembly remains specific to each application.

## Target Layout

```text
buildpython/steps/appimage/   Python builder, smoke checks, checked-in AppRun
system/desktop/             desktop entry
system/udev/                scoped device permissions
system/systemd/user/        user service unit
system/dbus-1/services/     session D-Bus activation
assets/icons/hicolor/      prepared application icons
assets/                    SVG and other source artwork
scripts/                   installers, uninstallers, release/diagnostic tools
build/appimage/             generated wheel, runtime venv, AppDir, build tool
dist/                      generated release artifacts
buildlog/naga-control/      generated logs and reports
```

Source directories stay tracked. `build/`, `dist/`, and `buildlog/` are already
ignored. Existing packaged GUI assets remain in `src/naga_control/gui/assets/`;
deduplicating their source artwork is outside this migration.

## Contracts To Preserve

- GUI/service/capture/integration/python AppImage dispatch and install/remove flags.
- Host OpenRazer client/daemon-helper isolation, bundled dbus-python/NumPy,
  CPython, and PySide6. Importing helpers does not start a daemon or use macros.
- Unprivileged GUI and service; no raw HID or hardware tests during builds.
- Existing installed filenames, service/bus identities, and configuration paths.
- `KillMode=mixed` and the corrected host OpenRazer package symlink.
- Versioned output `dist/Naga-Control-<version>-<arch>.AppImage` and the release's
  unversioned `Naga-Control-x86_64.AppImage` plus checksum.
- All Python files remain at or below 400 physical lines.
- The installed AppImage and running service are not replaced or restarted.

The new AppImage exposes templates under
`usr/share/naga-control/system/` and icon sources under sibling
`usr/share/naga-control/assets/icons/hicolor/`. Checkout and bundled integration
therefore use the same relative source layout. Only explicit runtime assets are
shipped, not build scripts or shutdown probes.

## Delivery Sequence

1. Record this plan and inventory all existing layout consumers and dirty files.
2. Relocate AppRun, integration templates, icons, SVG, and the existing shutdown
   probe while retaining their contents and existing fixes.
3. Replace shell assembly with focused Python functions under buildpython.
   Keep build staging and artifact paths stable; reject unsupported architecture
   overrides rather than imply cross-compilation. Exclude host site-packages
   when copying stdlib so they cannot overwrite staged dependencies.
4. Update integration source discovery, checkout installation, raw udev URLs,
   repository validation, ShellCheck, manifests, and tests. For published old
   release tags, retain a same-tag old udev-path fallback; do not silently install
   a rule from main when a pinned tag was requested.
5. Route local and GitHub release builds through
   `python -m buildpython --profile release`, retaining tag/version checks,
   release notes, checksum generation, and upload/promotion logic. Ordinary CI
   uses the same runner with `--profile ci` and a `.venv` development environment.
6. Update documentation and verify the new layout and runtime payload using
   temporary fixtures, standard checks, and a packaging build where feasible.
   Record unavailable Docker/native-runtime checks explicitly.

## Acceptance Checks

- No active source dependency on the removed repository layout remains, except
  the documented published-tag installer fallback.
- Checkout and fake extracted-AppImage integration installs create the same seven
  user integration files plus one udev rule and preserve service shutdown behavior.
- AppDir assembly ships the expected templates and all four icon sizes, has an
  executable AppRun, and excludes build tooling and diagnostics.
- Builder failures cannot pass validation or smoke-test stale artifacts.
- `ruff check .`, `ruff format --check .`, `pyright`, and `pytest` pass.
- Default tests never access real device nodes or start the remapping service.
- Docker smoke uses an unprivileged offscreen application, CLI help, and temporary
  integration installation only.

## Progress

- Plan and consumer inventory: complete.
- Source relocation and Python assembly: complete; repository `packaging/` removed.
- Integration, workflow, documentation, and tests: complete.
- Standard and host runtime verification: complete; Docker smoke remains unrun.

## Verification Record

Verified on 2026-10-05, Linux x86_64, CPython 3.14.7:

- Default buildpython profile: all nine checks passed, including Ruff lint/format,
  Pyright, import validation, architecture validation, and the physical-line limit.
- Pytest: 955 passed, two optional coverage tests skipped. Hardware tests remain
  excluded; no real input nodes were read, grabbed, or written.
- Python assembly produced `dist/Naga-Control-0.4.0-x86_64.AppImage`.
- The actual artifact passed extraction-and-run checks for bundled dependency
  imports, the host OpenRazer client import, and an offscreen QApplication.
- Service, capture, and integration help paths passed without starting the service.
- Actual bundled integration installation passed using temporary home/udev paths,
  with eight files and preserved `KillMode=mixed`.
- The source distribution built successfully with AppRun, templates, artwork,
  tooling, installer scripts, and test fixtures included.
- Bash syntax and `git diff --check` passed; generated output remains ignored.

Real-artifact checks exposed and resolved issues absent from small fixtures:
the dependency copier now excludes only top-level host OpenRazer packages rather
than Naga's own adapter; NumPy is bundled for the client; the host bridge exposes
both `openrazer` and the client's `openrazer_daemon` helpers. Cache links are
atomically replaced so concurrent GUI/service launches do not race. Build Python
commands use isolated mode; runtime imports exclude inherited Python paths,
user-site packages, and the current directory. Unsupported free-threaded CPython
is rejected rather than assembled with incorrect ABI paths.

Docker and ShellCheck are not installed on this host. The Ubuntu 24.04 Docker
smoke path is covered by script/fixture tests but has not executed here. It now
installs Qt's GLib dependency and remains a required release gate. Cross-distro
native-library compatibility, aarch64 execution, actual GUI interaction, and
hardware behavior are not claimed by these checks. The installed AppImage and
running user service were left unchanged; no release was published.
