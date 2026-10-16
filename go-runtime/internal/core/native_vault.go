package core

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"time"
)

const HelperIdentifier = "local.meiju.mcp.vault-helper"
const HelperBackend = "meiju-vault-v1"
const helperMaxOutput = 4096

var vaultKeyPattern = regexp.MustCompile(`^meiju-mcp\.go\.[a-f0-9]{32}\.(encryption-key|client-app|client-codex)$`)

type helperRequest struct {
	Action string `json:"action"`
	Key    string `json:"key"`
	Value  string `json:"value"`
}
type helperResponse struct {
	OK    bool   `json:"ok"`
	Found bool   `json:"found"`
	Value string `json:"value"`
	Code  string `json:"code,omitempty"`
}
type HelperInstallation struct {
	Protocol   int    `json:"protocol"`
	Identifier string `json:"identifier"`
	Backend    string `json:"backend"`
	SHA256     string `json:"sha256"`
	Signing    string `json:"signing"`
}

// Resolver/runner are private injection points for unit tests. Production never
// resolves a helper from PATH, the current executable, a profile, or an env var.
type NativeVault struct {
	resolve func() (string, error)
	run     func(context.Context, string, []string, []byte) ([]byte, error)
	allowUI bool
}

func (NativeVault) BackendID() string { return HelperBackend }
func DefaultHelperRoot() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", Err("storage_helper_unavailable")
	}
	if runtime.GOOS == "darwin" {
		return filepath.Join(home, "Library", "Application Support", "MeijuMCP", "VaultHelper"), nil
	}
	if runtime.GOOS == "windows" {
		return filepath.Join(os.Getenv("LOCALAPPDATA"), "MeijuMCP", "VaultHelper"), nil
	}
	return filepath.Join(home, ".local", "share", "meiju-mcp", "vault-helper"), nil
}
func helperExecutable(root string) string {
	if runtime.GOOS == "darwin" {
		return filepath.Join(root, "MeijuVaultHelper.app", "Contents", "MacOS", "MeijuVaultHelper")
	}
	if runtime.GOOS == "windows" {
		return filepath.Join(root, "meiju-vault-helper.exe")
	}
	return filepath.Join(root, "meiju-vault-helper")
}
func verifyHelperFiles(root string) (string, HelperInstallation, error) {
	var manifest HelperInstallation
	// Read only: a missing helper must not create a directory or launch an installer.
	clean, err := filepath.EvalSymlinks(root)
	if err != nil || clean != filepath.Clean(root) {
		return "", manifest, Err("storage_helper_unavailable")
	}
	fi, err := os.Stat(root)
	if err != nil || !fi.IsDir() || checkPrivate(root, fi) != nil {
		return "", manifest, Err("storage_helper_identity")
	}
	raw, err := PrivateRead(filepath.Join(root, "installation.json"))
	if err != nil || Decode(raw, &manifest) != nil {
		return "", manifest, Err("storage_helper_identity")
	}
	if manifest.Protocol != 1 || manifest.Identifier != HelperIdentifier || manifest.Backend != HelperBackend || len(manifest.SHA256) != 64 {
		return "", manifest, Err("storage_helper_identity")
	}
	executable := helperExecutable(root)
	canonical, err := filepath.EvalSymlinks(executable)
	if err != nil || canonical != executable {
		return "", manifest, Err("storage_helper_identity")
	}
	fi, err = os.Stat(executable)
	if err != nil || !fi.Mode().IsRegular() || fi.Size() > 32*1024*1024 || checkPrivate(executable, fi) != nil {
		return "", manifest, Err("storage_helper_identity")
	}
	file, err := os.Open(executable)
	if err != nil {
		return "", manifest, Err("storage_helper_identity")
	}
	defer file.Close()
	digest := sha256.New()
	if _, err = io.Copy(digest, file); err != nil || hex.EncodeToString(digest.Sum(nil)) != manifest.SHA256 {
		return "", manifest, Err("storage_helper_identity")
	}
	return executable, manifest, nil
}
func resolveInstalledHelper() (string, error) {
	root, err := DefaultHelperRoot()
	if err != nil {
		return "", err
	}
	path, _, err := verifyHelperFiles(root)
	if err != nil {
		return "", err
	}
	if runtime.GOOS == "darwin" {
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		// Verify signature AND identifier after pinning the exact, user-installed binary.
		requirement := `=identifier "` + HelperIdentifier + `"`
		cmd := exec.CommandContext(ctx, "/usr/bin/codesign", "--verify", "--strict", "-R", requirement, filepath.Join(root, "MeijuVaultHelper.app"))
		cmd.Stdout = io.Discard
		cmd.Stderr = io.Discard
		if cmd.Run() != nil {
			return "", Err("storage_helper_identity")
		}
	}
	return path, nil
}
func (n NativeVault) call(action, key string, value []byte) ([]byte, error) {
	if !vaultKeyPattern.MatchString(key) || !((action == "get" || action == "delete") && len(value) == 0 || action == "set" && len(value) == 32) {
		return nil, Err("storage_invalid_request")
	}
	if n.run == nil && os.Getenv("MEIJU_TEST_NO_NATIVE_VAULT") == "1" {
		return nil, Err("storage_native_disabled")
	}
	resolve := n.resolve
	if resolve == nil {
		resolve = resolveInstalledHelper
	}
	path, err := resolve()
	if err != nil {
		return nil, err
	}
	args := []string{}
	timeout := 12 * time.Second
	if n.allowUI {
		args = []string{"--authorize"}
		timeout = 90 * time.Second
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	input, _ := JSON(helperRequest{action, key, base64.StdEncoding.EncodeToString(value)})
	run := n.run
	if run == nil {
		run = runFixedHelper
	}
	raw, err := run(ctx, path, args, input)
	if err != nil {
		return nil, Err("storage_unavailable")
	}
	if len(raw) > helperMaxOutput {
		return nil, Err("storage_corrupt")
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil || fields["ok"] == nil || fields["found"] == nil || fields["value"] == nil {
		return nil, Err("storage_corrupt")
	}
	for _, name := range []string{"ok", "found"} {
		v := string(fields[name])
		if v != "true" && v != "false" {
			return nil, Err("storage_corrupt")
		}
	}
	if string(fields["value"]) == "null" {
		return nil, Err("storage_corrupt")
	}
	var response helperResponse
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&response) != nil {
		return nil, Err("storage_corrupt")
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return nil, Err("storage_corrupt")
	}
	if !response.OK {
		switch response.Code {
		case "storage_unavailable", "storage_authorization_required", "storage_item_exists", "storage_corrupt", "storage_invalid_request":
			return nil, Err(response.Code)
		default:
			return nil, Err("storage_unavailable")
		}
	}
	data, err := base64.StdEncoding.DecodeString(response.Value)
	if err != nil {
		return nil, Err("storage_corrupt")
	}
	if action == "get" {
		if !response.Found && len(data) == 0 {
			return nil, nil
		}
		if !response.Found || len(data) != 32 {
			return nil, Err("storage_corrupt")
		}
		return data, nil
	}
	if len(data) != 0 || response.Found {
		return nil, Err("storage_corrupt")
	}
	return nil, nil
}
func (n NativeVault) Get(k string) ([]byte, error) { return n.call("get", k, nil) }
func (n NativeVault) Set(k string, b []byte) error { _, err := n.call("set", k, b); return err }
func (n NativeVault) Delete(k string) error        { _, err := n.call("delete", k, nil); return err }

// Only an explicit CLI authorization command may request UI. Normal MCP tools,
// bridge connections and login persistence all use the zero-value silent client.
func InteractiveVault() Vault { return NativeVault{allowUI: true} }
func HelperCheck() error      { _, err := resolveInstalledHelper(); return err }

type limitedOutput struct{ bytes.Buffer }

func (b *limitedOutput) Write(p []byte) (int, error) {
	if len(p) > helperMaxOutput-b.Len() {
		return 0, errors.New("helper response too large")
	}
	return b.Buffer.Write(p)
}
func runFixedHelper(ctx context.Context, path string, args []string, input []byte) ([]byte, error) {
	cmd := exec.CommandContext(ctx, path, args...)
	cmd.Stdin = bytes.NewReader(input)
	out := &limitedOutput{}
	cmd.Stdout = out
	cmd.Stderr = io.Discard
	// No secret in argv, env or logs. Drop dynamic-library injection variables.
	env := []string{}
	for _, entry := range os.Environ() {
		if !strings.HasPrefix(entry, "DYLD_") && !strings.HasPrefix(entry, "LD_PRELOAD=") {
			env = append(env, entry)
		}
	}
	cmd.Env = env
	if err := cmd.Run(); err != nil {
		return nil, err
	}
	return out.Bytes(), nil
}

// Prepare a key before human login, so a denied OS authorization doesn't require
// another SMS login. It never reads or migrates any Meiju access token.
func PrepareEncryptionKey(store *Store) error {
	return store.locked(func() error {
		key, err := store.Key("encryption-key")
		if err != nil {
			return err
		}
		value, err := store.Vault.Get(key)
		if err != nil {
			return err
		}
		if len(value) == 32 {
			return nil
		}
		if len(value) != 0 {
			return Err("storage_corrupt")
		}
		var value32 [32]byte
		if _, err := rand.Read(value32[:]); err != nil {
			return Err("storage_unavailable")
		}
		return store.Vault.Set(key, value32[:])
	})
}
