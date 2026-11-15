"""Real launcher, fake host discovery/Python, and isolated cache write failures."""

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "buildpython/steps/appimage/AppRun"
PACKAGES = ("openrazer", "openrazer_daemon")


def _executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\nset -eu\n" + body)
    path.chmod(0o755)


@dataclass
class Launcher:
    root: Path
    appdir: Path
    host: Path
    links: Path
    env: dict[str, str]

    def run(self, command: str = "service") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/bash", str(self.appdir / "AppRun"), command],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def seed(self, *, stale: bool = False) -> None:
        self.links.mkdir(parents=True, exist_ok=True)
        for package in PACKAGES:
            target = self.root / "old-host" / package if stale else self.host / package
            (self.links / package).symlink_to(target)

    def fail(self, command: str) -> None:
        _executable(
            self.appdir / "usr/bin" / command,
            f'printf "%s\\n" "{command}: simulated No space left on device" >&2\nexit 1\n',
        )

    def assert_links(self) -> None:
        for package in PACKAGES:
            assert (self.links / package).is_symlink()
            assert os.readlink(self.links / package) == str(self.host / package)
        assert sorted(path.name for path in self.links.iterdir()) == sorted(PACKAGES)


@pytest.fixture
def launcher(tmp_path: Path) -> Launcher:
    # Spaces also exercise quoting in the real launcher, not just a fake shell path.
    root = tmp_path / "launch fixture"
    appdir = root / "AppDir"
    host = root / "host-site"
    for package in PACKAGES:
        (host / package).mkdir(parents=True)
    (appdir / "usr/lib/python3.12").mkdir(parents=True)
    discovery = root / "discover"
    _executable(
        discovery,
        "for package do :; done\n"
        '[ "${NO_HOST_PACKAGES:-0}" = 0 ] || exit 0\n'
        'printf "%s/%s\\n" "$FAKE_HOST" "$package"\n',
    )
    source = SOURCE.read_text()
    assert source.count("/usr/bin/python3 -c") == 1
    (appdir / "AppRun").write_text(
        source.replace("/usr/bin/python3 -c", f"{shlex.quote(str(discovery))} -c")
    )
    _executable(
        appdir / "usr/bin/python3",
        'printf "bundled-python:%s\\n" "$*"\nprintf "bridge:%s\\n" "${PYTHONPATH-UNSET}"\n',
    )
    cache = root / "cache"
    env = dict(
        os.environ,
        APPDIR=str(appdir),
        APPIMAGE=str(root / "fake.AppImage"),
        HOME=str(root / "home"),
        XDG_CACHE_HOME=str(cache),
        FAKE_HOST=str(host),
        PATH="/usr/bin:/bin",
        PYTHONPATH="must-not-leak-host-site-packages",
        NO_HOST_PACKAGES="0",
    )
    return Launcher(root, appdir, host, cache / "naga-control/host-openrazer", env)


def test_fresh_writable_cache_starts_python(launcher: Launcher) -> None:
    result = launcher.run()
    assert result.returncode == 0, result.stderr
    assert "bundled-python:-m naga_control.service.service_cli" in result.stdout
    assert f"bridge:{launcher.links}\n" in result.stdout
    launcher.assert_links()


@pytest.mark.parametrize("command", ["gui", "service", "capture", "integration", "python"])
def test_matching_links_need_no_cache_writes(launcher: Launcher, command: str) -> None:
    launcher.seed()
    inodes = {package: (launcher.links / package).lstat().st_ino for package in PACKAGES}
    for writer in ("mkdir", "mktemp", "ln", "mv", "rm"):
        launcher.fail(writer)

    result = launcher.run(command)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "bundled-python:" in result.stdout
    assert f"bridge:{launcher.links}\n" in result.stdout
    launcher.assert_links()
    assert {package: (launcher.links / package).lstat().st_ino for package in PACKAGES} == inodes


@pytest.mark.parametrize("writer", ["mkdir", "mktemp", "ln", "mv"])
@pytest.mark.parametrize("stale", [False, True], ids=["fresh-cache", "stale-links"])
def test_cache_write_failure_exits_75_before_python(
    launcher: Launcher, writer: str, stale: bool
) -> None:
    if stale:
        launcher.seed(stale=True)
    launcher.fail(writer)

    result = launcher.run()

    assert result.returncode == 75
    assert "bundled-python:" not in result.stdout
    assert f"{writer}: simulated No space left on device" in result.stderr
    assert "Naga Control: cannot prepare OpenRazer cache" in result.stderr
    assert str(launcher.links) in result.stderr
    assert "package openrazer" in result.stderr
    assert "start again manually" in result.stderr
    if stale:
        for package in PACKAGES:
            assert os.readlink(launcher.links / package) == str(
                launcher.root / "old-host" / package
            )
    if launcher.links.exists():
        assert not list(launcher.links.glob(".*")), "failed replacement left temporary links"


def test_second_package_failure_preserves_first_valid_link(launcher: Launcher) -> None:
    launcher.seed()
    first = launcher.links / PACKAGES[0]
    inode = first.lstat().st_ino
    (launcher.links / PACKAGES[1]).unlink()
    launcher.fail("mktemp")

    result = launcher.run()

    assert result.returncode == 75
    assert "package openrazer_daemon" in result.stderr
    assert "bundled-python:" not in result.stdout
    assert first.lstat().st_ino == inode
    assert os.readlink(first) == str(launcher.host / PACKAGES[0])


def test_stale_links_are_replaced_without_touching_old_targets(launcher: Launcher) -> None:
    launcher.seed(stale=True)
    for package in PACKAGES:
        old = launcher.root / "old-host" / package
        old.mkdir(parents=True)
        (old / "sentinel").write_text("preserve")

    result = launcher.run()

    assert result.returncode == 0, result.stderr
    launcher.assert_links()
    for package in PACKAGES:
        assert (launcher.root / "old-host" / package / "sentinel").read_text() == "preserve"


def test_regular_file_is_replaced_not_reused_as_a_link(launcher: Launcher) -> None:
    launcher.links.mkdir(parents=True)
    (launcher.links / PACKAGES[0]).write_text(str(launcher.host / PACKAGES[0]))

    result = launcher.run()

    assert result.returncode == 0, result.stderr
    launcher.assert_links()


def test_obstructing_directory_is_preserved_and_startup_stops(launcher: Launcher) -> None:
    obstruction = launcher.links / PACKAGES[0]
    obstruction.mkdir(parents=True)
    sentinel = obstruction / "sentinel"
    sentinel.write_text("preserve")

    result = launcher.run()

    assert result.returncode == 75
    assert "bundled-python:" not in result.stdout
    assert sentinel.read_text() == "preserve"
    assert list(launcher.links.iterdir()) == [obstruction]


def test_no_host_packages_needs_no_cache_and_no_pythonpath(launcher: Launcher) -> None:
    launcher.env["NO_HOST_PACKAGES"] = "1"
    launcher.fail("mkdir")
    launcher.fail("mktemp")

    result = launcher.run()

    assert result.returncode == 0, result.stderr
    assert "bridge:UNSET\n" in result.stdout
    assert not launcher.links.exists()
