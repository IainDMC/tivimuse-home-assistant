"""Remote display artwork sizing and poster title matching."""

from homeassistant.components.number import NumberEntity, NumberMode

from .display_controls import NUMBERS, DisplayControl


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.options.get("combined_display"):
        async_add_entities(
            [DisplayNumber(entry, key, *definition) for key, definition in NUMBERS.items()]
        )


class DisplayNumber(DisplayControl, NumberEntity):
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = "%"

    def __init__(self, entry, key, name, default, minimum, maximum, step):
        super().__init__(entry, key, name, default, "mdi:resize")
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step

    @property
    def native_value(self):
        return self.value

    async def async_set_native_value(self, value):
        await self.save(round(value))
