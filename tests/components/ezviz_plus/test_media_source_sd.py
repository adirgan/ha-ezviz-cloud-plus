"""Tests for SD-card recordings in the EZVIZ media source."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.ezviz_plus.const import DATA_COORDINATOR, DOMAIN
from custom_components.ezviz_plus.media_source import EzvizMediaSource
from homeassistant.components.media_source import MediaSourceItem


async def _run_executor_job(callable_job: object, *args: object) -> object:
    return callable_job(*args)  # type: ignore[operator]


def test_sd_recordings_browse_uses_v2_records() -> None:
    """Browsing an SD directory exposes v2 records as playable video items."""

    async def run() -> None:
        client = MagicMock()
        client.search_records_v2.return_value = {
            "records": [{"B": "2026-07-13T10:00:00", "E": "2026-07-13T10:00:20"}]
        }
        client.extract_record_list.return_value = client.search_records_v2.return_value[
            "records"
        ]
        hass = SimpleNamespace(
            data={
                DOMAIN: {
                    "entry-1": {
                        DATA_COORDINATOR: SimpleNamespace(
                            ezviz_client=client,
                            data={"SERIAL1": {"name": "Entrada"}},
                        )
                    }
                }
            },
            async_add_executor_job=AsyncMock(side_effect=_run_executor_job),
        )
        source = EzvizMediaSource(hass)  # type: ignore[arg-type]

        media = await source.async_browse_media(
            MediaSourceItem(hass, DOMAIN, "SDDIR|entry-1|SERIAL1|1h", None)  # type: ignore[arg-type]
        )

        assert media.children
        assert media.children[0].title == "10:00:00 - 10:00:20"
        assert media.children[0].can_play is True
        assert media.children[0].identifier.startswith("SDREC|entry-1|")
        client.search_records_v2.assert_called_once()

    asyncio.run(run())


def test_sd_recordings_browse_allows_no_records() -> None:
    """Browsing a window without recordings returns an empty directory."""

    async def run() -> None:
        client = MagicMock()
        client.search_records_v2.return_value = {"records": None}
        client.extract_record_list.return_value = None
        hass = SimpleNamespace(
            data={
                DOMAIN: {
                    "entry-1": {
                        DATA_COORDINATOR: SimpleNamespace(
                            ezviz_client=client,
                            data={"SERIAL1": {"name": "Entrada"}},
                        )
                    }
                }
            },
            async_add_executor_job=AsyncMock(side_effect=_run_executor_job),
        )
        source = EzvizMediaSource(hass)  # type: ignore[arg-type]

        media = await source.async_browse_media(
            MediaSourceItem(hass, DOMAIN, "SDDIR|entry-1|SERIAL1|today", None)  # type: ignore[arg-type]
        )

        assert media.title == "Entrada - SD recordings - today"
        assert media.can_expand is True
        assert media.children == []

    asyncio.run(run())


def test_sd_recording_resolve_returns_tokenized_local_url() -> None:
    """Resolving an SD item returns a local playback URL with a local token."""

    async def run() -> None:
        hass = SimpleNamespace(data={})
        source = EzvizMediaSource(hass)  # type: ignore[arg-type]
        item = source._recording_to_media_item(
            "entry-1",
            source._decode_recording_payload(
                "eyJzZXJpYWwiOiJTRVJJQUwxIiwiY2hhbm5lbCI6MSwiYmVnaW5fdGltZSI6IjIwMjYtMDctMTNUMTA6MDA6MDAiLCJlbmRfdGltZSI6IjIwMjYtMDctMTNUMTA6MDA6MjAiLCJsaWQiOm51bGwsInJlY29yZF90eXBlIjpudWxsfQ=="
            ),
        )

        resolved = await source.async_resolve_media(
            MediaSourceItem(hass, DOMAIN, item.identifier, None)  # type: ignore[arg-type]
        )

        assert resolved.mime_type == "video/mp4"
        assert resolved.url.startswith("/api/ezviz_plus/sd_playback/entry-1/")
        assert resolved.url.endswith(".mp4")
        assert "SERIAL1" not in resolved.url
        assert hass.data[DOMAIN]["_sd_playback_tokens"]["SERIAL1"] in resolved.url

    asyncio.run(run())