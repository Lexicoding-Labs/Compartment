#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
clt=/Library/Developer/CommandLineTools
if [[ "$(xcode-select -p)" == "$clt" && "$(xcrun --sdk macosx --show-sdk-version)" == 27.* && -d "$clt/SDKs/MacOSX26.5.sdk" ]]; then
    fw="$clt/Library/Developer/Frameworks"
    export DYLD_FRAMEWORK_PATH="$fw"
    swift test --disable-xctest --build-system native --sdk "$clt/SDKs/MacOSX26.5.sdk" \
        -Xswiftc -F -Xswiftc "$fw" -Xswiftc -plugin-path -Xswiftc "$clt/usr/lib/swift/host/plugins/testing" \
        -Xlinker -F -Xlinker "$fw" -Xlinker -rpath -Xlinker "$fw" "$@"
else
    swift test "$@"
fi
