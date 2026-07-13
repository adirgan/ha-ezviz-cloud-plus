"""Tests for EZVIZ SD-card download and remux helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pyezvizapi.exceptions import PyEzvizError
import pytest

from custom_components.ezviz_plus.recordings import EzvizRecording
from custom_components.ezviz_plus.sdcard import (
    BENIGN_VTM_EOF,
    capture_sd_playback,
    capture_sd_playback_mpegts,
    remux_mpegps_to_mp4,
    remux_mpegps_to_mpegts,
)


def _recording() -> EzvizRecording:
    return EzvizRecording(
        serial="SERIAL1",
        channel=1,
        begin_time="2026-07-09T22:24:58",
        end_time="2026-07-09T22:25:18",
    )


def test_capture_uses_cloud_playback_contract() -> None:
    """Pass the exact MPEG-PS and VTM arguments expected by pyEzvizApi."""
    client = MagicMock()
    client.save_clip.side_effect = lambda _serial, output, **_kwargs: output.write(
        b"mpegps"
    )

    with patch(
        "custom_components.ezviz_plus.sdcard.remux_mpegps_to_mpegts",
        return_value=b"mpegts",
    ):
        assert capture_sd_playback_mpegts(
            client, _recording(), None, "/usr/bin/ffmpeg"
        ) == b"mpegts"

    _args, kwargs = client.save_clip.call_args
    assert kwargs["source"] == "cloud-playback"
    assert kwargs["output_format"] == "mpegps"
    assert kwargs["cloud_client_type"] == 9
    assert kwargs["cloud_token_index"] == 0
    assert kwargs["cloud_refresh_vtm"] is True
    assert kwargs["cloud_playback_begin_time"] == "20260709T222458Z"
    assert kwargs["cloud_playback_end_time"] == "20260709T222518Z"
    assert "timeout" not in kwargs


def test_vtm_eof_with_zero_bytes_is_an_error() -> None:
    """Do not hide a VTM EOF when no media was received."""
    client = MagicMock()
    client.save_clip.side_effect = PyEzvizError(BENIGN_VTM_EOF)

    with pytest.raises(PyEzvizError, match=BENIGN_VTM_EOF):
        capture_sd_playback_mpegts(client, _recording(), None, "/usr/bin/ffmpeg")


def test_vtm_eof_after_bytes_remuxes_unencrypted_media() -> None:
    """Treat server EOF as completion only when clear MPEG-PS bytes validate."""
    client = MagicMock()

    def save_clip(_serial: str, output: object, **_kwargs: object) -> None:
        output.write(b"valid-mpegps")  # type: ignore[attr-defined]
        raise PyEzvizError(BENIGN_VTM_EOF)

    client.save_clip.side_effect = save_clip
    with patch(
        "custom_components.ezviz_plus.sdcard.remux_mpegps_to_mpegts",
        return_value=b"mpegts",
    ) as remux:
        assert capture_sd_playback_mpegts(
            client, _recording(), None, "/usr/bin/ffmpeg"
        ) == b"mpegts"

    remux.assert_called_once_with(b"valid-mpegps", "/usr/bin/ffmpeg")


def test_vtm_eof_is_not_ignored_for_encrypted_media() -> None:
    """Do not apply partial-payload EOF handling to encrypted playback."""
    client = MagicMock()

    def save_clip(_serial: str, output: object, **_kwargs: object) -> None:
        output.write(b"partial-encrypted")  # type: ignore[attr-defined]
        raise PyEzvizError(BENIGN_VTM_EOF)

    client.save_clip.side_effect = save_clip
    with pytest.raises(PyEzvizError, match=BENIGN_VTM_EOF):
        capture_sd_playback_mpegts(
            client, _recording(), "media-key", "/usr/bin/ffmpeg"
        )


def test_remux_mpegps_to_mpegts_uses_stream_copy() -> None:
    """Remux valid MPEG-PS to MPEG-TS without transcoding."""
    completed = MagicMock(returncode=0, stdout=b"mpegts", stderr=b"")
    with patch("custom_components.ezviz_plus.sdcard.subprocess.run", return_value=completed) as run:
        assert remux_mpegps_to_mpegts(b"mpegps", "ffmpeg") == b"mpegts"

    command = run.call_args.args[0]
    assert command[command.index("-c") + 1] == "copy"
    assert command[-2:] == ["mpegts", "pipe:1"]


def test_capture_defaults_to_browser_playable_mp4() -> None:
    """Return MP4 by default for Home Assistant Media Source playback."""
    client = MagicMock()
    client.save_clip.side_effect = lambda _serial, output, **_kwargs: output.write(
        b"mpegps"
    )
    with patch(
        "custom_components.ezviz_plus.sdcard.remux_mpegps_to_mp4",
        return_value=b"mp4",
    ) as remux:
        assert capture_sd_playback(client, _recording(), None, "ffmpeg") == b"mp4"

    remux.assert_called_once_with(b"mpegps", "ffmpeg")


def test_remux_mpegps_to_mp4_uses_fragmented_stream_copy() -> None:
    """Produce pipe-safe MP4 without transcoding."""
    completed = MagicMock(returncode=0, stdout=b"mp4", stderr=b"")
    with patch("custom_components.ezviz_plus.sdcard.subprocess.run", return_value=completed) as run:
        assert remux_mpegps_to_mp4(b"mpegps", "ffmpeg") == b"mp4"

    command = run.call_args.args[0]
    assert command[command.index("-c") + 1] == "copy"
    assert command[command.index("-bsf:a") + 1] == "aac_adtstoasc"
    assert "+frag_keyframe+empty_moov+default_base_moof" in command
    assert command[-2:] == ["mp4", "pipe:1"]