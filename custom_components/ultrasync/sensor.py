"""Monitor the Interlogix/Hills ComNav UltraSync Hub."""

import logging
from typing import Callable, List

from datetime import datetime
from typing import Optional

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, EntityCategory
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.util import dt as dt_util

from .entity import UltraSyncEntity
from .const import (
    DATA_COORDINATOR,
    DATA_UNDO_UPDATE_LISTENER,
    DOMAIN,
    SENSOR_UPDATE_LISTENER,
    SENSORS,
)
from .coordinator import UltraSyncDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Icons for each kind of sensor
ICON_AREA = "mdi:shield-home"
ICON_ZONE = "mdi:motion-sensor"
ICON_OUTPUT = "mdi:electric-switch"
ICON_HISTORY = "mdi:history"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Callable[[List[Entity], bool], None],
) -> None:
    """Set up UltraSync sensor based on a config entry."""
    coordinator: UltraSyncDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]

    # At least one sensor must be pre-created or Home Assistant will not
    # call any updates
    hass.data[DOMAIN][entry.entry_id][SENSORS]["area01_state"] = UltraSyncSensor(
        coordinator,
        entry.entry_id,
        entry.data[CONF_NAME],
        "area01_state",
        "Area 1 status",
        name_suffix=" status",
        icon=ICON_AREA,
    )

    async_add_entities([hass.data[DOMAIN][entry.entry_id][SENSORS]["area01_state"]])

    @callback
    def _auto_manage_sensors(areas: dict, zones: dict, outputs: dict, history_data: dict) -> None:
        """Dynamically create/delete sensors based on what was detected by the hub."""

        _LOGGER.debug(
            "Entering _auto_manage_sensors with %d history item(s), %d area(s), %d zone(s) and %d output(s)",
            len(history_data),
            len(areas),
            len(zones),
            len(outputs)
        )

        # our list of sensors to add
        new_sensors = []

        # A pointer to our sensors
        sensors = hass.data[DOMAIN][entry.entry_id][SENSORS]

        # Track our detected sensors (for automatic updates if required)
        detected_sensors = set()

        for meta in areas:
            bank_no = meta["bank"]
            sensor_id = "area{:0>2}_state".format(bank_no + 1)
            detected_sensors.add(sensor_id)
            if sensor_id not in sensors:
                # hash our entry
                sensors[sensor_id] = UltraSyncSensor(
                    coordinator,
                    entry.entry_id,
                    entry.data[CONF_NAME],
                    sensor_id,
                    # Friendly Name
                    "Area {} status".format(bank_no + 1),
                    name_suffix=" status",
                    icon=ICON_AREA,
                )

                # Add our new area sensor
                new_sensors.append(sensors[sensor_id])
                _LOGGER.debug(
                    "Detected %s.Area%dState", entry.data[CONF_NAME], bank_no + 1
                )

            # Update our meta information
            for key, value in meta.items():
                sensors[sensor_id][key] = value

        for meta in zones:
            bank_no = meta["bank"]
            sensor_id = "zone{:0>2}_state".format(bank_no + 1)
            detected_sensors.add(sensor_id)
            if sensor_id not in sensors:
                # hash our entry
                sensors[sensor_id] = UltraSyncSensor(
                    coordinator,
                    entry.entry_id,
                    entry.data[CONF_NAME],
                    sensor_id,
                    # Friendly Name
                    "Zone {} status".format(bank_no + 1),
                    name_suffix=" status",
                    icon=ICON_ZONE,
                )

                # Add our new zone sensor
                new_sensors.append(sensors[sensor_id])
                _LOGGER.debug(
                    "Detected %s.Zone%dState", entry.data[CONF_NAME], bank_no + 1
                )

            # Update our meta information
            for key, value in meta.items():
                sensors[sensor_id][key] = value

        output_index = 1
        for meta in outputs:
            output_name = meta["name"]
            sensor_id = "output{}state".format(output_index)
            detected_sensors.add(sensor_id)
            if sensor_id not in sensors:
                # hash our entry
                sensors[sensor_id] = UltraSyncSensor(
                    coordinator,
                    entry.entry_id,
                    entry.data[CONF_NAME],
                    sensor_id,
                    # Friendly Name
                    "Output {} status".format(output_index),
                    name_suffix=" status",
                    icon=ICON_OUTPUT,
                )

                # Add our new output sensor
                new_sensors.append(sensors[sensor_id])
                _LOGGER.debug(
                    "Detected %s.Output%dState", entry.data[CONF_NAME], output_index
                )
            
            # Update our meta information
            for key, value in meta.items():
                sensors[sensor_id][key] = value

            output_index += 1

        for meta in history_data:
            history_name = meta["area_name"]
            sensor_id = "history_name{}state".format(history_name)
            detected_sensors.add(sensor_id)
            if sensor_id not in sensors:
                # hash our entry
                sensors[sensor_id] = UltraSyncHistorySensor(
                    coordinator,
                    entry.entry_id,
                    entry.data[CONF_NAME],
                    sensor_id,
                    # Friendly Name
                    "{} history".format(history_name),
                    icon=ICON_HISTORY,
                )

                # Add our new history sensor
                new_sensors.append(sensors[sensor_id])
                _LOGGER.debug(
                    "Detected %s.%s", entry.data[CONF_NAME], sensor_id
                )
            
            # Update our meta information
            for key, value in meta.items():
                sensors[sensor_id][key] = value

        if new_sensors:
            # Add our newly detected sensors
            async_add_entities(new_sensors)

        for sensor_id in set(sensors.keys()).difference(detected_sensors):
            # Tidy up sensors leaving our listing
            entry.async_create_task(hass, sensors[sensor_id].async_remove())
            del sensors[sensor_id]

    # register our callback which will be called the second we make a
    # connection to our panel
    hass.data[DOMAIN][entry.entry_id][DATA_UNDO_UPDATE_LISTENER].append(
        async_dispatcher_connect(hass, SENSOR_UPDATE_LISTENER, _auto_manage_sensors)
    )


class UltraSyncSensor(UltraSyncEntity, SensorEntity):
    """Representation of a UltraSync sensor."""

    # These repeat what the alarm panel and binary sensors already show, so
    # they are listed under Diagnostics on the device page
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: UltraSyncDataUpdateCoordinator,
        entry_id: str,
        entry_name: str,
        sensor_type: str,
        sensor_name: str,
        name_suffix: str = "",
        icon: Optional[str] = None,
    ):
        """Initialize a new UltraSync sensor."""

        self._sensor_type = sensor_type

        # Shown when the panel has no name for this item, and appended to the
        # panel's name when it does
        self._entry_name = entry_name
        self._fallback_name = sensor_name
        self._name_suffix = name_suffix
        self._attr_icon = icon
        self._unique_id = f"{entry_id}_{sensor_type}"

        # Initialize our Attributes
        self.__attributes = {}

        super().__init__(
            coordinator=coordinator,
            entry_id=entry_id,
            entry_name=entry_name,
            name=sensor_name,
        )

    def __setitem__(self, key, value):
        """Set our sensor attributes."""
        self.__attributes[key] = value

    @property
    def name(self) -> str:
        """Return the panel's name for this item, or a generic one."""
        # The panel's own name is read from the latest poll, so renaming
        # a zone or area on the panel shows up here
        panel_name = self.__attributes.get("name")
        if isinstance(panel_name, str) and panel_name.strip():
            return f"{panel_name.strip()}{self._name_suffix}"

        return self._fallback_name

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._unique_id

    @property
    def extra_state_attributes(self):
        """Return the state attributes of the sensor."""
        return self.__attributes

    @property
    def native_value(self):
        """Return the state of the sensor."""
        value = self.coordinator.data.get(self._sensor_type)
        if value is None:
            _LOGGER.warning("Unable to locate value for %s", self._sensor_type)
            return None

        return value


class UltraSyncHistorySensor(UltraSyncSensor):
    """The time of the latest history line for an area.

    The action, user and area name are in the attributes.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> Optional[datetime]:
        """Return when the latest history line happened."""
        timestamp = self.extra_state_attributes.get("timestamp")
        if not isinstance(timestamp, str):
            return None

        parsed = dt_util.parse_datetime(timestamp)
        if parsed is None:
            return None

        # The panel gives its own clock time without a time zone; take it to
        # be in the time zone Home Assistant is set to
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())

        return parsed
