from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_release.py"
SPEC = importlib.util.spec_from_file_location("prepare_release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def write_project(tmp_path: Path, version: str, changelog: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "naga-control"\nversion = "{version}"\n', encoding="utf-8"
    )
    (tmp_path / "changelog.md").write_text(changelog, encoding="utf-8")


def arguments(tmp_path: Path, tag: str) -> list[str]:
    return [
        tag,
        "--project-root",
        str(tmp_path),
        "--notes-output",
        str(tmp_path / "notes.md"),
        "--github-output",
        str(tmp_path / "outputs"),
    ]


@pytest.mark.parametrize(
    ("tag", "package_version", "entry_version", "normalized", "prerelease"),
    [
        ("v0.3.0", "0.3.0", "0.3.0", "0.3.0", "false"),
        ("v0.4.0rc1", "0.4.0rc1", "0.4.0rc1", "0.4.0rc1", "true"),
        ("v0.4.0-rc.1", "0.4.0rc1", "0.4.0-rc.1", "0.4.0rc1", "true"),
        ("v0.4.0-beta.2", "0.4.0b2", "0.4.0b2", "0.4.0b2", "true"),
        ("v0.4.0-dev.1", "0.4.0.dev1", "0.4.0.dev1", "0.4.0.dev1", "true"),
        ("v0.3.0.post1", "0.3.0.post1", "0.3.0.post1", "0.3.0.post1", "false"),
    ],
)
def test_release_classification_and_normalization(
    tmp_path: Path,
    tag: str,
    package_version: str,
    entry_version: str,
    normalized: str,
    prerelease: str,
) -> None:
    write_project(
        tmp_path, package_version, f"## [{entry_version}] - 2026-10-03\n\n- Current changes.\n"
    )
    assert release.main(arguments(tmp_path, tag)) == 0
    assert (tmp_path / "outputs").read_text() == (
        f"version={normalized}\nprerelease={prerelease}\nlatest=false\n"
    )
    assert "- Current changes." in (tmp_path / "notes.md").read_text()


def test_extracts_only_matching_body_preserving_subheadings(tmp_path: Path) -> None:
    body = "### Added\n\n- Current changes.\n\n### Fixed\n\n- Current fixes."
    write_project(
        tmp_path,
        "0.3.0",
        "# Changelog\n\n## [Unreleased]\n\nFuture changes.\n\n"
        f"## [0.3.0] - 2026-10-03\n\n{body}\n\n"
        "## [0.2.0] - 2026-09-29\n\nOld changes.\n",
    )
    release.main(arguments(tmp_path, "v0.3.0"))
    notes = (tmp_path / "notes.md").read_text()
    assert notes.startswith(body + "\n\n")
    assert "Future changes" not in notes
    assert "Old changes" not in notes
    assert "# Changelog" not in notes


def test_prerequisites_are_added_without_duplicating_existing_content(tmp_path: Path) -> None:
    baseline = "2416bfebf0175db6aae519a450f55fe9eba255e9"
    body = (
        f"- Custom OpenRazer baseline `{baseline}`.\n"
        "- Wired `1532:00E7` and HyperSpeed `1532:00E8`, one transport\n  at a time.\n"
    )
    write_project(tmp_path, "0.3.0", f"## [0.3.0] - 2026-10-03\n\n{body}")
    release.main(arguments(tmp_path, "v0.3.0"))
    notes = (tmp_path / "notes.md").read_text()
    assert notes.count(baseline) == 1
    assert notes.count("1532:00E7") == 1
    assert notes.count("1532:00E8") == 1
    assert "Do not run the GUI or service as root." in notes


def test_complete_prerequisites_leave_entry_unchanged(tmp_path: Path) -> None:
    body = "\n".join(f"- {text}" for _, text in release.HARDWARE_PREREQUISITES) + "\n"
    write_project(tmp_path, "0.3.0", f"## [0.3.0] - 2026-10-03\n\n{body}")
    release.main(arguments(tmp_path, "v0.3.0"))
    assert (tmp_path / "notes.md").read_text() == body


@pytest.mark.parametrize(
    ("tag", "version", "changelog", "error"),
    [
        ("v0.3.0", "0.2.0", "", "does not match package version"),
        ("v0.3.0", "0.3.0", "## [0.2.0] - 2026-09-29\nOld.\n", "Missing dated"),
        ("v0.3.0", "0.3.0", "## [0.3.0]\nUndated.\n", "Missing dated"),
        ("v0.3.0", "0.3.0", "## [0.3.0] - 2026-10-03\n\n", "Empty changelog"),
        (
            "v0.3.0",
            "0.3.0",
            "## [0.3.0] - 2026-10-03\n\n## [0.2.0] - 2026-09-29\nOld.\n",
            "Empty changelog",
        ),
        ("v0.3.0", "0.3.0", "## [0.3.0] - 2026-10-03\n### Added\n", "Empty changelog"),
        (
            "v0.3.0",
            "0.3.0",
            "## [0.3.0] - 2026-10-03\nOne.\n## [0.3.0] - 2026-10-03\nTwo.\n",
            "Multiple changelog",
        ),
    ],
)
def test_rejects_unprepared_releases(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    tag: str,
    version: str,
    changelog: str,
    error: str,
) -> None:
    write_project(tmp_path, version, changelog)
    with pytest.raises(SystemExit) as caught:
        release.main(arguments(tmp_path, tag))
    assert caught.value.code == 2
    assert error in capsys.readouterr().err
    assert not (tmp_path / "notes.md").exists()
    assert not (tmp_path / "outputs").exists()


@pytest.mark.parametrize(
    "tag", ["", "0.3.0", "v", "vgarbage", "vv0.3.0", "v0.3.0-preview.x", "v0.3.0\n"]
)
def test_rejects_invalid_tags(tmp_path: Path, capsys: pytest.CaptureFixture[str], tag: str) -> None:
    write_project(tmp_path, "0.3.0", "## [0.3.0] - 2026-10-03\nChanges.\n")
    with pytest.raises(SystemExit) as caught:
        release.main(arguments(tmp_path, tag))
    assert caught.value.code == 2
    assert "Invalid release tag" in capsys.readouterr().err
    assert not (tmp_path / "notes.md").exists()


def test_appends_to_github_output_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_project(tmp_path, "0.3.0", "## [0.3.0] - 2026-10-03\nChanges.\n")
    output = tmp_path / "outputs"
    output.write_text("previous=value\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    release.main(arguments(tmp_path, "v0.3.0")[:-2])
    assert output.read_text() == "previous=value\nversion=0.3.0\nprerelease=false\nlatest=false\n"


@pytest.mark.parametrize(
    ("version", "published", "latest"),
    [
        ("0.3.0", "v0.4.0\n", "false"),
        ("0.3.0", "v0.2.0\n", "true"),
        ("0.3.0", "v0.2.0\nv0.3.0\n", "true"),
        ("0.3.0", "", "true"),
        ("0.10.0", "v0.9.0\n", "true"),
        ("0.9.0", "v0.10.0\n", "false"),
        ("0.3.0", "v0.2.0\nv0.4.0\nv0.1.4\n", "false"),
        ("0.3.0", "v0.4.0-rc.1\nv0.5.0.dev1\nv0.6.0-beta.2\n", "true"),
        ("0.3.0", "junk\nv0.7.0-preview.x\n\nv0.2.0\n", "true"),
        ("0.4.0rc1", "v0.3.0\n", "false"),
        ("0.4.0rc1", "", "false"),
        ("0.4.0.dev1", "", "false"),
    ],
)
def test_latest_promotion_uses_published_stable_versions(
    tmp_path: Path, version: str, published: str, latest: str
) -> None:
    write_project(tmp_path, version, f"## [{version}] - 2026-10-03\nChanges.\n")
    tags = tmp_path / "published-tags.txt"
    tags.write_text(published, encoding="utf-8")
    release.main([*arguments(tmp_path, f"v{version}"), "--published-tags", str(tags)])
    assert (tmp_path / "outputs").read_text().endswith(f"latest={latest}\n")


def test_missing_published_tags_file_fails_without_output(tmp_path: Path) -> None:
    write_project(tmp_path, "0.3.0", "## [0.3.0] - 2026-10-03\nChanges.\n")
    with pytest.raises(SystemExit) as caught:
        release.main(
            [*arguments(tmp_path, "v0.3.0"), "--published-tags", str(tmp_path / "missing.txt")]
        )
    assert caught.value.code == 2
    assert not (tmp_path / "notes.md").exists()
    assert not (tmp_path / "outputs").exists()


@pytest.mark.parametrize(
    ("tag", "version", "quoted_tag"),
    [
        ("v0.3.0", "0.3.0", "v0.3.0"),
        ("v0.4.0-rc.1+build.1", "0.4.0rc1+build.1", "v0.4.0-rc.1%2Bbuild.1"),
    ],
)
def test_repository_links_are_pinned_to_requested_tag(
    tmp_path: Path, tag: str, version: str, quoted_tag: str
) -> None:
    body = (
        "[Hardware](docs/hardware-validation.md)\n"
        '[Install](./README.md#install "Installation")\n'
        "[Overview](<docs/architecture.md>)\n"
        "[Details][details]\n\n"
        "[details]: docs/integration-findings.md?plain=1#openrazer-baseline\n"
    )
    write_project(
        tmp_path,
        version,
        f"## [{version}] - 2026-10-03\n{body}\n## [0.2.0] - 2026-09-29\n[Old](docs/old.md)\n",
    )
    release.main(arguments(tmp_path, tag))
    notes = (tmp_path / "notes.md").read_text()
    base = f"https://github.com/Rainexn0b/naga-control/blob/{quoted_tag}"
    assert f"[Hardware]({base}/docs/hardware-validation.md)" in notes
    assert f'[Install]({base}/README.md#install "Installation")' in notes
    assert f"[Overview](<{base}/docs/architecture.md>)" in notes
    assert f"[details]: {base}/docs/integration-findings.md?plain=1#openrazer-baseline" in notes
    assert "/blob/v0.2.0/" not in notes
    assert "docs/old.md" not in notes


def test_non_repository_links_are_unchanged(tmp_path: Path) -> None:
    body = (
        "[Web](https://example.org/docs.md)\n"
        "[HTTP](http://example.org/docs.md)\n"
        "[Anchor](#hardware)\n"
        "[Mail](mailto:hello@example.org)\n"
        "[FTP](ftp://example.org/docs.md)\n"
        "[Shared](//example.org/docs.md)\n"
        "[Outside](../outside.md)\n"
    )
    write_project(tmp_path, "0.3.0", f"## [0.3.0] - 2026-10-03\n{body}")
    release.main(arguments(tmp_path, "v0.3.0"))
    assert (tmp_path / "notes.md").read_text().startswith(body)
