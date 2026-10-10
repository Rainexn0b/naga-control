"""Domain key-token vocabulary: unsupported keys fail at construction time."""

import pytest

from naga_control.domain.actions import (
    MODIFIER_KEYS,
    OUTPUT_KEY_TOKENS,
    KeyAction,
    KeyComboAction,
)
from naga_control.domain.errors import ConfigValidationError
from naga_control.gui.actions_view import parse_action


def test_key_action_rejects_an_out_of_vocabulary_token() -> None:
    with pytest.raises(ConfigValidationError) as error:
        KeyAction("f13")

    assert error.value.field_path == "key"
    assert "'f13'" in error.value.message


def test_key_combo_rejects_an_out_of_vocabulary_final_key() -> None:
    with pytest.raises(ConfigValidationError) as error:
        KeyComboAction(("left_ctrl",), "f13")

    assert error.value.field_path == "key"
    assert "'f13'" in error.value.message


def test_key_action_rejects_a_typo_token() -> None:
    with pytest.raises(ConfigValidationError) as error:
        KeyAction("foo")

    assert error.value.field_path == "key"
    assert "'foo'" in error.value.message


def test_every_vocabulary_token_constructs_and_covers_modifiers() -> None:
    assert MODIFIER_KEYS <= OUTPUT_KEY_TOKENS
    assert len(OUTPUT_KEY_TOKENS) == 75
    for token in OUTPUT_KEY_TOKENS:
        assert KeyAction(token).key == token


def test_standalone_and_combo_use_of_modifiers_stays_valid() -> None:
    assert KeyAction("left_alt").key == "left_alt"
    assert KeyComboAction(("left_ctrl",), "left_alt").key == "left_alt"


def test_syntax_errors_keep_their_messages_before_vocabulary_checks() -> None:
    with pytest.raises(ConfigValidationError, match="lowercase"):
        KeyAction("F13")
    with pytest.raises(ConfigValidationError, match="KEY_"):
        KeyAction("key_a")


def test_parse_action_rejects_out_of_vocabulary_tokens() -> None:
    with pytest.raises(ConfigValidationError):
        parse_action("key", "f13")
    with pytest.raises(ConfigValidationError):
        parse_action("key", "left_ctrl+f13")
    with pytest.raises(ConfigValidationError):
        parse_action("key_combo", "left_ctrl+f13")
