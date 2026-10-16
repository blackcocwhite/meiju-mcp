# Go shared service and independent Swift test app

**Unreleased development implementation.** No public tag, Release, Python package upgrade, global MCP configuration switch, or original App replacement is performed by these scripts. The existing Python sources remain the compatibility reference.

## What is implemented

- The same seven MCP tools, strict input schemas, output schemas and control rules.
- Native Go stdio mode, one shared loopback TLS service, and client-only stdio connectors for App/Codex.
- One account per service/profile, opaque device IDs, serialized cloud operations, at most 16 waiting operations, five-second queue wait limit, and bounded request times. No automatic retry of uncertain writes.
- Human-operated local login page, explicit opt-in encrypted persistence, shared logout, and safe errors.
- Independent fixed credential helpers for macOS Keychain, Windows Credential Manager and Linux Secret Service. No file-password or plaintext fallback. Windows/Linux installer and native credential-store acceptance remain pending.
- Independent Swift menu-bar test app. Its `ACCore` target contains display DTOs/enums only, not the original cloud client. All operations go through MCP.

The Go SDK serializes `idempotentHint: false` where Python omits that field. The protocol default is also false. Compatibility tests compare this default semantically; all input/output schemas remain equal. Automatic Python SDK negotiation currently falls back to the legacy initialize handshake supported by the pinned Go SDK; both client modes are tested.

## Build

Use Go 1.25 or later; the independent macOS credential helper also needs the Apple C toolchain. Swift test app needs Swift 6 and macOS 14+. These are build-time tools: the resulting App and service do **not** need Python or Go installed on the end user's computer.

From this directory:

```sh
go mod download
go test -race ./...
go vet ./...
go build -trimpath -ldflags='-s -w' -o ./build/meiju-mcp ./cmd/meiju-mcp
```

`scripts/go.sh` uses `MEIJU_GO_BINARY` if specified, then the project-local verified toolchain cache, otherwise `go` from PATH. The dependency graph is pinned in `go.mod` / `go.sum`.

Normal service/App builds do not rebuild or install the fixed helper. Read [helper setup, authorization and migration](../docs/fixed-vault-helper.md) before using native storage.

Profiles now have a private, stable `profile.json` identity. Fresh profiles use a random ID; explicit migration preserves the existing credential namespace and ciphertext. Legacy profiles remain path-bound until migrated. See [profile migration and current local startup paths](../docs/profile-migration.md). Never copy a live profile or run its rollback copy as a second writer.

## Runtime modes

`meiju-mcp` without a subcommand is the compatible standalone stdio service. `--session-only` disables reading/writing saved login. This mode is for users who do not use the shared service; it is not a fallback for an unavailable daemon.

After installing and explicitly preparing the fixed helper, shared deployment uses one new private absolute directory. Old profiles are rejected for implicit migration:

```sh
meiju-mcp prepare-helper --session-dir /absolute/private/profile
meiju-mcp serve --session-dir /absolute/private/profile
meiju-mcp bridge --client codex --session-dir /absolute/private/profile
```

`enroll` creates/reuses two independent client credentials (`app`, `codex`) in the OS vault. It does not log in to Meiju. Normal commands suppress credential dialogs; only explicit `authorize-helper` enables authorization UI and also prepares the session encryption key before human login. The bridge is configured as the MCP command and only forwards validated tool calls. It answers discovery before accessing the vault or daemon, preventing startup authorization delays from breaking the MCP handshake. After a connection failure, it reconnects only for a subsequent new request, never replaying the failed request.

The Swift test app uses the same Go connector with `--client app`. Sharing that small connector avoids a second implementation of TLS/credential handling in Swift. There is still only one cloud-account service. Each connector has process overhead; measure it rather than assuming it is free.

Revoke only one client, without logging out the shared Meiju account:

```sh
meiju-mcp revoke --client codex --session-dir /absolute/private/profile
```

A private verifier file lets the daemon enforce revocation on the next request, including existing client sessions. An already-sent cloud action cannot be recalled. `enroll` is an explicit operation that authorizes both clients again.

Explicitly forget the account saved in this profile:

```sh
meiju-mcp --session-dir /absolute/private/profile --forget-saved-login
```

Running services observe the saved-session revision before subsequent cloud requests. Client disconnection or application exit never implies account logout.

## Isolation and security

Default Go storage is deliberately **different from the Python default** (`meiju-mcp-go`). During migration use explicit test directories. No process-memory extraction or legacy App credential import exists. The Python AES-GCM file format is tested with a synthetic ciphertext fixture, but production key namespaces differ; this is not an automatic migration of old saved credentials. An existing ciphertext with a missing key is preserved instead of overwritten during a new save.

Session payload: token and client device ID only. AES-256-GCM, fresh random nonce, authenticated format/revision, OS-vault encryption key, process/file locks and atomic replacement. Local access tokens are separate from the Meiju token. Their SHA-256 verifiers, not bearer tokens, are stored in the private client registry. Vault access runs in a bounded helper process; no secrets enter argv, environment or diagnostics. On macOS, only the native item-not-found status means absence: dark wake, locked-store and authorization errors are reported as unavailable, never converted into a new credential enrollment.

The HTTP service binds only `127.0.0.1`, requires client authentication, rejects browser Origin headers, checks Host, and limits headers/body sizes. An ephemeral server certificate is pinned through the owner-only endpoint descriptor; no global certificate trust settings are changed. The browser login listener is a separate loopback-only endpoint with its own short-lived flow secret, strict Origin checks and no-store headers.

macOS/POSIX paths check owner, permissions and links; Windows uses current-user ACLs. These measures do not protect against malicious code running as the same user or an administrator. All compatible clients in one profile share the same account permissions.

## LaunchAgent staging

```sh
meiju-mcp service-plist --session-dir /absolute/private/profile > test-service.plist
```

This only generates a plist; it does not install it or edit client settings. The label is `local.meiju.mcp.go.test`, deliberately not the original App's identifier. It runs as the current user, restarts crashes with launchd throttling, and refuses more than three managed starts in ten minutes. Startup errors exit normally rather than repeatedly prompting for vault access. The restart budget is private profile metadata and expires with time.

When explicitly testing activation, bootstrap the staged plist in the user's GUI domain. Bootout that exact test label to stop it. Do not register or overwrite a production LaunchAgent during migration. Reboot/start-at-login installation and signed public distribution are outside this development acceptance.

## Swift test build

From the repository root, choose an isolated profile:

```sh
MEIJU_TEST_SESSION_DIR=/absolute/private/profile go-runtime/scripts/build-swift-test.sh
```

Produces `.cache/go-build/美居空调-Go测试.app`, with bundle ID `local.meiju.mcp.go.independent-test`. It refuses to overwrite its own running test bundle. It never overwrites `../artifacts/美居空调.app`. The App is locally ad-hoc signed, not notarized or published.

`connection.json` contains only the Go executable path, profile directory and `readOnly` switch; no credentials. The test build defaults to read-only. Setting `readOnly: false` enables the existing button-to-MCP path; do this only for an explicitly authorized control test. UI selection is local to the App, never a shared daemon-global selected device.

`--probe` exercises login status and, if authenticated, device/status/capability reads through the actual connector. `--probe --render /absolute/output.png` additionally renders the panel. Use synthetic data for saved screenshots. `--connection /absolute/connection.json` selects an isolated test configuration without changing the bundled default.

## Reproducible offline acceptance

Build `cmd/offline-harness` separately; it is not the production service and must not be shipped as one. It uses a synthetic HTTP cloud and synthetic account only. It uses only synthetic storage, never the native credential helper, and tests process restarts without SMS or device actions. Its publicly derived keys must never protect real accounts.

The Python development environment is used only for compatibility testing. The complete mock-only shared/restart script is `go-runtime/scripts/fixed_helper_acceptance.py` (requires the candidate harness and Swift App); set `CODEX_TEST_BINARY` to include an ephemeral native Codex/Skill check. It stops only the synthetic children it creates.

For the protocol compatibility step:

```sh
.venv-persistence/bin/python go-runtime/scripts/compatibility.py
```

Run from repository root while `.cache/fixed-helper-candidate/offline-harness` owns `.cache/go-synthetic-profile`. Set `MEIJU_TEST_NO_NATIVE_VAULT=1` throughout the test run. The script verifies the owner executable before sending synthetic controls. It compares the seven tool schemas/annotations, exercises auto and legacy negotiation, rejects malformed controls, and verifies local browser login/persistence. It never targets a production cloud endpoint.

`contract/tools.json` is a checked-in snapshot. `scripts/export_contract.py` regenerates it from the Python reference without starting a server. Review snapshot changes before accepting them. Other fixtures contain explicitly synthetic signing/profile/encryption data.

See `../docs/go-validation.md` for actual results and remaining limits. Cross-compilation is not Windows/Linux runtime validation. Synthetic cloud acceptance is not proof of real Meiju login or hardware compatibility.
