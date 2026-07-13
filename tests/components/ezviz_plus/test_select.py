"""Tests for EZVIZ battery work-mode selects."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ezviz_plus.select import (
    SELECTS,
    EzvizSelect,
    EzvizSelectEntityDescription,
    _is_desc_supported,
)


def _description(key: str) -> EzvizSelectEntityDescription:
    """Return a select description by key."""
    return next(description for description in SELECTS if description.key == key)


CLASSIC_DESCRIPTION = _description("battery_camera_work_mode")
AOV_DESCRIPTION = _description("battery_camera_work_mode_aov")


def test_aov_work_mode_table() -> None:
    """Expose the new API values with their expected Home Assistant options."""
    assert AOV_DESCRIPTION.options == [
        "standard",
        "plugged_in",
        "super_power_save",
        "custom",
        "aov_mode",
    ]
    assert AOV_DESCRIPTION.option_range == [1, 2, 3, 4, 7]


@pytest.mark.parametrize(
    "support_ext",
    [
        {"687": "1,3,10,9,8", "502": None},
        {"687": " 8, 1, 9, 3, 10 ", "502": None},
        {"687": "12,8,1,9,3,10,15", "502": "1,2,3,4,10"},
        {687: "1,3,10,9,8"},
    ],
)
def test_aov_capability_selects_only_new_work_mode(
    support_ext: dict[object, object],
) -> None:
    """Prefer the new AOV work-mode table regardless of token formatting."""
    camera_data = {"supportExt": support_ext, "battery_camera_work_mode": 1}

    assert _is_desc_supported(camera_data, AOV_DESCRIPTION)
    assert not _is_desc_supported(camera_data, CLASSIC_DESCRIPTION)


def test_classic_capability_keeps_classic_work_mode() -> None:
    """Keep the legacy table for cameras that only advertise capability 502."""
    camera_data = {
        "supportExt": {"502": "1,2,3,4,10"},
        "battery_camera_work_mode": 1,
    }

    assert _is_desc_supported(camera_data, CLASSIC_DESCRIPTION)
    assert not _is_desc_supported(camera_data, AOV_DESCRIPTION)


def test_aov_capability_can_be_nested_in_device_infos() -> None:
    """Read AOV support from the nested deviceInfos payload variant."""
    camera_data = {
        "deviceInfos": {"supportExt": {687: " 10, 8, 3, 1, 9, 12 "}},
        "battery_camera_work_mode": "7",
    }

    assert _is_desc_supported(camera_data, AOV_DESCRIPTION)
    assert not _is_desc_supported(camera_data, CLASSIC_DESCRIPTION)


@pytest.mark.parametrize(
    ("current_value", "expected_option"),
    [(1, "standard"), ("1", "standard"), (7, "aov_mode"), ("7", "aov_mode")],
)
def test_aov_current_option_accepts_mixed_api_values(
    current_value: int | str, expected_option: str
) -> None:
    """Map integer and string API values through the AOV option table."""
    entity = object.__new__(EzvizSelect)
    entity.entity_description = AOV_DESCRIPTION
    entity._serial = "test-camera"
    entity.coordinator = SimpleNamespace(
        data={"test-camera": {"battery_camera_work_mode": current_value}}
    )

    assert entity.current_option == expected_option


def test_selecting_aov_mode_sends_value_seven() -> None:
    """Write AOV mode using the API value 7 and refresh coordinator data."""
    api = MagicMock()
    coordinator = SimpleNamespace(
        data={"test-camera": {"battery_camera_work_mode": 1}},
        ezviz_client=api,
        async_request_refresh=AsyncMock(),
    )
    hass = SimpleNamespace(
        async_add_executor_job=AsyncMock(
            side_effect=lambda target, *args: target(*args)
        )
    )
    entity = object.__new__(EzvizSelect)
    entity.entity_description = AOV_DESCRIPTION
    entity._serial = "test-camera"
    entity.coordinator = coordinator
    entity.hass = hass
    entity.async_write_ha_state = MagicMock()

    asyncio.run(entity.async_select_option("aov_mode"))

    api.set_battery_camera_work_mode.assert_called_once_with("test-camera", 7)
    assert entity.current_option == "aov_mode"
    entity.async_write_ha_state.assert_called_once_with()
    coordinator.async_request_refresh.assert_awaited_once_with()


def test_aov_optimistic_option_clears_when_coordinator_confirms() -> None:
    """Use the API-accepted option until coordinator data catches up."""
    entity = object.__new__(EzvizSelect)
    entity.entity_description = AOV_DESCRIPTION
    entity._serial = "test-camera"
    entity._optimistic_option = "aov_mode"
    entity._optimistic_option_expires = float("inf")
    entity.coordinator = SimpleNamespace(
        data={"test-camera": {"battery_camera_work_mode": 1}}
    )

    assert entity.current_option == "aov_mode"

    entity.coordinator.data["test-camera"]["battery_camera_work_mode"] = 7

    assert entity.current_option == "aov_mode"
    assert entity._optimistic_option is None