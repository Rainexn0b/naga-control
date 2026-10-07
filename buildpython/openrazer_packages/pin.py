"""Read the small, data-only OpenRazer pin; never source unvalidated shell input."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path

FIELDS = {
    "OPENRAZER_FORK_REPO": r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+",
    "OPENRAZER_COMMIT": r"[0-9a-f]{40}",
    "OPENRAZER_BRANCH": r"[A-Za-z0-9][A-Za-z0-9._/-]*",
    "OPENRAZER_PKGVER": r"[0-9][A-Za-z0-9._+]*",
    "OPENRAZER_PKGREL": r"[1-9][0-9]*",
}
PACKAGE_NAMES = (
    "openrazer-driver-dkms-local",
    "openrazer-daemon-local",
    "python-openrazer-local",
)


def read_pin(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r'([A-Z_]+)="([^"\n]+)"', line)
        if match is None:
            raise ValueError("Invalid pin assignment (expected quoted data only)")
        key, value = match.groups()
        if key not in FIELDS or key in values:
            raise ValueError(f"Unknown or duplicate pin field: {key}")
        if re.fullmatch(FIELDS[key], value) is None or ".." in value:
            raise ValueError(f"Unsafe pin field: {key}")
        values[key] = value
    if values.keys() != FIELDS.keys():
        raise ValueError("Missing required pin fields")
    return values


def package_version(pin: dict[str, str]) -> str:
    return f"{pin['OPENRAZER_PKGVER']}-{pin['OPENRAZER_PKGREL']}"


def package_filenames(pin: dict[str, str]) -> tuple[str, ...]:
    return tuple(f"{name}-{package_version(pin)}-any.pkg.tar.zst" for name in PACKAGE_NAMES)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", type=Path, default=Path(__file__).with_name("pin.conf"))
    parser.add_argument("--shell", action="store_true")
    parser.add_argument("--github-env", type=Path)
    args = parser.parse_args(argv)
    try:
        pin = read_pin(args.pin)
        if args.github_env is not None:
            with args.github_env.open("a", encoding="ascii") as output:
                output.write("".join(f"{key}={value}\n" for key, value in pin.items()))
        if args.shell:
            # All values passed the restrictive grammar above; no shell expansion allowed.
            print("\n".join(f"{key}='{value}'" for key, value in pin.items()))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
