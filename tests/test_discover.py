"""Station detection stays off a random indoor thermometer."""

from __future__ import annotations

from sprinklecast.discover import EntityHint, discover


def _hint(entity_id: str, **kwargs: object) -> EntityHint:
    return EntityHint(entity_id=entity_id, **kwargs)  # type: ignore[arg-type]


def test_tempest_cluster_is_prefilled_and_indoor_temperature_is_not() -> None:
    found = discover(
        [
            _hint("weather.tempest", name="Tempest"),
            _hint("weather.forecast_home", name="Home"),
            _hint(
                "sensor.tempest_air_temperature",
                device_class="temperature",
                name="Air Temperature",
                device_id="station",
                device_name="Tempest",
            ),
            _hint(
                "sensor.kitchen_temperature",
                device_class="temperature",
                name="Kitchen",
                device_id="indoor",
                device_name="Hall thermostat",
            ),
            _hint(
                "sensor.tempest_station_pressure",
                device_class="pressure",
                name="Station Pressure",
                device_id="station",
            ),
            _hint(
                "sensor.tempest_sea_level_pressure",
                device_class="pressure",
                name="Sea Level Pressure",
                device_id="station",
            ),
            _hint(
                "sensor.tempest_rain_today",
                device_class="precipitation",
                name="Rain Today",
                device_id="station",
                unit="mm",
            ),
            _hint(
                "sensor.tempest_precip_rate",
                device_class="precipitation",
                name="Precipitation Rate",
                device_id="station",
                unit="mm/h",
            ),
        ]
    )
    assert found.weather == "weather.tempest"
    assert found.temperature == "sensor.tempest_air_temperature"
    assert found.pressure == "sensor.tempest_station_pressure"
    assert found.rain == "sensor.tempest_rain_today"
    assert found.rain_kind == "daily_total"


def test_a_single_weather_entity_is_suggested() -> None:
    found = discover(
        [
            _hint("weather.home", name="Home"),
            _hint("sensor.kitchen_temperature", device_class="temperature"),
        ]
    )
    assert found.weather == "weather.home"
    assert found.temperature is None


def test_two_unnamed_weather_entities_are_not_guessed() -> None:
    found = discover(
        [
            _hint("weather.home"),
            _hint("weather.backyard"),
        ]
    )
    assert found.weather is None


def test_daily_rain_wins_and_a_rate_name_sets_the_kind() -> None:
    found = discover(
        [
            _hint(
                "sensor.wf_rain_rate",
                name="Rain rate",
                device_class="precipitation",
                unit="mm/h",
            )
        ]
    )
    assert found.rain == "sensor.wf_rain_rate"
    assert found.rain_kind == "rate"
