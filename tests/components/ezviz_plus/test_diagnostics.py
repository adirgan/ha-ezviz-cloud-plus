"""Tests for EZVIZ diagnostics."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.ezviz_plus.const import DATA_COORDINATOR, DOMAIN
from custom_components.ezviz_plus.diagnostics import (
    async_get_config_entry_diagnostics,
)


def test_diagnostics_use_existing_coordinator_snapshot() -> None:
    """Do not issue an additional cloud request while collecting diagnostics."""
    coordinator = SimpleNamespace(
        data={"CAMERA_A": {"name": "Camera A", "status": 1}},
        diagnostic_health={
            "camera_count": 1,
            "unavailable_count": 0,
            "degraded": False,
            "load_in_progress": False,
        },
        ezviz_client=MagicMock(),
    )
    entry = SimpleNamespace(entry_id="entry-1")
    hass = SimpleNamespace(
        data={DOMAIN: {entry.entry_id: {DATA_COORDINATOR: coordinator}}}
    )

    diagnostics = asyncio.run(async_get_config_entry_diagnostics(hass, entry))

    assert diagnostics["ezviz_coordinator_health"] == coordinator.diagnostic_health
    assert diagnostics["ezviz_coordinator_data"][0]["CAMERA_A"]["status"] == 1
    coordinator.ezviz_client.get_device_infos.assert_not_called()