"""Ezviz Integration views (proxy and decrypt images)."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
import binascii
from contextlib import suppress
from http import HTTPStatus
import logging

from aiohttp import ClientError, ClientTimeout, web
from pyezvizapi.constants import HIK_ENCRYPTION_HEADER
from pyezvizapi.exceptions import PyEzvizError
from pyezvizapi.utils import decrypt_image

from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.text import DOMAIN as TEXT_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .cloud_video import CloudMpegtsStream
from .const import CONF_ENC_KEY, DATA_COORDINATOR, DOMAIN, OPTIONS_KEY_CAMERAS
from .recordings import decode_recording_identifier
from .sdcard import capture_sd_playback

_LOGGER = logging.getLogger(__name__)


@callback
def async_generate_image_proxy_url(config_entry_id: str, serial: str, url: str) -> str:
    """Generate proxy URL for alarm image (decrypted if needed)."""
    return ImageProxyView.url.format(
        config_entry_id=config_entry_id,
        serial=serial,
        url=urlsafe_b64encode(url.encode("utf-8")).decode("utf-8"),
    )


@callback
def async_generate_cloud_stream_url(config_entry_id: str, serial: str, token: str) -> str:
    """Generate a local URL for the cloud MPEG-TS stream proxy."""

    return CloudStreamView.url.format(
        config_entry_id=config_entry_id,
        serial=serial,
        token=token,
    )


@callback
def async_generate_sd_playback_url(config_entry_id: str, token: str, payload: str) -> str:
    """Generate a local URL for an SD-card playback stream."""

    return SdPlaybackView.url.format(
        config_entry_id=config_entry_id,
        token=token,
        payload=payload,
    )


class ImageProxyView(HomeAssistantView):
    """View to proxy and decrypt Ezviz alarm images."""

    requires_auth = True
    url = "/api/ezviz_plus/image/{config_entry_id}/{serial}/{url}"
    name = "api:ezviz_plus_image"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the proxy view."""
        self.hass = hass
        self.session = async_get_clientsession(hass)

    async def get(
        self, request: web.Request, config_entry_id: str, serial: str, url: str
    ) -> web.StreamResponse:
        """Return decrypted image bytes for an alarm picture."""
        try:
            raw_url = urlsafe_b64decode(url.encode("utf-8")).decode("utf-8")
        except (ValueError, binascii.Error, UnicodeDecodeError):
            return web.Response(
                text="Invalid encoded URL",
                status=HTTPStatus.BAD_REQUEST,
            )

        entry = self.hass.config_entries.async_get_entry(config_entry_id)
        if entry is None or entry.domain != DOMAIN:
            return web.Response(
                text=f"Unknown config entry id: {config_entry_id}",
                status=HTTPStatus.BAD_REQUEST,
            )

        # 1) Prefer runtime Text entity value (if enabled) for the enc key
        enc_key: str | None = None
        entity_reg = er.async_get(self.hass)
        text_entity_id = entity_reg.async_get_entity_id(
            TEXT_DOMAIN, DOMAIN, f"{serial}_camera_enc_key"
        )
        if text_entity_id:
            state = self.hass.states.get(text_entity_id)
            if state and state.state and state.state.lower() != "unavailable":
                enc_key = state.state

        # 2) Fallback to options mapping
        if not enc_key:
            enc_key = (
                (entry.options.get(OPTIONS_KEY_CAMERAS, {}) or {})
                .get(serial, {})
                .get(CONF_ENC_KEY)
            )

        # Security: never forward HA's incoming request headers (e.g., Authorization)
        # to third-party endpoints. Build a minimal, safe header set.
        headers = {
            "User-Agent": "HomeAssistant/ezviz_plus",
            "Accept": "*/*",
        }

        try:
            resp = await self.session.get(
                raw_url,
                headers=headers,
                timeout=ClientTimeout(connect=10, sock_connect=10, sock_read=20),
            )
        except ClientError as err:
            _LOGGER.debug("Error fetching Ezviz image: %s", err)
            return web.Response(text=str(err), status=HTTPStatus.BAD_REQUEST)

        if resp.status != HTTPStatus.OK:
            text = await resp.text()
            return web.Response(text=text, status=resp.status)

        content_type = resp.headers.get("Content-Type", "image/jpeg")
        body = await resp.read()

        # Try to decrypt if key available; the helper returns original if unencrypted
        if enc_key:
            try:
                body = decrypt_image(body, enc_key)
            except PyEzvizError as err:
                # Invalid key or format; surface an error to caller
                _LOGGER.debug("Decrypt failed: %s", err)
                return web.Response(text=str(err), status=HTTPStatus.BAD_REQUEST)
        # If no key is set and the payload looks encrypted, warn once per request
        elif body[: len(HIK_ENCRYPTION_HEADER)] == HIK_ENCRYPTION_HEADER:
            _LOGGER.warning(
                "Image appears encrypted but no encryption key is set for camera %s",
                serial,
            )

        return web.Response(body=body, content_type=content_type)


class CloudStreamView(HomeAssistantView):
    """View to expose an EZVIZ cloud stream as MPEG-TS."""

    requires_auth = False
    url = "/api/ezviz_plus/cloud_stream/{config_entry_id}/{serial}/{token}.ts"
    name = "api:ezviz_plus_cloud_stream"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the cloud stream view."""
        self.hass = hass

    async def get(
        self, request: web.Request, config_entry_id: str, serial: str, token: str
    ) -> web.StreamResponse:
        """Return a continuous cloud MPEG-TS stream for HA's stream worker."""
        entry = self.hass.config_entries.async_get_entry(config_entry_id)
        if entry is None or entry.domain != DOMAIN:
            return web.Response(
                text=f"Unknown config entry id: {config_entry_id}",
                status=HTTPStatus.BAD_REQUEST,
            )

        coordinator = self.hass.data.get(DOMAIN, {}).get(config_entry_id, {}).get(
            DATA_COORDINATOR
        )
        if coordinator is None or serial not in coordinator.data:
            return web.Response(
                text="Unknown EZVIZ camera",
                status=HTTPStatus.NOT_FOUND,
            )
        expected_token = self.hass.data.get(DOMAIN, {}).get("_cloud_stream_tokens", {}).get(
            serial
        )
        if expected_token is None or token != expected_token:
            return web.Response(text="Invalid stream token", status=HTTPStatus.FORBIDDEN)

        media_key = (
            (entry.options.get(OPTIONS_KEY_CAMERAS, {}) or {})
            .get(serial, {})
            .get(CONF_ENC_KEY)
        )
        ffmpeg_path = get_ffmpeg_manager(self.hass).binary
        response = web.StreamResponse(
            status=HTTPStatus.OK,
            headers={"Content-Type": "video/mp2t"},
        )
        await response.prepare(request)

        cloud_stream = CloudMpegtsStream(
            coordinator.ezviz_client,
            serial,
            media_key=media_key,
            ffmpeg_path=ffmpeg_path,
            output_codec="h264",
        )

        try:
            while True:
                chunk = await self.hass.async_add_executor_job(cloud_stream.read)
                if not chunk:
                    break
                await response.write(chunk)
        except (ConnectionError, ConnectionResetError):
            pass
        except PyEzvizError:
            _LOGGER.warning("Cloud stream failed for a configured camera")
        finally:
            cloud_stream.close()

        with suppress(ConnectionError, ConnectionResetError):
            await response.write_eof()
        return response


class SdPlaybackView(HomeAssistantView):
    """View to expose an EZVIZ SD-card recording segment as MP4."""

    requires_auth = False
    url = "/api/ezviz_plus/sd_playback/{config_entry_id}/{token}/{payload}.mp4"
    name = "api:ezviz_plus_sd_playback"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the SD playback view."""
        self.hass = hass

    async def get(
        self, request: web.Request, config_entry_id: str, token: str, payload: str
    ) -> web.Response:
        """Return a playable MPEG-TS clip for one SD-card recording segment."""
        try:
            recording = decode_recording_identifier(payload)
        except (ValueError, binascii.Error, UnicodeDecodeError, KeyError, TypeError):
            return web.Response(text="Invalid recording payload", status=HTTPStatus.BAD_REQUEST)

        entry = self.hass.config_entries.async_get_entry(config_entry_id)
        if entry is None or entry.domain != DOMAIN:
            return web.Response(
                text=f"Unknown config entry id: {config_entry_id}",
                status=HTTPStatus.BAD_REQUEST,
            )

        coordinator = self.hass.data.get(DOMAIN, {}).get(config_entry_id, {}).get(
            DATA_COORDINATOR
        )
        if coordinator is None or recording.serial not in coordinator.data:
            return web.Response(
                text="Unknown EZVIZ camera",
                status=HTTPStatus.NOT_FOUND,
            )

        expected_token = self.hass.data.get(DOMAIN, {}).get(
            "_sd_playback_tokens", {}
        ).get(recording.serial)
        if expected_token is None or token != expected_token:
            return web.Response(text="Invalid playback token", status=HTTPStatus.FORBIDDEN)

        media_key = (
            (entry.options.get(OPTIONS_KEY_CAMERAS, {}) or {})
            .get(recording.serial, {})
            .get(CONF_ENC_KEY)
        )
        ffmpeg_path = get_ffmpeg_manager(self.hass).binary

        try:
            body = await self.hass.async_add_executor_job(
                capture_sd_playback,
                coordinator.ezviz_client,
                recording,
                media_key,
                ffmpeg_path,
            )
        except TypeError as err:
            _LOGGER.warning("pyEzvizApi does not support cloud playback yet: %s", err)
            return web.Response(
                text="Installed pyEzvizApi does not support SD cloud playback yet",
                status=HTTPStatus.NOT_IMPLEMENTED,
            )
        except PyEzvizError:
            _LOGGER.warning("SD playback failed for a configured camera")
            return web.Response(
                text="EZVIZ SD playback failed", status=HTTPStatus.BAD_GATEWAY
            )

        return web.Response(body=body, content_type="video/mp4")
