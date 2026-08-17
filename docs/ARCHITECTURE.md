# Architecture

## Runtime flow

1. `config_flow.py` authenticates the EZVIZ account and stores cloud tokens in a
   Home Assistant config entry.
2. `__init__.py` recreates `EzvizClient`, validates/refreshes tokens, creates the
   coordinator, starts MQTT handling, and forwards platform setup.
3. `coordinator.py` serializes all shared-client calls, calls
   `EzvizClient.load_cameras()` every 30 seconds, and deep-copies camera data
   before releasing the client lock.
4. Platform modules create entities from explicit description tuples and read
   values from the stable coordinator snapshot.
5. The coordinator reconciles raw camera structure per camera. Partial snapshots
   retain the last complete state within a two-failure/75-second grace period;
   changed recovery states require two equal complete snapshots.
6. A timed-out polling Future is reused once to permit normal late completion.
   If it times out again, the coordinator isolates the blocked client and creates
   a replacement from the last known token so its lock cannot stall new work.
7. Raw `requests` transport exceptions retain an existing snapshot instead of
   failing the Home Assistant refresh. Account-alarm polling has an independent
   eight-second timeout so client-lock contention cannot trigger HA's slow-update
   warning or replace its last known state.
8. `mqtt.py` and optimistic commands publish copy-on-write camera updates and
   synchronize the reconciler so polling cannot revert newer local information.
9. Camera previews use stale-while-revalidate semantics. A single shared task
   retries transient cloud capture failures and survives Home Assistant's proxy
   request timeout; the last valid JPEG is served immediately for five minutes
   so an open dashboard cannot repeatedly wake a battery camera. Stale data
   refreshes once in the background, and entity removal cancels the remaining
   refresh task.

## Ownership map

- `manifest.json`: HACS/HA identity and pinned API dependency.
- `const.py`: domain, entry keys, defaults, regions, and shared constants.
- `config_flow.py`: login, MFA, reauthentication, and options UI.
- `__init__.py`: config-entry lifecycle and platform registration.
- `coordinator.py`: serialized cloud access, snapshot ownership, transient-state
  reconciliation, per-camera health, and copy-on-write updates.
- `entity.py`: common entity/device behavior.
- `camera.py`: RTSP/cloud preview routing, bounded snapshot retries, last-valid
  preview caching, and live-stream source selection.
- `utility.py`: payload normalization, feature traversal, and support gates.
- `sensor.py`, `binary_sensor.py`, etc.: explicit HA entity descriptions.
- `strings.json` and `translations/en.json`: entity and config-flow translations.
- `migration.py`: unique-ID and legacy-entry migrations.

## State semantics

- Structural absence is unknown input, not a functional state change.
- Explicit EZVIZ offline status and authentication failures are immediate.
- Diagnostic camera health expires after the bounded grace period, but retained
  entity values remain available to Recorder. Only explicit EZVIZ `status == 2`
  makes camera entities unavailable.
- Equal snapshots are deduplicated by `DataUpdateCoordinator(always_update=False)`.
- Diagnostics read the existing redacted snapshot and sanitized health counts;
  they do not perform an additional API request.
- Runtime logs never include signed image URLs, camera serials, credentials, or
  raw cloud payloads. Cloud-video cleanup does not block the event loop.

## Identity constraints

- Domain is `ezviz_plus`.
- The old base domain was `ezviz_cloud`; it must not be reintroduced.
- Unique IDs use camera serial plus description key.
- Repository is intended to coexist with official `ezviz` and other custom
  integrations, so domain separation is deliberate.

## Dependency

The manifest currently pins the API fork to an immutable commit:

```text
pyezvizapi @ git+https://github.com/adirgan/pyEzvizApi.git@a7710099624008e113269daed0f7f41e3d0b510e
```

Prefer a tagged/released API version before public HACS distribution, while
keeping an immutable requirement for reproducible installs.
