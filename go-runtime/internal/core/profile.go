package core

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"regexp"
)

type profileIdentity struct {
	Version int    `json:"version"`
	VaultID string `json:"vault_id"`
}

var profilePattern = regexp.MustCompile(`^[a-f0-9]{32}$`)

func (s *Store) profileID() (string, error) {
	raw, err := PrivateRead(filepath.Join(s.Dir, "profile.json"))
	if err != nil {
		return "", err
	}
	var identity profileIdentity
	if Decode(raw, &identity) != nil || identity.Version != 1 || !profilePattern.MatchString(identity.VaultID) {
		return "", Err("storage_profile_invalid")
	}
	return identity.VaultID, nil
}
func (s *Store) Key(name string) (string, error) {
	if name != "encryption-key" && name != "client-app" && name != "client-codex" {
		return "", Err("storage_invalid_request")
	}
	if err := PrivateDir(s.Dir); err != nil {
		return "", err
	}
	if _, err := os.Lstat(filepath.Join(s.Dir, "migration.pending")); err == nil || !os.IsNotExist(err) {
		return "", Err("storage_migration_incomplete")
	}
	id, err := s.profileID()
	if os.IsNotExist(err) {
		// Only legacy profiles may derive their namespace from a path.
		if raw, e := PrivateRead(filepath.Join(s.Dir, "vault-backend.json")); e == nil {
			var marker struct {
				Backend string `json:"backend"`
				Version int    `json:"version"`
			}
			if Decode(raw, &marker) != nil || marker.Version != 1 {
				return "", Err("storage_profile_invalid")
			}
		} else if !os.IsNotExist(e) {
			return "", e
		}
		p, _ := filepath.Abs(s.Dir)
		h := sha256.Sum256([]byte(p))
		id = hex.EncodeToString(h[:16])
	} else if err != nil {
		return "", Err("storage_profile_invalid")
	}
	return "meiju-mcp.go." + id + "." + name, nil
}

// Called under session.lock. Never implicitly changes a legacy identity.
func (s *Store) ensureProfile() error {
	if _, err := os.Lstat(filepath.Join(s.Dir, "migration.pending")); err == nil || !os.IsNotExist(err) {
		return Err("storage_migration_incomplete")
	}
	if _, err := s.profileID(); err == nil {
		return nil
	} else if !os.IsNotExist(err) {
		return Err("storage_profile_invalid")
	}
	for _, name := range []string{"session.json", "client-auth.json", "vault-backend.json"} {
		if _, err := os.Lstat(filepath.Join(s.Dir, name)); err == nil {
			return nil
		} else if !os.IsNotExist(err) {
			return Err("storage_unsafe")
		}
	}
	raw, _ := JSON(profileIdentity{1, ID()})
	return AtomicWrite(filepath.Join(s.Dir, "profile.json"), raw)
}
