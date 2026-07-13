"""Helpers for EZVIZ SD-card recording search and playback identifiers."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from typing import Any

from pyezvizapi.exceptions import PyEzvizError

EZVIZ_RECORD_SEARCH_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
EZVIZ_RECORD_DISPLAY_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
EZVIZ_CLOUD_PLAYBACK_TIME_FORMAT = "%Y%m%dT%H%M%SZ"
MIN_USEFUL_OVERLAP_SECONDS = 10.0

BEGIN_TIME_KEYS = (
    "B",
    "begin",
    "beginTime",
    "begin_time",
    "startTime",
    "startTimeStr",
    "start_time",
    "start",
)
END_TIME_KEYS = (
    "E",
    "end",
    "endTime",
    "end_time",
    "stopTime",
    "stopTimeStr",
    "stop_time",
)


@dataclass(slots=True, frozen=True)
class EzvizRecording:
    """Normalized SD-card recording segment."""

    serial: str
    channel: int
    begin_time: str
    end_time: str
    lid: str | None = None
    record_type: str | None = None

    @property
    def title(self) -> str:
        """Return a compact display title for the recording."""
        begin_dt = parse_record_datetime(self.begin_time)
        end_dt = parse_record_datetime(self.end_time)
        if begin_dt and end_dt and begin_dt.date() == end_dt.date():
            return f"{begin_dt:%H:%M:%S} - {end_dt:%H:%M:%S}"
        return f"{self.begin_time} - {self.end_time}"


def format_ezviz_record_time(value: datetime) -> str:
    """Format a datetime for EZVIZ recording search endpoints."""
    return value.strftime(EZVIZ_RECORD_SEARCH_TIME_FORMAT)


def format_cloud_playback_time(value: datetime) -> str:
    """Format a datetime for EZVIZ VTM cloud-playback."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.strftime(EZVIZ_CLOUD_PLAYBACK_TIME_FORMAT)


def parse_record_datetime(value: Any) -> datetime | None:
    """Parse a timestamp used by EZVIZ recording APIs."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y%m%dT%H%M%SZ",
        "%Y%m%d%H%M%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def record_time_value(record: dict[str, Any] | EzvizRecording, *names: str) -> datetime | None:
    """Return the first parseable record timestamp for the requested keys."""
    for name in names:
        value = _record_get(record, name)
        if (parsed := parse_record_datetime(value)) is not None:
            return parsed
    return None


def record_interval(
    record: dict[str, Any] | EzvizRecording,
) -> tuple[datetime, datetime] | None:
    """Return the begin/end interval for a recording."""
    record_start = record_time_value(record, *BEGIN_TIME_KEYS)
    record_stop = record_time_value(record, *END_TIME_KEYS)
    if record_start is None or record_stop is None or record_stop <= record_start:
        return None
    return record_start, record_stop


def record_duration_seconds(record: dict[str, Any] | EzvizRecording) -> float:
    """Return a recording duration in seconds."""
    interval = record_interval(record)
    if interval is None:
        return 0.0
    return (interval[1] - interval[0]).total_seconds()


def record_contains_time(
    record: dict[str, Any] | EzvizRecording, event_time: datetime
) -> bool:
    """Return true if a recording includes the event timestamp."""
    interval = record_interval(record)
    return interval is not None and interval[0] <= event_time <= interval[1]


def record_overlaps_window(
    record: dict[str, Any] | EzvizRecording, start_time: datetime, stop_time: datetime
) -> bool:
    """Return true if a recording overlaps the requested window."""
    interval = record_interval(record)
    return interval is not None and interval[0] <= stop_time and interval[1] >= start_time


def record_distance_seconds(
    record: dict[str, Any] | EzvizRecording, event_time: datetime
) -> float:
    """Return distance between a recording interval and an event timestamp."""
    interval = record_interval(record)
    if interval is None:
        return 0.0
    record_start, record_stop = interval
    if record_start <= event_time <= record_stop:
        return 0.0
    if event_time < record_start:
        return (record_start - event_time).total_seconds()
    return (event_time - record_stop).total_seconds()


def select_sdcard_record_for_event(
    records: list[EzvizRecording],
    event_time: datetime,
    requested_start: datetime,
    requested_stop: datetime,
) -> tuple[EzvizRecording | None, str]:
    """Select the most useful recording segment for an event."""
    overlapping = [
        record for record in records if record_overlaps_window(record, requested_start, requested_stop)
    ]
    containing = [record for record in overlapping if record_contains_time(record, event_time)]
    if containing:
        return max(containing, key=record_duration_seconds), "contains-event"
    useful_overlapping = [
        record
        for record in overlapping
        if record_duration_seconds(record) >= MIN_USEFUL_OVERLAP_SECONDS
    ]
    if useful_overlapping:
        return min(
            useful_overlapping,
            key=lambda record: record_distance_seconds(record, event_time),
        ), "overlap"
    if records:
        return min(records, key=lambda record: record_distance_seconds(record, event_time)), "nearest"
    return None, "none"


def merged_sdcard_playback_window(
    records: list[EzvizRecording],
    selected_record: EzvizRecording,
    requested_start: datetime,
    requested_stop: datetime,
    *,
    max_gap_seconds: float,
) -> tuple[datetime, datetime, int] | None:
    """Merge contiguous SD-card segments around the selected recording."""
    selected_interval = record_interval(selected_record)
    if selected_interval is None:
        return None

    max_gap = timedelta(seconds=max(0.0, max_gap_seconds))
    cluster_start, cluster_stop = selected_interval
    intervals = sorted(
        interval
        for record in records
        if (interval := record_interval(record)) is not None
        and interval[1] >= requested_start
        and interval[0] <= requested_stop
    )
    changed = True
    while changed:
        changed = False
        for record_start, record_stop in intervals:
            if record_start <= cluster_stop + max_gap and record_stop >= cluster_start - max_gap:
                new_start = min(cluster_start, record_start)
                new_stop = max(cluster_stop, record_stop)
                if new_start != cluster_start or new_stop != cluster_stop:
                    cluster_start, cluster_stop = new_start, new_stop
                    changed = True

    merged_count = sum(
        1
        for record_start, record_stop in intervals
        if record_start >= cluster_start and record_stop <= cluster_stop
    )
    return cluster_start, cluster_stop, merged_count


def search_sdcard_records(
    client: Any,
    serial: str,
    channel: int,
    start_time: datetime,
    stop_time: datetime,
    *,
    size: int = 20,
    source: str = "v2",
) -> list[EzvizRecording]:
    """Search SD-card recordings through the selected pyEzvizApi endpoint."""
    start_text = format_ezviz_record_time(start_time)
    stop_text = format_ezviz_record_time(stop_time)
    try:
        if source == "legacy":
            response = client.search_records(
                serial, channel, serial, start_text, stop_text, size=size
            )
        elif source == "common":
            response = client.search_common_records(
                serial, channel, start_text, stop_text, size=size
            )
        else:
            response = client.search_records_v2(
                serial, channel, start_text, stop_text, size=size
            )
    except PyEzvizError as err:
        message = str(err)
        if (
            "'records': None" in message
            and "'code': 2004" in message
            and "'DEVICE_EXCEPTION': '70'" in message
        ):
            return []
        raise
    records = client.extract_record_list(response) or []
    return normalize_recordings(records, serial=serial, default_channel=channel)


def encode_recording_identifier(recording: EzvizRecording) -> str:
    """Encode a recording into a URL-safe media-source identifier payload."""
    payload = {
        "serial": recording.serial,
        "channel": recording.channel,
        "begin_time": recording.begin_time,
        "end_time": recording.end_time,
        "lid": recording.lid,
        "record_type": recording.record_type,
    }
    encoded = urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
    return encoded.decode()


def decode_recording_identifier(value: str) -> EzvizRecording:
    """Decode a URL-safe media-source identifier payload into a recording."""
    payload = json.loads(urlsafe_b64decode(value.encode()).decode())
    return EzvizRecording(
        serial=str(payload["serial"]),
        channel=int(payload.get("channel") or 1),
        begin_time=str(payload["begin_time"]),
        end_time=str(payload["end_time"]),
        lid=str(payload["lid"]) if payload.get("lid") is not None else None,
        record_type=(
            str(payload["record_type"]) if payload.get("record_type") is not None else None
        ),
    )


def normalize_recordings(
    records: list[Any], *, serial: str, default_channel: int = 1
) -> list[EzvizRecording]:
    """Normalize mixed EZVIZ record payloads into playable recording segments."""
    normalized: list[EzvizRecording] = []
    for record in records:
        if not isinstance(record, dict):
            continue

        begin_time = _first_string(record, *BEGIN_TIME_KEYS)
        end_time = _first_string(record, *END_TIME_KEYS)
        if not begin_time or not end_time:
            continue

        recording = EzvizRecording(
            serial=str(record.get("deviceSerial") or record.get("serial") or serial),
            channel=_coerce_int(record.get("channel"), default_channel),
            begin_time=begin_time,
            end_time=end_time,
            lid=_first_string(record, "lid", "id", "fileId", "file_id"),
            record_type=_first_string(record, "recordType", "record_type", "type"),
        )
        if record_interval(recording) is not None:
            normalized.append(recording)

    return sorted(normalized, key=lambda item: item.begin_time, reverse=True)


def _first_string(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value):
            return str(value)
    return None


def _record_get(record: dict[str, Any] | EzvizRecording, key: str) -> Any:
    if isinstance(record, EzvizRecording):
        if key in BEGIN_TIME_KEYS:
            return record.begin_time
        if key in END_TIME_KEYS:
            return record.end_time
        return getattr(record, key, None)
    return record.get(key)


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default