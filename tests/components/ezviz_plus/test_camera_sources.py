"""Tests for per-camera media source routing."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pyezvizapi.exceptions import PyEzvizError
import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from custom_components.ezviz_plus.camera import EzvizCamera
from custom_components.ezviz_plus.const import (
    MEDIA_SOURCE_AUTO,
    MEDIA_SOURCE_CLOUD,
    MEDIA_SOURCE_LOCAL,
)

CLOUD_IMAGE = b"\xff\xd8" + b"image-data" * 8 + b"\xff\xd9"


def _camera(source: str) -> EzvizCamera:
    """Build the smallest camera object needed to test image routing."""
    camera = object.__new__(EzvizCamera)
    camera.hass = SimpleNamespace(async_add_executor_job=AsyncMock())
    camera.coordinator = SimpleNamespace(ezviz_client=MagicMock())
    camera._serial = "TEST123"
    camera._image_source = source
    camera._encryption_key = "camera-key"
    camera._last_camera_image = None
    camera._camera_image_updated_at = 0.0
    camera._camera_image_task = None
    camera.async_write_ha_state = MagicMock()
    camera._build_rtsp = MagicMock(return_value="rtsp://local-camera/stream")
    return camera


def _stream_camera(source: str) -> EzvizCamera:
    """Build the smallest camera object needed to test live routing."""
    camera = _camera(MEDIA_SOURCE_AUTO)
    camera.hass.data = {}
    camera._live_stream_source = source
    camera._config_entry_id = "entry-1"
    camera._cloud_stream_token = "token-1"
    return camera


async def _run_executor_job(callable_job: object, *args: object) -> object:
    """Run a submitted executor callable synchronously in the test loop."""
    return callable_job(*args)  # type: ignore[operator]


def _save_cloud_image(serial: str, output: object, **kwargs: object) -> dict[str, object]:
    """Write a representative image through the save_image contract."""
    output.write(CLOUD_IMAGE)  # type: ignore[attr-defined]
    return {"ok": True, "serial": serial, **kwargs}


@pytest.mark.asyncio
async def test_local_image_never_calls_cloud() -> None:
    """Keep local-only current images entirely off EZVIZ Cloud."""
    camera = _camera(MEDIA_SOURCE_LOCAL)

    with patch(
        "custom_components.ezviz_plus.camera.ffmpeg.async_get_image",
        AsyncMock(return_value=None),
    ) as get_image:
        assert await camera.async_camera_image() is None

    get_image.assert_awaited_once()
    camera.hass.async_add_executor_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_cloud_image_skips_local_rtsp() -> None:
    """Skip the LAN when the current-image source is cloud-only."""
    camera = _camera(MEDIA_SOURCE_CLOUD)
    camera.hass.async_add_executor_job.side_effect = _run_executor_job
    camera.coordinator.ezviz_client.save_image.side_effect = _save_cloud_image

    with patch(
        "custom_components.ezviz_plus.camera.ffmpeg.async_get_image",
        AsyncMock(),
    ) as get_image:
        assert await camera.async_camera_image() == CLOUD_IMAGE

    get_image.assert_not_awaited()
    assert camera.hass.async_add_executor_job.await_count == 2
    camera.coordinator.ezviz_client.save_image.assert_called_once()
    args, kwargs = camera.coordinator.ezviz_client.save_image.call_args
    assert args[0] == "TEST123"
    assert args[1].getvalue() == CLOUD_IMAGE
    assert kwargs == {"channel": 1, "decrypt": False}
    decrypt_call = camera.hass.async_add_executor_job.await_args_list[1]
    assert decrypt_call.args[1:] == (CLOUD_IMAGE, "camera-key")


@pytest.mark.asyncio
async def test_cloud_image_returns_none_when_save_image_fails() -> None:
    """Return no frame when the high-level cloud image helper fails."""
    camera = _camera(MEDIA_SOURCE_CLOUD)
    camera.hass.async_add_executor_job.side_effect = PyEzvizError(
        "Capture response did not include an image URL"
    )

    with patch(
        "custom_components.ezviz_plus.camera.asyncio.sleep", AsyncMock()
    ) as retry_sleep:
        assert await camera.async_camera_image() is None

    assert camera.hass.async_add_executor_job.await_count == 3
    assert retry_sleep.await_count == 2


@pytest.mark.asyncio
async def test_cloud_image_retries_transient_capture_failure() -> None:
    """Recover a preview without requiring a full page reload."""
    camera = _camera(MEDIA_SOURCE_CLOUD)
    camera._encryption_key = ""

    def fail_then_save(callable_job: object, *args: object) -> object:
        if camera.hass.async_add_executor_job.await_count == 1:
            raise PyEzvizError("Cloud snapshot is not ready")
        return callable_job(*args)  # type: ignore[operator]

    camera.hass.async_add_executor_job.side_effect = fail_then_save
    camera.coordinator.ezviz_client.save_image.side_effect = _save_cloud_image

    with patch(
        "custom_components.ezviz_plus.camera.asyncio.sleep", AsyncMock()
    ) as retry_sleep:
        assert await camera.async_camera_image() == CLOUD_IMAGE

    retry_sleep.assert_awaited_once()
    assert camera.coordinator.ezviz_client.save_image.call_count == 1


@pytest.mark.asyncio
async def test_cloud_image_retains_last_preview_after_retries() -> None:
    """Keep the previous preview visible during a transient cloud outage."""
    camera = _camera(MEDIA_SOURCE_CLOUD)
    camera._last_camera_image = CLOUD_IMAGE
    camera.hass.async_add_executor_job.side_effect = PyEzvizError(
        "Capture response did not include an image URL"
    )

    with patch("custom_components.ezviz_plus.camera.asyncio.sleep", AsyncMock()):
        assert await camera.async_camera_image() == CLOUD_IMAGE


@pytest.mark.asyncio
async def test_cloud_image_retries_requests_transport_failure() -> None:
    """Retry raw requests failures emitted by the upstream API client."""
    camera = _camera(MEDIA_SOURCE_CLOUD)
    camera._encryption_key = ""

    def fail_then_save(callable_job: object, *args: object) -> object:
        if camera.hass.async_add_executor_job.await_count == 1:
            raise RequestsConnectionError("cloud unavailable")
        return callable_job(*args)  # type: ignore[operator]

    camera.hass.async_add_executor_job.side_effect = fail_then_save
    camera.coordinator.ezviz_client.save_image.side_effect = _save_cloud_image

    with patch("custom_components.ezviz_plus.camera.asyncio.sleep", AsyncMock()):
        assert await camera.async_camera_image() == CLOUD_IMAGE


@pytest.mark.asyncio
async def test_cloud_image_refresh_survives_proxy_cancellation() -> None:
    """Finish and publish a slow preview after HA cancels the proxy request."""
    camera = _camera(MEDIA_SOURCE_CLOUD)
    camera._encryption_key = ""
    capture_started = asyncio.Event()
    release_capture = asyncio.Event()

    async def delayed_executor(callable_job: object, *args: object) -> object:
        capture_started.set()
        await release_capture.wait()
        return callable_job(*args)  # type: ignore[operator]

    camera.hass.async_add_executor_job.side_effect = delayed_executor
    camera.coordinator.ezviz_client.save_image.side_effect = _save_cloud_image

    request = asyncio.create_task(camera.async_camera_image())
    await capture_started.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request

    release_capture.set()
    assert camera._camera_image_task is not None
    await camera._camera_image_task

    assert camera._last_camera_image == CLOUD_IMAGE
    camera.async_write_ha_state.assert_called_once_with()


@pytest.mark.asyncio
async def test_cloud_image_returns_cache_while_refreshing() -> None:
    """Serve the previous JPEG immediately while one refresh runs in background."""
    camera = _camera(MEDIA_SOURCE_CLOUD)
    camera._last_camera_image = CLOUD_IMAGE
    refresh = asyncio.get_running_loop().create_future()
    camera._camera_image_task = refresh

    assert await camera.async_camera_image() == CLOUD_IMAGE

    camera.hass.async_add_executor_job.assert_not_awaited()
    refresh.cancel()


@pytest.mark.asyncio
async def test_cloud_image_does_not_refresh_fresh_cache() -> None:
    """Avoid one cloud capture per frontend preview request."""
    camera = _camera(MEDIA_SOURCE_CLOUD)
    camera._last_camera_image = CLOUD_IMAGE
    camera._camera_image_updated_at = 100.0

    with patch("custom_components.ezviz_plus.camera.time.monotonic", return_value=399.0):
        assert await camera.async_camera_image() == CLOUD_IMAGE

    assert camera._camera_image_task is None
    camera.hass.async_add_executor_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_camera_removal_cancels_preview_refresh() -> None:
    """Do not leave background cloud work attached to a removed entity."""
    camera = _camera(MEDIA_SOURCE_CLOUD)
    refresh = asyncio.get_running_loop().create_future()
    camera._camera_image_task = refresh

    await camera.async_will_remove_from_hass()

    assert refresh.cancelled()


@pytest.mark.asyncio
async def test_auto_image_falls_back_to_cloud() -> None:
    """Use cloud for automatic current images only after LAN returns no frame."""
    camera = _camera(MEDIA_SOURCE_AUTO)
    camera.hass.async_add_executor_job.side_effect = _run_executor_job
    camera.coordinator.ezviz_client.save_image.side_effect = _save_cloud_image

    with patch(
        "custom_components.ezviz_plus.camera.ffmpeg.async_get_image",
        AsyncMock(return_value=None),
    ) as get_image:
        assert await camera.async_camera_image(width=640, height=360) == CLOUD_IMAGE

    get_image.assert_awaited_once_with(
        camera.hass,
        "rtsp://local-camera/stream",
        width=640,
        height=360,
    )
    assert camera.hass.async_add_executor_job.await_count == 2


@pytest.mark.asyncio
async def test_cloud_stream_source_returns_proxy_url() -> None:
    """Route cloud-only live video through the integration proxy."""
    camera = _stream_camera(MEDIA_SOURCE_CLOUD)

    with patch(
        "custom_components.ezviz_plus.camera.get_url",
        return_value="http://ha.local:8123",
    ):
        assert await camera.stream_source() == (
            "http://ha.local:8123"
            "/api/ezviz_plus/cloud_stream/entry-1/TEST123/token-1.ts"
        )


@pytest.mark.asyncio
async def test_local_stream_source_returns_rtsp_url() -> None:
    """Keep local-only live video on the RTSP path."""
    camera = _stream_camera(MEDIA_SOURCE_LOCAL)

    assert await camera.stream_source() == "rtsp://local-camera/stream"
