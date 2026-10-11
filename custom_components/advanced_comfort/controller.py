"""Shared controller with cancellable HA actions and fail-safe shutdown."""

import asyncio
from datetime import timedelta
import logging
from time import monotonic

from homeassistant.core import Context, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.script import Script, async_validate_actions_config
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import DEFAULTS, DOMAIN, NAME
from .engine import finite, select_node

_LOGGER = logging.getLogger(__name__)


class ComfortController(RestoreEntity):
    """Controls actions; hardware states are never claimed as measured output."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry):
        self.config = {**DEFAULTS, **entry.data, **entry.options}
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": self.config["name"],
            "manufacturer": NAME,
            "model": self.config["kind"],
        }
        self.target = self.config["target"]
        self.control_mode = "auto"
        self._control_enabled = False
        self.measurement = None
        self.temperature = None
        self.humidity = None
        self.active_node = None
        self.status = "off"
        self.last_error = None
        self._key = None
        self._last_transition = float("-inf")
        self._lock = asyncio.Lock()
        self._scripts = {}
        self._action_task = None
        self._running_script = None
        self._closed = False
        self._retry_at = 0
        self._applied = False

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        old = await self.async_get_last_state()
        if old:
            try:
                restored = finite(old.attributes.get("controller_target", self.target))
                if self.config["min_target"] <= restored <= self.config["max_target"]:
                    self.target = restored
            except (ValueError, TypeError):
                pass
            # Deliberately start disabled after restart/reload. Never replay an
            # old heating rule before the new sensor/config has been checked.
            mode = old.attributes.get("controller_mode", "auto")
            if mode in self.allowed_modes:
                self.control_mode = mode
        sequences = {n["id"]: n["actions"] for n in self.config["nodes"]}
        sequences["__safe__"] = self.config["safe_actions"]
        for key, actions in sequences.items():
            validated = await async_validate_actions_config(self.hass, cv.SCRIPT_SCHEMA(actions))
            self._scripts[key] = Script(
                self.hass,
                validated,
                f"{self.config['name']}: {key}",
                DOMAIN,
                script_mode="restart",
            )
        sensors = [self.config["sensor"]]
        if self.config.get("secondary_sensor"):
            sensors.append(self.config["secondary_sensor"])
        self.async_on_remove(async_track_state_change_event(self.hass, sensors, self._sensor_changed))
        self.async_on_remove(async_track_time_interval(self.hass, self._timer, timedelta(seconds=10)))
        await self.async_evaluate()

    @callback
    def _sensor_changed(self, event):
        self.hass.async_create_task(self.async_evaluate())

    async def _timer(self, now):
        await self.async_evaluate()

    def _read(self, entity_id, temperature=False):
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        try:
            value = finite(state.state)
            if (dt_util.utcnow() - state.last_reported).total_seconds() > self.config["sensor_timeout"]:
                return None
            if temperature:
                unit = state.attributes.get("unit_of_measurement")
                if unit not in ("°C", "°F", "K"):
                    return None
                value = TemperatureConverter.convert(value, unit, self.hass.config.units.temperature_unit)
            elif not 0 <= value <= 100:
                return None
            return value
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self):
        return {
            "controller_target": self.target,
            "controller_mode": self.control_mode,
            "controller_status": self.status,
            "active_node": self.active_node["name"] if self.active_node else None,
            "active_node_id": self.active_node["id"] if self.active_node else None,
            "actions_applied": self._applied,
            "delta": None if self.measurement is None else round(self.measurement - self.target, 3),
            "measured_temperature": self.temperature,
            "measured_humidity": self.humidity,
            "primary": self.config["primary"],
            "auxiliaries": self.config["auxiliaries"],
            "last_error": self.last_error,
        }

    async def async_set_target(self, value):
        try:
            value = finite(value)
        except (ValueError, TypeError) as err:
            raise HomeAssistantError("Target must be finite") from err
        if not self.config["min_target"] <= value <= self.config["max_target"]:
            raise HomeAssistantError("Target is outside configured limits")
        self.target = value
        await self.async_evaluate()

    async def async_enable(self, enabled, mode=None):
        if mode is not None:
            if mode not in self.allowed_modes:
                raise HomeAssistantError("Unsupported controller mode")
            self.control_mode = mode
        self._control_enabled = enabled
        await self.async_evaluate()

    async def _stop_actions(self):
        if self._running_script:
            await self._running_script.async_stop()
        if self._action_task and not self._action_task.done():
            self._action_task.cancel()
            try:
                await self._action_task
            except asyncio.CancelledError:
                pass
        self._action_task = None
        self._running_script = None

    def _variables(self):
        return {
            "target": self.target,
            "current": self.measurement,
            "delta": None if self.measurement is None else self.measurement - self.target,
            "temperature": self.temperature,
            "humidity": self.humidity,
            "primary": self.config["primary"],
            "auxiliaries": self.config["auxiliaries"],
            "controller_mode": self.control_mode,
        }

    async def async_evaluate(self):
        async with self._lock:
            if self._closed:
                return
            is_temp = self.config["kind"] == "temperature"
            self.measurement = self._read(self.config["sensor"], is_temp)
            secondary = self.config.get("secondary_sensor")
            second = self._read(secondary, not is_temp) if secondary else None
            self.temperature = self.measurement if is_temp else second
            self.humidity = second if is_temp else self.measurement
            node = None
            desired_status = "off"
            if self._control_enabled:
                if self.measurement is None:
                    desired_status = "sensor_fault"
                else:
                    node = select_node(
                        self.config["nodes"],
                        self.measurement - self.target,
                        self.control_mode,
                        self.active_node["id"] if self.active_node else None,
                        self.config["hysteresis"],
                    )
                    desired_status = "active" if node else "no_match"
            key = (node["id"], self.target, self.control_mode) if node else ("__safe__", desired_status)
            now = monotonic()
            if key == self._key and not self.last_error:
                self.status = desired_status
                self.async_write_ha_state()
                return
            if self.last_error and key == self._key and now < self._retry_at:
                self.async_write_ha_state()
                return
            # Off, missing sensors, and unconfigured gaps bypass dwell. Starting
            # again still waits, preventing immediate compressor restarts.
            if node and now - self._last_transition < self.config["min_dwell"]:
                self.status = "waiting"
                self.async_write_ha_state()
                return
            await self._stop_actions()
            self.active_node = node
            self.status = desired_status
            self._key = key
            self._last_transition = now
            self.last_error = None
            self._applied = False
            script = self._scripts[node["id"] if node else "__safe__"]
            self._running_script = script
            self._action_task = self.hass.async_create_background_task(
                self._run(script, self._variables()), f"{DOMAIN} actions {self.entity_id}"
            )
            self.async_write_ha_state()

    async def _run(self, script, variables):
        try:
            await script.async_run(variables, context=Context())
            self._applied = True
        except asyncio.CancelledError:
            raise
        except Exception as err:  # HA action/templating integrations can raise arbitrary errors.
            self.last_error = str(err)
            self.status = "action_error"
            self._retry_at = monotonic() + max(30, self.config["min_dwell"])
            _LOGGER.exception("Action failed for %s", self.entity_id)
            if script is not self._scripts["__safe__"]:
                try:
                    self._running_script = self._scripts["__safe__"]
                    await self._running_script.async_run(variables, context=Context())
                except Exception:
                    _LOGGER.exception("Fail-safe action also failed for %s", self.entity_id)
        finally:
            if not self._closed:
                self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        async with self._lock:
            self._closed = True
            await self._stop_actions()
            if "__safe__" in self._scripts:
                try:
                    async with asyncio.timeout(15):
                        await self._scripts["__safe__"].async_run(self._variables(), context=Context())
                except Exception:
                    _LOGGER.exception("Shutdown actions failed for %s", self.entity_id)
        await super().async_will_remove_from_hass()
