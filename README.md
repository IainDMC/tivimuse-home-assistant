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

The native TiviMuse media player supplies programme titles, channel subtitles (`media_artist`), playlist information, current/next programmes, progress and logos directly from TiviMuse. It requires no guide download, webhook or screen observer. Existing entity IDs, settings and automations are preserved.

### One display for TiviMuse, Nuvio and SmartTube

1. Update **TiviMuse** in HACS and restart Home Assistant.
2. Open **Settings → Devices & services → TiviMuse → Configure**. Enable **Combined Remote 3 display**.
3. Choose the Shield's playback metadata media player and its foreground-app media player (usually the Android TV/ADB entity). These are the underlying Shield entities, not a TiviMuse entity or the old display entity. They may be the same entity if it provides both functions.
4. If exactly one old Remote 3 Display config entry exists, compatible source/artwork settings are suggested privately, including its optional TMDB token. Check these before saving. No XMLTV URLs, provider logins or observer settings are copied.
5. Add the new **TiviMuse Remote 3 display** media player to Remote 3 through its Home Assistant integration. Use it for the display and playback controls in your activity. The original TiviMuse media player remains available for automations and exact channel selection.
6. After testing all three apps, disable/remove the old display integration yourself if you no longer need it. It is not altered automatically.

The foreground app selects the display. TiviMuse supplies its own current programme and matched EPG logo. Nuvio and SmartTube retain the playback source's title, subtitle, progress and controls, with per-app primary/fallback artwork choices: source artwork, optional TMDB movie/show posters, or an app logo. Nuvio movie/episode/trailer classification is exposed as an attribute. Poster fitting, optional blurred backgrounds, canvas width and title-match threshold are configurable. TMDB searches are disabled by default unless explicitly enabled or reused from your existing settings, and are never used for TiviMuse.

The combined display continues working for Nuvio and SmartTube when TiviMuse is closed or unreachable. When foreground and media metadata arrive at different times, mismatched old titles/artwork are cleared until the new app's metadata arrives. Turning off/unavailable foreground detection clears the display. A source without an identifiable matching app is not treated as current media.

Media controls target the selected app's source. TiviMuse channel actions always use the exact stable channel ID. Power/wake and volume for TiviMuse remain on the existing Shield/Android TV integration. This integration does not launch closed apps automatically.

### Device-page controls

The TiviMuse device page includes the combined display's configuration entities:

- Switches for TiviMuse detection, programme title, channel name, progress, next programme, blurred posters and TMDB artwork.
- Per-app preferred/fallback artwork selectors, plus channel-icon canvas shape and background.
- Sliders for channel-icon size, poster-canvas width and TMDB title matching.
- Refresh TiviMuse data, clear artwork cache and test-artwork buttons.
- Diagnostic sensors for the active app, selected artwork source, Nuvio content type and native connection.

Presentation changes apply live and persist without reloading the native connection. Power, volume, mute and volume-step commands use the Shield source even during TiviMuse playback; supported play/pause/seek controls use TiviMuse's API. Nuvio/SmartTube retain their source player's stop, skip, seek and playback controls.

The old XMLTV download, playlist matching and screen-observer settings are intentionally replaced by the native TiviMuse connection. They are not needed to supply programme information or logos.

**Remote 3 must use the new combined entity.** Updating HACS does not replace an old activity's selected entity automatically. Add/select the TiviMuse Remote 3 display in the remote's Home Assistant integration and activity; selecting the Shield's ordinary TV Room player still displays only that source's information. Keep the original native TiviMuse entity for channel-selection automations.

### Artwork and updates

Logos come from TiviMuse through Home Assistant's token-protected media image proxy. They are fitted inside a transparent square with safe margins. A five-minute memory cache avoids repeated logo downloads; slow old-channel responses cannot replace the current logo. Posters are loaded on media changes, not position ticks. Failed artwork falls back to the next configured choice.

Programme updates arrive whenever TiviMuse publishes changed metadata, including changes on the same channel. Timing depends on the installed companion APK. The display does not independently infer programme changes or download a guide.

Remote 3's Home Assistant connection determines the on-screen layout and supported controls. This integration supplies standard media-player fields; it does not replace the remote's firmware. Remote 3 must be able to reach Home Assistant's configured address to fetch artwork. Optional app-logo URLs support HTTP(S) or Home Assistant `/local/` paths.

The optional legacy webhook reporter can remain enabled for other automations. It is independent of this display path.

## Validation and limitations

The Android companion tests cover stable IDs, duplicate names, persistence, authentication, HTTP limits and listener shutdown. This repository includes real local HTTP client tests and Home Assistant framework tests, plus HACS/hassfest CI validation. A paired device test is still required for each initial installation; passing unit tests alone is not a claim of verified hardware compatibility.

Home Assistant thumbnails depend on the channel's matched EPG artwork. The integration never exports stream URLs or provider passwords. Pairing tokens appear only in authorization headers and HA's stored config entry; diagnostics exclude them and private programme/channel data.

## Development

Run client contract tests with `python -m unittest discover -s tests -p test_client.py`. Run the full Home Assistant tests with the dependencies in `requirements-test.txt` on a supported Python/Linux environment. The workflow validates both repository structure and runtime integration setup.

Licensed under GPL-3.0-or-later. Not affiliated with Unfolded Circle or Home Assistant.

### Generic Remote 3 metadata sources

A selected media source without an Android `app_id` is supported; the separate foreground-app entity identifies Nuvio or SmartTube. Explicitly conflicting app IDs are still rejected. If using the Unfolded Circle media-player facade as the source, set its sound mode to the native Android TV media player rather than Automatic selection or the display itself. This prevents the facade from feeding the combined display back into itself.

To preserve existing Remote 3 activity assignments when replacing a removed legacy display, the new combined entity can be assigned the old entity ID in Home Assistant, provided that ID is free. Do not overwrite a still-registered legacy entity.
