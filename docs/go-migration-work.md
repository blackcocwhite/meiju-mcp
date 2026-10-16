# Go + Swift development architecture

This is an unreleased source preview. The published v0.2.1 assets remain the Python prerelease. Updating source or documentation does not install a service, switch a client's MCP implementation or publish a new version.

## Responsibilities

- `internal/core`: cloud protocol, account/device authority, state mapping, bounded request queue and encrypted profiles.
- `internal/service`: seven-tool MCP contract, local login page, authenticated loopback service and client-only stdio bridge.
- `vault-helper/macos`: independently staged macOS credential helper; normal calls suppress UI and an explicit operator command can enable authorization.
- `internal/vaultworker`: Windows/Linux helper source. Native installation and credential-store acceptance remain incomplete.
- `swift-test`: display model and menu-bar UI. Cloud and credential logic remain in Go; the App starts an `app` bridge with an explicit profile.
- `internal/testsupport` and `cmd/offline-harness`: synthetic cloud/storage only, excluded from production execution paths.
- `contract`: Python-derived schemas and synthetic protocol fixtures.

## Compatibility and migration

The Python implementation remains available. Go preserves the same tool names, strict input/output schemas and uncertainty rules. `idempotentHint: false` is equivalent to the omitted protocol default in the Python snapshot. Auto and legacy client negotiation are tested.

One profile is served by one daemon. App/Codex use separate connection credentials and share the account, not a globally selected device. Device selection belongs to each client. Explicit account logout is shared; closing a connector is not logout. Never replay an uncertain control after reconnecting.

Stable profile identities preserve credential lookup across an explicit, stopped-profile migration. The helper's identity and existing OS entries are unchanged; migration copies ciphertext and authorization metadata without exporting plaintext tokens. See [profile migration](profile-migration.md).

## Development and distribution boundary

Use [installation](installation.md) for a fresh macOS setup and [Go README](../go-runtime/README.md) for developer commands. Use an isolated checkout/output directory whenever a local service or App is already running.

The development helper is ad-hoc signed and immutable once installed. Production signing, helper upgrade/rollback handling, user-facing installation packages and Windows/Linux native acceptance are not complete. Automatic OS-login startup is not enabled by repository scripts. The Swift test App defaults to read-only.

Validation is summarized in [Go validation](go-validation.md). Real login/shared reads/restart restoration have been accepted locally; real Go control remains unverified. Machine-specific paths, process identifiers, account data and rollback records belong outside the public source tree.
