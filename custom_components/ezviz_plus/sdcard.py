"""Download and remux EZVIZ SD-card playback clips."""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
import subprocess
from typing import Any

from pyezvizapi.exceptions import PyEzvizError

from .recordings import (
    EzvizRecording,
    format_cloud_playback_time,
    parse_record_datetime,
    record_duration_seconds,
)

BENIGN_VTM_EOF = "VTM socket closed while reading packet"
MAX_SD_PLAYBACK_SECONDS = 300


def capture_sd_playback(
    client: Any,
    recording: EzvizRecording,
    media_key: str | None,
    ffmpeg_path: str,
    *,
    output_format: str = "mp4",
) -> bytes:
    """Download one MPEG-PS SD segment and remux it for Home Assistant."""
    duration = record_duration_seconds(recording)
    if duration <= 0 or duration > MAX_SD_PLAYBACK_SECONDS:
        raise PyEzvizError(
            f"Invalid SD playback duration: {duration:.1f}s; maximum is "
            f"{MAX_SD_PLAYBACK_SECONDS}s"
        )

    begin_time = parse_record_datetime(recording.begin_time)
    end_time = parse_record_datetime(recording.end_time)
    if begin_time is None or end_time is None:
        raise PyEzvizError("Invalid SD playback timestamps")

    decrypt_video = bool(media_key)
    output = BytesIO()
    save_clip: Callable[..., object] = client.save_clip
    try:
        save_clip(
            recording.serial,
            output,
            source="cloud-playback",
            output_format="mpegps",
            duration_seconds=None,
            channel=recording.channel,
            decrypt_video=decrypt_video,
            media_key=media_key,
            nalu_header_size=None,
            cloud_client_type=9,
            cloud_token_index=0,
            cloud_refresh_vtm=True,
            cloud_playback_begin_time=format_cloud_playback_time(begin_time),
            cloud_playback_end_time=format_cloud_playback_time(end_time),
            cloud_playback_lid=recording.lid,
        )
    except PyEzvizError as err:
        if decrypt_video or BENIGN_VTM_EOF not in str(err) or output.tell() == 0:
            raise

    mpegps = output.getvalue()
    if output_format == "mpegts":
        return remux_mpegps_to_mpegts(mpegps, ffmpeg_path)
    if output_format == "mp4":
        return remux_mpegps_to_mp4(mpegps, ffmpeg_path)
    raise PyEzvizError(f"Unsupported SD playback output format: {output_format}")


def capture_sd_playback_mpegts(
    client: Any,
    recording: EzvizRecording,
    media_key: str | None,
    ffmpeg_path: str,
) -> bytes:
    """Download one SD segment and return MPEG-TS bytes."""
    return capture_sd_playback(
        client,
        recording,
        media_key,
        ffmpeg_path,
        output_format="mpegts",
    )


def remux_mpegps_to_mp4(mpegps: bytes, ffmpeg_path: str) -> bytes:
    """Validate and remux MPEG-PS bytes into fragmented MP4."""
    if not mpegps:
        raise PyEzvizError("SD playback returned an empty MPEG-PS payload")

    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "mpeg",
        "-i",
        "pipe:0",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c",
        "copy",
        "-bsf:a",
        "aac_adtstoasc",
        "-movflags",
        "+frag_keyframe+empty_moov+default_base_moof",
        "-f",
        "mp4",
        "pipe:1",
    ]
    return _run_ffmpeg_remux(command, mpegps, "MP4")


def remux_mpegps_to_mpegts(mpegps: bytes, ffmpeg_path: str) -> bytes:
    """Validate and remux MPEG-PS bytes into MPEG-TS without transcoding."""
    if not mpegps:
        raise PyEzvizError("SD playback returned an empty MPEG-PS payload")

    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "mpeg",
        "-i",
        "pipe:0",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c",
        "copy",
        "-f",
        "mpegts",
        "pipe:1",
    ]
    return _run_ffmpeg_remux(command, mpegps, "MPEG-TS")


def _run_ffmpeg_remux(command: list[str], payload: bytes, output_name: str) -> bytes:
    """Run an FFmpeg remux command and return validated output bytes."""
    result = subprocess.run(
        command,
        input=payload,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        message = result.stderr.decode(errors="ignore").strip() or (
            f"FFmpeg exited with status {result.returncode}"
        )
        raise PyEzvizError(f"Invalid SD playback MPEG-PS for {output_name}: {message}")
    return result.stdout