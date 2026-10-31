"""Device-page controls for the combined Remote 3 display."""

from homeassistant.helpers.entity import Entity, EntityCategory

from .const import DOMAIN

SWITCHES = {
    "tivimuse_enabled": ("TiviMuse detection", True, "mdi:television-play"),
    "show_progress": ("Show programme progress", True, "mdi:progress-clock"),
    "show_channel_as_artist": ("Show channel name", True, "mdi:television-guide"),
    "show_program_as_title": ("Show programme title", True, "mdi:format-title"),
    "show_next_program": ("Show next programme", True, "mdi:skip-next"),
    "poster_blurred_background": (
        "Blurred poster background",
        False,
        "mdi:image-filter-center-focus",
    ),
    "tmdb_enabled": ("TMDB artwork", False, "mdi:movie-open-star"),
    "tmdb_for_other_apps": ("TMDB artwork for other apps", True, "mdi:apps"),
}
SELECTS = {
    "nuvio_artwork": (
        "Nuvio preferred artwork",
        "tmdb_poster",
        ["tmdb_poster", "source_artwork", "app_logo"],
    ),
    "nuvio_fallback_artwork": (
        "Nuvio fallback artwork",
        "source_artwork",
        ["tmdb_poster", "source_artwork", "app_logo"],
    ),
    "smarttube_artwork": (
        "SmartTube preferred artwork",
        "tmdb_poster",
        ["tmdb_poster", "source_artwork", "app_logo"],
    ),
    "smarttube_fallback_artwork": (
        "SmartTube fallback artwork",
        "source_artwork",
        ["tmdb_poster", "source_artwork", "app_logo"],
    ),
    "icon_canvas_shape": ("Channel icon canvas", "square", ["preserve", "square", "16:9"]),
    "icon_background": (
        "Channel icon background",
        "transparent",
        ["transparent", "black", "white", "automatic"],
    ),
}
NUMBERS = {
    "poster_canvas_width": ("Poster canvas width", 100, 100, 200, 5),
    "channel_icon_scale": ("Channel icon size", 100, 10, 100, 5),
    "tmdb_minimum_match": ("TMDB minimum title match", 60, 0, 100, 5),
}
BUTTONS = {
    "refresh_metadata": ("Refresh TiviMuse data", "mdi:update"),
    "clear_artwork_cache": ("Clear artwork cache", "mdi:image-refresh"),
    "test_artwork": ("Test artwork selection", "mdi:image-search"),
}
SENSORS = {
    "active_app": ("Display active app", "mdi:apps"),
    "artwork_source": ("Display artwork source", "mdi:image-search"),
    "nuvio_content_type": ("Nuvio content type", "mdi:movie-open"),
    "native_connection": ("TiviMuse connection", "mdi:access-point-network"),
}


class DisplayControl(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry, key, name, default=None, icon=None):
        self.entry = entry
        self.key = key
        self.default = default
        self._attr_unique_id = f"{entry.unique_id}_display_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.unique_id)}}

    @property
    def value(self):
        return self.entry.options.get(self.key, self.default)

    async def async_added_to_hass(self):
        self.async_on_remove(self.entry.add_update_listener(self._updated))

    async def _updated(self, hass, entry):
        self.async_write_ha_state()

    async def save(self, value):
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, self.key: value}
        )
        self.async_write_ha_state()
