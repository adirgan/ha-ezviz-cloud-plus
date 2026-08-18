"""Provides the ezviz DataUpdateCoordinator."""

import asyncio
from collections.abc import Callable
from copy import deepcopy
from datetime import timedelta
from functools import wraps
import logging
from threading import RLock
from time import monotonic
from typing import Any

from pyezvizapi.client import EzvizClient
from pyezvizapi.exceptions import (
    EzvizAuthTokenExpired,
    EzvizAuthVerificationCode,
    HTTPError,
    InvalidURL,
    PyEzvizError,
)
from requests.exceptions import RequestException

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_RAW_CAMERA_KEYS = {"deviceInfos", "resourceInfos"}
_MAX_TRANSIENT_FAILURES = 2
_MAX_STALE_SECONDS = 75
_MAX_CONSECUTIVE_LOAD_TIMEOUTS = 2
_RECOVERY_VOLATILE_KEYS = {"last_alarm_pic"}


def _is_raw_camera_key(key: str) -> bool:
    """Return whether a camera key comes from the raw API payload."""
    return key in _RAW_CAMERA_KEYS or key.isupper()


def _contains_mapping_structure(current: Any, previous: Any) -> bool:
    """Return whether current retains the mapping structure from previous."""
    if not isinstance(previous, dict):
        return True
    if not isinstance(current, dict):
        return False
    return all(
        key in current and _contains_mapping_structure(current[key], value)
        for key, value in previous.items()
    )


def _recovery_snapshots_equal(
    first: dict[str, Any], second: dict[str, Any]
) -> bool:
    """Compare recovery snapshots without volatile signed cloud values."""
    return all(
        first.get(key) == second.get(key)
        for key in first.keys() | second.keys()
        if key not in _RECOVERY_VOLATILE_KEYS
    )


class _CameraSnapshotReconciler:
    """Keep complete camera snapshots stable across partial API responses."""

    def __init__(self, initial: dict[str, dict[str, Any]]) -> None:
        """Initialize the reconciler with a detached published snapshot."""
        self._published = deepcopy(initial)
        self._degraded_serials: set[str] = set()
        self._candidates: dict[str, dict[str, Any]] = {}
        self._last_partial_serials: set[str] = set()

    @property
    def degraded(self) -> bool:
        """Return whether any camera is waiting for complete recovery."""
        return bool(self._degraded_serials)

    @property
    def partial_serials(self) -> set[str]:
        """Return cameras that were incomplete in the latest response."""
        return set(self._last_partial_serials)

    def _is_complete(self, serial: str, camera: dict[str, Any]) -> bool:
        """Return whether camera retains its previously confirmed raw structure."""
        previous = self._published.get(serial)
        if previous is None:
            return bool(camera.get("name")) and "status" in camera
        return all(
            key in camera and _contains_mapping_structure(camera[key], value)
            for key, value in previous.items()
            if _is_raw_camera_key(key)
        )

    def merge_camera_update(self, serial: str, fields: dict[str, Any]) -> None:
        """Apply an immediate push or optimistic update to internal snapshots."""
        if serial in self._published:
            self._published[serial] = {**self._published[serial], **fields}
        if serial in self._candidates:
            self._candidates[serial] = {**self._candidates[serial], **fields}

    def reconcile(self, incoming: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Return a stable detached snapshot for publication."""
        reconciled = deepcopy(self._published)
        self._last_partial_serials = set()

        for serial, camera in incoming.items():
            if not self._is_complete(serial, camera):
                self._last_partial_serials.add(serial)
                self._degraded_serials.add(serial)
                self._candidates.pop(serial, None)
                continue

            detached_camera = deepcopy(camera)
            previous = self._published.get(serial)
            if detached_camera.get("status") == 2:
                reconciled[serial] = detached_camera
                self._degraded_serials.discard(serial)
                self._candidates.pop(serial, None)
                continue
            if serial not in self._degraded_serials or previous is None:
                reconciled[serial] = detached_camera
                continue

            if detached_camera == previous:
                self._degraded_serials.discard(serial)
                self._candidates.pop(serial, None)
                continue

            candidate = self._candidates.get(serial)
            if candidate is not None and _recovery_snapshots_equal(
                candidate, detached_camera
            ):
                reconciled[serial] = detached_camera
                self._degraded_serials.discard(serial)
                self._candidates.pop(serial, None)
            else:
                self._candidates[serial] = detached_camera

        missing_serials = self._published.keys() - incoming.keys()
        self._last_partial_serials.update(missing_serials)
        self._degraded_serials.update(missing_serials)
        for serial in missing_serials:
            self._candidates.pop(serial, None)

        self._published = deepcopy(reconciled)
        return reconciled


class _TransientFailureTracker:
    """Track bounded stale-data grace after transient failures."""

    def __init__(self, *, now: Callable[[], float] = monotonic) -> None:
        """Initialize the failure tracker."""
        self._now = now
        self._last_success = now()
        self._failures = 0

    def record_success(self) -> None:
        """Reset failure state after a complete response."""
        self._last_success = self._now()
        self._failures = 0

    def record_failure(self) -> bool:
        """Return whether the stale-data grace has expired."""
        self._failures += 1
        return (
            self._failures >= _MAX_TRANSIENT_FAILURES
            or self._now() - self._last_success >= _MAX_STALE_SECONDS
        )


class _LockedEzvizClientProxy:
    """Serialize runtime access to the shared EZVIZ client."""

    def __init__(self, client: EzvizClient) -> None:
        """Initialize the client proxy."""
        self._client = client
        self._lock = RLock()
        self._wrappers: dict[str, Callable[..., Any]] = {}

    def load_cameras(self) -> dict:
        """Load and detach camera data while holding the client lock."""
        with self._lock:
            return deepcopy(self._client.load_cameras())

    def __getattr__(self, name: str) -> Any:
        """Proxy client attributes and serialize callable access."""
        attribute = getattr(self._client, name)
        if not callable(attribute):
            return attribute
        if name in self._wrappers:
            return self._wrappers[name]

        @wraps(attribute)
        def locked_call(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                return attribute(*args, **kwargs)

        self._wrappers[name] = locked_call
        return locked_call


class EzvizDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching EZVIZ data."""

    def __init__(
        self, hass: HomeAssistant, *, api: EzvizClient, api_timeout: int
    ) -> None:
        """Initialize global EZVIZ data updater."""
        self._raw_ezviz_client = api
        self.ezviz_client = _LockedEzvizClientProxy(api)
        self._client_token = api.export_token()
        self._api_timeout = api_timeout
        self._snapshot_reconciler: _CameraSnapshotReconciler | None = None
        self._failure_trackers: dict[str, _TransientFailureTracker] = {}
        self._unavailable_serials: set[str] = set()
        self._availability_changed = False
        self._data_changed = False
        self._load_cameras_task: asyncio.Future[dict] | None = None
        self._consecutive_load_timeouts = 0
        update_interval = timedelta(seconds=30)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
            always_update=False,
        )

    async def _async_update_data(self) -> dict:
        """Fetch data from EZVIZ."""
        try:
            if self._load_cameras_task is None:
                self._load_cameras_task = asyncio.ensure_future(
                    self.hass.async_add_executor_job(self.ezviz_client.load_cameras)
                )
            async with asyncio.timeout(self._api_timeout):
                cameras = await asyncio.shield(self._load_cameras_task)

            self._load_cameras_task = None
            self._consecutive_load_timeouts = 0
            if raw_client := getattr(self, "_raw_ezviz_client", None):
                self._client_token = raw_client.export_token()
            return self._process_camera_snapshot(cameras)

        except (EzvizAuthTokenExpired, EzvizAuthVerificationCode) as error:
            self._load_cameras_task = None
            raise ConfigEntryAuthFailed from error

        except (InvalidURL, HTTPError, PyEzvizError, RequestException) as error:
            self._load_cameras_task = None
            self._consecutive_load_timeouts = 0
            if self._retain_after_global_failure():
                return self.data
            raise UpdateFailed(f"Invalid response from API: {error}") from error

        except TimeoutError as error:
            self._consecutive_load_timeouts = (
                getattr(self, "_consecutive_load_timeouts", 0) + 1
            )
            if self._consecutive_load_timeouts >= _MAX_CONSECUTIVE_LOAD_TIMEOUTS:
                self._rotate_stalled_client()
            if self._retain_after_global_failure():
                return self.data
            raise UpdateFailed("Timed out fetching EZVIZ data") from error

    @staticmethod
    def _observe_abandoned_task(task: asyncio.Future[dict]) -> None:
        """Consume a detached executor task result when it eventually finishes."""
        if not task.cancelled():
            task.exception()

    def _detach_load_task(self) -> None:
        """Detach polling work that cannot be cancelled once in the executor."""
        if load_task := self._load_cameras_task:
            if load_task.done():
                self._observe_abandoned_task(load_task)
            else:
                load_task.add_done_callback(self._observe_abandoned_task)
        self._load_cameras_task = None

    def _rotate_stalled_client(self) -> None:
        """Isolate a client whose polling request remains blocked."""
        self._detach_load_task()
        token = getattr(self, "_client_token", None)
        if token is None:
            token = self._raw_ezviz_client.export_token()
        replacement = EzvizClient(token=token, timeout=self._api_timeout)
        self._raw_ezviz_client = replacement
        self.ezviz_client = _LockedEzvizClientProxy(replacement)
        self._consecutive_load_timeouts = 0

    def _process_camera_snapshot(self, cameras: dict) -> dict:
        """Validate camera structure and apply bounded stale-data retention."""
        if not cameras:
            if self._retain_after_global_failure():
                return self.data
            raise UpdateFailed("EZVIZ returned an empty camera snapshot")

        if self._snapshot_reconciler is None:
            self._snapshot_reconciler = _CameraSnapshotReconciler(cameras)
            for serial, camera in cameras.items():
                self._failure_trackers[serial] = _TransientFailureTracker()
                if camera.get("status") == 2:
                    self._unavailable_serials.add(serial)
            self._data_changed = cameras != self.data
            return cameras

        reconciled = self._snapshot_reconciler.reconcile(cameras)
        partial_serials = self._snapshot_reconciler.partial_serials
        previous_unavailable = set(self._unavailable_serials)

        for serial in reconciled:
            tracker = self._failure_trackers.setdefault(
                serial, _TransientFailureTracker()
            )
            if serial in partial_serials:
                if tracker.record_failure():
                    self._unavailable_serials.add(serial)
            elif reconciled[serial].get("status") == 2:
                tracker.record_success()
                self._unavailable_serials.add(serial)
            else:
                tracker.record_success()
                self._unavailable_serials.discard(serial)

        self._availability_changed = previous_unavailable != self._unavailable_serials
        self._data_changed = reconciled != self.data
        return reconciled

    def _retain_after_global_failure(self) -> bool:
        """Return whether all published cameras remain inside stale grace."""
        if not self.data:
            return False
        previous_unavailable = set(self._unavailable_serials)
        for serial in self.data:
            tracker = self._failure_trackers.setdefault(
                serial, _TransientFailureTracker()
            )
            if tracker.record_failure():
                self._unavailable_serials.add(serial)
        self._availability_changed = previous_unavailable != self._unavailable_serials
        self._data_changed = False
        return True

    def is_camera_available(self, serial: str) -> bool:
        """Return whether a camera remains inside the accepted health policy."""
        return serial not in self._unavailable_serials

    @property
    def diagnostic_health(self) -> dict[str, Any]:
        """Return sanitized coordinator health metadata."""
        return {
            "camera_count": len(self.data),
            "unavailable_count": len(self._unavailable_serials),
            "degraded": bool(
                self._snapshot_reconciler and self._snapshot_reconciler.degraded
            ),
            "load_in_progress": bool(
                self._load_cameras_task and not self._load_cameras_task.done()
            ),
        }

    async def async_shutdown(self) -> None:
        """Detach active executor work before shutting down."""
        self._detach_load_task()
        await super().async_shutdown()

    def _async_refresh_finished(self) -> None:
        """Notify listeners when only camera availability changed."""
        if self._availability_changed and not self._data_changed:
            self.async_update_listeners()
        self._availability_changed = False
        self._data_changed = False

    def merge_mqtt_update(self, serial: str, mqtt_data: dict) -> None:
        """Merge MQTT update data into the coordinator."""
        ext = mqtt_data["ext"]
        if not ext.get("image"):
            return

        self.merge_camera_update(
            serial,
            {
                "last_alarm_type_code": ext.get("alert_type_code"),
                "last_alarm_time": ext.get("time"),
                "last_alarm_pic": ext.get("image"),
                "last_alarm_type_name": mqtt_data.get("alert"),
                "Motion_Trigger": True,
            },
        )

    def merge_camera_update(self, serial: str, fields: dict[str, Any]) -> None:
        """Publish a copy-on-write update for one camera."""
        updated_data = dict(self.data)
        camera_data = dict(updated_data.get(serial, {}))
        updated_camera = {**camera_data, **fields}
        if updated_camera == camera_data:
            return

        if reconciler := getattr(self, "_snapshot_reconciler", None):
            reconciler.merge_camera_update(serial, fields)
        updated_data[serial] = updated_camera
        self.async_set_updated_data(updated_data)
