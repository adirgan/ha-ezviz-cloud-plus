"""Support EZVIZ camera devices.

This module exposes Home Assistant camera entities based on data provided by the
cloud-scoped EZVIZ config entry. There are no per-camera config entries or discovery
flows. Per-camera configuration is read from the cloud entry's options at:

    entry.options["cameras"][<SERIAL>]

Where <SERIAL> is the camera serial. The legacy
option name `CONF_FFMPEG_ARGUMENTS` is used to store the RTSP *path* (e.g.,
"/Streaming/Channels/102"). We keep this name for compatibility with existing setups.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from functools import partial
from io import BytesIO
import logging
from secrets import token_urlsafe
import time
from typing import Any

from pyezvizapi.exceptions import HTTPError, InvalidHost, PyEzvizError
from pyezvizapi.utils import decrypt_image
from requests.exceptions import RequestException

from homeassistant.components import ffmpeg
from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.components.stream import CONF_USE_WALLCLOCK_AS_TIMESTAMPS
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)
from homeassistant.helpers.network import get_url

from .const import (
    CONF_ENC_KEY,
    CONF_FFMPEG_ARGUMENTS,  # used here as RTSP path (main/sub)
    CONF_IMAGE_SOURCE,
    CONF_LIVE_STREAM_SOURCE,
    CONF_RTSP_USES_VERIFICATION_CODE,
    DATA_COORDINATOR,
    DEFAULT_CAMERA_USERNAME,
    DEFAULT_FFMPEG_ARGUMENTS,  # default RTSP path
    DOMAIN,
    MEDIA_SOURCE_AUTO,
    MEDIA_SOURCE_CLOUD,
    MEDIA_SOURCE_LOCAL,
    OPTIONS_KEY_CAMERAS,
    SERVICE_WAKE_DEVICE,
)
from .coordinator import EzvizDataUpdateCoordinator
from .entity import EzvizEntity
from .views import async_generate_cloud_stream_url

_LOGGER = logging.getLogger(__name__)
_CLOUD_IMAGE_RETRY_DELAYS = (0.0, 0.5, 1.0)
_CAMERA_IMAGE_REFRESH_INTERVAL = 5 * 60.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EZVIZ cameras for a cloud config entry."""
    coordinator: EzvizDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]

    cams_opts: Mapping[str, dict[str, Any]] = entry.options[OPTIONS_KEY_CAMERAS]

    entities: list[EzvizCamera] = []
    for serial in coordinator.data:
        per_cam: dict[str, Any] = cams_opts.get(serial, {})

        username: str = per_cam.get(CONF_USERNAME, DEFAULT_CAMERA_USERNAME)

        use_vc: bool = bool(per_cam.get(CONF_RTSP_USES_VERIFICATION_CODE, False))
        enc_key: str = per_cam.get(CONF_ENC_KEY, "")
        password: str = enc_key if not use_vc else per_cam.get(CONF_PASSWORD, "")

        rtsp_path: str = per_cam.get(CONF_FFMPEG_ARGUMENTS, DEFAULT_FFMPEG_ARGUMENTS)
        image_source: str = per_cam.get(CONF_IMAGE_SOURCE, MEDIA_SOURCE_AUTO)
        live_stream_source: str = per_cam.get(
            CONF_LIVE_STREAM_SOURCE, MEDIA_SOURCE_AUTO
        )

        if rtsp_path and not rtsp_path.startswith("/"):
            # Be lenient: if users saved path without leading slash, add it.
            rtsp_path = "/" + rtsp_path

        if not password:
            _LOGGER.warning(
                "A configured camera is missing its RTSP password%s; stream may be unavailable until provided",
                " (verification code expected for RTSP)"
                if use_vc
                else " (encryption code expected for RTSP)",
            )

        entities.append(
            EzvizCamera(
                hass=hass,
                coordinator=coordinator,
                serial=serial,  # canonical unique_id
                config_entry_id=entry.entry_id,
                camera_username=username,
                camera_password=password,
                rtsp_path=rtsp_path,
                media_options={
                    CONF_ENC_KEY: enc_key,
                    CONF_IMAGE_SOURCE: image_source,
                    CONF_LIVE_STREAM_SOURCE: live_stream_source,
                },
            )
        )

    async_add_entities(entities)

    # Expose wake service on the camera platform.
    platform = async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_WAKE_DEVICE, None, "perform_wake_device"
    )


class EzvizCamera(EzvizEntity, Camera):
    """EZVIZ security camera entity."""

    _attr_name: str | None = None
    _attr_supported_features: CameraEntityFeature = CameraEntityFeature.STREAM

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: EzvizDataUpdateCoordinator,
        serial: str,
        config_entry_id: str,
        camera_username: str,
        camera_password: str,
        rtsp_path: str,
        media_options: Mapping[str, Any],
    ) -> None:
        """Initialize the camera entity."""
        super().__init__(coordinator, serial)
        Camera.__init__(self)

        self.stream_options[CONF_USE_WALLCLOCK_AS_TIMESTAMPS] = True

        self._config_entry_id = config_entry_id
        self._username: str = camera_username
        self._password: str = camera_password
        self._rtsp_path: str = rtsp_path
        self._encryption_key = str(media_options.get(CONF_ENC_KEY, ""))
        self._image_source = str(
            media_options.get(CONF_IMAGE_SOURCE, MEDIA_SOURCE_AUTO)
        )
        self._live_stream_source = str(
            media_options.get(CONF_LIVE_STREAM_SOURCE, MEDIA_SOURCE_AUTO)
        )
        self._ffmpeg = get_ffmpeg_manager(hass)
        self._attr_unique_id = serial
        self._rtsp_stream: str = self._build_rtsp()
        self._last_camera_image: bytes | None = None
        self._camera_image_updated_at = 0.0
        self._camera_image_task: asyncio.Task[bytes | None] | None = None
        domain_data = hass.data.setdefault(DOMAIN, {})
        stream_tokens = domain_data.setdefault("_cloud_stream_tokens", {})
        self._cloud_stream_token = stream_tokens.setdefault(serial, token_urlsafe(24))

    def _build_rtsp(self) -> str:
        """Build an RTSP URL from coordinator data and per-camera credentials.

        Returns:
            str
            RTSP URL in the form:'rtsp://<user>:<pass>@<ip>:<port><path>'
        """
        ip = self.data["local_ip"]
        port = self.data["local_rtsp_port"]
        path = self._rtsp_path or ""
        return f"rtsp://{self._username}:{self._password}@{ip}:{port}{path}"

    async def async_will_remove_from_hass(self) -> None:
        """Cancel an active preview refresh when the entity is removed."""
        if self._camera_image_task is not None:
            self._camera_image_task.cancel()
        await super().async_will_remove_from_hass()

    @property
    def is_recording(self) -> bool:
        """Return True if the device is currently recording."""
        return bool(self.data["alarm_notify"])

    @property
    def motion_detection_enabled(self) -> bool:
        """Return True if motion detection is enabled."""
        return bool(self.data["alarm_notify"])

    def enable_motion_detection(self) -> None:
        """Enable motion detection (a.k.a. defence) on the device."""
        try:
            self.coordinator.ezviz_client.set_camera_defence(self._serial, 1)

        except InvalidHost as err:
            raise InvalidHost("Error enabling motion detection") from err

    def disable_motion_detection(self) -> None:
        """Disable motion detection (a.k.a. defence) on the device."""
        try:
            self.coordinator.ezviz_client.set_camera_defence(self._serial, 0)

        except InvalidHost as err:
            raise InvalidHost("Error disabling motion detection") from err

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a current image using the configured per-camera transport."""
        image_task = self._camera_image_task
        image_is_fresh = (
            self._last_camera_image is not None
            and time.monotonic() - self._camera_image_updated_at
            < _CAMERA_IMAGE_REFRESH_INTERVAL
        )
        if not image_is_fresh and (image_task is None or image_task.done()):
            image_task = asyncio.create_task(
                self._async_refresh_camera_image(width, height)
            )
            image_task.add_done_callback(self._camera_image_refresh_finished)
            self._camera_image_task = image_task

        if self._last_camera_image is not None:
            return self._last_camera_image

        assert image_task is not None
        return await asyncio.shield(image_task)

    async def _async_refresh_camera_image(
        self, width: int | None, height: int | None
    ) -> bytes | None:
        """Refresh the cached preview without depending on the proxy request."""
        if self._image_source != MEDIA_SOURCE_CLOUD:
            local_image = await ffmpeg.async_get_image(
                self.hass, self._build_rtsp(), width=width, height=height
            )
            if local_image is not None:
                self._last_camera_image = local_image
                self._camera_image_updated_at = time.monotonic()
                return local_image
            if self._image_source == MEDIA_SOURCE_LOCAL:
                return self._last_camera_image

        for attempt, retry_delay in enumerate(_CLOUD_IMAGE_RETRY_DELAYS):
            if retry_delay:
                await asyncio.sleep(retry_delay)

            image = BytesIO()
            try:
                await self.hass.async_add_executor_job(
                    partial(
                        self.coordinator.ezviz_client.save_image,
                        self._serial,
                        image,
                        channel=1,
                        decrypt=not bool(self._encryption_key),
                    )
                )
                image_data = image.getvalue()
                if self._encryption_key:
                    image_data = await self.hass.async_add_executor_job(
                        decrypt_image, image_data, self._encryption_key
                    )
                if image_data:
                    self._last_camera_image = image_data
                    self._camera_image_updated_at = time.monotonic()
                    return image_data
            except (PyEzvizError, RequestException):
                if attempt < len(_CLOUD_IMAGE_RETRY_DELAYS) - 1:
                    continue
            else:
                if attempt < len(_CLOUD_IMAGE_RETRY_DELAYS) - 1:
                    continue
            break

        _LOGGER.debug("Cloud snapshot retries exhausted; retaining last preview")
        return self._last_camera_image

    def _camera_image_refresh_finished(
        self, image_task: asyncio.Task[bytes | None]
    ) -> None:
        """Publish a completed background preview refresh."""
        if image_task.cancelled() or image_task.exception() is not None:
            return
        if image_task.result() is not None and self.hass is not None:
            self.async_write_ha_state()

    async def stream_source(self) -> str:
        """Return the RTSP stream source for HA's stream component."""
        if self._live_stream_source == MEDIA_SOURCE_CLOUD:
            return get_url(self.hass, allow_external=False) + async_generate_cloud_stream_url(
                self._config_entry_id, self._serial, self._cloud_stream_token
            )
        return self._build_rtsp()

    def perform_wake_device(self) -> None:
        """Wake/ping the camera using a lightweight API call."""
        try:
            self.coordinator.ezviz_client.get_detection_sensibility(self._serial)
        except (HTTPError, PyEzvizError) as err:
            raise PyEzvizError("Cannot wake device") from err
