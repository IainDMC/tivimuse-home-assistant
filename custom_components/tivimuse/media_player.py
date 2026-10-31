"""A media player and paged channel browser for one TiviMuse installation."""

from __future__ import annotations

import asyncio
import json
from time import monotonic

import voluptuous as vol
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import TiviMuseError
from .artwork import fit_logo
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data.coordinator
    async_add_entities([TiviMusePlayer(coordinator)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "play_channel", {vol.Required("channel_id"): cv.string}, "async_play_channel"
    )
    platform.async_register_entity_service(
        "seek_relative",
        {vol.Required("seconds"): vol.All(vol.Coerce(float), vol.Range(min=-86400, max=86400))},
        "async_seek_relative",
    )
    platform.async_register_entity_service("jump_live", {}, "async_jump_live")


class TiviMusePlayer(CoordinatorEntity, MediaPlayerEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_app_name = "TiviMuse"
    _attr_app_id = "app.opentv.debug"
    _attr_media_image_remotely_accessible = False

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._logo_lock = asyncio.Lock()
        self._logo_cache = None
        self._logo_cache_key = None
        self._logo_cached_at = 0.0
        device_id = coordinator.info["device_id"]
        self._attr_unique_id = device_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": "TiviMuse",
            "manufacturer": "TiviMuse",
            "model": "Android TV local player",
            "sw_version": coordinator.info.get("version"),
        }

    @property
    def supported_features(self):
        features = (
            MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.BROWSE_MEDIA
        )
        if self.coordinator.data.get("can_seek") and self.coordinator.data.get("mode") != "live":
            features |= MediaPlayerEntityFeature.SEEK
        return features

    @property
    def state(self):
        return {
            "playing": MediaPlayerState.PLAYING,
            "paused": MediaPlayerState.PAUSED,
            "buffering": MediaPlayerState.BUFFERING,
        }.get(self.coordinator.data.get("state"), MediaPlayerState.IDLE)

    @property
    def _display_data(self):
        """Do not leave the previous programme on a stopped or disconnected display."""
        data = self.coordinator.data
        if not self.available or data.get("state") not in ("playing", "paused", "buffering"):
            return {}
        return data

    @property
    def media_content_id(self):
        return self._display_data.get("channel_id")

    @property
    def media_content_type(self):
        return MediaType.CHANNEL

    @property
    def media_channel(self):
        return self._display_data.get("channel")

    @property
    def media_playlist(self):
        return self._display_data.get("playlist")

    @property
    def media_title(self):
        return (self._display_data.get("programme") or {}).get("title") or self.media_channel

    @property
    def media_artist(self):
        """Remote 3 uses the standard artist field for the channel subtitle."""
        return self.media_channel

    @property
    def media_album_name(self):
        return self.media_playlist

    @property
    def media_duration(self):
        data = self._display_data
        if data.get("mode") == "live":
            programme = data.get("programme") or {}
            return (
                (programme["end_ms"] - programme["start_ms"]) / 1000
                if "end_ms" in programme and "start_ms" in programme
                else None
            )
        duration = data.get("duration_ms")
        return duration / 1000 if duration else None

    @property
    def media_position(self):
        data = self._display_data
        if data.get("mode") == "live":
            programme = data.get("programme") or {}
            at = self.media_position_updated_at
            return (
                max(0, (at.timestamp() * 1000 - programme["start_ms"]) / 1000)
                if at and "start_ms" in programme
                else None
            )
        position = data.get("position_ms")
        return position / 1000 if position is not None else None

    @property
    def media_position_updated_at(self):
        value = self._display_data.get("position_updated_at")
        return dt_util.parse_datetime(value) if value else None

    @property
    def media_image_url(self):
        return (
            f"tivimuse://logo/{self.media_content_id}"
            if self.media_content_id and self.coordinator.data.get("logo_available")
            else None
        )

    @property
    def extra_state_attributes(self):
        data = self._display_data
        return {
            "playback_state": data.get("state"),
            "channel_id": data.get("channel_id"),
            "playlist_id": data.get("playlist_id"),
            "playback_mode": data.get("mode"),
            "programme": data.get("programme"),
            "next_programme": data.get("next_programme"),
            "can_seek": data.get("can_seek", False),
        }

    async def _command(self, action, **kwargs):
        try:
            await self.coordinator.client.command(action, **kwargs)
        except TiviMuseError as error:
            raise HomeAssistantError(str(error)) from error

    async def async_media_play(self):
        await self._command("play")

    async def async_media_pause(self):
        await self._command("pause")

    async def async_media_seek(self, position):
        await self._command("seek", seconds=position)

    async def async_seek_relative(self, seconds):
        await self._command("seek_relative", seconds=seconds)

    async def async_jump_live(self):
        await self._command("jump_live")

    async def async_play_channel(self, channel_id):
        await self._command("play_channel", channel_id=channel_id)

    async def async_play_media(self, media_type, media_id, **kwargs):
        if media_type not in (MediaType.CHANNEL, "channel", DOMAIN):
            raise HomeAssistantError("Only TiviMuse channel IDs are supported")
        await self.async_play_channel(media_id)

    async def async_get_media_image(self, width=None, height=None):
        async with self._logo_lock:
            key = self.media_image_url
            if not key:
                self._logo_cache_key = self._logo_cache = None
                return None, None
            if key == self._logo_cache_key and monotonic() - self._logo_cached_at < 300:
                return self._logo_cache
            try:
                data, _ = await self.coordinator.client.logo(self.media_content_id)
                image = await self.hass.async_add_executor_job(fit_logo, data)
            except TiviMuseError:
                return None, None
            # An old request must never become the new channel's artwork.
            if key != self.media_image_url:
                return None, None
            if image is not None:
                self._logo_cache_key, self._logo_cache = key, image
                self._logo_cached_at = monotonic()
            return image or (None, None)

    async def async_get_browse_image(self, media_content_type, media_content_id, media_image_id):
        if (
            media_content_type != "channel"
            or media_content_id != media_image_id
            or not media_image_id.startswith("tmc1:")
        ):
            return None, None
        try:
            data, _ = await self.coordinator.client.logo(media_image_id)
            return await self.hass.async_add_executor_job(fit_logo, data) or (None, None)
        except TiviMuseError:
            return None, None

    async def async_browse_media(self, media_content_type=None, media_content_id=None):
        client = self.coordinator.client
        try:
            if not media_content_id or media_content_id == "root":
                items = await client.playlists()
                return directory(
                    "TiviMuse playlists",
                    "root",
                    DOMAIN,
                    [directory(x["name"], x["id"], "tivimuse.playlist") for x in items],
                )
            if media_content_type == "tivimuse.playlist":
                items = await client.categories(media_content_id)
                children = [
                    directory(
                        "All channels",
                        json.dumps({"playlist_id": media_content_id}),
                        "tivimuse.channels",
                    )
                ]
                children.extend(
                    directory(
                        x["name"],
                        json.dumps({"playlist_id": media_content_id, "category_id": x["id"]}),
                        "tivimuse.channels",
                    )
                    for x in items
                )
                return directory("Playlist", media_content_id, media_content_type, children)
            if media_content_type == "tivimuse.channels":
                options = json.loads(media_content_id)
                page = await client.channels(
                    options["playlist_id"], options.get("category_id"), options.get("offset", 0)
                )
                children = []
                for item in page["items"]:
                    title = item["name"] + (f" · {item['quality']}" if item.get("quality") else "")
                    children.append(
                        BrowseMedia(
                            title=title,
                            media_class=MediaClass.CHANNEL,
                            media_content_id=item["id"],
                            media_content_type="channel",
                            can_play=True,
                            can_expand=False,
                            thumbnail=self.get_browse_image_url("channel", item["id"], item["id"])
                            if item.get("logo_available")
                            else None,
                        )
                    )
                if page.get("next_offset") is not None:
                    children.append(
                        directory(
                            "Next page",
                            json.dumps({**options, "offset": page["next_offset"]}),
                            "tivimuse.channels",
                        )
                    )
                return directory("Channels", media_content_id, media_content_type, children)
        except (TiviMuseError, ValueError, KeyError) as error:
            raise HomeAssistantError("Cannot browse these TiviMuse channels") from error
        raise HomeAssistantError("Unknown TiviMuse directory")


def directory(title, content_id, content_type, children=None):
    return BrowseMedia(
        title=title,
        media_class=MediaClass.DIRECTORY,
        media_content_id=content_id,
        media_content_type=content_type,
        can_play=False,
        can_expand=True,
        children=children,
    )
