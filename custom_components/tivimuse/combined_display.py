"""One Remote 3 display, selected by the Shield's foreground application."""

from __future__ import annotations

import asyncio
import hashlib
import math
from datetime import timedelta
from urllib.parse import urljoin

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .display_artwork import (
    app_kind,
    fetch_artwork,
    fit_poster,
    nuvio_type,
    style_logo,
    tmdb_poster,
    unmodified_image,
)

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
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
)
DEVICE_CONTROLS = (
    MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
)


class TiviMuseRemoteDisplay(MediaPlayerEntity):
    _attr_has_entity_name = True
    _attr_name = "Remote 3 display"
    _attr_should_poll = False
    _attr_device_class = MediaPlayerDeviceClass.TV
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
        self._logo_style_key = None
        self._styled_logo = None
        self.artwork_source = "None"
        self._poster_cache = {}
        self._poster_image_cache = {}
        self._selected_url = None
        self._native_art_task = None
        self._native_art_key = None
        self._native_art_image = None

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
        self.async_on_remove(
            async_track_time_interval(self.hass, self._programme_tick, timedelta(seconds=1))
        )

    @callback
    def _programme_tick(self, now):
        if self._programme_window:
            self.async_write_ha_state()

    def _cancel_artwork(self):
        if self._art_task:
            self._art_task.cancel()
            self._art_task = None
        if self._native_art_task:
            self._native_art_task.cancel()
            self._native_art_task = None

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
        kind = (
            app_kind(attrs.get("app_id"))
            or app_kind(attrs.get("source"))
            or app_kind(attrs.get("app_name"))
        )
        return (
            None if kind == "tivimuse" and not self.options.get("tivimuse_enabled", True) else kind
        )

    @property
    def _source(self):
        state = self.hass.states.get(self._source_id)
        if (
            not state
            or not state.attributes.get("media_title")
            or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)
            or self._kind not in ("nuvio", "smarttube")
        ):
            return None
        identity = state.attributes.get("app_id") or state.attributes.get("app_name")
        source_kind = app_kind(state.attributes.get("app_id")) or app_kind(
            state.attributes.get("app_name")
        )
        if identity and source_kind != self._kind:
            raw = state.attributes.get("app_name") or state.attributes.get("app_id")
            mapped = self.options.get("app_names", {}).get(raw, raw)
            if source_kind is not None or mapped != self.app_name:
                return None
        return state

    def _attribute(self, name):
        if self._kind == "tivimuse":
            return getattr(self.native, name, None) if self.native.available else None
        source = self._source
        return source.attributes.get(name) if source else None

    @property
    def available(self):
        # Keep the facade alive so explicit empty fields clear Remote 3's cache.
        # Native connection health remains on the native entity and diagnostics.
        return True

    @property
    def state(self):
        app = self.hass.states.get(self._app_id)
        if app and app.state == "off":
            return "off"
        if self._kind == "tivimuse":
            return self.native.state if self.native.available else "idle"
        return self._source.state if self._source else "idle"

    @property
    def app_id(self):
        state = self._foreground
        return state.attributes.get("app_id") or state.attributes.get("source") if state else None

    @property
    def app_name(self):
        state = self._foreground
        raw = (
            (
                state.attributes.get("app_name")
                or state.attributes.get("source")
                or state.attributes.get("app_id")
            )
            if state
            else None
        )
        names = self.options.get("app_names", {})
        return (
            names.get(raw)
            or names.get(self.app_id)
            or {"tivimuse": "TiviMuse", "nuvio": "Nuvio", "smarttube": "SmartTube"}.get(self._kind)
            or raw
        )

    @property
    def media_title(self):
        if self._kind == "tivimuse" and not self.options.get("show_program_as_title", True):
            return ""
        return self._attribute("media_title") or ""

    @property
    def media_artist(self):
        if self._kind == "tivimuse" and not self.options.get("show_channel_as_artist", True):
            return ""
        return self._attribute("media_artist") or ""

    @property
    def media_album_name(self):
        return self._attribute("media_album_name") or ""

    @property
    def media_content_id(self):
        return self._attribute("media_content_id") or ""

    @property
    def media_content_type(self):
        return self._attribute("media_content_type") or "app"

    @property
    def media_duration(self):
        if self._kind == "tivimuse":
            window = self._programme_window
            return (
                (window[1] - window[0]) if window and self.options.get("show_progress", True) else 0
            )
        return (
            (self._attribute("media_duration") or 0)
            if self.options.get("show_progress", True)
            else 0
        )

    @property
    def media_position(self):
        if self._kind == "tivimuse":
            window = self._programme_window
            return (
                min(max(0, dt_util.utcnow().timestamp() - window[0]), window[1] - window[0])
                if window and self.options.get("show_progress", True)
                else 0
            )
        return (
            (self._attribute("media_position") or 0)
            if self.options.get("show_progress", True)
            else 0
        )

    @property
    def media_position_updated_at(self):
        if not self.options.get("show_progress", True):
            return None
        if self._kind == "tivimuse":
            return dt_util.utcnow()
        value = self._attribute("media_position_updated_at")
        if not value and not self.media_title:
            return dt_util.utcnow()
        return dt_util.parse_datetime(value) if isinstance(value, str) else value

    @property
    def _programme_window(self):
        if self._kind != "tivimuse" or not self.native.available or self.native.state not in ACTIVE:
            return None
        programme = self.native.coordinator.data.get("programme") or {}
        start, end = programme.get("start_ms"), programme.get("end_ms")
        if (
            isinstance(start, (int, float))
            and isinstance(end, (int, float))
            and math.isfinite(start)
            and math.isfinite(end)
            and end > start
        ):
            return start / 1000, end / 1000
        return None

    @property
    def volume_level(self):
        state = self.hass.states.get(self._source_id)
        return state.attributes.get("volume_level") if state else None

    @property
    def is_volume_muted(self):
        state = self.hass.states.get(self._source_id)
        return state.attributes.get("is_volume_muted") if state else None

    @property
    def supported_features(self):
        # Remote 3's installed HA driver 0.17.0 only declares duration/position
        # when SEEK is declared at discovery time. Keep that display contract
        # stable, as the original facade did; commands still validate whether
        # the current stream can actually seek. Native HA capabilities stay exact.
        progress_compat = MediaPlayerEntityFeature.SEEK
        if not self.available:
            return MediaPlayerEntityFeature(0)
        if self._kind == "tivimuse":
            source = self.hass.states.get(self._source_id)
            return (
                progress_compat
                | self.native.supported_features
                | (
                    MediaPlayerEntityFeature(source.attributes.get("supported_features", 0))
                    & DEVICE_CONTROLS
                    if source
                    else 0
                )
            )
        source = self.hass.states.get(self._source_id)
        device = (
            MediaPlayerEntityFeature(source.attributes.get("supported_features", 0))
            & DEVICE_CONTROLS
            if source
            else 0
        )
        return (
            progress_compat
            | (MediaPlayerEntityFeature(self._attribute("supported_features") or 0) & FORWARDED)
            | device
        )

    @property
    def extra_state_attributes(self):
        if self._kind == "tivimuse" and self.native.available:
            data = {**self.native.extra_state_attributes, "display_app": "TiviMuse"}
            if not self.options.get("show_next_program", True):
                data.pop("next_programme", None)
            return data
        content_type = (
            nuvio_type(self._source.attributes) if self._kind == "nuvio" and self._source else None
        )
        if content_type == "Unknown":
            media_type = getattr(self._poster_cache.get(self._poster_key()), "media_type", None)
            content_type = {"movie": "Movie", "tv": "Episode"}.get(media_type, content_type)
        return {
            "display_app": self.app_name,
            "nuvio_content_type": content_type,
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

    def _native_image_key(self):
        if self._kind != "tivimuse" or not self.native.available or self.native.state not in ACTIVE:
            return None
        url = self.native.media_image_url
        return (
            (
                url,
                self.options.get("channel_icon_scale", 100),
                self.options.get("icon_canvas_shape", "square"),
                self.options.get("icon_background", "transparent"),
            )
            if url
            else None
        )

    def _app_logo(self):
        logos = self.options.get("app_logos", {})
        return (
            logos.get(self.app_name)
            or logos.get(self.app_id)
            or self.options.get(f"{self._kind}_logo")
            or self.options.get("fallback_logo")
        )

    def _source_artwork(self):
        source = self._source
        if not source:
            return None
        return (
            source.attributes.get("entity_picture")
            or source.attributes.get("entity_picture_local")
            or source.attributes.get("media_image_url")
        )

    def _art_preferences(self):
        marker = f"{self.app_id or ''} {self.app_name or ''}".casefold()
        for match, profile in self.options.get("app_artwork_profiles", {}).items():
            if str(match).casefold() in marker:
                values = (
                    profile.split(",")
                    if isinstance(profile, str)
                    else profile
                    if isinstance(profile, (list, tuple))
                    else []
                )
                valid = tuple(
                    str(x).strip()
                    for x in values
                    if str(x).strip() in ("tmdb_poster", "source_artwork", "app_logo")
                )
                if valid:
                    return (*valid, "app_logo")
        return (
            self.options.get(f"{self._kind}_artwork", "tmdb_poster"),
            self.options.get(f"{self._kind}_fallback_artwork", "source_artwork"),
            "app_logo",
        )

    def _poster_key(self):
        return (
            self.media_title,
            self.options.get("tmdb_language", "en-US"),
            self.options.get("tmdb_minimum_match", 60),
        )

    def _instant_artwork(self):
        if self._kind == "tivimuse":
            return self._app_logo()
        if self._source:
            for choice in self._art_preferences():
                if (
                    choice == "tmdb_poster"
                    and self.options.get("tmdb_enabled")
                    and self.options.get("tmdb_for_other_apps", True)
                    and not self.options.get("poster_blurred_background", False)
                ):
                    url = self._poster_cache.get(self._poster_key())
                    if url:
                        return url
                if choice == "source_artwork" and self._source_artwork():
                    return self._source_artwork()
                if choice == "app_logo" and self._app_logo():
                    return self._app_logo()
        return self._app_logo()

    @callback
    def _changed(self, event=None):
        native_key = self._native_image_key()
        if native_key != self._native_art_key:
            if self._native_art_task:
                self._native_art_task.cancel()
            self._native_art_key = native_key
            self._native_art_image = None
            self._image_revision += 1
            if native_key:
                self._native_art_task = self.hass.async_create_background_task(
                    self._load_native_logo(native_key), "TiviMuse ready channel logo"
                )
        key = self._artwork_key()
        if key != self._art_key:
            if self._art_task:
                self._art_task.cancel()
            self._art_key = key
            self._art_image = None
            self._selected_url = None
            if (
                key
                and self._art_preferences()[0] == "tmdb_poster"
                and self.options.get("tmdb_enabled")
                and self.options.get("tmdb_for_other_apps", True)
                and self.options.get("poster_blurred_background", False)
            ):
                url = self._poster_cache.get(self._poster_key())
                self._art_image = self._poster_image_cache.get(
                    (url, self.options.get("poster_canvas_width", 100))
                )
                if self._art_image:
                    self.artwork_source = "TMDB poster"
            self._image_revision += 1
            if key:
                self._art_task = self.hass.async_create_background_task(
                    self._load_artwork(key), "TiviMuse Remote 3 artwork"
                )
        if self._kind == "tivimuse":
            self.artwork_source = (
                "TiviMuse EPG logo"
                if self._native_art_image
                else "app logo"
                if self._app_logo()
                else "None"
            )
        elif not self._art_image and not self._selected_url:
            self.artwork_source = (
                "source artwork"
                if self._source_artwork() and self._instant_artwork() == self._source_artwork()
                else "app logo"
                if self._instant_artwork()
                else "None"
            )
        self.async_write_ha_state()

    @callback
    def refresh_artwork(self, clear_cache=False):
        if clear_cache:
            self._poster_cache.clear()
            self._poster_image_cache.clear()
        self._art_key = None
        self._native_art_key = None
        self._changed()

    async def _load_native_logo(self, key):
        # Publish a URL only after its bytes are ready. Remote 3 must never cache
        # an initial 404 while the Shield is still loading the channel logo.
        for delay in (0, 1, 3, 10, 30):
            if delay:
                await asyncio.sleep(delay)
            if key != self._native_image_key():
                return
            image = await self.native.async_get_media_image()
            if not image or not image[0]:
                continue
            styled = await self.hass.async_add_executor_job(style_logo, image[0], *key[1:])
            if key != self._native_image_key():
                return
            if styled[0]:
                self._native_art_image = styled
                self._image_revision += 1
                self.artwork_source = "TiviMuse EPG logo"
                self.async_write_ha_state()
                return

    async def _load_artwork(self, key):
        session = async_get_clientsession(self.hass)
        for choice in dict.fromkeys(self._art_preferences()):
            if key != self._artwork_key():
                return
            if (
                choice == "tmdb_poster"
                and self._source
                and self.options.get("tmdb_enabled")
                and self.options.get("tmdb_for_other_apps", True)
            ):
                cache_key = self._poster_key()
                if cache_key not in self._poster_cache:
                    url = await tmdb_poster(
                        session,
                        self.options.get("tmdb_token"),
                        key[1],
                        key[5],
                        self.options.get("tmdb_language", "en-US"),
                        self.options.get("tmdb_minimum_match", 60),
                    )
                    if len(self._poster_cache) >= 32:
                        self._poster_cache.pop(next(iter(self._poster_cache)))
                    self._poster_cache[cache_key] = url
                url = self._poster_cache[cache_key]
                if not url:
                    continue
                if self.options.get("poster_blurred_background", False):
                    image_key = (url, self.options.get("poster_canvas_width", 100))
                    result = self._poster_image_cache.get(image_key)
                    if result is None:
                        data = await fetch_artwork(session, url)
                        result = (
                            await self.hass.async_add_executor_job(
                                fit_poster, data, True, image_key[1]
                            )
                            if data
                            else (None, None)
                        )
                        if result[0]:
                            if len(self._poster_image_cache) >= 32:
                                self._poster_image_cache.pop(next(iter(self._poster_image_cache)))
                            self._poster_image_cache[image_key] = result
                    if not result[0]:
                        continue
                else:
                    result = None
                if key == self._artwork_key():
                    self._art_image = result
                    self._selected_url = url if result is None else None
                    self._image_revision += 1
                    self.artwork_source = "TMDB poster"
                    self.async_write_ha_state()
                return
            url = (
                self._source_artwork()
                if choice == "source_artwork"
                else self._app_logo()
                if choice == "app_logo"
                else None
            )
            if url:
                if key == self._artwork_key():
                    self._selected_url = url
                    self.artwork_source = (
                        "source artwork" if choice == "source_artwork" else "app logo"
                    )
                    self.async_write_ha_state()
                return

    @property
    def media_image_url(self):
        if self._kind == "tivimuse":
            if self._native_art_image and self._native_art_key == self._native_image_key():
                digest = hashlib.sha256(repr(self._native_art_key).encode()).hexdigest()[:16]
                return f"tivimuse://display/native/{digest}/{self._image_revision}"
            return self._app_logo()
        if self._art_key == self._artwork_key():
            if self._art_image:
                digest = hashlib.sha256(repr(self._art_key).encode()).hexdigest()[:16]
                return f"tivimuse://display/{digest}/{self._image_revision}"
            if self._selected_url:
                return self._selected_url
        return self._instant_artwork()

    @property
    def entity_picture(self):
        url = self.media_image_url
        return self.media_image_local if url and url.startswith("tivimuse://") else url or ""

    async def async_get_media_image(self, width=None, height=None):
        if self._kind == "tivimuse":
            return (
                self._native_art_image
                if self._native_art_image and self._native_art_key == self._native_image_key()
                else (None, None)
            )
        if self._art_key == self._artwork_key() and self._art_image:
            return self._art_image
        url = self.media_image_url
        if not url:
            return None, None
        if url and url.startswith("/"):
            try:
                url = urljoin(get_url(self.hass, allow_external=False), url)
            except NoURLAvailableError:
                return None, None
        data = await fetch_artwork(async_get_clientsession(self.hass), url)
        return (
            await self.hass.async_add_executor_job(unmodified_image, data) if data else (None, None)
        )

    async def _command(self, service, **data):
        if service in (
            "volume_set",
            "volume_mute",
            "volume_up",
            "volume_down",
            "turn_on",
            "turn_off",
        ):
            await self.hass.services.async_call(
                "media_player", service, {"entity_id": self._source_id, **data}, blocking=True
            )
            return
        if not self.available:
            raise HomeAssistantError("The active display source is unavailable")
        if self._kind == "tivimuse":
            handlers = {
                "media_play": self.native.async_media_play,
                "media_pause": self.native.async_media_pause,
                "media_seek": lambda: self._seek_programme(data["seek_position"]),
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

    async def _seek_programme(self, position):
        """Translate a programme-bar target into the player's timeshift coordinates."""
        window = self._programme_window
        if not window:
            raise HomeAssistantError("Programme times are unavailable")
        data = self.native.coordinator.data
        if not data.get("can_seek"):
            raise HomeAssistantError("This stream cannot seek")
        live_ms = data.get("live_position_ms")
        if live_ms is None:
            live_ms = data.get("duration_ms")
        if not isinstance(live_ms, (int, float)) or not math.isfinite(live_ms) or live_ms < 0:
            raise HomeAssistantError("The timeshift window is unavailable")
        if not math.isfinite(position):
            raise HomeAssistantError("Invalid seek position")
        target = live_ms / 1000 - (dt_util.utcnow().timestamp() - window[0] - position)
        await self.native.async_media_seek(min(max(0, target), live_ms / 1000))

    async def async_media_next_track(self):
        await self._command("media_next_track")

    async def async_media_previous_track(self):
        await self._command("media_previous_track")

    async def async_set_volume_level(self, volume):
        await self._command("volume_set", volume_level=volume)

    async def async_mute_volume(self, mute):
        await self._command("volume_mute", is_volume_muted=mute)

    async def async_volume_up(self):
        await self._command("volume_up")

    async def async_volume_down(self):
        await self._command("volume_down")

    async def async_turn_on(self):
        await self._command("turn_on")

    async def async_turn_off(self):
        await self._command("turn_off")

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
