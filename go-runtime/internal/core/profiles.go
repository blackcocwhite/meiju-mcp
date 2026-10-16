package core

import (
	"encoding/json"
	assets "github.com/blackcocwhite/meiju-mcp/go-runtime"
	"math"
	"strconv"
	"strings"
)

var modes = []string{"cool", "heat", "auto", "dry", "fan"}
var fans = map[string]float64{"silent": 20, "low": 40, "medium": 60, "high": 80, "full": 100, "auto": 102}

func number(v any, allowString bool) (float64, bool) {
	var f float64
	var err error
	switch x := v.(type) {
	case float64:
		f = x
	case int:
		f = float64(x)
	case json.Number:
		f, err = x.Float64()
	case string:
		if !allowString {
			return 0, false
		}
		f, err = strconv.ParseFloat(x, 64)
	default:
		return 0, false
	}
	return f, err == nil && !math.IsInf(f, 0) && !math.IsNaN(f)
}
func contains(xs []string, s string) bool {
	for _, x := range xs {
		if x == s {
			return true
		}
	}
	return false
}
func IsAC(v any) bool {
	if s, ok := v.(string); ok {
		return contains([]string{"0xac", "ac", "172"}, strings.ToLower(strings.TrimSpace(s)))
	}
	n, ok := number(v, false)
	return ok && n == 172
}
func ParseState(p Object) Object {
	out := Object{"power": nil, "target_temperature": nil, "indoor_temperature": nil, "mode": nil, "fan_speed": nil}
	if s := text(p["power"]); s == "on" || s == "off" {
		out["power"] = s == "on"
	}
	if a, ok := number(p["temperature"], true); ok {
		if b, yes := number(p["small_temperature"], true); yes && !math.IsInf(a+b, 0) {
			out["target_temperature"] = a + b
		}
	}
	if n, ok := number(p["indoor_temperature"], true); ok {
		out["indoor_temperature"] = n
	}
	if m := text(p["mode"]); contains(modes, m) {
		out["mode"] = m
	}
	if n, ok := number(p["wind_speed"], true); ok {
		for k, v := range fans {
			if n == v {
				out["fan_speed"] = k
			}
		}
	}
	return out
}
func Capabilities(state Object) Object {
	b, _ := assets.Files.ReadFile("contract/capabilities.json")
	var out Object
	_ = json.Unmarshal(b, &out)
	observed := []string{}
	for _, k := range []string{"power", "target_temperature", "indoor_temperature", "mode", "fan_speed"} {
		if state[k] != nil {
			observed = append(observed, k)
		}
	}
	out["observed_fields"] = observed
	return out
}
func Changes(a Object) (Object, Object, error) {
	changes := Object{}
	wire := Object{}
	for k, v := range a {
		if k == "device_id" || v == nil {
			continue
		}
		switch k {
		case "power":
			b, ok := v.(bool)
			if !ok {
				return nil, nil, Err("invalid_control")
			}
			changes[k] = b
			wire[k] = "off"
			if b {
				wire[k] = "on"
			}
		case "target_temperature":
			n, ok := number(v, false)
			if !ok || n < 17 || n > 30 || math.Trunc(n*2) != n*2 {
				return nil, nil, Err("invalid_control")
			}
			changes[k] = n
			wire["temperature"] = int(n)
			wire["small_temperature"] = n - math.Trunc(n)
		case "mode":
			m := text(v)
			if !contains(modes, m) {
				return nil, nil, Err("invalid_control")
			}
			changes[k] = m
			wire[k] = m
		case "fan_speed":
			f, ok := fans[text(v)]
			if !ok {
				return nil, nil, Err("invalid_control")
			}
			changes[k] = v
			wire["wind_speed"] = f
		default:
			return nil, nil, Err("invalid_control")
		}
	}
	if len(changes) == 0 {
		return nil, nil, Err("invalid_control")
	}
	return changes, wire, nil
}
