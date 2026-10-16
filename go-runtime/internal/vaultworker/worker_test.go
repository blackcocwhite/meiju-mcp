package vaultworker

import (
	"bytes"
	"encoding/base64"
	"strings"
	"testing"
)

type mockBackend struct {
	values  map[string][]byte
	calls   int
	failure string
}

func TestMalformedWireRequestNeverReachesBackend(t *testing.T) {
	key := "meiju-mcp.go.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.encryption-key"
	for _, raw := range []string{
		`{"action":"get","key":"` + key + `","value":null}`,
		`{"action":"get","key":"` + key + `"}`,
		`{"action":"get","key":"` + key + `","value":"","extra":true}`,
		`{"action":"get","key":"` + key + `","value":""} {}`,
		strings.Repeat("x", 4097),
	} {
		b := &mockBackend{values: map[string][]byte{}}
		var output bytes.Buffer
		if run(strings.NewReader(raw), &output, b) != nil || b.calls != 0 || !strings.Contains(output.String(), "storage_invalid_request") {
			t.Fatal("malformed wire request reached backend")
		}
	}
}

func (b *mockBackend) Get(k string) ([]byte, bool, string) {
	b.calls++
	v, ok := b.values[k]
	return v, ok, b.failure
}
func (b *mockBackend) Create(k string, v []byte) string {
	b.calls++
	if b.failure != "" {
		return b.failure
	}
	if _, ok := b.values[k]; ok {
		return "storage_item_exists"
	}
	b.values[k] = v
	return ""
}
func (b *mockBackend) Delete(k string) string {
	b.calls++
	if b.failure != "" {
		return b.failure
	}
	delete(b.values, k)
	return ""
}
func TestWorkerProtocolWithMock(t *testing.T) {
	b := &mockBackend{values: map[string][]byte{}}
	key := "meiju-mcp.go.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.encryption-key"
	value := base64.StdEncoding.EncodeToString([]byte(strings.Repeat("x", 32)))
	if r := execute(request{"get", key, ""}, b); !r.OK || r.Found {
		t.Fatal("missing")
	}
	if !execute(request{"set", key, value}, b).OK {
		t.Fatal("create")
	}
	if r := execute(request{"get", key, ""}, b); !r.Found || r.Value != value {
		t.Fatal("read")
	}
	if execute(request{"set", key, value}, b).Code != "storage_item_exists" {
		t.Fatal("overwritten")
	}
	b.failure = "storage_authorization_required"
	if execute(request{"get", key, ""}, b).OK {
		t.Fatal("denial became absence")
	}
	before := b.calls
	if execute(request{"get", "another-password", ""}, b).OK || b.calls != before {
		t.Fatal("invalid input reached backend")
	}
}
