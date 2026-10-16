package core

import (
	"context"
	"encoding/base64"
	"encoding/json"
	assets "github.com/blackcocwhite/meiju-mcp/go-runtime"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
)

type memoryVault struct {
	mu   sync.Mutex
	data map[string][]byte
	fail bool
}

func (v *memoryVault) Get(k string) ([]byte, error) {
	v.mu.Lock()
	defer v.mu.Unlock()
	if v.fail {
		return nil, Err("storage_unavailable")
	}
	return append([]byte(nil), v.data[k]...), nil
}
func (v *memoryVault) Set(k string, b []byte) error {
	v.mu.Lock()
	defer v.mu.Unlock()
	if v.fail {
		return Err("storage_unavailable")
	}
	v.data[k] = append([]byte(nil), b...)
	return nil
}
func (v *memoryVault) Delete(k string) error {
	v.mu.Lock()
	defer v.mu.Unlock()
	delete(v.data, k)
	return nil
}
func testStore(t *testing.T) *Store {
	t.Helper()
	return NewStore(filepath.Join(canonicalTemp(t), "session"), &memoryVault{data: map[string][]byte{}})
}
func TestProfileGolden(t *testing.T) {
	b, _ := assets.Files.ReadFile("contract/profiles.json")
	var cases []struct{ Input, Output Object }
	if err := Decode(b, &cases); err != nil {
		t.Fatal(err)
	}
	for _, c := range cases {
		a, _ := JSON(ParseState(c.Input))
		b, _ := JSON(c.Output)
		if string(a) != string(b) {
			t.Fatalf("profile mismatch: %s != %s", a, b)
		}
	}
}
func TestSignatureGolden(t *testing.T) {
	b, _ := assets.Files.ReadFile("contract/signature.json")
	var c struct {
		Body              Object
		Random, Signature string
	}
	if Decode(b, &c) != nil {
		t.Fatal("decode")
	}
	raw, _ := JSON(c.Body)
	if Signature(raw, c.Random) != c.Signature {
		t.Fatal("signature mismatch")
	}
}
func TestStorageRoundTripAndCAS(t *testing.T) {
	s := testStore(t)
	r, v, err := s.Load()
	if err != nil || v != nil || r != "empty" {
		t.Fatal(err)
	}
	token := strings.Repeat("X", 4096)
	rev, err := s.Save(SavedSession{token, ID()}, r)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := os.ReadFile(filepath.Join(s.Dir, "session.json"))
	if strings.Contains(string(raw), token) {
		t.Fatal("plaintext")
	}
	r, got, err := s.Load()
	if err != nil || got.Token != token || r != rev {
		t.Fatal(err)
	}
	if _, err = s.Save(SavedSession{"other", ID()}, "empty"); err == nil {
		t.Fatal("stale save")
	}
	if err = s.Forget("empty"); err != nil {
		t.Fatal(err)
	}
	_, got, _ = s.Load()
	if got == nil {
		t.Fatal("old expiry deleted new login")
	}
	if err = s.Forget(rev); err != nil {
		t.Fatal(err)
	}
	_, got, _ = s.Load()
	if got != nil {
		t.Fatal("not forgotten")
	}
}
func TestTamperAndLockedStore(t *testing.T) {
	s := testStore(t)
	_, err := s.Save(SavedSession{"synthetic", ID()}, "empty")
	if err != nil {
		t.Fatal(err)
	}
	s.Vault.(*memoryVault).fail = true
	if _, _, err = s.Load(); err == nil {
		t.Fatal("locked vault")
	}
	s.Vault.(*memoryVault).fail = false
	p := filepath.Join(s.Dir, "session.json")
	raw, _ := os.ReadFile(p)
	var r record
	json.Unmarshal(raw, &r)
	r.Revision = ID()
	raw, _ = JSON(r)
	os.WriteFile(p, raw, 0600)
	if _, _, err = s.Load(); err == nil {
		t.Fatal("tamper accepted")
	}
}
func TestUnsafeStorage(t *testing.T) {
	s := testStore(t)
	if err := PrivateDir(s.Dir); err != nil {
		t.Fatal(err)
	}
	outside := filepath.Join(t.TempDir(), "outside")
	os.WriteFile(outside, []byte("unchanged"), 0600)
	if err := os.Symlink(outside, filepath.Join(s.Dir, "session.json")); err != nil {
		t.Skip("symlinks unavailable")
	}
	if _, _, err := s.Load(); err == nil {
		t.Fatal("symlink accepted")
	}
	b, _ := os.ReadFile(outside)
	if string(b) != "unchanged" {
		t.Fatal("outside changed")
	}
}
func fixture(t *testing.T) (*Engine, *atomic.Int32) {
	t.Helper()
	writes := &atomic.Int32{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		if r.Header.Get("Sign") != Signature(b, r.Header.Get("Random")) {
			t.Error("bad signature")
		}
		if r.Header.Get("Cookie") != "" {
			t.Error("cookie leaked")
		}
		var req Object
		Decode(b, &req)
		var data any
		switch r.URL.Query().Get("alias") {
		case SMS:
			json.NewEncoder(w).Encode(Object{"code": 0})
			return
		case Login:
			data = Object{"mdata": Object{"accessToken": "synthetic-token"}}
		case Homes:
			data = Object{"homeList": []any{Object{"homegroupId": json.Number("18446744073709551615"), "name": "测试家庭"}}}
		case Devices:
			data = Object{"homeList": []any{Object{"homegroupId": json.Number("18446744073709551615"), "roomList": []any{Object{"name": "客厅", "applianceList": []any{Object{"applianceCode": json.Number("18446744073709551614"), "type": "0xAC", "name": "测试空调", "onlineStatus": 1, "sn8": "99999999"}}}}}}}
		case Status:
			data = Object{"power": "off", "temperature": 25, "small_temperature": 0.5, "indoor_temperature": 27, "mode": "auto", "wind_speed": 102}
		case Control:
			writes.Add(1)
			data = Object{}
		default:
			t.Error("unexpected endpoint")
		}
		json.NewEncoder(w).Encode(Object{"code": 0, "data": data})
	}))
	t.Cleanup(srv.Close)
	e := NewEngine(nil)
	e.http = srv.Client()
	e.endpoint = srv.URL
	return e, writes
}
func TestCloudFlowAndNoImplicitPower(t *testing.T) {
	e, writes := fixture(t)
	ctx := context.Background()
	if _, err := e.SMS(ctx, "13800138000", ""); err != nil {
		t.Fatal(err)
	}
	if err := e.Verify(ctx, "13800138000", "123456"); err != nil {
		t.Fatal(err)
	}
	out, err := e.Call(ctx, "meiju_list_devices", Object{})
	if err != nil {
		t.Fatal(err)
	}
	devices := out["devices"].([]any)
	d := devices[0].(Object)
	if d["name"] != "测试空调" || strings.Contains(d["device_id"].(string), "184467") {
		t.Fatal("device mapping")
	}
	id := d["device_id"].(string)
	state, err := e.Call(ctx, "meiju_get_status", Object{"device_id": id})
	if err != nil || state["target_temperature"] != 25.5 {
		t.Fatal(err, state)
	}
	out, err = e.Call(ctx, "meiju_control", Object{"device_id": id, "target_temperature": 26.5})
	if err != nil || writes.Load() != 1 || out["verification"] != "cloud_differs" {
		t.Fatal(err, out)
	}
	_, wire, err := Changes(Object{"target_temperature": 26.5})
	if err != nil || wire["power"] != nil {
		t.Fatal("implicit power")
	}
	e.Logout()
	if _, err = e.Call(ctx, "meiju_get_status", Object{"device_id": id}); err == nil {
		t.Fatal("logged out")
	}
}
func TestLogoutDuringNetworkRejectsLateLogin(t *testing.T) {
	e, _ := fixture(t)
	ctx := context.Background()
	e.SMS(ctx, "13800138000", "")
	started := make(chan struct{})
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(started)
		<-release
		json.NewEncoder(w).Encode(Object{"code": 0, "data": Object{"mdata": Object{"accessToken": "late-token"}}})
	}))
	defer srv.Close()
	e.endpoint = srv.URL
	finished := make(chan error)
	go func() { finished <- e.Verify(ctx, "13800138000", "123456") }()
	<-started
	e.Logout()
	close(release)
	if err := <-finished; err == nil {
		t.Fatal("resurrected")
	}
	if e.Status()["authenticated"] != false {
		t.Fatal("authenticated")
	}
}
func TestInputChanges(t *testing.T) {
	for _, a := range []Object{{}, {"power": "false"}, {"power": 1}, {"target_temperature": 26.2}, {"target_temperature": true}, {"mode": "unknown"}, {"fan_speed": 40}, {"swing": true}} {
		if _, _, e := Changes(a); e == nil {
			t.Fatal("bad control accepted")
		}
	}
	a, w, e := Changes(Object{"power": false, "mode": "cool", "fan_speed": "auto"})
	if e != nil || !reflect.DeepEqual(a, Object{"power": false, "mode": "cool", "fan_speed": "auto"}) || w["power"] != "off" {
		t.Fatal("mapping")
	}
}

func canonicalTemp(t *testing.T) string {
	t.Helper()
	p, e := filepath.EvalSymlinks(t.TempDir())
	if e != nil {
		t.Fatal(e)
	}
	return p
}

func TestPythonEncryptedFixture(t *testing.T) {
	b, _ := assets.Files.ReadFile("contract/storage.json")
	var fixture struct {
		Key     string
		Record  record
		Payload SavedSession
	}
	if Decode(b, &fixture) != nil {
		t.Fatal("fixture")
	}
	s := testStore(t)
	if PrivateDir(s.Dir) != nil {
		t.Fatal("dir")
	}
	key, err := base64.StdEncoding.DecodeString(fixture.Key)
	if err != nil {
		t.Fatal(err)
	}
	s.Vault.Set(testKey(t, s, "encryption-key"), key)
	raw, _ := JSON(fixture.Record)
	AtomicWrite(filepath.Join(s.Dir, "session.json"), raw)
	_, session, err := s.Load()
	if err != nil || session.Token != fixture.Payload.Token || session.DeviceID != fixture.Payload.DeviceID {
		t.Fatal("Python ciphertext not compatible", err)
	}
}
func TestUncertainWriteNotRetried(t *testing.T) {
	e, writes := fixture(t)
	ctx := context.Background()
	e.SMS(ctx, "13800138000", "")
	e.Verify(ctx, "13800138000", "123456")
	list, _ := e.Call(ctx, "meiju_list_devices", Object{})
	id := list["devices"].([]any)[0].(Object)["device_id"].(string)
	original := e.http.Transport
	e.http.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.Query().Get("alias") == Control {
			writes.Add(1)
			return nil, io.ErrUnexpectedEOF
		}
		return original.RoundTrip(r)
	})
	_, err := e.Call(ctx, "meiju_control", Object{"device_id": id, "power": true})
	safe, ok := err.(*SafeError)
	if !ok || !safe.Uncertain || writes.Load() != 1 {
		t.Fatal("write retry or uncertainty lost", err, writes.Load())
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func TestMalformedStoreDoesNotSilentlyForget(t *testing.T) {
	s := testStore(t)
	PrivateDir(s.Dir)
	os.WriteFile(filepath.Join(s.Dir, "session.json"), []byte(`{"schema":1,"revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","unexpected":true}`), 0600)
	if _, _, err := s.Load(); err == nil {
		t.Fatal("missing ciphertext accepted")
	}
}

func TestMissingKeyCannotOverwriteExistingCiphertext(t *testing.T) {
	s := testStore(t)
	rev, err := s.Save(SavedSession{"original-synthetic", ID()}, "empty")
	if err != nil {
		t.Fatal(err)
	}
	before, _ := os.ReadFile(filepath.Join(s.Dir, "session.json"))
	s.Vault.Delete(testKey(t, s, "encryption-key"))
	if _, err = s.Save(SavedSession{"new-synthetic", ID()}, rev); err == nil {
		t.Fatal("overwrote unknown saved login")
	}
	after, _ := os.ReadFile(filepath.Join(s.Dir, "session.json"))
	if string(before) != string(after) {
		t.Fatal("ciphertext changed")
	}
}

func TestExternalForgetInvalidatesRunningAccount(t *testing.T) {
	store := testStore(t)
	store.Save(SavedSession{"synthetic", ID()}, "empty")
	engine := NewEngine(store)
	if engine.Status()["authenticated"] != true {
		t.Fatal("not restored")
	}
	if err := store.Forget(""); err != nil {
		t.Fatal(err)
	}
	if engine.Status()["authenticated"] != false {
		t.Fatal("external logout ignored")
	}
}
func TestSharedReplacementResetsOpaqueIDs(t *testing.T) {
	store := testStore(t)
	rev, _ := store.Save(SavedSession{"first", ID()}, "empty")
	engine := NewEngine(store)
	engine.devices["dev_old"] = device{serverID: "old", ac: true}
	engine.ids["old"] = "dev_old"
	store.Save(SavedSession{"second", ID()}, rev)
	if engine.Status()["session_source"] != "restored" {
		t.Fatal("not restored")
	}
	done, err := engine.enter(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer done()
	if len(engine.devices) != 0 || len(engine.ids) != 0 {
		t.Fatal("old IDs retained")
	}
}
