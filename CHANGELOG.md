# Changelog

All notable changes to EZVIZ Cloud Plus are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Synchronized release automation and agent instructions so manifest, changelog,
  README/HACS metadata, release tags, and archives report the same version.

## [0.2.7] - 2026-08-17

### Fixed

- Prevented rotating signed alarm-image URLs from blocking two-snapshot
  recovery and leaving functional values such as battery level stale until an
  integration reload.
- Attached the alarm timestamp to alarm-type sensor state so repeated alarms of
  the same type are recorded as fresh Home Assistant activity.

## [0.2.6] - 2026-08-17

### Fixed

- Handled raw `requests` transport failures without noisy Home Assistant update
  errors and bounded account-alarm polling below the slow-update threshold.
- Removed signed image URLs, camera serials, and raw cloud failure details from
  runtime logs and made cloud-video process cleanup nonblocking.
- Made camera previews resilient to slow or transient cloud captures with
  bounded retries, a shared background refresh that survives proxy-request
  cancellation, and a battery-conscious five-minute last-valid-image cache.

## [0.2.5] - 2026-08-17

### Fixed

- Recovered from polling requests that remain blocked by isolating the stalled
  client after two consecutive timeouts, allowing later refreshes and commands
  to use a fresh session instead of waiting indefinitely on the old lock.
- Allowed integration unload and Home Assistant shutdown to proceed without
  waiting forever for executor work that Python cannot cancel.

## [0.2.4] - 2026-08-17

### Fixed

- Prevented partial EZVIZ camera responses from publishing synchronized
  transient `unknown`, `idle`, false, or default work-mode states.
- Serialized shared API-client access, detached mutable upstream snapshots, and
  reused in-flight polling work after timeout.
- Made MQTT and optimistic camera updates copy-on-write and health-aware.
- Removed the extra cloud request previously made while collecting diagnostics.
- Retained published entity values and Recorder continuity during transient
  cloud-health expiry; explicit EZVIZ offline status remains immediate.

## [0.2.3] - 2026-08-17

### Changed

- Updated the GitHub Actions Python setup action from version 6 to version 7.

## [0.2.2] - 2026-07-13

### Changed

- Enabled automatic patch releases for every validated push to `main`.

## [0.2.1] - 2026-07-13

### Changed

- Reorganized the HACS README into compact feature, configuration, RTSP, and
  troubleshooting tables with a consistent heading hierarchy.
- Replaced HACS-sensitive HTML branding markup with standard GitHub Markdown.
- Clarified release-based installation, account setup, per-camera options, and
  VC/ENC authentication.

## [0.2.0] - 2026-07-13

### Added

- Continuous EZVIZ Cloud live streaming for H.264 and HEVC cameras, including
  encrypted media support and browser-compatible H.264 output when required.
- Per-camera media routing for current images and live video, with Automatic,
  Local RTSP, and EZVIZ Cloud source preferences.
- Home Assistant Media Browser directories for recent alarm images and SD-card
  recordings from the last hour, today, or the last seven days.
- Browser playback for SD-card recordings through token-protected local
  endpoints and fragmented MP4 remuxing with audio support.
- Individual alarm control panels for supported cameras. Arm away and Disarm
  control motion detection and EZVIZ app notifications per camera.
- Battery charge-state, active-charging, and charging-source entities.
- AOV battery work modes for cameras advertising the newer work-mode
  capability, while retaining classic modes for older cameras.
- Regional API host persistence after login, MFA, and reauthentication.
- HACS and Home Assistant branding assets.

### Changed

- Improved the README with current streaming, playback, battery, alarm,
  configuration, troubleshooting, and privacy documentation.
- Empty or unsupported SD recording searches now produce an empty media folder
  instead of a playback error.
- Camera work-mode writes publish an optimistic state while the cloud update is
  reconciled.
- CI now installs Home Assistant's FFmpeg Python dependency and runs focused
  per-camera alarm tests.
- Minimum supported Home Assistant version is now `2026.7.2`, the version used
  for runtime validation of this release.

### Compatibility

- Tested with Home Assistant `2026.7.2`.
- Requires HACS `1.6.0` or newer when installed through HACS.

## [0.1.0] - 2026-07-13

### Added

- Initial EZVIZ Cloud Plus integration based on the upstream EZVIZ integration.
- Separate `ezviz_plus` domain, config-entry migration, cloud polling, MQTT
  events, local RTSP configuration, and capability-gated camera entities.

[Unreleased]: https://github.com/adirgan/ha-ezviz-cloud-plus/compare/v0.2.7...HEAD
[0.2.7]: https://github.com/adirgan/ha-ezviz-cloud-plus/compare/v0.2.6...v0.2.7
[0.2.6]: https://github.com/adirgan/ha-ezviz-cloud-plus/compare/v0.2.5...v0.2.6
[0.2.5]: https://github.com/adirgan/ha-ezviz-cloud-plus/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/adirgan/ha-ezviz-cloud-plus/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/adirgan/ha-ezviz-cloud-plus/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/adirgan/ha-ezviz-cloud-plus/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/adirgan/ha-ezviz-cloud-plus/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/adirgan/ha-ezviz-cloud-plus/compare/bb8ccd7...v0.2.0
[0.1.0]: https://github.com/adirgan/ha-ezviz-cloud-plus/tree/bb8ccd7
