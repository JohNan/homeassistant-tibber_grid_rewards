"""Provides device actions for Tibber Grid Reward."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_ACTION_BASE_SCHEMA
from homeassistant.components.time import DOMAIN as TIME_DOMAIN, ATTR_TIME
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_ENTITY_ID, CONF_TYPE
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er, config_validation as cv

from .const import DOMAIN

ACTION_TYPES = {"set_value"}


async def async_get_actions(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    """List device actions for Tibber Grid Reward."""
    registry = er.async_get(hass)
    actions = []

    for entry in er.async_entries_for_device(registry, device_id):
        if entry.domain == TIME_DOMAIN and entry.platform == DOMAIN:
            actions.append(
                {
                    CONF_DEVICE_ID: device_id,
                    CONF_DOMAIN: DOMAIN,
                    CONF_ENTITY_ID: entry.entity_id,
                    CONF_TYPE: "set_value",
                }
            )

    return actions


async def async_get_action_capabilities(
    hass: HomeAssistant, config: dict[str, Any]
) -> dict[str, vol.Schema]:
    """List action capabilities."""
    if config[CONF_TYPE] == "set_value":
        return {
            "extra_fields": vol.Schema(
                {vol.Required(ATTR_TIME): cv.time}
            )
        }
    return {}


async def async_call_action_from_config(
    hass: HomeAssistant,
    config: dict[str, str],
    variables: dict[str, Any],
    context: Context | None,
) -> None:
    """Execute a device action."""
    await hass.services.async_call(
        TIME_DOMAIN,
        "set_value",
        {
            "entity_id": config[CONF_ENTITY_ID],
            "time": variables[ATTR_TIME],
        },
        blocking=True,
        context=context,
    )


ACTION_SCHEMA = DEVICE_ACTION_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_ENTITY_ID): cv.entity_id,
        vol.Required(CONF_TYPE): vol.In(ACTION_TYPES),
    }
)