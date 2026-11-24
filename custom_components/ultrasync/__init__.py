"""The Interlogix/Hills ComNav UltraSync Hub component."""

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from ultrasync import AlarmScene
import voluptuous as vol

from .const import (
    DATA_COORDINATOR,
    DATA_UNDO_UPDATE_LISTENER,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SENSORS,
    SERVICE_AWAY,
    SERVICE_DISARM,
    SERVICE_STAY,
    SERVICE_FIRE,
    SERVICE_MEDICAL,
    SERVICE_PANIC,
    SERVICE_BYPASS,
    SERVICE_UNBYPASS,
    SERVICE_SWITCH
)
from .coordinator import UltraSyncDataUpdateCoordinator

PLATFORMS = ["sensor", "alarm_control_panel", "binary_sensor", "switch", "button"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the UltraSync integration."""
    hass.data.setdefault(DOMAIN, {})

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up UltraSync from a config entry."""
    if not entry.options:
        options = {
            CONF_SCAN_INTERVAL: entry.data.get(
                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
            ),
        }
        hass.config_entries.async_update_entry(entry, options=options)

    coordinator = UltraSyncDataUpdateCoordinator(
        hass,
        config=entry.data,
        options=entry.options,
        config_entry=entry,
    )

    # Raises ConfigEntryNotReady if the panel is offline, and starts a
    # re-login prompt if the panel refuses the saved details
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_COORDINATOR: coordinator,
        DATA_UNDO_UPDATE_LISTENER: [],
        SENSORS: {},
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for setting changes only once setup has worked. A setup that
    # fails part way is never unloaded, so a listener added earlier would
    # stay behind (one more each retry) and reload the entry several times.
    hass.data[DOMAIN][entry.entry_id][DATA_UNDO_UPDATE_LISTENER].append(
        entry.add_update_listener(_async_update_listener)
    )

    _async_register_services(hass, coordinator)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )

    if unload_ok:
        for unsub in hass.data[DOMAIN][entry.entry_id][DATA_UNDO_UPDATE_LISTENER]:
            unsub()
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


def _async_register_services(
    hass: HomeAssistant,
    coordinator: UltraSyncDataUpdateCoordinator,
) -> None:
    """Register integration-level services."""

    async def _send(method, *args, **kwargs) -> None:
        """Send a command between polls, and refresh.

        Raises an error if the panel refused it, so the caller sees it fail.
        """
        if not await coordinator.async_hub_call(method, *args, **kwargs):
            raise HomeAssistantError("UltraSync did not accept the command")

        await coordinator.async_request_refresh()

    def _alarm_service(scene: str):
        """Return a service handler that sets every area to a scene."""

        async def handler(call: ServiceCall) -> None:
            await _send(coordinator.hub.set_alarm, state=scene)

        return handler

    async def bypass(call: ServiceCall) -> None:
        """Service call to bypass a zone in UltraSync Hub."""
        await _send(coordinator.hub.set_zone_bypass, state=True, zone=call.data["zone"])

    async def unbypass(call: ServiceCall) -> None:
        """Service call to unbypass a zone in UltraSync Hub."""
        await _send(coordinator.hub.set_zone_bypass, state=False, zone=call.data["zone"])

    async def switch(call: ServiceCall) -> None:
        """Service call to switch on/off an output control in UltraSync Hub."""
        # Outputs are only read now and then, so read them again after this
        coordinator.mark_outputs_stale()
        await _send(
            coordinator.hub.set_output_control,
            output=call.data["output"],
            state=call.data["state"],
        )

    for service, scene in (
        (SERVICE_AWAY, AlarmScene.AWAY),
        (SERVICE_STAY, AlarmScene.STAY),
        (SERVICE_FIRE, AlarmScene.FIRE),
        (SERVICE_MEDICAL, AlarmScene.MEDICAL),
        (SERVICE_PANIC, AlarmScene.PANIC),
        (SERVICE_DISARM, AlarmScene.DISARMED),
    ):
        hass.services.async_register(
            DOMAIN, service, _alarm_service(scene), schema=vol.Schema({})
        )

    # The zone selector can send a number like 1.0; the panel wants a whole one
    zone_schema = vol.Schema({vol.Required("zone"): vol.Coerce(int)})
    hass.services.async_register(DOMAIN, SERVICE_BYPASS, bypass, schema=zone_schema)
    hass.services.async_register(DOMAIN, SERVICE_UNBYPASS, unbypass, schema=zone_schema)
    hass.services.async_register(
        DOMAIN,
        SERVICE_SWITCH,
        switch,
        schema=vol.Schema(
            {
                vol.Required("output"): vol.Coerce(int),
                vol.Required("state"): vol.Coerce(int),
            }
        ),
    )


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
