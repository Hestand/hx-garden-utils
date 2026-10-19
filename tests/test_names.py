"""User-facing names stay plain, and the English catalog matches strings.json."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "sprinklecast"

# Shown as a whole word in a label. Parentheses may still carry the term.
_BARE = ("ET0", "ETc", "MAD", "RAW", "AWC", "DU_lq", "Deficit", "Bucket")


def _load(name: str) -> dict:
    return json.loads((ROOT / name).read_text())


def test_english_catalog_matches_strings() -> None:
    assert _load("strings.json") == _load("translations/en.json")


def test_entity_names_are_plain_and_ids_stay() -> None:
    data = _load("strings.json")
    sensors = data["entity"]["sensor"]
    assert sensors["et0"]["name"] == "Water loss today (reference lawn)"
    assert sensors["deficit"]["name"] == "Water needed"
    assert sensors["soil_water"]["name"] == "Soil water"
    assert sensors["raw"]["name"] == "Watering point"
    assert sensors["next_run"]["name"] == "Next watering"
    assert data["entity"]["sensor"]["water_use"]["name"] == "Water used"
    # Translation keys are the stable ids. Renames do not change them.
    assert "et0" in sensors
    assert "deficit" in sensors
    assert "tonight_plan" in sensors
    for block in sensors.values():
        name = block["name"]
        for word in _BARE:
            assert word not in name.split()


def test_config_fields_have_a_description() -> None:
    data = _load("strings.json")

    def walk(node: object) -> None:
        if not isinstance(node, dict):
            return
        labels = node.get("data")
        if isinstance(labels, dict):
            described = node.get("data_description") or {}
            missing = [key for key in labels if key not in described]
            assert missing == []
        for value in node.values():
            walk(value)

    walk(data["config"])
    walk(data["options"])
    walk(data["config_subentries"])
