//go:build !windows && !linux

package vaultworker

type nativeBackend struct{}

func (nativeBackend) Get(string) ([]byte, bool, string) {
	return nil, false, "storage_helper_unavailable"
}
func (nativeBackend) Create(string, []byte) string { return "storage_helper_unavailable" }
func (nativeBackend) Delete(string) string         { return "storage_helper_unavailable" }
