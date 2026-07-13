# Documentation Index

This directory is the project handoff for maintainers and coding agents.

| Document                                     | Purpose                                                |
| -------------------------------------------- | ------------------------------------------------------ |
| [ARCHITECTURE.md](ARCHITECTURE.md)           | Integration lifecycle, modules, and data flow          |
| [BATTERY_TELEMETRY.md](BATTERY_TELEMETRY.md) | EZVIZ battery payload and Home Assistant entities      |
| [DEVELOPMENT.md](DEVELOPMENT.md)             | Local setup, Docker, tests, logs, and validation       |
| [HANDOFF.md](HANDOFF.md)                     | Exact current state, validated behavior, and next work |

## Repository layout

```text
.
|-- AGENT.md
|-- AGENTS.md
|-- custom_components/
|   `-- ezviz_plus/
|       |-- __init__.py
|       |-- config_flow.py
|       |-- coordinator.py
|       |-- entity.py
|       |-- utility.py
|       |-- manifest.json
|       `-- <Home Assistant platforms>.py
|-- docs/
|-- tests/components/ezviz_plus/
|-- _devconfig/
|-- .devcontainer/
|-- .github/workflows/
`-- .vscode/
```

`_devconfig` is a disposable Home Assistant configuration. Only its intentional
configuration files belong in Git; databases, `.storage`, logs, tokens, and
generated links are ignored.
