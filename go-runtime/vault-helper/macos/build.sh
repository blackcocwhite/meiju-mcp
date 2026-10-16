#!/bin/bash
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
stage="$root/../.cache/vault-helper-stage"
mode="${1:-stage}"
mkdir -p "$stage"
chmod 700 "$stage"
if [[ "$mode" == test ]]; then
  clang -fobjc-arc -fblocks -mmacosx-version-min=14.0 -DMEIJU_VAULT_MOCK=1 -Wno-deprecated-declarations "$root/vault-helper/macos/main.m" -framework Foundation -framework Security -o "$stage/mock-helper"
  # Prove this test executable has no native credential access functions.
  if nm -u "$stage/mock-helper" | grep -Eq '_Sec(Item|Keychain|Access)'; then echo 'Mock backend unexpectedly links native credential calls' >&2; exit 1; fi
  "$stage/mock-helper" --self-test
  exit 0
fi
[[ "$mode" == stage ]] || { echo 'Usage: build.sh [stage|test]' >&2; exit 2; }
app="$stage/MeijuVaultHelper.app"
if [[ -e "$stage/installation.json" || -e "$app" ]]; then
  echo 'Helper stage already exists; refusing an implicit rebuild or identity change.' >&2
  exit 1
fi
mkdir -p "$app/Contents/MacOS"
clang -fobjc-arc -fblocks -mmacosx-version-min=14.0 -Os -Wno-deprecated-declarations "$root/vault-helper/macos/main.m" -framework Foundation -framework Security -o "$app/Contents/MacOS/MeijuVaultHelper"
chmod 700 "$app/Contents/MacOS/MeijuVaultHelper"
python3 - "$app" <<'PY'
import pathlib,plistlib,sys
p=pathlib.Path(sys.argv[1]);(p/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'local.meiju.mcp.vault-helper','CFBundleName':'美居登录存储助手','CFBundleExecutable':'MeijuVaultHelper','CFBundlePackageType':'APPL','CFBundleVersion':'1','LSUIElement':True,'LSMinimumSystemVersion':'14.0'}))
PY
# Ad-hoc stage only: no signing identity/keychain lookup, installation or execution.
codesign --force --sign - --identifier local.meiju.mcp.vault-helper --options runtime "$app"
codesign --verify --strict -R '=identifier "local.meiju.mcp.vault-helper"' "$app"
python3 - "$stage" <<'PY'
import pathlib,sys,hashlib,json
p=pathlib.Path(sys.argv[1]);binary=p/'MeijuVaultHelper.app/Contents/MacOS/MeijuVaultHelper'
manifest={'protocol':1,'identifier':'local.meiju.mcp.vault-helper','backend':'meiju-vault-v1','sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'signing':'ad-hoc-pinned-immutable'}
(p/'installation.json').write_text(json.dumps(manifest,indent=2));(p/'installation.json').chmod(0o600)
print(json.dumps({'staged':str(p),'sha256':manifest['sha256'],'keychain_access_performed':False}))
PY
