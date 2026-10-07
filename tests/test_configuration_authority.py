from dataclasses import replace

import pytest

from naga_control.config import parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.domain.profiles import Configuration
from naga_control.service.configuration_authority import ConfigurationAuthority


class Store:
    def __init__(self) -> None:
        self.saved: list[Configuration] = []
        self.error: OSError | None = None

    def load(self) -> None:
        return None

    def save(self, configuration: Configuration) -> None:
        if self.error is not None:
            raise self.error
        self.saved.append(configuration)


def test_loading_is_deferred_and_repeated_without_saving_defaults() -> None:
    calls: list[str] = []
    store = Store()

    def load() -> Configuration | None:
        calls.append("load")
        return None if len(calls) == 1 else replace(default_configuration(), revision=7)

    authority = ConfigurationAuthority(load, store)
    assert authority.current is None
    assert calls == []
    with pytest.raises(RuntimeError, match="Naga service has no loaded configuration"):
        authority.require_current()
    authority.load()
    assert authority.current == default_configuration()
    authority.load()
    assert authority.revision() == 7
    assert parse_toml(authority.document()) == authority.current
    assert store.saved == []


def test_revision_validation_does_not_persist_or_replace_configuration() -> None:
    store = Store()
    authority = ConfigurationAuthority(default_configuration, store)
    authority.load()
    original = authority.current
    authority.validate_revision(0, replace(default_configuration(), revision=1))
    assert authority.current is original
    assert store.saved == []


@pytest.mark.parametrize("operation", ["apply", "select", "save"])
def test_save_failure_leaves_authoritative_configuration_unchanged(operation: str) -> None:
    original = default_configuration()
    store = Store()
    failure = OSError("cannot persist configuration")
    store.error = failure
    authority = ConfigurationAuthority(lambda: original, store)
    authority.load()
    updated = replace(original, revision=1)
    with pytest.raises(OSError) as caught:
        if operation == "apply":
            authority.apply(0, updated)
        elif operation == "select":
            authority.select_profile("default")
        else:
            authority.save(updated)
    assert caught.value is failure
    assert authority.current is original
    assert store.saved == []
