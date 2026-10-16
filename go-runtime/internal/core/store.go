package core

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"github.com/gofrs/flock"
	"os"
	"path/filepath"
	"time"
)

type Vault interface {
	Get(string) ([]byte, error)
	Set(string, []byte) error
	Delete(string) error
}
type SavedSession struct {
	Token    string `json:"token"`
	DeviceID string `json:"device_id"`
}

func (s SavedSession) String() string { return "SavedSession(<redacted>)" }

type record struct {
	Schema     int     `json:"schema"`
	Revision   string  `json:"revision"`
	Ciphertext *string `json:"ciphertext"`
}
type Store struct {
	Dir   string
	Vault Vault
}

func NewStore(dir string, v Vault) *Store {
	if v == nil {
		v = NativeVault{}
	}
	return &Store{Dir: dir, Vault: v}
}
func PrivateDir(dir string) error {
	p, e := filepath.Abs(dir)
	if e != nil {
		return Err("storage_unsafe")
	}
	for a := p; ; a = filepath.Dir(a) {
		fi, err := os.Lstat(a)
		if err == nil && fi.Mode()&os.ModeSymlink != 0 {
			return Err("storage_unsafe")
		}
		if filepath.Dir(a) == a {
			break
		}
	}
	_, prior := os.Lstat(p)
	if e = os.MkdirAll(p, 0700); e != nil {
		return Err("storage_unavailable")
	}
	if os.IsNotExist(prior) {
		if err := restrictNew(p, true); err != nil {
			return Err("storage_unavailable")
		}
	}
	fi, e := os.Stat(p)
	if e != nil || !fi.IsDir() {
		return Err("storage_unsafe")
	}
	return checkPrivate(p, fi)
}
func PrivateRead(path string) ([]byte, error) {
	fi, e := os.Lstat(path)
	if e != nil {
		return nil, e
	}
	if !fi.Mode().IsRegular() || fi.Size() > 65536 {
		return nil, Err("storage_unsafe")
	}
	if e := checkPrivate(path, fi); e != nil {
		return nil, e
	}
	return os.ReadFile(path)
}
func AtomicWrite(path string, b []byte) error {
	if fi, e := os.Lstat(path); e == nil && (!fi.Mode().IsRegular() || checkPrivate(path, fi) != nil) {
		return Err("storage_unsafe")
	}
	f, e := os.CreateTemp(filepath.Dir(path), ".meiju-")
	if e != nil {
		return Err("storage_unavailable")
	}
	name := f.Name()
	defer os.Remove(name)
	if err := restrictNew(name, false); err != nil {
		f.Close()
		return Err("storage_unavailable")
	}
	if _, e = f.Write(b); e == nil {
		e = f.Sync()
	}
	closeErr := f.Close()
	if e != nil || closeErr != nil {
		return Err("storage_unavailable")
	}
	if e = os.Rename(name, path); e != nil {
		return Err("storage_unavailable")
	}
	return nil
}
func (s *Store) locked(fn func() error) error {
	if e := PrivateDir(s.Dir); e != nil {
		return e
	}
	p := filepath.Join(s.Dir, "session.lock")
	if _, e := os.Lstat(p); e == nil {
		if _, e = PrivateRead(p); e != nil {
			return e
		}
	}
	f, e := os.OpenFile(p, os.O_CREATE|os.O_RDWR, 0600)
	if e != nil {
		return Err("storage_unavailable")
	}
	f.Close()
	if err := restrictNew(p, false); err != nil {
		return Err("storage_unavailable")
	}
	lock := flock.New(p)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	ok, e := lock.TryLockContext(ctx, 20*time.Millisecond)
	if e != nil || !ok {
		return Err("storage_unavailable")
	}
	defer lock.Unlock()
	if err := s.ensureProfile(); err != nil {
		return err
	}
	if err := s.checkBackend(); err != nil {
		return err
	}
	return fn()
}
func (s *Store) record() (record, error) {
	b, e := PrivateRead(filepath.Join(s.Dir, "session.json"))
	if os.IsNotExist(e) {
		return record{Schema: 1, Revision: "empty"}, nil
	}
	if e != nil {
		return record{}, e
	}
	var fields Object
	if Decode(b, &fields) != nil || len(fields) != 3 {
		return record{}, Err("storage_corrupt")
	}
	if _, ok := fields["ciphertext"]; !ok {
		return record{}, Err("storage_corrupt")
	}
	var r record
	if Decode(b, &r) != nil || r.Schema != 1 || len(r.Revision) != 32 {
		return r, Err("storage_corrupt")
	}
	return r, nil
}
func (s *Store) Load() (string, *SavedSession, error) {
	var r record
	var session *SavedSession
	e := s.locked(func() error {
		var err error
		r, err = s.record()
		if err != nil || r.Ciphertext == nil {
			return err
		}
		name, err := s.Key("encryption-key")
		if err != nil {
			return err
		}
		key, err := s.Vault.Get(name)
		if err != nil {
			return err
		}
		if len(key) != 32 {
			return Err("storage_key_missing")
		}
		block, _ := aes.NewCipher(key)
		aead, _ := cipher.NewGCM(block)
		b, err := base64.StdEncoding.DecodeString(*r.Ciphertext)
		if err != nil || len(b) < 12 {
			return Err("storage_corrupt")
		}
		plain, err := aead.Open(nil, b[:12], b[12:], []byte("meiju-mcp:1:"+r.Revision))
		if err != nil {
			return Err("storage_corrupt")
		}
		var ss SavedSession
		if Decode(plain, &ss) != nil || !validToken(ss.Token) || len(ss.DeviceID) != 32 {
			return Err("storage_corrupt")
		}
		session = &ss
		return nil
	})
	return r.Revision, session, e
}
func (s *Store) Save(ss SavedSession, expected string) (string, error) {
	if !validToken(ss.Token) || len(ss.DeviceID) != 32 {
		return "", Err("storage_corrupt")
	}
	rev := ID()
	e := s.locked(func() error {
		r, e := s.record()
		if e != nil {
			return e
		}
		if r.Revision != expected {
			return Err("session_changed")
		}
		name, e := s.Key("encryption-key")
		if e != nil {
			return e
		}
		key, e := s.Vault.Get(name)
		if e != nil {
			return e
		}
		if len(key) == 0 {
			if r.Ciphertext != nil {
				return Err("storage_key_missing")
			}
			key = make([]byte, 32)
			if _, e = rand.Read(key); e != nil {
				return e
			}
			if e = s.Vault.Set(name, key); e != nil {
				return e
			}
		}
		if len(key) != 32 {
			return Err("storage_corrupt")
		}
		block, _ := aes.NewCipher(key)
		aead, _ := cipher.NewGCM(block)
		nonce := make([]byte, 12)
		if _, e = rand.Read(nonce); e != nil {
			return e
		}
		plain, _ := JSON(ss)
		blob := aead.Seal(nonce, nonce, plain, []byte("meiju-mcp:1:"+rev))
		encoded := base64.StdEncoding.EncodeToString(blob)
		raw, _ := JSON(record{1, rev, &encoded})
		return AtomicWrite(filepath.Join(s.Dir, "session.json"), raw)
	})
	return rev, e
}
func (s *Store) Forget(expected string) error {
	return s.locked(func() error {
		if expected != "" {
			r, e := s.record()
			if e != nil {
				return e
			}
			if r.Revision != expected {
				return nil
			}
		}
		raw, _ := JSON(record{Schema: 1, Revision: ID()})
		if e := AtomicWrite(filepath.Join(s.Dir, "session.json"), raw); e != nil {
			return e
		}
		name, err := s.Key("encryption-key")
		if err != nil {
			return err
		}
		return s.Vault.Delete(name)
	})
}

// EnsureLockFile creates a private lock inode once; never replaces a locked inode.
func EnsureLockFile(path string) error {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_RDWR, 0600)
	if os.IsExist(err) {
		_, err = PrivateRead(path)
		return err
	}
	if err != nil {
		return Err("storage_unavailable")
	}
	f.Close()
	if err = restrictNew(path, false); err != nil {
		return Err("storage_unavailable")
	}
	return nil
}

func (s *Store) Revision() (string, error) {
	var revision string
	err := s.locked(func() error { r, e := s.record(); revision = r.Revision; return e })
	return revision, err
}

// The helper uses a new service namespace. Never overwrite legacy verifier or
// ciphertext files just because the new helper correctly reports a missing key.
func (s *Store) checkBackend() error {
	backend, ok := s.Vault.(interface{ BackendID() string })
	if !ok {
		return nil
	}
	expected := backend.BackendID()
	path := filepath.Join(s.Dir, "vault-backend.json")
	raw, err := PrivateRead(path)
	if err == nil {
		var marker struct {
			Backend string `json:"backend"`
			Version int    `json:"version"`
		}
		if Decode(raw, &marker) != nil || (marker.Version != 1 && marker.Version != 2) || marker.Backend != expected {
			return Err("storage_migration_required")
		}
		if marker.Version == 2 {
			_, err := s.profileID()
			return err
		}
		return nil
	}
	if !os.IsNotExist(err) {
		return Err("storage_unsafe")
	}
	for _, name := range []string{"session.json", "client-auth.json"} {
		if _, err := os.Lstat(filepath.Join(s.Dir, name)); err == nil {
			return Err("storage_migration_required")
		} else if !os.IsNotExist(err) {
			return Err("storage_unsafe")
		}
	}
	raw, _ = JSON(Object{"backend": expected, "version": 2})
	return AtomicWrite(path, raw)
}
func (s *Store) EnsureBackend() error { return s.locked(func() error { return nil }) }
