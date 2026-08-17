"""Tests for EZVIZ cloud video helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.ezviz_plus.cloud_video import (
    CloudMpegtsStream,
    _ffmpeg_output_codec_args,
    _remux_elementary_video_bytes_to_mpegts,
    _rtp_packets_to_annexb,
    _RtpAnnexBDepacketizer,
    _RtpTimestampPacer,
    _select_rtp_video_packets,
)


def test_cloud_stream_close_does_not_wait_for_ffmpeg() -> None:
    """Avoid blocking Home Assistant's event loop while closing FFmpeg."""
    process = SimpleNamespace(
        stdin=SimpleNamespace(close=lambda: None),
        terminate=lambda: None,
        wait=lambda **_kwargs: pytest.fail("close must not wait for FFmpeg"),
        kill=lambda: None,
    )
    stream = CloudMpegtsStream(SimpleNamespace(), "CAMERA123")
    stream._process = process

    stream.close()


def _rtp(
    payload_type: int,
    sequence: int,
    payload: bytes,
    timestamp: int | None = None,
) -> SimpleNamespace:
    body = (
        bytes((0x80, payload_type))
        + sequence.to_bytes(2, "big")
        + (timestamp or 0).to_bytes(4, "big")
        + b"\0" * 4
        + payload
    )
    return SimpleNamespace(body=body, encrypted=False)


def test_select_rtp_video_packets_ignores_non_video_tracks() -> None:
    """Depacketize the video RTP track without audio/control payloads."""

    packets = [
        _rtp(96, 1, b"\x40\x01vps"),
        _rtp(112, 2, b"audio"),
        _rtp(104, 3, b"metadata"),
        _rtp(96, 4, b"\x42\x01sps"),
    ]

    codec, video_packets = _select_rtp_video_packets(packets)
    assert codec == "hevc"
    assert video_packets == [packets[0], packets[3]]
    assert _rtp_packets_to_annexb(video_packets, codec=codec) == (
        b"\x00\x00\x00\x01\x40\x01vps\x00\x00\x00\x01\x42\x01sps"
    )


def test_incremental_depacketizer_matches_bounded_hevc_conversion() -> None:
    """Produce the same Annex-B bytes packet by packet for a live pipe."""

    packets = [
        _rtp(96, 1, b"\x40\x01vps"),
        _rtp(96, 2, b"\x42\x01sps"),
    ]
    depacketizer = _RtpAnnexBDepacketizer("hevc")

    assert b"".join(depacketizer.push_packet(packet) for packet in packets) == (
        _rtp_packets_to_annexb(packets, codec="hevc")
    )


def test_rtp_timestamp_pacer_uses_camera_clock() -> None:
    """Pace live packets from RTP timestamps instead of a fixed FPS."""

    class FakeStopEvent:
        delay = 0.0

        def wait(self, delay: float) -> bool:
            self.delay = delay
            return False

    now = 10.0
    stop_event = FakeStopEvent()
    pacer = _RtpTimestampPacer(lambda: now, stop_event)  # type: ignore[arg-type]

    pacer.wait(_rtp(96, 1, b"\x40\x01vps", timestamp=90_000))
    pacer.wait(_rtp(96, 2, b"\x42\x01sps", timestamp=93_000))

    assert stop_event.delay == pytest.approx(3_000 / 90_000)


def test_remux_elementary_video_uses_codec_input_format() -> None:
    """Pass HEVC Annex-B bytes to FFmpeg using the elementary codec format."""

    calls: dict[str, Any] = {}

    class FakeProcess:
        returncode = 0

        def communicate(self, data: bytes) -> tuple[bytes, bytes]:
            calls["data"] = data
            return b"mpegts", b""

    def fake_popen(args: list[str], **kwargs: Any) -> FakeProcess:
        calls["args"] = args
        calls["kwargs"] = kwargs
        return FakeProcess()

    output = SimpleNamespace(data=b"")

    def write(data: bytes) -> None:
        output.data += data

    output.write = write
    output.flush = lambda: None

    _remux_elementary_video_bytes_to_mpegts(
        b"annexb",
        output,  # type: ignore[arg-type]
        ffmpeg_path="/usr/bin/ffmpeg",
        codec="hevc",
        popen=fake_popen,
    )

    assert calls["args"][:8] == [
        "/usr/bin/ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "hevc",
        "-i",
        "pipe:0",
    ]
    assert calls["data"] == b"annexb"
    assert output.data == b"mpegts"


def test_h264_output_codec_transcodes_for_browser_playback() -> None:
    """Use libx264 when the HA dashboard needs browser-playable HLS."""

    assert _ffmpeg_output_codec_args("h264") == [
        "-an",
        "-vf",
        "scale='min(1280,iw)':-2",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-b:v",
        "1500k",
        "-maxrate",
        "1800k",
        "-bufsize",
        "3000k",
        "-g",
        "30",
        "-keyint_min",
        "30",
    ]
