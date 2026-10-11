"""Closed-PATH native installer command emulation; only fixture files are used."""

FAKE = r"""
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from urllib.parse import urlsplit

name = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path(os.environ["FAKE_ROOT"])
if name in ("sudo", "systemctl"):
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
    print({"-u": state.get("uid", str(os.getuid())), "-un": "desktop-user", "-nG": state["groups"]}[args[0]])
elif name == "uname":
    print({"-s": state.get("os", "Linux"), "-m": state.get("arch", "x86_64"), "-r": state.get("kernel", "6.8.0-52-generic")}[args[0]])
elif name == "stat":
    if args[:2] == ["-c", "%u"]:
        target = args[2] if len(args) > 2 else ""
        if state.get("foreign_owner") and "/output/" in target:
            print(str(int(os.getuid()) + 1))
        else:
            sys.exit(subprocess.run([os.environ["SAFE_STAT"], *args], check=False).returncode)
    elif args[:2] in (["-Lc", "%d:%i"], ["-Lc", "%a"], ["-c", "%u"], ["-c", "%Y"]):
        sys.exit(subprocess.run([os.environ["SAFE_STAT"], *args], check=False).returncode)
    else:
        raise AssertionError(args)
elif name == "curl":
    url = next(arg for arg in args if arg.startswith("https://"))
    target = Path(args[args.index("-o") + 1])
    if "api.github.com" in url and "/commits/" in url:
        if "naga-sha" in state.get("download_fail", []):
            sys.exit(22)
        text = state.get("naga_sha_text", None)
        if text is not None:
            target.write_text(text)
        else:
            target.write_text(state.get("naga_sha", "a" * 40) + "\n")
    elif "codeload.github.com" in url and "/tar.gz/" in url:
        if "naga.tar.gz" in state.get("download_fail", []):
            sys.exit(22)
        kind = state.get("code_tar", "good")
        fixture = root / "remote" / "naga-code.tar.gz"
        if kind == "good":
            shutil.copyfile(fixture, target)
        elif kind == "not-archive":
            target.write_text("not a tarball\n")
        elif kind == "bad-pin":
            with tarfile.open(fixture, "r:gz") as tar:
                members = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
            bad = dict(members)
            for key in list(bad):
                if key.endswith("/pin.conf"):
                    bad[key] = b'OPENRAZER_FORK_REPO="Rainexn0b/openrazer"\nOPENRAZER_COMMIT="' + b"b" * 40 + b'"\nOPENRAZER_BRANCH="naga-v3-pro-compat"\nOPENRAZER_PKGVER="3.12.1.pr2904.fix2"\nOPENRAZER_PKGREL="1"\n'
            with tarfile.open(target, "w:gz") as tar:
                for arcname, data in bad.items():
                    info = tarfile.TarInfo(arcname)
                    info.size = len(data)
                    info.mode = 0o644
                    tar.addfile(info, io.BytesIO(data))
        elif kind == "wrong-root":
            with tarfile.open(fixture, "r:gz") as tar:
                members = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
            with tarfile.open(target, "w:gz") as tar:
                for arcname, data in members.items():
                    fixed = arcname.replace("naga-control-" + "a" * 40, "wrong-root")
                    info = tarfile.TarInfo(fixed)
                    info.size = len(data)
                    info.mode = 0o644
                    tar.addfile(info, io.BytesIO(data))
        elif kind == "dotpath":
            with tarfile.open(target, "w:gz") as tar:
                for arcname in ["naga-control-" + "a" * 40 + "/buildpython/__init__.py", "naga-control-" + "a" * 40 + "/buildpython/../evil.py"]:
                    info = tarfile.TarInfo(arcname)
                    data = b"# evil\n"
                    info.size = len(data)
                    info.mode = 0o644
                    tar.addfile(info, io.BytesIO(data))
        elif kind == "link":
            with tarfile.open(target, "w:gz") as tar:
                info = tarfile.TarInfo("naga-control-" + "a" * 40 + "/buildpython/__init__.py")
                data = b""
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
                link = tarfile.TarInfo("naga-control-" + "a" * 40 + "/buildpython/openrazer_native/evil.py")
                link.type = tarfile.SYMTYPE
                link.linkname = "/etc/passwd"
                tar.addfile(link)
        elif kind == "missing-native":
            with tarfile.open(fixture, "r:gz") as tar:
                members = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
            with tarfile.open(target, "w:gz") as tar:
                for arcname, data in members.items():
                    if arcname.endswith("/openrazer_native/__main__.py"):
                        continue
                    info = tarfile.TarInfo(arcname)
                    info.size = len(data)
                    info.mode = 0o644
                    tar.addfile(info, io.BytesIO(data))
        else:
            target.write_text("unsafe\n")
    else:
        filename = Path(urlsplit(url).path).name
        if filename in state.get("download_fail", []):
            sys.exit(22)
        fixture = root / "remote" / filename
        if not fixture.is_file():
            sys.exit(22)
        shutil.copyfile(fixture, target)
elif name == "git":
    if state.get("git_fail"):
        sys.exit(1)
    stripped = []
    skip = False
    idx = 0
    while idx < len(args):
        if skip:
            skip = False
            idx += 1
            continue
        if args[idx] == "-c":
            skip = True
            idx += 1
            continue
        stripped.append(args[idx])
        idx += 1
    joined = " ".join(stripped)
    if len(stripped) >= 2 and stripped[0] == "init":
        Path(stripped[-1]).mkdir(parents=True, exist_ok=True)
    elif len(stripped) >= 5 and stripped[0] == "-C" and stripped[2:4] == ["remote", "add"]:
        if "https://github.com/Rainexn0b/openrazer.git" not in stripped:
            raise AssertionError(args)
    elif len(stripped) >= 5 and stripped[0] == "-C" and stripped[2] == "fetch":
        if state.get("git_dead_branch"):
            sys.exit(128)
    elif len(stripped) >= 4 and stripped[0] == "-C" and stripped[2:4] == ["checkout", "--detach"]:
        pass
    elif len(stripped) >= 4 and stripped[0] == "-C" and stripped[2:4] == ["rev-parse", "HEAD"]:
        print(state.get("git_head", "26b0eeb5ed70d638fa3528851adcd5e58369a7f5"))
    elif len(stripped) >= 3 and stripped[0] == "-C" and stripped[2] == "status":
        if stripped[3:] != ["--porcelain", "--untracked-files=all", "--ignored"]:
            raise AssertionError("unflagged status: " + " ".join(args))
        if state.get("git_dirty"):
            print(" M daemon/openrazer_daemon/hardware/mouse.py")
    else:
        raise AssertionError("unknown git: " + " ".join(args))
elif name == "dpkg-query":
    if state.get("query_fail"):
        sys.exit(1)
    if state.get("query_malformed") == "controls":
        print("install ok installed openrazer-daemon-local 3.12.1.pr2904.fix2-1\x01")
        sys.exit(0)
    if state.get("query_malformed") == "no-space":
        print("malformed-row-without-space")
        sys.exit(0)
    if state.get("query_malformed") not in (None, "", "controls", "no-space"):
        malformed = state["query_malformed"]
        if isinstance(malformed, list):
            print("\n".join(str(p) for p in malformed))
        else:
            print(str(malformed))
        sys.exit(0)
    for pkg, ver in state.get("installed", {}).items():
        status = "install ok installed"
        if pkg in state.get("partial", []):
            status = "install ok unpacked"
        print(f"{status} {pkg} {ver}")
elif name == "rpm":
    if len(args) >= 2 and args[0] == "-q" and "--whatprovides" in args:
        if state.get("whatprovides_fail"):
            sys.exit(1)
        print(state.get("kernel_evr", "6.10.5-1.1"))
    else:
        assert args[:1] == ["-qa"], args
        if state.get("query_fail"):
            sys.exit(1)
        if state.get("query_malformed") == "controls":
            print("openrazer-daemon-local\x01 3.12.1.pr2904.fix2-1")
            sys.exit(0)
        if state.get("query_malformed") == "no-space":
            print("malformed-row")
            sys.exit(0)
        if state.get("query_malformed") not in (None, "", "controls", "no-space"):
            malformed = state["query_malformed"]
            if isinstance(malformed, list):
                print("\n".join(str(p) for p in malformed))
            else:
                print(str(malformed))
            sys.exit(0)
        for pkg, ver in state.get("installed", {}).items():
            print(f"{pkg} {ver}")
elif name == "sudo":
    if args[0] in ("apt-get", "dnf", "zypper"):
        manager = args[0]
        rest = args[1:]
        if manager == "zypper" and rest[:2] == ["install", "--allow-unsigned-rpm"]:
            assert len(rest) >= 3, args
            assert all(Path(p).is_file() and p.endswith(".rpm") for p in rest[2:]), args
            assert len(rest[2:]) == 3, args
            sys.exit(state.get("pkg_failure", 0))
        elif rest[:1] == ["install"]:
            pkgs = rest[1:]
            assert len(pkgs) >= 1, args
            assert not any(p in ("-y", "--noconfirm", "--non-interactive", "--no-confirm", "-n") for p in pkgs), args
            assert "--allow-unsigned-rpm" not in pkgs or manager != "zypper" or all(p.endswith(".rpm") for p in pkgs), args
            if all(Path(p).is_absolute() and Path(p).is_file() for p in pkgs):
                assert len(pkgs) == 3, args
                sys.exit(state.get("pkg_failure", 0))
            else:
                assert not any(Path(p).is_absolute() for p in pkgs), args
                import time as _time

                _time.sleep(state.get("prereq_sleep", 0))
                sys.exit(state.get("prereq_failure", 0))
        else:
            raise AssertionError(args)
    elif args[0] == "usermod":
        assert args == ["usermod", "-aG", "openrazer", "desktop-user"], args
        sys.exit(state.get("group_failure", 0))
    else:
        raise AssertionError(args)
elif name == "systemctl":
    if args == ["--user", "show", "--property=Version", "--value"]:
        print("fake systemd")
        sys.exit(state.get("systemd_failure", 0))
    assert args in [["--user", "daemon-reload"], ["--user", "enable", "openrazer-daemon.service"]], args
    if state.get("unit_failure", "") in ("daemon-reload", "enable"):
        if args[1] == state["unit_failure"]:
            sys.exit(1)
elif name == "busctl":
    assert args == ["--user", "status"], args
    sys.exit(state.get("bus_failure", 0))
elif name in ("system-python3", "python", "python3"):
    assert args[:2] == ["-I", "-B"], args
    if "-c" in args:
        code = args[args.index("-c") + 1]
        if "sys.stdin.buffer.read" in code:
            proc = subprocess.run(
                [sys.executable, "-I", "-B", "-c", code], input=sys.stdin.buffer.read()
            )
            sys.exit(proc.returncode)
        if "run_module(\"buildpython.openrazer_native\"" in code:
            idx = args.index("-c") + 2
            rest = args[idx:]
            family = rest[rest.index("--family") + 1]
            output = Path(rest[rest.index("--output") + 1])
            if state.get("builder_fail"):
                sys.exit(1)
            bad = state.get("builder_bad", "")
            version = "3.12.1.pr2904.fix2-1"
            if family == "debian":
                names = [f"openrazer-driver-dkms-local_{version}_all.deb", f"openrazer-daemon-local_{version}_all.deb", f"python-openrazer-local_{version}_all.deb"]
            else:
                names = [f"openrazer-driver-dkms-local-{version}.noarch.rpm", f"openrazer-daemon-local-{version}.noarch.rpm", f"python-openrazer-local-{version}.noarch.rpm"]
            output.mkdir(parents=True, exist_ok=True)
            if bad == "missing-role":
                names = names[:2]
            for n in names:
                (output / n).write_bytes((n + " fake native bytes\n").encode())
            if bad == "extra-file":
                (output / "unexpected.txt").write_text("extra\n")
            if bad == "symlink":
                target = output / names[0]
                target.unlink()
                target.symlink_to(names[1])
            if bad == "hardlink" and len(names) >= 2:
                (output / names[0]).unlink()
                os.link(output / names[1], output / names[0])
            import hashlib
            import json as _json
            rows = []
            for n in names:
                if (output / n).is_symlink():
                    digest = "0" * 64
                else:
                    digest = hashlib.sha256((output / n).read_bytes()).hexdigest()
                if bad == "bad-digest" and n == names[0]:
                    digest = "0" * 64
                rows.append(f"{digest}  {n}\n")
            if bad == "bad-manifest-row":
                rows[0] = rows[0].replace("  ", " *")
            if bad == "missing-newline":
                (output / "openrazer-native-packages.sha256").write_text("".join(rows).rstrip("\n"))
            else:
                (output / "openrazer-native-packages.sha256").write_text("".join(rows))
            if bad == "sidecar-symlink":
                side = output / "openrazer-native-packages.sha256"
                data = side.read_bytes()
                side.unlink()
                side.symlink_to(names[0])
            host_full = state.get("host_python", "3.12")
            try:
                _major, _minor = host_full.split(".")
                int(_minor)
            except (ValueError, IndexError):
                _major, _minor = "3", "12"
            minor_str = f"{_major}.{_minor}"
            if bad == "mixed-python":
                minor_str = f"{_major}.{int(_minor) + 1}"
            if bad == "foreign-minor":
                minor_str = "3.9"
            if bad == "future-minor":
                minor_str = "3.15"
            doc = {"schema": 1, "source_commit": "26b0eeb5ed70d638fa3528851adcd5e58369a7f5", "family": family, "version": version, "python_minor": minor_str, "packages": []}
            if bad == "bad-schema":
                doc["schema"] = 2
            if bad == "schema-true":
                doc["schema"] = True
            if bad == "wrong-family":
                doc["family"] = "debian" if family != "debian" else "fedora"
            if bad == "wrong-commit":
                doc["source_commit"] = "b" * 40
            if bad == "extra-keys":
                doc["extra"] = 1
            for n in names:
                role = ""
                for r in ("openrazer-driver-dkms-local", "openrazer-daemon-local", "python-openrazer-local"):
                    if n.startswith(r):
                        role = r
                        break
                use_role = role
                if bad == "role-swap" and role == "openrazer-driver-dkms-local":
                    use_role = "openrazer-daemon-local"
                elif bad == "role-swap" and role == "openrazer-daemon-local":
                    use_role = "openrazer-driver-dkms-local"
                if (output / n).is_symlink():
                    digest = "0" * 64
                else:
                    digest = hashlib.sha256((output / n).read_bytes()).hexdigest()
                if bad == "bad-digest" and n == names[0]:
                    digest = "0" * 64
                doc["packages"].append({"role": use_role, "filename": n, "sha256": digest})
            if bad == "missing-role":
                doc["packages"] = doc["packages"][:2]
            if bad == "duplicate-keys":
                raw = _json.dumps(doc)
                raw = raw.replace('"schema": 1', '"schema": 1, "schema": 1')
                (output / "native-build.json").write_text(raw)
            else:
                (output / "native-build.json").write_text(_json.dumps(doc))
            if bad == "json-symlink":
                js = output / "native-build.json"
                data = js.read_bytes()
                js.unlink()
                js.symlink_to(names[0])
        elif "sys.exit(0 if sys.version_info" in code:
            parts = state["host_python"].split(".")
            try:
                version = (int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                version = (0, 0)
            sys.exit(0 if version >= (3, 10) else 1)
        elif "print(f\"{sys.version_info.major}.{sys.version_info.minor}\")" in code:
            print(state.get("host_python", "3.12"))
        elif "print(sys.version_info.minor)" in code:
            raw = state.get("host_python", "3.12")
            try:
                print(raw.split(".")[1])
            except IndexError:
                print("invalid")
        elif "sys.version_info" in code and "print" in code:
            print(state["host_python"] if name == "system-python3" else state.get("venv_python", "3.12"))
        else:
            assert "PathFinder" in code, code
            assert "OPENRAZER-PROBE" in code, code
            if state.get("python_discover_error"):
                sys.exit(1)
            if state.get("python_malformed"):
                print(state["python_malformed"])
                sys.exit(0)
            root_flag = state.get("python_root", False)
            client = state.get("python_client", False)
            daemon = state.get("python_daemon", False)
            print(f"OPENRAZER-PROBE p={root_flag} client={client} daemon={daemon}")
            sys.exit(0 if (not root_flag and not daemon) else 1)
    else:
        assert name == "system-python3", "validator must use the absolute system interpreter"
        assert args[:3] == ["-I", "-B", "-"], args
        sys.exit(subprocess.run([sys.executable, *args], check=False).returncode)
elif name in ("cc", "make", "dkms", "gcc", "clang", "ld.lld", "llvm-ar", "llvm-nm", "llvm-objcopy", "llvm-objdump", "llvm-readelf", "llvm-strip", "dpkg-deb", "rpmbuild", "rpm2cpio"):
    raise AssertionError("preflight must only discover tools, never build")
else:
    raise AssertionError(name)
"""
