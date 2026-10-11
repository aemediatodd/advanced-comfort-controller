"""Standard humidifier entity for bidirectional humidity node control."""

from homeassistant.components.humidifier import HumidifierEntity, HumidifierEntityFeature

from .const import HUMIDITY_MODES
from .controller import ComfortController


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([AdvancedHygrostat(entry)])


class AdvancedHygrostat(ComfortController, HumidifierEntity):
    allowed_modes = HUMIDITY_MODES
    _attr_available_modes = HUMIDITY_MODES
    _attr_supported_features = HumidifierEntityFeature.MODES

    @property
    def is_on(self):
        return self._control_enabled

    @property
    def mode(self):
        return self.control_mode

    @property
    def current_humidity(self):
        return self.humidity

    @property
    def target_humidity(self):
        return self.target

    @property
    def min_humidity(self):
        return self.config["min_target"]

    @property
    def max_humidity(self):
        return self.config["max_target"]

    async def async_set_humidity(self, humidity):
        await self.async_set_target(humidity)

    async def async_set_mode(self, mode):
        await self.async_enable(self._control_enabled, mode)

    async def async_turn_on(self, **kwargs):
        await self.async_enable(True)

    async def async_turn_off(self, **kwargs):
        await self.async_enable(False)
