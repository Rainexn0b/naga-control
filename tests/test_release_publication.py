from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from buildpython.openrazer_packages import validation
from buildpython.openrazer_packages.pin import read_pin
from scripts import publish_release_assets as publisher
from scripts import validate_release_assets as release
from scripts.prepare_release import prepare_release
from tests.release_assets_fakes import PIN_PATH, archive_reader, write_assets, write_project
from tests.release_publication_fakes import FakeGh, change_version, copy_assets


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    project.mkdir()
    write_project(project)
    directory = tmp_path / "assets"
    write_assets(directory, read_pin(PIN_PATH))
    notes = tmp_path / "notes.md"
    notes.write_text(prepare_release("v0.4.0", project)[1])

    def packages(directory: Path, pin: dict[str, str]) -> tuple[Path, ...]:
        return validation.validate_packages(directory, pin, reader=archive_reader)

    monkeypatch.setattr(release, "validate_packages", packages)
    return project, directory, notes


def publish(
    prepared: tuple[Path, Path, Path], call: FakeGh, event: str = "push", tag: str = "v0.4.0"
) -> str:
    project, directory, notes = prepared
    return publisher.publish(
        tag, project, directory, notes, "Rainexn0b/naga-control", event=event, call=call
    )


@pytest.mark.parametrize("state", [None, True])
def test_absent_or_draft_release_uploaded_verified_then_published(
    prepared: tuple[Path, Path, Path],
    state: bool | None,
) -> None:
    fake = FakeGh("v0.4.0", state)
    assert "verified and published" in publish(prepared, fake)
    assert fake.release is not None and not fake.release["draft"]
    assert fake.remote == copy_assets(prepared[1])
    upload = next(
        index for index, command in enumerate(fake.commands) if command[:2] == ["release", "upload"]
    )
    download = next(
        index
        for index, command in enumerate(fake.commands)
        if command[:2] == ["release", "download"]
    )
    edit = next(
        index for index, command in enumerate(fake.commands) if command[:2] == ["release", "edit"]
    )
    assert upload < download < edit
    assert "--clobber" not in fake.commands[upload]


def test_draft_reconciles_all_stale_and_partial_assets(prepared: tuple[Path, Path, Path]) -> None:
    remote = {"old-version.pkg.tar.zst": b"old", "unknown.txt": b"old"}
    first_asset = next(iter(copy_assets(prepared[1])))
    remote[first_asset] = b"previous partial upload"
    fake = FakeGh("v0.4.0", True, remote)
    publish(prepared, fake)
    deletes = [command for command in fake.commands if command[:3] == ["api", "--method", "DELETE"]]
    assert len(deletes) == 3
    assert fake.remote == copy_assets(prepared[1])


def test_identical_completed_release_verified_noop(prepared: tuple[Path, Path, Path]) -> None:
    fake = FakeGh("v0.4.0", False, copy_assets(prepared[1]))
    assert "no changes made" in publish(prepared, fake)
    assert fake.mutations() == []
    assert any(command[:2] == ["release", "download"] for command in fake.commands)


@pytest.mark.parametrize("divergence", ["partial", "stale", "bytes"])
def test_public_release_is_immutable_even_with_old_or_partial_assets(
    prepared: tuple[Path, Path, Path],
    divergence: str,
) -> None:
    remote = copy_assets(prepared[1])
    if divergence == "partial":
        remote.pop(next(iter(remote)))
    elif divergence == "stale":
        remote["old-version.pkg.tar.zst"] = b"old"
    else:
        remote[next(iter(remote))] = b"different bytes"
    fake = FakeGh("v0.4.0", False, remote)
    with pytest.raises(ValueError, match="immutable; use a new tag"):
        publish(prepared, fake)
    assert fake.mutations() == []


def test_upload_failure_remains_draft_and_rerun_recovers(prepared: tuple[Path, Path, Path]) -> None:
    fake = FakeGh("v0.4.0", None)
    fake.fail_upload = True
    with pytest.raises(subprocess.CalledProcessError):
        publish(prepared, fake)
    assert fake.release is not None and fake.release["draft"]
    assert len(fake.remote) == 1
    assert all(command[:2] != ["release", "edit"] for command in fake.commands)
    fake.fail_upload = False
    publish(prepared, fake)
    assert fake.remote == copy_assets(prepared[1])
    assert not fake.release["draft"]


def test_failed_remote_verification_does_not_publish(prepared: tuple[Path, Path, Path]) -> None:
    fake = FakeGh("v0.4.0", True)
    fake.corrupt_download = True
    with pytest.raises(ValueError, match="bytes differ"):
        publish(prepared, fake)
    assert fake.release is not None and fake.release["draft"]
    assert all(command[:2] != ["release", "edit"] for command in fake.commands)


@pytest.mark.parametrize("event", ["workflow_dispatch", "pull_request", ""])
def test_dispatch_never_publishes_even_on_tag_ref(
    prepared: tuple[Path, Path, Path],
    event: str,
) -> None:
    fake = FakeGh("v0.4.0", None)
    with pytest.raises(ValueError, match="forbidden"):
        publish(prepared, fake, event)
    assert fake.commands == []


@pytest.mark.parametrize("bad", ["missing-asset", "notes", "tag"])
def test_preconditions_block_all_gh_operations(prepared: tuple[Path, Path, Path], bad: str) -> None:
    fake = FakeGh("v0.4.0", None)
    if bad == "missing-asset":
        (prepared[1] / release.APPIMAGE).unlink()
    elif bad == "notes":
        prepared[2].write_text("wrong notes")
    with pytest.raises(ValueError):
        publish(prepared, fake, tag="v9.9.9" if bad == "tag" else "v0.4.0")
    assert fake.commands == []


def test_failed_release_read_is_not_absent(prepared: tuple[Path, Path, Path]) -> None:
    fake = FakeGh("v0.4.0", None)
    fake.fail_read = True
    with pytest.raises(subprocess.CalledProcessError):
        publish(prepared, fake)
    assert fake.mutations() == []


@pytest.mark.parametrize(
    ("version", "previous", "latest", "prerelease"),
    [
        ("0.4.0", "v0.5.0", False, False),
        ("0.4.0", "v0.3.0", True, False),
        ("0.4.0", "v0.5.0rc1", True, False),
        ("0.4.0rc1", "v0.3.0", False, True),
    ],
)
def test_publisher_preserves_latest_and_prerelease_promotion_policy(
    prepared: tuple[Path, Path, Path],
    version: str,
    previous: str,
    latest: bool,
    prerelease: bool,
) -> None:
    project, _, notes = prepared
    change_version(project, version)
    tag = f"v{version}"
    notes.write_text(prepare_release(tag, project)[1])
    fake = FakeGh(tag, None)
    fake.previous = [{"tag_name": previous, "draft": False, "prerelease": "rc" in previous}]
    publish(prepared, fake, tag=tag)
    edit = next(command for command in fake.commands if command[:2] == ["release", "edit"])
    assert f"--latest={str(latest).lower()}" in edit
    assert f"--prerelease={str(prerelease).lower()}" in edit


def test_draft_resolution_uses_release_id_not_tag_endpoint(
    prepared: tuple[Path, Path, Path],
) -> None:
    for state in (None, True):
        fake = FakeGh("v0.4.0", state)
        publish(prepared, fake)
        assert any(
            command[0] == "api" and len(command) == 2 and "/releases/408962506" in command[1]
            for command in fake.commands
        )
        assert not any("/releases/tags/" in " ".join(command) for command in fake.commands)


def test_fake_tag_endpoint_404_and_unknown_id_rejected() -> None:
    fake = FakeGh("v0.4.0", True)
    with pytest.raises(subprocess.CalledProcessError):
        fake(["api", "repos/Rainexn0b/naga-control/releases/tags/v0.4.0"])
    with pytest.raises(subprocess.CalledProcessError):
        fake(["api", "repos/Rainexn0b/naga-control/releases/999999999"])


@pytest.mark.parametrize("bad", ["missing", "bool", "str", "zero", "negative", "wrongtag"])
def test_fresh_listing_with_invalid_id_refuses_upload(
    prepared: tuple[Path, Path, Path], bad: str
) -> None:
    fake = FakeGh("v0.4.0", None)
    fake.fresh_bad = bad
    with pytest.raises(ValueError, match=r"identifier|mismatch|lookup|Fresh"):
        publish(prepared, fake)
    assert all(command[:2] != ["release", "upload"] for command in fake.commands)
    assert all(command[:2] != ["release", "edit"] for command in fake.commands)
    assert not any(command[:3] == ["api", "--method", "DELETE"] for command in fake.commands)


@pytest.mark.parametrize("bad", ["missing", "bool", "str", "zero", "negative"])
def test_existing_draft_with_invalid_id_refuses_mutation(
    prepared: tuple[Path, Path, Path], bad: str
) -> None:
    fake = FakeGh("v0.4.0", True)
    assert fake.release is not None
    if bad == "missing":
        del fake.release["id"]
    elif bad == "bool":
        fake.release["id"] = True
    elif bad == "str":
        fake.release["id"] = "408962506"
    elif bad == "zero":
        fake.release["id"] = 0
    else:
        fake.release["id"] = -7
    with pytest.raises(ValueError, match=r"identifier|mismatch"):
        publish(prepared, fake)
    assert fake.mutations() == []


def test_fresh_relist_failure_refuses_upload(prepared: tuple[Path, Path, Path]) -> None:
    fake = FakeGh("v0.4.0", None)
    fake.fail_relist = True
    with pytest.raises(subprocess.CalledProcessError):
        publish(prepared, fake)
    assert all(command[:2] != ["release", "upload"] for command in fake.commands)
    assert all(command[:2] != ["release", "edit"] for command in fake.commands)


def test_id_fetch_failure_refuses_upload(prepared: tuple[Path, Path, Path]) -> None:
    fake = FakeGh("v0.4.0", True)
    fake.fail_fetch = True
    with pytest.raises(subprocess.CalledProcessError):
        publish(prepared, fake)
    assert all(command[:2] != ["release", "upload"] for command in fake.commands)
    assert all(command[:2] != ["release", "edit"] for command in fake.commands)


def test_ambiguous_fresh_listing_refuses_unknown_release(
    prepared: tuple[Path, Path, Path],
) -> None:
    fake = FakeGh("v0.4.0", None)
    fake.duplicate_after_create = True
    with pytest.raises(ValueError, match="Ambiguous"):
        publish(prepared, fake)
    assert [command[1] for command in fake.mutations()] == ["create"]


def test_public_race_before_first_delete_refuses_mutation(
    prepared: tuple[Path, Path, Path],
) -> None:
    remote = {"old-version.pkg.tar.zst": b"old", "unknown.txt": b"old"}
    first_asset = next(iter(copy_assets(prepared[1])))
    remote[first_asset] = b"previous partial upload"
    expected = set(remote)
    fake = FakeGh("v0.4.0", True, remote)
    fake.public_on_fetch = 2
    with pytest.raises(ValueError, match=r"no longer a draft|became public"):
        publish(prepared, fake)
    assert not any(command[:3] == ["api", "--method", "DELETE"] for command in fake.commands)
    assert all(command[:2] != ["release", "upload"] for command in fake.commands)
    assert all(command[:2] != ["release", "edit"] for command in fake.commands)
    assert set(fake.remote) == expected


def test_public_race_before_upload_refuses_upload(
    prepared: tuple[Path, Path, Path],
) -> None:
    fake = FakeGh("v0.4.0", True)
    fake.public_on_fetch = 2
    with pytest.raises(ValueError, match=r"no longer a draft|became public"):
        publish(prepared, fake)
    assert all(command[:2] != ["release", "upload"] for command in fake.commands)
    assert all(command[:2] != ["release", "edit"] for command in fake.commands)


def test_public_race_after_upload_refuses_publication(
    prepared: tuple[Path, Path, Path],
) -> None:
    fake = FakeGh("v0.4.0", True)
    fake.public_on_fetch = 3
    with pytest.raises(ValueError, match="must remain a draft"):
        publish(prepared, fake)
    assert any(command[:2] == ["release", "upload"] for command in fake.commands)
    assert all(command[:2] != ["release", "edit"] for command in fake.commands)


@pytest.mark.parametrize("bad", ["missing_id", "bool_id", "str_id", "wrong_id", "wrongtag"])
def test_checked_fetch_mismatch_refuses_mutation(
    prepared: tuple[Path, Path, Path], bad: str
) -> None:
    fake = FakeGh("v0.4.0", True)
    fake.fetch_bad = bad
    with pytest.raises(ValueError, match=r"identifier|mismatch"):
        publish(prepared, fake)
    assert fake.mutations() == []


@pytest.mark.parametrize("bad", ["draft_1", "draft_true", "draft_false", "draft_none"])
def test_nonbool_draft_fetch_refuses_mutation(prepared: tuple[Path, Path, Path], bad: str) -> None:
    fake = FakeGh("v0.4.0", True)
    fake.fetch_bad = bad
    with pytest.raises(ValueError, match=r"no longer a draft|became public"):
        publish(prepared, fake)
    assert fake.mutations() == []


def test_public_race_at_final_fetch_refuses_edit(
    prepared: tuple[Path, Path, Path],
) -> None:
    fake = FakeGh("v0.4.0", True)
    fake.public_on_fetch = 4
    with pytest.raises(ValueError, match=r"became public"):
        publish(prepared, fake)
    assert any(command[:2] == ["release", "upload"] for command in fake.commands)
    assert any(command[:2] == ["release", "download"] for command in fake.commands)
    assert all(command[:2] != ["release", "edit"] for command in fake.commands)
