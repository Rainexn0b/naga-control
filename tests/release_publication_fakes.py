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
        if draft is not None:
            self.release = {"tag_name": tag, "draft": draft, "prerelease": False, "assets": []}
        self.previous: list[dict[str, Any]] = []
        self.commands: list[list[str]] = []
        self.fail_upload = False
        self.fail_read = False
        self.corrupt_download = False
        self._ids: dict[str, int] = {}
        self.refresh()

    def refresh(self) -> None:
        for name in self.remote:
            if name not in self._ids:
                self._ids[name] = len(self._ids) + 1
        if self.release is not None:
            self.release["assets"] = [{"name": name, "id": self._ids[name]} for name in self.remote]

    def __call__(self, command: list[str]) -> str:
        self.commands.append(command)
        if command[0] == "release":
            assert command[-2:] == ["--repo", "Rainexn0b/naga-control"]
            command = command[:-2]
        if command[:3] == ["api", "--paginate", "--slurp"]:
            if self.fail_read:
                raise subprocess.CalledProcessError(1, ["fake-gh", *command])
            releases = [*self.previous, *([self.release] if self.release is not None else [])]
            return json.dumps([releases])
        if command[:3] == ["api", "--method", "DELETE"]:
            identifier = int(command[3].rsplit("/", 1)[1])
            for name in list(self.remote):
                if self._ids[name] == identifier:
                    del self.remote[name]
            self.refresh()
            return ""
        if command[0] == "api":
            assert self.release is not None
            return json.dumps(self.release)
        assert command[0] == "release"
        operation = command[1]
        if operation == "create":
            assert "--draft" in command and "--verify-tag" in command
            self.release = {"tag_name": self.tag, "draft": True, "prerelease": False, "assets": []}
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
