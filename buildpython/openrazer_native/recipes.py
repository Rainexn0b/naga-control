"""Static native recipes: filenames, dependencies, control/spec, scriptlets."""

from __future__ import annotations

SUPPORTED_FAMILIES: tuple[str, ...] = ("debian", "fedora", "opensuse")

LOCAL_ROLES: tuple[str, ...] = (
    "openrazer-driver-dkms-local",
    "openrazer-daemon-local",
    "python-openrazer-local",
)

EXPECTED_REPO = "Rainexn0b/openrazer"
EXPECTED_COMMIT = "26b0eeb5ed70d638fa3528851adcd5e58369a7f5"
EXPECTED_PKGVER = "3.12.1.pr2904.fix2"
EXPECTED_PKGREL = "1"
ALLOWED_BRANCHES: tuple[str, ...] = ("test-pr-2904-edualb", "naga-v3-pro-compat")

SIDECAR_NAME = "openrazer-native-packages.sha256"
MANIFEST_NAME = "native-build.json"
SCHEMA_VERSION = 1

DKMS_NAME = "openrazer-driver"

FORBIDDEN_SCRIPT_FRAGMENTS: tuple[str, ...] = (
    "modprobe",
    "rmmod",
    "depmod",
    "udevadm",
    "systemctl",
    "systemd-run",
    "service openrazer",
    "service dbus",
    "gpasswd",
    "usermod",
    "useradd",
    "update-rc.d",
    "invoke-rc.d",
    "deb-systemd-helper",
    "dh_systemd",
    "xdg_autostart",
    "/etc/xdg/autostart",
)

UPSTREAM_DEB: dict[str, str] = {
    "openrazer-driver-dkms-local": "openrazer-driver-dkms",
    "openrazer-daemon-local": "openrazer-daemon",
    "python-openrazer-local": "python3-openrazer",
}

UPSTREAM_RPM: dict[str, str] = {
    "openrazer-driver-dkms-local": "openrazer-kernel-modules-dkms",
    "openrazer-daemon-local": "openrazer-daemon",
    "python-openrazer-local": "python3-openrazer",
}


def package_version(pin: dict[str, str]) -> str:
    """Return cohort version as <pkgver>-<pkgrel>."""
    return f"{pin['OPENRAZER_PKGVER']}-{pin['OPENRAZER_PKGREL']}"


def python_next(minor: str) -> str:
    """Return next minor bound for ``3.N`` (e.g. ``3.10`` -> ``3.11``)."""
    generation, _, patch = minor.partition(".")
    return f"{generation}.{int(patch) + 1}"


def deb_filename(role: str, version: str) -> str:
    """Return canonical Debian filename for a local role."""
    return f"{role}_{version}_all.deb"


def rpm_filename(role: str, version: str) -> str:
    """Return canonical RPM filename for a local role."""
    return f"{role}-{version}.noarch.rpm"


def expected_filenames(family: str, pin: dict[str, str]) -> tuple[str, ...]:
    """Return the exact three output basenames for a family."""
    version = package_version(pin)
    if family == "debian":
        return tuple(deb_filename(role, version) for role in LOCAL_ROLES)
    if family in ("fedora", "opensuse"):
        return tuple(rpm_filename(role, version) for role in LOCAL_ROLES)
    raise ValueError(f"Unsupported family: {family}")


def debian_depends(role: str, version: str, minor: str) -> str:
    """Return Debian Depends evidence from pinned debian/control."""
    nxt = python_next(minor)
    if role == "openrazer-driver-dkms-local":
        return "dkms, udev"
    if role == "openrazer-daemon-local":
        return (
            f"openrazer-driver-dkms-local (= {version}), "
            f"python3 (>= {minor}), python3 (<< {nxt}), "
            "python3-dbus, python3-gi, python3-pyudev, "
            "python3-setproctitle, python3-daemonize (>= 2.4.7), "
            "gir1.2-glib-2.0, libnotify-bin, xautomation, dbus-session-bus"
        )
    if role == "python-openrazer-local":
        return (
            f"openrazer-daemon-local (= {version}), "
            f"python3 (>= {minor}), python3 (<< {nxt}), "
            "python3-dbus, python3-gi, python3-numpy"
        )
    raise ValueError(f"Unknown role: {role}")


def rpm_requires(family: str, role: str, version: str, minor: str) -> list[str]:
    """Return RPM Requires evidence from the official OBS reference spec."""
    if family not in ("fedora", "opensuse"):
        raise ValueError(f"Unsupported RPM family: {family}")
    nxt = python_next(minor)
    if role == "openrazer-driver-dkms-local":
        group_tool = "shadow-utils" if family == "fedora" else "shadow"
        return ["dkms", "make", "udev", group_tool]
    if role == "openrazer-daemon-local":
        dbus_req = "python3-dbus" if family == "fedora" else "dbus-1-python3"
        requires = [
            f"openrazer-driver-dkms-local = {version}",
            f"python3 >= {minor}",
            f"python3 < {nxt}",
            dbus_req,
            "python3-gobject",
            "python3-setproctitle",
            "python3-pyudev",
            "python3-daemonize",
            "xautomation",
        ]
        if family == "opensuse":
            requires.append("typelib(Gdk) = 3.0")
        return requires
    if role == "python-openrazer-local":
        dbus_req = "python3-dbus" if family == "fedora" else "dbus-1-python3"
        return [
            f"openrazer-daemon-local = {version}",
            f"python3 >= {minor}",
            f"python3 < {nxt}",
            dbus_req,
            "python3-gobject",
            "python3-numpy",
        ]
    raise ValueError(f"Unknown role: {role}")


def upstream_name(family: str, role: str) -> str:
    """Return the upstream counterpart for Provides/Conflicts handling."""
    if family == "debian":
        return UPSTREAM_DEB[role]
    if family in ("fedora", "opensuse"):
        return UPSTREAM_RPM[role]
    raise ValueError(f"Unsupported family: {family}")


def deb_control(role: str, version: str, minor: str) -> str:
    """Return DEBIAN/control content for a Debian package."""
    upstream = UPSTREAM_DEB[role]
    depends = debian_depends(role, version, minor)
    lines = [
        f"Package: {role}",
        f"Version: {version}",
        "Architecture: all",
        "Maintainer: naga-control-local <local@example.invalid>",
        f"Depends: {depends}",
        f"Provides: {upstream}",
        f"Conflicts: {upstream}",
        f"Replaces: {upstream}",
        f"Description: Local OpenRazer {role} (pinned Naga V3 Pro baseline)",
        " Private local build from the pinned source; see source-commit stamp.",
    ]
    return "\n".join(lines) + "\n"


def deb_postinst(role: str, pkgver: str) -> str:
    """Return DEBIAN/postinst as data (never executed by the builder)."""
    header = "#!/bin/sh\nset -e\n"
    if role == "openrazer-driver-dkms-local":
        return (
            header
            + "getent group openrazer >/dev/null || groupadd -r openrazer\n"
            + 'if [ "$1" = configure ]; then\n'
            + f"  dkms install {DKMS_NAME}/{pkgver}\n"
            + "fi\n"
        )
    return header + "exit 0\n"


def deb_prerm(role: str, pkgver: str) -> str:
    """Return DEBIAN/prerm as data with remove-vs-upgrade guards."""
    header = "#!/bin/sh\nset -e\n"
    if role == "openrazer-driver-dkms-local":
        return (
            header
            + 'if [ "$1" = "remove" ]; then\n'
            + f"  dkms remove -m {DKMS_NAME} -v {pkgver} --all\n"
            + "fi\n"
        )
    return header + "exit 0\n"


def rpm_spec(family: str, version: str, minor: str, pkgver: str) -> str:
    """Return the owned static RPM spec template (no Source0 network)."""
    nxt = python_next(minor)
    driver_up = UPSTREAM_RPM["openrazer-driver-dkms-local"]
    daemon_up = UPSTREAM_RPM["openrazer-daemon-local"]
    client_up = UPSTREAM_RPM["python-openrazer-local"]
    group_req = "shadow-utils" if family == "fedora" else "shadow"
    dbus_req = "python3-dbus" if family == "fedora" else "dbus-1-python3"
    pylib = f"/usr/lib/python{minor}/site-packages"
    lines: list[str] = [
        f"# Owned static template for {family}; no Source0 network fetch.",
        f"# Cohort {version}; DKMS {DKMS_NAME}-{pkgver}; Python {minor}.",
        "# No debuginfo/debugsource: noarch DKMS source plus Python, no ELF to strip.",
        "%global debug_package %{nil}",
        "Name: openrazer-local",
        f"Version: {pkgver}",
        "Release: 1",
        "Summary: Local OpenRazer pinned Naga V3 Pro baseline",
        "License: GPL-2.0-or-later",
        "BuildArch: noarch",
        "",
        "%description",
        "Private local build from the pinned source; see source-commit stamp.",
        "",
        "%package -n openrazer-driver-dkms-local",
        "Summary: Local OpenRazer driver (DKMS source)",
        f"Provides: {driver_up}",
        f"Conflicts: {driver_up}",
        f"Obsoletes: {driver_up}",
        "Requires: dkms",
        "Requires: make",
        "Requires: udev",
        f"Requires(pre): {group_req}",
        "%description -n openrazer-driver-dkms-local",
        "Local driver source for DKMS builds.",
        "",
        "%package -n openrazer-daemon-local",
        "Summary: Local OpenRazer daemon",
        f"Provides: {daemon_up}",
        f"Conflicts: {daemon_up}",
        f"Obsoletes: {daemon_up}",
        f"Requires: openrazer-driver-dkms-local = {version}",
        f"Requires: python3 >= {minor}",
        f"Requires: python3 < {nxt}",
        f"Requires: {dbus_req}",
        "Requires: python3-gobject",
        "Requires: python3-setproctitle",
        "Requires: python3-pyudev",
        "Requires: python3-daemonize",
        "Requires: xautomation",
    ]
    if family == "opensuse":
        lines.append("Requires: typelib(Gdk) = 3.0")
    lines.extend(
        [
            "%description -n openrazer-daemon-local",
            "Local userspace daemon.",
            "",
            "%package -n python-openrazer-local",
            "Summary: Local OpenRazer Python library",
            f"Provides: {client_up}",
            f"Conflicts: {client_up}",
            f"Obsoletes: {client_up}",
            f"Requires: openrazer-daemon-local = {version}",
            f"Requires: python3 >= {minor}",
            f"Requires: python3 < {nxt}",
            f"Requires: {dbus_req}",
            "Requires: python3-gobject",
            "Requires: python3-numpy",
            "%description -n python-openrazer-local",
            "Local Python client library.",
            "",
            "%prep",
            "# noop: staged payload is already prepared by the builder.",
            "",
            "%build",
            "# noop: DKMS modules build at install time via dkms.",
            "",
            "%install",
            "mkdir -p $RPM_BUILD_ROOT",
            "cp -a %{stagedir}/* $RPM_BUILD_ROOT/",
            "",
            "%pre -n openrazer-driver-dkms-local",
            "#!/bin/sh",
            "set -e",
            "getent group openrazer >/dev/null || groupadd -r openrazer",
            "",
            "%posttrans -n openrazer-driver-dkms-local",
            "#!/bin/sh",
            "set -e",
            f"dkms install {DKMS_NAME}/{pkgver}",
            "",
            "%preun -n openrazer-driver-dkms-local",
            "#!/bin/sh",
            "set -e",
            'if [ "$1" = 0 ]; then',
            f"  dkms remove -m {DKMS_NAME} -v {pkgver} --all",
            "fi",
            "",
            "%files -n openrazer-driver-dkms-local",
            "%defattr(-,root,root,-)",
            f"/usr/src/{DKMS_NAME}-{pkgver}/",
            "/usr/lib/udev/rules.d/99-razer.rules",
            "/usr/lib/udev/razer_mount",
            "/usr/share/metainfo/io.github.openrazer.openrazer.metainfo.xml",
            "/usr/share/doc/openrazer-driver-dkms-local/",
            "",
            "%files -n openrazer-daemon-local",
            "%defattr(-,root,root,-)",
            "/usr/bin/openrazer-daemon",
            "/usr/share/openrazer/razer.conf.example",
            "/usr/share/dbus-1/services/org.razer.service",
            "/usr/lib/systemd/user/openrazer-daemon.service",
            "/usr/share/man/man5/razer.conf.5.gz",
            "/usr/share/man/man8/openrazer-daemon.8.gz",
            f"{pylib}/openrazer_daemon/",
            f"{pylib}/openrazer_daemon-*.egg-info/",
            "/usr/share/doc/openrazer-daemon-local/",
            "",
            "%files -n python-openrazer-local",
            "%defattr(-,root,root,-)",
            f"{pylib}/openrazer/",
            f"{pylib}/openrazer-*.egg-info/",
            "/usr/share/doc/python-openrazer-local/",
        ]
    )
    return "\n".join(lines) + "\n"


def audit_deb_control(text: str, role: str, version: str, minor: str) -> None:
    """Audit generated DEBIAN/control content before packaging."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith(" "):
            continue
        if ": " not in line:
            raise ValueError("Malformed Debian control")
        key, value = line.split(": ", 1)
        fields[key] = value
    if fields.get("Package") != role or fields.get("Version") != version:
        raise ValueError("Debian control package/version mismatch")
    if fields.get("Architecture") != "all":
        raise ValueError("Debian control architecture must be all")
    for key in ("Provides", "Conflicts", "Replaces"):
        if fields.get(key) != UPSTREAM_DEB[role]:
            raise ValueError(f"Debian control {key} must be the upstream role only")
    depends = fields.get("Depends", "")
    if role == "openrazer-driver-dkms-local":
        if depends != "dkms, udev":
            raise ValueError("Driver Debian dependencies mismatch")
    elif role in ("openrazer-daemon-local", "python-openrazer-local"):
        link = (
            "openrazer-driver-dkms-local"
            if role == "openrazer-daemon-local"
            else "openrazer-daemon-local"
        )
        if f"{link} (= {version})" not in depends:
            raise ValueError("Debian cohort link mismatch")
        if f"python3 (>= {minor})" not in depends:
            raise ValueError("Debian Python floor mismatch")
        if f"python3 (<< {python_next(minor)})" not in depends:
            raise ValueError("Debian Python ceiling mismatch")
    else:
        raise ValueError(f"Unknown role: {role}")
