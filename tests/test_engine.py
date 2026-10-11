import pytest

from custom_components.advanced_comfort.engine import finite, select_node, validate_node


def band(name, lower=None, upper=None, **kw):
    return {
        "id": name,
        "name": name,
        "lower": lower,
        "upper": upper,
        "actions": [{"action": "switch.turn_off"}],
        **kw,
    }


@pytest.mark.parametrize(
    "value,expected",
    [
        (1.1, "boost"),
        (1, "boost"),
        (0.5, "normal"),
        (0.49, None),
        (-0.1, "gentle"),
        (-0.5, "gentle"),
        (-0.51, None),
        (-1, "sleep"),
        (-2, "sleep"),
        (-2.01, "fan"),
        (-5.01, "heat"),
    ],
)
def test_six_nodes_boundaries_and_gaps(value, expected):
    nodes = [
        band("boost", 1),
        band("normal", 0.5, 1),
        band("gentle", -0.5, 0),
        band("heat", upper=-5),
        band("fan", upper=-2),
        band("sleep", upper=-0.99),
    ]
    selected = select_node(nodes, value, "auto")
    assert (selected["id"] if selected else None) == expected


def test_hysteresis_and_priority():
    nodes = [band("high", 1), band("low", upper=1)]
    assert select_node(nodes, 1.05, "auto", "low", 0.1)["id"] == "low"
    assert select_node(nodes, 1.11, "auto", "low", 0.1)["id"] == "high"
    assert select_node(nodes, 0.95, "auto", "high", 0.1)["id"] == "high"
    assert select_node(nodes, 0.89, "auto", "high", 0.1)["id"] == "low"


def test_modes_and_disabled_nodes():
    nodes = [band("disabled", enabled=False), band("cool", modes=["cool"]), band("fallback")]
    assert select_node(nodes, 0, "heat")["id"] == "fallback"
    assert select_node(nodes, 0, "cool")["id"] == "cool"


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "unavailable", True])
def test_invalid_measurements(value):
    with pytest.raises(ValueError):
        finite(value)


def test_invalid_band():
    with pytest.raises(ValueError):
        validate_node(band("bad", 2, 1))
