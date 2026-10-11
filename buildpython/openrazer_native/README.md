# Native OpenRazer packages (builder only, experimental)

This directory builds **private local** `.deb`/`.rpm` packages from the
immutable pinned OpenRazer source. It does not install anything, load kernel
modules, start daemons, or claim hardware support.

## Pinned source

- Fork `Rainexn0b/openrazer`, commit
  `26b0eeb5ed70d638fa3528851adcd5e58369a7f5`, packaged as
  `3.12.1.pr2904.fix2-1`.
- Branch labels `test-pr-2904-edualb` and `naga-v3-pro-compat` are aliases;
  the full commit SHA is authoritative, never a moving tip.
- The same three local role names as the Arch cohort are produced:
  `openrazer-driver-dkms-local`, `openrazer-daemon-local`,
  `python-openrazer-local`.

Reference evidence only (never fetched or executed at runtime):

- Pinned `Makefile`, `daemon/Makefile`, `pylib/Makefile`,
  `daemon/setup.py`, `pylib/setup.py`, `debian/control`, `debian/rules`,
  `install_files/dkms/dkms.conf`, daemon D-Bus/user-unit templates.
- Official OBS `openrazer.spec` for Fedora/openSUSE dependency evidence.

## CLI

Run with the target host's isolated system Python 3.10+ (stdlib only).
Use `fedora` or `opensuse` for `--family` on those hosts; `--pin`
is optional data-only. Source must be a fresh clean git checkout
at the full pinned SHA; output must be an owned private empty
directory.

```bash
python -m buildpython.openrazer_native \
  --family debian --source /path/to/pinned-source --output /path/to/private-empty-output
```

The builder refuses root, unsupported families, invalid pins, dirty or
mismatched sources, and non-empty/unsafe outputs **before** any
source or build command. It uses trusted command arrays only
(`git`, `make`, isolated `setup.py install`, `dpkg-deb`, `rpmbuild`,
`rpm`, `rpm2cpio`), never `sudo`, package-manager installs, DKMS
activation, `systemctl`, device queries, or raw network clones.

## Payload and packaging

- Every `make`/`setup.py install` uses a private `DESTDIR`/`--root`
  with `PREFIX=/usr`; forbidden targets include `driver_install`,
  `depmod`, and `xdg_autostart`.
- Driver stages `setup_dkms`, `udev_install`, `appstream_install` with
  `UDEV_PREFIX=/usr`, `DKMS_VER=3.12.1.pr2904.fix2`, a patched
  `dkms.conf` (`PACKAGE_VERSION`, `MAKE="./dkms-make ${kernelver}"`),
  the vetted `dkms-make` wrapper, and the `openrazer` group transform.
- Daemon resources come from `install-resources`, `install-systemd`,
  `manpages`; Python trees use explicit `--install-lib`
  (`/usr/lib/python3/dist-packages` on Debian,
  `/usr/lib/python3.N/site-packages` on RPM) with
  `--single-version-externally-managed --record`.
- Each role carries `usr/share/doc/<role>/source-commit` (full SHA
  plus newline) and a GPL reference; XDG autostart is never staged.
- Debian packages are built with `dpkg-deb --root-owner-group` from
  the staged payload plus owned `DEBIAN/control/postinst/prerm`;
  the unreviewed `dh` pipeline is never used.
- RPMs are built via a private topdir `rpmbuild` from the owned
  static spec template and staged payload; no `Source0` network,
  no `%post` activation.
- Filenames are canonical: `role_3.12.1.pr2904.fix2-1_all.deb` and
  `role-3.12.1.pr2904.fix2-1.noarch.rpm`. No meta/doc/debug extras.
- `openrazer-native-packages.sha256` (3 rows) and `native-build.json`
  (`schema=1`) are written only after the full cohort passes audit.
  Checksums are corruption detection, not published signed release
  authentication.

## Scope and operators

- Supported families `debian`, `fedora`, `opensuse` are **experimental**;
  runtime and hardware (`1532:00E7`/`1532:00E8`, OpenRazer-only,
  fail-open) remain unverified. Debian and Leap themselves were not
  smoked; no blanket distro certification is claimed.
- This builder stays build-only and unprivileged: no package installs,
  dependency provisioning, module loads, group changes, or daemon
  activation. Normal installs use the separate opt-in first-install-only
  helper `../../scripts/install_openrazer_native.sh` on exact named
  Ubuntu/Debian/Fedora/Leap/TW hosts; see
  `../../docs/release-notes.md#local-native-installer-ubuntudebian-fedora-opensuse`
  for prerequisites, consent, and limits.
- Build evidence only: rootless pinned-source builds passed package and
  output audits plus the native-helper output validator on Ubuntu
  22.04.5, Fedora 44, and openSUSE TW 20261009, with no OpenRazer
  install, DKMS compile/load, service, GUI, or hardware run claimed.

## Tests

Fake-only unit tests (no real git/builds/devices):

```bash
.venv/bin/pytest -q tests/test_openrazer_native_build.py \
  tests/test_openrazer_native_payload.py tests/test_openrazer_native_validation.py
```
