from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class FakeGh:
    """Hermetic gh replacement, including stored remote bytes and partial uploads."""

    def __init__(self, tag: str, draft: bool | None, remote: dict[str, bytes] | None = None):
        self.tag = tag
        self.remote = remote or {}
        self.release: dict[str, Any] | None = None
        self.release_id = 408962506
        if draft is not None:
            self.release = {
                "id": self.release_id,
                "tag_name": tag,
                "draft": draft,
                "prerelease": False,
                "assets": [],
            }
        self.previous: list[dict[str, Any]] = []
        self.commands: list[list[str]] = []
        self.fail_upload = False
        self.fail_read = False
        self.corrupt_download = False
        self._ids: dict[str, int] = {}
        self.list_calls = 0
        self.fetch_calls = 0
        self.fail_relist = False
        self.fail_fetch = False
        self.duplicate_after_create = False
        self.fresh_bad: str | None = None
        self.fetch_bad: str | None = None
        self.public_on_fetch: int | None = None
        self.refresh()

    def refresh(self) -> None:
        for name in self.remote:
            if name not in self._ids:
                self._ids[name] = len(self._ids) + 1
        if self.release is not None:
            self.release["assets"] = [{"name": name, "id": self._ids[name]} for name in self.remote]

    def _listing(self) -> str:
        if self.fail_read:
            raise subprocess.CalledProcessError(1, ["fake-gh", "api", "releases"])
        self.list_calls += 1
        if self.fail_relist and self.list_calls >= 2:
            raise subprocess.CalledProcessError(1, ["fake-gh", "api", "releases"])
        releases = [*self.previous, *([self.release] if self.release is not None else [])]
        if self.duplicate_after_create and self.list_calls >= 2 and self.release is not None:
            duplicate = dict(self.release)
            duplicate["id"] = self.release_id + 1
            releases = [*releases, duplicate]
        if self.fresh_bad is not None and self.list_calls >= 2 and self.release is not None:
            corrupted = dict(self.release)
            if self.fresh_bad == "missing":
                corrupted.pop("id", None)
            elif self.fresh_bad == "bool":
                corrupted["id"] = True
            elif self.fresh_bad == "str":
                corrupted["id"] = "408962506"
            elif self.fresh_bad == "zero":
                corrupted["id"] = 0
            elif self.fresh_bad == "negative":
                corrupted["id"] = -7
            elif self.fresh_bad == "wrongtag":
                corrupted["tag_name"] = "v9.9.9"
            else:
                raise AssertionError(f"Unexpected fresh_bad: {self.fresh_bad}")
            releases = [item for item in releases if item.get("tag_name") != self.tag]
            releases.append(corrupted)
        return json.dumps([releases])

    def _fetch_by_id(self, command: list[str]) -> str:
        if self.fail_fetch:
            raise subprocess.CalledProcessError(1, ["fake-gh", *command])
        self.fetch_calls += 1
        if (
            self.public_on_fetch is not None
            and self.fetch_calls >= self.public_on_fetch
            and self.release is not None
        ):
            self.release["draft"] = False
            self.refresh()
        if self.release is None:
            raise subprocess.CalledProcessError(1, ["fake-gh", *command])
        if self.fetch_bad is not None:
            requested_text = command[1].rsplit("/", 1)[1]
            try:
                requested = int(requested_text)
            except ValueError:
                raise subprocess.CalledProcessError(1, ["fake-gh", *command]) from None
            if requested != self.release_id:
                raise subprocess.CalledProcessError(1, ["fake-gh", *command])
            corrupted = dict(self.release)
            if self.fetch_bad == "missing_id":
                corrupted.pop("id", None)
            elif self.fetch_bad == "bool_id":
                corrupted["id"] = True
            elif self.fetch_bad == "str_id":
                corrupted["id"] = "408962506"
            elif self.fetch_bad == "wrong_id":
                corrupted["id"] = self.release_id + 99
            elif self.fetch_bad == "wrongtag":
                corrupted["tag_name"] = "v9.9.9"
            elif self.fetch_bad == "draft_1":
                corrupted["draft"] = 1
            elif self.fetch_bad == "draft_true":
                corrupted["draft"] = "true"
            elif self.fetch_bad == "draft_false":
                corrupted["draft"] = "false"
            elif self.fetch_bad == "draft_none":
                corrupted["draft"] = None
            else:
                raise AssertionError(f"Unexpected fetch_bad: {self.fetch_bad}")
            return json.dumps(corrupted)
        stored = self.release.get("id")
        path = command[1]
        requested_text = path.rsplit("/", 1)[1]
        try:
            requested = int(requested_text)
        except ValueError:
            raise subprocess.CalledProcessError(1, ["fake-gh", *command]) from None
        if isinstance(stored, bool) or not isinstance(stored, int) or stored != requested:
            raise subprocess.CalledProcessError(1, ["fake-gh", *command])
        return json.dumps(self.release)

    def __call__(self, command: list[str]) -> str:
        self.commands.append(command)
        if command[0] == "release":
            assert command[-2:] == ["--repo", "Rainexn0b/naga-control"]
            command = command[:-2]
        if command[:3] == ["api", "--paginate", "--slurp"]:
            return self._listing()
        if command[:3] == ["api", "--method", "DELETE"]:
            identifier = int(command[3].rsplit("/", 1)[1])
            for name in list(self.remote):
                if self._ids[name] == identifier:
                    del self.remote[name]
            self.refresh()
            return ""
        if command[0] == "api":
            path = command[1]
            if path.rsplit("/", 2)[-2] == "tags":
                # Actual GET /releases/tags/{tag} only serves published releases.
                raise subprocess.CalledProcessError(1, ["fake-gh", *command])
            if "/releases/tags/" in path:
                raise subprocess.CalledProcessError(1, ["fake-gh", *command])
            return self._fetch_by_id(command)
        assert command[0] == "release"
        operation = command[1]
        if operation == "create":
            assert "--draft" in command and "--verify-tag" in command
            self.release = {
                "id": self.release_id,
                "tag_name": self.tag,
                "draft": True,
                "prerelease": False,
                "assets": [],
            }
            self.refresh()
        elif operation == "upload":
            for filename in command[3:]:
                path = Path(filename)
                self.remote[path.name] = path.read_bytes()
                self.refresh()
                if self.fail_upload:
                    raise subprocess.CalledProcessError(1, ["fake-gh", *command])
        elif operation == "download":
            directory = Path(command[command.index("--dir") + 1])
            for name, data in self.remote.items():
                (directory / name).write_bytes(b"corrupted" if self.corrupt_download else data)
        elif operation == "edit":
            assert self.release is not None
            self.release["draft"] = False
        else:
            raise AssertionError(f"Unexpected fake gh operation: {command}")
        return ""

    def mutations(self) -> list[list[str]]:
        return [
            command
            for command in self.commands
            if (
                command[:2] in (["release", "create"], ["release", "upload"], ["release", "edit"])
                or command[:3] == ["api", "--method", "DELETE"]
            )
        ]


def copy_assets(source: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in source.iterdir()}


def change_version(project: Path, version: str) -> None:
    (project / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
    (project / "changelog.md").write_text(f"## [{version}] - 2026-10-07\n\n- Fixture changes.\n")
