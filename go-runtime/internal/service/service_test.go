package service

import (
	"context"
	"encoding/json"
	"github.com/blackcocwhite/meiju-mcp/go-runtime/internal/core"
	"github.com/modelcontextprotocol/go-sdk/mcp"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

type vault struct {
	mu sync.Mutex
	m  map[string][]byte
}

func (v *vault) Get(k string) ([]byte, error) { v.mu.Lock(); defer v.mu.Unlock(); return v.m[k], nil }
func (v *vault) Set(k string, b []byte) error {
	v.mu.Lock()
	defer v.mu.Unlock()
	v.m[k] = b
	return nil
}
func (v *vault) Delete(k string) error { v.mu.Lock(); defer v.mu.Unlock(); delete(v.m, k); return nil }
func TestMCPStrictSchemaAndDiscovery(t *testing.T) {
	ctx := context.Background()
	engine := core.NewEngine(nil)
	portal := NewPortal(engine)
	defer portal.Close()
	server, err := NewMCP(LocalCaller(engine, portal))
	if err != nil {
		t.Fatal(err)
	}
	a, b := mcp.NewInMemoryTransports()
	ss, err := server.Connect(ctx, a, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer ss.Close()
	client := mcp.NewClient(&mcp.Implementation{Name: "test", Version: "1"}, nil)
	cs, err := client.Connect(ctx, b, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer cs.Close()
	list, err := cs.ListTools(ctx, nil)
	if err != nil || len(list.Tools) != 7 {
		t.Fatal(err)
	}
	for _, args := range []core.Object{{"device_id": "x", "power": "false"}, {"device_id": "x", "power": 1}, {"device_id": "x", "power": true, "swing": true}, {"device_id": "x", "target_temperature": 26.2}} {
		r, err := cs.CallTool(ctx, &mcp.CallToolParams{Name: "meiju_control", Arguments: args})
		if err != nil || !r.IsError {
			t.Fatal("input accepted", err)
		}
	}
	r, err := cs.CallTool(ctx, &mcp.CallToolParams{Name: "meiju_login_status", Arguments: core.Object{}})
	if err != nil || r.IsError {
		t.Fatal(err)
	}
}
func TestPortalOriginsAndNoCredentialsInTools(t *testing.T) {
	p := NewPortal(core.NewEngine(nil))
	defer p.Close()
	result, err := p.Start()
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(result["login_url"].(string), "http://127.0.0.1:") {
		t.Fatal("not local")
	}
	for _, origin := range []string{"", "https://evil.test"} {
		req, _ := http.NewRequest("POST", p.origin+"/api/login", strings.NewReader(`{"mobile":"13800138000","code":"123456"}`))
		req.Header.Set("Origin", origin)
		req.Header.Set("X-Meiju-Flow", p.secret)
		req.Header.Set("Content-Type", "application/json")
		r, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		r.Body.Close()
		if r.StatusCode != 403 {
			t.Fatal("origin allowed")
		}
	}
	req, _ := http.NewRequest("POST", p.origin+"/api/login", strings.NewReader(`{"mobile":"13800138000","code":"123456","remember":"true"}`))
	req.Header.Set("Origin", p.origin)
	req.Header.Set("X-Meiju-Flow", p.secret)
	req.Header.Set("Content-Type", "application/json")
	r, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Body.Close()
	if r.StatusCode != 400 {
		t.Fatal("remember coercion")
	}
}
func TestSharedDaemonTwoClientsAndTLS(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	store := core.NewStore(filepath.Join(canonicalTemp(t), "daemon"), &vault{m: map[string][]byte{}})
	if err := Enroll(store); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- Serve(ctx, store, core.NewEngine(nil)) }()
	path := filepath.Join(store.Dir, "endpoint.json")
	for i := 0; i < 100; i++ {
		if _, err := os.Stat(path); err == nil {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	first, err := Connect(ctx, store, "app")
	if err != nil {
		t.Fatal(err)
	}
	defer first.Close()
	second, err := Connect(ctx, store, "codex")
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()
	for _, c := range []*mcp.ClientSession{first, second} {
		list, err := c.ListTools(ctx, nil)
		if err != nil || len(list.Tools) != 7 {
			t.Fatal(err)
		}
	}
	first.Close()
	if _, err = second.CallTool(ctx, &mcp.CallToolParams{Name: "meiju_login_status"}); err != nil {
		t.Fatal("other client impacted", err)
	}
	raw, _ := os.ReadFile(path)
	var ep Endpoint
	json.Unmarshal(raw, &ep)
	if _, err = http.Get(ep.URL); err == nil {
		t.Fatal("unpinned TLS trusted")
	}
	if err = Serve(ctx, store, core.NewEngine(nil)); err == nil {
		t.Fatal("duplicate daemon")
	}
	cancel()
	if err = <-done; err != nil {
		t.Fatal(err)
	}
}
func TestBadHostPortal(t *testing.T) {
	p := NewPortal(core.NewEngine(nil))
	p.origin = "http://127.0.0.1:1234"
	r := httptest.NewRequest("GET", "http://evil.test/", nil)
	w := httptest.NewRecorder()
	p.serve(w, r)
	if w.Code != 403 {
		t.Fatal("bad host")
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

func TestRevocationKeepsOtherClient(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	store := core.NewStore(filepath.Join(canonicalTemp(t), "revoke"), &vault{m: map[string][]byte{}})
	if err := Enroll(store); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- Serve(ctx, store, core.NewEngine(nil)) }()
	for i := 0; i < 100; i++ {
		if _, err := os.Stat(filepath.Join(store.Dir, "endpoint.json")); err == nil {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	app, err := Connect(ctx, store, "app")
	if err != nil {
		t.Fatal(err)
	}
	defer app.Close()
	codex, err := Connect(ctx, store, "codex")
	if err != nil {
		t.Fatal(err)
	}
	defer codex.Close()
	if err = Revoke(store, "app"); err != nil {
		t.Fatal(err)
	}
	if _, err = app.CallTool(ctx, &mcp.CallToolParams{Name: "meiju_login_status"}); err == nil {
		t.Fatal("revoked client accepted")
	}
	if _, err = codex.CallTool(ctx, &mcp.CallToolParams{Name: "meiju_login_status"}); err != nil {
		t.Fatal("other client revoked", err)
	}
	cancel()
	<-done
}

func TestBridgeDiscoveryDoesNotRequireRunningDaemon(t *testing.T) {
	ctx := context.Background()
	server, err := NewMCP(func(context.Context, string, core.Object) (*mcp.CallToolResult, error) {
		return Result(nil, core.Err("service_unavailable")), nil
	})
	if err != nil {
		t.Fatal(err)
	}
	a, b := mcp.NewInMemoryTransports()
	ss, err := server.Connect(ctx, a, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer ss.Close()
	client, err := mcp.NewClient(&mcp.Implementation{Name: "discovery-test", Version: "1"}, nil).Connect(ctx, b, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	tools, err := client.ListTools(ctx, nil)
	if err != nil || len(tools.Tools) != 7 {
		t.Fatal("discovery needs daemon")
	}
	status, err := client.CallTool(ctx, &mcp.CallToolParams{Name: "meiju_login_status"})
	if err != nil || !status.IsError {
		t.Fatal("offline backend not reported")
	}
}
