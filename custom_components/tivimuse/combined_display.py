"""One Remote 3 display, selected by the Shield's foreground application."""

from __future__ import annotations

import hashlib
from urllib.parse import urljoin

import aiohttp
from homeassistant.components.media_player import MediaPlayerEntity, MediaPlayerEntityFeature
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .display_artwork import app_kind, fetch_artwork, fit_poster, nuvio_type, tmdb_poster

ACTIVE = {"playing", "paused", "buffering"}
FORWARDED = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
)


class TiviMuseRemoteDisplay(MediaPlayerEntity):
    _attr_has_entity_name = True
    _attr_name = "Remote 3 display"
    _attr_should_poll = False
    _attr_media_image_remotely_accessible = False

    def __init__(self, native, entry):
        self.native = native
        self.options = entry.options
        self._source_id = self.options["source_entity"]
        self._app_id = self.options["app_entity"]
        self._attr_unique_id = f"{entry.unique_id}_remote3_display"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.unique_id)}}
        self._art_task = None
        self._art_key = None
        self._art_image = None
        self._image_revision = 0

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._source_id, self._app_id],
                self._changed,
            )
        )
        self.async_on_remove(self.native.coordinator.async_add_listener(self._changed))
        self.async_on_remove(self._cancel_artwork)
        self._changed()

    def _cancel_artwork(self):
        if self._art_task:
            self._art_task.cancel()
            self._art_task = None

    @property
    def _foreground(self):
        state = self.hass.states.get(self._app_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, "off"):
            return None
        return state

    @property
    def _kind(self):
        state = self._foreground
        if not state:
            return None
        # Foreground identity is authoritative; do not let a stale media title choose the app.
        attrs = state.attributes
        identity = attrs.get("app_id") or attrs.get("source") or attrs.get("app_name")
        return app_kind(identity)

    @property
    def _source(self):
        state = self.hass.states.get(self._source_id)
        if not state or state.state not in ACTIVE or self._kind not in ("nuvio", "smarttube"):
            return None
        identity = state.attributes.get("app_id") or state.attributes.get("app_name")
        if app_kind(identity) != self._kind:
            return None
        return state

    def _attribute(self, name):
        if self._kind == "tivimuse":
            return getattr(self.native, name, None) if self.native.available else None
        source = self._source
        return source.attributes.get(name) if source else None

    @property
    def available(self):
        if not self._foreground:
            return False
        return self.native.available if self._kind == "tivimuse" else True

    @property
    def state(self):
        if self._kind == "tivimuse":
            return self.native.state
        return self._source.state if self._source else "idle"

    @property
    def app_id(self):
        state = self._foreground
        return state.attributes.get("app_id") or state.attributes.get("source") if state else None

    @property
    def app_name(self):
        return {"tivimuse": "TiviMuse", "nuvio": "Nuvio", "smarttube": "SmartTube"}.get(self._kind)

    @property
    def media_title(self):
        return self._attribute("media_title")

    @property
    def media_artist(self):
        return self._attribute("media_artist")

    @property
    def media_album_name(self):
        return self._attribute("media_album_name")

    @property
    def media_content_id(self):
        return self._attribute("media_content_id")

    @property
    def media_content_type(self):
        return self._attribute("media_content_type")

    @property
    def media_duration(self):
        return self._attribute("media_duration")

    @property
    def media_position(self):
        return self._attribute("media_position")

    @property
    def media_position_updated_at(self):
        value = self._attribute("media_position_updated_at")
        return dt_util.parse_datetime(value) if isinstance(value, str) else value

    @property
    def volume_level(self):
        return self._attribute("volume_level")

    @property
    def is_volume_muted(self):
        return self._attribute("is_volume_muted")

    @property
    def supported_features(self):
        if not self.available:
            return MediaPlayerEntityFeature(0)
        if self._kind == "tivimuse":
            return self.native.supported_features
        return MediaPlayerEntityFeature(self._attribute("supported_features") or 0) & FORWARDED

    @property
    def extra_state_attributes(self):
        if self._kind == "tivimuse" and self.available:
            return {**self.native.extra_state_attributes, "display_app": "TiviMuse"}
        return {
            "display_app": self.app_name,
            "nuvio_content_type": nuvio_type(self._source.attributes)
            if self._kind == "nuvio" and self._source
            else None,
        }

    def _artwork_key(self):
        source = self._source
        if not source:
            return (
                (self._kind, None, None, None, None, "Unknown")
                if self._kind in ("nuvio", "smarttube")
                else None
            )
        return (
            self._kind,
            self.media_title,
            self.media_content_id,
            source.attributes.get("entity_picture"),
            source.attributes.get("media_series_title"),
            nuvio_type(source.attributes) if self._kind == "nuvio" else "Unknown",
        )

    @callback
    def _changed(self, event=None):
        key = self._artwork_key()
        if key != self._art_key:
            self._cancel_artwork()
            self._art_key = key
            self._art_image = None
            self._image_revision += 1
            if key:
                self._art_task = self.hass.async_create_background_task(
                    self._load_artwork(key),
                    "TiviMuse Remote 3 artwork",
                )
        self.async_write_ha_state()

    async def _load_artwork(self, key):
        """Resolve artwork once per media change, never on playback-position ticks."""
        session = async_get_clientsession(self.hass)
        kind = key[0]
        primary = self.options.get(f"{kind}_artwork", "tmdb_poster")
        fallback = self.options.get(f"{kind}_fallback_artwork", "source_artwork")
        result = None, None
        for choice in dict.fromkeys((primary, fallback)):
            data = None
            if choice == "tmdb_poster" and self.options.get("tmdb_enabled"):
                # Live TV cannot enter this path: _artwork_key requires Nuvio/SmartTube.
                title = key[4] if key[5] == "Episode" and key[4] else key[1]
                url = await tmdb_poster(
                    session,
                    self.options.get("tmdb_token"),
                    title,
                    key[5],
                    self.options.get("tmdb_language", "en-US"),
                    self.options.get("tmdb_minimum_match", 60),
                )
                data = await fetch_artwork(session, url)
            elif choice == "source_artwork" and self._source:
                source = self.hass.data["media_player"].get_entity(self._source_id)
                if source:
                    try:
                        image = await source.async_get_media_image()
                        data = image[0] if image else None
                    except (
                        HomeAssistantError,
                        OSError,
                        ValueError,
                        aiohttp.ClientError,
                        TimeoutError,
                    ):
                        data = None
            elif choice == "app_logo":
                url = self.options.get(f"{kind}_logo")
                if isinstance(url, str) and url.startswith("/local/"):
                    try:
                        url = urljoin(get_url(self.hass, allow_external=False), url)
                    except NoURLAvailableError:
                        url = None
                data = await fetch_artwork(session, url)
            if data:
                result = await self.hass.async_add_executor_job(
                    fit_poster,
                    data,
                    self.options.get("poster_blurred_background", False),
                    self.options.get("poster_canvas_width", 100),
                )
            if result[0]:
                break
        if key == self._artwork_key():
            self._art_image = result if result[0] else None
            self._image_revision += 1
            self.async_write_ha_state()

    @property
    def media_image_url(self):
        if self._kind == "tivimuse":
            return self.native.media_image_url if self.available else None
        if self._art_image and self._art_key == self._artwork_key():
            digest = hashlib.sha256(repr(self._art_key).encode()).hexdigest()[:16]
            return f"tivimuse://display/{digest}/{self._image_revision}"
        return None

    async def async_get_media_image(self, width=None, height=None):
        if self._kind == "tivimuse" and self.available:
            image = await self.native.async_get_media_image()
            return image if self._kind == "tivimuse" else (None, None)
        if self._art_key == self._artwork_key():
            return self._art_image or (None, None)
        return None, None

    async def _command(self, service, **data):
        if not self.available:
            raise HomeAssistantError("The active display source is unavailable")
        if self._kind == "tivimuse":
            handlers = {
                "media_play": self.native.async_media_play,
                "media_pause": self.native.async_media_pause,
                "media_seek": lambda: self.native.async_media_seek(data["seek_position"]),
            }
            if service not in handlers:
                raise HomeAssistantError("This control is not available for TiviMuse")
            await handlers[service]()
            return
        if not self._source:
            raise HomeAssistantError("No matching Nuvio or SmartTube media is active")
        await self.hass.services.async_call(
            "media_player",
            service,
            {"entity_id": self._source_id, **data},
            blocking=True,
        )

    async def async_media_play(self):
        await self._command("media_play")

    async def async_media_pause(self):
        await self._command("media_pause")

    async def async_media_stop(self):
        await self._command("media_stop")

    async def async_media_seek(self, position):
        await self._command("media_seek", seek_position=position)

    async def async_media_next_track(self):
        await self._command("media_next_track")

    async def async_media_previous_track(self):
        await self._command("media_previous_track")

    async def async_set_volume_level(self, volume):
        await self._command("volume_set", volume_level=volume)

    async def async_mute_volume(self, mute):
        await self._command("volume_mute", is_volume_muted=mute)

    async def async_play_media(self, media_type, media_id, **kwargs):
        # Explicit stable channel IDs always address TiviMuse, never the foreground VOD app.
        await self.native.async_play_media(media_type, media_id, **kwargs)

    async def async_browse_media(self, media_content_type=None, media_content_id=None):
        return await self.native.async_browse_media(media_content_type, media_content_id)

    async def async_get_browse_image(self, media_content_type, media_content_id, media_image_id):
        return await self.native.async_get_browse_image(
            media_content_type, media_content_id, media_image_id
        )

    async def async_play_channel(self, channel_id):
        await self.native.async_play_channel(channel_id)

    async def async_seek_relative(self, seconds):
        if self._kind != "tivimuse":
            raise HomeAssistantError("Relative timeshift seeking requires TiviMuse")
        await self.native.async_seek_relative(seconds)

    async def async_jump_live(self):
        if self._kind != "tivimuse":
            raise HomeAssistantError("Jump to live requires TiviMuse")
        await self.native.async_jump_live()
