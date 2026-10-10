import pytest

from naga_control.domain.actions import (
    DeviceAction,
    DisabledAction,
    KeyAction,
    KeyComboAction,
    MouseButtonAction,
)
from naga_control.domain.errors import ConfigValidationError
from naga_control.gui.actions_view import (
    action_kind,
    control_display_name,
    controls_for_layout,
    format_action_detail,
    parse_action,
)


def test_kind_and_detail_round_trip_every_action_shape() -> None:
    actions = [
        DisabledAction(),
        KeyAction(key="f12"),
        KeyComboAction(modifiers=("left_ctrl", "left_shift"), key="t"),
        MouseButtonAction(button="back"),
        DeviceAction(action="dpi_stage_up"),
    ]
    for action in actions:
        rebuilt = parse_action(action_kind(action), format_action_detail(action))
        assert rebuilt == action


def test_parse_action_rejects_invalid_input() -> None:
    with pytest.raises(ConfigValidationError):
        parse_action("key", "")
    with pytest.raises(ConfigValidationError):
        parse_action("key_combo", "t")
    with pytest.raises(ConfigValidationError):
        parse_action("key_combo", "not_a_modifier+t")
    with pytest.raises(ConfigValidationError):
        parse_action("mouse_button", "wheel")
    with pytest.raises(ConfigValidationError):
        parse_action("device", "make_coffee")
    with pytest.raises(ConfigValidationError):
        parse_action("magic", "x")


def test_control_display_names_are_human_readable() -> None:
    assert control_display_name("dpi_up") == "DPI up"
    assert control_display_name("side_12_3") == "Side 3 (12-button plate)"
    assert control_display_name("side_2_front") == "Side front"
    assert control_display_name("unknown_control") == "unknown_control"


def test_controls_for_layout_lists_common_then_plate() -> None:
    controls = controls_for_layout(6)

    assert controls[0] == "dpi_down"
    assert len(controls) == 7 + 6
    assert "side_6_6" in controls
    assert "side_12_1" not in controls


def test_parse_action_normalizes_bracket_literals() -> None:
    assert parse_action("key", "[") == KeyAction(key="left_brace")
    assert parse_action("key", "]") == KeyAction(key="right_brace")
    assert parse_action("key_combo", "left_ctrl+]") == KeyComboAction(
        modifiers=("left_ctrl",), key="right_brace"
    )


def test_parse_action_rejects_unsupported_literal() -> None:
    with pytest.raises(ConfigValidationError):
        parse_action("key", "$")


def test_parse_key_normalizes_equal_and_minus_literals() -> None:
    assert parse_action("key", "=") == KeyAction(key="equal")
    assert parse_action("key", "-") == KeyAction(key="minus")
    assert action_kind(parse_action("key", "=")) == "key"


def test_parse_key_infers_complete_modifier_chord() -> None:
    assert parse_action("key", "left_ctrl+left_shift+8") == KeyComboAction(
        modifiers=("left_ctrl", "left_shift"), key="8"
    )
    assert parse_action("key", "left_ctrl+left_shift+tab") == KeyComboAction(
        modifiers=("left_ctrl", "left_shift"), key="tab"
    )
    assert parse_action("key", "left_ctrl+t") == KeyComboAction(modifiers=("left_ctrl",), key="t")


def test_parse_key_infers_literal_final_token() -> None:
    assert parse_action("key", "left_ctrl+=") == KeyComboAction(
        modifiers=("left_ctrl",), key="equal"
    )
    assert parse_action("key", "left_ctrl+-") == KeyComboAction(
        modifiers=("left_ctrl",), key="minus"
    )
    assert parse_action("key", "left_ctrl+]") == KeyComboAction(
        modifiers=("left_ctrl",), key="right_brace"
    )


def test_parse_key_does_not_infer_incomplete_or_invalid_chord() -> None:
    for detail in (
        "left_ctrl+left_shift",
        "left_ctrl+",
        "left_ctrl+ ",
        "not_a_modifier+t",
        "left_ctrl+$",
    ):
        with pytest.raises(ConfigValidationError):
            parse_action("key", detail)
    # A bare modifier pair must not silently become a combo.
    with pytest.raises(ConfigValidationError):
        parse_action("key", "left_ctrl+left_shift")
