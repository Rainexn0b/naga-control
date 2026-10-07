"""Closed-PATH installer command emulation; only fixture files are accessed."""

FAKE = r"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

name = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path(os.environ["FAKE_ROOT"])
if name in ("sudo", "systemctl", "naga-control.AppImage", "Naga-Control-x86_64.AppImage"):
    try:
        os.fstat(9)
    except OSError:
        pass
    else:
        raise AssertionError("install lock FD leaked to activation/privilege child")
state = json.loads((root / "state.json").read_text())
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps([name, *args]) + "\n")
if name == "id":
    print({"-u": state.get("uid", "1000"), "-un": "desktop-user", "-nG": state["groups"]}[args[0]])
elif name == "installer-helper":
    assert len(args) == 3 and args[0] == "--version", args
    if args[2] == "--preflight":
        print("fake prerequisite preflight: " + " ".join(args))
        sys.exit(state.get("helper_preflight_failure", 0))
    assert args[2] == "--install", args
    print("fake prerequisite called: " + " ".join(args))
    sys.exit(state.get("helper_install_failure", 0))
elif name == "curl":
    url = next(arg for arg in args if arg.startswith("https://"))
    if url.endswith("/releases/latest"):
        print("https://github.com/Rainexn0b/naga-control/releases/tag/v0.4.0")
    else:
        filename = Path(urlsplit(url).path).name
        if filename == state.get("barrier_file"):
            with (root / "barrier-ready").open("w") as ready:
                ready.write("ready\n")
            with (root / "barrier-release").open() as release:
                release.read()
        target = Path(args[args.index("-o") + 1])
        fixture = root / "remote" / filename
        if filename == "70-naga-control.rules" and state.get("rule_layout"):
            if "/" + state["rule_layout"] + "/udev/" not in url:
                sys.exit(22)
        if filename in state["download_fail"] or not fixture.is_file():
            sys.exit(22)
        if filename == "Naga-Control-x86_64.AppImage.sha256" and ("/" + state.get("previous_tag", "unused") + "/") in url:
            target.write_text(state["previous_digest"] + "  Naga-Control-x86_64.AppImage\n")
            sys.exit(0)
        shutil.copyfile(fixture, target)
elif name == "pacman":
    assert args[0] == "-Q", args
    version = state["installed"].get(args[1])
    if version is None:
        sys.exit(1)
    print(args[1] + " " + version)
elif name == "sudo":
    if args[0] == "pacman":
        assert args[1] == "-U", args
        assert len(args) == 5, args
        assert all(Path(arg).is_file() for arg in args[2:]), args
        sys.exit(state["pacman_failure"])
    elif args[0] == "usermod":
        assert args == ["usermod", "-aG", "openrazer", "desktop-user"], args
    elif args[0] == "install":
        assert args[:3] == ["install", "-m", "644"], args
        assert args[-1] == "/etc/udev/rules.d/70-naga-control.rules", args
        shutil.copyfile(args[3], root / "installed.rules")
    else:
        assert args == ["udevadm", "control", "--reload"], args
        sys.exit(state.get("udev_failure", 0))
elif name == "systemctl":
    if args == ["--user", "show", "--property=Version", "--value"]:
        print("fake systemd")
        sys.exit(state.get("systemd_failure", 0))
    if args == ["--user", "show", "naga-control.service", "--property=ActiveState", "--value"]:
        print(state.get("service_state", "inactive"))
        sys.exit(0)
    if args == ["--user", "show", "naga-control.service", "--property=UnitFileState", "--value"]:
        print(state.get("unit_state", ""))
        sys.exit(0)
    assert args in [["--user", "daemon-reload"],
                     ["--user", "enable", "openrazer-daemon.service"],
                     ["--user", "enable", "naga-control.service"],
                     ["--user", "enable", "--runtime", "naga-control.service"],
                     ["--user", "disable", "naga-control.service"],
                     ["--user", "disable", "--now", "naga-control.service"],
                     ["--user", "stop", "naga-control.service"],
                     ["--user", "start", "naga-control.service"],
                     ["--user", "enable", "--now", "naga-control.service"]], args
    if state["unit_failure"] and args[1] == state["unit_failure"]:
        if state.get("unit_failure_once"):
            state["unit_failure"] = ""
            (root / "state.json").write_text(json.dumps(state))
        sys.exit(1)
    if args[1] == "stop" or (args[1] == "disable" and "--now" in args):
        state["service_state"] = state.get("stop_state", "inactive")
    elif args[1] == "start" or "--now" in args:
        state["service_state"] = "active"
    if args[1] == "enable" and "naga-control.service" in args:
        state["unit_state"] = "enabled-runtime" if "--runtime" in args else "enabled"
    elif args[1] == "disable":
        state["unit_state"] = "disabled"
    (root / "state.json").write_text(json.dumps(state))
elif name == "busctl":
    assert args == ["--user", "status"], args
    sys.exit(state.get("bus_failure", 0))
elif name == "uname":
    print({"-s": state.get("os", "Linux"), "-m": state.get("arch", "x86_64"), "-r": "fake-kernel"}[args[0]])
elif name == "ldconfig":
    assert args == ["-p"], args
    if not state.get("fuse_library_missing"):
        print("libfuse.so.2 (libc6," + state.get("fuse_library_arch", "x86-64") + ") => " + str(root / "libfuse.so.2"))
elif name == "stat":
    if args[:2] in (["-Lc", "%d:%i"], ["-Lc", "%a"]):
        sys.exit(subprocess.run([os.environ["SAFE_STAT"], *args], check=False).returncode)
    else:
        assert args[:2] == ["-c", "%F"], args
        print("character special file" if not state.get("fuse_runtime_missing") else "regular file")
elif name in ("install", "udevadm", "cc", "make", "dkms", "clang", "ld.lld", "llvm-ar", "llvm-nm", "llvm-objcopy", "llvm-objdump", "llvm-readelf", "llvm-strip"):
    raise AssertionError("preflight must only discover tools, never build")
elif name in ("system-python3", "python", "python3"):
    assert args[:2] == ["-I", "-B"], args
    if "-c" in args:
        code = args[args.index("-c") + 1]
        if "sys.exit(0 if sys.version_info" in code:
            version = tuple(int(part) for part in state["host_python"].split(".")) if state["host_python"][0].isdigit() else ()
            sys.exit(0 if version >= (3, 9) else 1)
        elif "sys.version_info" in code:
            print(state["host_python"] if name == "system-python3" else state["venv_python"])
        else:
            assert "PathFinder" in code, code
            print("Host import discoverability: openrazer.client=True, openrazer_daemon=True")
    else:
        assert name == "system-python3", "validator must use the absolute system interpreter"
        assert args[:3] == ["-I", "-B", "-"], args
        sys.exit(subprocess.run([sys.executable, *args], check=False).returncode)
elif name == "bsdtar":
    filename = Path(args[1]).name
    metadata = state["metadata"][filename]
    if args[0] == "-tf":
        print("\n".join(metadata["members"]))
    else:
        assert args[0] == "-xOf" and args[2] == "--", args
        member = args[3].removeprefix("./")
        assert member in [".PKGINFO", "usr/share/doc/" + metadata["role"] + "/source-commit"], args
        print(metadata["pkginfo"] if member == ".PKGINFO" else metadata["stamp"], end="")
elif name == "cat":
    if args and args[0].startswith("/usr/share/doc/"):
        stamp = state["stamps"].get(Path(args[0]).parent.name)
        if stamp is None:
            sys.exit(1)
        print(stamp)
    else:
        sys.exit(subprocess.run([os.environ["SAFE_CAT"], *args], check=False).returncode)
elif name in ("naga-control.AppImage", "Naga-Control-x86_64.AppImage"):
    if args == ["--uninstall"]:
        sys.exit(0)
    assert args[0] == "--install", args
    assert args[args.index("--exec-prefix") + 1] == str(root / "home/.local/bin/naga-control.AppImage"), args
    home = Path(args[args.index("--home") + 1])
    assert home.is_relative_to(root / "temporary"), args
    files = [".config/systemd/user/naga-control.service",
             ".local/share/dbus-1/services/org.nagacontrol.Service1.service",
             ".local/share/applications/org.nagacontrol.NagaControl.desktop"]
    files += [f".local/share/icons/hicolor/{s}x{s}/apps/org.nagacontrol.NagaControl.png" for s in (64, 128, 256, 512)]
    for relative in files:
        target = home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("new fake integration\n")
        target.chmod(0o644)
    sys.exit(state.get("integration_failure", 0))
else:
    raise AssertionError(name)
"""
