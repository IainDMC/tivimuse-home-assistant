# Changelog

## 0.3.0

- Add an optional single Remote 3 display for TiviMuse, Nuvio and SmartTube, with foreground-app switching and app-specific controls.
- Keep the combined display available for Nuvio/SmartTube while TiviMuse is closed.
- Preserve optional TMDB posters, source artwork, app logos, fitted posters and blurred backgrounds for Nuvio/SmartTube. TiviMuse uses only its own programme data and logos.
- Suggest compatible settings from one existing legacy display entry privately, without importing guide feeds or observer configuration.
- Reject stale cross-app metadata and artwork when foreground/source updates arrive out of order.
- Keep existing native media-player identities, pairing and automations intact.

## 0.2.0

- Include Remote 3 display support in the existing TiviMuse media player: programme title, channel subtitle and playlist metadata.
- Use TiviMuse programme updates and EPG logos directly, without a separate guide download, webhook or observer.
- Preserve existing entity IDs, pairing settings, controls and stable channel selection.
- Clear inactive display metadata, retain paused/buffering information and restore it after reconnecting.
- Cache fitted logos briefly and reject artwork responses for a channel that is no longer playing.
- Return a proper not-found response for missing or corrupt artwork through the Home Assistant proxy.

Validation covers programme changes on the same channel, artwork fitting/caching and channel-change races, inactive/reconnected state, controls and the real Home Assistant image proxy. Remote hardware verification remains a separate step.
