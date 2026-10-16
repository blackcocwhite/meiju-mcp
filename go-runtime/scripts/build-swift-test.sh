#!/bin/bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
: "${MEIJU_TEST_SESSION_DIR:?Set an isolated absolute test session directory}"
output_dir="${MEIJU_TEST_OUTPUT_DIR:-$root/../.cache/go-build}"
bin="${MEIJU_TEST_CONNECTOR:-$output_dir/meiju-mcp-go}"
output="$output_dir/美居空调-Go测试.app"
# Never replace even the test bundle while it is running.
processes="$(/bin/ps -axo comm=)" || { echo 'Cannot verify running app paths; refusing to overwrite a bundle.' >&2; exit 1; }
if /usr/bin/grep -Fxq "$output/Contents/MacOS/MeijuMCPTest" <<< "$processes"; then echo 'Test app is running; close only that test app before rebuilding.' >&2; exit 1; fi
mkdir -p "$output_dir" "$root/../.cache/swift-test-cache" "$root/../.cache/swift-test-config" "$root/../.cache/swift-test-security"
if [[ -z "${MEIJU_TEST_CONNECTOR:-}" ]]; then "$root/scripts/go.sh" build -trimpath -ldflags='-s -w' -o "$bin" ./cmd/meiju-mcp; fi
swift build --package-path "$root/swift-test" --scratch-path "$root/../.cache/swift-test-build" --cache-path "$root/../.cache/swift-test-cache" --config-path "$root/../.cache/swift-test-config" --security-path "$root/../.cache/swift-test-security" --disable-netrc --disable-keychain -c release
mkdir -p "$output/Contents/MacOS" "$output/Contents/Resources"
binary_dir="$(swift build --package-path "$root/swift-test" --scratch-path "$root/../.cache/swift-test-build" -c release --show-bin-path)"
cp "$binary_dir/MeijuMCPTest" "$output/Contents/MacOS/MeijuMCPTest"
python3 - "$output" "$bin" "$MEIJU_TEST_SESSION_DIR" <<'PY'
import sys,pathlib,plistlib,json
app=pathlib.Path(sys.argv[1])
(app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'local.meiju.mcp.go.independent-test','CFBundleName':'美居空调-Go测试','CFBundleExecutable':'MeijuMCPTest','CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.0.0','CFBundleVersion':'1','LSMinimumSystemVersion':'14.0','LSUIElement':True}))
(app/'Contents/Resources/connection.json').write_text(json.dumps({'executable':sys.argv[2],'sessionDirectory':sys.argv[3],'readOnly':True},ensure_ascii=False))
PY
codesign --force --sign - "$output"
codesign --verify --strict "$output"
echo "$output"
