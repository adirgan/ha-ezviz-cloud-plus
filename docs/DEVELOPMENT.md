# Development And Testing

## VS Code workflow

Open this repository as the workspace, then run:

1. `Tasks: Run Task` -> `HA: create venv` once.
2. `Tasks: Run Task` -> `Test: battery telemetry` for the focused unit test.
3. `Tasks: Run Task` -> `HA: run dev instance` for a local HA process.

The run task creates `_devconfig/custom_components/ezviz_plus` as a generated
link to the source component.

## Docker Home Assistant

Current disposable instance:

- Container: `ezviz-plus-ha-dev`
- Image: `ghcr.io/home-assistant/home-assistant:stable`
- Observed HA version: `2026.7.2`
- URL: `http://localhost:8123`
- Local HA username: `test`
- Local HA password: `test`

These credentials are intentionally weak and are valid only for the local,
disposable instance. They are not EZVIZ credentials.

Useful commands:

```bash
docker start ezviz-plus-ha-dev
docker stop ezviz-plus-ha-dev
docker logs -f ezviz-plus-ha-dev
docker logs ezviz-plus-ha-dev 2>&1 | rg -i 'ezviz_plus|pyezvizapi|error|exception|failed'
```

The container mounts `_devconfig` at `/config` and mounts
`custom_components/ezviz_plus` read-only at
`/config/custom_components/ezviz_plus`. Source edits therefore take effect after
a Home Assistant restart:

```bash
docker restart ezviz-plus-ha-dev
```

## Integration test procedure

1. Open Home Assistant and log in with the local credentials above.
2. Open Settings -> Devices & services -> Add integration.
3. Select `EZVIZ Cloud Plus`.
4. Enter EZVIZ credentials directly in Home Assistant. Never write them in docs,
   shell history, fixtures, or source files.
5. Complete MFA in the browser if requested.
6. Open a battery camera and verify the entities listed in
   [BATTERY_TELEMETRY.md](BATTERY_TELEMETRY.md).
7. Check logs for config-flow, dependency, coordinator, or entity errors.

## Automated checks

```bash
python -m ruff check .
pytest -q tests/components/ezviz_plus/test_battery.py
git diff --check
```

`test_config_flow.py` was inherited from the base and imports Home Assistant's
internal `tests.common`; it generally requires a Home Assistant development test
environment rather than only the PyPI package.

GitHub workflows provide Ruff, mypy, focused battery tests, HACS validation, and
hassfest. Local static validation has passed; the full workflow has not run in
the new repository because the remote does not yet exist.
