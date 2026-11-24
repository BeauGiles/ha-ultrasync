"""Binary sensors for UltraSync zones and panel problems."""

from typing import Any, Optional

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from ultrasync.common import ZoneStatus

from .const import CONF_ZONE_TYPES, DATA_COORDINATOR, DEFAULT_NAME, DOMAIN
from .coordinator import UltraSyncDataUpdateCoordinator
from .entity import UltraSyncEntity

# The panel reports problems as text: on a zone ("Low Battery") and on an area
# ("System Low Battery", "Battery Test Fail", "Sensor Tamper"). Each sensor
# below is on while any zone or area text matches one of its words. Texts
# are matched in this order, so "Battery Test Fail" counts as a battery
# problem only.
PROBLEMS = {
    "low_battery": (BinarySensorDeviceClass.BATTERY, ("battery",)),
    "tamper": (BinarySensorDeviceClass.TAMPER, ("tamper", "antimask")),
    "bypassed": (None, ("bypass", "inhibit")),
    "trouble": (
        BinarySensorDeviceClass.PROBLEM,
        ("trouble", "fault", "fail", "supervision"),
    ),
}

# The "System fault" sensor (key "trouble") is on for every fault the panel
# reports except a bypass, which is a choice rather than a fault. The panel's
# own wording is listed in its `faults` attribute.
FAULT_KEYS = ("low_battery", "tamper", "trouble")

# What an area's priority is when the panel has a trouble, tamper, battery or
# supervision condition (it stays set even while the area is armed, when the
# status text shows "Armed Away" instead)
AREA_PROBLEM_PRIORITY = 2


def classify_problem(text: Any) -> Optional[str]:
    """Return which kind of problem a status text reports, if any."""
    if not isinstance(text, str):
        return None

    text = text.lower()
    for key, (_, words) in PROBLEMS.items():
        if any(word in text for word in words):
            return key

    return None


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

    # What the user said each zone is (zone number as text -> device class)
    zone_types = entry.options.get(CONF_ZONE_TYPES, {})

    entities: list[BinarySensorEntity] = [
        UltraSyncZoneBinarySensor(
            coordinator,
            entry.entry_id,
            entry_name,
            zone,
            zone_types.get(str(zone["bank"] + 1)),
        )
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
        device_class, _ = PROBLEMS[key]
        self._attr_device_class = device_class

        # The name (and icon) come from strings.json and icons.json
        self._attr_translation_key = key

        # Battery and system fault are for checking the panel's health. Tamper
        # and bypassed zones stay with the main sensors, since they affect
        # the security of the system.
        if key in ("low_battery", "trouble"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_unique_id = f"{entry_id}_problem_{key}"

        super().__init__(
            coordinator=coordinator,
            entry_id=entry_id,
            entry_name=entry_name,
        )

    def _affected(self) -> list[str]:
        """Return the zones, areas and panel faults that report this problem."""
        keys = FAULT_KEYS if self._key == "trouble" else (self._key,)
        affected = []

        for zone in self.coordinator.zones:
            if classify_problem(zone.get("status")) in keys:
                name = (zone.get("name") or "").strip() or f"Zone {zone['bank'] + 1}"
                affected.append(f"{name}: {zone['status']}")

        for fault in self.coordinator.system_faults:
            if classify_problem(fault) in keys:
                affected.append(f"Panel: {fault}")

        for area in self.coordinator.areas:
            status = area.get("status")
            if classify_problem(status) in keys:
                name = (area.get("name") or "").strip() or f"Area {area['bank'] + 1}"
                affected.append(f"{name}: {status}")

        # The panel flags an area as having a problem even while the area is
        # armed and its status text shows something else. If nothing above
        # says what it is, report that so the sensor still turns on. An area
        # that reads "Ready" has nothing hidden: the flag is just the panel
        # echoing a fault listed above.
        if self._key == "trouble" and not affected:
            for area in self.coordinator.areas:
                if (
                    area.get("priority") == AREA_PROBLEM_PRIORITY
                    and area.get("status") != "Ready"
                ):
                    name = (area.get("name") or "").strip() or f"Area {area['bank'] + 1}"
                    affected.append(f"{name}: Problem reported by the panel")

        return affected

    @property
    def is_on(self) -> bool:
        """Return True if any zone or area reports this problem."""
        return bool(self._affected())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return which zones and areas report the problem."""
        key = "faults" if self._key == "trouble" else "reported_by"
        return {key: self._affected()}
