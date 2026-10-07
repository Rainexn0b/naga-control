"""Fake-only AppRun python lib selection contracts."""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_APPRUN = REPO_ROOT / "buildpython/steps/appimage/AppRun"


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _make_fake_host(path: Path) -> None:
    _write_executable(path, "#!/usr/bin/env bash\nexit 0\n")


def _make_bundled_python(path: Path) -> None:
    _write_executable(
        path,
        "#!/usr/bin/env bash\n"
        "printf 'LD_LIBRARY_PATH=%s\\n' \"${LD_LIBRARY_PATH-UNSET}\"\n"
        "printf 'PYTHONHOME=%s\\n' \"${PYTHONHOME-UNSET}\"\n"
        "printf 'APPDIR=%s\\n' \"$APPDIR\"\n",
    )


def _install_copy(copy: Path, fake_host: Path) -> None:
    text = SOURCE_APPRUN.read_text(encoding="utf-8")
    patched = text.replace("/usr/bin/python3 -c", f"{fake_host} -c")
    assert "/usr/bin/python3 -c" not in patched
    assert str(fake_host) in patched
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text(patched, encoding="utf-8")
    copy.chmod(0o755)


def _prepare(
    appdir: Path,
    copy: Path,
    fake_host: Path,
    lib_dirs: list[str],
    decoy_files: list[str],
) -> None:
    for name in lib_dirs:
        (appdir / "usr/lib" / name).mkdir(parents=True, exist_ok=True)
    for name in decoy_files:
        target = appdir / "usr/lib" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("decoy", encoding="utf-8")
    _make_bundled_python(appdir / "usr/bin/python3")
    _make_fake_host(fake_host)
    _install_copy(copy, fake_host)


def _run_copy(copy: Path, appdir: Path, cache: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["APPDIR"] = str(appdir)
    env["XDG_CACHE_HOME"] = str(cache)
    env["HOME"] = str(cache)
    env.pop("APPIMAGE", None)
    env.pop("LD_LIBRARY_PATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        ["bash", str(copy), "python"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


def test_single_python314_selects_version_and_qt_lib(tmp_path: Path) -> None:
    appdir = tmp_path / "AppDir"
    copy = tmp_path / "AppRun-copy"
    fake_host = tmp_path / "fake-host"
    cache = tmp_path / "cache"
    _prepare(appdir, copy, fake_host, ["python3.14"], [])
    result = _run_copy(copy, appdir, cache)
    assert result.returncode == 0, result.stderr
    expected = f"{appdir}/usr/lib/python3.14/site-packages/PySide6/Qt/lib"
    assert expected in result.stdout
    assert f"PYTHONHOME={appdir}/usr" in result.stdout
    assert result.stdout.startswith(f"LD_LIBRARY_PATH={appdir}/usr/lib:")


def test_multiple_dirs_select_lexicographically_first(tmp_path: Path) -> None:
    appdir = tmp_path / "AppDir"
    copy = tmp_path / "AppRun-copy"
    fake_host = tmp_path / "fake-host"
    cache = tmp_path / "cache"
    # Create in reverse order to prove sorting, not creation order.
    _prepare(appdir, copy, fake_host, ["python3.14", "python3.13", "python3.12"], [])
    result = _run_copy(copy, appdir, cache)
    assert result.returncode == 0, result.stderr
    expected = f"{appdir}/usr/lib/python3.12/site-packages/PySide6/Qt/lib"
    assert expected in result.stdout
    assert "python3.13" not in result.stdout
    assert "python3.14" not in result.stdout.replace(str(appdir), "")


def test_decoy_regular_file_is_skipped(tmp_path: Path) -> None:
    appdir = tmp_path / "AppDir"
    copy = tmp_path / "AppRun-copy"
    fake_host = tmp_path / "fake-host"
    cache = tmp_path / "cache"
    # Regular file sorts before both directories but must not be selected.
    _prepare(appdir, copy, fake_host, ["python3.14", "python3.12"], ["python3.10"])
    assert (appdir / "usr/lib/python3.10").is_file()
    result = _run_copy(copy, appdir, cache)
    assert result.returncode == 0, result.stderr
    expected = f"{appdir}/usr/lib/python3.12/site-packages/PySide6/Qt/lib"
    assert expected in result.stdout
    assert "python3.10" not in result.stdout


def test_no_python_lib_leaves_base_lib_path(tmp_path: Path) -> None:
    appdir = tmp_path / "AppDir"
    copy = tmp_path / "AppRun-copy"
    fake_host = tmp_path / "fake-host"
    cache = tmp_path / "cache"
    _prepare(appdir, copy, fake_host, [], [])
    result = _run_copy(copy, appdir, cache)
    assert result.returncode == 0, result.stderr
    assert f"LD_LIBRARY_PATH={appdir}/usr/lib\n" in result.stdout
    assert "PySide6" not in result.stdout
    assert "site-packages" not in result.stdout


def test_file_only_behaves_like_no_python_lib(tmp_path: Path) -> None:
    appdir = tmp_path / "AppDir"
    copy = tmp_path / "AppRun-copy"
    fake_host = tmp_path / "fake-host"
    cache = tmp_path / "cache"
    _prepare(appdir, copy, fake_host, [], ["python3.10"])
    result = _run_copy(copy, appdir, cache)
    assert result.returncode == 0, result.stderr
    assert f"LD_LIBRARY_PATH={appdir}/usr/lib\n" in result.stdout
    assert "PySide6" not in result.stdout


def test_whitespace_appdir_is_quoted(tmp_path: Path) -> None:
    appdir = tmp_path / "dir with spaces" / "AppDir"
    copy = tmp_path / "AppRun-copy"
    fake_host = tmp_path / "fake-host"
    cache = tmp_path / "cache with spaces"
    cache.mkdir(parents=True, exist_ok=True)
    _prepare(appdir, copy, fake_host, ["python3.12"], [])
    result = _run_copy(copy, appdir, cache)
    assert result.returncode == 0, result.stderr
    expected = f"{appdir}/usr/lib/python3.12/site-packages/PySide6/Qt/lib"
    assert expected in result.stdout
    assert f"PYTHONHOME={appdir}/usr" in result.stdout


def test_source_uses_quoted_glob_without_ls(tmp_path: Path) -> None:
    del tmp_path  # Static source check only; no fake AppDir needed.
    text = SOURCE_APPRUN.read_text(encoding="utf-8")
    assert 'ls -d "$APPDIR"' not in text
    assert "head -n 1" not in text
    assert 'for candidate in "$APPDIR"/usr/lib/python3.*' in text
    assert '[ -d "$candidate" ]' in text
    assert 'PYLIB="$candidate"' in text
    assert "shellcheck disable" not in text.lower()


def test_source_passes_bash_syntax_check() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SOURCE_APPRUN)],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
