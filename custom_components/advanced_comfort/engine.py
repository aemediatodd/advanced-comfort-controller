"""Pure, deterministic band selection. Bounds are [lower, upper)."""

from math import isfinite


def finite(value):
    """Parse a real finite sensor/setting value."""
    if isinstance(value, bool):
        raise ValueError("Boolean is not a measurement")
    number = float(value)
    if not isfinite(number):
        raise ValueError("Measurement must be finite")
    return number


def validate_node(node):
    """Validate a node without relying on Home Assistant."""
    if not node.get("id") or not isinstance(node.get("name"), str) or not node["name"].strip():
        raise ValueError("Node ID and name are required")
    lower = finite(node["lower"]) if node.get("lower") is not None else None
    upper = finite(node["upper"]) if node.get("upper") is not None else None
    if lower is not None and upper is not None and lower >= upper:
        raise ValueError("Lower bound must be smaller than upper bound")
    if not isinstance(node.get("actions"), list) or not node["actions"]:
        raise ValueError("At least one action is required")
    if not isinstance(node.get("enabled", True), bool):
        raise ValueError("Enabled must be a boolean")
    finite(node.get("priority", 0))
    if not isinstance(node.get("priority", 0), (float, int)):
        raise ValueError("Priority must be numeric")
    if not isinstance(node.get("modes", []), list):
        raise ValueError("Modes must be a list")
    if node.get("activity", "idle") not in ("idle", "cooling", "heating", "fan", "drying", "humidifying"):
        raise ValueError("Invalid activity")
    return node


def matches(node, delta, mode, margin=0):
    """A blank mode list applies to every enabled controller mode."""
    if not node.get("enabled", True):
        return False
    if node.get("modes") and mode not in node["modes"]:
        return False
    lower, upper = node.get("lower"), node.get("upper")
    return (lower is None or delta >= lower - margin) and (upper is None or delta < upper + margin)


def select_node(nodes, delta, mode, current_id=None, hysteresis=0):
    """Retain an active band through its hysteresis, otherwise first match wins."""
    delta = finite(delta)
    # At zero hysteresis, priority is always the configured list order.
    if hysteresis > 0 and current_id is not None:
        current = next((n for n in nodes if n["id"] == current_id), None)
        if current and matches(current, delta, mode, hysteresis):
            return current
    return next((n for n in nodes if matches(n, delta, mode)), None)
