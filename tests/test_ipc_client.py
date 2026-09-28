import pytest
from dbus_next.errors import DBusError

from naga_control.ipc.client import (
    BUS_NAME,
    INTERFACE_NAME,
    OBJECT_PATH,
    InvalidConfigurationError,
    NagaControlClient,
    StaleRevisionError,
    UnknownProfileError,
    connect_service_client,
)


class FakeCalls:
    def __init__(
        self,
        *,
        apply_error: DBusError | None = None,
        select_error: DBusError | None = None,
    ) -> None:
        self.apply_error = apply_error
        self.select_error = select_error
        self.applied: tuple[int, str] | None = None
        self.selected: str | None = None

    async def call_get_snapshot(self) -> str:
        return '{"status":"available"}'

    async def call_release_all(self) -> None:
        return None

    async def call_get_configuration(self) -> str:
        return "<document>"

    async def call_apply_configuration(self, expected_revision: int, document: str) -> int:
        if self.apply_error is not None:
            raise self.apply_error
        self.applied = (expected_revision, document)
        return 7

    async def call_select_profile(self, profile_id: str) -> int:
        if self.select_error is not None:
            raise self.select_error
        self.selected = profile_id
        return 8

    async def call_begin_calibration(self) -> bool:
        self.begun = True
        return True

    async def call_end_calibration(self) -> bool:
        self.ended = True
        return False


def test_client_passes_documents_and_writes_through() -> None:
    import asyncio

    calls = FakeCalls()
    client = NagaControlClient(calls)

    async def scenario() -> None:
        assert await client.snapshot_document() == '{"status":"available"}'
        await client.release_all()
        assert await client.configuration_document() == "<document>"
        assert await client.apply_configuration(3, "doc") == 7
        assert await client.select_profile("fps") == 8
        assert await client.begin_calibration() is True
        assert await client.end_calibration() is False

    asyncio.run(scenario())
    assert calls.applied == (3, "doc")
    assert calls.selected == "fps"


@pytest.mark.parametrize(
    ("error_name", "expected"),
    [
        ("org.nagacontrol.Service1.Error.StaleRevision", StaleRevisionError),
        ("org.nagacontrol.Service1.Error.InvalidConfiguration", InvalidConfigurationError),
    ],
)
def test_client_maps_apply_errors(error_name: str, expected: type[Exception]) -> None:
    import asyncio

    client = NagaControlClient(FakeCalls(apply_error=DBusError(error_name, "boom")))

    with pytest.raises(expected, match="boom"):
        asyncio.run(client.apply_configuration(1, "doc"))


def test_client_maps_unknown_profile_error() -> None:
    import asyncio

    client = NagaControlClient(
        FakeCalls(select_error=DBusError("org.nagacontrol.Service1.Error.UnknownProfile", "nope"))
    )

    with pytest.raises(UnknownProfileError, match="nope"):
        asyncio.run(client.select_profile("missing"))


def test_client_leaves_other_dbus_errors_untouched() -> None:
    import asyncio

    client = NagaControlClient(
        FakeCalls(apply_error=DBusError("org.freedesktop.DBus.Error.ServiceUnknown", "gone"))
    )

    with pytest.raises(DBusError):
        asyncio.run(client.apply_configuration(1, "doc"))


class FakeProxyObject:
    def __init__(self) -> None:
        self.requested_interface: str | None = None

    def get_interface(self, name: str) -> FakeCalls:
        self.requested_interface = name
        return FakeCalls()


class FakeBus:
    def __init__(self) -> None:
        self.introspected: tuple[str, str] | None = None
        self.proxy = FakeProxyObject()

    async def introspect(self, name: str, path: str) -> object:
        self.introspected = (name, path)
        return object()

    def get_proxy_object(self, name: str, path: str, introspection: object) -> FakeProxyObject:
        return self.proxy


def test_connect_service_client_introspects_the_published_contract() -> None:
    import asyncio

    bus = FakeBus()

    client = asyncio.run(connect_service_client(bus))

    assert bus.introspected == (BUS_NAME, OBJECT_PATH)
    assert bus.proxy.requested_interface == INTERFACE_NAME
    assert isinstance(client, NagaControlClient)
