"""Qt-free configuration document editing used by the GUI pages."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.actions import Action
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.profiles import (
    COMMON_CONTROL_IDS,
    PLATE_CONTROL_IDS,
    Binding,
    Bindings,
    Configuration,
    DpiSettings,
    DpiStage,
    LightingSettings,
    LogicalControlId,
    PowerSettings,
    Profile,
    ScrollMode,
    ScrollSettings,
)


def edit_configuration(document: str, transform: Callable[[Configuration], Configuration]) -> str:
    """Return a new document with the configuration replaced, revision bumped."""
    configuration = parse_toml(document)
    updated = transform(configuration)
    return dump_toml(replace(updated, revision=configuration.revision + 1))


def edit_profile(document: str, profile_id: str, transform: Callable[[Profile], Profile]) -> str:
    """Return a new document with one profile replaced and revision bumped."""

    def transform_configuration(configuration: Configuration) -> Configuration:
        return _with_profile(configuration, profile_id, transform)

    return edit_configuration(document, transform_configuration)


def set_dpi_stages(
    document: str,
    profile_id: str,
    stages: Sequence[tuple[int, int]],
    active_stage: int,
) -> str:
    """Replace the DPI stages of one profile, validating through the domain."""

    def transform(profile: Profile) -> Profile:
        replacement = DpiSettings(
            stages=tuple(DpiStage(x, y) for x, y in stages), active_stage=active_stage
        )
        return replace(profile, dpi=replacement)

    return edit_profile(document, profile_id, transform)


def set_plate_layout(document: str, profile_id: str, plate_layout: int) -> str:
    """Replace the side-plate layout of one profile, validating through the domain."""

    def transform(profile: Profile) -> Profile:
        return replace(profile, plate_layout=plate_layout)

    return edit_profile(document, profile_id, transform)


def set_bindings(
    document: str,
    profile_id: str,
    replacements: Mapping[LogicalControlId, Action | None],
) -> str:
    """Replace or remove the actions of several controls in one revision bump.

    A ``None`` action removes the binding so the control passes through.
    """

    def transform(profile: Profile) -> Profile:
        groups = {
            "common": COMMON_CONTROL_IDS,
            "plate_2": PLATE_CONTROL_IDS[2],
            "plate_6": PLATE_CONTROL_IDS[6],
            "plate_12": PLATE_CONTROL_IDS[12],
        }
        unknown = [
            control
            for control in replacements
            if not any(control in allowed for allowed in groups.values())
        ]
        if unknown:
            raise KeyError(", ".join(sorted(unknown)))
        bindings = profile.bindings
        updated = {
            name: _replace_group(getattr(bindings, name), replacements, allowed)
            for name, allowed in groups.items()
        }
        return replace(profile, bindings=Bindings(**updated))

    return edit_profile(document, profile_id, transform)


def _replace_group(
    existing: tuple[Binding, ...],
    replacements: Mapping[LogicalControlId, Action | None],
    allowed: frozenset[str],
) -> tuple[Binding, ...]:
    changed: dict[LogicalControlId, Action | None] = {
        control: action for control, action in replacements.items() if control in allowed
    }
    replaced = [
        binding
        for binding in existing
        if not (binding.control_id in changed and changed[binding.control_id] is None)
    ]
    for control, action in changed.items():
        if action is None:
            continue
        replacement = Binding(control_id=control, action=action)
        position = next(
            (index for index, binding in enumerate(replaced) if binding.control_id == control),
            None,
        )
        if position is None:
            replaced.append(replacement)
        else:
            replaced[position] = replacement
    return tuple(replaced)


def set_scroll(
    document: str,
    profile_id: str,
    mode: ScrollMode,
    acceleration: bool,
    smart_reel: bool,
) -> str:
    """Replace the scroll settings of one profile, validating through the domain."""

    def transform(profile: Profile) -> Profile:
        return replace(
            profile,
            scroll=ScrollSettings(mode=mode, acceleration=acceleration, smart_reel=smart_reel),
        )

    return edit_profile(document, profile_id, transform)


def set_lighting(document: str, profile_id: str, lighting: LightingSettings) -> str:
    """Replace the lighting settings of one profile, validating through the domain."""

    def transform(profile: Profile) -> Profile:
        return replace(profile, lighting=lighting)

    return edit_profile(document, profile_id, transform)


def set_power(document: str, profile_id: str, idle_seconds: int, low_battery_threshold: int) -> str:
    """Replace the power settings of one profile, validating through the domain."""

    def transform(profile: Profile) -> Profile:
        return replace(
            profile,
            power=PowerSettings(
                idle_seconds=idle_seconds, low_battery_threshold=low_battery_threshold
            ),
        )

    return edit_profile(document, profile_id, transform)


def active_profile_id(configuration: Configuration) -> str:
    return configuration.active_profile


def duplicate_profile(document: str, source_id: str, new_id: str, display_name: str) -> str:
    """Add a copy of one profile under a new identifier."""

    def transform(configuration: Configuration) -> Configuration:
        source = configuration.profile(source_id)
        if new_id in {identifier for identifier, _ in configuration.profiles}:
            raise ConfigValidationError("profiles", f"profile {new_id!r} already exists")
        copy = replace(source, display_name=display_name)
        return replace(configuration, profiles=(*configuration.profiles, (new_id, copy)))

    return edit_configuration(document, transform)


def rename_profile(document: str, profile_id: str, display_name: str) -> str:
    """Change the display name of one profile, keeping its identifier."""

    def transform(profile: Profile) -> Profile:
        return replace(profile, display_name=display_name)

    return edit_profile(document, profile_id, transform)


def remove_profile(document: str, profile_id: str) -> str:
    """Remove one profile, reassigning default and active as needed."""

    def transform(configuration: Configuration) -> Configuration:
        identifiers = [identifier for identifier, _ in configuration.profiles]
        if profile_id not in identifiers:
            raise KeyError(profile_id)
        if len(identifiers) == 1:
            raise ConfigValidationError("profiles", "must contain at least one profile")
        remaining = tuple(
            (identifier, profile)
            for identifier, profile in configuration.profiles
            if identifier != profile_id
        )
        first = remaining[0][0]
        default = (
            first if configuration.default_profile == profile_id else configuration.default_profile
        )
        active = (
            first if configuration.active_profile == profile_id else configuration.active_profile
        )
        return replace(
            configuration, profiles=remaining, default_profile=default, active_profile=active
        )

    return edit_configuration(document, transform)


def _with_profile(
    configuration: Configuration, profile_id: str, transform: Callable[[Profile], Profile]
) -> Configuration:
    if profile_id not in {identifier for identifier, _ in configuration.profiles}:
        raise KeyError(profile_id)
    profiles = tuple(
        (identifier, transform(profile) if identifier == profile_id else profile)
        for identifier, profile in configuration.profiles
    )
    return replace(configuration, profiles=profiles)
