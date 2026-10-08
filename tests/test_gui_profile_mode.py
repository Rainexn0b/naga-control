"""Presentation regressions use immutable snapshots, never a service or device."""

from dataclasses import replace

import pytest

from naga_control.config import dump_toml
from naga_control.domain.defaults import default_configuration
from naga_control.gui.models import ServiceModel, ServiceSnapshotView, parse_snapshot
from naga_control.gui.profile_mode_view import device_mode_view, software_profile_label


def _snapshot(**changes: object) -> ServiceSnapshotView:
    return replace(
        ServiceSnapshotView(
            "available",
            1,
            "wired",
            None,
            desired_mode="software",
            observed_mode="software",
            mode_ready=True,
        ),
        **changes,
    )


@pytest.mark.parametrize(
    ("snapshot", "requested", "observed", "remapping", "error"),
    [
        (
            _snapshot(),
            "Software / driver",
            "Software / driver",
            "Active (software mode verified)",
            None,
        ),
        (
            _snapshot(desired_mode="firmware", observed_mode="firmware"),
            "Onboard / firmware",
            "Onboard / firmware",
            "Off (onboard mode verified)",
            None,
        ),
        (
            _snapshot(desired_mode="firmware"),
            "Onboard / firmware",
            "Software / driver",
            "Not ready (requested/observed differ)",
            None,
        ),
        (
            _snapshot(observed_mode="firmware"),
            "Software / driver",
            "Onboard / firmware",
            "Not ready (requested/observed differ)",
            None,
        ),
        (_snapshot(mode_ready=False), "Software / driver", "Software / driver", "Not ready", None),
        (
            _snapshot(desired_mode="firmware", observed_mode="firmware", mode_ready=False),
            "Onboard / firmware",
            "Onboard / firmware",
            "Not ready",
            None,
        ),
        (
            _snapshot(observed_mode=None),
            "Software / driver",
            "Unknown",
            "Unknown (mode not verified)",
            None,
        ),
        (
            _snapshot(desired_mode=None),
            "Unknown",
            "Software / driver",
            "Unknown (mode not verified)",
            None,
        ),
        (
            _snapshot(observed_mode="unexpected"),
            "Software / driver",
            "Unknown",
            "Unknown (mode not verified)",
            None,
        ),
        (
            _snapshot(desired_mode="unexpected"),
            "Unknown",
            "Software / driver",
            "Unknown (mode not verified)",
            None,
        ),
        (
            _snapshot(status="unavailable"),
            "Software / driver",
            "Software / driver",
            "Not ready (device unavailable)",
            None,
        ),
        (
            _snapshot(mode_error="readback failed"),
            "Software / driver",
            "Software / driver",
            "Not ready (mode error)",
            "readback failed",
        ),
        (
            _snapshot(calibrating=True),
            "Software / driver",
            "Software / driver",
            "Off (calibration passthrough)",
            None,
        ),
        (
            _snapshot(desired_mode="firmware", observed_mode="firmware", calibrating=True),
            "Onboard / firmware",
            "Onboard / firmware",
            "Off (calibration passthrough)",
            None,
        ),
        (
            parse_snapshot('{"status":"available","generation":1}'),
            "Unknown",
            "Unknown",
            "Unknown (mode not verified)",
            None,
        ),
    ],
)
def test_requested_observed_and_remapping_are_separate(
    snapshot: ServiceSnapshotView, requested: str, observed: str, remapping: str, error: str | None
) -> None:
    model = ServiceModel()
    model.apply_snapshot(snapshot)
    view = device_mode_view(model)
    assert (view.requested, view.observed, view.remapping, view.error) == (
        requested,
        observed,
        remapping,
        error,
    )


@pytest.mark.parametrize("mode", ["software", "firmware"])
def test_offline_retained_ready_snapshot_is_not_current_readback(mode: str) -> None:
    model = ServiceModel()
    model.apply_snapshot(_snapshot(desired_mode=mode, observed_mode=mode, mode_error="old error"))
    model.mark_unreachable("disconnected")
    view = device_mode_view(model)
    assert "last known; offline" in view.requested
    assert view.observed == "Unknown (service offline)"
    assert view.remapping == "Unknown (service offline)"
    assert view.error == "Last known (offline): old error"


@pytest.mark.parametrize("snapshot", [False, True])
@pytest.mark.parametrize("online", [False, True])
def test_saved_policy_fallback_does_not_invent_observed_readiness(
    snapshot: bool, online: bool
) -> None:
    model = ServiceModel()
    # Legacy documents default to software, but cannot prove driver mode or remapping.
    document = dump_toml(default_configuration()).replace('mode = "software"\n', "", 1)
    model.apply_configuration(1, document)
    if snapshot:
        model.apply_snapshot(parse_snapshot('{"status":"available","generation":1}'))
    if online:
        model.mark_reachable()
    else:
        model.mark_unreachable("offline")
    view = device_mode_view(model)
    assert view.requested == (
        "Software / driver (saved configuration)"
        if online
        else "Software / driver (saved configuration; offline)"
    )
    assert view.observed == ("Unknown" if online else "Unknown (service offline)")
    assert not view.remapping.startswith("Active")


def test_absent_or_unreadable_configuration_is_unknown_and_snapshot_is_authoritative() -> None:
    model = ServiceModel()
    assert device_mode_view(model).requested == "Unknown"
    model.apply_configuration(1, "invalid toml = [")
    assert device_mode_view(model).requested == "Unknown"
    model.apply_snapshot(_snapshot(desired_mode="firmware", observed_mode="firmware"))
    assert device_mode_view(model).requested == "Onboard / firmware"
    assert model.configuration_document == "invalid toml = ["


def test_saved_firmware_policy_alone_is_not_a_verified_handoff() -> None:
    model = ServiceModel()
    model.apply_configuration(1, dump_toml(replace(default_configuration(), mode="firmware")))
    model.mark_reachable()
    view = device_mode_view(model)
    assert view.requested == "Onboard / firmware (saved configuration)"
    assert view.observed == "Unknown"
    assert view.remapping == "Unknown (no mode status)"


def test_profile_labels_disambiguate_names_without_breaking_identifier_suffix() -> None:
    assert software_profile_label("Same", "first") == "Same (first)"
    assert software_profile_label("Same", "second") == "Same (second)"
    assert software_profile_label("Name (extra)", "third").endswith("(third)")
