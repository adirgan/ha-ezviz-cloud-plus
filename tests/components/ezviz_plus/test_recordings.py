"""Tests for SD-card recording helpers."""

from __future__ import annotations

from datetime import datetime

from pyezvizapi.exceptions import PyEzvizError
import pytest

from custom_components.ezviz_plus.recordings import (
    EzvizRecording,
    decode_recording_identifier,
    encode_recording_identifier,
    format_cloud_playback_time,
    format_ezviz_record_time,
    merged_sdcard_playback_window,
    normalize_recordings,
    search_sdcard_records,
    select_sdcard_record_for_event,
)


def test_format_ezviz_record_time_uses_v2_api_format() -> None:
    """Format record searches with the v2 endpoint's accepted shape."""
    assert format_ezviz_record_time(datetime(2026, 7, 13, 4, 5, 6)) == (
        "2026-07-13T04:05:06"
    )


def test_format_cloud_playback_time_uses_vtm_format() -> None:
    """Format selected playback windows for VTM cloud-playback."""
    assert format_cloud_playback_time(datetime(2026, 7, 9, 22, 24, 58)) == (
        "20260709T222458Z"
    )


def test_normalize_recordings_accepts_mixed_payload_keys() -> None:
    """Normalize representative record dictionaries and discard unusable rows."""
    records = normalize_recordings(
        [
            {
                "B": "2026-07-13T12:00:00",
                "E": "2026-07-13T12:00:12",
                "Type": 0,
            },
            {
                "beginTime": "2026-07-13 10:00:00",
                "endTime": "2026-07-13 10:01:00",
                "channel": "1",
                "lid": 123,
                "recordType": 0,
            },
            {
                "start_time": "2026-07-13 11:00:00",
                "stop_time": "2026-07-13 11:02:00",
                "channel": "bad",
                "id": "abc",
            },
            {"beginTime": "2026-07-13 12:00:00"},
            {
                "B": "2026-07-13T13:00:20",
                "E": "2026-07-13T13:00:10",
            },
        ],
        serial="SERIAL1",
    )

    assert records == [
        EzvizRecording(
            serial="SERIAL1",
            channel=1,
            begin_time="2026-07-13T12:00:00",
            end_time="2026-07-13T12:00:12",
        ),
        EzvizRecording(
            serial="SERIAL1",
            channel=1,
            begin_time="2026-07-13 11:00:00",
            end_time="2026-07-13 11:02:00",
            lid="abc",
        ),
        EzvizRecording(
            serial="SERIAL1",
            channel=1,
            begin_time="2026-07-13 10:00:00",
            end_time="2026-07-13 10:01:00",
            lid="123",
            record_type="0",
        ),
    ]


def test_recording_identifier_round_trips() -> None:
    """Keep playable recording metadata inside one URL-safe identifier."""
    recording = EzvizRecording(
        serial="SERIAL1",
        channel=2,
        begin_time="2026-07-13 10:00:00",
        end_time="2026-07-13 10:01:00",
        lid="lid-1",
        record_type="motion",
    )

    assert decode_recording_identifier(encode_recording_identifier(recording)) == recording
    assert recording.title == "10:00:00 - 10:01:00"


def test_search_sdcard_records_uses_v2_and_extract_record_list() -> None:
    """Search through v2 and normalize the extracted record list."""
    class Client:
        def search_records_v2(self, *args: object, **kwargs: object) -> dict[str, object]:
            self.search_args = args
            self.search_kwargs = kwargs
            return {"records": [{"B": "2026-07-13T10:00:00", "E": "2026-07-13T10:00:10"}]}

        def extract_record_list(self, response: object) -> list[dict[str, object]]:
            self.extract_response = response
            return response["records"]  # type: ignore[index]

    client = Client()

    records = search_sdcard_records(
        client,
        "SERIAL1",
        1,
        datetime(2026, 7, 13, 9, 59, 50),
        datetime(2026, 7, 13, 10, 0, 20),
        size=20,
    )

    assert client.search_args == (
        "SERIAL1",
        1,
        "2026-07-13T09:59:50",
        "2026-07-13T10:00:20",
    )
    assert client.search_kwargs == {"size": 20}
    assert records[0].begin_time == "2026-07-13T10:00:00"


def test_search_sdcard_records_accepts_empty_response() -> None:
    """Treat an empty extracted payload as no available recordings."""

    class Client:
        def search_records_v2(self, *args: object, **kwargs: object) -> dict[str, object]:
            return {"records": None}

        def extract_record_list(self, response: object) -> None:
            return None

    assert search_sdcard_records(
        Client(),
        "SERIAL1",
        1,
        datetime(2026, 7, 13, 0, 0, 0),
        datetime(2026, 7, 13, 1, 0, 0),
    ) == []


def test_search_sdcard_records_accepts_device_no_records_response() -> None:
    """Treat EZVIZ device exception 70 with no records as an empty window."""

    class Client:
        def search_records_v2(self, *args: object, **kwargs: object) -> None:
            raise PyEzvizError(
                "Could not search v2 records: Got {'records': None, "
                "'meta': {'code': 2004, 'message': 'device exception', "
                "'moreInfo': {'DEVICE_EXCEPTION': '70'}}})"
            )

    assert search_sdcard_records(
        Client(),
        "SERIAL1",
        1,
        datetime(2026, 7, 13, 0, 0, 0),
        datetime(2026, 7, 13, 1, 0, 0),
    ) == []


def test_search_sdcard_records_preserves_other_api_errors() -> None:
    """Do not hide API failures unrelated to an empty recording window."""

    class Client:
        def search_records_v2(self, *args: object, **kwargs: object) -> None:
            raise PyEzvizError("Authentication failed")

    with pytest.raises(PyEzvizError, match="Authentication failed"):
        search_sdcard_records(
            Client(),
            "SERIAL1",
            1,
            datetime(2026, 7, 13, 0, 0, 0),
            datetime(2026, 7, 13, 1, 0, 0),
        )


def test_select_sdcard_record_prioritizes_event_containment() -> None:
    """Prefer a segment containing the event timestamp."""
    records = normalize_recordings(
        [
            {"B": "2026-07-13T10:00:00", "E": "2026-07-13T10:00:08"},
            {"B": "2026-07-13T10:00:09", "E": "2026-07-13T10:00:40"},
        ],
        serial="SERIAL1",
    )

    selected, reason = select_sdcard_record_for_event(
        records,
        datetime(2026, 7, 13, 10, 0, 12),
        datetime(2026, 7, 13, 10, 0, 5),
        datetime(2026, 7, 13, 10, 0, 30),
    )

    assert reason == "contains-event"
    assert selected is not None
    assert selected.begin_time == "2026-07-13T10:00:09"


def test_select_sdcard_record_uses_overlap_then_nearest() -> None:
    """Use useful overlap first and nearest segment as fallback."""
    overlapping = normalize_recordings(
        [{"B": "2026-07-13T10:00:00", "E": "2026-07-13T10:00:12"}],
        serial="SERIAL1",
    )
    selected, reason = select_sdcard_record_for_event(
        overlapping,
        datetime(2026, 7, 13, 10, 0, 30),
        datetime(2026, 7, 13, 10, 0, 10),
        datetime(2026, 7, 13, 10, 0, 25),
    )
    assert reason == "overlap"
    assert selected == overlapping[0]

    nearest = normalize_recordings(
        [{"B": "2026-07-13T10:01:00", "E": "2026-07-13T10:01:15"}],
        serial="SERIAL1",
    )
    selected, reason = select_sdcard_record_for_event(
        nearest,
        datetime(2026, 7, 13, 10, 0, 30),
        datetime(2026, 7, 13, 10, 0, 20),
        datetime(2026, 7, 13, 10, 0, 40),
    )
    assert reason == "nearest"
    assert selected == nearest[0]


def test_merged_sdcard_playback_window_joins_contiguous_segments() -> None:
    """Merge neighboring segments when the gap is within the configured bound."""
    records = normalize_recordings(
        [
            {"B": "2026-07-13T10:00:00", "E": "2026-07-13T10:00:10"},
            {"B": "2026-07-13T10:00:13", "E": "2026-07-13T10:00:30"},
            {"B": "2026-07-13T10:01:00", "E": "2026-07-13T10:01:10"},
        ],
        serial="SERIAL1",
    )

    assert merged_sdcard_playback_window(
        records,
        records[1],
        datetime(2026, 7, 13, 10, 0, 0),
        datetime(2026, 7, 13, 10, 0, 35),
        max_gap_seconds=5,
    ) == (
        datetime(2026, 7, 13, 10, 0, 0),
        datetime(2026, 7, 13, 10, 0, 30),
        2,
    )