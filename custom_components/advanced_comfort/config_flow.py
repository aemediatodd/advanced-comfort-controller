"""UI configuration with any number of nodes and native action selectors."""

from copy import deepcopy
from uuid import uuid4

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv, selector
from homeassistant.helpers.script import async_validate_actions_config

from .const import DEFAULTS, DOMAIN, HUMIDITY_MODES, TEMPERATURE_MODES
from .engine import finite, validate_node


def entity(domains=None, multiple=False):
    config = {"multiple": multiple}
    if domains:
        config["domain"] = domains
    return selector.EntitySelector(config)


def number(low, high, step=0.1):
    return selector.NumberSelector({"min": low, "max": high, "step": step, "mode": "box"})


class Editor:
    """Shared editor; edits are only persisted by the explicit save step."""

    _working: dict
    _editing: str | None = None

    async def async_step_settings(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                for key in (
                    "target",
                    "min_target",
                    "max_target",
                    "hysteresis",
                    "min_dwell",
                    "sensor_timeout",
                ):
                    user_input[key] = finite(user_input[key])
                if not user_input["min_target"] <= user_input["target"] <= user_input["max_target"]:
                    raise ValueError("Target outside limits")
                if user_input["min_target"] >= user_input["max_target"]:
                    raise ValueError("Invalid limits")
                self._working.update(user_input)
                self._working["secondary_sensor"] = user_input.get("secondary_sensor")
                self._working["auxiliaries"] = user_input.get("auxiliaries", [])
                if "safe_actions" not in self._working:
                    self._working["safe_actions"] = [
                        {
                            "action": "homeassistant.turn_off",
                            "target": {"entity_id": eid},
                            "continue_on_error": True,
                        }
                        for eid in dict.fromkeys([self._working["primary"], *self._working["auxiliaries"]])
                        if eid.split(".")[0]
                        in ("climate", "switch", "fan", "humidifier", "light", "input_boolean")
                    ]
                return await self.async_step_manage()
            except (ValueError, TypeError):
                errors["base"] = "invalid_settings"
        is_temp = self._working["kind"] == "temperature"
        settings = {
            vol.Required("sensor"): entity(["sensor", "input_number"]),
            vol.Optional("secondary_sensor"): entity(["sensor", "input_number"]),
            vol.Required("primary"): entity(["climate", "switch", "fan", "humidifier", "input_boolean"]),
            vol.Optional("auxiliaries", default=[]): entity(multiple=True),
            vol.Required("target"): number(-100 if is_temp else 0, 200 if is_temp else 100),
            vol.Required("min_target"): number(-100 if is_temp else 0, 200 if is_temp else 100),
            vol.Required("max_target"): number(-100 if is_temp else 0, 200 if is_temp else 100),
            vol.Required("hysteresis"): number(0, 20),
            vol.Required("min_dwell"): number(0, 3600, 1),
            vol.Required("sensor_timeout"): number(10, 86400, 1),
        }
        return self.async_show_form(
            step_id="settings",
            errors=errors,
            data_schema=self.add_suggested_values_to_schema(vol.Schema(settings), self._working),
        )

    async def async_step_manage(self, user_input=None):
        return self.async_show_menu(
            step_id="manage",
            menu_options=[
                "add_node",
                "edit_node",
                "remove_node",
                "import_nodes",
                "settings",
                "safe_actions",
                "finish",
            ],
            description_placeholders={"count": str(len(self._working["nodes"]))},
        )

    async def async_step_add_node(self, user_input=None):
        self._editing = None
        return await self.async_step_node()

    async def async_step_import_nodes(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                imported = deepcopy(user_input["nodes"])
                if not isinstance(imported, list) or not imported:
                    raise ValueError("Expected a non-empty list")
                modes = TEMPERATURE_MODES if self._working["kind"] == "temperature" else HUMIDITY_MODES
                for node in imported:
                    if not isinstance(node, dict):
                        raise ValueError("Expected node object")
                    node["id"] = uuid4().hex
                    for key in ("lower", "upper"):
                        if node.get(key) is not None:
                            node[key] = finite(node[key])
                    validate_node(node)
                    if any(mode not in modes for mode in node.get("modes", [])):
                        raise ValueError("Invalid modes")
                    await async_validate_actions_config(
                        self.hass, cv.SCRIPT_SCHEMA(deepcopy(node["actions"]))
                    )
                self._working["nodes"] = sorted(
                    [*self._working["nodes"], *imported], key=lambda n: -n.get("priority", 0)
                )
                return await self.async_step_manage()
            except (ValueError, TypeError, vol.Invalid):
                errors["base"] = "invalid_node"
        return self.async_show_form(
            step_id="import_nodes",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required("nodes"): selector.ObjectSelector(),
                }
            ),
        )

    async def async_step_edit_node(self, user_input=None):
        if not self._working["nodes"]:
            return await self.async_step_add_node()
        if user_input is not None:
            self._editing = user_input["node"]
            return await self.async_step_node()
        return self.async_show_form(step_id="edit_node", data_schema=self._pick_node_schema())

    def _pick_node_schema(self):
        return vol.Schema(
            {
                vol.Required("node"): selector.SelectSelector(
                    {
                        "options": [
                            {"value": n["id"], "label": f"{n.get('priority', 0)} · {n['name']}"}
                            for n in self._working["nodes"]
                        ]
                    }
                )
            }
        )

    async def async_step_remove_node(self, user_input=None):
        if not self._working["nodes"]:
            return await self.async_step_manage()
        if user_input is not None:
            self._working["nodes"] = [n for n in self._working["nodes"] if n["id"] != user_input["node"]]
            return await self.async_step_manage()
        return self.async_show_form(step_id="remove_node", data_schema=self._pick_node_schema())

    async def async_step_node(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                node = {**user_input, "id": self._editing or uuid4().hex}
                for key in ("lower", "upper"):
                    if key in node:
                        node[key] = finite(node[key])
                validate_node(node)
                await async_validate_actions_config(self.hass, cv.SCRIPT_SCHEMA(deepcopy(node["actions"])))
                nodes = [n for n in self._working["nodes"] if n["id"] != node["id"]]
                nodes.append(node)
                self._working["nodes"] = sorted(nodes, key=lambda n: -n.get("priority", 0))
                return await self.async_step_manage()
            except (ValueError, TypeError, vol.Invalid):
                errors["base"] = "invalid_node"
        existing = next((n for n in self._working["nodes"] if n["id"] == self._editing), {})
        suggested = user_input if user_input is not None else existing
        modes = TEMPERATURE_MODES if self._working["kind"] == "temperature" else HUMIDITY_MODES
        schema = vol.Schema(
            {
                vol.Required("name"): selector.TextSelector(),
                vol.Required("enabled", default=True): selector.BooleanSelector(),
                vol.Required("priority", default=0): number(-1000, 1000, 1),
                vol.Optional("lower"): number(-1000, 1000),
                vol.Optional("upper"): number(-1000, 1000),
                vol.Optional("modes", default=[]): selector.SelectSelector(
                    {"options": modes, "multiple": True}
                ),
                vol.Required("activity", default="idle"): selector.SelectSelector(
                    {
                        "options": ["idle", "cooling", "heating", "fan", "drying", "humidifying"],
                        "translation_key": "activity",
                    }
                ),
                vol.Required("actions"): selector.ActionSelector(),
            }
        )
        return self.async_show_form(
            step_id="node", errors=errors, data_schema=self.add_suggested_values_to_schema(schema, suggested)
        )

    async def async_step_safe_actions(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                actions = user_input["safe_actions"]
                if not actions:
                    raise ValueError("Shutdown actions cannot be empty")
                await async_validate_actions_config(self.hass, cv.SCRIPT_SCHEMA(deepcopy(actions)))
                self._working["safe_actions"] = actions
                return await self.async_step_manage()
            except (ValueError, TypeError, vol.Invalid):
                errors["base"] = "invalid_actions"
        return self.async_show_form(
            step_id="safe_actions",
            errors=errors,
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required("safe_actions"): selector.ActionSelector(),
                    }
                ),
                self._working,
            ),
        )

    async def async_step_finish(self, user_input=None):
        if not self._working["nodes"]:
            return await self.async_step_add_node()
        if not self._working.get("safe_actions"):
            return await self.async_step_safe_actions()
        return self.async_create_entry(title=self._working["name"], data=self._working)


class ComfortConfigFlow(Editor, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self._working = {**deepcopy(DEFAULTS), **user_input}
            if user_input["kind"] == "humidity":
                self._working.update(target=50, min_target=0, max_target=100, hysteresis=1)
            elif self.hass.config.units.temperature_unit == "°F":
                self._working.update(target=75, min_target=41, max_target=104, hysteresis=0.2)
            return await self.async_step_settings()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): selector.TextSelector(),
                    vol.Required("kind", default="temperature"): selector.SelectSelector(
                        {"options": ["temperature", "humidity"], "translation_key": "kind"}
                    ),
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ComfortOptionsFlow()


class ComfortOptionsFlow(Editor, config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        self._working = deepcopy({**DEFAULTS, **self.config_entry.data, **self.config_entry.options})
        return await self.async_step_manage()
