# Current Handoff

Last updated: 2026-07-13.

## Completed

- Cloned `RenierM26/ha-ezviz` at upstream tag `0.2.0.24`.
- Renamed integration directory and domain from `ezviz_cloud` to `ezviz_plus`.
- Updated manifest, HACS metadata, code references, tests, translations, README,
  API routes, and service selectors for the new domain.
- Set product name to `EZVIZ Cloud Plus` and version to `0.1.0`.
- Pinned the manifest to the `adirgan/pyEzvizApi` fork commit documented in
  [ARCHITECTURE.md](ARCHITECTURE.md).
- Added normalized battery detail/status/source helpers.
- Added charge-state and charging-source sensors.
- Added a battery-charging binary sensor.
- Added focused battery helper tests using an observed payload shape.
- Added VS Code tasks and a disposable Docker Home Assistant setup.
- Created the public GitHub repository at
  `https://github.com/adirgan/ha-ezviz-cloud-plus`.
- Committed and pushed the initial `ezviz_plus` integration to `main`.
- Configured Git remotes:
  - `origin`: `https://github.com/adirgan/ha-ezviz-cloud-plus.git`
  - `upstream`: `https://github.com/RenierM26/ha-ezviz.git`

## Validated

- `python -m ruff check .` passes.
- JSON metadata and translation files parse.
- The component compiles.
- Battery helpers pass isolated behavior checks and the focused fixture captures
  authoritative `BatteryDetails.status` precedence.
- Home Assistant `2026.7.2` starts in Docker on port 8123.
- HA discovers `ezviz_plus` as a custom integration without startup errors.
- Docker instance onboarding is complete.

## Not yet validated

- No `ezviz_plus` config entry exists in the Docker instance yet.
- EZVIZ login, MFA, first coordinator refresh, MQTT subscription, and platform
  setup have not been exercised in this instance.
- The three new battery entities have not yet been inspected in Home Assistant.
- Full inherited config-flow tests have not been run in HA's complete test suite.
- HACS and hassfest workflows have not run remotely.

## Immediate next steps

1. Log in to local HA using the credentials in [DEVELOPMENT.md](DEVELOPMENT.md).
2. Add `EZVIZ Cloud Plus` and enter EZVIZ credentials only in the HA UI.
3. Watch container logs during login and first refresh.
4. Verify battery state, binary charging, and charging source on both cameras.
5. Add entity-level tests if setup reveals gating or translation issues.
6. Confirm CI, HACS, and hassfest checks on GitHub.
7. Create a `v0.1.0` release after the checks pass.

## Working-tree status

The domain rename and initial battery telemetry work are committed on `main`.
Do not restore the deleted old-domain files or reintroduce `ezviz_cloud`.

## Security note

`_devconfig/.storage`, databases, logs, and generated runtime files are ignored.
They can contain HA auth data or EZVIZ tokens. The local HA credentials
`test` / `test` may be documented because the user explicitly approved them for
this disposable instance. This exception does not apply to any EZVIZ secret.
