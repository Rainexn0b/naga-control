"""Validate release assets or prepare and validate the pinned Arch package sidecar."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buildpython.openrazer_packages.pin import package_filenames, read_pin
from buildpython.openrazer_packages.validation import (
    SIDECAR,
    parse_checksums,
    sha256,
    validate_packages,
)

APPIMAGE = "Naga-Control-x86_64.AppImage"


def validate_release_assets(directory: Path, pin_path: Path) -> tuple[Path, ...]:
    packages = validate_packages(directory, read_pin(pin_path))
    sidecar = directory / (APPIMAGE + ".sha256")
    checksums = parse_checksums(sidecar.read_text(encoding="ascii"), (APPIMAGE,))
    image = directory / APPIMAGE
    if image.is_symlink() or not image.is_file() or image.stat().st_size == 0:
        raise ValueError("Missing or unsafe AppImage")
    if sha256(image) != checksums[APPIMAGE]:
        raise ValueError("AppImage checksum mismatch")
    assets = (image, sidecar, *packages)
    if {path.name for path in directory.iterdir()} != {path.name for path in assets}:
        raise ValueError("Release directory must contain exactly the complete six-asset set")
    if any(path.is_symlink() or not path.is_file() for path in assets):
        raise ValueError("Release assets must be regular files, not links")
    return assets


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--pin",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "buildpython/openrazer_packages/pin.conf",
    )
    parser.add_argument("--packages-only", action="store_true")
    parser.add_argument("--create-checksums", action="store_true")
    parser.add_argument("--check-imports", action="store_true")
    args = parser.parse_args(argv)
    try:
        pin = read_pin(args.pin)
        if args.create_checksums:
            filenames = package_filenames(pin)
            if {p.name for p in args.directory.glob("*.pkg.tar.*")} != set(filenames):
                raise ValueError("Cannot checksum an incomplete or divergent package set")
            (args.directory / SIDECAR).write_text(
                "".join(f"{sha256(args.directory / name)}  {name}\n" for name in filenames),
                encoding="ascii",
            )
        if args.packages_only:
            assets = validate_packages(args.directory, pin, imports=args.check_imports)
        else:
            if args.check_imports:
                raise ValueError("Import checks belong to the builder packages-only gate")
            assets = validate_release_assets(args.directory, args.pin)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    print("Validated assets:\n" + "\n".join(path.name for path in assets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
