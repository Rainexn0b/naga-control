from dataclasses import replace

from naga_control.domain.actions import KeyAction, KeyComboAction
from naga_control.domain.defaults import default_configuration
from naga_control.domain.intents import DeviceActionIntent, KeyOutputIntent
from naga_control.domain.profiles import Binding, Bindings, Profile, as_logical_control
from naga_control.service.action_dispatcher import ActionDispatcher


def test_ring_finger_emits_held_left_alt() -> None:
    dispatcher = ActionDispatcher(_profile())

    assert dispatcher.dispatch(as_logical_control("ring_finger"), 1).intents == (
        KeyOutputIntent("left_alt", 1),
    )
    assert dispatcher.dispatch(as_logical_control("ring_finger"), 2).intents == ()
    assert dispatcher.dispatch(as_logical_control("ring_finger"), 0).intents == (
        KeyOutputIntent("left_alt", 0),
    )


def test_release_uses_the_action_resolved_before_a_profile_change() -> None:
    dispatcher = ActionDispatcher(_profile())
    dispatcher.dispatch(as_logical_control("ring_finger"), 1)
    dispatcher.set_profile(
        _profile_with_common(Binding(as_logical_control("ring_finger"), KeyAction("f")))
    )

    result = dispatcher.dispatch(as_logical_control("ring_finger"), 0)

    assert result.intents == (KeyOutputIntent("left_alt", 0),)


def test_device_action_fires_only_on_press() -> None:
    dispatcher = ActionDispatcher(_profile())

    pressed = dispatcher.dispatch(as_logical_control("dpi_up"), 1)

    assert pressed.intents == (DeviceActionIntent("dpi_stage_up"),)
    assert dispatcher.dispatch(as_logical_control("dpi_up"), 2).intents == ()
    assert dispatcher.dispatch(as_logical_control("dpi_up"), 0).intents == ()


def test_two_controls_reference_count_the_same_key() -> None:
    dispatcher = ActionDispatcher(
        _profile_with_common(
            Binding(as_logical_control("ring_finger"), KeyAction("left_alt")),
            Binding(as_logical_control("top_front"), KeyAction("left_alt")),
        )
    )

    first = dispatcher.dispatch(as_logical_control("ring_finger"), 1)
    second = dispatcher.dispatch(as_logical_control("top_front"), 1)
    first_release = dispatcher.dispatch(as_logical_control("ring_finger"), 0)
    final_release = dispatcher.dispatch(as_logical_control("top_front"), 0)

    assert first.intents == (KeyOutputIntent("left_alt", 1),)
    assert second.intents == ()
    assert first_release.intents == ()
    assert final_release.intents == (KeyOutputIntent("left_alt", 0),)


def test_combo_presses_and_releases_in_order() -> None:
    dispatcher = ActionDispatcher(
        _profile_with_common(
            Binding(
                as_logical_control("ring_finger"),
                KeyComboAction(("left_ctrl", "left_shift"), "f"),
            )
        )
    )

    pressed = dispatcher.dispatch(as_logical_control("ring_finger"), 1)
    repeated = dispatcher.dispatch(as_logical_control("ring_finger"), 2)
    released = dispatcher.dispatch(as_logical_control("ring_finger"), 0)

    assert pressed.intents == (
        KeyOutputIntent("left_ctrl", 1),
        KeyOutputIntent("left_shift", 1),
        KeyOutputIntent("f", 1),
    )
    assert repeated.intents == (KeyOutputIntent("f", 2),)
    assert released.intents == (
        KeyOutputIntent("f", 0),
        KeyOutputIntent("left_shift", 0),
        KeyOutputIntent("left_ctrl", 0),
    )


def test_invalid_event_value_releases_outputs_and_marks_the_state_unsafe() -> None:
    dispatcher = ActionDispatcher(_profile())
    dispatcher.dispatch(as_logical_control("ring_finger"), 1)

    result = dispatcher.dispatch(as_logical_control("ring_finger"), 9)

    assert result.unsafe
    assert result.intents == (KeyOutputIntent("left_alt", 0),)


def test_release_all_releases_held_controls_in_reverse_press_order() -> None:
    dispatcher = ActionDispatcher(
        _profile_with_common(
            Binding(as_logical_control("ring_finger"), KeyAction("left_alt")),
            Binding(as_logical_control("top_front"), KeyAction("left_ctrl")),
        )
    )
    dispatcher.dispatch(as_logical_control("ring_finger"), 1)
    dispatcher.dispatch(as_logical_control("top_front"), 1)

    intents = dispatcher.release_all()

    assert intents == (KeyOutputIntent("left_ctrl", 0), KeyOutputIntent("left_alt", 0))
    assert dispatcher.release_all() == ()


def _profile() -> Profile:
    return default_configuration().profile("default")


def _profile_with_common(*common: Binding) -> Profile:
    profile = _profile()
    return replace(
        profile,
        bindings=Bindings(
            common=common,
            plate_2=profile.bindings.plate_2,
            plate_6=profile.bindings.plate_6,
            plate_12=profile.bindings.plate_12,
        ),
    )
