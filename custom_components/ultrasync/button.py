"""Buttons that raise a fire, medical or panic alarm on the UltraSync panel."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from ultrasync import AlarmScene

from .const import DATA_COORDINATOR, DEFAULT_NAME, DOMAIN
from .coordinator import UltraSyncDataUpdateCoordinator
from .entity import UltraSyncEntity

# (key, alarm to raise); the names are in strings.json
ALARMS = (
    ("fire", AlarmScene.FIRE),
    ("medical", AlarmScene.MEDICAL),
    ("panic", AlarmScene.PANIC),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the alarm buttons."""
    coordinator: UltraSyncDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_COORDINATOR]
    entry_name = entry.data.get(CONF_NAME, DEFAULT_NAME)

    async_add_entities(
        UltraSyncAlarmButton(coordinator, entry.entry_id, entry_name, *alarm)
        for alarm in ALARMS
    )


class UltraSyncAlarmButton(UltraSyncEntity, ButtonEntity):
    """Raises one kind of alarm on the panel."""

    _attr_has_entity_name = True

    # These set off a real alarm, so they are opt-in
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: UltraSyncDataUpdateCoordinator,
        entry_id: str,
        entry_name: str,
        key: str,
        scene: str,
    ) -> None:
        """Initialize an alarm button."""
        self._scene = scene
        self._attr_unique_id = f"{entry_id}_button_{key}"
        self._attr_translation_key = key

        super().__init__(
            coordinator=coordinator,
            entry_id=entry_id,
            entry_name=entry_name,
        )

    async def async_press(self) -> None:
        """Raise the alarm."""
        if not await self.coordinator.async_hub_call(
            self.coordinator.hub.set_alarm, state=self._scene
        ):
            raise HomeAssistantError(f"UltraSync could not raise {self.name}")

        await self.coordinator.async_request_refresh()
