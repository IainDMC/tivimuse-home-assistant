"""Remote display artwork selectors."""

from homeassistant.components.select import SelectEntity

from .display_controls import SELECTS, DisplayControl


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.options.get("combined_display"):
        async_add_entities(
            [DisplaySelect(entry, key, *definition) for key, definition in SELECTS.items()]
        )


class DisplaySelect(DisplayControl, SelectEntity):
    def __init__(self, entry, key, name, default, options):
        super().__init__(entry, key, name, default, "mdi:image")
        self._attr_options = options

    @property
    def current_option(self):
        return self.value

    async def async_select_option(self, option):
        if option not in self.options:
            raise ValueError("Unsupported display artwork option")
        await self.save(option)
