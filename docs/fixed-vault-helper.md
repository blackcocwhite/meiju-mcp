# Fixed-identity credential helper

The Go development runtime separates credential-store access from the frequently rebuilt service and App. This prevents ordinary service builds from changing the executable identity that accesses macOS Keychain.

## Identity and boundaries

On macOS the helper is installed at `~/Library/Application Support/MeijuMCP/VaultHelper/MeijuVaultHelper.app`, with identifier `local.meiju.mcp.vault-helper`. The runtime verifies private ownership/modes, symlink restrictions, a pinned binary SHA-256 and the code signature before launching it. It does not search PATH, the current service executable or a profile for an alternative helper.

Only bounded JSON crosses stdin/stdout. Keys are limited to this project's encryption key and App/Codex connection credentials under `meiju-mcp.vault.v1`. Secrets are excluded from argv, environment and diagnostics. Existing items are not overwritten; the helper does not import legacy App credentials or rewrite ACL/partition lists.

For a new macOS item, `SecAccessCreate(..., NULL, ...)` uses the documented calling-application trust behavior. This is an API contract, not a claim that actual ACL contents have been independently audited. The local fixed-binary save/restart path has been verified; arbitrary upgrades and re-signing have not.

The development helper is **ad-hoc signed and pinned as an immutable local binary**. A local digest/identifier does not authenticate a public publisher or defend against malicious code running as the same user. Production signing and controlled helper upgrades remain future work.

## Dialog behavior

Normal service, connector, login-save and restore paths prohibit Keychain interaction UI within the short-lived helper process. If access requires user action, they return `storage_authorization_required` rather than retrying or displaying repeated prompts. No system-wide setting is changed and no keychain is unlocked automatically.

`prepare-helper` silently prepares/reuses the two local client credentials and session encryption key **before** an SMS login. Only the explicit `authorize-helper` operator command allows UI. Explain why authorization is needed, and stop on repeated failures; do not ask the user to keep logging in while storage is unavailable.

| Result | Response |
| --- | --- |
| `storage_helper_unavailable` | Install/check the fixed helper; do not request SMS login. |
| `storage_helper_identity` | Check paths, ownership, digest and signature; do not bypass verification. |
| `storage_authorization_required` | Explain the OS access and use the explicit operator step if authorized. |
| `storage_migration_required` | Preserve the old profile and follow explicit migration instructions. |
| Other `storage_*` | Preserve saved data and diagnose storage independently of cloud token validity. |

## Build and installation

See [installation](installation.md) for the complete fresh macOS sequence. In brief, `build.sh test` compiles the mock backend; `build.sh stage` compiles/signs a candidate without running its credential code. An existing stage is not silently rebuilt. `install.py` defaults to a read-only plan; `--install` uses create-only installation and refuses replacement. `helper-check` validates files/signature without reading credentials.

The macOS helper uses Objective-C and Security.framework; the Go service does not require cgo for Keychain. Windows helper source uses current-user Credential Manager. Linux source uses desktop Secret Service and refuses locked/prompt-required operations rather than invoking unlock/prompt. Windows/Linux installation and native acceptance remain incomplete; no plaintext fallback is available.

## Automated verification

The macOS mock build replaces the credential backend and verifies that native SecItem/SecKeychain/SecAccess calls are absent from the executable. Protocol tests cover missing/read/create/delete, duplicate creation, denial classification and malformed requests. Stateful Go mocks cover first key creation and encrypted restore. The cross-process offline harness uses public deterministic keys only for synthetic data; it is not a security backend.

Use `MEIJU_TEST_NO_NATIVE_VAULT=1` in automation. CI compiles/signs the native candidate but never installs or invokes it for credential operations. Real account/OS acceptance is separate and must preserve existing sessions unless an explicitly scoped migration or restart is requested.
