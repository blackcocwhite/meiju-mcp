// Package vaultworker is the dedicated Windows/Linux helper implementation.
// macOS uses the independently built Objective-C helper, not this executable.
package vaultworker

import (
	"encoding/base64"
	"encoding/json"
	"io"
	"regexp"
)

type request struct {
	Action string `json:"action"`
	Key    string `json:"key"`
	Value  string `json:"value"`
}
type response struct {
	OK    bool   `json:"ok"`
	Found bool   `json:"found"`
	Value string `json:"value"`
	Code  string `json:"code,omitempty"`
}
type backend interface {
	Get(string) ([]byte, bool, string)
	Create(string, []byte) string
	Delete(string) string
}

var keyPattern = regexp.MustCompile(`^meiju-mcp\.go\.[a-f0-9]{32}\.(encryption-key|client-app|client-codex)$`)

func execute(r request, b backend) response {
	fail := func(code string) response { return response{Code: code} }
	if !keyPattern.MatchString(r.Key) {
		return fail("storage_invalid_request")
	}
	if r.Action == "set" {
		value, err := base64.StdEncoding.DecodeString(r.Value)
		if err != nil || len(value) != 32 {
			return fail("storage_invalid_request")
		}
		if code := b.Create(r.Key, value); code != "" {
			return fail(code)
		}
		return response{OK: true}
	}
	if r.Value != "" {
		return fail("storage_invalid_request")
	}
	switch r.Action {
	case "get":
		value, found, code := b.Get(r.Key)
		if code != "" {
			return fail(code)
		}
		if found && len(value) != 32 || !found && len(value) != 0 {
			return fail("storage_corrupt")
		}
		return response{OK: true, Found: found, Value: base64.StdEncoding.EncodeToString(value)}
	case "delete":
		if code := b.Delete(r.Key); code != "" {
			return fail(code)
		}
		return response{OK: true}
	default:
		return fail("storage_invalid_request")
	}
}
func Run(in io.Reader, out io.Writer) error {
	return run(in, out, nativeBackend{})
}
func run(in io.Reader, out io.Writer, b backend) error {
	// No automatic unlock, prompt, plain-text backend or legacy ACL migration.
	raw, err := io.ReadAll(io.LimitReader(in, 4097))
	if err != nil {
		return err
	}
	r := request{}
	valid := len(raw) <= 4096
	if valid {
		var obj map[string]json.RawMessage
		valid = json.Unmarshal(raw, &obj) == nil && len(obj) == 3 && obj["action"] != nil && obj["key"] != nil && obj["value"] != nil && json.Unmarshal(raw, &r) == nil
		for _, name := range []string{"action", "key", "value"} {
			var value *string
			if json.Unmarshal(obj[name], &value) != nil || value == nil {
				valid = false
			}
		}
	}
	result := response{Code: "storage_invalid_request"}
	if valid {
		result = execute(r, b)
	}
	return json.NewEncoder(out).Encode(result)
}
