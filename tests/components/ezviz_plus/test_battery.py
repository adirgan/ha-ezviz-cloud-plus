"""Tests for EZVIZ battery telemetry helpers."""

from custom_components.ezviz_plus.utility import (
    battery_charge_state,
    battery_charging_source,
    battery_details,
    battery_is_charging,
)


def test_battery_details_uses_power_manager_telemetry() -> None:
    """Prefer the explicit PowerMgr status used by battery cameras."""
    camera_data = {
        "FEATURE_INFO": {
            "1": {
                "Video": {
                    "PowerMgr": {
                        "BatteryDetails": [
                            {
                                "chargingType": 0,
                                "remain": 68,
                                "type": 3,
                                "status": 1,
                            }
                        ]
                    }
                }
            }
        },
        "optionals": {"powerStatus": "0"},
    }

    assert battery_details(camera_data) == {
        "chargingType": 0,
        "remain": 68,
        "type": 3,
        "status": 1,
    }
    assert battery_charge_state(camera_data) == "charging"
    assert battery_is_charging(camera_data) is True
    assert battery_charging_source(camera_data) == "power_adapter"


def test_battery_status_accepts_string_fallback() -> None:
    """Normalize legacy optionals values when PowerMgr is unavailable."""
    camera_data = {"optionals": {"powerStatus": "2"}}

    assert battery_charge_state(camera_data) == "full"
    assert battery_is_charging(camera_data) is False
    assert battery_charging_source(camera_data) is None