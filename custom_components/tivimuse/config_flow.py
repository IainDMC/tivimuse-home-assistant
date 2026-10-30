"""Pair an existing TiviMuse installation using its generated local key."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import InvalidAuth, TiviMuseClient, TiviMuseError
from .const import CONF_TOKEN, DEFAULT_PORT, DOMAIN


def schema(defaults=None):
    values = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=values.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=values.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=1024, max=65535)
            ),
            vol.Required(CONF_TOKEN, default=values.get(CONF_TOKEN, "")): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
        }
    )


class TiviMuseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                client = TiviMuseClient(
                    async_get_clientsession(self.hass),
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    user_input[CONF_TOKEN],
                )
                info = await client.info()
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except (TiviMuseError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info["device_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="TiviMuse", data=user_input)
        return self.async_show_form(step_id="user", data_schema=schema(user_input), errors=errors)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reconfigure()

    async def async_step_reconfigure(self, user_input=None):
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        errors = {}
        if user_input is not None:
            try:
                client = TiviMuseClient(
                    async_get_clientsession(self.hass),
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    user_input[CONF_TOKEN],
                )
                info = await client.info()
                if info["device_id"] != entry.unique_id:
                    errors["base"] = "wrong_device"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except (TiviMuseError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                if not errors:
                    self.hass.config_entries.async_update_entry(entry, data=user_input)
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reconfigure_successful")
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema(user_input or entry.data), errors=errors
        )
