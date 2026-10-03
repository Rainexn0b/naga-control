"""Validate a release tag and generate notes from the root changelog."""

from __future__ import annotations

import argparse
import os
import posixpath
import re
import tomllib
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from packaging.version import InvalidVersion, Version

HARDWARE_PREREQUISITES = (
    (
        ("2416bfebf0175db6aae519a450f55fe9eba255e9",),
        "Requires the custom OpenRazer `add-razer-naga-v3-pro-support` baseline at "
        "`2416bfebf0175db6aae519a450f55fe9eba255e9`; no released upstream minimum "
        "replaces it. Use compatible kernel module, daemon, Python client, udev rules, "
        "and metadata.",
    ),
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

    with (project_root / "pyproject.toml").open("rb") as source:
        package_version = Version(tomllib.load(source)["project"]["version"])
    if version != package_version:
        raise ValueError(f"Tag version {version} does not match package version {package_version}")

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
        for markers, text in HARDWARE_PREREQUISITES
        if not all(marker in normalized_notes for marker in markers)
    ]
    if missing:
        notes += "\n\n### Hardware Prerequisites\n\n" + "\n".join(f"- {text}" for text in missing)
    return version, pin_repository_links(notes, tag) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="Release tag, for example v0.3.0 or v0.4.0-rc.1")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--notes-output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, default=os.environ.get("GITHUB_OUTPUT"))
    parser.add_argument(
        "--published-tags", type=Path, help="Newline-separated published stable release tags"
    )
    args = parser.parse_args(argv)
    try:
        version, notes = prepare_release(args.tag, args.project_root)
        prerelease = version.is_prerelease or version.is_devrelease
        latest = False
        if args.published_tags is not None:
            latest = not prerelease
            for tag in args.published_tags.read_text(encoding="utf-8").splitlines():
                try:
                    published = Version(tag.strip())
                except InvalidVersion:
                    continue
                if not (published.is_prerelease or published.is_devrelease) and published > version:
                    latest = False
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
