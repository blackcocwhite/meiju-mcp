package core

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const testVaultKey = "meiju-mcp.go.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.encryption-key"

func mockNative(t *testing.T, response string) NativeVault {
	t.Helper()
	return NativeVault{resolve: func() (string, error) { return "/fixed/MeijuVaultHelper", nil }, run: func(ctx context.Context, path string, args []string, input []byte) ([]byte, error) {
		if path != "/fixed/MeijuVaultHelper" || len(args) != 0 {
			t.Fatal("runtime requested UI or changed helper identity")
		}
		deadline, ok := ctx.Deadline()
		if !ok || deadline.IsZero() {
			t.Fatal("missing timeout")
		}
		var request helperRequest
		if Decode(input, &request) != nil || request.Key != testVaultKey {
			t.Fatal("invalid pipe request")
		}
		return []byte(response), nil
	}}
}
func TestFixedHelperPipeAndMissingSemantics(t *testing.T) {
	v := mockNative(t, `{"ok":true,"found":false,"value":""}`)
	value, err := v.Get(testVaultKey)
	if err != nil || value != nil {
		t.Fatal("missing misclassified")
	}
	encoded := base64.StdEncoding.EncodeToString([]byte(strings.Repeat("x", 32)))
	v = mockNative(t, `{"ok":true,"found":true,"value":"`+encoded+`"}`)
	value, err = v.Get(testVaultKey)
	if err != nil || len(value) != 32 {
		t.Fatal("read failed")
	}
}
func TestHelperFailuresNeverTriggerInteractiveRetry(t *testing.T) {
	for _, code := range []string{"storage_authorization_required", "storage_unavailable", "storage_item_exists"} {
		calls := 0
		v := mockNative(t, "")
		v.run = func(context.Context, string, []string, []byte) ([]byte, error) {
			calls++
			return []byte(`{"ok":false,"found":false,"value":"","code":"` + code + `"}`), nil
		}
		_, err := v.Get(testVaultKey)
		if safeCode(err) != code || calls != 1 {
			t.Fatal("wrong mapping or retry", code, calls)
		}
	}
}
func TestHelperProtocolRejectsMalformedReplies(t *testing.T) {
	for _, reply := range []string{`not json`, `{"ok":true}`, `{"ok":true,"found":null,"value":""}`, `{"ok":true,"found":false,"value":null}`, `{"ok":true,"found":true,"value":""}`, `{"ok":true,"found":false,"value":"eA=="}`, `{"ok":true,"found":false,"value":"","token":"private"}`, `{"ok":true,"found":false,"value":""} {}`, strings.Repeat("x", 4097)} {
		v := mockNative(t, reply)
		if _, err := v.Get(testVaultKey); err == nil {
			t.Fatal("malformed reply accepted")
		}
	}
}
func TestHelperTimeoutAndSecretErrorRedaction(t *testing.T) {
	v := mockNative(t, "")
	v.run = func(context.Context, string, []string, []byte) ([]byte, error) {
		return nil, errors.New("private-secret")
	}
	_, err := v.Get(testVaultKey)
	if err == nil || strings.Contains(err.Error(), "private-secret") {
		t.Fatal("error leak")
	}
}
func TestHelperRejectsInvalidInputBeforeResolving(t *testing.T) {
	v := NativeVault{resolve: func() (string, error) { t.Fatal("invalid request reached helper resolver"); return "", nil }}
	for _, key := range []string{"other-service", "meiju-mcp.go.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.password", testVaultKey + "\n"} {
		if _, err := v.Get(key); err == nil {
			t.Fatal("bad key accepted")
		}
	}
	if v.Set(testVaultKey, []byte("short")) == nil {
		t.Fatal("short value accepted")
	}
}
func TestNativeAccessCanBeDisabledWithoutLaunchingAnything(t *testing.T) {
	t.Setenv("MEIJU_TEST_NO_NATIVE_VAULT", "1")
	v := NativeVault{resolve: func() (string, error) { t.Fatal("native access attempted"); return "", nil }}
	if _, err := v.Get(testVaultKey); safeCode(err) != "storage_native_disabled" {
		t.Fatal(err)
	}
}
func TestInteractiveModeRequiresExplicitClient(t *testing.T) {
	v := mockNative(t, "")
	v.allowUI = true
	v.run = func(_ context.Context, _ string, args []string, _ []byte) ([]byte, error) {
		if len(args) != 1 || args[0] != "--authorize" {
			t.Fatal("explicit UI mode missing")
		}
		return []byte(`{"ok":true,"found":false,"value":""}`), nil
	}
	if _, err := v.Get(testVaultKey); err != nil {
		t.Fatal(err)
	}
}
func TestHelperIdentityRejectsTamperingAndSymlink(t *testing.T) {
	root := filepath.Join(canonicalTemp(t), "helper")
	if err := PrivateDir(root); err != nil {
		t.Fatal(err)
	}
	exe := helperExecutable(root)
	os.MkdirAll(filepath.Dir(exe), 0700)
	os.WriteFile(exe, []byte("immutable mock binary"), 0700)
	sum := sha256.Sum256([]byte("immutable mock binary"))
	manifest := HelperInstallation{1, HelperIdentifier, HelperBackend, hex.EncodeToString(sum[:]), "test-fixture"}
	raw, _ := JSON(manifest)
	os.WriteFile(filepath.Join(root, "installation.json"), raw, 0600)
	if _, _, err := verifyHelperFiles(root); err != nil {
		t.Fatal(err)
	}
	manifestPath := filepath.Join(root, "installation.json")
	os.Chmod(manifestPath, 0644)
	if _, _, err := verifyHelperFiles(root); err == nil {
		t.Fatal("public manifest accepted")
	}
	os.Chmod(manifestPath, 0600)
	os.Rename(manifestPath, manifestPath+".real")
	os.Symlink(manifestPath+".real", manifestPath)
	if _, _, err := verifyHelperFiles(root); err == nil {
		t.Fatal("redirected manifest accepted")
	}
	os.Remove(manifestPath)
	os.Rename(manifestPath+".real", manifestPath)
	os.WriteFile(exe, []byte("changed binary"), 0700)
	if _, _, err := verifyHelperFiles(root); err == nil {
		t.Fatal("tampered binary accepted")
	}
	os.Remove(exe)
	os.Symlink("/bin/false", exe)
	if _, _, err := verifyHelperFiles(root); err == nil {
		t.Fatal("symlink accepted")
	}
}

type identifiedMockVault struct{ *memoryVault }

func (identifiedMockVault) BackendID() string { return HelperBackend }
func TestLegacyProfileCannotBeSilentlyMigrated(t *testing.T) {
	store := NewStore(filepath.Join(canonicalTemp(t), "legacy"), identifiedMockVault{&memoryVault{data: map[string][]byte{}}})
	PrivateDir(store.Dir)
	path := filepath.Join(store.Dir, "client-auth.json")
	os.WriteFile(path, []byte(`{"app":"legacy-verifier"}`), 0600)
	if err := store.EnsureBackend(); safeCode(err) != "storage_migration_required" {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(path)
	if string(b) != `{"app":"legacy-verifier"}` {
		t.Fatal("legacy overwritten")
	}
	if len(store.Vault.(identifiedMockVault).data) != 0 {
		t.Fatal("vault touched")
	}
}
func TestEncryptionKeyPreparedBeforeLoginAndReused(t *testing.T) {
	store := testStore(t)
	if err := PrepareEncryptionKey(store); err != nil {
		t.Fatal(err)
	}
	before, _ := store.Vault.Get(testKey(t, store, "encryption-key"))
	if len(before) != 32 {
		t.Fatal("no key prepared")
	}
	if err := PrepareEncryptionKey(store); err != nil {
		t.Fatal(err)
	}
	after, _ := store.Vault.Get(testKey(t, store, "encryption-key"))
	if string(before) != string(after) {
		t.Fatal("key rotated implicitly")
	}
}

func TestEncryptedRestartThroughMockHelperProtocol(t *testing.T) {
	values := map[string][]byte{}
	sets := 0
	v := NativeVault{resolve: func() (string, error) { return "/fixed/helper", nil }, run: func(_ context.Context, _ string, args []string, input []byte) ([]byte, error) {
		if len(args) != 0 {
			t.Fatal("mock flow requested OS interaction")
		}
		var req helperRequest
		if Decode(input, &req) != nil {
			t.Fatal("input")
		}
		out := helperResponse{OK: true}
		switch req.Action {
		case "get":
			value, found := values[req.Key]
			out.Found = found
			out.Value = base64.StdEncoding.EncodeToString(value)
		case "set":
			if _, exists := values[req.Key]; exists {
				out.OK = false
				out.Code = "storage_item_exists"
			} else {
				b, err := base64.StdEncoding.DecodeString(req.Value)
				if err != nil || len(b) != 32 {
					t.Fatal("invalid set")
				}
				values[req.Key] = b
				sets++
			}
		case "delete":
			delete(values, req.Key)
		default:
			t.Fatal("action")
		}
		b, _ := JSON(out)
		return b, nil
	}}
	store := NewStore(filepath.Join(canonicalTemp(t), "session"), v)
	if err := PrepareEncryptionKey(store); err != nil {
		t.Fatal(err)
	}
	rev, _, err := store.Load()
	if err != nil {
		t.Fatal(err)
	}
	if _, err = store.Save(SavedSession{"synthetic-persisted-login", ID()}, rev); err != nil {
		t.Fatal(err)
	}
	restarted := NewEngine(store)
	state := restarted.Status()
	if state["authenticated"] != true || state["session_source"] != "restored" || sets != 1 {
		t.Fatal("restart or key reuse failed")
	}
	if _, err = restarted.Logout(); err != nil {
		t.Fatal(err)
	}
	if NewEngine(store).Status()["authenticated"] != false {
		t.Fatal("logout not persistent")
	}
}
