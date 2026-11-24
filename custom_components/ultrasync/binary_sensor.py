"""Binary sensors for UltraSync zones and panel problems."""

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

from .const import DATA_COORDINATOR, DEFAULT_NAME, DOMAIN
from .coordinator import UltraSyncDataUpdateCoordinator
from .entity import UltraSyncEntity

# Zone status text, grouped by the kind of problem it reports. A zone shows
# only one status at a time (the first that applies), so a zone that is both
# open and tampered shows as "Not Ready".
PROBLEMS = {
    "tamper": (
        "Tamper",
        BinarySensorDeviceClass.TAMPER,
        ("Tamper", "Antimask"),
    ),
    "trouble": (
        "Trouble",
        BinarySensorDeviceClass.PROBLEM,
        ("Trouble", "Supervision Fault", "Test Fail", "Activity Fail"),
    ),
    "low_battery": (
        "Low battery",
        BinarySensorDeviceClass.BATTERY,
        ("Low Battery",),
    ),
    "bypassed": (
        "Zones bypassed",
        None,
        ("Inhibited",),
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one binary sensor for each zone, and the panel problem sensors."""
    coordinator: UltraSyncDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_COORDINATOR]
    entry_name = entry.data.get(CONF_NAME, DEFAULT_NAME)

    entities: list[BinarySensorEntity] = [
        UltraSyncZoneBinarySensor(coordinator, entry.entry_id, entry_name, zone)
        for zone in coordinator.zones
    ]
    entities.extend(
        UltraSyncProblemBinarySensor(coordinator, entry.entry_id, entry_name, key)
        for key in PROBLEMS
    )
    async_add_entities(entities)


class UltraSyncZoneBinarySensor(UltraSyncEntity, BinarySensorEntity):
    """One zone: on while the zone is not ready (open or triggered)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UltraSyncDataUpdateCoordinator,
        entry_id: str,
        entry_name: str,
        zone: dict[str, Any],
    ) -> None:
        """Initialize the binary sensor for one zone."""
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


class UltraSyncProblemBinarySensor(UltraSyncEntity, BinarySensorEntity):
    """On while any zone reports one kind of problem."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UltraSyncDataUpdateCoordinator,
        entry_id: str,
        entry_name: str,
        key: str,
    ) -> None:
        """Initialize a panel problem sensor."""
        self._key = key
        name, device_class, self._statuses = PROBLEMS[key]
        self._attr_device_class = device_class
        self._attr_unique_id = f"{entry_id}_problem_{key}"

        super().__init__(
            coordinator=coordinator,
            entry_id=entry_id,
            entry_name=entry_name,
            name=name,
        )

    def _affected(self) -> list[str]:
        """Return the names of the zones that report this problem."""
        return [
            (z.get("name") or "").strip() or f"Zone {z['bank'] + 1}"
            for z in self.coordinator.zones
            if z.get("status") in self._statuses
        ]

    @property
    def is_on(self) -> bool:
        """Return True if any zone reports this problem."""
        return bool(self._affected())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return which zones report the problem."""
        return {"zones": self._affected()}
