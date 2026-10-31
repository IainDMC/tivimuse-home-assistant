"""Config flow, entity controls and browser validation against the real HA framework."""

import asyncio
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from PIL import Image
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


@pytest.fixture
async def display(hass):
    """Exercise the same entity and coordinator used by an actual installation."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE,
        data={CONF_HOST: "test-device", CONF_PORT: 42990, CONF_TOKEN: "test-key"},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.tivimuse.api.TiviMuseClient.info", return_value=INFO),
        patch("custom_components.tivimuse.api.TiviMuseClient.state", side_effect=state),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        player = hass.data["media_player"].get_entity("media_player.tivimuse")
        yield player, entry.runtime_data.coordinator
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_remote_display_updates_programme_without_changing_channel(hass, display):
    _, coordinator = display
    for title, start in [("First programme", 0), ("Next programme", 3600000)]:
        coordinator.async_set_updated_data(
            {
                **STATE,
                "programme": {"title": title, "start_ms": start, "end_ms": start + 3600000},
                "next_programme": {"title": "Coming next"},
            }
        )
        entity = hass.states.get("media_player.tivimuse")
        assert entity.attributes["media_title"] == title
        assert entity.attributes["media_artist"] == "ABC TV"
        assert entity.attributes["media_album_name"] == "Second playlist"
        assert entity.attributes["media_content_id"] == CHANNEL
        assert entity.attributes["next_programme"]["title"] == "Coming next"


async def test_remote_display_clears_idle_and_unavailable_metadata(hass, display):
    _, coordinator = display
    coordinator.async_set_updated_data({**STATE, "logo_available": True})
    assert hass.states.get("media_player.tivimuse").attributes.get("entity_picture")
    coordinator.async_set_updated_data({**STATE, "state": "idle", "logo_available": True})
    entity = hass.states.get("media_player.tivimuse")
    assert entity.state == "idle"
    assert not entity.attributes.get("media_artist")
    assert not entity.attributes.get("entity_picture")
    coordinator.async_set_update_error(Exception("Offline"))
    assert hass.states.get("media_player.tivimuse").state == "unavailable"
    coordinator.async_set_updated_data(STATE)
    assert hass.states.get("media_player.tivimuse").attributes["media_artist"] == "ABC TV"


async def test_remote_logo_is_proxied_fitted_and_cached(display):
    player, coordinator = display
    coordinator.async_set_updated_data({**STATE, "logo_available": True})
    raw = BytesIO()
    Image.new("RGBA", (900, 150), "white").save(raw, "PNG")
    with patch.object(
        coordinator.client, "logo", return_value=(raw.getvalue(), "image/png")
    ) as logo:
        first = await player.async_get_media_image()
        assert first == await player.async_get_media_image()
        logo.assert_awaited_once_with(CHANNEL)
        image = Image.open(BytesIO(first[0]))
        assert image.size == (512, 512)
        assert image.getbbox() == (16, 216, 496, 296)
        assert player.media_image_remotely_accessible is False


async def test_slow_logo_cannot_become_another_channels_artwork(display):
    player, coordinator = display
    coordinator.async_set_updated_data({**STATE, "logo_available": True})
    entered, release = asyncio.Event(), asyncio.Event()
    raw = BytesIO()
    Image.new("RGBA", (100, 100), "white").save(raw, "PNG")

    async def slow_logo(channel):
        entered.set()
        await release.wait()
        return raw.getvalue(), "image/png"

    with patch.object(coordinator.client, "logo", side_effect=slow_logo):
        task = asyncio.create_task(player.async_get_media_image())
        await entered.wait()
        coordinator.async_set_updated_data(
            {**STATE, "channel_id": "tmc1:other", "logo_available": True}
        )
        release.set()
        assert await task == (None, None)


async def test_missing_logo_returns_not_found_in_ha_proxy(hass, display, hass_client):
    player, coordinator = display
    coordinator.async_set_updated_data({**STATE, "logo_available": True})
    with patch.object(coordinator.client, "logo", return_value=(b"broken image", "image/png")):
        client = await hass_client()
        response = await client.get(player.entity_picture)
        assert response.status == 404


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
