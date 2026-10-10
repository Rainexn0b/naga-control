"""Publish only a complete validated set; public binaries are immutable on rerun."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buildpython.openrazer_packages.validation import sha256
from scripts.prepare_release import prepare_release, promotion
from scripts.validate_release_assets import validate_release_assets

Gh = Callable[[list[str]], str]


def gh(command: list[str]) -> str:
    return subprocess.run(["gh", *command], check=True, capture_output=True, text=True).stdout


def release_assets(release: dict[str, Any]) -> dict[str, int]:
    assets: dict[str, int] = {}
    for asset in release["assets"]:
        name, identifier = asset["name"], asset["id"]
        if not isinstance(name, str) or not isinstance(identifier, int) or name in assets:
            raise ValueError("Invalid or duplicate remote asset metadata")
        assets[name] = identifier
    return assets


def list_releases(call: Gh, repository: str) -> list[dict[str, Any]]:
    pages = json.loads(call(["api", "--paginate", "--slurp", f"repos/{repository}/releases"]))
    return [release for page in pages for release in page]


def draft_release_id(release: dict[str, Any], tag: str) -> int:
    identifier = release.get("id")
    if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier <= 0:
        raise ValueError("Release metadata is missing a valid release identifier")
    if release.get("tag_name") != tag:
        raise ValueError("Release metadata tag mismatch")
    return identifier


def fetch_release(call: Gh, repository: str, identifier: int) -> dict[str, Any]:
    return json.loads(call(["api", f"repos/{repository}/releases/{identifier}"]))


def checked_fetch(call: Gh, repository: str, identifier: int, tag: str) -> dict[str, Any]:
    current = fetch_release(call, repository, identifier)
    fetched = current.get("id")
    if isinstance(fetched, bool) or not isinstance(fetched, int) or fetched != identifier:
        raise ValueError("Release identifier lookup mismatch")
    if current.get("tag_name") != tag:
        raise ValueError("Release identifier lookup mismatch")
    return current


def verify_remote(tag: str, assets: tuple[Path, ...], call: Gh) -> None:
    with tempfile.TemporaryDirectory(prefix="release-verification-") as temp:
        directory = Path(temp)
        call(["release", "download", tag, "--dir", str(directory)])
        if {path.name for path in directory.iterdir()} != {path.name for path in assets}:
            raise ValueError("Remote release asset set is incomplete or divergent")
        for asset in assets:
            downloaded = directory / asset.name
            if (
                downloaded.is_symlink()
                or not downloaded.is_file()
                or sha256(downloaded) != sha256(asset)
            ):
                raise ValueError(f"Remote asset bytes differ: {asset.name}")


def publish(
    tag: str,
    project_root: Path,
    directory: Path,
    notes_file: Path,
    repository: str,
    *,
    event: str,
    call: Gh = gh,
) -> str:
    if event != "push":
        raise ValueError("Publication is forbidden for dispatch and non-push events")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        raise ValueError("Invalid GitHub repository")
    original_call = call

    def repository_call(command: list[str]) -> str:
        # The API and gh release operations must address the same explicit repository.
        if command[0] == "release":
            command = [*command, "--repo", repository]
        return original_call(command)

    call = repository_call
    version, notes = prepare_release(tag, project_root)
    if notes_file.read_text(encoding="utf-8") != notes:
        raise ValueError("Prepared release notes do not match validated metadata")
    assets = validate_release_assets(
        directory, project_root / "buildpython/openrazer_packages/pin.conf"
    )
    # A failed read is not treated as 'absent'. List drafts too, and paginate fully.
    # GET /releases/tags/{tag} only returns published releases, so drafts resolve
    # by stable release ID from the listing, then GET /releases/{id}.
    # GitHub offers no atomic compare-and-swap; rechecks narrow the public race.
    releases = list_releases(call, repository)
    matches = [release for release in releases if release.get("tag_name") == tag]
    if len(matches) > 1:
        raise ValueError("Ambiguous release metadata")
    prerelease, latest = promotion(
        version,
        [
            release["tag_name"]
            for release in releases
            if not release["draft"] and not release["prerelease"]
        ],
    )
    existing = matches[0] if matches else None
    if existing is not None and existing.get("draft") is False:
        if set(release_assets(existing)) != {path.name for path in assets}:
            raise ValueError("Published release is immutable; use a new tag for divergent assets")
        try:
            verify_remote(tag, assets, call)
        except ValueError as error:
            raise ValueError("Published binaries are immutable; use a new tag") from error
        if existing.get("prerelease") != prerelease:
            raise ValueError("Published classification differs; use a new tag")
        return "Identical completed release verified; no changes made"

    if existing is None:
        call(
            [
                "release",
                "create",
                tag,
                "--draft",
                "--verify-tag",
                "--title",
                tag,
                "--notes-file",
                str(notes_file),
            ]
        )
        releases = list_releases(call, repository)
        matches = [release for release in releases if release.get("tag_name") == tag]
        if len(matches) > 1:
            raise ValueError("Ambiguous release metadata")
        if not matches:
            raise ValueError("Fresh release lookup failed; refusing asset mutation")
        existing = matches[0]
    identifier = draft_release_id(existing, tag)
    current = checked_fetch(call, repository, identifier, tag)
    if current.get("draft") is not True:
        raise ValueError("Refusing to reconcile a release that is no longer a draft")
    # Draft reruns discard ALL stale/partial assets, not just matching basenames.
    for asset_id in release_assets(current).values():
        fresh = checked_fetch(call, repository, identifier, tag)
        if fresh.get("draft") is not True:
            raise ValueError("Release became public; refusing asset mutation")
        call(["api", "--method", "DELETE", f"repos/{repository}/releases/assets/{asset_id}"])
    pre_upload = checked_fetch(call, repository, identifier, tag)
    if pre_upload.get("draft") is not True:
        raise ValueError("Release became public; refusing asset mutation")
    call(["release", "upload", tag, *[str(path) for path in assets]])
    current = checked_fetch(call, repository, identifier, tag)
    if current.get("draft") is not True or set(release_assets(current)) != {
        path.name for path in assets
    }:
        raise ValueError("Uploaded release must remain a draft with exactly the complete asset set")
    verify_remote(tag, assets, call)
    final = checked_fetch(call, repository, identifier, tag)
    if final.get("draft") is not True:
        raise ValueError("Release became public; refusing asset mutation")
    call(
        [
            "release",
            "edit",
            tag,
            "--draft=false",
            "--title",
            tag,
            "--notes-file",
            str(notes_file),
            f"--prerelease={str(prerelease).lower()}",
            f"--latest={str(latest).lower()}",
        ]
    )
    return "Complete release asset set verified and published"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args(argv)
    try:
        print(
            publish(
                args.tag,
                args.project_root,
                args.directory,
                args.notes,
                args.repository,
                event=os.environ.get("GITHUB_EVENT_NAME", ""),
            )
        )
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
