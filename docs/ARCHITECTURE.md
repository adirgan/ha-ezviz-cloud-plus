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
6. `mqtt.py` and optimistic commands publish copy-on-write camera updates and
   synchronize the reconciler so polling cannot revert newer local information.

## Ownership map

- `manifest.json`: HACS/HA identity and pinned API dependency.
- `const.py`: domain, entry keys, defaults, regions, and shared constants.
- `config_flow.py`: login, MFA, reauthentication, and options UI.
- `__init__.py`: config-entry lifecycle and platform registration.
- `coordinator.py`: serialized cloud access, snapshot ownership, transient-state
  reconciliation, per-camera health, and copy-on-write updates.
- `entity.py`: common entity/device behavior.
- `utility.py`: payload normalization, feature traversal, and support gates.
- `sensor.py`, `binary_sensor.py`, etc.: explicit HA entity descriptions.
- `strings.json` and `translations/en.json`: entity and config-flow translations.
- `migration.py`: unique-ID and legacy-entry migrations.

## State semantics

- Structural absence is unknown input, not a functional state change.
- Explicit EZVIZ offline status and authentication failures are immediate.
- Retained data becomes unavailable after the bounded grace period without
  replacing its last known values with synthesized defaults.
- Equal snapshots are deduplicated by `DataUpdateCoordinator(always_update=False)`.
- Diagnostics read the existing redacted snapshot and sanitized health counts;
  they do not perform an additional API request.

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
