"""Remote display switches, matching the former device-page controls."""

from homeassistant.components.switch import SwitchEntity

from .display_controls import SWITCHES, DisplayControl


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.options.get("combined_display"):
        async_add_entities(
            [
                DisplaySwitch(entry, key, name, default, icon)
                for key, (name, default, icon) in SWITCHES.items()
            ]
        )


class DisplaySwitch(DisplayControl, SwitchEntity):
    @property
    def is_on(self):
        return self.value

    async def async_turn_on(self, **kwargs):
        await self.save(True)

    async def async_turn_off(self, **kwargs):
        await self.save(False)
