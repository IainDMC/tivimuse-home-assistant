"""Authenticated browser handoff to the Shield Web Manager."""

import re
from urllib.parse import urlencode, urlsplit

from aiohttp import web
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.components import frontend
from homeassistant.components.http.const import KEY_HASS_USER
from pathlib import Path

from .api import TiviMuseError
from .const import DOMAIN


class WebManagerView(HomeAssistantView):
    url = "/api/tivimuse/web_manager/{entry_id}"
    name = "api:tivimuse:web_manager"
    requires_auth = True

    async def get(self, request, entry_id):
        if not request[KEY_HASS_USER].is_admin:
            raise web.HTTPForbidden()
        entry = request.app["hass"].config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN or not entry.runtime_data:
            raise web.HTTPNotFound()
        client = entry.runtime_data.coordinator.client
        try:
            result = await client.web_manager_sign_in()
        except TiviMuseError:
            raise web.HTTPServiceUnavailable(text="TiviMuse Web Manager is unavailable.") from None
        port, code = result.get("port"), result.get("code")
        if type(port) is not int or not 1024 <= port <= 65535 or not isinstance(code, str) or not re.fullmatch(r"[0-9a-f]{48}", code):
            raise web.HTTPBadGateway()
        host = urlsplit(client.url).hostname
        if ":" in host:
            host = f"[{host}]"
        raise web.HTTPSeeOther(
            location=f"http://{host}:{port}/sign-in?{urlencode({'code': code})}",
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )


async def async_register_web_manager(hass):
    if hass.data.get("tivimuse_web_manager_registered"):
        return
    hass.http.register_view(WebManagerView)
    await hass.http.async_register_static_paths([
        StaticPathConfig("/tivimuse-web-manager.js", str(Path(__file__).with_name("web_manager.js")), False)
    ])
    frontend.async_register_built_in_panel(
        hass, "custom", frontend_url_path="tivimuse-settings", require_admin=True,
        config={"_panel_custom": {"name": "tivimuse-settings", "module_url": "/tivimuse-web-manager.js"}},
    )
    hass.data["tivimuse_web_manager_registered"] = True
