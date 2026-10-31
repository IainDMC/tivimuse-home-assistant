"""Remote display maintenance buttons with direct TiviMuse data refresh."""

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError

from .display_controls import BUTTONS, DisplayControl


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.options.get("combined_display"):
        async_add_entities(
            [DisplayButton(entry, key, name, icon=icon) for key, (name, icon) in BUTTONS.items()]
        )


class DisplayButton(DisplayControl, ButtonEntity):
    async def async_press(self):
        runtime = self.entry.runtime_data
        if self.key == "refresh_metadata":
            await runtime.coordinator.async_request_refresh()
            if not runtime.coordinator.last_update_success:
                raise HomeAssistantError("TiviMuse is not reachable")
        if runtime.display:
            runtime.native._logo_cache_key = runtime.native._logo_cache = None
            runtime.display.refresh_artwork(clear_cache=self.key == "clear_artwork_cache")
