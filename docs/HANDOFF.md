# Current Handoff

Last updated: 2026-08-17.

## Completed

- Stabilized the full coordinator state machine against synchronized partial
  EZVIZ responses observed across two cameras. Missing raw structure now retains
  each camera's last complete snapshot instead of publishing synthesized
  `unknown`, `idle`, `False`, or `standard` values.
- Serialized all runtime calls to the shared `pyEzvizApi` client through a
  transparent coordinator proxy and deep-copied `load_cameras()` results while
  holding its lock.
- Added bounded stale-data health: one transient failure is retained; camera
  availability expires on the second failure or after 75 seconds.
- Added two-snapshot confirmation for changed recovery values after degradation,
  while authentication failures and explicit offline status remain immediate.
- Converted MQTT and individual defence optimistic updates to copy-on-write and
  synchronized them with the reconciler.
- Preserved timed-out executor work for the next refresh and observe any active
  load during coordinator shutdown.
- Removed the additional cloud request from diagnostics and exposed only the
  redacted coordinator snapshot plus sanitized health metadata.
- Added focused regression coverage in
  `tests/components/ezviz_plus/test_coordinator_transient.py`, including the
  observed `custom -> partial -> standard -> standard` work-mode sequence.

- Cloned `RenierM26/ha-ezviz` at upstream tag `0.2.0.24`.
- Renamed integration directory and domain from `ezviz_cloud` to `ezviz_plus`.
- Updated manifest, HACS metadata, code references, tests, translations, README,
  API routes, and service selectors for the new domain.
- Set product name to `EZVIZ Cloud Plus` and version to `0.2.0`.
- Pinned the manifest to the `adirgan/pyEzvizApi` fork commit documented in
  [ARCHITECTURE.md](ARCHITECTURE.md).
- Added normalized battery detail/status/source helpers.
- Added charge-state and charging-source sensors.
- Added a battery-charging binary sensor.
- Added focused battery helper tests using an observed payload shape.
- Added mutually exclusive classic/AOV battery work-mode selectors. Compatible
  capability 687 uses the 1/2/3/4/7 AOV table and takes precedence over legacy
  capability 502.
- Added focused select tests for capability variants, current values, and mocked
  AOV writes.
- Persisted the regional API host returned by EZVIZ login and reauthentication
  instead of retaining the initially selected host.
- Added focused tests for regional-host normalization, redirect, and fallback.
- Added VS Code tasks and a disposable Docker Home Assistant setup.
- Created the public GitHub repository at
  `https://github.com/adirgan/ha-ezviz-cloud-plus`.
- Committed and pushed the initial `ezviz_plus` integration to `main`.
- Configured Git remotes:
  - `origin`: `https://github.com/adirgan/ha-ezviz-cloud-plus.git`
  - `upstream`: `https://github.com/RenierM26/ha-ezviz.git`

## Validated

- Transient coordinator, diagnostics, and alarm copy-on-write tests pass in the
  repository `.venv` on Python 3.14.6.

- `python -m ruff check .` passes.
- JSON metadata and translation files parse.
- The component compiles.
- Battery helpers pass isolated behavior checks and the focused fixture captures
  authoritative `BatteryDetails.status` precedence.
- Battery work-mode select tests pass for AOV and classic capability payloads,
  including mixed-type current values and AOV value 7 writes.
- Home Assistant `2026.7.2` starts in Docker on port 8123.
- HA discovers `ezviz_plus` as a custom integration without startup errors.
- Docker instance onboarding is complete.
- Login, coordinator refresh, MQTT startup, and platform setup complete against
  the API host returned by EZVIZ.
- The coordinator discovers both test cameras and HA registers 113 integration
  entities, including two camera entities.
- Both cameras expose one active AOV work-mode selector and no classic
  work-mode selector. The UI shows Standard, Plugged in, Super power saving,
  Custom, and AOV mode; no real camera mode was changed during validation.
- GitHub CI, HACS, and hassfest checks pass on the published baseline.
- `EzvizClient.save_image()` was validated against a real configured camera. It
  returned a JPEG capture through `BytesIO`; the camera entity now uses this
  high-level helper instead of manually combining `capture_picture()` and
  `download_alarm_image()`.
- Per-camera image routing was checked in the Docker Home Assistant runtime:
  local-only does not call cloud, cloud-only skips RTSP, and automatic falls
  back to cloud when RTSP returns no frame.
- Cloud live-video capture is implemented inside the integration, without
  modifying `pyEzvizApi`. `cloud_video.py` uses the API's existing
  `open_cloud_stream()` plus stream helpers to detect RTP, select the video
  payload type, discard audio/control tracks, rebuild H.264/HEVC Annex-B,
  optionally decrypt using the per-camera media key, and remux through FFmpeg's
  elementary input format.
- Cloud live-video proxying now uses a continuous pipe instead of repeated
  bounded captures. `CloudMpegtsStream` keeps one VTM cloud session and one
  FFmpeg process open per HA stream-worker connection, feeds depacketized
  Annex-B video into FFmpeg stdin, and streams H.264 MPEG-TS chunks from FFmpeg
  stdout to Home Assistant.
- The integration-level cloud capture helper was tested against both configured
  real cameras using the installed API package. `Entrada Parcelas` produced clear
  HEVC MPEG-TS and `Entrada Casa` produced decrypted HEVC MPEG-TS; `ffprobe`
  reported valid video streams for both.
- Added an SD-card playback MVP through Home Assistant Media Source. Per-camera
  media browsing now exposes recent alarm images plus SD recording windows, and
  SD recording items resolve to a token-protected local playback endpoint.
- SD record search uses `search_records_v2()` with `YYYY-MM-DDTHH:MM:SS` search
  times and normalizes real `B`/`E` records through `extract_record_list()`.
  Playback downloads through `save_clip(source="cloud-playback",
output_format="mpegps")`, then remuxes MPEG-PS to fragmented MP4 with FFmpeg
  for browser playback. The MP4 remux copies both streams and applies
  `aac_adtstoasc` so EZVIZ AAC/ADTS audio is valid inside MP4.
- Docker smoke against `Entrada Parcelas` confirmed `search_records_v2()` returns
  SD records with `B`, `E`, and `Type` fields. Do real camera tests with
  `Entrada Parcelas`; avoid `Entrada Casa` because its battery is low.
- Docker and Home Assistant Media Browser playback were validated against the
  eight-second `Entrada Parcelas` segment from 22:41:20 to 22:41:28. The browser
  loaded a 3840x2160 MP4, reached ready state 4, played through 8.066 seconds,
  and ended without a media error. A VTM socket close after receiving clear
  media is treated as normal completion only when FFmpeg validates the result;
  encrypted or empty responses remain errors.
- Focused SD tests pass (22 tests), as do the focused battery tests, Ruff, mypy,
  and `git diff --check`.

## Not yet validated

- The three new battery entities have not yet been inspected in Home Assistant.
- Full inherited config-flow tests have not been run in HA's complete test suite.
- The Home Assistant cloud-stream proxy endpoint has been exercised through
  HA's `camera/stream` WebSocket command after a Docker restart. HA created HLS
  for `camera.entrada_parcelas` from the continuous pipe with
  `CODECS="avc1.42c01f"`, 1-second LL-HLS parts, and no new stream-worker or
  FFmpeg errors in the HA logs. The same dashboard path still needs visual
  confirmation by watching Lovelace playback.
- Encrypted SD playback has not been tested against `Entrada Casa`; continue to
  avoid real tests on that camera while its battery is low.

The standalone repository cannot collect the inherited config-flow suite because
its imports expect Home Assistant's source-test layout (`config` and
`tests.common`). Focused region tests cover the new host-selection helper.

## Regional redirect fix

EZVIZ redirected the initial Europe login from `apiieu.ezvizlife.com` to
`apiisa.ezvizlife.com`. Keeping the selected Europe host produced successful but
empty resource responses, so only the account-level alarm entity appeared. With
the returned host, the same session discovers two cameras and four resources.
Initial login, MFA, reauthentication, and reauthentication MFA now persist the
host returned in `token["api_url"]`, with the selected host as fallback.

## Immediate next steps

1. Verify stable state history in Home Assistant over multiple polling cycles.
2. Verify battery state, binary charging, and charging source on both cameras.
3. Visually confirm the already functional cloud live stream in Lovelace.
4. Run CI, HACS, and hassfest checks before the next release.

## Working-tree status

The domain rename and initial battery telemetry work are committed on `main`.
Do not restore the deleted old-domain files or reintroduce `ezviz_cloud`.

## Security note

`_devconfig/.storage`, databases, logs, and generated runtime files are ignored.
They can contain HA auth data or EZVIZ tokens. The local HA credentials
`test` / `test` may be documented because the user explicitly approved them for
this disposable instance. This exception does not apply to any EZVIZ secret.
