"""Local TiviMuse media player integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import DeviceUnavailable, InvalidAuth, TiviMuseClient, TiviMuseError
from .const import CONF_TOKEN
from .coordinator import TiviMuseCoordinator


@dataclass
class RuntimeData:
    coordinator: TiviMuseCoordinator


async def async_setup_entry(hass, entry: ConfigEntry) -> bool:
    client = TiviMuseClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_TOKEN],
    )
    disconnected = False
    try:
        info = await client.info()
    except InvalidAuth as error:
        raise ConfigEntryAuthFailed(str(error)) from error
    except DeviceUnavailable as error:
        if not entry.options.get("combined_display"):
            raise ConfigEntryNotReady(str(error)) from error
        # Nuvio and SmartTube must remain usable while the native app is closed.
        info = {"device_id": entry.unique_id, "protocol": 1}
        client.device_id = entry.unique_id
        disconnected = True
    except TiviMuseError as error:
        raise ConfigEntryNotReady(str(error)) from error
    if entry.unique_id != info["device_id"]:
        raise ConfigEntryNotReady("A different TiviMuse installation is at this address")
    coordinator = TiviMuseCoordinator(hass, entry, client, info)
    if disconnected:
        coordinator.async_set_updated_data({"state": "idle"})
        coordinator.async_set_update_error(UpdateFailed("TiviMuse is not reachable"))
    else:
        await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = RuntimeData(coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.MEDIA_PLAYER])
    coordinator.start()
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry: ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, [Platform.MEDIA_PLAYER]):
        await entry.runtime_data.coordinator.stop()
        return True
    return False
