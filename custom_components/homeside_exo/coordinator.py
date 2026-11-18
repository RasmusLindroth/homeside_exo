"""DataUpdateCoordinator som pollar regulatorn."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .exosocket import ExoAuthError, ExoError, async_read

_LOGGER = logging.getLogger(__name__)


class ExoCoordinator(DataUpdateCoordinator[dict]):
    """Hämtar punkter från EXOsocket med jämna mellanrum."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        user: str,
        password: str,
        items: list[int],
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self._host = host
        self._user = user
        self._password = password
        self._items = items
        self._session = async_get_clientsession(hass)

    async def _async_update_data(self) -> dict:
        try:
            return await async_read(
                self._session, self._host, self._items, self._user, self._password
            )
        except ExoAuthError as ex:
            # Startar HA:s reauth-flöde (se config_flow.async_step_reauth).
            raise ConfigEntryAuthFailed(str(ex)) from ex
        except ExoError as ex:
            raise UpdateFailed(str(ex)) from ex
