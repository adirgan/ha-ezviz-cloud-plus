"""Support for Ezviz alarm."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

from pyezvizapi import PyEzvizError
from pyezvizapi.constants import DefenseModeType, SupportExt

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityDescription,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN, MANUFACTURER
from .coordinator import EzvizDataUpdateCoordinator
from .entity import EzvizEntity
from .utility import support_ext_has

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class EzvizAlarmControlPanelEntityDescription(AlarmControlPanelEntityDescription):
    """Describe an EZVIZ Alarm control panel entity."""

    ezviz_alarm_states: list


ALARM_TYPE = EzvizAlarmControlPanelEntityDescription(
    key="ezviz_alarm",
    ezviz_alarm_states=[
        None,
        AlarmControlPanelState.DISARMED,
        AlarmControlPanelState.ARMED_AWAY,
        AlarmControlPanelState.ARMED_HOME,
    ],
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Ezviz alarm control panel."""
    coordinator: EzvizDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]

    identifier = entry.unique_id or entry.entry_id
    device_info = DeviceInfo(
        identifiers={(DOMAIN, identifier)},
        name="EZVIZ Alarm",
        model="EZVIZ Alarm",
        manufacturer=MANUFACTURER,
    )

    camera_alarms = (
        EzvizCameraAlarm(coordinator, serial)
        for serial, camera_data in coordinator.data.items()
        if support_ext_has(camera_data, str(SupportExt.SupportDefence.value))
    )
    async_add_entities(
        [
            EzvizAlarm(coordinator, entry.entry_id, device_info, ALARM_TYPE),
            *camera_alarms,
        ]
    )


class EzvizCameraAlarm(EzvizEntity, AlarmControlPanelEntity):
    """Representation of an individual EZVIZ camera defence state."""

    _attr_code_arm_required = False
    _attr_code_disarm_required = False
    _attr_name = None
    _attr_supported_features = AlarmControlPanelEntityFeature.ARM_AWAY
    _attr_translation_key = "camera_alarm"

    def __init__(
        self, coordinator: EzvizDataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize the individual camera alarm panel."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}-camera_alarm"

    @property
    def alarm_state(self) -> AlarmControlPanelState:
        """Return the current camera defence state."""
        if self.data.get("alarm_notify"):
            return AlarmControlPanelState.ARMED_AWAY
        return AlarmControlPanelState.DISARMED

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Arm motion detection for this camera."""
        await self._async_set_camera_defence(True)

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Disarm motion detection for this camera."""
        await self._async_set_camera_defence(False)

    async def _async_set_camera_defence(self, enable: bool) -> None:
        """Set and publish the individual camera defence state."""
        try:
            await self.hass.async_add_executor_job(
                self.coordinator.ezviz_client.set_camera_defence,
                self._serial,
                int(enable),
            )
        except PyEzvizError as error:
            action = "arm" if enable else "disarm"
            raise HomeAssistantError(f"Unable to {action} camera") from error

        self.coordinator.merge_camera_update(
            self._serial, {"alarm_notify": enable}
        )


class EzvizAlarm(AlarmControlPanelEntity):
    """Representation of an Ezviz alarm control panel."""

    entity_description: EzvizAlarmControlPanelEntityDescription
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_AWAY
        | AlarmControlPanelEntityFeature.ARM_HOME
    )
    _attr_code_arm_required = False

    def __init__(
        self,
        coordinator: EzvizDataUpdateCoordinator,
        entry_id: str,
        device_info: DeviceInfo,
        entity_description: EzvizAlarmControlPanelEntityDescription,
    ) -> None:
        """Initialize alarm control panel entity."""
        self._attr_unique_id = f"{entry_id}_{entity_description.key}"
        self._attr_device_info = device_info
        self.entity_description = entity_description
        self.coordinator = coordinator
        self._attr_alarm_state = None

    async def async_added_to_hass(self) -> None:
        """Entity added to hass."""
        self.async_schedule_update_ha_state(True)

    def alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        try:
            if self.coordinator.ezviz_client.api_set_defence_mode(
                DefenseModeType.HOME_MODE.value
            ):
                self._attr_alarm_state = AlarmControlPanelState.DISARMED

        except PyEzvizError as err:
            raise HomeAssistantError("Cannot disarm EZVIZ alarm") from err

    def alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command."""
        try:
            if self.coordinator.ezviz_client.api_set_defence_mode(
                DefenseModeType.AWAY_MODE.value
            ):
                self._attr_alarm_state = AlarmControlPanelState.ARMED_AWAY

        except PyEzvizError as err:
            raise HomeAssistantError("Cannot arm EZVIZ alarm") from err

    def alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command."""
        try:
            if self.coordinator.ezviz_client.api_set_defence_mode(
                DefenseModeType.SLEEP_MODE.value
            ):
                self._attr_alarm_state = AlarmControlPanelState.ARMED_HOME

        except PyEzvizError as err:
            raise HomeAssistantError("Cannot arm EZVIZ alarm") from err

    def update(self) -> None:
        """Fetch data from EZVIZ."""
        ezviz_alarm_state_number = "0"
        try:
            ezviz_alarm_state_number = (
                self.coordinator.ezviz_client.get_group_defence_mode()
            )
            _LOGGER.debug(
                "Updating EZVIZ alarm with response %s", ezviz_alarm_state_number
            )
            self._attr_alarm_state = self.entity_description.ezviz_alarm_states[
                int(ezviz_alarm_state_number)
            ]

        except PyEzvizError as error:
            raise HomeAssistantError(
                f"Could not fetch EZVIZ alarm status: {error}"
            ) from error
