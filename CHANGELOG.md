# Changelog

All notable changes to EZVIZ Cloud Plus are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Prevented partial EZVIZ camera responses from publishing synchronized
  transient `unknown`, `idle`, false, or default work-mode states.
- Serialized shared API-client access, detached mutable upstream snapshots, and
  reused in-flight polling work after timeout.
- Recover from a polling request that remains blocked by isolating its client
  after two consecutive timeouts, allowing later refreshes and commands to use
  a fresh session instead of waiting indefinitely on the old client lock.
- Allow integration unload and Home Assistant shutdown to proceed without
  waiting forever for executor work that Python cannot cancel.
- Made MQTT and optimistic camera updates copy-on-write and health-aware.
- Removed the extra cloud request previously made while collecting diagnostics.

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

[Unreleased]: https://github.com/adirgan/ha-ezviz-cloud-plus/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/adirgan/ha-ezviz-cloud-plus/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/adirgan/ha-ezviz-cloud-plus/compare/bb8ccd7...v0.2.0
[0.1.0]: https://github.com/adirgan/ha-ezviz-cloud-plus/tree/bb8ccd7
