package core

import (
	"encoding/hex"
	"github.com/gofrs/flock"
	"os"
	"path/filepath"
	"strings"
)

// MigrateProfile copies encrypted state only. It never invokes a vault, decrypts
// a token, enrolls a client, deletes keys, or changes the source profile's payloads. Lock files may be created.
// Call only after stopping the source daemon; retain source for rollback.
func MigrateProfile(source, destination string) error {
	src, err := filepath.Abs(source)
	if err != nil {
		return Err("storage_unsafe")
	}
	dst, err := filepath.Abs(destination)
	if err != nil {
		return Err("storage_unsafe")
	}
	if src == dst || strings.HasPrefix(dst, src+string(os.PathSeparator)) || strings.HasPrefix(src, dst+string(os.PathSeparator)) {
		return Err("storage_unsafe")
	}
	info, err := os.Lstat(src)
	if err != nil || !info.IsDir() {
		return Err("storage_unsafe")
	}
	if err := PrivateDir(src); err != nil {
		return err
	}
	locks := []*flock.Flock{}
	defer func() {
		for i := len(locks) - 1; i >= 0; i-- {
			locks[i].Unlock()
		}
	}()
	for _, name := range []string{"daemon.lock", "clients.lock", "session.lock"} {
		path := filepath.Join(src, name)
		if err := EnsureLockFile(path); err != nil {
			return err
		}
		lock := flock.New(path)
		ok, err := lock.TryLock()
		if err != nil || !ok {
			return Err("migration_source_busy")
		}
		locks = append(locks, lock)
	}
	s := NewStore(src, nil)
	name, err := s.Key("encryption-key")
	if err != nil {
		return err
	}
	id := strings.TrimSuffix(strings.TrimPrefix(name, "meiju-mcp.go."), ".encryption-key")
	if !profilePattern.MatchString(id) {
		return Err("storage_profile_invalid")
	}
	backendRaw, err := PrivateRead(filepath.Join(src, "vault-backend.json"))
	if err != nil {
		return err
	}
	var backend struct {
		Backend string `json:"backend"`
		Version int    `json:"version"`
	}
	if Decode(backendRaw, &backend) != nil || (backend.Version != 1 && backend.Version != 2) || (backend.Backend != HelperBackend && backend.Backend != "synthetic-only-public-test-keys-v1") {
		return Err("storage_migration_required")
	}
	if _, err := s.record(); err != nil {
		return err
	}
	files := map[string][]byte{}
	for _, filename := range []string{"session.json", "client-auth.json"} {
		raw, err := PrivateRead(filepath.Join(src, filename))
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return err
		}
		if filename == "client-auth.json" {
			var clients map[string]string
			if Decode(raw, &clients) != nil || clients == nil {
				return Err("storage_corrupt")
			}
			for role, hash := range clients {
				_, decodeErr := hex.DecodeString(hash)
				if (role != "app" && role != "codex") || len(hash) != 64 || decodeErr != nil {
					return Err("storage_corrupt")
				}
			}
		}
		files[filename] = raw
	}
	if _, err := os.Lstat(dst); !os.IsNotExist(err) {
		return Err("migration_destination_exists")
	}
	if err := PrivateDir(filepath.Dir(dst)); err != nil {
		return err
	}
	if err := os.Mkdir(dst, 0700); err != nil {
		return Err("migration_destination_exists")
	}
	if err := restrictNew(dst, true); err != nil {
		return err
	}
	// Any interrupted copy is explicitly unusable, not an empty/new account.
	if err := AtomicWrite(filepath.Join(dst, "migration.pending"), []byte("encrypted profile migration\n")); err != nil {
		return err
	}
	identity, _ := JSON(profileIdentity{1, id})
	files["profile.json"] = identity
	marker, _ := JSON(Object{"backend": backend.Backend, "version": 2})
	files["vault-backend.json"] = marker
	for filename, raw := range files {
		if err := AtomicWrite(filepath.Join(dst, filename), raw); err != nil {
			return err
		}
	}
	dir, err := os.Open(dst)
	if err != nil {
		return err
	}
	defer dir.Close()
	if err = dir.Sync(); err != nil {
		return err
	}
	if err = os.Remove(filepath.Join(dst, "migration.pending")); err != nil {
		return err
	}
	return dir.Sync()
}
