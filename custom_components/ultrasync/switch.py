"""Switches for UltraSync outputs, area chime and zone bypass."""

from typing import Any, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from ultrasync.common import NX595EVendor

from .const import DATA_COORDINATOR, DEFAULT_NAME, DOMAIN
from .coordinator import UltraSyncDataUpdateCoordinator
from .entity import UltraSyncEntity

# Panels that can bypass a zone (the library has no bypass for xGen)
BYPASS_VENDORS = (NX595EVendor.ZEROWIRE, NX595EVendor.XGEN8, NX595EVendor.COMNAV)

# The status a bypassed zone shows
BYPASSED_STATUS = "Inhibited"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switches the panel supports."""
    coordinator: UltraSyncDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_COORDINATOR]
    entry_name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    args = (coordinator, entry.entry_id, entry_name)

    entities: list[SwitchEntity] = [
        UltraSyncChimeSwitch(*args, area) for area in coordinator.areas
    ]

    # Only ComNav panels have output control; the library lists no outputs
    # for the others
    entities.extend(
        UltraSyncOutputSwitch(*args, number, output)
        for number, output in enumerate(coordinator.outputs, start=1)
    )

    if coordinator.hub.vendor in BYPASS_VENDORS:
        entities.extend(UltraSyncBypassSwitch(*args, zone) for zone in coordinator.zones)

    async_add_entities(entities)


class UltraSyncSwitch(UltraSyncEntity, SwitchEntity):
    """Shared behaviour: send a command, then refresh."""

    _attr_has_entity_name = True

    async def _async_send(self, method, *args, **kwargs) -> None:
        """Send a panel command and refresh, raising an error if it was refused."""
        if not await self.coordinator.async_hub_call(method, *args, **kwargs):
            raise HomeAssistantError(f"UltraSync could not update {self.name}")

        await self.coordinator.async_request_refresh()


class UltraSyncChimeSwitch(UltraSyncSwitch):
    """The chime of one area."""

    def __init__(
        self,
        coordinator: UltraSyncDataUpdateCoordinator,
        entry_id: str,
        entry_name: str,
        area: dict[str, Any],
    ) -> None:
        """Initialize the chime switch for one area."""
        self._bank = area["bank"]
        self._attr_unique_id = f"{entry_id}_chime_{self._bank}"
        area_name = (area.get("name") or "").strip() or f"Area {self._bank + 1}"

        # "<area> chime", from strings.json
        self._attr_translation_key = "chime"
        self._attr_translation_placeholders = {"area": area_name}

        super().__init__(
            coordinator=coordinator,
            entry_id=entry_id,
            entry_name=entry_name,
        )

    @property
    def is_on(self) -> Optional[bool]:
        """Return True if the area's chime is on."""
        area = next((a for a in self.coordinator.areas if a["bank"] == self._bank), None)
        if area is None:
            return None

        return bool(area.get("states", {}).get("chime"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the chime on."""
        # Areas are numbered from 1 when sending, but banks start at 0
        await self._async_send(
            self.coordinator.hub.set_chime, areas=self._bank + 1, state=True
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the chime off."""
        await self._async_send(
            self.coordinator.hub.set_chime, areas=self._bank + 1, state=False
        )


class UltraSyncOutputSwitch(UltraSyncSwitch):
    """One output (relay) of the panel."""

    def __init__(
        self,
        coordinator: UltraSyncDataUpdateCoordinator,
        entry_id: str,
        entry_name: str,
        number: int,
        output: dict[str, Any],
    ) -> None:
        """Initialize the switch for one output."""
        # Outputs are numbered from 1, in the order the panel lists them
        self._number = number
        self._attr_unique_id = f"{entry_id}_output_switch_{number}"

        # The name is the one set on the panel; the key gives the icon
        self._attr_translation_key = "output"

        super().__init__(
            coordinator=coordinator,
            entry_id=entry_id,
            entry_name=entry_name,
            name=(output.get("name") or "").strip() or f"Output {number}",
        )

    @property
    def is_on(self) -> Optional[bool]:
        """Return True if the output is on."""
        outputs = self.coordinator.outputs
        if self._number > len(outputs):
            return None

        return str(outputs[self._number - 1].get("state")) == "1"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the output on."""
        self.coordinator.mark_outputs_stale()
        await self._async_send(
            self.coordinator.hub.set_output_control, output=self._number, state=1
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the output off."""
        self.coordinator.mark_outputs_stale()
        await self._async_send(
            self.coordinator.hub.set_output_control, output=self._number, state=0
        )


class UltraSyncBypassSwitch(UltraSyncSwitch):
    """Bypass (inhibit) one zone."""

    # Bypassing a zone weakens the alarm, so this is opt-in
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: UltraSyncDataUpdateCoordinator,
        entry_id: str,
        entry_name: str,
        zone: dict[str, Any],
    ) -> None:
        """Initialize the bypass switch for one zone."""
        self._bank = zone["bank"]
        self._attr_unique_id = f"{entry_id}_bypass_{self._bank}"
        zone_name = (zone.get("name") or "").strip() or f"Zone {self._bank + 1}"

        # "<zone> bypass", from strings.json
        self._attr_translation_key = "bypass"
        self._attr_translation_placeholders = {"zone": zone_name}

        super().__init__(
            coordinator=coordinator,
            entry_id=entry_id,
            entry_name=entry_name,
        )

    @property
    def is_on(self) -> Optional[bool]:
        """Return True if the zone is bypassed."""
        zone = next((z for z in self.coordinator.zones if z["bank"] == self._bank), None)
        if zone is None:
            return None

        return zone.get("status") == BYPASSED_STATUS

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Bypass the zone."""
        # Zones are numbered from 1 when sending, but banks start at 0
        await self._async_send(
            self.coordinator.hub.set_zone_bypass, zone=self._bank + 1, state=True
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop bypassing the zone."""
        await self._async_send(
            self.coordinator.hub.set_zone_bypass, zone=self._bank + 1, state=False
        )
