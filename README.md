# TiviMuse for Home Assistant

A local-push Home Assistant media player for TiviMuse on Android TV. Browse playlists and categories, select an exact channel, display live programme information, and control playback without reading the TV screen.

## Requirements

- Home Assistant 2026.10 or newer and HACS for the custom-repository installation route.
- A compatible TiviMuse companion APK with **local API protocol 1**. The companion APK is built separately; this repository contains the Home Assistant integration.
- Home Assistant and the Android TV device can reach each other on the local network. TiviMuse must be open. Power/wake and launching the app can remain in your existing Android TV Remote integration.

## Install through HACS

1. In HACS, open **Custom repositories**.
2. Add `https://github.com/IainDMC/tivimuse-home-assistant` with type **Integration**.
3. Download **TiviMuse**, then restart Home Assistant.
4. In TiviMuse, open **Settings → Home Assistant → Home Assistant local integration**. Enable local playback control. Note the generated pairing key and local API port (default `42990`).
5. In Home Assistant, choose **Settings → Devices & services → Add integration → TiviMuse**. Enter the TV device hostname/IP, port and pairing key.

Keep the pairing key private. No key, webhook URL, provider login or household address is embedded in this repository or the APK. Local control is off on a fresh installation. App updates retain existing settings and the pairing key. The API runs while TiviMuse is in the foreground; its entity becomes unavailable when the app is closed or backgrounded. Reconfigure the integration if its device address or port changes.

Manual installation: copy `custom_components/tivimuse` into your Home Assistant `custom_components` directory and restart.

## What it provides

- One media-player entity per TiviMuse installation, with playing/paused/buffering/idle state.
- Current channel, playlist, EPG logo, programme title/synopsis/times and next programme.
- Live programme progress; timeshift seek-window progress while behind live.
- Play/pause, relative seek, jump to live, and precise channel selection.
- A paginated media browser grouped by playlist and category, with EPG thumbnails proxied through Home Assistant. Large playlists are not copied into entity attributes on every update.
- Local-push state updates using long polling; automatic reconnect when the app reopens. Normal live position ticks are not written as new HA states.

Standard volume and device power stay with your Shield/Android TV integration. This first version controls live TV, not movies, series, recordings or multiview. Seek commands require a seekable stream or timeshift buffer; unavailable seeking is rejected rather than reported as successful.

## Stable channel IDs

Every playable channel has a device- and playlist-scoped ID based on the provider stream reference. Names, channel numbers, playlist titles, order and internal channel-row IDs are not used for selection.

Two channels named **ABC TV** in different playlists have different IDs. A rename, reorder, normal catalogue refresh or APK update leaves the same channel reference unchanged. Removing and re-adding a playlist creates a new playlist identity. Clearing app data creates a new device identity. If a referenced channel is unavailable, the action fails: it never silently falls back to a similarly named channel.

Choose a channel from the media browser, then copy the media player's `channel_id` attribute for an automation. IDs are machine references; do not construct them from a display label.

```yaml
action: tivimuse.play_channel
target:
  entity_id: media_player.tivimuse
data:
  channel_id: "COPY_THE_EXACT_CHANNEL_ID_HERE"
```

The standard `media_player.play_media` action also accepts `media_content_type: channel` and that ID as `media_content_id`.

```yaml
action: tivimuse.seek_relative
target:
  entity_id: media_player.tivimuse
data:
  seconds: -10
```

Use `tivimuse.jump_live` with the same entity target to return to live. During live playback the progress bar shows programme time and is read-only; use relative seeking to enter timeshift. In timeshift, the standard media seek action uses seconds within the available buffer.

## Remote 3 display (included)

Use the existing **TiviMuse media-player entity** in Remote 3's Home Assistant integration. There is no additional display integration to install and no second pairing step. Existing entity IDs and automations are preserved by this update.

1. Update TiviMuse in HACS and restart Home Assistant.
2. In the Remote 3 configurator, open its Home Assistant integration and add your TiviMuse media-player entity to the remote/activity. If already added, keep that entity.
3. Use that entity for the media display and play/pause controls. Replace the old generic display entity in your activity when ready; it is not removed automatically.

The programme title is the main title; the channel name is the subtitle (`media_artist`). The playlist is also exposed as `media_album_name`. Channel selection uses the existing stable channel IDs, including duplicate names in different playlists.

Channel artwork comes directly from TiviMuse's matched EPG logo through Home Assistant's token-protected media image proxy. It is fitted inside a transparent square with safe margins so wide logos remain complete. A small, five-minute memory cache avoids repeated image downloads. Missing or invalid artwork is omitted; a slow response from a previous channel cannot replace the current channel's artwork.

Programme and next-programme changes are published from TiviMuse's local state connection, even when the channel stays the same. The display does not download XMLTV, inspect the screen, fetch movie posters or infer programme changes independently. Update timing depends on the companion APK sending its revised programme metadata. No separate webhook, observer app or guide credentials are required.

Playing, paused and buffering retain the current information. Stopping clears programme/channel artwork; disconnecting marks the entity unavailable, and reconnecting restores the latest state. Missing programme data falls back to the channel name. Live programme progress and timeshift progress retain their existing meanings.

Remote 3's Home Assistant connection determines which fields and controls appear on its screen. This integration supplies standard Home Assistant media-player fields; it does not replace the remote's firmware or display layout. The remote must be able to reach Home Assistant's configured address to fetch artwork.

The optional legacy webhook reporter may remain enabled for other automations. It is independent of this display path.

## Validation and limitations

The Android companion tests cover stable IDs, duplicate names, persistence, authentication, HTTP limits and listener shutdown. This repository includes real local HTTP client tests and Home Assistant framework tests, plus HACS/hassfest CI validation. A paired device test is still required for each initial installation; passing unit tests alone is not a claim of verified hardware compatibility.

Home Assistant thumbnails depend on the channel's matched EPG artwork. The integration never exports stream URLs or provider passwords. Pairing tokens appear only in authorization headers and HA's stored config entry; diagnostics exclude them and private programme/channel data.

## Development

Run client contract tests with `python -m unittest discover -s tests -p test_client.py`. Run the full Home Assistant tests with the dependencies in `requirements-test.txt` on a supported Python/Linux environment. The workflow validates both repository structure and runtime integration setup.

Licensed under GPL-3.0-or-later. Not affiliated with Unfolded Circle or Home Assistant.
