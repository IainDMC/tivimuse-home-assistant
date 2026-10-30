"""Diagnostics intentionally omit pairing secrets and private viewing information."""


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data.coordinator
    return {
        "integration": "tivimuse",
        "protocol": coordinator.info.get("protocol"),
        "app_version": coordinator.info.get("version"),
        "available": coordinator.last_update_success,
        "state": (coordinator.data or {}).get("state"),
        "mode": (coordinator.data or {}).get("mode"),
    }
