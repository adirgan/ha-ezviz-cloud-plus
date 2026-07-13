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

## Required validation

Run the narrowest relevant test first, then:

```bash
python -m ruff check .
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
