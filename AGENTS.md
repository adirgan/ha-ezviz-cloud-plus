# Agent Instructions

Read [docs/README.md](docs/README.md) before changing code. For continuation
work, read [docs/HANDOFF.md](docs/HANDOFF.md) first.

## Project identity

- Repository: `adirgan/ha-ezviz-cloud-plus`
- Home Assistant domain: `ezviz_plus`
- Integration directory: `custom_components/ezviz_plus`
- Upstream base: `RenierM26/ha-ezviz`
- API fork: `adirgan/pyEzvizApi`
- Do not restore the old `ezviz_cloud` domain or mix it with `ezviz_plus`.

## Working rules

- Preserve the current Home Assistant entity-description and coordinator patterns.
- Treat API values as mixed-type input; use coercion helpers from `utility.py`.
- Prefer structured traversal of `FEATURE_INFO` over ad hoc string parsing.
- Add focused tests for every newly exposed API field.
- Keep runtime data under `_devconfig` out of Git. It may contain tokens.
- Never commit EZVIZ usernames, passwords, MFA codes, session IDs, or camera keys.
- The local HA development login `test` / `test` is intentionally documented;
  it belongs only to the disposable Docker instance.
- Do not commit, tag, push, or publish unless the user explicitly requests it.
- Do not discard unrelated working-tree changes.

## Coordinator state invariants

- Route every runtime API call through `coordinator.ezviz_client`; never retain
  or call the raw shared client outside coordinator construction.
- Detach polling snapshots from the upstream mutable cache while holding the
  serialized client lock. Published coordinator data must share no mutable
  references with `pyEzvizApi`.
- Treat missing raw sections or nested keys as a partial snapshot, not as proof
  of synthesized values such as `False`, `None`, `-1`, `idle`, or `standard`.
- Retain the last complete per-camera snapshot during a transient partial or
  global failure. After two failures or 75 seconds, expire diagnostic camera
  health but keep retained entity values available unless `status == 2`.
- Treat `requests` transport exceptions as transient polling failures when a
  retained snapshot exists. Account-alarm polling must return before Home
  Assistant's ten-second slow-update threshold and retain its last state.
- After degradation, require two equal complete snapshots before publishing a
  changed functional state. Authentication failures and explicit `status == 2`
  remain immediate.
- Apply MQTT and optimistic command updates through coordinator copy-on-write
  helpers, including reconciler state; never mutate `coordinator.data` in place.
- Keep `DataUpdateCoordinator(always_update=False)` so equal snapshots do not
  notify listeners. Notify explicitly when only camera health changes.
- Diagnostics must use the existing redacted coordinator snapshot and sanitized
  health metadata; they must not issue another cloud request.
- Add focused tests for every newly consumed raw section or field and for any
  change to partial-snapshot, recovery, timeout, availability, or push behavior.
- Never log payloads, tokens, credentials, camera keys, signed image URLs, or
  serials. Health telemetry must be counts or booleans only.

## Required validation

Run the narrowest relevant test first, then:

```bash
python -m ruff check .
pytest -q tests/components/ezviz_plus/test_coordinator_transient.py
pytest -q tests/components/ezviz_plus/test_battery.py
git diff --check
```

Use the repository `.venv` or the devcontainer for Python commands. The existing
listener virtualenv does not include Home Assistant. See
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for Docker and VS Code workflows.

## Source-of-truth docs

- Architecture and ownership: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Battery schema and entities: [docs/BATTERY_TELEMETRY.md](docs/BATTERY_TELEMETRY.md)
- Development and testing: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- Current state and next actions: [docs/HANDOFF.md](docs/HANDOFF.md)
