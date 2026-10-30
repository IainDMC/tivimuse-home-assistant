"""Small asynchronous client; pairing keys stay in authorization headers."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


class TiviMuseError(Exception):
    """Generic device/API failure without private request details."""


class InvalidAuth(TiviMuseError):
    """Pairing key rejected."""


class DeviceUnavailable(TiviMuseError):
    """App closed, unreachable, or protocol unavailable."""


class CommandRejected(TiviMuseError):
    """The app rejected the requested operation."""


def base_url(host: str, port: int) -> str:
    host = host.strip()
    if not host or any(x in host for x in ("/", "@", "?", "#")) or not 1024 <= port <= 65535:
        raise ValueError("Enter a hostname/IP and valid local API port")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}"


class TiviMuseClient:
    def __init__(self, session: aiohttp.ClientSession, host: str, port: int, token: str):
        self.session = session
        self.url = base_url(host, port)
        self._token = token
        self.device_id: str | None = None

    async def _request(self, method: str, path: str, *, params=None, payload=None, image=False):
        try:
            async with self.session.request(
                method,
                self.url + path,
                headers={"Authorization": f"Bearer {self._token}"},
                params=params,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=25, connect=5),
            ) as response:
                if response.status == 401:
                    raise InvalidAuth("Pairing key rejected")
                if response.status in (400, 404, 409, 413, 415):
                    raise CommandRejected("Device rejected the request")
                if response.status != 200:
                    raise DeviceUnavailable("TiviMuse is unavailable")
                if image:
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        body.extend(chunk)
                        if len(body) > 4 * 1024 * 1024:
                            raise TiviMuseError("Logo too large")
                    return bytes(body), response.headers.get("Content-Type", "image/png")
                data = await response.json()
                if not isinstance(data, dict):
                    raise TiviMuseError("Invalid device response")
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            raise DeviceUnavailable("Cannot reach TiviMuse") from None

    async def info(self) -> dict[str, Any]:
        data = await self._request("GET", "/v1/info")
        if data.get("protocol") != 1 or not isinstance(data.get("device_id"), str):
            raise TiviMuseError("Unsupported TiviMuse API version")
        self.device_id = data["device_id"]
        return data

    async def state(self, after: str | None = None) -> dict[str, Any]:
        data = await self._request("GET", "/v1/state", params={"after": after} if after else None)
        if data.get("device_id") != self.device_id or not isinstance(data.get("revision"), str):
            raise TiviMuseError("Invalid device state")
        return data

    async def playlists(self):
        return (await self._request("GET", "/v1/playlists"))["items"]

    async def categories(self, playlist_id):
        return (await self._request("GET", "/v1/categories", params={"playlist_id": playlist_id}))[
            "items"
        ]

    async def channels(self, playlist_id, category_id=None, offset=0):
        params = {"playlist_id": playlist_id, "offset": offset, "limit": 100}
        if category_id is not None:
            params["category_id"] = category_id
        return await self._request("GET", "/v1/channels", params=params)

    async def command(self, action: str, **kwargs):
        return await self._request("POST", "/v1/command", payload={"action": action, **kwargs})

    async def logo(self, channel_id: str):
        return await self._request("GET", "/v1/logo", params={"channel_id": channel_id}, image=True)
