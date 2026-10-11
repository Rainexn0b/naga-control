"""Orchestrate verified source copy, staging, packaging, audit, manifest."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from . import payload, recipes
from .archive_audit import audit_deb_file, audit_rpm_file
from .validation import (
    ByteRunner,
    Runner,
    audit_payload_stages,
    audit_script_text,
    check_family,
    check_not_root,
    current_python_minor,
    default_byte_runner,
    default_runner,
    read_and_check_pin,
    verify_output_dir,
    verify_source,
)


def parse_sidecar(text: str, expected: tuple[str, ...]) -> dict[str, str]:
    """Parse the canonical 3-row sha256 sidecar."""
    checksums: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._+-]*)", line)
        if match is None or match[2] not in expected or match[2] in checksums:
            raise ValueError("Invalid native checksum sidecar")
        checksums[match[2]] = match[1]
    if set(checksums) != set(expected):
        raise ValueError("Incomplete native checksum sidecar")
    return checksums


def check_no_overlap(groups: Sequence[set[str]]) -> None:
    seen: set[str] = set()
    for members in groups:
        overlap = seen & members
        if overlap:
            raise ValueError(f"Overlapping cohort files: {sorted(overlap)[0]}")
        seen |= members


def _publish_bytes(dest: Path, data: bytes, created: list[Path]) -> tuple[int, int]:
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        owned = os.fstat(fd)
    except OSError:
        with contextlib.suppress(OSError):
            os.close(fd)
        raise
    owned_id = (owned.st_dev, owned.st_ino)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except BaseException:
        with contextlib.suppress(OSError):
            _unlink_owned(dest, owned_id)
        raise
    created.append(dest)
    return owned_id


def _unlink_owned(dest: Path, owned_id: tuple[int, int]) -> None:
    try:
        current = dest.lstat()
    except OSError:
        return
    if not stat.S_ISREG(current.st_mode):
        return
    if (current.st_dev, current.st_ino) != owned_id:
        return
    with contextlib.suppress(OSError):
        dest.unlink()


def _publish_text(dest: Path, text: str, created: list[Path]) -> tuple[int, int]:
    return _publish_bytes(dest, text.encode("ascii"), created)


def _publish_copy(src: Path, dest: Path, created: list[Path]) -> tuple[int, int]:
    with src.open("rb") as handle:
        data = handle.read()
    return _publish_bytes(dest, data, created)


def sha256_file(path: Path) -> str:
    """Return hex sha256 without requiring 3.11 file_digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stage_files(stage: Path) -> set[str]:
    members: set[str] = set()
    for item in stage.rglob("*"):
        if item.is_symlink() or not item.is_file():
            continue
        rel = item.relative_to(stage).as_posix()
        if rel.startswith("DEBIAN/"):
            continue
        members.add(rel)
    return members


def _write_debian_package_dir(stage: Path, role: str, version: str, minor: str) -> None:
    pkgver = version.rsplit("-", 1)[0]
    control = recipes.deb_control(role, version, minor)
    recipes.audit_deb_control(control, role, version, minor)
    postinst = recipes.deb_postinst(role, pkgver)
    prerm = recipes.deb_prerm(role, pkgver)
    audit_script_text(role, postinst, pkgver)
    audit_script_text(role, prerm, pkgver)
    debian_dir = stage / "DEBIAN"
    debian_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(debian_dir, 0o755)
    control_path = debian_dir / "control"
    control_path.write_text(control, encoding="ascii")
    os.chmod(control_path, 0o644)
    for name, text in (("postinst", postinst), ("prerm", prerm)):
        target = debian_dir / name
        target.write_text(text, encoding="ascii")
        os.chmod(target, 0o755)


def _audit_spec_text(spec: str, family: str, version: str, minor: str, pkgver: str) -> None:
    lowered = spec.lower()
    for fragment in recipes.FORBIDDEN_SCRIPT_FRAGMENTS:
        if fragment.lower() in lowered:
            raise ValueError(f"Spec contains forbidden fragment: {fragment}")
    if "|| true" in spec or "|| :" in spec:
        raise ValueError("Spec must not mask DKMS failures")
    if "source0:" in lowered and "http" in lowered:
        raise ValueError("Spec must not fetch Source0 over network")
    if "getent group openrazer" not in spec or "groupadd -r openrazer" not in spec:
        raise ValueError("Spec must create the openrazer group")
    if f"dkms install {recipes.DKMS_NAME}/{pkgver}" not in spec:
        raise ValueError("Spec must install the matching DKMS version")
    if f"dkms remove -m {recipes.DKMS_NAME} -v {pkgver} --all" not in spec:
        raise ValueError("Spec must remove the matching DKMS version")
    if '"$1" = 0' not in spec:
        raise ValueError("Spec must guard RPM transactions with $1")
    for need in ("dkms", "make", "udev"):
        if need not in lowered:
            raise ValueError(f"Spec lacks driver requirement: {need}")


def build_native_packages(
    family: str,
    source: Path,
    output: Path,
    pin_path: Path,
    euid: int,
    runner: Runner = default_runner,
    byte_runner: ByteRunner = default_byte_runner,
) -> dict[str, object]:
    """Build, audit, and publish the exact three-file cohort plus manifest."""
    check_not_root(euid)
    check_family(family)
    pin = read_and_check_pin(pin_path)
    minor = current_python_minor()
    verify_output_dir(output, source, euid)
    verify_source(source, pin, runner)
    version = recipes.package_version(pin)
    pkgver = pin["OPENRAZER_PKGVER"]
    expected = recipes.expected_filenames(family, pin)
    created: list[Path] = []
    owned: dict[Path, tuple[int, int]] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="openrazer-native-") as tmp:
            workdir = Path(tmp)
            os.chmod(workdir, 0o700)
            copy_root = workdir / "source-copy"
            payload.copy_source_tree(source, copy_root)
            payload.apply_group_transform(copy_root)
            dkms_src = payload.find_dkms_make_src()
            stages = payload.prepare_stages(
                copy_root, workdir, family, minor, pin, dkms_src, runner
            )
            audit_payload_stages(stages, family, pin, minor)
            check_no_overlap([_stage_files(stage) for stage in stages.values()])
            built: list[Path] = []
            if family == "debian":
                for role, filename in zip(recipes.LOCAL_ROLES, expected, strict=True):
                    stage = stages[role]
                    _write_debian_package_dir(stage, role, version, minor)
                    target = workdir / filename
                    result = runner(
                        ["dpkg-deb", "--root-owner-group", "--build", str(stage), str(target)],
                        None,
                    )
                    if result.returncode != 0:
                        raise ValueError(f"dpkg-deb failed for {role}: {result.stderr.strip()}")
                    if not target.is_file() or target.is_symlink():
                        raise ValueError(f"Missing built package: {filename}")
                    built.append(target)
                members_list: list[set[str]] = []
                for role, target in zip(recipes.LOCAL_ROLES, built, strict=True):
                    members_list.append(
                        audit_deb_file(target, role, version, minor, pin, runner, byte_runner)
                    )
                check_no_overlap(members_list)
                for role, stage, members in zip(
                    recipes.LOCAL_ROLES, stages.values(), members_list, strict=True
                ):
                    if _stage_files(stage) != members:
                        raise ValueError(f"Deb payload incomplete for {role}")
            else:
                merged = workdir / "merged"
                merged.mkdir(parents=True, exist_ok=False)
                for stage in stages.values():
                    shutil.copytree(stage, merged, symlinks=True, dirs_exist_ok=True)
                spec = recipes.rpm_spec(family, version, minor, pkgver)
                _audit_spec_text(spec, family, version, minor, pkgver)
                topdir = workdir / "rpm-top"
                for sub in ("BUILD", "RPMS", "SOURCES", "SPECS", "SRPMS"):
                    (topdir / sub).mkdir(parents=True, exist_ok=True)
                tmppath = workdir / "rpm-tmp"
                tmppath.mkdir(mode=0o700, parents=True, exist_ok=True)
                os.chmod(tmppath, 0o700)
                spec_path = topdir / "SPECS" / "openrazer-local.spec"
                spec_path.write_text(spec, encoding="ascii")
                result = runner(
                    [
                        "rpmbuild",
                        "-bb",
                        "--define",
                        f"_topdir {topdir}",
                        "--define",
                        f"_tmppath {tmppath}",
                        "--define",
                        f"stagedir {merged}",
                        "--",
                        str(spec_path),
                    ],
                    None,
                )
                if result.returncode != 0:
                    raise ValueError(f"rpmbuild failed: {result.stderr.strip()}")
                rpmdir = topdir / "RPMS" / "noarch"
                try:
                    actual_rpms = sorted(p.name for p in rpmdir.iterdir() if p.is_file())
                except OSError as error:
                    raise ValueError(f"Unable to list built RPMS: {error}") from error
                if set(actual_rpms) != set(expected):
                    raise ValueError("RPM build must produce exactly the three cohort RPMS")
                for _role, filename in zip(recipes.LOCAL_ROLES, expected, strict=True):
                    candidate = rpmdir / filename
                    if candidate.is_symlink() or not candidate.is_file():
                        raise ValueError(f"Missing built RPM: {filename}")
                    built.append(candidate)
                members_list: list[set[str]] = []
                for role, target in zip(recipes.LOCAL_ROLES, built, strict=True):
                    members_list.append(
                        audit_rpm_file(
                            target, role, family, version, minor, pkgver, pin, runner, byte_runner
                        )
                    )
                check_no_overlap(members_list)
                merged_files = {
                    p.relative_to(merged).as_posix()
                    for p in merged.rglob("*")
                    if p.is_file() and not p.is_symlink()
                }
                packaged: set[str] = set()
                for members in members_list:
                    packaged |= members
                missing = merged_files - packaged
                if missing:
                    raise ValueError(f"RPM payload omits staged files: {sorted(missing)[0]}")
                for extra in packaged - merged_files:
                    if "/__pycache__/" not in extra and not extra.endswith((".pyc", ".pyo")):
                        raise ValueError(f"RPM payload has unexpected file: {extra}")
            for src, name in zip(built, expected, strict=True):
                shutil.copy2(src, workdir / f"final-{name}")
            checksums = {name: sha256_file(workdir / f"final-{name}") for name in expected}
            sidecar_lines = "".join(f"{checksums[name]}  {name}\n" for name in expected)
            parse_sidecar(sidecar_lines, expected)
            manifest: dict[str, object] = {
                "schema": recipes.SCHEMA_VERSION,
                "source_commit": pin["OPENRAZER_COMMIT"],
                "family": family,
                "version": version,
                "python_minor": minor,
                "packages": [
                    {"role": role, "filename": name, "sha256": checksums[name]}
                    for role, name in zip(recipes.LOCAL_ROLES, expected, strict=True)
                ],
            }
            manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            parsed = json.loads(manifest_text)
            if parsed != manifest:
                raise ValueError("Manifest round-trip mismatch")
            for src, name in zip(built, expected, strict=True):
                owned[output / name] = _publish_copy(src, output / name, created)
            for sidecar_name, sidecar_text in (
                (recipes.SIDECAR_NAME, sidecar_lines),
                (recipes.MANIFEST_NAME, manifest_text),
            ):
                owned[output / sidecar_name] = _publish_text(
                    output / sidecar_name, sidecar_text, created
                )
            return manifest
    except Exception:
        for known in created:
            try:
                expected_id = owned.get(known)
                if expected_id is None:
                    continue
                current = known.lstat()
                if not stat.S_ISREG(current.st_mode):
                    continue
                if (current.st_dev, current.st_ino) != expected_id:
                    continue
                known.unlink()
            except OSError:
                pass
        raise


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry used by __main__ (stdlib only, no app imports)."""
    import argparse

    parser = argparse.ArgumentParser(description="Build local native OpenRazer packages.")
    parser.add_argument("--family", required=True, choices=list(recipes.SUPPORTED_FAMILIES))
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pin", required=False, type=Path, default=None)
    args = parser.parse_args(argv)
    default_pin = Path(__file__).resolve().parent.parent / "openrazer_packages" / "pin.conf"
    pin_path: Path = args.pin if args.pin is not None else default_pin
    try:
        manifest = build_native_packages(
            args.family,
            args.source,
            args.output,
            pin_path,
            os.geteuid(),
            default_runner,
            default_byte_runner,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
