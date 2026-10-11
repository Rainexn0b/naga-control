"""Read-only archive audits for built native packages."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

from . import recipes, rpm_audit
from .validation import ByteRunner, Runner, audit_script_text, check_safe_relpath

_MAX_BYTES = 32 * 1024 * 1024
_MAX_ENTRIES = 8192


def audit_member_listing(
    lines: list[str], role: str, family: str, minor: str, rpm: bool
) -> set[str]:
    files: set[str] = set()
    dirs: set[str] = set()
    for line in lines:
        if rpm and not line.strip():
            continue
        parts = line.split()
        if len(parts) < 6 or len(parts[0]) < 10:
            raise ValueError("Malformed package listing")
        perms, member = parts[0], parts[-1]
        if perms[0] not in ("-", "d"):
            raise ValueError("Package payload must not contain special file types")
        if "->" in line:
            raise ValueError("Package payload must not contain symlinks")
        if perms[3].lower() == "s" or perms[6].lower() == "s":
            raise ValueError("Package payload must not contain setuid/setgid")
        if rpm:
            if len(parts) < 9 or parts[2] != "root" or parts[3] != "root":
                raise ValueError("RPM payload ownership must be root/root")
            if member != "/usr" and not member.startswith("/usr/"):
                raise ValueError("RPM payload must stay under /usr")
        elif parts[1] != "root/root":
            raise ValueError("Deb payload ownership must be root/root")
        elif member != "./" and not member.startswith("./usr/"):
            raise ValueError("Deb payload must stay under /usr")
        norm = member.removeprefix("./").removeprefix("/").removesuffix("/")
        if norm == "":
            if perms[0] != "d" or "" in dirs:
                raise ValueError("Invalid or duplicate package root entry")
            dirs.add("")
            continue
        if perms[0] == "d":
            if norm in dirs or norm in files:
                raise ValueError("Duplicate package directory or collision")
            check_safe_relpath(member, dirs)
            continue
        if norm in files or norm in dirs:
            raise ValueError("Duplicate package file or collision")
        cleaned = check_safe_relpath(member, files)
        if cleaned.rsplit("/", 1)[-1] in (".PKGINFO", ".BUILDINFO"):
            raise ValueError("Native package must not carry Arch sidecars")
        if "etc/xdg/autostart" in cleaned or "/tests/" in cleaned or "_fake_driver" in cleaned:
            raise ValueError("Package payload must exclude activation/tests/fake driver")
    if f"usr/share/doc/{role}/source-commit" not in files:
        raise ValueError("Package payload lacks source stamp")
    base = (
        "usr/lib/python3/dist-packages/"
        if family == "debian"
        else f"usr/lib/python{minor}/site-packages/"
    )
    if role != "openrazer-driver-dkms-local":
        want = base + (
            "openrazer_daemon/__init__.py"
            if role == "openrazer-daemon-local"
            else "openrazer/__init__.py"
        )
        if want not in files:
            raise ValueError("Package lacks exact module __init__ at declared minor")
        dist = "openrazer_daemon" if role == "openrazer-daemon-local" else "openrazer"
        want_egg = base + rpm_audit.egg_info_dir(dist, minor) + "/"
        if not any(m == want_egg.rstrip("/") or m.startswith(want_egg) for m in files):
            raise ValueError("Package lacks exact egg-info tree at declared minor")
        allowed_prefix = base + dist + "/"
        allowed_egg = want_egg
        for m in files:
            if not m.startswith("usr/lib/python"):
                continue
            if m.startswith(allowed_prefix) or m.startswith(allowed_egg):
                if m.startswith(allowed_egg):
                    leaf = m.rsplit("/", 1)[-1]
                    if leaf not in rpm_audit.EGG_FILES and m != allowed_egg.rstrip("/"):
                        raise ValueError("Unexpected egg-info payload file")
                continue
            raise ValueError("Foreign Python payload path")
    elif any(m.startswith("usr/lib/python") for m in files):
        raise ValueError("Driver payload must not carry Python modules")
    return files


def parse_deb_data_tar(data: bytes, role: str, commit: str, pkgver: str) -> set[str]:
    if not data or len(data) > _MAX_BYTES:
        raise ValueError("Invalid Deb data tar size")
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
            infos = tar.getmembers()
            if len(infos) > _MAX_ENTRIES:
                raise ValueError("Deb data tar has too many members")
            files: set[str] = set()
            dirs: set[str] = set()
            want_exec: set[str] = set()
            if role == "openrazer-driver-dkms-local":
                want_exec = {
                    f"usr/src/{recipes.DKMS_NAME}-{pkgver}/dkms-make",
                    "usr/lib/udev/razer_mount",
                }
            elif role == "openrazer-daemon-local":
                want_exec = {"usr/bin/openrazer-daemon"}
            for info in infos:
                norm = info.name.removeprefix("./").removeprefix("/").removesuffix("/")
                if norm == ".":
                    norm = ""
                if norm == "":
                    if not info.isdir() or "" in dirs:
                        raise ValueError("Invalid or duplicate Deb root entry")
                    dirs.add("")
                    continue
                if info.issym() or info.islnk() or info.isblk() or info.ischr() or info.isfifo():
                    raise ValueError("Deb payload must not contain special files")
                if not info.isreg() and not info.isdir():
                    raise ValueError("Deb payload has unsupported member type")
                if info.uid != 0 or info.gid != 0:
                    raise ValueError("Deb payload ownership must be root/root")
                mode = info.mode & 0o7777
                if mode & 0o6000:
                    raise ValueError("Deb payload must not contain setuid/setgid")
                if info.isdir():
                    if norm in dirs or norm in files or mode != 0o755:
                        raise ValueError("Invalid Deb directory entry")
                    dirs.add(norm)
                    continue
                if norm in files or norm in dirs:
                    raise ValueError("Duplicate Deb file or collision")
                if not norm.startswith("usr/"):
                    raise ValueError("Deb payload must stay under /usr")
                if (norm in want_exec and mode != 0o755) or (
                    norm not in want_exec and mode != 0o644
                ):
                    raise ValueError("Deb file mode must be 0644 (0755 for helpers)")
                files.add(norm)
                if norm.rsplit("/", 1)[-1] in (".PKGINFO", ".BUILDINFO"):
                    raise ValueError("Native Deb must not carry Arch sidecars")
            want = f"usr/share/doc/{role}/source-commit"
            if want not in files:
                raise ValueError("Deb data lacks source stamp")
            for info in infos:
                if info.name.removeprefix("./").removeprefix("/") == want:
                    extracted = tar.extractfile(info)
                    if extracted is None or not info.isreg():
                        raise ValueError("Unable to read Deb stamp")
                    if extracted.read().decode("ascii") != commit + "\n":
                        raise ValueError("Deb stamp does not match pin")
                    break
            else:
                raise ValueError("Deb data lacks source stamp")
            return files
    except (tarfile.TarError, UnicodeDecodeError) as error:
        raise ValueError(f"Invalid Deb data tar: {error}") from error


def parse_deb_control_tar(data: bytes, role: str, version: str, minor: str, pkgver: str) -> None:
    if not data or len(data) > 1024 * 1024:
        raise ValueError("Invalid Deb control tar size")
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
            infos = tar.getmembers()
            if len(infos) > 64:
                raise ValueError("Deb control tar has too many members")
            seen: set[str] = set()
            for info in infos:
                norm = info.name.removeprefix("./").removeprefix("/").removesuffix("/")
                if norm == ".":
                    norm = ""
                if norm == "":
                    if not info.isdir() or "" in seen:
                        raise ValueError("Invalid or duplicate control root entry")
                    if info.uid != 0 or info.gid != 0 or (info.mode & 0o7777) != 0o755:
                        raise ValueError("Invalid control root entry")
                    seen.add("")
                    continue
                if info.issym() or info.islnk() or info.isblk() or info.ischr() or info.isfifo():
                    raise ValueError("Deb control tar must not contain special files")
                if not info.isreg() or info.uid != 0 or info.gid != 0:
                    raise ValueError("Invalid Deb control tar member")
                if info.mode & 0o6000:
                    raise ValueError("Deb control tar must not contain setuid/setgid")
                if norm in seen:
                    raise ValueError("Duplicate Deb control tar member")
                seen.add(norm)
            names = seen - {""}
            if not {"control", "postinst", "prerm"} <= names:
                raise ValueError("Deb control tar lacks control/scriptlets")
            if names - {"control", "md5sums", "postinst", "prerm"}:
                raise ValueError("Deb control tar has unexpected members")
            control = tar.extractfile(
                next(
                    m
                    for m in tar.getmembers()
                    if m.name.removeprefix("./").removeprefix("/") == "control"
                )
            )
            if control is None:
                raise ValueError("Unable to read Deb control")
            recipes.audit_deb_control(control.read().decode("ascii"), role, version, minor)
            for script in ("postinst", "prerm"):
                member = next(
                    m
                    for m in tar.getmembers()
                    if m.name.removeprefix("./").removeprefix("/") == script
                )
                if not member.isreg() or (member.mode & 0o777) != 0o755:
                    raise ValueError("Deb scriptlet must be executable 0755")
                script_file = tar.extractfile(member)
                if script_file is None:
                    raise ValueError(f"Unable to read Deb {script}")
                audit_script_text(role, script_file.read().decode("ascii"), pkgver)
    except (tarfile.TarError, UnicodeDecodeError, ValueError) as error:
        if isinstance(error, ValueError):
            raise
        raise ValueError(f"Invalid Deb control tar: {error}") from error


def _deb_field(path: Path, field: str, runner: Runner) -> str:
    result = runner(["dpkg-deb", "-f", str(path), field], None)
    if result.returncode != 0:
        raise ValueError(f"Unable to read Deb field: {field}")
    return result.stdout.strip()


def audit_deb_file(
    path: Path,
    role: str,
    version: str,
    minor: str,
    pin: dict[str, str],
    runner: Runner,
    byte_runner: ByteRunner,
) -> set[str]:
    if path.name != recipes.deb_filename(role, version):
        raise ValueError("Deb filename does not match cohort")
    pkgver, commit = pin["OPENRAZER_PKGVER"], pin["OPENRAZER_COMMIT"]
    if _deb_field(path, "Package", runner) != role:
        raise ValueError("Deb Package field mismatch")
    if _deb_field(path, "Version", runner) != version:
        raise ValueError("Deb Version field mismatch")
    if _deb_field(path, "Architecture", runner) != "all":
        raise ValueError("Deb Architecture must be all")
    if _deb_field(path, "Depends", runner) != recipes.debian_depends(role, version, minor):
        raise ValueError("Deb Depends set mismatch")
    for field in ("Provides", "Conflicts", "Replaces"):
        if _deb_field(path, field, runner) != recipes.UPSTREAM_DEB[role]:
            raise ValueError(f"Deb {field} must be the upstream role only")
    listing = runner(["dpkg-deb", "-c", str(path)], None)
    if listing.returncode != 0:
        raise ValueError("Unable to list Deb payload")
    members = audit_member_listing(listing.stdout.splitlines(), role, "debian", minor, False)
    raw = byte_runner(["dpkg-deb", "--fsys-tarfile", str(path)], None)
    if raw.returncode != 0:
        raise ValueError("Unable to read Deb data tar")
    tar_members = parse_deb_data_tar(raw.stdout, role, commit, pkgver)
    if members != tar_members:
        raise ValueError("Deb listing and data tar filesets disagree")
    ctrl = byte_runner(["dpkg-deb", "--ctrl-tarfile", str(path)], None)
    if ctrl.returncode != 0:
        raise ValueError("Unable to read Deb control tar")
    parse_deb_control_tar(ctrl.stdout, role, version, minor, pkgver)
    return members


def audit_rpm_file(
    path: Path,
    role: str,
    family: str,
    version: str,
    minor: str,
    pkgver: str,
    pin: dict[str, str],
    runner: Runner,
    byte_runner: ByteRunner,
) -> set[str]:
    if path.name != recipes.rpm_filename(role, version):
        raise ValueError("RPM filename does not match cohort")
    commit = pin["OPENRAZER_COMMIT"]
    if rpm_audit.rpm_query(path, ["--queryformat", "%{NAME}"], runner) != role:
        raise ValueError("RPM Name mismatch")
    if rpm_audit.rpm_query(path, ["--queryformat", "%{VERSION}"], runner) != pkgver:
        raise ValueError("RPM Version mismatch")
    if rpm_audit.rpm_query(path, ["--queryformat", "%{RELEASE}"], runner) != "1":
        raise ValueError("RPM Release must be 1")
    if rpm_audit.rpm_query(path, ["--queryformat", "%{ARCH}"], runner) != "noarch":
        raise ValueError("RPM Architecture must be noarch")
    requires = {
        line.strip()
        for line in rpm_audit.rpm_query(path, ["--requires"], runner).splitlines()
        if line.strip()
    }
    rpm_audit.check_requires(requires, family, role, version, minor)
    provides = {
        line.strip()
        for line in rpm_audit.rpm_query(path, ["--provides"], runner).splitlines()
        if line.strip()
    }
    rpm_audit.check_provides(provides, role, family, minor, version)
    for flag, label in ((["--conflicts"], "Conflicts"), (["--obsoletes"], "Obsoletes")):
        values = {
            line.strip()
            for line in rpm_audit.rpm_query(path, flag, runner).splitlines()
            if line.strip()
        }
        rpm_audit.check_conflicts_obsoletes(values, role, label)
    raw_list = runner(["rpm", "-qplv", "--", str(path)], None)
    if raw_list.returncode != 0:
        raise ValueError("Unable to list RPM payload")
    members = audit_member_listing(raw_list.stdout.splitlines(), role, family, minor, True)
    raw = byte_runner(["rpm2cpio", str(path)], None)
    if raw.returncode != 0:
        raise ValueError("Unable to read RPM payload")
    parsed = rpm_audit.cpio_parse_all(raw.stdout)
    if members != set(parsed):
        raise ValueError("RPM listing and payload filesets disagree")
    want = f"usr/share/doc/{role}/source-commit"
    if want not in parsed or parsed[want].decode("ascii") != commit + "\n":
        raise ValueError("RPM stamp does not match pin")
    scripts = rpm_audit.rpm_query(path, ["--scripts"], runner)
    triggers = rpm_audit.rpm_query(path, ["--triggers"], runner)
    rpm_audit.check_scripts(scripts, triggers, role, pkgver)
    return members
