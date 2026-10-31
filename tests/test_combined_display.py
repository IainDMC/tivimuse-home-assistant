"""Real HA lifecycle, foreground arbitration and service routing for one display."""

import asyncio
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import entity_registry as er
from PIL import Image
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.tivimuse.api import DeviceUnavailable
from custom_components.tivimuse.const import CONF_TOKEN, DOMAIN

DEVICE = "combined-test-device"
SOURCE = "media_player.shield_metadata"
APP = "media_player.shield_foreground"
DISPLAY = "media_player.tivimuse_remote_3_display"
NATIVE = {
    "state": "playing",
    "channel_id": "tmc1:combined:playlist:channel",
    "channel": "ABC TV",
    "programme": {"title": "Native programme"},
    "mode": "live",
    "revision": "1",
    "device_id": DEVICE,
}


def foreground(hass, app, state="playing"):
    hass.states.async_set(APP, state, {"app_id": app})


def playback(hass, app, title, state="playing"):
    hass.states.async_set(
        SOURCE,
        state,
        {
            "app_id": app,
            "media_title": title,
            "media_artist": "Source subtitle",
            "media_duration": 600,
            "media_position": 120,
            "media_content_type": "movie",
            "supported_features": 16389,
        },
    )


@pytest.fixture
async def combined(hass):
    foreground(hass, "app.opentv.debug")
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE,
        data={CONF_HOST: "test-device", CONF_PORT: 42990, CONF_TOKEN: "test-key"},
        options={"combined_display": True, "source_entity": SOURCE, "app_entity": APP},
    )
    entry.add_to_hass(hass)

    async def state(after=None):
        if after:
            await asyncio.Event().wait()
        return NATIVE

    with (
        patch(
            "custom_components.tivimuse.api.TiviMuseClient.info",
            return_value={"device_id": DEVICE, "protocol": 1},
        ),
        patch("custom_components.tivimuse.api.TiviMuseClient.state", side_effect=state),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry, hass.data["media_player"].get_entity(DISPLAY)
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_one_display_switches_apps_and_rejects_lagging_source(hass, combined):
    _, player = combined
    assert player is not None
    assert hass.states.get(DISPLAY).attributes["media_title"] == "Native programme"
    # Foreground switches first; old live-TV and stale source metadata must disappear.
    foreground(hass, "com.nuvio.app")
    playback(hass, "com.teamsmart.videomanager.tv", "Stale video")
    await hass.async_block_till_done()
    assert hass.states.get(DISPLAY).state == "idle"
    assert not hass.states.get(DISPLAY).attributes.get("media_title")
    playback(hass, "com.nuvio.app", "Nuvio movie", "paused")
    await hass.async_block_till_done()
    entity = hass.states.get(DISPLAY)
    assert entity.state == "paused"
    assert entity.attributes["media_title"] == "Nuvio movie"
    assert entity.attributes["nuvio_content_type"] == "Movie"
    foreground(hass, "com.teamsmart.videomanager.tv")
    await hass.async_block_till_done()
    assert not hass.states.get(DISPLAY).attributes.get("media_title")
    playback(hass, "com.teamsmart.videomanager.tv", "SmartTube video")
    await hass.async_block_till_done()
    assert hass.states.get(DISPLAY).attributes["media_title"] == "SmartTube video"
    foreground(hass, "app.opentv.debug")
    await hass.async_block_till_done()
    assert hass.states.get(DISPLAY).attributes["media_title"] == "Native programme"
    foreground(hass, "launcher")
    await hass.async_block_till_done()
    assert not hass.states.get(DISPLAY).attributes.get("entity_picture")
    assert not hass.states.get(DISPLAY).attributes.get("media_title")


async def test_live_tv_never_looks_up_a_poster_and_routes_controls(hass, combined):
    entry, player = combined
    player.options = {**player.options, "tmdb_enabled": True, "tmdb_token": "test-token"}
    with (
        patch(
            "custom_components.tivimuse.combined_display.tmdb_poster", new_callable=AsyncMock
        ) as posters,
        patch.object(
            entry.runtime_data.coordinator.client, "command", new_callable=AsyncMock
        ) as command,
    ):
        await player.async_media_pause()
        command.assert_awaited_once_with("pause")
        entry.runtime_data.coordinator.async_set_updated_data(
            {
                **NATIVE,
                "programme": {"title": "Next live programme"},
            }
        )
        await hass.async_block_till_done()
        assert hass.states.get(DISPLAY).attributes["media_title"] == "Next live programme"
        posters.assert_not_awaited()
    player.options = {**player.options, "tmdb_enabled": False}
    foreground(hass, "com.nuvio.app")
    playback(hass, "com.nuvio.app", "A movie")
    await hass.async_block_till_done()
    calls = async_mock_service(hass, "media_player", "media_pause")
    await player.async_media_pause()
    assert len(calls) == 1
    assert calls[0].data["entity_id"] == SOURCE


async def test_display_starts_when_tivimuse_is_closed(hass):
    foreground(hass, "com.teamsmart.videomanager.tv")
    playback(hass, "com.teamsmart.videomanager.tv", "Video while TiviMuse is closed")
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE,
        data={CONF_HOST: "closed-device", CONF_PORT: 42990, CONF_TOKEN: "test-key"},
        options={"combined_display": True, "source_entity": SOURCE, "app_entity": APP},
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.tivimuse.api.TiviMuseClient.info", side_effect=DeviceUnavailable()
        ),
        patch(
            "custom_components.tivimuse.api.TiviMuseClient.state", side_effect=DeviceUnavailable()
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get("media_player.tivimuse").state == "unavailable"
        assert (
            hass.states.get(DISPLAY).attributes["media_title"] == "Video while TiviMuse is closed"
        )
        assert hass.states.get(DISPLAY).state == "playing"
        foreground(hass, "app.opentv.debug")
        await hass.async_block_till_done()
        assert hass.states.get(DISPLAY).state == "unavailable"
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_options_preserve_pairing_and_reject_a_display_as_source(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE,
        data={CONF_HOST: "test-device", CONF_PORT: 42990, CONF_TOKEN: "private-test-key"},
    )
    entry.add_to_hass(hass)
    foreground(hass, "app.opentv.debug")
    playback(hass, "com.nuvio.app", "Movie")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "combined_display": True,
            "source_entity": SOURCE,
            "app_entity": APP,
        },
    )
    assert result["type"] == "create_entry"
    assert entry.data[CONF_TOKEN] == "private-test-key"
    assert entry.options["source_entity"] == SOURCE
    invalid = er.async_get(hass).async_get_or_create(
        "media_player",
        DOMAIN,
        "display-loop",
        config_entry=entry,
    )
    hass.states.async_set(invalid.entity_id, "playing")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "combined_display": True,
            "source_entity": invalid.entity_id,
            "app_entity": APP,
        },
    )
    assert result["errors"]["base"] == "invalid_display_source"


async def test_foreground_unavailable_does_not_keep_previous_media(hass, combined):
    foreground(hass, "app.opentv.debug", "unavailable")
    await hass.async_block_till_done()
    state = hass.states.get(DISPLAY)
    assert state.state == "unavailable"
    assert not state.attributes.get("media_title")


async def test_late_poster_is_discarded_after_switching_apps(hass, combined):
    _, player = combined
    player.options = {**player.options, "tmdb_enabled": True, "tmdb_token": "test-token"}
    entered, release = asyncio.Event(), asyncio.Event()
    raw = BytesIO()
    Image.new("RGBA", (200, 600), "red").save(raw, "PNG")

    async def delayed(*args):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            # Model an I/O library that completes despite cancellation.
            await release.wait()
        return "https://image.tmdb.org/test-poster"

    with (
        patch("custom_components.tivimuse.combined_display.tmdb_poster", side_effect=delayed),
        patch(
            "custom_components.tivimuse.combined_display.fetch_artwork", return_value=raw.getvalue()
        ),
    ):
        foreground(hass, "com.nuvio.app")
        playback(hass, "com.nuvio.app", "Slow movie")
        await entered.wait()
        task = player._art_task
        foreground(hass, "launcher")
        await hass.async_block_till_done()
        release.set()
        await task
        assert player.media_image_url is None
        assert await player.async_get_media_image() == (None, None)
