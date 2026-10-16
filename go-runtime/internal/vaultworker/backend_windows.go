//go:build windows

package vaultworker

import (
	"errors"
	"github.com/danieljoos/wincred"
	"syscall"
)

type nativeBackend struct{}

func credentialName(key string) string { return "meiju-mcp.vault.v1:" + key }
func (nativeBackend) Get(key string) ([]byte, bool, string) {
	cred, err := wincred.GetGenericCredential(credentialName(key))
	if errors.Is(err, syscall.Errno(1168)) {
		return nil, false, ""
	}
	if err != nil {
		return nil, false, "storage_unavailable"
	}
	return cred.CredentialBlob, true, ""
}
func (b nativeBackend) Create(key string, value []byte) string {
	_, found, code := b.Get(key)
	if code != "" {
		return code
	}
	if found {
		return "storage_item_exists"
	}
	cred := wincred.NewGenericCredential(credentialName(key))
	cred.Persist = wincred.PersistLocalMachine
	cred.CredentialBlob = value
	if cred.Write() != nil {
		return "storage_unavailable"
	}
	return ""
}
func (nativeBackend) Delete(key string) string {
	cred, err := wincred.GetGenericCredential(credentialName(key))
	if errors.Is(err, syscall.Errno(1168)) {
		return ""
	}
	if err != nil || cred.Delete() != nil {
		return "storage_unavailable"
	}
	return ""
}
