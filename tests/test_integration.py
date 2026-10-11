"""Integration and lifecycle tests using real HA services and config flows."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.script import async_validate_actions_config
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.advanced_comfort.const import DOMAIN
from custom_components.advanced_comfort.engine import validate_node


def config(kind="temperature"):
    return {
        "name": "Room",
        "kind": kind,
        "sensor": "sensor.room",
        "primary": "switch.main",
        "auxiliaries": ["fan.desk"],
        "target": 24 if kind == "temperature" else 50,
        "min_target": 5 if kind == "temperature" else 0,
        "max_target": 40 if kind == "temperature" else 100,
        "min_dwell": 0,
        "hysteresis": 0.1,
        "sensor_timeout": 60,
        "nodes": [
            {
                "id": "boost",
                "name": "Boost",
                "lower": 1,
                "activity": "cooling",
                "actions": [
                    {"action": "test_device.apply", "data": {"temperature": "{{ target - 2 }}", "fan": 100}},
                    {"action": "test_device.apply", "data": {"fan_entity": "{{ auxiliaries[0] }}"}},
                ],
            },
            {
                "id": "gentle",
                "name": "Gentle",
                "upper": 1,
                "activity": "fan",
                "actions": [{"action": "test_device.apply", "data": {"fan": 25}}],
            },
        ],
        "safe_actions": [{"action": "test_device.apply", "data": {"off": True}}],
    }


async def settle(hass):
    await hass.async_block_till_done()
    # Include controller background scripts (HA intentionally excludes background
    # tasks from async_block_till_done until their service calls are scheduled).
    for _ in range(4):
        await asyncio.sleep(0)
        await hass.async_block_till_done()


async def setup(hass, conf=None):
    conf = conf or config()
    calls = []

    @callback
    def handle(call):
        calls.append(dict(call.data))

    hass.services.async_register("test_device", "apply", handle)
    unit = "°C" if conf["kind"] == "temperature" else "%"
    hass.states.async_set("sensor.room", conf["target"] + 2, {"unit_of_measurement": unit})
    entry = MockConfigEntry(domain=DOMAIN, data=conf, title="Room")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)
    platform = "climate" if conf["kind"] == "temperature" else "humidifier"
    state = next(s for s in hass.states.async_all(platform) if s.attributes.get("primary") == "switch.main")
    calls.clear()
    return entry, state.entity_id, calls


async def test_temperature_actions_template_and_no_repeated_commands(hass):
    entry, eid, calls = await setup(hass)
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": eid, "hvac_mode": "auto"}, blocking=True
    )
    await settle(hass)
    assert calls == [{"temperature": 22, "fan": 100}, {"fan_entity": "fan.desk"}]
    assert hass.states.get(eid).attributes["active_node"] == "Boost"
    hass.states.async_set("sensor.room", 26.1, {"unit_of_measurement": "°C"})
    await settle(hass)
    assert len(calls) == 2
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": eid, "temperature": 25}, blocking=True
    )
    await settle(hass)
    assert calls[-2]["temperature"] == 23
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_humidity_controller(hass):
    entry, eid, calls = await setup(hass, config("humidity"))
    await hass.services.async_call("humidifier", "turn_on", {"entity_id": eid}, blocking=True)
    await settle(hass)
    assert calls[0]["temperature"] == 48
    await hass.services.async_call(
        "humidifier", "set_humidity", {"entity_id": eid, "humidity": 55}, blocking=True
    )
    await settle(hass)
    assert calls[-1] == {"fan": 25}
    assert hass.states.get(eid).attributes["humidity"] == 55
    await hass.config_entries.async_unload(entry.entry_id)


async def test_sensor_failure_stops_and_recovers(hass):
    entry, eid, calls = await setup(hass)
    await hass.services.async_call("climate", "turn_on", {"entity_id": eid}, blocking=True)
    await settle(hass)
    hass.states.async_set("sensor.room", "unavailable")
    await settle(hass)
    assert calls[-1] == {"off": True}
    assert hass.states.get(eid).attributes["controller_status"] == "sensor_fault"
    hass.states.async_set("sensor.room", 26, {"unit_of_measurement": "°C"})
    await settle(hass)
    assert calls[-1] == {"fan_entity": "fan.desk"}
    await hass.config_entries.async_unload(entry.entry_id)


async def test_off_cancels_delayed_node(hass):
    conf = config()
    conf["nodes"][0]["actions"] = [{"delay": 30}, {"action": "test_device.apply", "data": {"late": True}}]
    entry, eid, calls = await setup(hass, conf)
    await hass.services.async_call("climate", "turn_on", {"entity_id": eid}, blocking=True)
    await settle(hass)
    await asyncio.wait_for(
        hass.services.async_call("climate", "turn_off", {"entity_id": eid}, blocking=True), timeout=2
    )
    await settle(hass)
    assert calls == [{"off": True}]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_no_match_and_unit_conversion(hass):
    conf = config()
    conf["nodes"] = conf["nodes"][:1]
    entry, eid, calls = await setup(hass, conf)
    hass.states.async_set("sensor.room", 78.8, {"unit_of_measurement": "°F"})
    await hass.services.async_call("climate", "turn_on", {"entity_id": eid}, blocking=True)
    await settle(hass)
    assert hass.states.get(eid).attributes["current_temperature"] == pytest.approx(26)
    hass.states.async_set("sensor.room", 20, {"unit_of_measurement": "°C"})
    await settle(hass)
    assert calls[-1] == {"off": True}
    assert hass.states.get(eid).attributes["controller_status"] == "no_match"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_action_failure_attempts_safe_actions(hass):
    conf = config()
    conf["nodes"][0]["actions"] = [{"action": "missing_domain.missing_action"}]
    entry, eid, calls = await setup(hass, conf)
    await hass.services.async_call("climate", "turn_on", {"entity_id": eid}, blocking=True)
    await settle(hass)
    assert calls[-1] == {"off": True}
    state = hass.states.get(eid)
    assert state.attributes["controller_status"] == "action_error"
    assert state.attributes["last_error"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_config_flow_add_and_edit_nodes(hass):
    await async_setup_component(hass, "homeassistant", {})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Office", "kind": "temperature"}
    )
    assert result["step_id"] == "settings"
    conf = config()
    settings = {
        key: conf[key]
        for key in (
            "sensor",
            "primary",
            "auxiliaries",
            "target",
            "min_target",
            "max_target",
            "min_dwell",
            "hysteresis",
            "sensor_timeout",
        )
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], settings)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "add_node"})
    node = deepcopy(conf["nodes"][0])
    del node["id"]
    node.update(enabled=True, priority=10, modes=[])
    result = await hass.config_entries.flow.async_configure(result["flow_id"], node)
    assert result["step_id"] == "manage"
    with patch("custom_components.advanced_comfort.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "finish"})
        await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert len(result["data"]["nodes"]) == 1
    entry = result["result"]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "edit_node"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"node": entry.data["nodes"][0]["id"]}
    )
    node["lower"] = 2
    result = await hass.config_entries.options.async_configure(result["flow_id"], node)
    with patch("custom_components.advanced_comfort.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "finish"}
        )
        await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.options["nodes"][0]["lower"] == 2


async def test_dwell_defers_changes_but_off_bypasses_it(hass):
    conf = config()
    conf["min_dwell"] = 120
    with patch("custom_components.advanced_comfort.controller.monotonic", return_value=1000) as clock:
        entry, eid, calls = await setup(hass, conf)
        await hass.services.async_call("climate", "turn_on", {"entity_id": eid}, blocking=True)
        await settle(hass)
        assert not calls
        assert hass.states.get(eid).attributes["controller_status"] == "waiting"
        clock.return_value = 1121
        controller = hass.data["climate"].get_entity(eid)
        await controller.async_evaluate()
        await settle(hass)
        assert calls[-1] == {"fan_entity": "fan.desk"}
        hass.states.async_set("sensor.room", 24, {"unit_of_measurement": "°C"})
        await settle(hass)
        assert hass.states.get(eid).attributes["controller_status"] == "waiting"
        hass.states.async_set("sensor.room", 26, {"unit_of_measurement": "°C"})
        await settle(hass)
        assert hass.states.get(eid).attributes["controller_status"] == "active"
        await hass.services.async_call("climate", "turn_off", {"entity_id": eid}, blocking=True)
        await settle(hass)
        assert calls[-1] == {"off": True}
        await hass.config_entries.async_unload(entry.entry_id)


async def test_sensor_stale_without_value_change(hass):
    entry, eid, calls = await setup(hass)
    await hass.services.async_call("climate", "turn_on", {"entity_id": eid}, blocking=True)
    await settle(hass)
    future = dt_util.utcnow() + timedelta(seconds=61)
    with patch("custom_components.advanced_comfort.controller.dt_util.utcnow", return_value=future):
        await hass.data["climate"].get_entity(eid).async_evaluate()
        await settle(hass)
    assert calls[-1] == {"off": True}
    assert hass.states.get(eid).attributes["controller_status"] == "sensor_fault"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reload_stops_and_restores_target(hass):
    entry, eid, calls = await setup(hass)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": eid, "temperature": 25}, blocking=True
    )
    await hass.services.async_call("climate", "turn_on", {"entity_id": eid}, blocking=True)
    await settle(hass)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await settle(hass)
    assert calls[-1] == {"off": True}
    assert hass.states.get(eid).state == "off"
    assert hass.states.get(eid).attributes["temperature"] == 25
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("filename", ["temperature-six-nodes.yaml", "humidity-nodes.yaml"])
async def test_example_action_schemas(hass, filename):
    nodes = yaml.safe_load((Path(__file__).parents[1] / "examples" / filename).read_text(encoding="utf-8"))
    for node in nodes:
        validate_node({**node, "id": "example"})
        await async_validate_actions_config(hass, cv.SCRIPT_SCHEMA(node["actions"]))


async def test_bulk_import_validation(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Room", "kind": "humidity"}
    )
    conf = config("humidity")
    fields = (
        "sensor",
        "primary",
        "auxiliaries",
        "target",
        "min_target",
        "max_target",
        "min_dwell",
        "hysteresis",
        "sensor_timeout",
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {k: conf[k] for k in fields})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "import_nodes"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"nodes": [{"name": 42}]})
    assert result["errors"] == {"base": "invalid_node"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"nodes": conf["nodes"]})
    assert result["step_id"] == "manage"
