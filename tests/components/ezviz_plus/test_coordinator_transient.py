"""Tests for transient EZVIZ coordinator snapshots."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from requests.exceptions import ReadTimeout

from custom_components.ezviz_plus.coordinator import (
    EzvizDataUpdateCoordinator,
    _CameraSnapshotReconciler,
    _LockedEzvizClientProxy,
    _TransientFailureTracker,
)
from custom_components.ezviz_plus.entity import EzvizEntity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


def _camera_snapshot() -> dict:
    """Return a complete minimal camera snapshot."""
    return {
        "CAMERA_A": {
            "name": "Camera A",
            "status": 1,
            "alarm_notify": True,
            "battery_level": 100,
            "battery_camera_work_mode": 4,
            "last_alarm_pic": "old.jpg",
            "STATUS": {
                "globalStatus": 1,
                "optionals": {
                    "powerRemaining": 100,
                    "batteryCameraWorkMode": 4,
                },
            },
        }
    }


def test_mqtt_merge_is_copy_on_write() -> None:
    """Do not mutate a camera snapshot that was already published."""
    coordinator = object.__new__(EzvizDataUpdateCoordinator)
    coordinator.data = _camera_snapshot()
    coordinator.async_set_updated_data = MagicMock()
    previous_data = coordinator.data
    previous_camera = coordinator.data["CAMERA_A"]
    previous_snapshot = deepcopy(previous_data)

    coordinator.merge_mqtt_update(
        "CAMERA_A",
        {
            "alert": "Person",
            "ext": {
                "alert_type_code": 2403,
                "device_serial": "CAMERA_A",
                "image": "new.jpg",
                "time": "2026-08-17 15:22:18",
            },
        },
    )

    published = coordinator.async_set_updated_data.call_args.args[0]
    assert previous_data == previous_snapshot
    assert published is not previous_data
    assert published["CAMERA_A"] is not previous_camera
    assert published["CAMERA_A"]["last_alarm_pic"] == "new.jpg"


def test_client_proxy_preserves_attributes() -> None:
    """Expose non-callable client attributes without changing their values."""
    client = MagicMock()
    client.api_url = "api.example.test"

    proxy = _LockedEzvizClientProxy(client)

    assert proxy.api_url == "api.example.test"


def test_client_proxy_serializes_calls() -> None:
    """Allow only one runtime client call to execute at a time."""
    first_started = Event()
    release_first = Event()
    state_lock = Lock()
    active_calls = 0
    max_active_calls = 0

    class Client:
        def call(self, *, wait: bool) -> None:
            nonlocal active_calls, max_active_calls
            with state_lock:
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
            if wait:
                first_started.set()
                release_first.wait(timeout=1)
            with state_lock:
                active_calls -= 1

    proxy = _LockedEzvizClientProxy(Client())
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(proxy.call, wait=True)
        assert first_started.wait(timeout=1)
        second = executor.submit(proxy.call, wait=False)
        release_first.set()
        first.result(timeout=1)
        second.result(timeout=1)

    assert max_active_calls == 1


def test_client_proxy_copies_camera_snapshot_under_lock() -> None:
    """Return camera data that cannot be changed through the client cache."""
    client = MagicMock()
    client.load_cameras.return_value = _camera_snapshot()
    proxy = _LockedEzvizClientProxy(client)

    snapshot = proxy.load_cameras()
    client.load_cameras.return_value["CAMERA_A"]["STATUS"]["globalStatus"] = 0

    assert snapshot["CAMERA_A"]["STATUS"]["globalStatus"] == 1


def test_partial_camera_keeps_last_complete_snapshot() -> None:
    """Do not expose synthesized defaults when raw camera data disappears."""
    initial = _camera_snapshot()
    reconciler = _CameraSnapshotReconciler(initial)
    partial = deepcopy(initial)
    partial["CAMERA_A"]["alarm_notify"] = False
    partial["CAMERA_A"]["battery_level"] = None
    partial["CAMERA_A"]["battery_camera_work_mode"] = -1
    partial["CAMERA_A"]["STATUS"] = {}

    result = reconciler.reconcile(partial)

    assert result == initial
    assert reconciler.degraded


def test_healthy_camera_updates_while_other_camera_is_partial() -> None:
    """Accept healthy camera changes without exposing a partial peer."""
    initial = _camera_snapshot()
    initial["CAMERA_B"] = deepcopy(initial["CAMERA_A"])
    initial["CAMERA_B"]["name"] = "Camera B"
    reconciler = _CameraSnapshotReconciler(initial)
    incoming = deepcopy(initial)
    incoming["CAMERA_A"]["battery_level"] = 99
    incoming["CAMERA_A"]["STATUS"]["optionals"]["powerRemaining"] = 99
    incoming["CAMERA_B"]["STATUS"] = {}
    incoming["CAMERA_B"]["battery_level"] = None

    result = reconciler.reconcile(incoming)

    assert result["CAMERA_A"]["battery_level"] == 99
    assert result["CAMERA_B"] == initial["CAMERA_B"]


def test_recovery_change_requires_two_complete_snapshots() -> None:
    """Confirm a changed camera twice after a degraded snapshot."""
    initial = _camera_snapshot()
    reconciler = _CameraSnapshotReconciler(initial)
    partial = deepcopy(initial)
    partial["CAMERA_A"]["STATUS"] = {}
    reconciler.reconcile(partial)
    recovered = deepcopy(initial)
    recovered["CAMERA_A"]["battery_camera_work_mode"] = 1
    recovered["CAMERA_A"]["STATUS"]["optionals"]["batteryCameraWorkMode"] = 1

    first = reconciler.reconcile(recovered)
    second = reconciler.reconcile(deepcopy(recovered))

    assert first["CAMERA_A"]["battery_camera_work_mode"] == 4
    assert second["CAMERA_A"]["battery_camera_work_mode"] == 1
    assert not reconciler.degraded


def test_recovery_ignores_rotating_signed_alarm_image_url() -> None:
    """Confirm stable values when only the signed alarm image URL rotates."""
    initial = _camera_snapshot()
    reconciler = _CameraSnapshotReconciler(initial)
    partial = deepcopy(initial)
    partial["CAMERA_A"]["STATUS"] = {}
    reconciler.reconcile(partial)

    first_recovery = deepcopy(initial)
    first_recovery["CAMERA_A"]["battery_level"] = 96
    first_recovery["CAMERA_A"]["STATUS"]["optionals"]["powerRemaining"] = 96
    first_recovery["CAMERA_A"]["last_alarm_pic"] = "alarm.jpg?sign=first"
    second_recovery = deepcopy(first_recovery)
    second_recovery["CAMERA_A"]["last_alarm_pic"] = "alarm.jpg?sign=second"

    first = reconciler.reconcile(first_recovery)
    second = reconciler.reconcile(second_recovery)

    assert first["CAMERA_A"]["battery_level"] == 100
    assert second["CAMERA_A"]["battery_level"] == 96
    assert second["CAMERA_A"]["last_alarm_pic"] == "alarm.jpg?sign=second"
    assert not reconciler.degraded


def test_work_mode_history_sequence_stays_stable_until_confirmed() -> None:
    """Keep custom through a partial response and one standard candidate."""
    initial = _camera_snapshot()
    reconciler = _CameraSnapshotReconciler(initial)
    partial = deepcopy(initial)
    partial["CAMERA_A"]["STATUS"] = {}
    standard = deepcopy(initial)
    standard["CAMERA_A"]["battery_camera_work_mode"] = 1
    standard["CAMERA_A"]["STATUS"]["optionals"]["batteryCameraWorkMode"] = 1

    during_partial = reconciler.reconcile(partial)
    first_standard = reconciler.reconcile(standard)
    confirmed_standard = reconciler.reconcile(deepcopy(standard))

    assert during_partial["CAMERA_A"]["battery_camera_work_mode"] == 4
    assert first_standard["CAMERA_A"]["battery_camera_work_mode"] == 4
    assert confirmed_standard["CAMERA_A"]["battery_camera_work_mode"] == 1


def test_explicit_offline_bypasses_recovery_confirmation() -> None:
    """Publish explicit offline status immediately after degradation."""
    initial = _camera_snapshot()
    reconciler = _CameraSnapshotReconciler(initial)
    partial = deepcopy(initial)
    partial["CAMERA_A"]["STATUS"] = {}
    reconciler.reconcile(partial)
    offline = deepcopy(initial)
    offline["CAMERA_A"]["status"] = 2

    result = reconciler.reconcile(offline)

    assert result["CAMERA_A"]["status"] == 2
    assert not reconciler.degraded


def test_push_update_is_not_reverted_by_next_poll() -> None:
    """Keep a push field until polling reports a genuinely newer value."""
    initial = _camera_snapshot()
    reconciler = _CameraSnapshotReconciler(initial)
    reconciler.merge_camera_update("CAMERA_A", {"last_alarm_pic": "new.jpg"})
    incoming = deepcopy(initial)
    incoming["CAMERA_A"]["last_alarm_pic"] = "new.jpg"

    result = reconciler.reconcile(incoming)

    assert result["CAMERA_A"]["last_alarm_pic"] == "new.jpg"


def test_transient_failure_tracker_expires_on_second_failure() -> None:
    """Retain one transient failure and expire on the second."""
    clock = SimpleNamespace(value=100.0)
    tracker = _TransientFailureTracker(now=lambda: clock.value)

    assert not tracker.record_failure()
    clock.value += 1
    assert tracker.record_failure()


def test_transient_failure_tracker_expires_after_seventy_five_seconds() -> None:
    """Expire stale data when its age reaches the configured limit."""
    clock = SimpleNamespace(value=100.0)
    tracker = _TransientFailureTracker(now=lambda: clock.value)
    tracker.record_success()
    clock.value += 75

    assert tracker.record_failure()


def test_transient_failure_tracker_resets_after_success() -> None:
    """Reset the failure count after a complete API response."""
    clock = SimpleNamespace(value=100.0)
    tracker = _TransientFailureTracker(now=lambda: clock.value)
    assert not tracker.record_failure()
    tracker.record_success()

    assert not tracker.record_failure()


def test_entity_availability_retains_last_known_value_during_cloud_failure() -> None:
    """Keep retained entity values available when only cloud health expires."""
    entity = object.__new__(EzvizEntity)
    entity._serial = "CAMERA_A"
    entity.coordinator = SimpleNamespace(
        data=_camera_snapshot(),
        is_camera_available=lambda serial: False,
    )

    assert entity.available


def test_explicit_offline_status_is_unavailable() -> None:
    """Do not hide an explicit device offline status behind stale grace."""
    data = _camera_snapshot()
    data["CAMERA_A"]["status"] = 2
    entity = object.__new__(EzvizEntity)
    entity._serial = "CAMERA_A"
    entity.coordinator = SimpleNamespace(
        data=data,
        is_camera_available=lambda serial: True,
    )

    assert not entity.available


def test_initial_offline_snapshot_updates_camera_health() -> None:
    """Count an explicitly offline camera in initial health metadata."""
    cameras = _camera_snapshot()
    cameras["CAMERA_A"]["status"] = 2
    coordinator = object.__new__(EzvizDataUpdateCoordinator)
    coordinator.data = None
    coordinator._snapshot_reconciler = None
    coordinator._failure_trackers = {}
    coordinator._unavailable_serials = set()
    coordinator._availability_changed = False
    coordinator._data_changed = False
    coordinator._load_cameras_task = None

    coordinator.data = coordinator._process_camera_snapshot(cameras)

    assert not coordinator.is_camera_available("CAMERA_A")
    assert coordinator.diagnostic_health["unavailable_count"] == 1


def test_shutdown_observes_active_camera_load() -> None:
    """Observe the persistent executor future before coordinator shutdown ends."""

    async def run_test() -> None:
        coordinator = object.__new__(EzvizDataUpdateCoordinator)
        load_task = asyncio.get_running_loop().create_future()
        coordinator._load_cameras_task = load_task
        load_task.set_result(_camera_snapshot())

        with patch.object(
            DataUpdateCoordinator, "async_shutdown", new=AsyncMock()
        ) as base_shutdown:
            await coordinator.async_shutdown()

        base_shutdown.assert_awaited_once()
        assert coordinator._load_cameras_task is None

    asyncio.run(run_test())


def test_shutdown_does_not_wait_for_stalled_camera_load() -> None:
    """Allow Home Assistant to stop while executor work remains blocked."""

    async def run_test() -> None:
        coordinator = object.__new__(EzvizDataUpdateCoordinator)
        load_task = asyncio.get_running_loop().create_future()
        coordinator._load_cameras_task = load_task

        with patch.object(
            DataUpdateCoordinator, "async_shutdown", new=AsyncMock()
        ) as base_shutdown:
            async with asyncio.timeout(0.1):
                await coordinator.async_shutdown()

        base_shutdown.assert_awaited_once()
        assert coordinator._load_cameras_task is None
        assert not load_task.cancelled()

    asyncio.run(run_test())


def test_timeout_reuses_and_later_consumes_camera_load() -> None:
    """Do not start another API load while timed-out executor work continues."""

    async def run_test() -> None:
        coordinator = object.__new__(EzvizDataUpdateCoordinator)
        load_task = asyncio.get_running_loop().create_future()
        coordinator._load_cameras_task = load_task
        coordinator._api_timeout = 0.001
        coordinator.data = _camera_snapshot()
        coordinator._snapshot_reconciler = _CameraSnapshotReconciler(
            coordinator.data
        )
        coordinator._failure_trackers = {
            "CAMERA_A": _TransientFailureTracker()
        }
        coordinator._unavailable_serials = set()
        coordinator._availability_changed = False
        coordinator._data_changed = False
        coordinator.hass = SimpleNamespace(async_add_executor_job=MagicMock())

        retained = await coordinator._async_update_data()

        assert retained == coordinator.data
        assert coordinator._load_cameras_task is load_task
        coordinator.hass.async_add_executor_job.assert_not_called()

        recovered = deepcopy(coordinator.data)
        recovered["CAMERA_A"]["battery_level"] = 99
        recovered["CAMERA_A"]["STATUS"]["optionals"]["powerRemaining"] = 99
        load_task.set_result(recovered)
        coordinator._api_timeout = 1

        result = await coordinator._async_update_data()

        assert result["CAMERA_A"]["battery_level"] == 99
        assert coordinator._load_cameras_task is None
        coordinator.hass.async_add_executor_job.assert_not_called()

    asyncio.run(run_test())


def test_second_timeout_rotates_stalled_client() -> None:
    """Isolate a permanently blocked client after the second timeout."""

    async def run_test() -> None:
        coordinator = object.__new__(EzvizDataUpdateCoordinator)
        load_task = asyncio.get_running_loop().create_future()
        old_client = MagicMock()
        old_client.export_token.return_value = {
            "session_id": "session",
            "rf_session_id": "refresh",
            "username": "account",
            "api_url": "api.example.test",
        }
        coordinator._raw_ezviz_client = old_client
        coordinator.ezviz_client = _LockedEzvizClientProxy(old_client)
        coordinator._load_cameras_task = load_task
        coordinator._consecutive_load_timeouts = 0
        coordinator._api_timeout = 0.001
        coordinator.data = _camera_snapshot()
        coordinator._snapshot_reconciler = _CameraSnapshotReconciler(
            coordinator.data
        )
        coordinator._failure_trackers = {
            "CAMERA_A": _TransientFailureTracker()
        }
        coordinator._unavailable_serials = set()
        coordinator._availability_changed = False
        coordinator._data_changed = False
        coordinator.hass = SimpleNamespace(async_add_executor_job=MagicMock())
        new_client = MagicMock()

        with patch(
            "custom_components.ezviz_plus.coordinator.EzvizClient",
            return_value=new_client,
        ) as client_type:
            await coordinator._async_update_data()
            assert coordinator._load_cameras_task is load_task

            await coordinator._async_update_data()

        client_type.assert_called_once_with(
            token=old_client.export_token.return_value,
            timeout=coordinator._api_timeout,
        )
        assert coordinator._raw_ezviz_client is new_client
        assert coordinator._load_cameras_task is None
        assert not load_task.cancelled()

    asyncio.run(run_test())


def test_requests_timeout_retains_snapshot_without_update_failure() -> None:
    """Treat requests transport failures as transient cloud failures."""

    async def run_test() -> None:
        coordinator = object.__new__(EzvizDataUpdateCoordinator)
        load_task = asyncio.get_running_loop().create_future()
        load_task.set_exception(ReadTimeout("cloud read timed out"))
        coordinator._load_cameras_task = load_task
        coordinator._consecutive_load_timeouts = 0
        coordinator._api_timeout = 25
        coordinator.data = _camera_snapshot()
        coordinator._snapshot_reconciler = _CameraSnapshotReconciler(
            coordinator.data
        )
        coordinator._failure_trackers = {
            "CAMERA_A": _TransientFailureTracker()
        }
        coordinator._unavailable_serials = set()
        coordinator._availability_changed = False
        coordinator._data_changed = False

        result = await coordinator._async_update_data()

        assert result == coordinator.data
        assert coordinator._load_cameras_task is None

    asyncio.run(run_test())
