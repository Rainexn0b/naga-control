from naga_control.gui.models import ConnectionState, ServiceModel, parse_snapshot


def test_parse_snapshot_reads_all_fields() -> None:
    view = parse_snapshot(
        '{"status":"available","generation":4,"transport":"hyperspeed","error":null}'
    )

    assert view.status == "available"
    assert view.generation == 4
    assert view.transport == "hyperspeed"
    assert view.error is None


def test_parse_snapshot_accepts_error_and_missing_transport() -> None:
    view = parse_snapshot('{"status":"failed","generation":2,"transport":null,"error":"boom"}')

    assert view.transport is None
    assert view.error == "boom"


def test_parse_snapshot_distinguishes_desired_and_observed_device_mode() -> None:
    view = parse_snapshot(
        '{"status":"unavailable","generation":2,"desired_mode":"firmware",'
        '"observed_mode":"software","mode_ready":false,"mode_error":"driver reasserted"}'
    )
    assert (view.desired_mode, view.observed_mode, view.mode_ready, view.mode_error) == (
        "firmware",
        "software",
        False,
        "driver reasserted",
    )


def test_parse_snapshot_reads_optional_observed_values() -> None:
    view = parse_snapshot(
        '{"status":"available","generation":6,"transport":"wired","error":null,'
        '"settings_failures":["scroll_mode: boom"],'
        '"observed":{"dpi":[1600,1600],"active_dpi_stage":2,"scroll_mode":"tactile",'
        '"scroll_acceleration":false,"scroll_smart_reel":true,'
        '"poll_rate":500,"battery_percent":88.0,"charging":false,"firmware_version":"v1.0"}}'
    )

    observed = view.observed
    assert observed.dpi == (1600, 1600)
    assert observed.active_dpi_stage == 2
    assert observed.scroll_mode == "tactile"
    assert observed.scroll_acceleration is False
    assert observed.scroll_smart_reel is True
    assert observed.poll_rate == 500
    assert observed.battery_percent == 88.0
    assert observed.charging is False
    assert observed.firmware_version == "v1.0"
    assert observed.settings_failures == ("scroll_mode: boom",)


def test_parse_snapshot_defaults_observed_when_absent() -> None:
    view = parse_snapshot('{"status":"absent","generation":0,"transport":null,"error":null}')

    assert view.calibrating is False
    assert parse_snapshot(
        '{"status":"available","generation":1,"transport":null,"error":null,"calibrating":true}'
    ).calibrating

    assert view.observed.dpi is None
    assert view.observed.scroll_acceleration is None
    assert view.observed.scroll_smart_reel is None
    assert view.observed.settings_failures == ()


def test_model_notifies_snapshot_and_configuration_changes() -> None:
    model = ServiceModel()
    notifications: list[str] = []
    model.add_listener(lambda: notifications.append("changed"))

    model.apply_snapshot(
        parse_snapshot('{"status":"available","generation":1,"transport":null,"error":null}')
    )

    assert model.connection.reachable
    assert model.snapshot is not None and model.snapshot.status == "available"
    assert notifications == ["changed"]

    model.apply_configuration(5, "doc")

    assert model.configuration_revision == 5
    assert model.configuration_document == "doc"
    assert notifications == ["changed", "changed"]


def test_model_suppresses_redundant_notifications() -> None:
    model = ServiceModel()
    notifications: list[bool] = []
    model.add_listener(lambda: notifications.append(True))
    view = parse_snapshot('{"status":"available","generation":1,"transport":null,"error":null}')

    model.apply_snapshot(view)
    model.apply_snapshot(view)
    model.apply_configuration(5, "doc")
    model.apply_configuration(5, "doc")
    model.mark_reachable()

    assert len(notifications) == 2


def test_model_tracks_unreachable_detail() -> None:
    model = ServiceModel()
    model.mark_unreachable("connection refused")

    assert model.connection == ConnectionState(reachable=False, detail="connection refused")

    model.mark_unreachable("connection refused")

    model.mark_reachable()

    assert model.connection == ConnectionState(reachable=True)


def test_configuration_revision_never_moves_backward_or_notifies_on_older_document() -> None:
    model = ServiceModel()
    notifications: list[bool] = []
    model.add_listener(lambda: notifications.append(True))

    model.apply_configuration(8, "new document")
    model.apply_configuration(7, "different older document")

    assert model.configuration_revision == 8
    assert model.configuration_document == "new document"
    assert notifications == [True]

    model.apply_configuration(9, "newest document")

    assert model.configuration_revision == 9
    assert model.configuration_document == "newest document"
    assert notifications == [True, True]
