package main

import (
	"context"
	"flag"
	"fmt"
	"github.com/blackcocwhite/meiju-mcp/go-runtime/internal/core"
	"github.com/blackcocwhite/meiju-mcp/go-runtime/internal/service"
	"github.com/modelcontextprotocol/go-sdk/mcp"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"syscall"
)

func main() {
	if err := run(); err != nil {
		if safe, ok := err.(*core.SafeError); ok {
			fmt.Fprintln(os.Stderr, "meiju-mcp:", safe.Code)
		} else {
			fmt.Fprintln(os.Stderr, "meiju-mcp: operation failed; check local service or credential-store status")
		}
		os.Exit(1)
	}
}
func run() error {
	args := os.Args[1:]
	mode := "stdio"
	if len(args) > 0 && len(args[0]) > 0 && args[0][0] != '-' {
		mode = args[0]
		args = args[1:]
	}
	if mode == "vault-helper" {
		return core.Err("storage_helper_required")
	}
	fs := flag.NewFlagSet("meiju-mcp", flag.ContinueOnError)
	home, _ := os.UserHomeDir()
	dirDefault := filepath.Join(home, ".local", "share", "meiju-mcp-go", "session")
	if runtime.GOOS == "darwin" {
		dirDefault = filepath.Join(home, "Library", "Application Support", "meiju-mcp-go", "session")
	}
	if runtime.GOOS == "windows" {
		dirDefault = filepath.Join(os.Getenv("LOCALAPPDATA"), "meiju-mcp-go", "session")
	}
	dir := fs.String("session-dir", dirDefault, "Private storage directory")
	sessionOnly := fs.Bool("session-only", false, "Disable saved login")
	version := fs.Bool("version", false, "Print development version")
	forget := fs.Bool("forget-saved-login", false, "Explicitly forget saved login")
	client := fs.String("client", "codex", "Connector identity: app or codex")
	destination := fs.String("destination", "", "New private directory for explicit encrypted profile migration")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *version {
		fmt.Println(service.BuildVersion)
		return nil
	}
	if *sessionOnly && *forget {
		return core.Err("invalid_input")
	}
	abs, err := filepath.Abs(*dir)
	if err != nil {
		return err
	}
	store := core.NewStore(abs, nil)
	if *forget {
		return store.Forget("")
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	switch mode {
	case "migrate-profile":
		if *destination == "" {
			return core.Err("invalid_input")
		}
		return core.MigrateProfile(abs, *destination)
	case "helper-check":
		if err := core.HelperCheck(); err != nil {
			return err
		}
		fmt.Println("Fixed helper identity verified; no Keychain access performed.")
		return nil
	case "prepare-helper", "authorize-helper":
		// First try silent preparation. Only explicit authorize-helper may show UI.
		prepared := store
		if mode == "authorize-helper" {
			prepared = core.NewStore(abs, core.InteractiveVault())
		}
		if err := service.Enroll(prepared); err != nil {
			return err
		}
		return core.PrepareEncryptionKey(prepared)
	case "enroll":
		return service.Enroll(store)
	case "revoke":
		return service.Revoke(store, *client)
	case "bridge":
		return service.Bridge(ctx, store, *client)
	case "service-plist":
		exe, _ := os.Executable()
		p, err := service.LaunchAgent(exe, abs, "local.meiju.mcp.go.test")
		if err == nil {
			fmt.Println(p)
		}
		return err
	case "serve", "stdio":
	default:
		return core.Err("invalid_input")
	}
	var sessionStore *core.Store
	if !*sessionOnly {
		sessionStore = store
	}
	engine := core.NewEngine(sessionStore)
	if mode == "serve" {
		return service.Serve(ctx, store, engine)
	}
	portal := service.NewPortal(engine)
	defer portal.Close()
	server, err := service.NewMCP(service.LocalCaller(engine, portal))
	if err != nil {
		return err
	}
	return server.Run(ctx, &mcp.StdioTransport{})
}
