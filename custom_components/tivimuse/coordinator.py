"""Local-push updates through a bounded long-poll connection."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import InvalidAuth, TiviMuseClient, TiviMuseError

LOGGER = logging.getLogger(__name__)


class TiviMuseCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass, entry, client: TiviMuseClient, info: dict):
        super().__init__(hass, LOGGER, name="TiviMuse", config_entry=entry)
        self.client = client
        self.info = info
        self.entry = entry
        self._task = None

    async def _async_update_data(self):
        try:
            return await self.client.state()
        except InvalidAuth as error:
            raise ConfigEntryAuthFailed(str(error)) from error
        except TiviMuseError as error:
            raise UpdateFailed(str(error)) from error

    def start(self):
        self._task = self.hass.async_create_background_task(
            self._listen(), "TiviMuse local updates"
        )

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _listen(self):
        revision = None
        while True:
            try:
                started = asyncio.get_running_loop().time()
                state = await self.client.state(revision)
                if state["revision"] == revision:
                    elapsed = asyncio.get_running_loop().time() - started
                    if elapsed < 1:
                        await asyncio.sleep(1 - elapsed)
                revision = state["revision"]
                public = dict(state)
                public.pop("revision", None)
                if self.data and self.last_update_success and state.get("mode") == "live":
                    ignored = {
                        "revision",
                        "position_ms",
                        "position_updated_at",
                        "duration_ms",
                        "live_position_ms",
                    }
                    if {k: v for k, v in public.items() if k not in ignored} == {
                        k: v for k, v in self.data.items() if k not in ignored
                    }:
                        continue
                if public != self.data or not self.last_update_success:
                    self.async_set_updated_data(public)
            except InvalidAuth:
                self.async_set_update_error(UpdateFailed("Pairing key rejected"))
                self.entry.async_start_reauth(self.hass)
                return
            except TiviMuseError:
                revision = None
                self.async_set_update_error(UpdateFailed("TiviMuse is not reachable"))
                await asyncio.sleep(5)
