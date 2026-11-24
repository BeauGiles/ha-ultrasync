"""Provides the UltraSync DataUpdateCoordinator."""
import asyncio
from datetime import timedelta
import logging
import threading
import time

import requests

try:
    # Python 3.11+ has this built in; newer Home Assistant no longer ships
    # the async_timeout package
    from asyncio import timeout

except ImportError:
    from async_timeout import timeout

from homeassistant.const import CONF_HOST, CONF_PIN, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import ultrasync

from .const import DOMAIN, SENSOR_UPDATE_LISTENER

_LOGGER = logging.getLogger(__name__)

# The library only reads the outputs page when it logs in, so a ComNav
# panel's outputs are read again this often (and right after a command)
OUTPUT_REFRESH_SECONDS = 30

# How many reads in a row the panel must refuse, while still answering on the
# network, before we ask the user to log in again. A panel also refuses a
# login for a moment when it has run out of sessions, so one miss proves little.
AUTH_FAILURES_BEFORE_REAUTH = 3


def _read_poll_outcome(poll: asyncio.Future) -> None:
    """Read how a panel read ended, so a late error is not reported as unhandled."""
    # A read that ends after the timeout has nobody waiting on it anymore.
    if poll.cancelled():
        return

    error = poll.exception()
    if error is not None:
        _LOGGER.debug("UltraSync panel read failed: %s", error)


class UltraSyncDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching UltraSync data."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        config: dict,
        options: dict,
        config_entry: ConfigEntry,
    ):
        """Initialize global UltraSync data updater."""
        self.hub = ultrasync.UltraSync(
            user=config[CONF_USERNAME],
            pin=config[CONF_PIN],
            host=config[CONF_HOST],
        )

        self._init = False

        # Whether the panel answered on the network during the last failed
        # read, and how many reads in a row failed that way
        self._panel_reachable = False
        self._auth_failures = 0

        # Polls and alarm panel commands run in different worker threads, but
        # share one panel session; this lock makes them take turns
        self.hub_lock = threading.Lock()

        # The areas, zones and outputs from the last successful poll (used
        # by the alarm panels, binary sensors, switches and buttons)
        self.areas = []
        self.zones = []
        self.outputs = []

        # When the outputs were last read (monotonic seconds)
        self._outputs_read = 0.0

        # The panel read currently running in a worker thread (if any)
        self._poll = None

        # Used to track delta (for change tracking)
        self._area_delta = {}
        self._zone_delta = {}
        self._output_delta = {}
        self._history_delta = {}

        # The area sequence numbers when the history was last read
        self._history_sequences = None

        update_interval = timedelta(seconds=options[CONF_SCAN_INTERVAL])

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
            config_entry=config_entry,
        )

    async def _async_update_data(self) -> dict:
        """Fetch data from UltraSync Hub."""

        # initialize our response
        response = {}

        # A read that timed out keeps running in its worker thread, because
        # a timeout can not stop it. Skip this update until it ends, so
        # waiting threads don't pile up while the panel is down. On a
        # healthy panel every read ends long before the next update.
        if self._poll is not None and not self._poll.done():
            raise UpdateFailed("Still waiting on the last UltraSync panel read")

        self._poll = self.hass.async_add_executor_job(self._details)
        self._poll.add_done_callback(_read_poll_outcome)

        # The hub can sometimes take a very long time to respond; wait
        # (asyncio.wait never cancels self._poll, so it stays pending until
        # the thread really ends)
        async with timeout(10):
            await asyncio.wait((self._poll,))

        details = self._poll.result()

        # An empty reply means the panel could not be read (it is offline,
        # or the login was refused). Report a failed update so Home
        # Assistant shows the entities as unavailable, keeps the last
        # good data and tries again on the next poll.
        if not details:
            # A panel that answers but keeps refusing the login most likely
            # has a changed PIN or username: ask the user to log in again.
            # An offline panel only counts as a failed update.
            if self._panel_reachable:
                self._auth_failures += 1
            else:
                self._auth_failures = 0

            # The very first read has no earlier good data, so it does not
            # wait for repeated misses
            limit = 1 if not self._init else AUTH_FAILURES_BEFORE_REAUTH
            if self._auth_failures >= limit:
                raise ConfigEntryAuthFailed(
                    "The UltraSync panel refused the saved login"
                )

            raise UpdateFailed("Unable to read the UltraSync panel")

        self._auth_failures = 0

        # Update our details
        if details:
            # Keep the latest areas for the alarm panels
            self.areas = details["areas"]
            self.zones = details["zones"]
            self.outputs = details["outputs"]

            async_dispatcher_send(
                self.hass,
                SENSOR_UPDATE_LISTENER,
                details["areas"],
                details["zones"],
                details["outputs"],
                details["history_data"]
            )

            # Process zone data
            for zone in details["zones"]:
                if self._zone_delta.get(zone["bank"]) != zone["sequence"]:
                    self.hass.bus.fire(
                        "ultrasync_zone_update",
                        {
                            "sensor": zone["bank"] + 1,
                            "name": zone["name"],
                            "status": zone["status"],
                        },
                    )

                    # Update our sequence
                    self._zone_delta[zone["bank"]] = zone["sequence"]

                # Set our state:
                response["zone{:0>2}_state".format(zone["bank"] + 1)] = zone[
                    "status"
                ]

            # Process history data (if present)
            for history in details["history_data"]:
                history_name = history["area_name"]
                sensor_id = "history_name{}state".format(history_name)
                state_value = "{} by {} at {}".format(history["action"], history["user"], history["timestamp"])
                response[sensor_id] = state_value

                # Announce each history line once: on the first poll, then
                # whenever the area's latest line changes
                latest = (history["action"], history["user"], history["timestamp"])
                if self._history_delta.get(history_name) != latest:
                    self.hass.bus.fire(
                        "ultrasync_history_update",
                        {
                            "name": history_name,
                            "status": history["action"],
                            "timestamp": history["timestamp"],
                            "user": history["user"],
                        },
                    )

                    # Update our last seen line
                    self._history_delta[history_name] = latest

            # Process area data
            for area in details["areas"]:
                area_changed = self._area_delta.get(area["bank"]) != area["sequence"]
                if area_changed:
                    self.hass.bus.fire(
                        "ultrasync_area_update",
                        {
                            "area": area["bank"] + 1,
                            "name": area["name"],
                            "status": area["status"],
                        },
                    )

                    # Update our sequence
                    self._area_delta[area["bank"]] = area["sequence"]

                # Set our state:
                response["area{:0>2}_state".format(area["bank"] + 1)] = area[
                    "status"
                ]

            # Process output data (if present)
            output_index = 1
            for output in details["outputs"]:
                if self._output_delta.get(output["name"]) != output["state"]:
                    self.hass.bus.fire(
                        "ultrasync_output_update",
                        {
                            "name": output["name"],
                            "status": output["state"],
                        },
                    )

                    # Update our sequence
                    self._output_delta[output["name"]] = output["state"]

                # Set our state:
                response["output{}state".format(output_index)] = output[
                    "state"
                ]
                output_index += 1

        self._init = True

        # Return our response
        return response

    async def async_hub_call(self, method, *args, **kwargs) -> bool:
        """Run a panel command in a worker thread, between polls.

        Returns what the command returned (True when the panel accepted it).
        """

        def _call() -> bool:
            with self.hub_lock:
                return method(*args, **kwargs)

        return await self.hass.async_add_executor_job(_call)

    def mark_outputs_stale(self) -> None:
        """Read the outputs again on the next poll (after a command)."""
        self._outputs_read = 0.0

    def _details(self) -> dict:
        """Read the panel details, waiting for any alarm command to finish."""
        with self.hub_lock:
            details = self.hub.details(max_age_sec=0)
            if not details:
                self._panel_reachable = self._can_reach_panel()
                return details

            # Outputs are only read at login, so read them again now and then
            # (ComNav panels are the only ones that have them)
            if (
                self.hub.vendor == "comnav"
                and time.monotonic() - self._outputs_read >= OUTPUT_REFRESH_SECONDS
            ):
                if self.hub.output_control():
                    self._outputs_read = time.monotonic()
                    details["outputs"] = list(self.hub.outputs.values())

            # The library only reads the history page when it logs in. A
            # new history line comes with an area change (for example
            # someone arming), so read it again only then. A quiet panel
            # gets no extra requests.
            sequences = {area["bank"]: area["sequence"] for area in details["areas"]}
            if self._history_sequences is None:
                # First read: the history was just read while logging in
                self._history_sequences = sequences

            elif sequences != self._history_sequences and self.hub.history():
                # Only remember these areas once the history was read, so a
                # failed read is tried again on the next poll
                self._history_sequences = sequences
                details["history_data"] = list(self.hub.history_data.values())

            return details

    def _can_reach_panel(self) -> bool:
        """Return True if the panel's web server answers at all."""
        # Any HTTP answer (even an error page) shows the panel is online, so
        # the failed read was down to the login
        try:
            requests.get(
                self.hub.url, timeout=3, verify=self.hub.verify, allow_redirects=False
            )

        except requests.RequestException:
            return False

        return True
