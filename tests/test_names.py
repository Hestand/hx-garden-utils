"""User-facing names stay plain, and the English catalog matches strings.json."""

import json
import re
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
    assert sensors["soil_water"]["name"] == "Soil moisture"
    assert sensors["average_soil_moisture"]["name"] == "Average soil moisture"
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


def test_entity_selectors_name_their_units() -> None:
    """Every entity selector description says which units the code accepts."""
    root = Path(__file__).resolve().parents[1] / "custom_components" / "sprinklecast"
    flow = (root / "config_flow.py").read_text()
    const = (root / "const.py").read_text()
    assigned = dict(re.findall(r'^(CONF_[A-Z0-9_]+)\s*=\s*"([^"]+)"', const, re.M))
    found = re.findall(
        r"(CONF_[A-Z0-9_]+)\)\s*(?:\]\s*)?(?::|=)\s*"
        r"(_SENSOR|_BINARY|_WEATHER|_ON_OFF|_RAIN)\b",
        flow,
    )
    assert found, "no entity selectors found in config_flow.py"
    keys = set()
    for name, _kind in found:
        assert name in assigned, name
        keys.add(assigned[name])

    data = _load("strings.json")
    seen: set[str] = set()

    def walk(node: object) -> None:
        if not isinstance(node, dict):
            return
        labels = node.get("data")
        if isinstance(labels, dict):
            described = node.get("data_description") or {}
            for key in labels:
                if key not in keys:
                    continue
                text = described.get(key)
                assert isinstance(text, str) and "Units:" in text, key
                seen.add(key)
        for value in node.values():
            walk(value)

    walk(data["config"])
    walk(data["options"])
    walk(data["config_subentries"])
    assert seen == keys
    blob = json.dumps(data)
    assert "is read as" not in blob
