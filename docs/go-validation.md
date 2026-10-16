# Go / Swift validation scope

Status: unreleased development source. This summary separates mocked checks, real credential storage, native client integration and physical appliance response. It contains no personal paths, process IDs, account identifiers or raw cloud responses.

## Recorded local acceptance

| Area | Evidence and limits |
| --- | --- |
| Tool compatibility | All seven input/output schemas compared with Python; annotations compared using protocol defaults. Auto and explicit legacy negotiation exercised. |
| Go offline tests | 37 test functions passed with the race detector before the documentation/CI update; `go vet` passed. Re-run results belong to the current CI/check output. |
| macOS helper mock | 17 protocol checks passed; test binary checked for absence of native Keychain access functions. |
| Synthetic shared service | App/Codex identities and actual Swift connector read synthetic state; browser remember/login/logout paths and strict input rejection tested against a fake cloud. Synthetic controls do not count as hardware tests. |
| Synthetic profile migration | Encrypted payload and identity survived a real directory change and service-process restart. Busy source, existing target, damaged identity and incomplete-copy refusal covered by unit tests. |
| Real Go login and reads | User entered credentials in a same-computer browser. App and Agent read the same account's AC state and candidate capabilities. |
| Real persistence and restart | Service reported `saved`; private encrypted file existed. After restart, `restored` was followed by fresh device reads that validated cloud authorization. No SMS re-login was needed. |
| Real profile relocation | Old source path removed from active deployment; relocated service restarted and both clients read successfully. Helper binary/identity remained unchanged. |
| Native Codex + Skill | An independent native client automatically read the Skill and invoked login status, device list, state and capabilities. No real control or logout was invoked. |
| Windows/Linux | Service/helper cross-compilation only; not native credential-store, installer or hardware acceptance. |

Earlier storage failures were not counted as success: a memory-only login did not prove persistence, and a browser success message did not override a service-side save error. The fixed-helper and restart checks were performed after correcting those issues.

## What is not established

- Go physical power, temperature, mode or fan response is not yet accepted. Historical Python on/off evidence on `KFR-35G/N8HE1ⅡPro` is recorded separately in [Python validation](validation.md).
- A successful Swift build/probe is not exhaustive mouse, keyboard or accessibility testing.
- A fixed local ad-hoc helper working without UI does not prove unattended access after arbitrary re-signing/upgrades, lock states or on another OS. No claim is made that actual Keychain ACL contents were audited.
- One device's success does not establish support for all Midea models. Capabilities remain experimental; cloud freshness and physical execution are not inferred from ACK/readback.

## Reproduce safe checks

[CI](../.github/workflows/ci.yml) runs Python offline tests, Go tests/race/vet, cross-builds, native helper compilation/signature checks without installation, mock helper protocol checks, Swift compilation and the synthetic shared/migration/restart flow.

Set `MEIJU_TEST_NO_NATIVE_VAULT=1` for Go automated testing. Synthetic harness profiles use public deterministic test keys and are never suitable for real accounts. Native Codex acceptance requires a separately configured client and is not part of unattended CI. Do not use CI success as proof of a real account or physical control.

Private runtime files, credentials, raw client events and local rollback data must not be submitted. Public compatibility reports should give platform, model, operation and sanitized outcome; omit device IDs, serial numbers, phone numbers and tokens.
