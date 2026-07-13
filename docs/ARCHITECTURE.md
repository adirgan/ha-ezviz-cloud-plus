# Architecture

## Runtime flow

1. `config_flow.py` authenticates the EZVIZ account and stores cloud tokens in a
   Home Assistant config entry.
2. `__init__.py` recreates `EzvizClient`, validates/refreshes tokens, creates the
   coordinator, starts MQTT handling, and forwards platform setup.
3. `coordinator.py` calls `EzvizClient.load_cameras()` every 30 seconds.
4. Platform modules create entities from explicit description tuples and read
   values from the coordinator snapshot.
5. `mqtt.py` merges event updates into the same coordinator data and publishes a
   new top-level dictionary so listeners update.

## Ownership map

- `manifest.json`: HACS/HA identity and pinned API dependency.
- `const.py`: domain, entry keys, defaults, regions, and shared constants.
- `config_flow.py`: login, MFA, reauthentication, and options UI.
- `__init__.py`: config-entry lifecycle and platform registration.
- `coordinator.py`: cloud polling and update error handling.
- `entity.py`: common entity/device behavior.
- `utility.py`: payload normalization, feature traversal, and support gates.
- `sensor.py`, `binary_sensor.py`, etc.: explicit HA entity descriptions.
- `strings.json` and `translations/en.json`: entity and config-flow translations.
- `migration.py`: unique-ID and legacy-entry migrations.

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
