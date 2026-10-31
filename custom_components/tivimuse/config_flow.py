"""Pair an existing TiviMuse installation using its generated local key."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import InvalidAuth, TiviMuseClient, TiviMuseError
from .const import CONF_TOKEN, DEFAULT_PORT, DOMAIN
from .display_artwork import app_kind


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

    @staticmethod
    def async_get_options_flow(config_entry):
        return DisplayOptionsFlow()

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


class DisplayOptionsFlow(config_entries.OptionsFlow):
    """Configure one combined display without changing the native player identity."""

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            if user_input.get("combined_display"):
                registry = er.async_get(self.hass)
                for name in ("source_entity", "app_entity"):
                    entity_id = user_input.get(name)
                    entity = registry.async_get(entity_id) if entity_id else None
                    if (
                        not entity_id
                        or self.hass.states.get(entity_id) is None
                        or (entity and entity.platform in (DOMAIN, "remote3_display"))
                    ):
                        errors["base"] = "invalid_display_source"
            if not errors:
                return self.async_create_entry(title="", data=user_input)
        values = dict(self.config_entry.options)
        # Reuse compatible settings privately; never copy a guide URL or webhook.
        if not values:
            old_entries = self.hass.config_entries.async_entries("remote3_display")
            if len(old_entries) == 1:
                old = {**old_entries[0].data, **old_entries[0].options}
                for name in (
                    "source_entity",
                    "app_entity",
                    "tmdb_enabled",
                    "tmdb_token",
                    "tmdb_language",
                    "smarttube_artwork",
                    "smarttube_fallback_artwork",
                    "nuvio_artwork",
                    "nuvio_fallback_artwork",
                    "poster_blurred_background",
                    "poster_canvas_width",
                    "tmdb_minimum_match",
                ):
                    if name in old:
                        values[name] = old[name]
                for identity, url in old.get("app_logos", {}).items():
                    kind = app_kind(identity)
                    if kind in ("nuvio", "smarttube"):
                        values[f"{kind}_logo"] = url
                for identity, profile in old.get("app_artwork_profiles", {}).items():
                    kind = app_kind(identity)
                    if kind in ("nuvio", "smarttube") and isinstance(profile, list):
                        allowed = [
                            x for x in profile if x in ("tmdb_poster", "source_artwork", "app_logo")
                        ]
                        if allowed:
                            values[f"{kind}_artwork"] = allowed[0]
                            values[f"{kind}_fallback_artwork"] = allowed[-1]
        values.update(user_input or {})
        entity_selector = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="media_player")
        )
        choices = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=["tmdb_poster", "source_artwork", "app_logo"],
                translation_key="display_artwork",
            )
        )
        fields = {
            vol.Required("combined_display", default=values.get("combined_display", False)): bool,
            vol.Optional("source_entity"): entity_selector,
            vol.Optional("app_entity"): entity_selector,
            vol.Required("tmdb_enabled", default=values.get("tmdb_enabled", False)): bool,
            vol.Optional("tmdb_token"): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.PASSWORD,
                )
            ),
            vol.Optional("tmdb_language", default=values.get("tmdb_language", "en-US")): str,
            vol.Optional(
                "tmdb_minimum_match", default=values.get("tmdb_minimum_match", 60)
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
            vol.Optional(
                "poster_canvas_width", default=values.get("poster_canvas_width", 100)
            ): vol.All(vol.Coerce(int), vol.Range(min=100, max=200)),
            vol.Required(
                "poster_blurred_background", default=values.get("poster_blurred_background", False)
            ): bool,
        }
        for kind in ("nuvio", "smarttube"):
            fields[
                vol.Required(
                    f"{kind}_artwork", default=values.get(f"{kind}_artwork", "tmdb_poster")
                )
            ] = choices
            fields[
                vol.Required(
                    f"{kind}_fallback_artwork",
                    default=values.get(f"{kind}_fallback_artwork", "source_artwork"),
                )
            ] = choices
            fields[vol.Optional(f"{kind}_logo")] = str
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(vol.Schema(fields), values),
            errors=errors,
        )
