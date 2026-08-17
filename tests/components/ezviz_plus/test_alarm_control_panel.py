"""Tests for EZVIZ alarm control panels."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from pyezvizapi import PyEzvizError
import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from custom_components.ezviz_plus.alarm_control_panel import (
    EzvizAlarm,
    EzvizCameraAlarm,
    async_setup_entry,
)
from homeassistant.components.alarm_control_panel import AlarmControlPanelState
from homeassistant.exceptions import HomeAssistantError


def camera_data(*, supports_defence: bool = False) -> dict:
    """Return the minimum coordinator payload for an EZVIZ camera."""
    data = {
        "name": "Driveway",
        "status": 1,
        "device_category": "BatteryCamera",
        "device_sub_category": "EB8",
        "version": "1.0.0",
        "mac_address": None,
        "alarm_notify": False,
    }
    if supports_defence:
        data["supportExt"] = {"1": "1"}
    return data


@pytest.fixture
def camera_alarm() -> tuple[EzvizCameraAlarm, SimpleNamespace, MagicMock]:
    """Return an individual camera alarm with a lightweight coordinator."""
    client = MagicMock()
    coordinator = SimpleNamespace(
        data={"CAMERA123": camera_data(supports_defence=True)},
        ezviz_client=client,
        merge_camera_update=MagicMock(),
    )
    entity = EzvizCameraAlarm(coordinator, "CAMERA123")

    async def run_executor_job(target, *args):
        return target(*args)

    entity.hass = SimpleNamespace(
        async_add_executor_job=AsyncMock(side_effect=run_executor_job)
    )
    return entity, coordinator, client


def test_setup_creates_camera_alarm_only_when_supported() -> None:
    """Create individual alarm panels only for cameras with defence support."""
    coordinator = SimpleNamespace(
        data={
            "SUPPORTED": camera_data(supports_defence=True),
            "UNSUPPORTED": camera_data(),
        },
        ezviz_client=MagicMock(),
    )
    hass = SimpleNamespace(data={"ezviz_plus": {"entry-1": {"coordinator": coordinator}}})
    entry = SimpleNamespace(entry_id="entry-1", unique_id="account-1")
    entities = []

    asyncio.run(async_setup_entry(hass, entry, entities.extend))

    assert len(entities) == 2
    assert isinstance(entities[0], EzvizAlarm)
    assert isinstance(entities[1], EzvizCameraAlarm)
    assert entities[1].unique_id == "SUPPORTED-camera_alarm"


def test_camera_alarm_exposes_device_state(
    camera_alarm: tuple[EzvizCameraAlarm, SimpleNamespace, MagicMock],
) -> None:
    """Map camera defence data to alarm states and camera device metadata."""
    entity, coordinator, _client = camera_alarm

    assert entity.alarm_state is AlarmControlPanelState.DISARMED
    coordinator.data["CAMERA123"]["alarm_notify"] = True
    assert entity.alarm_state is AlarmControlPanelState.ARMED_AWAY
    assert entity.unique_id == "CAMERA123-camera_alarm"
    assert entity.device_info["identifiers"] == {("ezviz_plus", "CAMERA123")}


def test_camera_alarm_arms_and_disarms(
    camera_alarm: tuple[EzvizCameraAlarm, SimpleNamespace, MagicMock],
) -> None:
    """Send individual defence commands and publish their optimistic state."""
    entity, coordinator, client = camera_alarm

    asyncio.run(entity.async_alarm_arm_away())

    client.set_camera_defence.assert_called_once_with("CAMERA123", 1)
    coordinator.merge_camera_update.assert_called_once_with(
        "CAMERA123", {"alarm_notify": True}
    )

    client.set_camera_defence.reset_mock()
    coordinator.merge_camera_update.reset_mock()

    asyncio.run(entity.async_alarm_disarm())

    client.set_camera_defence.assert_called_once_with("CAMERA123", 0)
    coordinator.merge_camera_update.assert_called_once_with(
        "CAMERA123", {"alarm_notify": False}
    )


def test_camera_alarm_converts_api_errors(
    camera_alarm: tuple[EzvizCameraAlarm, SimpleNamespace, MagicMock],
) -> None:
    """Expose camera defence API failures as Home Assistant errors."""
    entity, coordinator, client = camera_alarm
    client.set_camera_defence.side_effect = PyEzvizError("API failure")

    with pytest.raises(HomeAssistantError, match="Unable to arm camera"):
        asyncio.run(entity.async_alarm_arm_away())

    assert entity.alarm_state is AlarmControlPanelState.DISARMED
    coordinator.merge_camera_update.assert_not_called()


def test_account_alarm_retains_state_on_transport_failure() -> None:
    """Do not fail the HA entity update for a transient requests error."""
    coordinator = SimpleNamespace(ezviz_client=MagicMock())
    coordinator.ezviz_client.get_group_defence_mode.side_effect = (
        RequestsConnectionError("cloud unavailable")
    )
    entity = EzvizAlarm(
        coordinator,
        "entry-1",
        MagicMock(),
        SimpleNamespace(
            key="ezviz_alarm",
            ezviz_alarm_states=[
                None,
                AlarmControlPanelState.DISARMED,
                AlarmControlPanelState.ARMED_AWAY,
                AlarmControlPanelState.ARMED_HOME,
            ],
        ),
    )
    entity._attr_alarm_state = AlarmControlPanelState.DISARMED
    entity.hass = SimpleNamespace(
        async_add_executor_job=AsyncMock(
            side_effect=RequestsConnectionError("cloud unavailable")
        )
    )

    asyncio.run(entity.async_update())

    assert entity.alarm_state is AlarmControlPanelState.DISARMED


def test_account_alarm_restores_state_before_first_poll() -> None:
    """Avoid an unknown Recorder state while the initial cloud poll starts."""
    entity = EzvizAlarm(
        SimpleNamespace(ezviz_client=MagicMock()),
        "entry-1",
        MagicMock(),
        SimpleNamespace(key="ezviz_alarm"),
    )
    entity.async_get_last_state = AsyncMock(
        return_value=SimpleNamespace(state=AlarmControlPanelState.DISARMED)
    )
    entity.async_schedule_update_ha_state = MagicMock()

    asyncio.run(entity.async_added_to_hass())

    assert entity.alarm_state is AlarmControlPanelState.DISARMED
    entity.async_schedule_update_ha_state.assert_called_once_with(True)


def test_account_alarm_does_not_restore_unknown_state() -> None:
    """Ignore nonfunctional Recorder states during startup restoration."""
    entity = EzvizAlarm(
        SimpleNamespace(ezviz_client=MagicMock()),
        "entry-1",
        MagicMock(),
        SimpleNamespace(key="ezviz_alarm"),
    )
    entity.async_get_last_state = AsyncMock(
        return_value=SimpleNamespace(state="unknown")
    )
    entity.async_schedule_update_ha_state = MagicMock()

    asyncio.run(entity.async_added_to_hass())

    assert entity.alarm_state is None


def test_account_alarm_retains_state_on_timeout(monkeypatch) -> None:
    """Return before HA's slow-update warning while an API call is blocked."""
    async def wait_forever(_target) -> None:
        await blocked_call.wait()

    coordinator = SimpleNamespace(ezviz_client=MagicMock())
    blocked_call = asyncio.Event()
    entity = EzvizAlarm(
        coordinator,
        "entry-1",
        MagicMock(),
        SimpleNamespace(
            key="ezviz_alarm",
            ezviz_alarm_states=[
                None,
                AlarmControlPanelState.DISARMED,
                AlarmControlPanelState.ARMED_AWAY,
                AlarmControlPanelState.ARMED_HOME,
            ],
        ),
    )
    entity._attr_alarm_state = AlarmControlPanelState.DISARMED
    entity.hass = SimpleNamespace(
        async_add_executor_job=AsyncMock(side_effect=wait_forever)
    )
    monkeypatch.setattr(
        "custom_components.ezviz_plus.alarm_control_panel.ALARM_UPDATE_TIMEOUT",
        0.01,
    )

    asyncio.run(entity.async_update())

    assert entity.alarm_state is AlarmControlPanelState.DISARMED
