"""Exercise installer paths without networking, privilege, or live services."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "scripts/install_user.sh"
REPO_URL = "https://raw.githubusercontent.com/Rainexn0b/naga-control"

FAKE_COMMAND = r"""
import json
import os
import shutil
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with Path(os.environ["COMMAND_LOG"]).open("a") as log:
    log.write(json.dumps([name, *args]) + "\n")
if name == "id":
    print("1000")
elif name == "curl":
    url = args[-1]
    if url.endswith("/releases/latest"):
        print("https://github.com/Rainexn0b/naga-control/releases/tag/" + os.environ["TEST_TAG"])
    else:
        target = Path(args[args.index("-o") + 1])
        if "/releases/download/" in url:
            shutil.copyfile(__file__, target)
        elif url == os.environ["RULE_URL"]:
            target.write_text("downloaded tagged rule\n")
        else:
            target.write_text("failed download\n")
            sys.exit(22)
elif name == "sudo":
    if args[0] == "install":
        assert args[:3] == ["install", "-m", "644"]
        assert args[-1] == "/etc/udev/rules.d/70-naga-control.rules"
        shutil.copyfile(args[3], os.environ["INSTALLED_RULE"])
    else:
        assert args in [["udevadm", "control", "--reload"], ["udevadm", "trigger"]]
elif name == "systemctl":
    assert args in [["--user", "daemon-reload"], ["--user", "enable", "--now", "naga-control.service"]]
elif name == "naga-control.AppImage":
    assert args[0] == "--install"
    assert args[1:3] == ["--exec-prefix", sys.argv[0]]
    assert args[3] == "--udev-dir"
    assert Path(args[4]).is_relative_to(Path(os.environ["TMPDIR"]))
else:
    raise AssertionError(name)
"""


def _run_installer(
    tmp_path: Path,
    *,
    rule_layout: str,
    version_source: str = "argument",
    checkout: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], Path]:
    tag = "v0.3.0" if rule_layout == "packaging" else "v0.4.0"
    root = tmp_path / "checkout"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "install_user.sh"
    shutil.copyfile(INSTALLER, script)
    # A legacy checkout path must not be treated as the current local source.
    legacy_rule = root / "packaging/udev/70-naga-control.rules"
    legacy_rule.parent.mkdir(parents=True)
    legacy_rule.write_text("legacy checkout decoy\n")
    if checkout:
        local_rule = root / "system/udev/70-naga-control.rules"
        local_rule.parent.mkdir(parents=True)
        local_rule.write_text("checkout system rule\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command in ("id", "curl", "sudo", "systemctl"):
        fake = bin_dir / command
        fake.write_text(f"#!{sys.executable}\n{FAKE_COMMAND}")
        fake.chmod(0o755)
    for command in ("mkdir", "cat", "mv", "chmod", "mktemp", "rm", "dirname"):
        executable = shutil.which(command)
        assert executable is not None
        (bin_dir / command).symlink_to(executable)

    temporary = tmp_path / "temporary"
    temporary.mkdir()
    log = tmp_path / "commands.jsonl"
    installed_rule = tmp_path / "installed.rules"
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": str(bin_dir),
        "TMPDIR": str(temporary),
        "COMMAND_LOG": str(log),
        "INSTALLED_RULE": str(installed_rule),
        "TEST_TAG": tag,
        "RULE_URL": f"{REPO_URL}/{tag}/{rule_layout}/udev/70-naga-control.rules",
    }
    for variable in ("NAGA_CONTROL_VERSION", "NAGA_CONTROL_FORCE_DOWNLOAD", "BASH_ENV", "ENV"):
        env.pop(variable, None)
    args = ["/bin/bash", str(script)]
    if version_source == "argument":
        args.extend(["--version", tag])
    elif version_source == "environment":
        env["NAGA_CONTROL_VERSION"] = tag
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10, check=False)
    commands: list[list[str]] = [json.loads(line) for line in log.read_text().splitlines()]
    return result, commands, installed_rule


def test_checkout_installer_uses_system_udev_rule(tmp_path: Path) -> None:
    result, commands, rule = _run_installer(tmp_path, rule_layout="missing", checkout=True)

    assert result.returncode == 0, result.stderr
    assert rule.read_text() == "checkout system rule\n"
    assert not any(REPO_URL in command[-1] for command in commands if command[0] == "curl")
    sudo_install = next(command for command in commands if command[:2] == ["sudo", "install"])
    assert sudo_install[4].endswith("/scripts/../system/udev/70-naga-control.rules")


@pytest.mark.parametrize("version_source", ["argument", "environment", "latest"])
@pytest.mark.parametrize("rule_layout", ["system", "packaging"])
def test_downloaded_installer_uses_same_tag_paths(
    tmp_path: Path, version_source: str, rule_layout: str
) -> None:
    result, commands, rule = _run_installer(
        tmp_path, rule_layout=rule_layout, version_source=version_source
    )

    assert result.returncode == 0, result.stderr
    tag = "v0.3.0" if rule_layout == "packaging" else "v0.4.0"
    expected_urls = [f"{REPO_URL}/{tag}/system/udev/70-naga-control.rules"]
    if rule_layout == "packaging":
        expected_urls.append(f"{REPO_URL}/{tag}/packaging/udev/70-naga-control.rules")
    assert [
        command[-1] for command in commands if command[0] == "curl" and REPO_URL in command[-1]
    ] == expected_urls
    assert rule.read_text() == "downloaded tagged rule\n"
    assert (tmp_path / "home/.local/share/naga-control/installed-tag").read_text() == f"{tag}\n"
    assert ["systemctl", "--user", "daemon-reload"] in commands
    assert ["systemctl", "--user", "enable", "--now", "naga-control.service"] in commands
    assert any(command[0] == "naga-control.AppImage" for command in commands)
    downloads = [
        command[-1]
        for command in commands
        if command[0] == "curl" and "/releases/download/" in command[-1]
    ]
    assert downloads == [
        f"https://github.com/Rainexn0b/naga-control/releases/download/{tag}/Naga-Control-x86_64.AppImage"
    ]


@pytest.mark.parametrize("version_source", ["argument", "environment", "latest"])
def test_missing_tagged_rule_never_falls_back_to_main(tmp_path: Path, version_source: str) -> None:
    result, commands, rule = _run_installer(
        tmp_path, rule_layout="missing", version_source=version_source
    )

    assert result.returncode != 0
    assert "could not download the udev rule for v0.4.0" in result.stderr
    assert [
        command[-1] for command in commands if command[0] == "curl" and REPO_URL in command[-1]
    ] == [
        f"{REPO_URL}/v0.4.0/system/udev/70-naga-control.rules",
        f"{REPO_URL}/v0.4.0/packaging/udev/70-naga-control.rules",
    ]
    assert not rule.exists()
    assert not any(command[0] in {"sudo", "systemctl"} for command in commands)
