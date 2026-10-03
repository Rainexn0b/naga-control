"""Synchronous, Qt-free release checks; callers should run fetches off the UI thread."""

import json
import re
from dataclasses import dataclass
from http.client import HTTPException
from importlib import metadata
from typing import cast
from urllib import error, request
from urllib.parse import quote

from packaging.version import InvalidVersion, Version

_API_URL = "https://api.github.com/repos/Rainexn0b/naga-control/releases"
_RELEASE_URL = "https://github.com/Rainexn0b/naga-control/releases/tag/"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_PAGE_SIZE = 100
_MAX_PAGES = 3


class UpdateCheckError(Exception):
    """An update check failed without establishing a complete release list."""


@dataclass(frozen=True)
class Release:
    tag: str
    version: Version
    prerelease: bool
    url: str


def installed_version() -> str:
    try:
        return metadata.version("naga-control")
    except metadata.PackageNotFoundError:
        return "unknown"


def parse_releases(payload: object) -> tuple[Release, ...]:
    """Validate GitHub's release list, omitting drafts and non-version tags."""
    if not isinstance(payload, list):
        raise UpdateCheckError("GitHub returned an invalid release list. Try again later.")
    releases: list[Release] = []
    for item in cast(list[object], payload):
        if not isinstance(item, dict):
            raise UpdateCheckError("GitHub returned an invalid release entry. Try again later.")
        entry = cast(dict[str, object], item)
        draft = entry.get("draft")
        if not isinstance(draft, bool):
            raise UpdateCheckError("GitHub returned an invalid release draft flag.")
        if draft:
            continue
        tag = entry.get("tag_name")
        prerelease = entry.get("prerelease")
        if not isinstance(tag, str) or not isinstance(prerelease, bool):
            raise UpdateCheckError("GitHub returned invalid release metadata. Try again later.")
        try:
            version = Version(tag.removeprefix("v"))
        except InvalidVersion:
            continue
        releases.append(
            Release(
                tag=tag,
                version=version,
                prerelease=prerelease or version.is_prerelease or version.is_devrelease,
                url=_RELEASE_URL + quote(tag, safe=""),
            )
        )
    return tuple(releases)


def latest_release(
    releases: tuple[Release, ...], *, include_prereleases: bool = False
) -> Release | None:
    return max(
        (release for release in releases if include_prereleases or not release.prerelease),
        key=lambda release: (release.version, not release.prerelease),
        default=None,
    )


def fetch_releases() -> tuple[Release, ...]:
    """Read at most three bounded GitHub pages, never returning a partial result."""
    releases: list[Release] = []
    for page in range(1, _MAX_PAGES + 1):
        query = request.Request(
            f"{_API_URL}?per_page={_PAGE_SIZE}&page={page}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Naga-Control",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with request.urlopen(query, timeout=5) as response:
                body = response.read(_MAX_RESPONSE_BYTES + 1)
                has_next = bool(re.search(r';\s*rel="next"', response.headers.get("Link", "")))
        except error.HTTPError as exc:
            try:
                if exc.code in (403, 429):
                    message = (
                        f"GitHub refused the update check (HTTP {exc.code}). "
                        "Its API rate limit may have been reached; try again later."
                    )
                elif exc.code == 404:
                    message = "The GitHub release repository was not found (HTTP 404)."
                else:
                    message = f"GitHub could not complete the update check (HTTP {exc.code})."
            finally:
                exc.close()
            raise UpdateCheckError(message) from exc
        except (error.URLError, OSError, HTTPException) as exc:
            raise UpdateCheckError(
                "Could not connect to GitHub. Check your network connection and try again."
            ) from exc
        if len(body) > _MAX_RESPONSE_BYTES:
            raise UpdateCheckError("GitHub's release response exceeded the 2 MB safety limit.")
        try:
            payload = cast(object, json.loads(body.decode("utf-8")))
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise UpdateCheckError(
                "GitHub returned malformed release JSON. Try again later."
            ) from exc
        releases.extend(parse_releases(payload))
        # Count raw entries: filtering drafts or invalid tags must not truncate pagination.
        entries = cast(list[object], payload)
        if len(entries) > _PAGE_SIZE:
            raise UpdateCheckError("GitHub returned an invalid release page size.")
        if not has_next and len(entries) < _PAGE_SIZE:
            return tuple(releases)
    raise UpdateCheckError(
        "GitHub's release list exceeds the 3-page safety limit; the update check is incomplete."
    )
