"""Config flow, entity controls and browser validation against the real HA framework."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tivimuse.const import CONF_TOKEN, DOMAIN

DEVICE = "c1047025-4ccd-40e1-a0bb-91d1c68d1ade"
CHANNEL = f"tmc1:{DEVICE}:2:MjM"
INFO = {"device_id": DEVICE, "protocol": 1, "version": "test"}
STATE = {
    "device_id": DEVICE,
    "revision": "test:1",
    "state": "playing",
    "mode": "live",
    "channel_id": CHANNEL,
    "channel": "ABC TV",
    "playlist": "Second playlist",
    "playlist_id": "playlist2",
    "can_seek": True,
    "position_ms": 10_000,
    "duration_ms": 60_000,
    "position_updated_at": "2026-10-30T08:00:00Z",
    "programme": None,
}


async def state(after=None):
    if after:
        await asyncio.Event().wait()
    return STATE


@pytest.mark.asyncio
async def test_user_flow_creates_one_device_entry(hass):
    with (
        patch("custom_components.tivimuse.api.TiviMuseClient.info", return_value=INFO),
        patch("custom_components.tivimuse.api.TiviMuseClient.state", side_effect=state),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_HOST: "test-device", CONF_PORT: 42990, CONF_TOKEN: "test-key"},
        )
        assert result["type"] == "create_entry"
        assert result["data"][CONF_TOKEN] == "test-key"
        await hass.async_block_till_done()
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_real_media_entity_routes_exact_ids_and_unloads(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE,
        data={CONF_HOST: "test-device", CONF_PORT: 42990, CONF_TOKEN: "test-key"},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.tivimuse.api.TiviMuseClient.info", return_value=INFO),
        patch("custom_components.tivimuse.api.TiviMuseClient.state", side_effect=state),
        patch(
            "custom_components.tivimuse.api.TiviMuseClient.command", new_callable=AsyncMock
        ) as command,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entity = hass.states.get("media_player.tivimuse")
        assert entity is not None
        assert entity.state == "playing"
        assert entity.attributes["channel_id"] == CHANNEL
        await hass.services.async_call(
            DOMAIN,
            "play_channel",
            {"entity_id": entity.entity_id, "channel_id": CHANNEL},
            blocking=True,
        )
        command.assert_awaited_with("play_channel", channel_id=CHANNEL)
        await hass.services.async_call(
            "media_player", "media_pause", {"entity_id": entity.entity_id}, blocking=True
        )
        command.assert_awaited_with("pause")
        await hass.services.async_call(
            DOMAIN, "jump_live", {"entity_id": entity.entity_id}, blocking=True
        )
        command.assert_awaited_with("jump_live")
        assert await hass.config_entries.async_unload(entry.entry_id)
