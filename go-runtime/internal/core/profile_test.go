package core

import (
	"github.com/gofrs/flock"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func testKey(t *testing.T, s *Store, name string) string {
	t.Helper()
	key, err := s.Key(name)
	if err != nil {
		t.Fatal(err)
	}
	return key
}
func legacyProfile(t *testing.T) *Store {
	t.Helper()
	s := NewStore(filepath.Join(canonicalTemp(t), "legacy"), identifiedMockVault{&memoryVault{data: map[string][]byte{}}})
	if err := PrivateDir(s.Dir); err != nil {
		t.Fatal(err)
	}
	AtomicWrite(filepath.Join(s.Dir, "vault-backend.json"), []byte(`{"backend":"meiju-vault-v1","version":1}`))
	if _, err := s.Save(SavedSession{"synthetic-migration-token", ID()}, "empty"); err != nil {
		t.Fatal(err)
	}
	// Revoked app is intentionally absent and must remain revoked.
	AtomicWrite(filepath.Join(s.Dir, "client-auth.json"), []byte(`{"codex":"`+strings.Repeat("a", 64)+`"}`))
	s.Vault.Set(testKey(t, s, "client-codex"), []byte(strings.Repeat("c", 32)))
	return s
}
func TestProfileMigrationPreservesEncryptedLoginAndRevocations(t *testing.T) {
	s := legacyProfile(t)
	dst := filepath.Join(canonicalTemp(t), "private", "new")
	oldKey := testKey(t, s, "encryption-key")
	before, _ := os.ReadFile(filepath.Join(s.Dir, "session.json"))
	if err := MigrateProfile(s.Dir, dst); err != nil {
		t.Fatal(err)
	}
	m := NewStore(dst, s.Vault)
	if testKey(t, m, "encryption-key") != oldKey {
		t.Fatal("key changed")
	}
	_, saved, err := m.Load()
	if err != nil || saved.Token != "synthetic-migration-token" {
		t.Fatal("restore failed", err)
	}
	after, _ := os.ReadFile(filepath.Join(dst, "session.json"))
	if string(before) != string(after) {
		t.Fatal("ciphertext changed")
	}
	clients, _ := os.ReadFile(filepath.Join(dst, "client-auth.json"))
	if strings.Contains(string(clients), "app") {
		t.Fatal("revoked client resurrected")
	}
	if _, err := os.Stat(filepath.Join(s.Dir, "profile.json")); !os.IsNotExist(err) {
		t.Fatal("source changed")
	}
	// Old format/source and stable-ID copy both remain readable for controlled rollback.
	_, old, err := s.Load()
	if err != nil || old.Token != saved.Token {
		t.Fatal("rollback source lost")
	}
	third := filepath.Join(canonicalTemp(t), "private", "second-move")
	if err := MigrateProfile(dst, third); err != nil {
		t.Fatal(err)
	}
	if _, again, err := NewStore(third, s.Vault).Load(); err != nil || again.Token != saved.Token {
		t.Fatal("second move failed", err)
	}
}
func TestMigrationRejectsBusySourceAndExistingDestination(t *testing.T) {
	s := legacyProfile(t)
	dst := filepath.Join(canonicalTemp(t), "private", "target")
	path := filepath.Join(s.Dir, "daemon.lock")
	EnsureLockFile(path)
	lock := flock.New(path)
	lock.Lock()
	if safeCode(MigrateProfile(s.Dir, dst)) != "migration_source_busy" {
		t.Fatal("live source accepted")
	}
	lock.Unlock()
	os.MkdirAll(dst, 0700)
	os.WriteFile(filepath.Join(dst, "keep"), []byte("keep"), 0600)
	if safeCode(MigrateProfile(s.Dir, dst)) != "migration_destination_exists" {
		t.Fatal("destination overwritten")
	}
	if b, _ := os.ReadFile(filepath.Join(dst, "keep")); string(b) != "keep" {
		t.Fatal("data lost")
	}
}
func TestProfileIdentityCorruptionAndInterruptedMigrationFailClosed(t *testing.T) {
	s := legacyProfile(t)
	dst := filepath.Join(canonicalTemp(t), "private", "target")
	if err := MigrateProfile(s.Dir, dst); err != nil {
		t.Fatal(err)
	}
	m := NewStore(dst, s.Vault)
	original, _ := os.ReadFile(filepath.Join(dst, "profile.json"))
	for _, bad := range []string{`{}`, `{"version":1,"vault_id":"bad"}`, `{"version":1,"vault_id":null}`} {
		AtomicWrite(filepath.Join(dst, "profile.json"), []byte(bad))
		if _, _, err := m.Load(); err == nil {
			t.Fatal("invalid identity accepted")
		}
	}
	os.Remove(filepath.Join(dst, "profile.json"))
	if _, _, err := m.Load(); err == nil {
		t.Fatal("missing identity accepted")
	}
	AtomicWrite(filepath.Join(dst, "profile.json"), original)
	AtomicWrite(filepath.Join(dst, "migration.pending"), []byte("pending"))
	if _, _, err := m.Load(); safeCode(err) != "storage_migration_incomplete" {
		t.Fatal("partial copy accepted", err)
	}
}
func TestNewProfilesUseStableRandomIdentity(t *testing.T) {
	s := testStore(t)
	if err := s.EnsureBackend(); err != nil {
		t.Fatal(err)
	}
	id, err := s.profileID()
	if err != nil || len(id) != 32 {
		t.Fatal("identity")
	}
	key := testKey(t, s, "encryption-key")
	dst := filepath.Join(canonicalTemp(t), "renamed")
	if err := os.Rename(s.Dir, dst); err != nil {
		t.Fatal(err)
	}
	if testKey(t, NewStore(dst, s.Vault), "encryption-key") != key {
		t.Fatal("path-bound identity")
	}
}
