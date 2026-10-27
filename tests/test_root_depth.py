"""Optional root depth sizes the bucket. Blank keeps the plant preset."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.sprinklecast.const import DOMAIN
from sprinklecast.balance import rescale_deficit, root_zone
from sprinklecast.presets import resolved_root_depth_in
from sprinklecast.units import inches_to_length, length_to_inches
from tests.test_week_plan import _freeze_saturday, _live_entry, _load

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def test_blank_root_depth_uses_the_plant_preset() -> None:
    blank = {"plant_type": "bermuda", "soil_type": "loam", "sprinkler_type": "spray"}
    stored = {**blank, "root_depth_in": 10}
    assert resolved_root_depth_in(blank) == pytest.approx(6)
    preset = root_zone(
        soil_type="loam",
        plant_type="bermuda",
        sun_exposure="full_sun",
        root_depth_in=resolved_root_depth_in(blank),
        p_table=None,
        et0_mm=5.0,
    )
    deeper = root_zone(
        soil_type="loam",
        plant_type="bermuda",
        sun_exposure="full_sun",
        root_depth_in=resolved_root_depth_in(stored),
        p_table=None,
        et0_mm=5.0,
    )
    assert deeper.taw_mm == pytest.approx(preset.taw_mm * 10 / 6)
    assert deeper.raw_mm == pytest.approx(preset.raw_mm * 10 / 6)
    # Available water is in/in, so the bucket in inches is depth times that.
    assert deeper.taw_mm / 25.4 == pytest.approx(10 * deeper.awc)


def test_centimeters_convert_and_a_missing_unit_is_rejected() -> None:
    assert length_to_inches(2.54, "cm") == pytest.approx(1.0)
    assert length_to_inches(25.4, "mm") == pytest.approx(1.0)
    assert length_to_inches(6, "in") == pytest.approx(6.0)
    assert inches_to_length(6, "cm") == pytest.approx(15.24)
    with pytest.raises(ValueError):
        length_to_inches(6, None)
    with pytest.raises(ValueError):
        length_to_inches(6, "ft")


def test_resizing_the_bucket_keeps_the_moisture_percent() -> None:
    old = 20.0
    deficit = 5.0
    new = 40.0
    scaled = rescale_deficit(deficit, old, new)
    assert scaled / new == pytest.approx(deficit / old)
    assert rescale_deficit(deficit, old, old) == pytest.approx(deficit)


async def test_blank_depth_does_not_move_the_bucket_and_a_change_keeps_percent(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    _freeze_saturday(monkeypatch)
    entry = await _load(hass, _live_entry())
    zone_id = next(iter(entry.subentries))
    coordinator = entry.runtime_data
    await hass.services.async_call(
        DOMAIN, "set_bucket", {"zone": "Test1", "deficit_mm": 8}, blocking=True
    )
    await hass.async_block_till_done()
    state = coordinator.store.zone(zone_id)
    before = float(state["deficit_mm"])
    taw = float(state["root_depth_taw_mm"])
    moisture = 1.0 - before / taw
    await coordinator.async_set_root_depth(zone_id, None)
    await hass.async_block_till_done()
    assert float(coordinator.store.zone(zone_id)["deficit_mm"]) == pytest.approx(before)
    assert coordinator.data.zones[zone_id].root_depth_source == "preset"

    await coordinator.async_set_root_depth(zone_id, coordinator.data.zones[zone_id].root_depth_in * 2)
    await hass.async_block_till_done()
    zone = coordinator.data.zones[zone_id]
    assert zone.root_depth_source == "set"
    assert zone.bucket_in == pytest.approx(zone.taw_mm / 25.4, abs=0.01)
    after = float(coordinator.store.zone(zone_id)["deficit_mm"])
    new_taw = float(coordinator.store.zone(zone_id)["root_depth_taw_mm"])
    assert 1.0 - after / new_taw == pytest.approx(moisture, abs=0.02)
    downloaded_source = zone.root_depth_source
    from custom_components.sprinklecast.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    downloaded = await async_get_config_entry_diagnostics(hass, entry)
    row = next(item for item in downloaded["zones"] if item["zone_id"] == zone_id)
    assert row["root_depth_source"] == downloaded_source
    assert row["bucket_in"] == zone.bucket_in
    assert row["root_depth_in"] == zone.root_depth_in
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    assert registry.async_get_entity_id(
        "number", DOMAIN, f"{entry.entry_id}_{zone_id}_root_depth"
    )
