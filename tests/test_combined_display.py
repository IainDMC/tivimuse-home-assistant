"""Real HA lifecycle, foreground arbitration and service routing for one display."""

import asyncio
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from PIL import Image
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.tivimuse.api import DeviceUnavailable
from custom_components.tivimuse.const import CONF_TOKEN, DOMAIN
from custom_components.tivimuse.display_controls import BUTTONS, NUMBERS, SELECTS, SENSORS, SWITCHES

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
        assert hass.states.get(DISPLAY).state == "idle"
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
    assert state.state == "idle"
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


async def test_device_page_controls_exist_and_apply_without_reloading(hass, combined):
    entry, player = combined
    registry = er.async_get(hass)
    all_controls = {**SWITCHES, **SELECTS, **NUMBERS, **BUTTONS, **SENSORS}
    entities = {}
    for key in all_controls:
        matching = [
            e
            for e in registry.entities.values()
            if e.config_entry_id == entry.entry_id and e.unique_id == f"{DEVICE}_display_{key}"
        ]
        assert len(matching) == 1, key
        entities[key] = matching[0].entity_id
        assert hass.states.get(matching[0].entity_id) is not None
    coordinator = entry.runtime_data.coordinator
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entities["show_program_as_title"]}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.coordinator is coordinator
    assert player is entry.runtime_data.display
    assert not hass.states.get(DISPLAY).attributes.get("media_title")
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entities["show_progress"]}, blocking=True
    )
    await hass.async_block_till_done()
    assert not hass.states.get(DISPLAY).attributes.get("media_duration")
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": entities["channel_icon_scale"], "value": 65},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entities["icon_background"], "option": "black"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert player.options["channel_icon_scale"] == 65
    assert player.options["icon_background"] == "black"
    await hass.services.async_call(
        "button", "press", {"entity_id": entities["clear_artwork_cache"]}, blocking=True
    )
    assert hass.states.get(entities["native_connection"]).state == "Connected"


async def test_native_playback_still_has_shield_volume_and_power(hass, combined):
    _, player = combined
    calls = {
        name: async_mock_service(hass, "media_player", name)
        for name in ("volume_up", "volume_set", "turn_off")
    }
    await player.async_volume_up()
    await player.async_set_volume_level(0.3)
    await player.async_turn_off()
    assert calls["volume_up"][0].data == {"entity_id": SOURCE}
    assert calls["volume_set"][0].data == {"entity_id": SOURCE, "volume_level": 0.3}
    assert calls["turn_off"][0].data == {"entity_id": SOURCE}


async def test_generic_remote_player_without_android_app_id_supplies_media(hass, combined):
    foreground(hass, "org.smarttube.stable")
    hass.states.async_set(
        SOURCE,
        "playing",
        {"media_title": "Current video", "media_artist": "Video creator", "media_position": 32},
    )
    await hass.async_block_till_done()
    entity = hass.states.get(DISPLAY)
    assert entity.state == "playing"
    assert entity.attributes["media_title"] == "Current video"
    assert entity.attributes["media_artist"] == "Video creator"
    foreground(hass, "com.nuvio.tv")
    hass.states.async_set(
        SOURCE, "playing", {"media_title": "Current movie", "media_content_type": "movie"}
    )
    await hass.async_block_till_done()
    assert hass.states.get(DISPLAY).attributes["media_title"] == "Current movie"


async def test_native_cast_app_id_uses_identifiable_app_name(hass, combined):
    for package, name, title in [
        ("com.nuvio.tv", "Nuvio", "Colony"),
        ("org.smarttube.stable", "SmartTube", "Current video"),
    ]:
        foreground(hass, package)
        hass.states.async_set(
            SOURCE,
            "paused",
            {
                "app_id": "AndroidNativeApp",
                "app_name": name,
                "media_title": title,
                "media_artist": "2026",
            },
        )
        await hass.async_block_till_done()
        assert hass.states.get(DISPLAY).state == "paused"
        assert hass.states.get(DISPLAY).attributes["media_title"] == title


async def test_programme_progress_replaces_buffer_progress_and_maps_seek(hass, combined):
    entry, player = combined
    now = dt_util.parse_datetime("2026-11-01T10:20:00Z")
    start = now.timestamp() * 1000 - 1200000
    with patch("custom_components.tivimuse.combined_display.dt_util.utcnow", return_value=now):
        entry.runtime_data.coordinator.async_set_updated_data(
            {
                **NATIVE,
                "mode": "timeshift",
                "state": "paused",
                "can_seek": True,
                "duration_ms": 1800000,
                "position_ms": 300000,
                "live_position_ms": 1800000,
                "programme": {
                    "title": "One-hour programme",
                    "start_ms": start,
                    "end_ms": start + 3600000,
                },
            }
        )
        entity = hass.states.get(DISPLAY)
        assert entity.attributes["media_duration"] == 3600
        assert entity.attributes["media_position"] == 1200
        assert player.native.media_duration == 1800
        assert player.native.media_position == 300
        with patch.object(
            entry.runtime_data.coordinator.client, "command", new_callable=AsyncMock
        ) as command:
            await player.async_media_seek(600)
            command.assert_awaited_once_with("seek", seconds=1200)
    later = dt_util.parse_datetime("2026-11-01T10:20:20Z")
    with patch("custom_components.tivimuse.combined_display.dt_util.utcnow", return_value=later):
        player._programme_tick(later)
        assert hass.states.get(DISPLAY).attributes["media_position"] == 1220
        entry.runtime_data.coordinator.async_set_updated_data(
            {
                **NATIVE,
                "mode": "timeshift",
                "duration_ms": 1800000,
                "position_ms": 300000,
                "programme": None,
            }
        )
        assert hass.states.get(DISPLAY).attributes["media_duration"] == 0
        assert hass.states.get(DISPLAY).attributes["media_position"] == 0


async def test_app_change_explicitly_clears_remote_fields_before_new_media(hass, combined):
    _, player = combined
    player.options = {**player.options, "nuvio_logo": "/local/icons/nuvio.png"}
    foreground(hass, "com.nuvio.tv")
    await hass.async_block_till_done()
    attributes = hass.states.get(DISPLAY).attributes
    assert attributes["media_title"] == ""
    assert attributes["media_artist"] == ""
    assert attributes["media_content_id"] == ""
    assert attributes["media_duration"] == 0
    assert attributes["media_position"] == 0
    assert attributes["entity_picture"] == "/local/icons/nuvio.png"


async def test_smarttube_artwork_and_logo_are_unmodified_even_with_blur_on(hass, combined):
    _, player = combined
    player.options = {
        **player.options,
        "smarttube_artwork": "source_artwork",
        "smarttube_logo": "/local/icons/smarttube.png",
        "poster_blurred_background": True,
        "poster_canvas_width": 200,
    }
    foreground(hass, "org.smarttube.stable")
    await hass.async_block_till_done()
    assert hass.states.get(DISPLAY).attributes["entity_picture"] == "/local/icons/smarttube.png"
    hass.states.async_set(
        SOURCE,
        "playing",
        {
            "app_id": "AndroidNativeApp",
            "app_name": "SmartTube",
            "media_title": "Unmodified thumbnail",
            "entity_picture": "https://example.test/original-wide.jpg",
        },
    )
    await hass.async_block_till_done()
    assert (
        hass.states.get(DISPLAY).attributes["entity_picture"]
        == "https://example.test/original-wide.jpg"
    )


async def test_native_logo_is_published_only_when_bytes_are_ready(hass, combined, hass_client):
    entry, player = combined
    raw = BytesIO()
    Image.new("RGBA", (800, 200), "blue").save(raw, "PNG")
    with patch.object(
        player.native,
        "async_get_media_image",
        side_effect=[(None, None), (raw.getvalue(), "image/png")],
    ) as logo:
        entry.runtime_data.coordinator.async_set_updated_data({**NATIVE, "logo_available": True})
        assert hass.states.get(DISPLAY).attributes["entity_picture"] == ""
        await player._native_art_task
        entity = hass.states.get(DISPLAY)
        assert entity.attributes["entity_picture"].startswith("/api/media_player_proxy/")
        client = await hass_client()
        response = await client.get(entity.attributes["entity_picture"])
        assert response.status == 200
        image = Image.open(BytesIO(await response.read()))
        assert image.getpixel((256, 256)) == (0, 0, 255, 255)
        assert logo.await_count == 2


async def test_original_app_name_aliases_and_artwork_priority_are_preserved(hass, combined):
    _, player = combined
    player.options = {
        **player.options,
        "app_names": {"org.smarttube.stable": "YouTube"},
        "app_logos": {"YouTube": "/local/icons/youtube.png"},
        "app_artwork_profiles": {"smarttube": "app_logo,source_artwork,tmdb_poster"},
    }
    foreground(hass, "org.smarttube.stable")
    hass.states.async_set(
        SOURCE,
        "playing",
        {
            "app_id": "AndroidNativeApp",
            "app_name": "YouTube",
            "media_title": "Original alias",
            "entity_picture": "https://example.test/thumbnail.jpg",
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get(DISPLAY).attributes["app_name"] == "YouTube"
    assert hass.states.get(DISPLAY).attributes["media_title"] == "Original alias"
    assert hass.states.get(DISPLAY).attributes["entity_picture"] == "/local/icons/youtube.png"


async def test_late_channel_logo_does_not_replace_new_channel_logo(hass, combined):
    entry, player = combined
    entered, release = asyncio.Event(), asyncio.Event()
    first_channel = NATIVE["channel_id"]
    images = {}
    for color in ("red", "blue"):
        raw = BytesIO()
        Image.new("RGBA", (200, 200), color).save(raw, "PNG")
        images[color] = raw.getvalue()

    async def load():
        if player.native.media_content_id == first_channel:
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return images["red"], "image/png"
        return images["blue"], "image/png"

    with patch.object(player.native, "async_get_media_image", side_effect=load):
        entry.runtime_data.coordinator.async_set_updated_data({**NATIVE, "logo_available": True})
        await entered.wait()
        old_task = player._native_art_task
        entry.runtime_data.coordinator.async_set_updated_data(
            {**NATIVE, "channel_id": "tmc1:new-channel", "logo_available": True}
        )
        await player._native_art_task
        current_url = player.media_image_url
        release.set()
        await old_task
        assert player.media_image_url == current_url
        data, _ = await player.async_get_media_image()
        assert Image.open(BytesIO(data)).getpixel((256, 256)) == (0, 0, 255, 255)


async def test_original_json_settings_validate_and_persist(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE,
        data={CONF_HOST: "test-device", CONF_PORT: 42990, CONF_TOKEN: "test-key"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"combined_display": False, "app_names_json": "[1,2]"}
    )
    assert result["errors"]["base"] == "invalid_display_json"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "combined_display": False,
            "app_names_json": '{"org.smarttube.stable":"YouTube"}',
            "app_artwork_profiles_json": '{"smarttube":["app_logo","source_artwork"]}',
        },
    )
    assert result["type"] == "create_entry"
    assert entry.options["app_names"] == {"org.smarttube.stable": "YouTube"}
    assert entry.options["app_artwork_profiles"]["smarttube"] == ["app_logo", "source_artwork"]


async def test_programme_progress_is_available_without_seekable_stream(hass, combined):
    entry, player = combined
    now = dt_util.parse_datetime("2026-11-01T10:20:00Z")
    start = now.timestamp() * 1000 - 1200000
    with patch("custom_components.tivimuse.combined_display.dt_util.utcnow", return_value=now):
        entry.runtime_data.coordinator.async_set_updated_data(
            {
                **NATIVE,
                "can_seek": False,
                "programme": {"title": "Programme", "start_ms": start, "end_ms": start + 3600000},
            }
        )
        assert player.supported_features & MediaPlayerEntityFeature.SEEK
        assert hass.states.get(DISPLAY).attributes["media_duration"] == 3600
        assert hass.states.get(DISPLAY).attributes["media_position"] == 1200
        with patch.object(
            entry.runtime_data.coordinator.client, "command", new_callable=AsyncMock
        ) as command:
            with pytest.raises(HomeAssistantError, match="cannot seek"):
                await player.async_media_seek(600)
            command.assert_not_awaited()
