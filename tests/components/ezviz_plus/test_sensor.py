"""Tests for EZVIZ sensors."""

from types import SimpleNamespace

from custom_components.ezviz_plus.sensor import SENSORS, EzvizSensor


def _description(key: str):
    """Return a sensor description by key."""
    return next(description for description in SENSORS if description.key == key)


def _camera_data(**values):
    """Return the minimum camera data required by an entity."""
    return {
        "name": "Camera A",
        "device_sub_category": "Test Camera",
        "version": "1.0",
        **values,
    }


def test_alarm_type_name_tracks_alarm_time_as_state_attribute() -> None:
    """Distinguish repeated alarms that have the same type name."""
    coordinator = SimpleNamespace(
        data={
            "CAMERA_A": _camera_data(
                last_alarm_type_name="AI Human Detection",
                last_alarm_time="2026-08-17 21:10:55",
            )
        }
    )

    entity = EzvizSensor(
        coordinator,
        "CAMERA_A",
        _description("last_alarm_type_name"),
    )

    assert entity.native_value == "AI Human Detection"
    assert entity.extra_state_attributes == {
        "last_alarm_time": "2026-08-17 21:10:55"
    }


def test_regular_sensor_has_no_alarm_identity_attribute() -> None:
    """Do not add alarm metadata to unrelated sensors."""
    coordinator = SimpleNamespace(
        data={"CAMERA_A": _camera_data(battery_level=96)}
    )

    entity = EzvizSensor(coordinator, "CAMERA_A", _description("battery_level"))

    assert entity.extra_state_attributes is None