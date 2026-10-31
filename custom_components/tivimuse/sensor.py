"""Display status and artwork diagnostics without exposing connection secrets."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.event import async_track_state_change_event

from .display_controls import SENSORS, DisplayControl


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.options.get("combined_display"):
        async_add_entities(
            [DisplaySensor(entry, key, name, icon=icon) for key, (name, icon) in SENSORS.items()]
        )


class DisplaySensor(DisplayControl, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            self.entry.runtime_data.coordinator.async_add_listener(self.async_write_ha_state)
        )
        display = self.entry.runtime_data.display
        self.async_on_remove(
            async_track_state_change_event(self.hass, [display.entity_id], self._display_changed)
        )

    async def _display_changed(self, event):
        self.async_write_ha_state()

    @property
    def native_value(self):
        display = self.entry.runtime_data.display
        if self.key == "native_connection":
            return (
                "Connected"
                if self.entry.runtime_data.coordinator.last_update_success
                else "Disconnected"
            )
        if self.key == "active_app":
            return display.app_name or "Inactive"
        if self.key == "artwork_source":
            return display.artwork_source
        return display.extra_state_attributes.get("nuvio_content_type") or "Inactive"
