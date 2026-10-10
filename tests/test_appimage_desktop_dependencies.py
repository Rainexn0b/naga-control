"""Desktop runtime prerequisites for portable AppImage (static recipe only).

Static checks for the throwaway builder and smoke environments only. No host
package installation, no network, no Docker, no root, no D-Bus, and no device
reads. Package lists cover the normal Qt Wayland/XCB/GTK/CUPS userspace that
the finished-artifact static gate reports as missing providers; they do not
claim every Linux host requires all packages when a bundled library provides
the same SONAME.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from buildpython.steps.appimage import artifact, elf, smoke

REPO = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO / "buildpython/steps/appimage/Dockerfile.portable"
SMOKE_MODULE = REPO / "buildpython/steps/appimage/smoke.py"
INNER = REPO / "buildpython/steps/appimage/portable-inner.sh"
PAYLOAD_MODULE = REPO / "buildpython/steps/appimage/payload.py"
DEPENDENCIES_MODULE = REPO / "buildpython/steps/appimage/dependencies.py"

BASE_IMAGE = "ubuntu:22.04@sha256:08ea48a03a3e78ebc7cd526e6a275053223aadd88bfc09cc49b06d5281525fde"
PYTHON_URL = "https://www.python.org/ftp/python/3.12.15/Python-3.12.15.tar.xz"
PYTHON_SHA = "c2c4321961fab0fb999d66e0cecf521c2ab3994c7992873ea99e306c1094fd5a"
EXPECTED_PY = "3.12.15"
EXPECTED_GLIBC = "2.35"

# SONAMEs reported as missing providers by the static gate (throwaway envs only).
WAYLAND_SONAMES = ("libwayland-cursor.so.0", "libwayland-egl.so.1")
XCB_SONAMES = (
    "libxcb-cursor.so.0",
    "libxcb-icccm.so.4",
    "libxcb-image.so.0",
    "libxcb-keysyms.so.1",
    "libxcb-render-util.so.0",
    "libxcb-render.so.0",
    "libxcb-shape.so.0",
    "libxcb-util.so.1",
    "libxcb-xkb.so.1",
    "libxkbcommon-x11.so.0",
)
# GTK transitive set is satisfied via libgtk-3-0(-t64); no separate atk/cairo
# package is listed because the GTK runtime pulls those dependencies.
GTK_SONAMES = (
    "libgtk-3.so.0",
    "libatk-1.0.so.0",
    "libcairo-gobject.so.2",
    "libcairo.so.2",
    "libgdk-3.so.0",
    "libgdk_pixbuf-2.0.so.0",
    "libharfbuzz.so.0",
    "libpango-1.0.so.0",
    "libpangocairo-1.0.so.0",
)
CUPS_SONAMES = ("libcups.so.2",)

DOCKER_22_RUNTIME = frozenset(
    {
        "libwayland-cursor0",
        "libwayland-egl1",
        "libxcb-cursor0",
        "libxcb-icccm4",
        "libxcb-image0",
        "libxcb-keysyms1",
        "libxcb-render-util0",
        "libxcb-render0",
        "libxcb-shape0",
        "libxcb-util1",
        "libxcb-xkb1",
        "libxkbcommon-x11-0",
        "libgtk-3-0",
        "libcups2",
    }
)
SMOKE_24_RUNTIME = frozenset(
    {
        "libwayland-cursor0",
        "libwayland-egl1",
        "libxcb-cursor0",
        "libxcb-icccm4",
        "libxcb-image0",
        "libxcb-keysyms1",
        "libxcb-render-util0",
        "libxcb-render0",
        "libxcb-shape0",
        "libxcb-util1",
        "libxcb-xkb1",
        "libxkbcommon-x11-0",
        "libgtk-3-0t64",
        "libcups2t64",
    }
)

SONAME_TO_22_PACKAGE = {
    "libwayland-cursor.so.0": "libwayland-cursor0",
    "libwayland-egl.so.1": "libwayland-egl1",
    "libxcb-cursor.so.0": "libxcb-cursor0",
    "libxcb-icccm.so.4": "libxcb-icccm4",
    "libxcb-image.so.0": "libxcb-image0",
    "libxcb-keysyms.so.1": "libxcb-keysyms1",
    "libxcb-render-util.so.0": "libxcb-render-util0",
    "libxcb-render.so.0": "libxcb-render0",
    "libxcb-shape.so.0": "libxcb-shape0",
    "libxcb-util.so.1": "libxcb-util1",
    "libxcb-xkb.so.1": "libxcb-xkb1",
    "libxkbcommon-x11.so.0": "libxkbcommon-x11-0",
    "libgtk-3.so.0": "libgtk-3-0",
    "libcups.so.2": "libcups2",
}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _docker_apt_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    in_install = False
    for line in text.splitlines():
        stripped = line.strip()
        if "apt-get install" in stripped:
            in_install = True
            after = stripped.split("apt-get install", 1)[1]
            for part in after.replace("\\", " ").split():
                clean = part.strip().rstrip(";")
                if clean in ("-y", "--no-install-recommends", "&&", "\\", ""):
                    continue
                if clean.startswith("-") or "://" in clean or "/" in clean:
                    continue
                tokens.append(clean)
            continue
        if not in_install:
            continue
        if stripped.startswith(("RUN ", "FROM ", "ENV ", "CMD ")):
            in_install = False
            continue
        if "rm -rf" in stripped:
            in_install = False
            continue
        for part in stripped.replace("\\", " ").replace("&&", " ").split():
            clean = part.strip().rstrip("\\").rstrip(";")
            if clean in ("&&", "\\", "") or clean.startswith("-"):
                continue
            if "://" in clean or "/" in clean:
                continue
            tokens.append(clean)
    return [token for token in tokens if token and token != "\\"]


def _smoke_apt_tokens(script: str) -> list[str]:
    for line in script.splitlines():
        if "apt-get install" in line:
            after = line.split("apt-get install", 1)[1]
            tokens: list[str] = []
            for part in after.replace(">/dev/null", " ").replace(">", " ").split():
                clean = part.strip().rstrip(";")
                if clean in ("-y", "--no-install-recommends", ""):
                    continue
                if clean.startswith("-") or "/" in clean:
                    continue
                tokens.append(clean)
            return tokens
    return []


def test_dockerfile_pins_immutable_toolchain() -> None:
    text = _read_text(DOCKERFILE)
    assert f"FROM {BASE_IMAGE}" in text
    assert PYTHON_URL in text
    assert PYTHON_SHA in text
    assert EXPECTED_PY in text
    assert text.index(PYTHON_SHA) < text.index("tar -xf")
    assert text.index(PYTHON_SHA) < text.index("./configure")
    assert "sha256sum -c" in text
    assert "--enable-shared" in text
    assert "--without-static-libpython" in text
    assert "--prefix=/opt/naga-python" in text
    assert "t64" not in text
    assert artifact.BASELINE == "Ubuntu 22.04 / glibc 2.35 / x86_64"
    assert EXPECTED_GLIBC in artifact.BASELINE
    inner = _read_text(INNER)
    assert EXPECTED_PY in inner
    assert EXPECTED_GLIBC in inner
    assert "--baseline-root /" in inner


def test_dockerfile_lists_desktop_runtime_prereqs() -> None:
    tokens = _docker_apt_tokens(_read_text(DOCKERFILE))
    assert tokens, "expected apt package tokens"
    assert set(tokens) >= DOCKER_22_RUNTIME
    for soname, package in SONAME_TO_22_PACKAGE.items():
        assert package in tokens, soname


def test_smoke_lists_equivalent_24_runtime_prereqs() -> None:
    script = smoke.smoke_script("Naga-Control-9.8.7-x86_64.AppImage", "9.8.7")
    tokens = _smoke_apt_tokens(script)
    assert tokens, "expected smoke apt package tokens"
    assert set(tokens) >= SMOKE_24_RUNTIME
    assert "libgtk-3-0t64" in tokens
    assert "libcups2t64" in tokens
    assert "libgtk-3-0" not in tokens
    assert "libcups2" not in tokens
    module_text = _read_text(SMOKE_MODULE)
    assert "ubuntu:24.04" in module_text
    assert "libwayland-cursor0" in tokens
    assert "libwayland-egl1" in tokens


def test_soname_to_package_correspondence_covers_gate_set() -> None:
    expected: set[str] = set((*WAYLAND_SONAMES, *XCB_SONAMES, "libgtk-3.so.0", *CUPS_SONAMES))
    assert expected <= set(SONAME_TO_22_PACKAGE)
    assert set(SONAME_TO_22_PACKAGE.values()) <= DOCKER_22_RUNTIME
    # GTK transitive members share the GTK runtime package; they are not
    # separately listed as apt packages.
    for transitive in (
        "libatk-1.0.so.0",
        "libcairo.so.2",
        "libgdk-3.so.0",
        "libharfbuzz.so.0",
        "libpango-1.0.so.0",
    ):
        assert transitive in GTK_SONAMES
    assert "libgtk-3-0" in DOCKER_22_RUNTIME
    assert "libgtk-3-0t64" in SMOKE_24_RUNTIME


def test_baseline_private_allow_remains_narrow() -> None:
    assert elf.BASELINE_PRIVATE_ALLOW == (
        "libc.so.6",
        "ld-linux-x86-64.so.2",
        "libm.so.6",
        "libresolv.so.2",
    )


def test_no_qt_platform_drop_or_dt_needed_ignore() -> None:
    payload_text = _read_text(PAYLOAD_MODULE)
    for retained in (
        "libqxcb.so",
        "libqwayland.so",
        "libqgtk3.so",
    ):
        assert retained in payload_text
    # Print support stays bundled by default: the trim removal list must not
    # contain the printsupport plugin directory as a standalone entry.
    assert '"printsupport",' not in payload_text
    assert '"platformthemes",' not in payload_text
    assert '"xcbglintegrations",' not in payload_text
    assert '"wayland-shell-integration",' not in payload_text
    assert '"wayland-graphics-integration-client",' not in payload_text
    assert '"wayland-decoration-client",' not in payload_text
    dependencies_text = _read_text(DEPENDENCIES_MODULE)
    assert "missing provider for" in dependencies_text
    assert "ignore" not in dependencies_text.lower()
    docker_text = _read_text(DOCKERFILE)
    assert "libqeglfs" not in docker_text
    script = smoke.smoke_script("Naga-Control-9.8.7-x86_64.AppImage", "9.8.7")
    assert "QT_QPA_PLATFORM=offscreen" in script


def test_smoke_runs_as_unprivileged_user_with_offscreen_contract() -> None:
    script = smoke.smoke_script("Naga-Control-9.8.7-x86_64.AppImage", "9.8.7")
    result = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "useradd --create-home --uid 10001 naga-smoke" in script
    assert 'runuser -u naga-smoke -- "$APPDIR/AppRun"' in script
    assert "QT_QPA_PLATFORM=offscreen" in script
    assert "from PySide6.QtWidgets import QApplication" in script
    assert '"${APP[@]}" service --help' in script
    assert '"${APP[@]}" capture --help' in script
    assert '"${APP[@]}" integration --help' in script
    assert "integration-payload-ok" in script
    assert "TemporaryDirectory" in script
    for forbidden in (
        "service --debug",
        "EVIOCGRAB",
        "/dev/uinput",
        "/dev/input",
        "--install",
    ):
        assert forbidden not in script
