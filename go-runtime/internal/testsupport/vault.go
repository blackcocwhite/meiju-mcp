// Package testsupport contains deliberately public, synthetic-only test data.
// It is imported only by cmd/offline-harness, never the production executable.
package testsupport

import (
	"crypto/sha256"
	"github.com/blackcocwhite/meiju-mcp/go-runtime/internal/core"
)

type Vault struct{}

func (Vault) BackendID() string { return "synthetic-only-public-test-keys-v1" }
func (Vault) Get(key string) ([]byte, error) {
	value := sha256.Sum256([]byte("PUBLIC SYNTHETIC TEST KEY; NEVER USE WITH REAL ACCOUNTS:" + key))
	return value[:], nil
}
func (Vault) Set(string, []byte) error { return core.Err("synthetic_key_is_fixed") }
func (Vault) Delete(string) error      { return nil }
