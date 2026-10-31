# Changelog

## 0.2.0

- Include Remote 3 display support in the existing TiviMuse media player: programme title, channel subtitle and playlist metadata.
- Use TiviMuse programme updates and EPG logos directly, without a separate guide download, webhook or observer.
- Preserve existing entity IDs, pairing settings, controls and stable channel selection.
- Clear inactive display metadata, retain paused/buffering information and restore it after reconnecting.
- Cache fitted logos briefly and reject artwork responses for a channel that is no longer playing.
- Return a proper not-found response for missing or corrupt artwork through the Home Assistant proxy.

Validation covers programme changes on the same channel, artwork fitting/caching and channel-change races, inactive/reconnected state, controls and the real Home Assistant image proxy. Remote hardware verification remains a separate step.
