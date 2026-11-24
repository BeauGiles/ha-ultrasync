"""Defines the base UltraSync entity."""

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

# What the panel's web interface tells us about the hardware family.  These
# are the vendor values reported by the ultrasync library.
PANEL_MODELS = {
    "zerowire": ("Interlogix", "ZeroWire UltraSync"),
    "comnav": ("Hills", "ComNav UltraSync"),
    "xgen": ("Interlogix", "xGen UltraSync"),
    "xgen8": ("Interlogix", "xGen8 UltraSync"),
}


def panel_device_info(coordinator, entry_id: str, entry_name: str) -> DeviceInfo:
    """Describe the panel using what it reported when we logged in."""
    hub = coordinator.hub

    # Only report what the panel actually told us; a panel that was never
    # identified keeps the generic details
    manufacturer, model = PANEL_MODELS.get(hub.vendor, ("UltraSync", None))

    # Installer logins can also read these from the panel
    panel_info = getattr(coordinator, "panel_info", None) or {}

    sw_version = None
    if hub.version and hub.version != "0.000":
        sw_version = hub.version
        if hub.release and hub.release != "0":
            sw_version = f"{sw_version}-{hub.release}"

    # The panel's own firmware is more exact than its web interface version
    sw_version = panel_info.get("firmware") or sw_version

    extra = {}
    if panel_info.get("mac"):
        mac = format_mac(panel_info["mac"])
        extra["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
        extra["serial_number"] = mac

    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name=entry_name,
        manufacturer=manufacturer,
        model=model,
        sw_version=sw_version,
        hw_version=panel_info.get("hardware"),
        **extra,
        # Adds a "Visit" link to the device page
        configuration_url=hub.url,
    )


class UltraSyncEntity(CoordinatorEntity):
    """Base class for a UltraSync entity."""

    # Entity names are just the item's own name (for example "Front Door");
    # Home Assistant puts the device name in front of it
    _attr_has_entity_name = True

    def __init__(
        self,
        *,
        coordinator,
        entry_id: str,
        entry_name: str,
        name: str,
    ) -> None:
        """Initialize the UltraSync entity."""

        super().__init__(coordinator)

        self._entry_id = entry_id
        self._attr_name = name

        # Group every entity of this integration under one device, named after
        # what the user called the integration when setting it up
        self._attr_device_info = panel_device_info(coordinator, entry_id, entry_name)
