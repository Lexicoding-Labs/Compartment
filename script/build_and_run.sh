#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mode=${1:-run}
config=${CONFIGURATION:-release}
app=dist/Compartment.app
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
opts=()
# Standalone CLT 27 lacks SwiftUIMacros. Use its bundled 26.5 SDK for the Mac 14 target.
clt=/Library/Developer/CommandLineTools
if [[ "$(xcode-select -p)" == "$clt" && "$(xcrun --sdk macosx --show-sdk-version)" == 27.* && -d "$clt/SDKs/MacOSX26.5.sdk" ]]; then
    opts=(--build-system native --sdk "$clt/SDKs/MacOSX26.5.sdk")
fi
swift build "${opts[@]}" -c "$config" --product Compartment
bin=$(swift build "${opts[@]}" -c "$config" --show-bin-path)
if [[ "$mode" != "--package" ]]; then
    pkill -f -x "$PWD/$app/Contents/MacOS/Compartment" || true
fi
install -m 755 "$bin/Compartment" "$app/Contents/MacOS/Compartment"
cp MacSupport/Info.plist "$app/Contents/Info.plist"
cp MacSupport/PrivacyInfo.xcprivacy MacSupport/Compartment.icns "$app/Contents/Resources/"
codesign --force --sign "${COMPARTMENT_SIGN_IDENTITY:--}" --options runtime --entitlements MacSupport/Compartment.entitlements "$app"
codesign --verify --strict "$app"
case "$mode" in
    --package) ;;
    --debug) lldb "$app/Contents/MacOS/Compartment" ;;
    run|--verify|--logs|--telemetry)
        open -n "$app"
        if [[ "$mode" == "--verify" ]]; then sleep 2; pgrep -f -x "$PWD/$app/Contents/MacOS/Compartment"; fi
        if [[ "$mode" == "--logs" || "$mode" == "--telemetry" ]]; then /usr/bin/log stream --style compact --predicate 'process == "Compartment"'; fi ;;
    *) echo "Use run, --package, --debug, --verify, --logs or --telemetry" >&2; exit 2 ;;
esac
