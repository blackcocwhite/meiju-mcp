"""Offline tests of uncertain state parsing and explicit generic AC controls."""

import math

import pytest

from meiju_mcp.profiles import (
    PROFILE_ID,
    capabilities,
    control_fields,
    is_ac,
    parse_state,
    validate_changes,
)


@pytest.mark.parametrize("device_type", ["0xAC", "0XaC", "AC", "ac", "172", " 0xAC ", 172, 172.0])
def test_ac_selection_does_not_require_a_serial_or_model(device_type):
    assert is_ac(device_type)


@pytest.mark.parametrize("device_type", [None, True, False, 0, 173, 172.1, "0xDB", "172.0", {}, [], ""])
def test_non_ac_types_are_not_selected(device_type):
    assert is_ac(device_type) is False


def test_recognized_status_fields_accept_finite_numeric_strings():
    assert parse_state(
        {
            "power": "off",
            "mode": "cool",
            "wind_speed": "102",
            "temperature": "26",
            "small_temperature": "0.5",
            "indoor_temperature": "27.2",
            "unknown": "ignored",
        }
    ) == {
        "power": False,
        "mode": "cool",
        "fan_speed": "auto",
        "target_temperature": 26.5,
        "indoor_temperature": 27.2,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"power": True, "mode": [], "wind_speed": True, "temperature": 26},
        {"power": 1, "mode": {}, "wind_speed": 43, "small_temperature": 0.5},
        {"power": "ON", "mode": "COOL", "wind_speed": "auto", "indoor_temperature": "Infinity"},
        {"power": "unexpected", "mode": "unexpected", "temperature": 26, "small_temperature": False},
    ],
)
def test_unknown_missing_and_unsupported_fields_remain_none(payload):
    assert all(value is None for value in parse_state(payload).values())


@pytest.mark.parametrize("value", [True, False, math.nan, math.inf, -math.inf, "nan", "inf", [], {}, 10**400])
def test_temperature_rejects_boolean_nonfinite_and_non_numeric_values(value):
    state = parse_state({"temperature": value, "small_temperature": 0, "indoor_temperature": value})
    assert state["target_temperature"] is None
    assert state["indoor_temperature"] is None
    assert parse_state({"temperature": 26, "small_temperature": value})["target_temperature"] is None


def test_state_sum_must_be_finite_but_does_not_impose_control_limits():
    assert parse_state({"temperature": 1e308, "small_temperature": 1e308})["target_temperature"] is None
    assert parse_state({"temperature": 16, "small_temperature": 0.5})["target_temperature"] == 16.5
    assert parse_state({"temperature": 31, "small_temperature": 0})["target_temperature"] == 31


@pytest.mark.parametrize(
    "code, name", [(20, "silent"), (40, "low"), (60, "medium"), (80, "high"), (100, "full"), (102, "auto")]
)
def test_fan_mappings_round_trip(code, name):
    assert parse_state({"wind_speed": code})["fan_speed"] == name
    assert parse_state({"wind_speed": str(code)})["fan_speed"] == name
    assert control_fields(validate_changes(fan_speed=name)) == {"wind_speed": code}


@pytest.mark.parametrize("mode", ["cool", "heat", "auto", "dry", "fan"])
def test_mode_mappings_round_trip_without_turning_on(mode):
    assert parse_state({"mode": mode})["mode"] == mode
    assert control_fields(validate_changes(mode=mode)) == {"mode": mode}


@pytest.mark.parametrize("power, wire", [(True, "on"), (False, "off")])
def test_power_remains_explicit(power, wire):
    assert validate_changes(power=power) == {"power": power}
    assert control_fields({"power": power}) == {"power": wire}
    assert parse_state({"power": wire})["power"] is power


@pytest.mark.parametrize("temperature", [17 + step / 2 for step in range(27)])
def test_every_allowed_half_degree_round_trips_without_power_change(temperature):
    changes = validate_changes(target_temperature=temperature)
    assert changes == {"target_temperature": float(temperature)}
    wire = control_fields(changes)
    assert set(wire) == {"temperature", "small_temperature"}
    assert type(wire["temperature"]) is int
    assert wire["small_temperature"] in (0, 0.5)
    assert parse_state(wire)["target_temperature"] == temperature


def test_combined_changes_preserve_only_requested_fields_and_do_not_mutate_input():
    changes = {"power": False, "target_temperature": 26.5, "mode": "dry", "fan_speed": "low"}
    before = changes.copy()
    assert control_fields(changes) == {
        "power": "off",
        "temperature": 26,
        "small_temperature": 0.5,
        "mode": "dry",
        "wind_speed": 40,
    }
    assert changes == before


@pytest.mark.parametrize(
    "temperature",
    [
        16.5,
        30.5,
        26.1,
        26.500000001,
        True,
        False,
        math.nan,
        math.inf,
        -math.inf,
        "26",
        "26.5",
        [],
        {},
        10**400,
    ],
)
def test_invalid_temperature_is_rejected_before_encoding(temperature):
    with pytest.raises(ValueError, match="Target temperature must be"):
        validate_changes(target_temperature=temperature)
    with pytest.raises(ValueError, match="Target temperature must be"):
        control_fields({"target_temperature": temperature})


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"power": None},
        {"power": "on"},
        {"power": 0},
        {"power": 1},
        {"mode": "COOL"},
        {"mode": " cool "},
        {"mode": []},
        {"fan_speed": "AUTO"},
        {"fan_speed": 20},
        {"fan_speed": {}},
    ],
)
def test_changes_require_at_least_one_strictly_typed_known_value(changes):
    with pytest.raises(ValueError):
        validate_changes(**changes)


@pytest.mark.parametrize(
    "changes", [{"eco": True}, {"power": True, "wind_speed": 20}, {1: "secret"}, [], None]
)
def test_raw_controls_cannot_bypass_the_requested_field_contract(changes):
    with pytest.raises(ValueError, match="Control changes contain unsupported fields"):
        control_fields(changes)


def test_errors_do_not_echo_untrusted_values_or_unknown_fields():
    secret = "sensitive-untrusted-input"
    with pytest.raises(ValueError) as captured:
        validate_changes(mode=secret)
    assert secret not in str(captured.value)
    with pytest.raises(ValueError) as captured:
        control_fields({secret: secret})
    assert secret not in str(captured.value)


def test_capability_candidates_are_explicitly_unverified_client_policy():
    result = capabilities(parse_state({"power": "off", "mode": "heat", "temperature": 26}))
    assert result["profile_id"] == PROFILE_ID == "generic_ac_lua_v1"
    assert result["verified"] is False
    assert result["experimental"] is True
    assert result["range_source"] == "client_policy"
    assert result["observed_fields"] == ["power", "mode"]
    assert result["candidate_controls"]["target_temperature"] == {
        "min": 17,
        "max": 30,
        "step": 0.5,
        "unit": "celsius",
    }
    assert "not hardware-discovered" in result["explanation"]
    assert "never been cross-model tested" in result["explanation"]
    assert "may reject" in result["explanation"]


def test_observed_fields_do_not_treat_unknown_values_as_support():
    assert (
        capabilities(
            {
                "power": "on",
                "mode": "future",
                "fan_speed": [],
                "target_temperature": True,
                "indoor_temperature": math.nan,
            }
        )["observed_fields"]
        == []
    )
    assert capabilities(
        parse_state(
            {
                "power": "on",
                "mode": "auto",
                "wind_speed": 20,
                "temperature": 31,
                "small_temperature": 0,
                "indoor_temperature": 0,
            }
        )
    )["observed_fields"] == ["power", "target_temperature", "indoor_temperature", "mode", "fan_speed"]


def test_capability_results_are_independent_and_do_not_mutate_state():
    state = parse_state({"power": "off"})
    original = state.copy()
    first = capabilities(state)
    first["candidate_controls"]["mode"].append("invalid")
    assert "invalid" not in capabilities(state)["candidate_controls"]["mode"]
    assert state == original
