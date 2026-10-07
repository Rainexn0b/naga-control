"""Exercise tagged integration paths without network, privilege or live units."""

import subprocess
from pathlib import Path

import pytest

from tests.installer_app_fakes import ASSET, app_harness, mutations, stamp
from tests.openrazer_installer_fakes import InstallerHarness

REPO_URL = "https://raw.githubusercontent.com/Rainexn0b/naga-control"


def _run_installer(
    tmp_path: Path,
    *,
    rule_layout: str,
    version_source: str = "argument",
    checkout: bool = False,
    opt_in: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], InstallerHarness]:
    fake, script = app_harness(tmp_path)
    tag = "v0.3.0" if rule_layout == "packaging" else "v0.4.0"
    fake.configure(rule_layout=rule_layout)
    if checkout:
        local_rule = script.parent.parent / "system/udev/70-naga-control.rules"
        local_rule.parent.mkdir(parents=True)
        local_rule.write_text("checkout system rule\n")
    legacy = script.parent.parent / "packaging/udev/70-naga-control.rules"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy checkout decoy\n")
    args = ["--install-openrazer"] if opt_in else []
    if version_source == "argument":
        args.extend(["--version", tag])
    elif version_source == "environment":
        fake.environment["NAGA_CONTROL_VERSION"] = tag
    result, commands = fake.run(*args, script=script)
    return result, commands, fake


def test_checkout_installer_uses_system_udev_rule(tmp_path: Path) -> None:
    result, commands, fake = _run_installer(tmp_path, rule_layout="missing", checkout=True)
    assert result.returncode == 0, result.stderr
    assert (fake.root / "installed.rules").read_text() == "checkout system rule\n"
    assert not any(REPO_URL in command[-1] for command in commands if command[0] == "curl")
    sudo_install = next(command for command in commands if command[:2] == ["sudo", "install"])
    assert sudo_install[4].endswith("/scripts/../system/udev/70-naga-control.rules")


@pytest.mark.parametrize("version_source", ["argument", "environment", "latest"])
@pytest.mark.parametrize("rule_layout", ["system", "packaging"])
def test_downloaded_installer_uses_same_tag_paths(
    tmp_path: Path, version_source: str, rule_layout: str
) -> None:
    # latest selects the fixture latest tag; only argument/environment select an
    # older tag explicitly. All fallback paths still use the selected exact tag.
    result, commands, fake = _run_installer(
        tmp_path, rule_layout=rule_layout, version_source=version_source
    )
    assert result.returncode == 0, result.stderr
    tag = "v0.3.0" if rule_layout == "packaging" and version_source != "latest" else "v0.4.0"
    urls = [f"{REPO_URL}/{tag}/system/udev/70-naga-control.rules"]
    if rule_layout == "packaging":
        urls.append(f"{REPO_URL}/{tag}/packaging/udev/70-naga-control.rules")
    assert [c[-1] for c in commands if c[0] == "curl" and REPO_URL in c[-1]] == urls
    assert (fake.root / "installed.rules").read_text() == "fake tagged rule\n"
    assert stamp(fake).read_text() == tag + "\n"
    assert ["systemctl", "--user", "daemon-reload"] in commands
    assert ["systemctl", "--user", "enable", "--now", "naga-control.service"] in commands
    assert any(command[0] == ASSET for command in commands)
    downloads = [c[-1] for c in commands if c[0] == "curl" and "/releases/download/" in c[-1]]
    base = f"https://github.com/Rainexn0b/naga-control/releases/download/{tag}"
    assert downloads == [f"{base}/{ASSET}.sha256", f"{base}/{ASSET}"]


@pytest.mark.parametrize("version_source", ["argument", "environment", "latest"])
def test_missing_tagged_rule_never_falls_back_to_main(tmp_path: Path, version_source: str) -> None:
    result, commands, fake = _run_installer(
        tmp_path, rule_layout="missing", version_source=version_source
    )
    assert result.returncode != 0
    assert "could not download the udev rule for v0.4.0" in result.stderr
    assert [c[-1] for c in commands if c[0] == "curl" and REPO_URL in c[-1]] == [
        f"{REPO_URL}/v0.4.0/system/udev/70-naga-control.rules",
        f"{REPO_URL}/v0.4.0/packaging/udev/70-naga-control.rules",
    ]
    assert mutations(commands) == []
    assert not (fake.root / "installed.rules").exists()
    assert not stamp(fake).exists()


@pytest.mark.parametrize("version_source", ["argument", "environment", "latest"])
def test_default_missing_helper_never_fetches_optional_script(
    tmp_path: Path, version_source: str
) -> None:
    result, commands, fake = _run_installer(
        tmp_path, rule_layout="system", version_source=version_source
    )
    assert result.returncode == 0, result.stderr
    assert [c[-1] for c in commands if c[0] == "curl" and REPO_URL in c[-1]] == [
        f"{REPO_URL}/v0.4.0/system/udev/70-naga-control.rules"
    ]
    assert "app-only install" in result.stdout
    assert ["systemctl", "--user", "enable", "--now", "naga-control.service"] in commands
    assert stamp(fake).read_text() == "v0.4.0\n"


@pytest.mark.parametrize("version_source", ["argument", "environment", "latest"])
def test_opt_in_missing_helper_failure_propagates(tmp_path: Path, version_source: str) -> None:
    result, commands, _ = _run_installer(
        tmp_path, rule_layout="system", version_source=version_source, opt_in=True
    )
    assert result.returncode != 0
    assert "could not download install_openrazer.sh for v0.4.0" in result.stderr
    assert mutations(commands) == []
    assert "app installed;" not in result.stdout
