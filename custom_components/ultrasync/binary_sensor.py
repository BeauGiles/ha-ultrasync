"""Binary sensors for UltraSync zones."""

from typing import Any, Optional

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from ultrasync.common import ZoneStatus

from .const import CONF_ZONE_TYPES, DATA_COORDINATOR, DEFAULT_NAME, DOMAIN
from .coordinator import UltraSyncDataUpdateCoordinator
from .entity import UltraSyncEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one binary sensor for each zone."""
    coordinator: UltraSyncDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_COORDINATOR]
    entry_name = entry.data.get(CONF_NAME, DEFAULT_NAME)

    # What the user said each zone is (zone number as text -> device class)
    zone_types = entry.options.get(CONF_ZONE_TYPES, {})

    async_add_entities(
        UltraSyncZoneBinarySensor(
            coordinator,
            entry.entry_id,
            entry_name,
            zone,
            zone_types.get(str(zone["bank"] + 1)),
        )
        for zone in coordinator.zones
    )


class UltraSyncZoneBinarySensor(UltraSyncEntity, BinarySensorEntity):
    """One zone: on while the zone is not ready (open or triggered)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UltraSyncDataUpdateCoordinator,
        entry_id: str,
        entry_name: str,
        zone: dict[str, Any],
        zone_type: Optional[str] = None,
    ) -> None:
        """Initialize the binary sensor for one zone."""
        try:
            self._attr_device_class = BinarySensorDeviceClass(zone_type)
        except ValueError:
            # Not chosen (or not a class we know): a plain on/off sensor
            self._attr_device_class = None

        # The zone's position on the panel (starting at 0)
        self._bank = zone["bank"]
        self._attr_unique_id = f"{entry_id}_zone_binary_{self._bank}"

        super().__init__(
            coordinator=coordinator,
            entry_id=entry_id,
            entry_name=entry_name,
            name=(zone.get("name") or "").strip() or f"Zone {self._bank + 1}",
        )

    @property
    def _zone(self) -> Optional[dict[str, Any]]:
        """Return this zone from the latest poll, if the panel still has it."""
        return next((z for z in self.coordinator.zones if z["bank"] == self._bank), None)

    @property
    def available(self) -> bool:
        """The zone is unavailable when the panel is, or no longer has it."""
        return super().available and self._zone is not None

    @property
    def is_on(self) -> Optional[bool]:
        """Return True when the zone is not ready."""
        zone = self._zone
        if zone is None:
            return None

        return zone.get("status") == ZoneStatus.NOT_READY

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the panel's own status text for the zone."""
        zone = self._zone
        return {"status": zone.get("status")} if zone else {}
