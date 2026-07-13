# EZVIZ Cloud Plus

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Release](https://img.shields.io/github/v/release/adirgan/ha-ezviz-cloud-plus)](https://github.com/adirgan/ha-ezviz-cloud-plus/releases/latest)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.7.2%2B-18BCF2.svg)](https://www.home-assistant.io/)
[![CI](https://github.com/adirgan/ha-ezviz-cloud-plus/actions/workflows/ci.yaml/badge.svg)](https://github.com/adirgan/ha-ezviz-cloud-plus/actions/workflows/ci.yaml)

[Releases](https://github.com/adirgan/ha-ezviz-cloud-plus/releases) |
[Changelog](CHANGELOG.md) |
[Report an issue](https://github.com/adirgan/ha-ezviz-cloud-plus/issues)

EZVIZ Cloud Plus is a custom Home Assistant integration for EZVIZ cameras. It
combines EZVIZ Cloud access, local RTSP streaming, MQTT events, SD-card
recording playback, and camera controls in one config entry.

The integration is backed by
[adirgan/pyEzvizApi](https://github.com/adirgan/pyEzvizApi) and is designed to
coexist with the official `ezviz` integration and other custom EZVIZ
integrations.

> [!NOTE]
> Install the latest published release through HACS. The `main` branch may
> contain unreleased changes.

| Release | Home Assistant      | HACS             | Status             |
| :------ | :------------------ | :--------------- | :----------------- |
| `0.2.1` | `2026.7.2` or newer | `1.6.0` or newer | Active development |

## Features

| Area                | Capabilities                                                                               |
| :------------------ | :----------------------------------------------------------------------------------------- |
| **Live video**      | Automatic local RTSP or EZVIZ Cloud streaming, H.264 and HEVC support, and cloud snapshots |
| **Recordings**      | SD-card search and browser playback for the last hour, today, or the last seven days       |
| **Events**          | Recent alarm images and MQTT motion/alarm events in Home Assistant                         |
| **Security**        | Account alarm plus independent arm/disarm controls for supported cameras                   |
| **Battery**         | Percentage, charge state, charging source, active charging, classic modes, and AOV modes   |
| **Camera controls** | Motion detection, privacy, tracking, lights, siren, PTZ, and model-specific settings       |
| **Maintenance**     | Firmware information, reboot controls, diagnostics, and connectivity sensors               |

EZVIZ models expose different capability sets. Home Assistant only creates a
control when the camera advertises the corresponding feature, so the exact
entity list varies by model and firmware.

## Media And Streaming

Each camera can use a different source for its current image and live stream.

| Mode          | Behavior                                                      |
| :------------ | :------------------------------------------------------------ |
| **Automatic** | Prefers local RTSP and falls back to EZVIZ Cloud              |
| **Local**     | Connects directly to the camera over RTSP                     |
| **Cloud**     | Streams through the EZVIZ account without local camera access |

Cloud streaming accepts H.264 and HEVC camera video. Compatible streams are
remuxed without re-encoding; HEVC is converted to browser-compatible H.264 when
required. FFmpeg is supplied through Home Assistant's `ffmpeg` integration.

### SD-Card Playback

Open **Media -> EZVIZ Cloud Plus**, then select a camera. The camera directory
contains:

- **Recent alarms** for cloud motion/alarm images.
- **SD recordings - last hour**.
- **SD recordings - today**.
- **SD recordings - last 7 days**.

Recording searches run against the SD card in the camera. Selected recordings
are downloaded through EZVIZ playback and remuxed to fragmented MP4 for browser
playback. Availability depends on camera, account, firmware, and SD-card
support; this is not a cloud-recording subscription browser.

## Camera Arming

Supported cameras receive their own `alarm_control_panel` entity in addition to
the account-level EZVIZ alarm:

- **Arm away** enables motion detection and the corresponding EZVIZ app alarm
  notifications for that camera.
- **Disarm** disables them for that camera only.

The existing motion-detection switch remains available and reflects the same
per-camera state. Arming one camera does not arm or disarm the other cameras on
the account.

## Battery Cameras

Supported battery cameras can expose:

- Battery percentage.
- Charge state, including charging, full, not charging, and fault states.
- Active-charging binary status.
- Charging source, such as power adapter or solar.
- A model-appropriate battery work-mode selector.

Newer cameras advertising AOV capabilities receive the AOV work modes
**Standard**, **Plugged in**, **Super power saving**, **Custom**, and **AOV
mode**. Other compatible cameras retain the classic work-mode choices.

## Installation

### HACS

This repository is not yet included in the default HACS catalog. Add it as a
custom repository:

1. Open **HACS** in Home Assistant.
2. Open the three-dot menu in the top-right corner and select
   **Custom repositories**.
3. Enter `https://github.com/adirgan/ha-ezviz-cloud-plus` as the repository URL.
4. Select **Integration** as the category and click **Add**.
5. Open **EZVIZ Cloud Plus** in HACS and select **Download**.
6. Select the latest release and complete the download.
7. Restart Home Assistant.

HACS installs the integration under `custom_components/ezviz_plus`. A Home
Assistant restart is required after the first installation and after updates.

### Add The Integration

After restarting Home Assistant:

1. Open **Settings -> Devices & services -> Add integration**.
2. Search for **EZVIZ Cloud Plus**.
3. Sign in with your EZVIZ account.
4. Complete the one-time verification prompt if EZVIZ requests it.

### EZVIZ Account

1. [Register an EZVIZ account](https://i.ezvizlife.com/user/userAction!goRegister.action).
2. Keep your EZVIZ username available for the Home Assistant setup flow.
3. Confirm that you can [sign in to EZVIZ](https://euauth.ezvizlife.com/signIn).
4. Add and manage cameras in the EZVIZ app before adding the integration.

## Configuration

The integration logs into **EZVIZ Cloud**, subscribes to **MQTT** events, and
stores media and credential settings independently for every camera.

All per-camera settings live under the cloud entry's **Options**. Legacy
per-camera entries are migrated automatically.

### Per-Camera Options

Open **Settings -> Devices & services -> EZVIZ Cloud Plus -> Configure**, choose
**Camera Settings**, and select a camera.

| Option                       | Purpose                                                             |
| :--------------------------- | :------------------------------------------------------------------ |
| **Media source preferences** | Selects Automatic, Local, or Cloud access for images and live video |
| **Cloud images**             | Stores or retrieves the key used for encrypted cloud media          |
| **Local live video (RTSP)**  | Configures local credentials, authentication mode, and stream path  |

### RTSP Settings

| Field                        | Description                                                                                                 |
| :--------------------------- | :---------------------------------------------------------------------------------------------------------- |
| **Camera username**          | Local RTSP username, commonly `admin`                                                                       |
| **RTSP path**                | `/Streaming/Channels/101` for the main stream or `/Streaming/Channels/102` for the lower-bitrate sub-stream |
| **Use verification code**    | Enables VC authentication; disable it to use the encryption key                                             |
| **Verification code**        | Code printed on the camera or NVR label                                                                     |
| **Encryption key**           | Device key used when media encryption is enabled                                                            |
| **Validate credentials now** | Tests the entered RTSP values once without saving the checkbox                                              |

> **Tip:** If you don’t know the VC or ENC, keep the default **`fetch_my_key`** value. The integration will fetch it from EZVIZ (you may be prompted for a one-time 2FA).

### Stored Values

- Per-camera settings are stored under the cloud entry’s **Options**.
- The **RTSP Path**, **auth mode** (VC vs ENC), and whichever secret you used (VC or ENC) are saved per camera.
- The **Validate** checkbox is **not** saved; it only runs a one-time check at submit time.

### VC And ENC Authentication

| Mode    | RTSP password            | When to use it                                                           |
| :------ | :----------------------- | :----------------------------------------------------------------------- |
| **VC**  | Camera verification code | Default choice; the code is printed on the device label                  |
| **ENC** | Device encryption key    | Use when encryption is enabled and the camera expects the encryption key |

You can switch modes at any time with the toggle. After you save, entities reload to use the new settings.

### One-Time Verification

When fetching VC or ENC from the cloud (because you left `fetch_my_key`), EZVIZ may require a **one-time 2FA**:

1. You’ll be prompted for a **Verification Code 2FA** (for VC fetch) or **Encryption Key 2FA** (for ENC fetch).
2. Enter the code you received; the integration fetches the value and returns to the edit form **prefilled** with the resolved secret.
3. Click **Submit** to save.

If validation fails (auth or connectivity), the form reopens with the **best-known values** so you can adjust and try again.

### RTSP Examples

**Typical main stream RTSP URL (VC mode):**
`rtsp://<username>:<verification_code>@<camera-ip>:554/Streaming/Channels/101`

**Typical sub-stream RTSP URL (ENC mode):**
`rtsp://<username>:<encryption_key>@<camera-ip>:554/Streaming/Channels/102`

> Only the **path** (`/Streaming/Channels/101` or `/Streaming/Channels/102`) is configured in Options; the integration composes the full URL for you.

## Troubleshooting

| Problem                             | Checks                                                                                          |
| :---------------------------------- | :---------------------------------------------------------------------------------------------- |
| **RTSP validation fails**           | Verify VC/ENC mode, try channel `101` or `102`, and confirm Home Assistant can reach port `554` |
| **Repeated verification prompts**   | Request a fresh code and use the code for the operation currently shown                         |
| **No events or updates**            | Reconfigure the cloud login and restart the camera if MQTT appears stuck                        |
| **Cloud stream does not start**     | Select Automatic or Cloud, configure the encryption key, and inspect FFmpeg logs                |
| **SD folder is empty**              | Confirm SD recording is enabled and try a wider time window                                     |
| **Camera alarm is missing**         | The camera must advertise individual defence support; reload after firmware changes             |
| **Arm/disarm takes time to settle** | The optimistic state is reconciled during the next coordinator update                           |

## Security And Privacy

- EZVIZ account tokens and per-camera credentials are stored in Home
  Assistant's config entry and options storage.
- Do not include diagnostics containing identifiers or credentials in public
  issue reports without reviewing them first.
- Local RTSP keeps live video on the local network after authentication. Cloud
  images, cloud live video, events, and SD playback communicate with EZVIZ.
- Media playback endpoints created by the integration use unguessable local
  access tokens and are not intended to be exposed directly.

## Migration

- Legacy per-camera config entries are merged into the cloud entry’s **Options**.
- Ignored legacy entries (`version < 4`) are cleaned up automatically.
- Entity identifiers are preserved.
