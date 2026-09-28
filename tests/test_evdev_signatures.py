import json
from pathlib import Path
from typing import cast

import pytest

from naga_control.adapters.evdev.frames import RawControlSignature
from naga_control.adapters.evdev.signatures import translations_for
from naga_control.domain.profiles import PlateLayout, as_logical_control

FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("*.json"))


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture.stem)
def test_every_captured_control_is_translated(fixture: Path) -> None:
    document = cast(dict[str, object], json.loads(fixture.read_text(encoding="utf-8")))
    product_id = cast(str, document["product_id"])
    plate_layout = cast(PlateLayout, document["plate_layout"])
    controls = cast(list[dict[str, object]], document["controls"])
    translations = translations_for(product_id, plate_layout)

    for control in controls:
        signature = RawControlSignature(
            product_id,
            cast(str, control["interface_number"]),
            cast(int, control["event_type"]),
            cast(int, control["event_code"]),
            cast(int | None, control["scan_code"]),
        )
        assert translations[signature] == as_logical_control(cast(str, control["control_id"]))


def test_translations_cover_only_captured_transport_and_plate_combinations() -> None:
    assert len(translations_for("00e8", 12)) == 19
    assert len(translations_for("00e8", 6)) == 13
    assert len(translations_for("00e8", 2)) == 9
    assert len(translations_for("00e7", 12)) == 19
    assert not translations_for("00e7", 6)
    assert not translations_for("00e7", 2)
    assert not translations_for("00e9", 12)
