"""Cloud video helpers for EZVIZ VTM streams."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from io import BytesIO
import queue
import subprocess
import threading
import time
from typing import Any, BinaryIO

from pyezvizapi.cloud_stream import (
    copy_cloud_stream_to_mpegts as api_copy_cloud_stream_to_mpegts,
    open_cloud_stream,
)
from pyezvizapi.exceptions import PyEzvizError
from pyezvizapi.stream import (
    StreamTransport,
    decrypt_hikvision_ps_video,
    detect_transport,
    rtp_payload,
)

_CLOUD_STREAM_READ_SIZE = 64 * 1024
_CLOUD_STREAM_BOOTSTRAP_PACKETS = 24
_CLOUD_STREAM_BOOTSTRAP_SECONDS = 8.0
_CLOUD_STREAM_READ_TIMEOUT = 20.0
_RTP_VIDEO_CLOCK_RATE = 90_000
_RTP_MAX_PACE_DELAY = 2.0


class CloudMpegtsStream:
    """Continuously pipe an EZVIZ cloud RTP stream through FFmpeg as MPEG-TS."""

    def __init__(  # noqa: PLR0913
        self,
        client: Any,
        serial: str,
        *,
        media_key: str | bytes | None = None,
        ffmpeg_path: str = "ffmpeg",
        channel: int = 1,
        client_type: int = 9,
        timeout: float | None = 10.0,
        output_codec: str = "h264",
        monotonic: Callable[[], float] = time.monotonic,
        popen: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        """Initialize the cloud stream pipe."""

        self._client = client
        self._serial = serial
        self._media_key = media_key
        self._ffmpeg_path = ffmpeg_path
        self._channel = channel
        self._client_type = client_type
        self._timeout = timeout
        self._output_codec = output_codec
        self._monotonic = monotonic
        self._popen = popen
        self._queue: queue.Queue[bytes | Exception | None] = queue.Queue(maxsize=32)
        self._stop = threading.Event()
        self._started = False
        self._process: Any | None = None
        self._threads: list[threading.Thread] = []

    def read(self) -> bytes:
        """Return the next MPEG-TS chunk, or empty bytes when the stream ends."""

        self.start()
        try:
            item = self._queue.get(timeout=_CLOUD_STREAM_READ_TIMEOUT)
        except queue.Empty as err:
            self.close()
            raise PyEzvizError("Timed out waiting for cloud stream data") from err
        if item is None:
            return b""
        if isinstance(item, Exception):
            self.close()
            if isinstance(item, PyEzvizError):
                raise item
            raise PyEzvizError(str(item)) from item
        return item

    def start(self) -> None:
        """Start the cloud stream worker once."""

        if self._started:
            return
        self._started = True
        feeder = threading.Thread(
            target=self._feed_ffmpeg,
            name=f"ezviz-plus-cloud-feed-{self._serial}",
            daemon=True,
        )
        feeder.start()
        self._threads.append(feeder)

    def close(self) -> None:
        """Stop the stream and release FFmpeg."""

        self._stop.set()
        process = self._process
        if process is not None:
            with suppress(Exception):
                if process.stdin:
                    process.stdin.close()
            with suppress(Exception):
                process.terminate()
            with suppress(Exception):
                process.wait(timeout=2)
            with suppress(Exception):
                process.kill()
        self._put_queue(None)

    def _feed_ffmpeg(self) -> None:
        """Read cloud packets, depacketize video, and write FFmpeg stdin."""

        try:
            self._feed_ffmpeg_inner()
        except Exception as err:
            self._put_queue(err)
        finally:
            process = self._process
            if process is not None:
                with suppress(Exception):
                    if process.stdin:
                        process.stdin.close()

    def _feed_ffmpeg_inner(self) -> None:
        buffered_packets: list[Any] = []
        video_payload_type: int | None = None
        depacketizer: _RtpAnnexBDepacketizer | None = None
        pacer: _RtpTimestampPacer | None = None
        bootstrap_started = self._monotonic()

        with open_cloud_stream(
            self._client,
            self._serial,
            channel=self._channel,
            client_type=self._client_type,
            timeout=self._timeout,
        ) as stream:
            stream.start()
            for packet in stream.iter_packets(max_packets=None):
                if self._stop.is_set():
                    break
                if packet.encrypted:
                    raise PyEzvizError("Encrypted VTM stream packets are not supported")
                if detect_transport(packet.body) != StreamTransport.RTP:
                    raise PyEzvizError("Continuous cloud streaming only supports RTP VTM")

                if video_payload_type is None:
                    buffered_packets.append(packet)
                    elapsed = self._monotonic() - bootstrap_started
                    video_track = _try_select_rtp_video_packets(buffered_packets)
                    if video_track is None and elapsed < _CLOUD_STREAM_BOOTSTRAP_SECONDS:
                        continue
                    if video_track is None:
                        raise PyEzvizError("Could not find an RTP video track")
                    codec, video_packets = video_track
                    video_payload_type = _rtp_packet_payload_type(video_packets[0])
                    depacketizer = _RtpAnnexBDepacketizer(codec)
                    pacer = _RtpTimestampPacer(self._monotonic, self._stop)
                    self._start_ffmpeg(codec)
                    self._write_packets(video_packets, depacketizer, pacer)
                    buffered_packets.clear()
                    continue

                if _rtp_packet_payload_type(packet) == video_payload_type:
                    if depacketizer is None or pacer is None:
                        raise PyEzvizError("Cloud stream depacketizer was not initialized")
                    self._write_packets([packet], depacketizer, pacer)

        self.close()

    def _start_ffmpeg(self, codec: str) -> None:
        output_args = _ffmpeg_output_codec_args(self._output_codec)
        try:
            process = self._popen(
                [
                    self._ffmpeg_path,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-fflags",
                    "+genpts",
                    "-use_wallclock_as_timestamps",
                    "1",
                    "-f",
                    codec,
                    "-i",
                    "pipe:0",
                    *output_args,
                    "-f",
                    "mpegts",
                    "-flush_packets",
                    "1",
                    "pipe:1",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as err:
            raise PyEzvizError(f"Could not launch FFmpeg at {self._ffmpeg_path!r}: {err}") from err
        self._process = process
        reader = threading.Thread(
            target=self._read_ffmpeg_stdout,
            name=f"ezviz-plus-cloud-read-{self._serial}",
            daemon=True,
        )
        reader.start()
        self._threads.append(reader)

    def _read_ffmpeg_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            self._put_queue(PyEzvizError("FFmpeg stdout is not available"))
            return
        try:
            while not self._stop.is_set():
                chunk = process.stdout.read(_CLOUD_STREAM_READ_SIZE)
                if not chunk:
                    break
                self._put_queue(chunk)
        except Exception as err:
            self._put_queue(err)
        finally:
            self._put_queue(None)

    def _write_packets(
        self,
        packets: list[Any],
        depacketizer: _RtpAnnexBDepacketizer,
        pacer: _RtpTimestampPacer,
    ) -> None:
        for packet in packets:
            pacer.wait(packet)
            payload = depacketizer.push_packet(packet)
            if not payload:
                continue
            if self._media_key:
                payload = _decrypt_annexb_video(
                    payload,
                    self._media_key,
                    codec=depacketizer.codec,
                )
            self._write_ffmpeg(payload)

    def _write_ffmpeg(self, data: bytes) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise PyEzvizError("FFmpeg stdin is not available")
        try:
            process.stdin.write(data)
            process.stdin.flush()
        except (BrokenPipeError, OSError) as err:
            raise PyEzvizError("FFmpeg stopped while writing cloud stream") from err

    def _put_queue(self, item: bytes | Exception | None) -> None:
        with suppress(queue.Full):
            self._queue.put(item, timeout=1)


def copy_cloud_stream_to_mpegts(  # noqa: PLR0913
    client: Any,
    serial: str,
    output: BinaryIO,
    *,
    media_key: str | bytes | None = None,
    ffmpeg_path: str = "ffmpeg",
    duration_seconds: float = 8.0,
    channel: int = 1,
    client_type: int = 9,
    timeout: float | None = 10.0,
    output_codec: str = "copy",
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Copy a short EZVIZ cloud RTP stream to MPEG-TS bytes."""

    packets: list[Any] = []
    with open_cloud_stream(
        client,
        serial,
        channel=channel,
        client_type=client_type,
        timeout=timeout,
    ) as stream:
        stream.start()
        deadline = monotonic() + duration_seconds
        for packet in stream.iter_packets(max_packets=None):
            if monotonic() >= deadline:
                break
            if packet.encrypted:
                raise PyEzvizError("Encrypted VTM stream packets are not supported")
            packets.append(packet)

    transport = _detect_packet_transport(packets)
    if transport != StreamTransport.RTP:
        api_copy_cloud_stream_to_mpegts(
            client,
            serial,
            output,
            media_key=media_key,
            ffmpeg_path=ffmpeg_path,
            duration_seconds=duration_seconds,
            channel=channel,
            client_type=client_type,
            timeout=timeout,
            decrypt_video=bool(media_key),
            nalu_header_size=None,
        )
        return

    codec, video_packets = _select_rtp_video_packets(packets)
    payload = _rtp_packets_to_annexb(video_packets, codec=codec)
    if media_key:
        payload = _decrypt_annexb_video(payload, media_key, codec=codec)
    _remux_elementary_video_bytes_to_mpegts(
        payload,
        output,
        ffmpeg_path=ffmpeg_path,
        codec=codec,
        output_codec=output_codec,
    )


def capture_cloud_stream_to_mpegts(  # noqa: PLR0913
    client: Any,
    serial: str,
    *,
    media_key: str | bytes | None = None,
    ffmpeg_path: str = "ffmpeg",
    duration_seconds: float = 8.0,
    channel: int = 1,
    client_type: int = 9,
    timeout: float | None = 10.0,
    output_codec: str = "copy",
    monotonic: Callable[[], float] = time.monotonic,
) -> bytes:
    """Return a bounded cloud stream capture as MPEG-TS bytes."""

    output = BytesIO()
    copy_cloud_stream_to_mpegts(
        client,
        serial,
        output,
        media_key=media_key,
        ffmpeg_path=ffmpeg_path,
        duration_seconds=duration_seconds,
        channel=channel,
        client_type=client_type,
        timeout=timeout,
        output_codec=output_codec,
        monotonic=monotonic,
    )
    return output.getvalue()


def _detect_packet_transport(packets: list[Any]) -> StreamTransport:
    """Return the first recognized stream transport."""

    for packet in packets:
        transport = detect_transport(packet.body)
        if transport != StreamTransport.UNKNOWN:
            return transport
    return StreamTransport.UNKNOWN


def _rtp_payload_codec(payload: bytes) -> str | None:
    """Return the likely video codec for an RTP payload."""

    if len(payload) < 2:
        return None
    hevc_type = (payload[0] >> 1) & 0x3F
    if hevc_type in {32, 33, 34, 48, 49}:
        return "hevc"
    h264_type = payload[0] & 0x1F
    if h264_type in {1, 5, 7, 8, 24, 28}:
        return "h264"
    return None


def _select_rtp_video_packets(packets: list[Any]) -> tuple[str, list[Any]]:
    """Select a single RTP video payload type and ignore non-video tracks."""

    video_track = _try_select_rtp_video_packets(packets)
    if video_track is None:
        raise PyEzvizError("Could not find an RTP video track")
    return video_track


def _try_select_rtp_video_packets(packets: list[Any]) -> tuple[str, list[Any]] | None:
    """Return a likely RTP video track, if the packet sample contains one."""

    tracks: dict[int, list[Any]] = {}
    for packet in packets:
        if len(packet.body) < 2:
            continue
        payload_type = _rtp_packet_payload_type(packet)
        tracks.setdefault(payload_type, []).append(packet)

    candidates: list[tuple[int, int, str, list[Any]]] = []
    for track_packets in tracks.values():
        codec_scores = {"h264": 0, "hevc": 0}
        payload_bytes = 0
        for packet in track_packets:
            try:
                payload = rtp_payload(packet.body)
            except PyEzvizError:
                continue
            payload_bytes += len(payload)
            codec = _rtp_payload_codec(payload)
            if codec:
                codec_scores[codec] += 1
        codec = "hevc" if codec_scores["hevc"] >= codec_scores["h264"] else "h264"
        score = codec_scores[codec]
        if score:
            candidates.append((score, payload_bytes, codec, track_packets))

    if not candidates:
        return None

    _score, _payload_bytes, codec, video_packets = max(
        candidates,
        key=lambda candidate: (candidate[0], candidate[1]),
    )
    return codec, video_packets


def _rtp_packet_payload_type(packet: Any) -> int:
    """Return an RTP packet payload type."""

    return packet.body[1] & 0x7F


def _rtp_packet_timestamp(packet: Any) -> int:
    """Return an RTP packet timestamp."""

    return int.from_bytes(packet.body[4:8], "big")


class _RtpTimestampPacer:
    """Pace packet delivery according to RTP video timestamps."""

    def __init__(
        self,
        monotonic: Callable[[], float],
        stop_event: threading.Event,
    ) -> None:
        self._monotonic = monotonic
        self._stop_event = stop_event
        self._base_rtp_timestamp: int | None = None
        self._base_wall_time: float | None = None

    def wait(self, packet: Any) -> None:
        """Wait until this RTP packet is due according to the camera clock."""

        if len(packet.body) < 8:
            return
        rtp_timestamp = _rtp_packet_timestamp(packet)
        now = self._monotonic()
        if self._base_rtp_timestamp is None or self._base_wall_time is None:
            self._base_rtp_timestamp = rtp_timestamp
            self._base_wall_time = now
            return

        timestamp_delta = (rtp_timestamp - self._base_rtp_timestamp) & 0xFFFFFFFF
        due_time = self._base_wall_time + (timestamp_delta / _RTP_VIDEO_CLOCK_RATE)
        delay = due_time - now
        if delay < 0:
            return
        if delay > _RTP_MAX_PACE_DELAY:
            self._base_rtp_timestamp = rtp_timestamp
            self._base_wall_time = now
            return
        self._stop_event.wait(delay)


class _RtpAnnexBDepacketizer:
    """Incrementally convert RTP video packets to Annex-B bytes."""

    def __init__(self, codec: str) -> None:
        self.codec = codec
        self._fragmented_nal = bytearray()
        self._in_fragment = False

    def push_packet(self, packet: Any) -> bytes:
        """Return Annex-B bytes completed by one RTP packet."""

        payload = rtp_payload(packet.body)
        if self.codec == "hevc":
            return self._push_hevc(payload)
        if self.codec == "h264":
            return self._push_h264(payload)
        raise PyEzvizError(f"Unsupported RTP video codec: {self.codec}")

    def _push_hevc(self, payload: bytes) -> bytes:
        output = bytearray()
        if len(payload) < 2:
            return b""
        nal_type = (payload[0] >> 1) & 0x3F
        if nal_type == 48:
            _append_hevc_aggregation_packet(output, payload)
            self._reset_fragment()
        elif nal_type == 49 and len(payload) >= 3:
            self._fragmented_nal, self._in_fragment = _append_hevc_fragment(
                output,
                payload,
                self._fragmented_nal,
                self._in_fragment,
            )
        else:
            _append_nal(output, payload)
            self._reset_fragment()
        return bytes(output)

    def _push_h264(self, payload: bytes) -> bytes:
        output = bytearray()
        nal_type = payload[0] & 0x1F if payload else 0
        if 1 <= nal_type <= 23:
            _append_nal(output, payload)
            self._reset_fragment()
        elif nal_type == 24:
            _append_h264_stap_a(output, payload)
            self._reset_fragment()
        elif nal_type == 28 and len(payload) >= 2:
            self._fragmented_nal, self._in_fragment = _append_h264_fragment(
                output,
                payload,
                self._fragmented_nal,
                self._in_fragment,
            )
        return bytes(output)

    def _reset_fragment(self) -> None:
        self._fragmented_nal.clear()
        self._in_fragment = False


def _rtp_packets_to_annexb(packets: list[Any], *, codec: str) -> bytes:
    """Convert one RTP H.264/HEVC video track to Annex-B bytes."""

    if codec == "hevc":
        return _hevc_rtp_packets_to_annexb(packets)
    if codec == "h264":
        return _h264_rtp_packets_to_annexb(packets)
    raise PyEzvizError(f"Unsupported RTP video codec: {codec}")


def _append_nal(output: bytearray, nal: bytes) -> None:
    """Append a NAL unit with an Annex-B start code."""

    if nal:
        output.extend(b"\x00\x00\x00\x01")
        output.extend(nal)


def _hevc_rtp_packets_to_annexb(packets: list[Any]) -> bytes:
    """Convert HEVC RTP payloads to Annex-B bytes."""

    output = bytearray()
    fragmented_nal = bytearray()
    in_fragment = False
    for packet in packets:
        payload = rtp_payload(packet.body)
        if len(payload) < 2:
            continue
        nal_type = (payload[0] >> 1) & 0x3F
        if nal_type == 48:
            _append_hevc_aggregation_packet(output, payload)
            fragmented_nal.clear()
            in_fragment = False
        elif nal_type == 49 and len(payload) >= 3:
            fragmented_nal, in_fragment = _append_hevc_fragment(
                output,
                payload,
                fragmented_nal,
                in_fragment,
            )
        else:
            _append_nal(output, payload)
            fragmented_nal.clear()
            in_fragment = False
    return bytes(output)


def _append_hevc_aggregation_packet(output: bytearray, payload: bytes) -> None:
    """Append HEVC aggregation-packet NAL units."""

    offset = 2
    while offset + 2 <= len(payload):
        nal_size = int.from_bytes(payload[offset : offset + 2], "big")
        offset += 2
        if nal_size <= 0 or offset + nal_size > len(payload):
            break
        _append_nal(output, payload[offset : offset + nal_size])
        offset += nal_size


def _append_hevc_fragment(
    output: bytearray,
    payload: bytes,
    fragmented_nal: bytearray,
    in_fragment: bool,
) -> tuple[bytearray, bool]:
    """Append an HEVC FU fragment when complete."""

    fu_header = payload[2]
    starts_fragment = bool(fu_header & 0x80)
    ends_fragment = bool(fu_header & 0x40)
    original_type = fu_header & 0x3F
    if starts_fragment:
        fragmented_nal = bytearray(
            ((payload[0] & 0x81) | (original_type << 1), payload[1])
        )
        fragmented_nal.extend(payload[3:])
        in_fragment = True
    elif in_fragment:
        fragmented_nal.extend(payload[3:])
    if in_fragment and ends_fragment:
        _append_nal(output, bytes(fragmented_nal))
        fragmented_nal.clear()
        in_fragment = False
    return fragmented_nal, in_fragment


def _h264_rtp_packets_to_annexb(packets: list[Any]) -> bytes:
    """Convert H.264 RTP payloads to Annex-B bytes."""

    output = bytearray()
    fragmented_nal = bytearray()
    in_fragment = False
    for packet in packets:
        payload = rtp_payload(packet.body)
        nal_type = payload[0] & 0x1F if payload else 0
        if 1 <= nal_type <= 23:
            _append_nal(output, payload)
            fragmented_nal.clear()
            in_fragment = False
        elif nal_type == 24:
            _append_h264_stap_a(output, payload)
            fragmented_nal.clear()
            in_fragment = False
        elif nal_type == 28 and len(payload) >= 2:
            fragmented_nal, in_fragment = _append_h264_fragment(
                output,
                payload,
                fragmented_nal,
                in_fragment,
            )
    return bytes(output)


def _append_h264_stap_a(output: bytearray, payload: bytes) -> None:
    """Append H.264 STAP-A NAL units."""

    offset = 1
    while offset + 2 <= len(payload):
        nal_size = int.from_bytes(payload[offset : offset + 2], "big")
        offset += 2
        if nal_size <= 0 or offset + nal_size > len(payload):
            break
        _append_nal(output, payload[offset : offset + nal_size])
        offset += nal_size


def _append_h264_fragment(
    output: bytearray,
    payload: bytes,
    fragmented_nal: bytearray,
    in_fragment: bool,
) -> tuple[bytearray, bool]:
    """Append an H.264 FU-A fragment when complete."""

    fu_header = payload[1]
    starts_fragment = bool(fu_header & 0x80)
    ends_fragment = bool(fu_header & 0x40)
    if starts_fragment:
        fragmented_nal = bytearray(((payload[0] & 0xE0) | (fu_header & 0x1F),))
        fragmented_nal.extend(payload[2:])
        in_fragment = True
    elif in_fragment:
        fragmented_nal.extend(payload[2:])
    if in_fragment and ends_fragment:
        _append_nal(output, bytes(fragmented_nal))
        fragmented_nal.clear()
        in_fragment = False
    return fragmented_nal, in_fragment


def _decrypt_annexb_video(data: bytes, key: str | bytes, *, codec: str) -> bytes:
    """Decrypt Annex-B video bytes using the Hikvision NAL transform."""

    header_size = 2 if codec == "hevc" else 1
    video_pes = b"\x00\x00\x01\xe0\x00\x00\x80\x00\x00" + data
    return decrypt_hikvision_ps_video(
        video_pes,
        key,
        nalu_header_size=header_size,
    )[9:]


def _remux_elementary_video_bytes_to_mpegts(
    data: bytes,
    output: BinaryIO,
    *,
    ffmpeg_path: str,
    codec: str,
    output_codec: str = "copy",
    popen: Callable[..., Any] = subprocess.Popen,
) -> None:
    """Remux H.264/HEVC Annex-B bytes to MPEG-TS."""

    output_args = _ffmpeg_output_codec_args(output_codec)

    try:
        process = popen(
            [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                codec,
                "-i",
                "pipe:0",
                *output_args,
                "-f",
                "mpegts",
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError as err:
        raise PyEzvizError(f"Could not launch FFmpeg at {ffmpeg_path!r}: {err}") from err
    stdout, _stderr = process.communicate(data)
    if process.returncode != 0:
        raise PyEzvizError(f"FFmpeg exited with status {process.returncode}")
    output.write(stdout)
    output.flush()


def _ffmpeg_output_codec_args(output_codec: str) -> list[str]:
    """Return FFmpeg output codec arguments for MPEG-TS."""

    if output_codec == "copy":
        return ["-c", "copy"]
    if output_codec == "h264":
        return [
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
    raise PyEzvizError(f"Unsupported cloud stream output codec: {output_codec}")
