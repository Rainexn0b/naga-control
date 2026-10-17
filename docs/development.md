# Development

Source setup, checks, builds, and safe diagnostics for Naga Control. Default
tests use fakes and never read, grab, or write real device nodes, start the
live service or GUI, or touch hardware.

## Environment

On distributions that install OpenRazer and PySide6 into the system Python,
create the virtual environment with access to system packages:

```bash
python -m venv --system-site-packages .venv
.venv/bin/python -m pip install -e '.[dev]'
```

The fake archive tests also require `bsdtar`: install `libarchive` on Arch
or `libarchive-tools` on Debian/Ubuntu. These tests read fixture archives
only; they do not install packages or access hardware. Host Python 3.12 or
newer with Qt 6 and PySide6 is a source-development and native-build
requirement only; the AppImage bundles its own runtime (see below).

## Checks

Run the baseline checks with:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pyright
.venv/bin/pytest
```

The repository-local `buildpython` runner combines these checks, writes
per-step logs and summaries under `buildlog/naga-control/`, and always
excludes hardware tests:

```bash
.venv/bin/python -m buildpython                  # full validation, no packaging
.venv/bin/python -m buildpython --profile quick  # compile, lint, formatting
.venv/bin/python -m buildpython --profile ci     # standard checks and pytest
.venv/bin/python -m buildpython --list-steps
.venv/bin/python -m buildpython --run-steps "Ruff,Type Check" --verbose
.venv/bin/python -m buildpython --profile release # validation, AppImage, Docker smoke
```

`--with-appimage` appends packaging and smoke checks to any selection.
`--profile debt` runs generic static-analysis reports. The 400-line limit
applies to all Python files, including tests. Hardware tests are opt-in and
never part of the default suite; read
[hardware validation](hardware-validation.md) before capturing or grabbing
real input devices.

## AppImage build

Build the self-contained AppImage (bundled CPython, PySide6, and Python
dependencies; OpenRazer itself stays on the host):

```bash
.venv/bin/python -m buildpython --run-steps AppImage --verbose
```

The builder writes `dist/Naga-Control-<version>-<arch>.AppImage` and stages
its wheel, isolated runtime venv, and AppDir under `build/appimage/`. A
local native build proves the packaging step only, not the portable glibc
floor; release validation uses the controlled Ubuntu 22.04 build plus the
static gate and smoke steps (see
[installation](installation.md) and the
[portability tracker](distro-portability-plan.md)).

## Advanced build details

Release validation runs source checks with
`.venv/bin/python -m buildpython --profile full` on the host, then the
controlled `buildpython/steps/appimage/portable-build.sh` (Ubuntu 22.04 /
CPython 3.12.15, requires Docker and excludes host runtime influences),
which runs the static finished-artifact gate before bundled userspace smoke
and asset staging, followed by the Ubuntu 24.04 smoke step. Native Linux
`x86_64` and `aarch64` builders are recognized; this is not a cross-compiler.
`PYTHON_BIN` optionally selects a native, GIL-enabled CPython 3.12+
runtime; otherwise the invoking interpreter's base CPython is bundled.
Build-time Python commands are isolated from inherited Python paths; the
runtime disables user-site and current-directory imports and exposes only
the intentional host OpenRazer client/daemon-helper bridge alongside bundled
dependencies. A local native build proves the packaging step only: native
library and glibc compatibility still depend on the build host, so no
distribution support pass is claimed from a local build alone.

The smoke step requires Docker and network access, tests the exact versioned
artifact in Ubuntu 24.04, imports bundled dependencies, creates an offscreen
Qt application, checks CLI help, and installs integration assets only into
temporary directories. It never starts the service or accesses physical
device nodes. Set `NAGA_APPIMAGE_SMOKE_IMAGE` to use another compatible
container image. Missing required validation tools or Docker fail the
selected check.

Host templates live in `system/`, integration artwork in
`assets/icons/hicolor/`, and the AppRun dispatcher in
`buildpython/steps/appimage/AppRun`. The bundled integration payload uses
`usr/share/naga-control/system/` and sibling `assets/icons/hicolor/`; build
tooling and diagnostic probes are not shipped. For source-only integration,
`--source-dir` points at `system/` with icons in the sibling
`assets/icons/hicolor/` tree.

`--profile debt` runs generic static-analysis reports. Coverage and
dead-code reports additionally need the optional `coverage` and `vulture`
packages; ShellCheck is an optional system tool.

## Service packaging

Packaging installs `system/systemd/user/naga-control.service` under the user
systemd unit directory and
`system/dbus-1/services/org.nagacontrol.Service1.service` under the session
D-Bus service directory, enabled after installing the scoped udev rule;
neither the service nor the GUI runs as root.

## Safe diagnostics

The Milestone 0 diagnostic lists matching physical event nodes or records a
short, read-only capture without grabbing them:

```bash
naga-control-capture --list
naga-control-capture --duration 60 --plate 12 \
  --output hardware-captures/wireless-12-button.json
```

Connect only one Naga transport during capture. Serial numbers and physical
USB paths are redacted unless `--include-identifiers` is passed. Redaction
is not whole-capture anonymization: frames can contain incidental keys,
scans, motion, and timestamps, so review captures before sharing; see
[debug bundle](troubleshooting.md#debug-bundle). Run as the desktop user,
never with `sudo`.
