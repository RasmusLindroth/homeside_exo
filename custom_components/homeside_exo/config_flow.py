"""Config flow (UI-inställningar) för HomeSide EXO."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    AUTH_CHECK_ITEM,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TEMPLATE,
    CONF_USER,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    SUPPORTED_TEMPLATES,
)
from .exosocket import (
    ERR_ACCESS_DENIED,
    ExoAuthError,
    ExoError,
    async_get_templates,
    async_read,
)

_INTERVAL = vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL))


async def _async_validate(
    hass: HomeAssistant, host: str, user: str, password: str
) -> str | None:
    """Testa anslutning + inloggning. Returnerar felnyckel eller None."""
    session = async_get_clientsession(hass)
    try:
        result = await async_read(session, host, [AUTH_CHECK_ITEM], user, password)
    except ExoAuthError:
        return "invalid_auth"
    except ExoError:
        return "cannot_connect"
    _val, err = result.get(AUTH_CHECK_ITEM, (None, None))
    if err == ERR_ACCESS_DENIED:
        return "invalid_auth"
    return None


class HomeSideExoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Hantera konfiguration via UI."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: ConfigEntry | None = None
        self._pending: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            error = await _async_validate(
                self.hass, host, user_input[CONF_USER], user_input[CONF_PASSWORD]
            )
            if error:
                errors["base"] = error
            else:
                try:
                    templates = await async_get_templates(
                        async_get_clientsession(self.hass), host
                    )
                except ExoError:
                    templates = []
                supported = [t for t in templates if t in SUPPORTED_TEMPLATES]
                self._pending = {
                    CONF_HOST: host,
                    CONF_USER: user_input[CONF_USER],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    # Startvärde; ändras sedan via options-flödet.
                    CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                    CONF_TEMPLATE: (supported or templates or [None])[0],
                }
                if supported:
                    return self.async_create_entry(title=host, data=self._pending)
                return await self.async_step_unsupported_template()

        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(CONF_USER, default=defaults.get(CONF_USER, "")): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): _INTERVAL,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_unsupported_template(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Varna för okänd regulatormall – punktindexen kan betyda något annat."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._pending[CONF_HOST], data=self._pending
            )
        return self.async_show_form(
            step_id="unsupported_template",
            data_schema=vol.Schema({}),
            description_placeholders={
                "template": self._pending.get(CONF_TEMPLATE) or "okänd",
                "supported": ", ".join(sorted(SUPPORTED_TEMPLATES)),
            },
        )

    # --- Reauth: startas av HA när inloggningen slutar fungera ---------------

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entry = self._reauth_entry
        assert entry is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _async_validate(
                self.hass,
                entry.data[CONF_HOST],
                user_input[CONF_USER],
                user_input[CONF_PASSWORD],
            )
            if error:
                errors["base"] = error
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_USER: user_input[CONF_USER],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        schema = vol.Schema(
            {
                vol.Required(CONF_USER, default=entry.data.get(CONF_USER, "")): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"host": entry.data[CONF_HOST]},
        )

    # --- Options ------------------------------------------------------------

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HomeSideExoOptionsFlow(config_entry)


class HomeSideExoOptionsFlow(OptionsFlow):
    """Ändra uppdateringsintervall utan att lägga till integrationen igen."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        # Sparas under eget namn: nyare HA sätter self.config_entry själv och
        # varnar om man skriver över det.
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._entry.options.get(
            CONF_SCAN_INTERVAL,
            self._entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        schema = vol.Schema(
            {vol.Required(CONF_SCAN_INTERVAL, default=current): _INTERVAL}
        )
        return self.async_show_form(step_id="init", data_schema=schema)
