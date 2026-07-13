"""Tests for SD-card playback view helpers."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.ezviz_plus.const import DATA_COORDINATOR, DOMAIN
from custom_components.ezviz_plus.recordings import EzvizRecording, encode_recording_identifier
from custom_components.ezviz_plus.sdcard import capture_sd_playback
from custom_components.ezviz_plus.views import (
    SdPlaybackView,
    async_generate_sd_playback_url,
)


def test_capture_sd_playback_uses_mpegps_and_vtm_times() -> None:
    """Cloud playback must download MPEG-PS and remux after capture."""
    client = MagicMock()

    def save_clip(_serial: str, output: object, **_kwargs: object) -> None:
        output.write(b"mpegps")  # type: ignore[attr-defined]

    client.save_clip.side_effect = save_clip
    recording = EzvizRecording(
        serial="SERIAL1",
        channel=1,
        begin_time="2026-07-09T22:24:58",
        end_time="2026-07-09T22:25:18",
        lid="lid-1",
    )

    with patch(
        "custom_components.ezviz_plus.sdcard.remux_mpegps_to_mp4",
        return_value=b"mp4",
    ) as remux:
        body = capture_sd_playback(
            client,
            recording,
            "media-key",
            "/usr/bin/ffmpeg",
        )

    assert body == b"mp4"
    client.save_clip.assert_called_once()
    args, kwargs = client.save_clip.call_args
    assert args[0] == "SERIAL1"
    assert kwargs["source"] == "cloud-playback"
    assert kwargs["output_format"] == "mpegps"
    assert kwargs["duration_seconds"] is None
    assert kwargs["decrypt_video"] is True
    assert kwargs["media_key"] == "media-key"
    assert kwargs["nalu_header_size"] is None
    assert kwargs["cloud_client_type"] == 9
    assert kwargs["cloud_token_index"] == 0
    assert kwargs["cloud_refresh_vtm"] is True
    assert kwargs["cloud_playback_begin_time"] == "20260709T222458Z"
    assert kwargs["cloud_playback_end_time"] == "20260709T222518Z"
    assert kwargs["cloud_playback_lid"] == "lid-1"
    assert "timeout" not in kwargs
    remux.assert_called_once_with(b"mpegps", "/usr/bin/ffmpeg")


def test_sd_playback_url_excludes_media_key() -> None:
    """Playback URLs carry only local token and encoded recording metadata."""
    payload = encode_recording_identifier(
        EzvizRecording(
            serial="SERIAL1",
            channel=1,
            begin_time="2026-07-09T22:24:58",
            end_time="2026-07-09T22:25:18",
        )
    )

    url = async_generate_sd_playback_url("entry-1", "local-token", payload)

    assert "local-token" in url
    assert "media-key" not in url
    assert "20260709" not in url


def test_capture_sd_playback_rejects_too_long_interval() -> None:
    """Keep in-memory MVP bounded until streaming cancellation is implemented."""
    client = MagicMock()
    recording = EzvizRecording(
        serial="SERIAL1",
        channel=1,
        begin_time="2026-07-09T22:24:58",
        end_time="2026-07-09T22:35:18",
    )

    with pytest.raises(Exception, match="Invalid SD playback duration"):
        capture_sd_playback(client, recording, None, "/usr/bin/ffmpeg")

    client.save_clip.assert_not_called()


def test_sd_playback_view_rejects_unknown_camera() -> None:
    """Return 404 before any cloud work when the camera serial is unknown."""

    async def run() -> None:
        entry = SimpleNamespace(domain=DOMAIN)
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_get_entry=MagicMock(return_value=entry)),
            data={
                DOMAIN: {
                    "entry-1": {
                        DATA_COORDINATOR: SimpleNamespace(
                            ezviz_client=MagicMock(),
                            data={},
                        )
                    }
                }
            },
        )
        payload = encode_recording_identifier(
            EzvizRecording(
                serial="SERIAL1",
                channel=1,
                begin_time="2026-07-09T22:24:58",
                end_time="2026-07-09T22:25:18",
            )
        )

        response = await SdPlaybackView(hass).get(  # type: ignore[arg-type]
            MagicMock(), "entry-1", "token", payload
        )

        assert response.status == HTTPStatus.NOT_FOUND

    asyncio.run(run())


def test_sd_playback_view_rejects_bad_token() -> None:
    """Return 403 when the local playback token does not match."""

    async def run() -> None:
        entry = SimpleNamespace(domain=DOMAIN)
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_get_entry=MagicMock(return_value=entry)),
            data={
                DOMAIN: {
                    "entry-1": {
                        DATA_COORDINATOR: SimpleNamespace(
                            ezviz_client=MagicMock(),
                            data={"SERIAL1": {}},
                        )
                    },
                    "_sd_playback_tokens": {"SERIAL1": "expected-token"},
                }
            },
        )
        payload = encode_recording_identifier(
            EzvizRecording(
                serial="SERIAL1",
                channel=1,
                begin_time="2026-07-09T22:24:58",
                end_time="2026-07-09T22:25:18",
            )
        )

        response = await SdPlaybackView(hass).get(  # type: ignore[arg-type]
            MagicMock(), "entry-1", "wrong-token", payload
        )

        assert response.status == HTTPStatus.FORBIDDEN

    asyncio.run(run())