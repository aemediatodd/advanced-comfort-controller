"""Standard climate entity for temperature node control."""

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACAction, HVACMode

from .const import TEMPERATURE_MODES
from .controller import ComfortController


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([AdvancedThermostat(entry)])


class AdvancedThermostat(ComfortController, ClimateEntity):
    allowed_modes = TEMPERATURE_MODES
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )
    _attr_target_temperature_step = 0.1

    @property
    def temperature_unit(self):
        return self.hass.config.units.temperature_unit

    @property
    def current_temperature(self):
        return self.temperature

    @property
    def current_humidity(self):
        return self.humidity

    @property
    def target_temperature(self):
        return self.target

    @property
    def min_temp(self):
        return self.config["min_target"]

    @property
    def max_temp(self):
        return self.config["max_target"]

    @property
    def hvac_mode(self):
        return HVACMode(self.control_mode) if self.enabled else HVACMode.OFF

    @property
    def hvac_action(self):
        if not self.enabled:
            return HVACAction.OFF
        if not self.active_node or not self._applied or self.last_error:
            return HVACAction.IDLE
        return {
            "cooling": HVACAction.COOLING,
            "heating": HVACAction.HEATING,
            "fan": HVACAction.FAN,
            "drying": HVACAction.DRYING,
        }.get(self.active_node.get("activity"), HVACAction.IDLE)

    async def async_set_temperature(self, **kwargs):
        if "temperature" in kwargs:
            await self.async_set_target(kwargs["temperature"])

    async def async_set_hvac_mode(self, hvac_mode):
        await self.async_enable(hvac_mode != HVACMode.OFF, None if hvac_mode == HVACMode.OFF else hvac_mode)

    async def async_turn_on(self):
        await self.async_enable(True)

    async def async_turn_off(self):
        await self.async_enable(False)
