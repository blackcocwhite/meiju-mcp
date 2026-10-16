//go:build !windows

package core

import (
	"os"
	"syscall"
)

func restrictNew(path string, dir bool) error {
	mode := os.FileMode(0600)
	if dir {
		mode = 0700
	}
	return os.Chmod(path, mode)
}
func checkPrivate(path string, fi os.FileInfo) error {
	st, ok := fi.Sys().(*syscall.Stat_t)
	if !ok || st.Uid != uint32(os.Getuid()) || fi.Mode().Perm()&0077 != 0 || (!fi.IsDir() && st.Nlink != 1) {
		return Err("storage_unsafe")
	}
	return nil
}
