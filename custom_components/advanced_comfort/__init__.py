"""Config-entry setup for Advanced Comfort Controller."""

from homeassistant.const import Platform

from .const import DEFAULTS


async def async_setup_entry(hass, entry):
    config = {**DEFAULTS, **entry.data, **entry.options}
    platform = Platform.CLIMATE if config["kind"] == "temperature" else Platform.HUMIDIFIER
    await hass.config_entries.async_forward_entry_setups(entry, [platform])
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    platform = Platform.CLIMATE if entry.data["kind"] == "temperature" else Platform.HUMIDIFIER
    return await hass.config_entries.async_unload_platforms(entry, [platform])
