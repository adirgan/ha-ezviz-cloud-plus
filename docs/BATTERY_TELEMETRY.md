# Battery Telemetry

## Authoritative payload

Battery state is read from:

```text
FEATURE_INFO.<channel>.Video.PowerMgr.BatteryDetails[0]
```

Observed detail fields include:

```json
{
  "chargingType": 0,
  "remain": 68,
  "type": 3,
  "status": 1
}
```

`FEATURE_INFO` channel keys vary, so traversal uses `WILDCARD_STEP` and
`first_nested`. API fields may be integers or numeric strings.

## Status semantics

| `status` | Entity state   | Meaning                       |
| -------: | -------------- | ----------------------------- |
|        0 | `not_charging` | Battery present, not charging |
|        1 | `charging`     | Actively charging             |
|        2 | `full`         | Fully charged                 |
|        3 | `no_battery`   | No battery                    |
|        4 | `fault`        | Damaged/faulty battery        |

Charging source:

| `chargingType` | Entity state    |
| -------------: | --------------- |
|              0 | `power_adapter` |
|              1 | `solar`         |

`chargingType` describes the source, not whether charging is active.

## Home Assistant entities

- `sensor.*_battery_level`: existing percentage sensor.
- `sensor.*_battery_charge_state`: diagnostic enum-like state.
- `binary_sensor.*_battery_charging`: `BATTERY_CHARGING` device class.
- `sensor.*_battery_charging_source`: diagnostic source state.

Entities are gated by support capability `SupportBatteryManage` value `"1"`
and by the presence of usable telemetry.

## Compatibility behavior

`battery_charge_status()` prioritizes `BatteryDetails.status`. It falls back to
`optionals.powerStatus` for older payloads. This fallback must keep using
`coerce_int` because EZVIZ commonly returns values such as `"1"`.

## Battery work modes

Cameras advertising `SupportExt.SupportNewWorkMode` capability 687 with the AOV
work-mode tokens use the new table:

| API value | Entity option      |
| --------: | ------------------ |
|         1 | `standard`         |
|         2 | `plugged_in`       |
|         3 | `super_power_save` |
|         4 | `custom`           |
|         7 | `aov_mode`         |

Capability tokens are compared without depending on order or whitespace, and
additional tokens are allowed. A compatible 687 capability takes precedence
over the legacy `SupportWorkModeList` capability 502 so only one work-mode
select is created. Cameras that advertise only a compatible 502 capability keep
the classic work-mode table.

## Verified devices

During initial investigation, both test cameras exposed support capability 119
as `"1"` and reported active adapter charging:

- Test camera A: 68%, `status=1`, `chargingType=0`.
- Test camera B: 94%, `status=1`, `chargingType=0`.

Do not add account credentials, device keys, cloud tokens, or MFA values to
fixtures or documentation.
