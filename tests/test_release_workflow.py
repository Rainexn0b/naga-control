"""Guard the small workflow graph without an undeclared YAML parser dependency."""

from __future__ import annotations

import re

from tests.release_assets_fakes import ROOT

WORKFLOW = (ROOT / ".github/workflows/release.yml").read_text()


def jobs() -> dict[str, str]:
    starts = list(re.finditer(r"^  ([a-z]+):$", WORKFLOW.split("jobs:\n", 1)[1], re.MULTILINE))
    body = WORKFLOW.split("jobs:\n", 1)[1]
    return {
        match[1]: body[
            match.end() : starts[index + 1].start() if index + 1 < len(starts) else len(body)
        ]
        for index, match in enumerate(starts)
    }


def test_metadata_blocks_both_read_only_independent_builds() -> None:
    graph = jobs()
    assert set(graph) == {"metadata", "appimage", "openrazer", "publish"}
    assert "permissions:\n  contents: read" in WORKFLOW
    for name in ("appimage", "openrazer"):
        assert "    needs: metadata\n" in graph[name]
        assert "contents: write" not in graph[name]
        assert "GH_TOKEN" not in graph[name]
        assert "gh release" not in graph[name]
        assert "actions/upload-artifact@v4" in graph[name]
    assert 'if [ "$GITHUB_EVENT_NAME" = push ]; then' in graph["metadata"]
    assert 'scripts/prepare_release.py "$GITHUB_REF_NAME"' in graph["metadata"]
    assert "--validation-only" in graph["metadata"]


def test_single_publisher_requires_both_successful_builds_and_only_tag_push() -> None:
    graph = jobs()
    publisher = graph["publish"]
    assert "needs: [metadata, appimage, openrazer]" in publisher
    assert "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')" in publisher
    assert "always()" not in WORKFLOW
    assert WORKFLOW.count("contents: write") == 1
    assert WORKFLOW.count("GH_TOKEN:") == 1
    assert "pattern: '*-release-assets'" in publisher
    assert publisher.index("scripts/validate_release_assets.py") < publisher.index("GH_TOKEN:")
    assert "scripts/publish_release_assets.py" in publisher
    for forbidden in ("pytest", "makepkg", "buildpython --profile", '-e ".[dev]"'):
        assert forbidden not in publisher


def test_all_checkouts_disable_persisted_credentials() -> None:
    assert WORKFLOW.count("actions/checkout@v4") == 4
    assert WORKFLOW.count("persist-credentials: false") == 4


def test_appimage_test_gate_provides_fixture_archive_reader() -> None:
    assert "libarchive-tools" in jobs()["appimage"]


def test_standard_ci_provides_fixture_archive_reader_and_installer_lock() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "libarchive-tools" in workflow
    assert "util-linux" in workflow


def test_arch_prerequisites_and_unprivileged_build_without_sudoers() -> None:
    package = jobs()["openrazer"]
    assert "run: python buildpython/openrazer_packages/pin.py" in package
    assert "source buildpython/openrazer_packages/pin.conf" not in package
    assert "sudoers" not in package
    assert "NOPASSWD" not in package
    assert "github-cli" not in package
    for dependency in (
        "clang",
        "llvm",
        "lld",
        "linux-headers",
        "linux-lts-headers",
        "python-setuptools",
        "python-daemonize",
        "python-pyudev",
        "python-setproctitle",
        "python-gobject",
        "dbus-python",
        "xautomation",
        "python-numpy",
    ):
        assert dependency in package
    assert "runuser -u builduser -- makepkg --verifysource" in package
    assert "runuser -u builduser -- makepkg --cleanbuild --log" in package
    assert "--packages-only --create-checksums --check-imports" in package
    assert 'make KERNELDIR="$header" LLVM=1 driver' in package
    assert 'make KERNELDIR="$header" driver' in package
    assert "modprobe" not in package


def test_appimage_validates_source_then_controlled_builder_then_smoke() -> None:
    appimage = jobs()["appimage"]
    assert ".venv/bin/python -m buildpython --profile full" in appimage
    assert "--profile release" not in appimage
    assert "buildpython/steps/appimage/portable-build.sh" in appimage
    assert '.venv/bin/python -m buildpython --run-steps "AppImage Smoke"' in appimage
    full_pos = appimage.index("--profile full")
    portable_pos = appimage.index("portable-build.sh")
    smoke_pos = appimage.index('--run-steps "AppImage Smoke"')
    stage_pos = appimage.index("Stage exactly one AppImage")
    assert full_pos < portable_pos < smoke_pos < stage_pos


def test_static_gate_precedes_any_bundled_execution_or_staging() -> None:
    appimage = jobs()["appimage"]
    assert "RELEASE_VERSION: ${{ needs.metadata.outputs.version }}" in appimage
    assert appimage.index("RELEASE_VERSION") < appimage.index("portable-build.sh")
    assert "build/appimage/AppDir/usr/bin/python3" not in appimage
    assert 'PYTHONHOME="$PWD/build/appimage' not in appimage
    assert "dist/Naga-Control-*-x86_64.AppImage" in appimage
    assert 'test "${#images[@]}" = 1' in appimage


def test_controlled_timeout_is_bounded_and_assets_unchanged() -> None:
    appimage = jobs()["appimage"]
    assert "timeout-minutes: 60" in appimage
    assert "timeout-minutes: 30" not in appimage
    assert WORKFLOW.count("actions/upload-artifact@v4") == 3
    assert "name: appimage-release-assets" in WORKFLOW
    assert "name: openrazer-release-assets" in WORKFLOW
    assert "name: release-metadata" in WORKFLOW
    assert "workflow_dispatch" in WORKFLOW
    assert "if: github.event_name == 'push'" in jobs()["publish"]
