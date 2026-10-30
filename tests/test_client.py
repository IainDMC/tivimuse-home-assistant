"""HTTP contract tests with a real local aiohttp device fixture."""

import importlib.util
import unittest
from pathlib import Path

import aiohttp
from aiohttp import web

spec = importlib.util.spec_from_file_location(
    "tivimuse_api_contract", Path(__file__).parents[1] / "custom_components/tivimuse/api.py"
)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
DEVICE = "c1047025-4ccd-40e1-a0bb-91d1c68d1ade"
ID_ONE = f"tmc1:{DEVICE}:1:MjM"
ID_TWO = f"tmc1:{DEVICE}:2:MjM"


class ClientContractTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.commands = []
        self.revision = "epoch:1"
        self.image = b"PNG fixture" + b"x" * 100_000
        app = web.Application()
        app.router.add_route("*", "/v1/{path}", self.handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        self.session = aiohttp.ClientSession()
        self.client = api.TiviMuseClient(self.session, "127.0.0.1", self.port, "test-pairing-key")

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()

    async def handle(self, request):
        if request.headers.get("Authorization") != "Bearer test-pairing-key":
            return web.Response(status=401)
        self.assertNotIn("token", request.query)
        path = request.match_info["path"]
        if path == "info":
            return web.json_response({"device_id": DEVICE, "protocol": 1, "version": "test"})
        if path == "state":
            self.assertIn(request.query.get("after"), (None, "epoch:0"))
            return web.json_response(
                {
                    "device_id": DEVICE,
                    "revision": self.revision,
                    "state": "playing",
                    "channel_id": ID_ONE,
                }
            )
        if path == "playlists":
            return web.json_response(
                {
                    "items": [
                        {"id": "playlist1", "name": "First"},
                        {"id": "playlist2", "name": "Second"},
                    ]
                }
            )
        if path == "channels":
            second = request.query["playlist_id"] == "playlist2"
            return web.json_response(
                {
                    "items": [{"id": ID_TWO if second else ID_ONE, "name": "ABC TV"}],
                    "next_offset": None,
                }
            )
        if path == "logo":
            response = web.StreamResponse(headers={"Content-Type": "image/png"})
            await response.prepare(request)
            for start in range(0, len(self.image), 1024):
                await response.write(self.image[start : start + 1024])
            await response.write_eof()
            return response
        if path == "command":
            data = await request.json()
            self.commands.append(data)
            if data.get("action") == "play_channel" and data.get("channel_id") not in (
                ID_ONE,
                ID_TWO,
            ):
                return web.Response(status=404)
            if data.get("action") == "seek" and data.get("seconds") == -1:
                return web.Response(status=409)
            return web.json_response({"accepted": True})
        return web.Response(status=404)

    async def test_duplicate_names_are_selected_by_exact_playlist_scoped_ids(self):
        await self.client.info()
        first = await self.client.channels("playlist1")
        second = await self.client.channels("playlist2")
        self.assertEqual(first["items"][0]["name"], second["items"][0]["name"])
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])
        await self.client.command("play_channel", channel_id=second["items"][0]["id"])
        self.assertEqual(self.commands, [{"action": "play_channel", "channel_id": ID_TWO}])

    async def test_stale_ids_and_unavailable_seek_are_not_silently_replaced(self):
        with self.assertRaises(api.CommandRejected):
            await self.client.command("play_channel", channel_id="removed")
        self.assertEqual(len(self.commands), 1)
        with self.assertRaises(api.CommandRejected):
            await self.client.command("seek", seconds=-1)

    async def test_state_revision_and_authentication(self):
        await self.client.info()
        self.assertEqual((await self.client.state("epoch:0"))["revision"], "epoch:1")
        bad = api.TiviMuseClient(self.session, "127.0.0.1", self.port, "wrong")
        with self.assertRaises(api.InvalidAuth):
            await bad.info()

    async def test_full_chunked_logo_is_read_and_tokens_are_not_in_urls(self):
        data, content_type = await self.client.logo(ID_ONE)
        self.assertEqual(self.image, data)
        self.assertEqual("image/png", content_type)

    def test_host_input_rejects_urls_credentials_and_invalid_ports(self):
        for host, port in [
            ("http://example.invalid", 42990),
            ("user@example.invalid", 42990),
            ("example.invalid", 80),
        ]:
            with self.assertRaises(ValueError):
                api.base_url(host, port)
        self.assertEqual("http://[fd00::1]:42990", api.base_url("fd00::1", 42990))


if __name__ == "__main__":
    unittest.main()
