// Offline acceptance harness. Never installed as the production service.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"github.com/blackcocwhite/meiju-mcp/go-runtime/internal/core"
	"github.com/blackcocwhite/meiju-mcp/go-runtime/internal/service"
	"github.com/blackcocwhite/meiju-mcp/go-runtime/internal/testsupport"
	"net/http"
	"net/http/httptest"
	"os"
	"os/signal"
	"path/filepath"
	"sync"
	"syscall"
)

func main() {
	bridge := len(os.Args) >= 2 && os.Args[1] == "bridge"
	if len(os.Args) != 2 && !bridge {
		fmt.Fprintln(os.Stderr, "Usage: offline-harness PRIVATE_TEST_DIRECTORY")
		os.Exit(1)
	}
	directory := os.Args[1]
	client := "codex"
	if bridge {
		fs := flag.NewFlagSet("bridge", flag.ExitOnError)
		dirFlag := fs.String("session-dir", "", "Synthetic profile only")
		clientFlag := fs.String("client", "codex", "app or codex")
		fs.Parse(os.Args[2:])
		directory, client = *dirFlag, *clientFlag
		if directory == "" && fs.NArg() == 1 {
			directory = fs.Arg(0)
		}
		if directory == "" {
			os.Exit(1)
		}
	}
	dir, _ := filepath.Abs(directory)
	store := core.NewStore(dir, testsupport.Vault{})
	if bridge {
		if service.Bridge(context.Background(), store, client) != nil {
			os.Exit(1)
		}
		return
	}
	if _, err := os.Stat(filepath.Join(dir, "client-auth.json")); os.IsNotExist(err) {
		if err := service.Enroll(store); err != nil {
			fmt.Fprintln(os.Stderr, "test credential enrollment failed")
			os.Exit(1)
		}
	}
	var mu sync.Mutex
	state := core.Object{"power": "off", "temperature": 25, "small_temperature": 0.5, "indoor_temperature": 27, "mode": "auto", "wind_speed": 102}
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		var data any
		switch r.URL.Query().Get("alias") {
		case core.SMS:
			json.NewEncoder(w).Encode(core.Object{"code": 0})
			return
		case core.Login:
			data = core.Object{"mdata": core.Object{"accessToken": "synthetic-only-offline-token"}}
		case core.Homes:
			data = core.Object{"homeList": []any{core.Object{"homegroupId": "synthetic-home", "name": "合成数据测试"}}}
		case core.Devices:
			data = core.Object{"homeList": []any{core.Object{"homegroupId": "synthetic-home", "roomList": []any{core.Object{"name": "测试房间", "applianceList": []any{core.Object{"applianceCode": "synthetic-device", "name": "合成测试空调（非真机）", "type": "0xAC", "onlineStatus": 1, "sn8": "99999999"}}}}}}}
		case core.Status:
			data = state
		case core.Control:
			var req core.Object
			json.NewDecoder(r.Body).Decode(&req)
			command, _ := req["command"].(map[string]any)
			changes, _ := command["control"].(map[string]any)
			for k, v := range changes {
				state[k] = v
			}
			data = core.Object{}
		default:
			http.Error(w, "unexpected endpoint", 400)
			return
		}
		json.NewEncoder(w).Encode(core.Object{"code": 0, "data": data})
	}))
	defer fake.Close()
	engine := core.NewEngineWithHTTP(store, fake.Client(), fake.URL)
	json.NewEncoder(os.Stdout).Encode(engine.Status())
	if engine.Status()["authenticated"] != true {
		if _, err := engine.SMS(context.Background(), "13800138000", ""); err != nil {
			panic("synthetic SMS failed")
		}
		if engine.Verify(context.Background(), "13800138000", "123456") != nil {
			panic("synthetic login failed")
		}
		saved, err := engine.Finish(true)
		if err != nil || saved["persistence_status"] != "saved" {
			panic("synthetic persistence failed")
		}
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	fmt.Println("OFFLINE ONLY: synthetic cloud and account; no real appliance requests.")
	if err := service.Serve(ctx, store, engine); err != nil {
		fmt.Fprintln(os.Stderr, "offline service failed")
		os.Exit(1)
	}
}
