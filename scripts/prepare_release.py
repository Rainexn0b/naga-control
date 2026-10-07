"""Validate a release tag and generate notes from the root changelog."""

from __future__ import annotations

import argparse
import os
import posixpath
import re
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from packaging.version import InvalidVersion, Version

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buildpython.openrazer_packages.pin import package_version, read_pin

SAFETY_PREREQUISITES = (
    (
        ("1532:00e7", "1532:00e8", "one transport at a time"),
        "Only Razer Naga V3 Pro wired `1532:00E7` and HyperSpeed `1532:00E8` are "
        "supported, one transport at a time. Bluetooth and other devices are excluded.",
    ),
    (
        ("gui", "service", "as root"),
        "Do not run the GUI or service as root.",
    ),
)


def hardware_prerequisites(project_root: Path) -> tuple[tuple[tuple[str, ...], str], ...]:
    pin = read_pin(project_root / "buildpython/openrazer_packages/pin.conf")
    commit = pin["OPENRAZER_COMMIT"]
    # Suppress only a complete current requirement, not an incidental SHA mention.
    # Historical/stale package guidance stays untouched and is intentionally augmented.
    markers = (
        f"`{commit}`",
        f"`{pin['OPENRAZER_FORK_REPO']}`".casefold(),
        f"`{pin['OPENRAZER_BRANCH']}`".casefold(),
        f"`{package_version(pin)}`".casefold(),
        "explicitly opt-in",
    )
    baseline = (
        markers,
        f"Requires the custom OpenRazer baseline at `{commit}` "
        f"(fork `{pin['OPENRAZER_FORK_REPO']}`, branch `{pin['OPENRAZER_BRANCH']}`, "
        f"Arch packages `{package_version(pin)}` attached to this release); no released "
        "upstream minimum replaces it. Use compatible kernel module, daemon, Python "
        "client, udev rules, and metadata. The temporary Arch prerequisite bridge is "
        "explicitly opt-in; source pinning is not an indefinite security freeze.",
    )
    return (baseline, *SAFETY_PREREQUISITES)


def project_version(project_root: Path) -> Version:
    with (project_root / "pyproject.toml").open("rb") as source:
        return Version(tomllib.load(source)["project"]["version"])


def promotion(version: Version, published_tags: Sequence[str]) -> tuple[bool, bool]:
    prerelease = version.is_prerelease or version.is_devrelease
    latest = not prerelease
    for tag in published_tags:
        try:
            published = Version(tag.strip())
        except InvalidVersion:
            continue
        if not (published.is_prerelease or published.is_devrelease) and published > version:
            latest = False
    return prerelease, latest


def pin_repository_links(notes: str, tag: str) -> str:
    def replace_link(match: re.Match[str]) -> str:
        target = urlsplit(match["target"])
        if target.scheme or target.netloc or not target.path:
            return match.group()
        path = posixpath.normpath(target.path.removeprefix("/"))
        if path == ".." or path.startswith("../"):
            return match.group()
        pinned = urlunsplit(
            (
                "https",
                "github.com",
                f"/Rainexn0b/naga-control/blob/{quote(tag, safe='')}/{quote(path, safe='/%')}",
                target.query,
                target.fragment,
            )
        )
        return match["prefix"] + pinned

    return re.sub(
        r"(?P<prefix>\]\(\s*<?|^ {0,3}\[[^\]\n]+\]:\s*<?)(?P<target>[^\s<>\)]+)",
        replace_link,
        notes,
        flags=re.MULTILINE,
    )


def prepare_release(tag: str, project_root: Path) -> tuple[Version, str]:
    if re.fullmatch(r"v[0-9][A-Za-z0-9.!+\-]*", tag) is None:
        raise ValueError(f"Invalid release tag: {tag!r}; expected v followed by a version")
    try:
        version = Version(tag[1:])
    except InvalidVersion as error:
        raise ValueError(f"Invalid release tag: {tag!r}") from error

    expected_version = project_version(project_root)
    if version != expected_version:
        raise ValueError(f"Tag version {version} does not match package version {expected_version}")

    changelog = (project_root / "changelog.md").read_text(encoding="utf-8")
    sections = list(re.finditer(r"^## .*$", changelog, re.MULTILINE))
    entries: list[str] = []
    for index, section in enumerate(sections):
        heading = re.fullmatch(r"## \[([^\]]+)\] - \d{4}-\d{2}-\d{2}", section.group())
        if heading is None:
            continue
        try:
            entry_version = Version(heading[1])
        except InvalidVersion:
            continue
        if entry_version == version:
            end = sections[index + 1].start() if index + 1 < len(sections) else len(changelog)
            entries.append(changelog[section.end() : end].strip())
    if not entries:
        raise ValueError(f"Missing dated changelog entry for {version}")
    if len(entries) != 1:
        raise ValueError(f"Multiple changelog entries for {version}")
    notes = entries[0]
    if not notes or not re.sub(r"(?m)^\s*#{1,6} .*$", "", notes).strip():
        raise ValueError(f"Empty changelog entry for {version}")

    normalized_notes = " ".join(notes.casefold().split())
    missing = [
        text
        for markers, text in hardware_prerequisites(project_root)
        if not all(marker in normalized_notes for marker in markers)
    ]
    if missing:
        notes += "\n\n### Hardware Prerequisites\n\n" + "\n".join(f"- {text}" for text in missing)
    return version, pin_repository_links(notes, tag) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", nargs="?", help="Release tag, e.g. v0.3.0 or v0.4.0-rc.1")
    parser.add_argument(
        "--validation-only", action="store_true", help="Use project version, not ref"
    )
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--notes-output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, default=os.environ.get("GITHUB_OUTPUT"))
    parser.add_argument(
        "--published-tags", type=Path, help="Newline-separated published stable release tags"
    )
    args = parser.parse_args(argv)
    try:
        tag = f"v{project_version(args.project_root)}" if args.validation_only else args.tag
        if tag is None:
            raise ValueError("A release tag is required unless --validation-only is used")
        version, notes = prepare_release(tag, args.project_root)
        prerelease = version.is_prerelease or version.is_devrelease
        latest = False
        if args.published_tags is not None:
            prerelease, latest = promotion(
                version, args.published_tags.read_text(encoding="utf-8").splitlines()
            )
        args.notes_output.write_text(notes, encoding="utf-8")
        outputs = (
            f"version={version}\n"
            f"prerelease={str(prerelease).lower()}\n"
            f"latest={str(latest).lower()}\n"
        )
        if args.github_output is not None:
            with args.github_output.open("a", encoding="utf-8") as destination:
                destination.write(outputs)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(outputs, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
