"""HomeSide EXO (Regin ControllerWeb) – Home Assistant-integration.

Läser datapunkter från regulatorns EXOsocket-WebSocket och exponerar dem som
sensorer. Endast läsning.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USER,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import ExoCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]

POINTS_FILE = Path(__file__).parent / "points.json"


def load_points() -> dict[str, dict]:
    """Ladda punktdefinitionen (delas med CLI-klienten)."""
    with open(POINTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def sensor_points(points: dict[str, dict]) -> dict[str, dict]:
    """Punkter som ska bli sensorer (icke-larm)."""
    return {k: v for k, v in points.items() if v.get("group") != "alarm"}


def base_id(entry: ConfigEntry) -> str:
    """Stabil bas för unika ID:n: värdnamnet (entry.unique_id).

    Överlever att integrationen tas bort och läggs till igen, till skillnad från
    entry_id som är nytt varje gång.
    """
    return entry.unique_id or entry.entry_id


def scan_interval(entry: ConfigEntry) -> int:
    return entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )


@callback
def _async_migrate_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Flytta äldre entry_id-baserade ID:n till värdnamnsbaserade (idempotent)."""
    new_base = base_id(entry)
    old_base = entry.entry_id
    if new_base == old_base:
        return

    ent_reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if not ent.unique_id.startswith(f"{old_base}_"):
            continue
        new_uid = f"{new_base}_{ent.unique_id[len(old_base) + 1:]}"
        if ent_reg.async_get_entity_id(ent.domain, DOMAIN, new_uid):
            continue  # finns redan – rör inte
        ent_reg.async_update_entity(ent.entity_id, new_unique_id=new_uid)

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, old_base)})
    if device and not dev_reg.async_get_device(identifiers={(DOMAIN, new_base)}):
        dev_reg.async_update_device(device.id, new_identifiers={(DOMAIN, new_base)})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Sätt upp integrationen från en config entry."""
    _async_migrate_ids(hass, entry)

    points = await hass.async_add_executor_job(load_points)
    items = [int(k) for k in sensor_points(points)]

    coordinator = ExoCoordinator(
        hass,
        host=entry.data[CONF_HOST],
        user=entry.data[CONF_USER],
        password=entry.data[CONF_PASSWORD],
        items=items,
        scan_interval=scan_interval(entry),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "points": points,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Ladda om när options (uppdateringsintervall) ändras.
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Ta bort en config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
