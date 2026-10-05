import tomllib
from collections.abc import Mapping
from typing import Literal, cast

from naga_control.domain.actions import (
    Action,
    DeviceAction,
    DeviceActionToken,
    DisabledAction,
    KeyAction,
    KeyComboAction,
    MouseButtonAction,
)
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.hardware import DeviceMode
from naga_control.domain.profiles import (
    COMMON_CONTROL_IDS,
    PLATE_CONTROL_IDS,
    PROFILE_ID_RE,
    Binding,
    Bindings,
    Configuration,
    DpiSettings,
    DpiStage,
    LightingEffect,
    LightingSettings,
    LightingZone,
    PowerSettings,
    Profile,
    ScrollSettings,
    as_logical_control,
)

ROOT_FIELDS = frozenset(
    {"schema_version", "revision", "default_profile", "active_profile", "profiles", "mode"}
)
ROOT_OPTIONAL_FIELDS = frozenset({"mode"})
PROFILE_FIELDS = frozenset(
    {"display_name", "plate_layout", "bindings", "dpi", "scroll", "lighting", "power", "poll_rate"}
)
PROFILE_OPTIONAL_FIELDS = frozenset({"poll_rate"})


def parse_toml(document: str) -> Configuration:
    try:
        raw = tomllib.loads(document)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigValidationError("document", f"invalid TOML: {exc}") from exc
    root = _table(raw, "root")
    _fields(root, ROOT_FIELDS, "root", optional=ROOT_OPTIONAL_FIELDS)
    _integer(_required(root, "schema_version", "root"), "schema_version", 1, 1)
    revision = _integer(_required(root, "revision", "root"), "revision", 0, 2**63 - 1)
    default_profile = _slug(_required(root, "default_profile", "root"), "default_profile")
    active_profile = _slug(_required(root, "active_profile", "root"), "active_profile")
    mode = _string(root.get("mode", "software"), "mode")
    if mode not in {"software", "firmware"}:
        raise ConfigValidationError("mode", "must be software or firmware")
    profile_table = _table(_required(root, "profiles", "root"), "profiles")
    if not profile_table:
        raise ConfigValidationError("profiles", "must contain at least one profile")
    profiles = tuple(
        (_slug(identifier, "profiles"), _parse_profile(value, f"profiles.{identifier}"))
        for identifier, value in profile_table.items()
    )
    return Configuration(
        revision, default_profile, active_profile, profiles, mode=cast(DeviceMode, mode)
    )


def _parse_profile(value: object, path: str) -> Profile:
    table = _table(value, path)
    _fields(table, PROFILE_FIELDS, path, optional=PROFILE_OPTIONAL_FIELDS)
    display_name = _string(_required(table, "display_name", path), f"{path}.display_name")
    if not display_name.strip():
        raise ConfigValidationError(f"{path}.display_name", "must be a non-empty string")
    plate_layout = _integer(_required(table, "plate_layout", path), f"{path}.plate_layout", 2, 12)
    if plate_layout not in {2, 6, 12}:
        raise ConfigValidationError(f"{path}.plate_layout", "must be 2, 6, or 12")
    return Profile(
        display_name=display_name,
        plate_layout=cast(Literal[2, 6, 12], plate_layout),
        bindings=_parse_bindings(_required(table, "bindings", path), f"{path}.bindings"),
        dpi=_parse_dpi(_required(table, "dpi", path), f"{path}.dpi"),
        scroll=_parse_scroll(_required(table, "scroll", path), f"{path}.scroll"),
        lighting=_parse_lighting(_required(table, "lighting", path), f"{path}.lighting"),
        power=_parse_power(_required(table, "power", path), f"{path}.power"),
        poll_rate=_parse_poll_rate(table, path),
    )


def _parse_poll_rate(table: Mapping[str, object], path: str) -> int:
    if "poll_rate" not in table:
        return 1000
    value = _integer(table["poll_rate"], f"{path}.poll_rate", 125, 1000)
    if value not in {125, 500, 1000}:
        raise ConfigValidationError(f"{path}.poll_rate", "must be 125, 500, or 1000")
    return value


def _parse_bindings(value: object, path: str) -> Bindings:
    table = _table(value, path)
    names = {"common", "plate_2", "plate_6", "plate_12"}
    _fields(table, names, path)
    return Bindings(
        common=_parse_binding_table(
            _required(table, "common", path), f"{path}.common", COMMON_CONTROL_IDS
        ),
        plate_2=_parse_binding_table(
            _required(table, "plate_2", path), f"{path}.plate_2", PLATE_CONTROL_IDS[2]
        ),
        plate_6=_parse_binding_table(
            _required(table, "plate_6", path), f"{path}.plate_6", PLATE_CONTROL_IDS[6]
        ),
        plate_12=_parse_binding_table(
            _required(table, "plate_12", path), f"{path}.plate_12", PLATE_CONTROL_IDS[12]
        ),
    )


def _parse_binding_table(value: object, path: str, allowed: frozenset[str]) -> tuple[Binding, ...]:
    table = _table(value, path)
    unknown = set(table) - allowed
    if unknown:
        raise ConfigValidationError(f"{path}.{sorted(unknown)[0]}", "is not a valid control ID")
    return tuple(
        Binding(as_logical_control(control_id), _parse_action(action, f"{path}.{control_id}"))
        for control_id, action in table.items()
    )


def _parse_action(value: object, path: str) -> Action:
    table = _table(value, path)
    action_type = _string(_required(table, "type", path), f"{path}.type")
    allowed_fields = {
        "disabled": {"type"},
        "key": {"type", "key"},
        "key_combo": {"type", "modifiers", "key"},
        "mouse_button": {"type", "button"},
        "device": {"type", "action"},
    }
    if action_type not in allowed_fields:
        raise ConfigValidationError(f"{path}.type", "must be a supported action type")
    _fields(table, allowed_fields[action_type], path)
    try:
        if action_type == "disabled":
            return DisabledAction()
        if action_type == "key":
            return KeyAction(_string(_required(table, "key", path), f"{path}.key"))
        if action_type == "key_combo":
            return KeyComboAction(
                tuple(
                    _string(item, f"{path}.modifiers[{index}]")
                    for index, item in enumerate(
                        _array(_required(table, "modifiers", path), f"{path}.modifiers")
                    )
                ),
                _string(_required(table, "key", path), f"{path}.key"),
            )
        if action_type == "mouse_button":
            return MouseButtonAction(_string(_required(table, "button", path), f"{path}.button"))
        return DeviceAction(
            cast(DeviceActionToken, _string(_required(table, "action", path), f"{path}.action"))
        )
    except ConfigValidationError as exc:
        raise ConfigValidationError(f"{path}.{exc.field_path}", exc.message) from exc


def _parse_dpi(value: object, path: str) -> DpiSettings:
    table = _table(value, path)
    _fields(table, {"stages", "active_stage"}, path)
    raw_stages = _array(_required(table, "stages", path), f"{path}.stages")
    if not raw_stages:
        raise ConfigValidationError(f"{path}.stages", "must contain from 1 through 5 stages")
    stages = tuple(
        _parse_stage(stage, f"{path}.stages[{index}]") for index, stage in enumerate(raw_stages)
    )
    active_stage = _integer(
        _required(table, "active_stage", path), f"{path}.active_stage", 1, len(stages)
    )
    return DpiSettings(stages, active_stage)


def _parse_stage(value: object, path: str) -> DpiStage:
    table = _table(value, path)
    _fields(table, {"x", "y"}, path)
    return DpiStage(
        _integer(_required(table, "x", path), f"{path}.x", 100, 50000),
        _integer(_required(table, "y", path), f"{path}.y", 100, 50000),
    )


def _parse_scroll(value: object, path: str) -> ScrollSettings:
    table = _table(value, path)
    _fields(table, {"mode", "acceleration", "smart_reel"}, path)
    mode = _string(_required(table, "mode", path), f"{path}.mode")
    if mode not in {"tactile", "free_spin", "precision_tactile"}:
        raise ConfigValidationError(
            f"{path}.mode", "must be tactile, free_spin, or precision_tactile"
        )
    return ScrollSettings(
        cast(Literal["tactile", "free_spin", "precision_tactile"], mode),
        _boolean(_required(table, "acceleration", path), f"{path}.acceleration"),
        _boolean(_required(table, "smart_reel", path), f"{path}.smart_reel"),
    )


def _parse_lighting(value: object, path: str) -> LightingSettings:
    table = _table(value, path)
    _fields(table, {"thumb_grid", "logo", "scroll_wheel"}, path)
    thumb_grid = _parse_zone(_required(table, "thumb_grid", path), f"{path}.thumb_grid")
    if thumb_grid.effect.kind == "wave":
        raise ConfigValidationError(f"{path}.thumb_grid.effect", "does not support wave")
    return LightingSettings(
        thumb_grid=thumb_grid,
        logo=_parse_zone(_required(table, "logo", path), f"{path}.logo"),
        scroll_wheel=_parse_zone(_required(table, "scroll_wheel", path), f"{path}.scroll_wheel"),
    )


def _parse_zone(value: object, path: str) -> LightingZone:
    table = _table(value, path)
    _fields(table, {"brightness", "effect"}, path)
    return LightingZone(
        _integer(_required(table, "brightness", path), f"{path}.brightness", 0, 100),
        _parse_effect(_required(table, "effect", path), f"{path}.effect"),
    )


def _parse_effect(value: object, path: str) -> LightingEffect:
    table = _table(value, path)
    kind = _string(_required(table, "type", path), f"{path}.type")
    fields = {
        "off": {"type"},
        "spectrum": {"type"},
        "static": {"type", "color"},
        "breathing": {"type", "color"},
        "reactive": {"type", "color", "speed"},
        "wave": {"type", "direction"},
    }
    if kind not in fields:
        raise ConfigValidationError(f"{path}.type", "must be a supported lighting effect")
    _fields(table, fields[kind], path)
    color = (
        _rgb(_required(table, "color", path), f"{path}.color") if "color" in fields[kind] else None
    )
    speed = (
        _integer(_required(table, "speed", path), f"{path}.speed", 1, 4)
        if "speed" in fields[kind]
        else None
    )
    direction = (
        _string(_required(table, "direction", path), f"{path}.direction")
        if "direction" in fields[kind]
        else None
    )
    if direction is not None and direction not in {"left", "right"}:
        raise ConfigValidationError(f"{path}.direction", "must be left or right")
    return LightingEffect(
        cast(Literal["off", "static", "spectrum", "breathing", "reactive", "wave"], kind),
        color,
        speed,
        cast(Literal["left", "right"] | None, direction),
    )


def _parse_power(value: object, path: str) -> PowerSettings:
    table = _table(value, path)
    _fields(table, {"idle_seconds", "low_battery_threshold"}, path)
    return PowerSettings(
        _integer(_required(table, "idle_seconds", path), f"{path}.idle_seconds", 60, 900),
        _integer(
            _required(table, "low_battery_threshold", path),
            f"{path}.low_battery_threshold",
            0,
            25,
        ),
    )


def _table(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ConfigValidationError(path, "must be a TOML table")
    return cast(Mapping[str, object], value)


def _array(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise ConfigValidationError(path, "must be an array")
    return cast(list[object], value)


def _required(table: Mapping[str, object], name: str, path: str) -> object:
    if name not in table:
        raise ConfigValidationError(f"{path}.{name}", "is required")
    return table[name]


def _fields(
    table: Mapping[str, object],
    allowed: frozenset[str] | set[str],
    path: str,
    *,
    optional: frozenset[str] = frozenset(),
) -> None:
    unknown = set(table) - allowed
    if unknown:
        raise ConfigValidationError(f"{path}.{sorted(unknown)[0]}", "is not allowed")
    missing = (allowed - optional) - set(table)
    if missing:
        raise ConfigValidationError(f"{path}.{sorted(missing)[0]}", "is required")


def _string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise ConfigValidationError(path, "must be a string")
    return value


def _slug(value: object, path: str) -> str:
    identifier = _string(value, path)
    if not identifier.isascii() or not PROFILE_ID_RE.fullmatch(identifier):
        raise ConfigValidationError(path, "must be a lowercase ASCII slug")
    return identifier


def _integer(value: object, path: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ConfigValidationError(path, f"must be an integer from {minimum} through {maximum}")
    return value


def _boolean(value: object, path: str) -> bool:
    if type(value) is not bool:
        raise ConfigValidationError(path, "must be a boolean")
    return value


def _rgb(value: object, path: str) -> tuple[int, int, int]:
    items = _array(value, path)
    if len(items) != 3:
        raise ConfigValidationError(path, "must contain exactly three RGB components")
    return (
        _integer(items[0], f"{path}[0]", 0, 255),
        _integer(items[1], f"{path}[1]", 0, 255),
        _integer(items[2], f"{path}[2]", 0, 255),
    )
