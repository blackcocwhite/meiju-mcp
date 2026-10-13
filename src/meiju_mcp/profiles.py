"""Experimental, model-independent candidates for Meiju's 0xAC Lua schema.

Recognized cloud fields describe a response, not hardware capabilities or freshness.
No serial-number family is used to select this profile.
"""

from math import isfinite
from typing import Any

# Mapping provenance: https://github.com/sususweet/midea_auto_cloud (Apache-2.0).
# State semantics also follow Controller/Sources/ACCore/MeijuCloudRead.swift and
# MeijuCloudControl.swift. Client policy below is not hardware discovery.
PROFILE_ID = "generic_ac_lua_v1"

_MODES = ("cool", "heat", "auto", "dry", "fan")
_FAN_VALUES = {"silent": 20, "low": 40, "medium": 60, "high": 80, "full": 100, "auto": 102}
_FAN_NAMES = {value: name for name, value in _FAN_VALUES.items()}
_STATE_FIELDS = ("power", "target_temperature", "indoor_temperature", "mode", "fan_speed")
_CHANGE_FIELDS = frozenset(("power", "target_temperature", "mode", "fan_speed"))


def is_ac(device_type: object) -> bool:
    """Recognize hexadecimal AC labels and decimal 172 without coercing booleans."""
    if isinstance(device_type, str):
        return device_type.strip().lower() in ("0xac", "ac", "172")
    return type(device_type) in (int, float) and device_type == 172


def _number(value: object, *, allow_string: bool = False) -> float | None:
    if type(value) not in (int, float) and not (allow_string and isinstance(value, str)):
        return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def parse_state(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse an unwrapped Lua status object; unsupported and absent values stay unknown."""
    if not isinstance(payload, dict):
        raise ValueError("Status payload must be an object.")

    power = payload.get("power")
    mode = payload.get("mode")
    wind_speed = _number(payload.get("wind_speed"), allow_string=True)
    whole = _number(payload.get("temperature"), allow_string=True)
    fraction = _number(payload.get("small_temperature"), allow_string=True)
    target = whole + fraction if whole is not None and fraction is not None else None
    if target is not None and not isfinite(target):
        target = None

    return {
        "power": (power == "on") if isinstance(power, str) and power in ("on", "off") else None,
        "target_temperature": target,
        "indoor_temperature": _number(payload.get("indoor_temperature"), allow_string=True),
        "mode": mode if isinstance(mode, str) and mode in _MODES else None,
        "fan_speed": _FAN_NAMES.get(wind_speed),
    }


def validate_changes(
    *,
    power: object = None,
    target_temperature: object = None,
    mode: object = None,
    fan_speed: object = None,
) -> dict[str, Any]:
    """Normalize explicit changes under client policy, without echoing invalid input."""
    changes: dict[str, Any] = {}
    if power is not None:
        if type(power) is not bool:
            raise ValueError("Power must be a boolean.")
        changes["power"] = power
    if target_temperature is not None:
        temperature = _number(target_temperature)
        if temperature is None or not 17 <= temperature <= 30 or not (temperature * 2).is_integer():
            raise ValueError("Target temperature must be a finite number from 17 to 30 in steps of 0.5.")
        changes["target_temperature"] = temperature
    if mode is not None:
        if not isinstance(mode, str) or mode not in _MODES:
            raise ValueError("Mode must be cool, heat, auto, dry, or fan.")
        changes["mode"] = mode
    if fan_speed is not None:
        if not isinstance(fan_speed, str) or fan_speed not in _FAN_VALUES:
            raise ValueError("Fan speed must be silent, low, medium, high, full, or auto.")
        changes["fan_speed"] = fan_speed
    if not changes:
        raise ValueError("At least one control change is required.")
    return changes


def control_fields(changes: dict[str, Any]) -> dict[str, Any]:
    """Encode only validated explicit changes into Lua fields; never infer power."""
    if not isinstance(changes, dict) or not changes.keys() <= _CHANGE_FIELDS:
        raise ValueError("Control changes contain unsupported fields.")
    normalized = validate_changes(**changes)
    fields: dict[str, Any] = {}
    if "power" in normalized:
        fields["power"] = "on" if normalized["power"] else "off"
    if "target_temperature" in normalized:
        temperature = normalized["target_temperature"]
        fields["temperature"] = int(temperature)
        fields["small_temperature"] = temperature - int(temperature)
    if "mode" in normalized:
        fields["mode"] = normalized["mode"]
    if "fan_speed" in normalized:
        fields["wind_speed"] = _FAN_VALUES[normalized["fan_speed"]]
    return fields


def capabilities(state: dict[str, Any]) -> dict[str, Any]:
    """Describe candidates and recognizable normalized fields, never verified support."""
    if not isinstance(state, dict):
        raise ValueError("State must be an object.")
    recognized = {
        "power": type(state.get("power")) is bool,
        "target_temperature": _number(state.get("target_temperature")) is not None,
        "indoor_temperature": _number(state.get("indoor_temperature")) is not None,
        "mode": isinstance(state.get("mode"), str) and state["mode"] in _MODES,
        "fan_speed": isinstance(state.get("fan_speed"), str) and state["fan_speed"] in _FAN_VALUES,
    }
    return {
        "profile_id": PROFILE_ID,
        "verified": False,
        "experimental": True,
        "range_source": "client_policy",
        "observed_fields": [field for field in _STATE_FIELDS if recognized[field]],
        "candidate_controls": {
            "power": [True, False],
            "target_temperature": {"min": 17.0, "max": 30.0, "step": 0.5, "unit": "celsius"},
            "mode": list(_MODES),
            "fan_speed": list(_FAN_VALUES),
        },
        "explanation": (
            "These are experimental generic 0xAC Lua candidates and client policy limits, "
            "not hardware-discovered capabilities. They have never been cross-model tested; "
            "the server or device may reject them. Observed fields only mean the cloud "
            "response contained recognizable values; they do not establish control support "
            "or a live device reading."
        ),
    }
