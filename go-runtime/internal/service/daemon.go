package service

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"github.com/blackcocwhite/meiju-mcp/go-runtime/internal/core"
	"github.com/gofrs/flock"
	"github.com/modelcontextprotocol/go-sdk/mcp"
	"math/big"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type Endpoint struct {
	URL         string `json:"url"`
	Certificate string `json:"certificate"`
	Instance    string `json:"instance"`
	PID         int    `json:"pid"`
}

func credentialLock(store *core.Store) (func(), error) {
	if err := core.PrivateDir(store.Dir); err != nil {
		return nil, err
	}
	path := filepath.Join(store.Dir, "clients.lock")
	if _, err := os.Lstat(path); err == nil {
		if _, err = core.PrivateRead(path); err != nil {
			return nil, err
		}
	}
	if err := core.EnsureLockFile(path); err != nil {
		return nil, err
	}
	lock := flock.New(path)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	ok, err := lock.TryLockContext(ctx, 20*time.Millisecond)
	if err != nil || !ok {
		return nil, core.Err("storage_unavailable")
	}
	return func() { lock.Unlock() }, nil
}
func Enroll(store *core.Store) error {
	if err := store.EnsureBackend(); err != nil {
		return err
	}
	unlock, err := credentialLock(store)
	if err != nil {
		return err
	}
	defer unlock()
	verifiers := map[string]string{}
	for _, client := range []string{"app", "codex"} {
		key, err := store.Key("client-" + client)
		if err != nil {
			return err
		}
		b, err := store.Vault.Get(key)
		if err != nil {
			return err
		}
		if len(b) == 0 {
			b = make([]byte, 32)
			if _, err = rand.Read(b); err != nil {
				return err
			}
			if err = store.Vault.Set(key, b); err != nil {
				return err
			}
		} else if len(b) != 32 {
			return core.Err("storage_corrupt")
		}
		token := base64.RawURLEncoding.EncodeToString(b)
		sum := sha256.Sum256([]byte(token))
		verifiers[client] = hex.EncodeToString(sum[:])
	}
	raw, _ := json.Marshal(verifiers)
	return core.AtomicWrite(filepath.Join(store.Dir, "client-auth.json"), raw)
}
func Revoke(store *core.Store, client string) error {
	if err := store.EnsureBackend(); err != nil {
		return err
	}
	unlock, err := credentialLock(store)
	if err != nil {
		return err
	}
	defer unlock()
	if client != "app" && client != "codex" {
		return core.Err("invalid_client")
	}
	raw, err := core.PrivateRead(filepath.Join(store.Dir, "client-auth.json"))
	if err != nil {
		return err
	}
	var hashes map[string]string
	if json.Unmarshal(raw, &hashes) != nil {
		return core.Err("storage_corrupt")
	}
	delete(hashes, client)
	raw, _ = json.Marshal(hashes)
	if err = core.AtomicWrite(filepath.Join(store.Dir, "client-auth.json"), raw); err != nil {
		return err
	}
	key, err := store.Key("client-" + client)
	if err != nil {
		return err
	}
	return store.Vault.Delete(key)
}
func certificate() (tls.Certificate, string, error) {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return tls.Certificate{}, "", err
	}
	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		return tls.Certificate{}, "", err
	}
	template := &x509.Certificate{SerialNumber: serial, Subject: pkix.Name{CommonName: "Meiju local service"}, NotBefore: time.Now().Add(-time.Minute), NotAfter: time.Now().Add(365 * 24 * time.Hour), KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}, IPAddresses: []net.IP{net.ParseIP("127.0.0.1")}, BasicConstraintsValid: true}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		return tls.Certificate{}, "", err
	}
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	pk, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return tls.Certificate{}, "", err
	}
	cert, err := tls.X509KeyPair(certPEM, pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: pk}))
	return cert, string(certPEM), err
}
func Serve(ctx context.Context, store *core.Store, engine *core.Engine) error {
	if err := store.EnsureBackend(); err != nil {
		return err
	}
	if err := core.PrivateDir(store.Dir); err != nil {
		return err
	}
	lockPath := filepath.Join(store.Dir, "daemon.lock")
	if _, err := os.Lstat(lockPath); err == nil {
		if _, err = core.PrivateRead(lockPath); err != nil {
			return err
		}
	}
	if err := core.EnsureLockFile(lockPath); err != nil {
		return err
	}
	lock := flock.New(lockPath)
	ok, err := lock.TryLock()
	if err != nil || !ok {
		return core.Err("service_already_running")
	}
	defer lock.Unlock()
	if os.Getenv("MEIJU_LAUNCH_AGENT") == "1" {
		path := filepath.Join(store.Dir, "restart-budget.json")
		var starts []int64
		raw, readErr := core.PrivateRead(path)
		if readErr == nil {
			if json.Unmarshal(raw, &starts) != nil {
				return core.Err("restart_budget_corrupt")
			}
		} else if !os.IsNotExist(readErr) {
			return readErr
		}
		now := time.Now().Unix()
		recent := []int64{}
		for _, v := range starts {
			if now-v < 600 {
				recent = append(recent, v)
			}
		}
		if len(recent) >= 3 {
			return core.Err("restart_budget_exhausted")
		}
		recent = append(recent, now)
		raw, _ = json.Marshal(recent)
		if err := core.AtomicWrite(path, raw); err != nil {
			return err
		}
	}
	if _, err := core.PrivateRead(filepath.Join(store.Dir, "client-auth.json")); err != nil {
		return core.Err("client_not_enrolled")
	}
	cert, pemText, err := certificate()
	if err != nil {
		return err
	}
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		return err
	}
	defer listener.Close()
	endpoint := Endpoint{URL: "https://" + listener.Addr().String() + "/mcp", Certificate: pemText, Instance: core.ID(), PID: os.Getpid()}
	portal := NewPortal(engine)
	defer portal.Close()
	server, err := NewMCP(LocalCaller(engine, portal))
	if err != nil {
		return err
	}
	handler := mcp.NewStreamableHTTPHandler(func(*http.Request) *mcp.Server { return server }, &mcp.StreamableHTTPOptions{Stateless: true, JSONResponse: true})
	wrapped := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Host != listener.Addr().String() {
			http.Error(w, "forbidden", 403)
			return
		}
		if len(r.Header.Values("Origin")) != 0 {
			http.Error(w, "forbidden", 403)
			return
		}
		if r.URL.Path != "/mcp" {
			http.NotFound(w, r)
			return
		}
		headers := r.Header.Values("Authorization")
		client := r.Header.Get("X-Meiju-Client")
		var verifiers map[string]string
		raw, authErr := core.PrivateRead(filepath.Join(store.Dir, "client-auth.json"))
		if authErr != nil || json.Unmarshal(raw, &verifiers) != nil {
			http.Error(w, "unauthorized", 401)
			return
		}
		expected, found := verifiers[client]
		supplied := ""
		if len(headers) == 1 && strings.HasPrefix(headers[0], "Bearer ") {
			sum := sha256.Sum256([]byte(strings.TrimPrefix(headers[0], "Bearer ")))
			supplied = hex.EncodeToString(sum[:])
		}
		if !found || len(headers) != 1 || subtle.ConstantTimeCompare([]byte(supplied), []byte(expected)) != 1 {
			http.Error(w, "unauthorized", 401)
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, 65536)
		handler.ServeHTTP(w, r)
	})
	httpServer := &http.Server{Handler: wrapped, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 100 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16384}
	raw, _ := json.Marshal(endpoint)
	path := filepath.Join(store.Dir, "endpoint.json")
	if err = core.AtomicWrite(path, raw); err != nil {
		return err
	}
	defer os.Remove(path)
	done := make(chan error, 1)
	go func() {
		done <- httpServer.Serve(tls.NewListener(listener, &tls.Config{Certificates: []tls.Certificate{cert}, MinVersion: tls.VersionTLS12}))
	}()
	select {
	case err = <-done:
		if !errors.Is(err, http.ErrServerClosed) {
			return err
		}
	case <-ctx.Done():
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = httpServer.Shutdown(shutdown)
	}
	return nil
}

type authorizedTransport struct {
	base          http.RoundTripper
	token, client string
}

func (t authorizedTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	copy := r.Clone(r.Context())
	copy.Header = r.Header.Clone()
	copy.Header.Set("Authorization", "Bearer "+t.token)
	copy.Header.Set("X-Meiju-Client", t.client)
	return t.base.RoundTrip(copy)
}
func Connect(ctx context.Context, store *core.Store, client string) (*mcp.ClientSession, error) {
	if err := store.EnsureBackend(); err != nil {
		return nil, err
	}
	if client != "app" && client != "codex" {
		return nil, core.Err("invalid_client")
	}
	if err := core.PrivateDir(store.Dir); err != nil {
		return nil, err
	}
	raw, err := core.PrivateRead(filepath.Join(store.Dir, "endpoint.json"))
	if err != nil {
		return nil, core.Err("service_unavailable")
	}
	var endpoint Endpoint
	if json.Unmarshal(raw, &endpoint) != nil {
		return nil, core.Err("service_unavailable")
	}
	u, err := url.Parse(endpoint.URL)
	if err != nil || u.Scheme != "https" || u.Hostname() != "127.0.0.1" || u.Path != "/mcp" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return nil, core.Err("invalid_endpoint")
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM([]byte(endpoint.Certificate)) {
		return nil, core.Err("invalid_endpoint")
	}
	name, err := store.Key("client-" + client)
	if err != nil {
		return nil, err
	}
	key, err := store.Vault.Get(name)
	if err != nil {
		return nil, err
	}
	if len(key) == 0 {
		return nil, core.Err("client_not_enrolled")
	}
	if len(key) != 32 {
		return nil, core.Err("storage_corrupt")
	}
	transport := &http.Transport{Proxy: nil, TLSClientConfig: &tls.Config{RootCAs: roots, MinVersion: tls.VersionTLS12}, DisableCompression: true}
	httpClient := &http.Client{Transport: authorizedTransport{transport, base64.RawURLEncoding.EncodeToString(key), client}, Timeout: 95 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	return mcp.NewClient(&mcp.Implementation{Name: "meiju-" + client, Version: BuildVersion}, nil).Connect(ctx, &mcp.StreamableClientTransport{Endpoint: endpoint.URL, HTTPClient: httpClient}, nil)
}
func Bridge(ctx context.Context, store *core.Store, client string) error {
	// Answer discovery immediately. Keychain unlock/remote startup must not delay
	// the stdio initialize handshake and trigger the host's fallback twice.
	var mu sync.Mutex
	var remote *mcp.ClientSession
	server, err := NewMCP(func(c context.Context, name string, args core.Object) (*mcp.CallToolResult, error) {
		mu.Lock()
		defer mu.Unlock()
		if remote == nil {
			var err error
			remote, err = Connect(c, store, client)
			if err != nil {
				return Result(nil, err), nil
			}
		}
		result, err := remote.CallTool(c, &mcp.CallToolParams{Name: name, Arguments: args})
		if err != nil {
			remote.Close()
			remote = nil
			failure := core.Err("service_unavailable")
			if name == "meiju_control" {
				failure.Code = "write_uncertain"
				failure.Uncertain = true
			}
			return Result(nil, failure), nil
		}
		return result, nil
	})
	if err != nil {
		return err
	}
	err = server.Run(ctx, &mcp.StdioTransport{})
	mu.Lock()
	defer mu.Unlock()
	if remote != nil {
		remote.Close()
	}
	return err
}
func LaunchAgent(executable, dir, label string) (string, error) {
	if !filepath.IsAbs(executable) || !filepath.IsAbs(dir) || strings.ContainsAny(executable+dir+label, "<>&\"\n\r") {
		return "", core.Err("invalid_input")
	}
	return `<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>Label</key><string>` + label + `</string><key>ProgramArguments</key><array><string>` + executable + `</string><string>serve</string><string>--session-dir</string><string>` + dir + `</string></array><key>EnvironmentVariables</key><dict><key>MEIJU_LAUNCH_AGENT</key><string>1</string></dict><key>RunAtLoad</key><true/><key>KeepAlive</key><dict><key>Crashed</key><true/></dict><key>ThrottleInterval</key><integer>30</integer><key>ProcessType</key><string>Background</string></dict></plist>`, nil
}
