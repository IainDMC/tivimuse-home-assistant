"""Local TiviMuse media player integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import InvalidAuth, TiviMuseClient, TiviMuseError
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
    try:
        info = await client.info()
    except InvalidAuth as error:
        raise ConfigEntryAuthFailed(str(error)) from error
    except TiviMuseError as error:
        raise ConfigEntryNotReady(str(error)) from error
    if entry.unique_id != info["device_id"]:
        raise ConfigEntryNotReady("A different TiviMuse installation is at this address")
    coordinator = TiviMuseCoordinator(hass, entry, client, info)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = RuntimeData(coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.MEDIA_PLAYER])
    coordinator.start()
    return True


async def async_unload_entry(hass, entry: ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, [Platform.MEDIA_PLAYER]):
        await entry.runtime_data.coordinator.stop()
        return True
    return False
