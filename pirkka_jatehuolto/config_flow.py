"""Config flow for Pirkanmaan Jätehuolto."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    PirkkaApiClient,
    PirkkaApiError,
    PirkkaCannotConnect,
    PirkkaInvalidAuth,
    PirkkaUnsupportedFlow,
)
from .const import CONF_PASSWORD, CONF_USERNAME, DOMAIN


class PirkkaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Pirkanmaan Jätehuolto."""

    VERSION = 1

    _reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle first step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            await self.async_set_unique_id(username)
            self._abort_if_unique_id_configured()

            errors = await self._validate_credentials(user_input)
            if not errors:
                return self.async_create_entry(
                    title=f"Pirkanmaan Jätehuolto ({username})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self._credentials_schema(user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Handle reauthentication trigger."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Confirm reauthentication with updated credentials."""
        errors: dict[str, str] = {}

        if self._reauth_entry is None:
            return self.async_abort(reason="unknown")

        defaults = {
            CONF_USERNAME: self._reauth_entry.data.get(CONF_USERNAME, ""),
            CONF_PASSWORD: "",
        }

        if user_input is not None:
            errors = await self._validate_credentials(user_input)
            if not errors:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            defaults.update({CONF_USERNAME: user_input[CONF_USERNAME], CONF_PASSWORD: ""})

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self._credentials_schema(defaults),
            errors=errors,
        )

    async def _validate_credentials(self, data: dict[str, str]) -> dict[str, str]:
        """Validate credentials with a real login + fetch."""
        api = PirkkaApiClient(
            session=async_get_clientsession(self.hass),
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
        )

        try:
            await api.fetch_bins()
        except PirkkaInvalidAuth:
            return {"base": "invalid_auth"}
        except PirkkaUnsupportedFlow:
            return {"base": "unsupported_flow"}
        except PirkkaCannotConnect:
            return {"base": "cannot_connect"}
        except PirkkaApiError:
            return {"base": "unknown"}
        except Exception:  # noqa: BLE001
            return {"base": "unknown"}

        return {}

    @staticmethod
    @callback
    def _credentials_schema(defaults: dict[str, str] | None = None) -> vol.Schema:
        """Return credentials form schema."""
        defaults = defaults or {}
        return vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
                vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
            }
        )
