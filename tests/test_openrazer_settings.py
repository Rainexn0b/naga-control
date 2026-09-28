from dataclasses import replace

from naga_control.adapters.openrazer.settings import apply_steps
from naga_control.domain.defaults import default_configuration
from naga_control.domain.profiles import LightingEffect, LightingZone, Profile


class FakeZone:
    def __init__(self, calls: list[str], prefix: str) -> None:
        self._calls = calls
        self._prefix = prefix
        self.brightness = 100.0

    def none(self) -> None:
        self._calls.append(f"{self._prefix}:none")

    def static(self, red: int, green: int, blue: int) -> None:
        self._calls.append(f"{self._prefix}:static:{red},{green},{blue}")

    def spectrum(self) -> None:
        self._calls.append(f"{self._prefix}:spectrum")

    def breath_single(self, red: int, green: int, blue: int) -> None:
        self._calls.append(f"{self._prefix}:breath:{red},{green},{blue}")

    def reactive(self, red: int, green: int, blue: int, speed: int) -> None:
        self._calls.append(f"{self._prefix}:reactive:{red},{green},{blue},{speed}")

    def wave(self, direction: int) -> None:
        self._calls.append(f"{self._prefix}:wave:{direction}")


class FakeMisc:
    def __init__(self, calls: list[str]) -> None:
        self.logo = FakeZone(calls, "logo")
        self.scroll_wheel = FakeZone(calls, "scroll")


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.dpi_stages: object = ()
        self.scroll_mode: object = 0
        self.scroll_acceleration = True
        self.scroll_smart_reel = True
        self.poll_rate = 1000
        self.brightness = 0.0
        self.fx = _FakeFx(self.calls)
        self.idle: list[int] = []
        self.threshold: list[int] = []

    def set_idle_time(self, seconds: int) -> None:
        self.idle.append(seconds)

    def set_low_battery_threshold(self, percent: int) -> None:
        self.threshold.append(percent)


class _FakeFx:
    def __init__(self, calls: list[str]) -> None:
        self.misc = FakeMisc(calls)
        self.grid = FakeZone(calls, "grid")

    def __getattr__(self, name: str) -> object:
        return getattr(self.grid, name)


def test_every_step_writes_the_desired_profile_values() -> None:
    client = FakeClient()
    profile = _profile(
        thumb_grid=LightingZone(60, LightingEffect("static", (255, 0, 0))),
        logo=LightingZone(40, LightingEffect("wave", direction="left")),
        scroll_wheel=LightingZone(20, LightingEffect("breathing", (0, 0, 255))),
        poll_rate=500,
    )

    failures = apply_steps(client, profile)

    assert failures == ()
    assert client.dpi_stages == (
        2,
        ((800, 800), (1600, 1600), (2400, 2400), (3200, 3200), (5000, 5000)),
    )
    assert client.scroll_mode == 0
    assert client.poll_rate == 500
    assert client.idle == [300]
    assert client.threshold == [20]
    assert client.brightness == 60
    assert client.fx.misc.logo.brightness == 40
    assert client.fx.misc.scroll_wheel.brightness == 20
    assert client.calls == [
        "grid:static:255,0,0",
        "logo:wave:1",
        "scroll:breath:0,0,255",
    ]


def test_effect_kinds_map_to_the_verified_client_methods() -> None:
    client = FakeClient()
    profile = _profile(
        thumb_grid=LightingZone(100, LightingEffect("off")),
        logo=LightingZone(100, LightingEffect("spectrum")),
        scroll_wheel=LightingZone(100, LightingEffect("reactive", (1, 2, 3), 3)),
    )

    failures = apply_steps(client, profile)

    assert failures == ()
    assert client.calls == ["grid:none", "logo:spectrum", "scroll:reactive:1,2,3,3"]


def test_one_failing_zone_does_not_stop_the_other_steps() -> None:
    client = FakeClient()

    def broken() -> None:
        raise RuntimeError("zone offline")

    method = "static"
    setattr(client.fx.misc.logo, method, broken)
    failures = apply_steps(client, _profile())

    assert [failure.setting for failure in failures] == ["lighting_logo"]
    assert "grid:static:0,255,0" in client.calls
    assert "scroll:static:0,255,0" in client.calls


def _profile(
    *,
    thumb_grid: LightingZone | None = None,
    logo: LightingZone | None = None,
    scroll_wheel: LightingZone | None = None,
    poll_rate: int = 1000,
) -> Profile:
    base = default_configuration().profile("default")
    green = LightingZone(100, LightingEffect("static", (0, 255, 0)))
    return replace(
        base,
        lighting=replace(
            base.lighting,
            thumb_grid=thumb_grid or green,
            logo=logo or green,
            scroll_wheel=scroll_wheel or green,
        ),
        poll_rate=poll_rate,
    )
