#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> Compiling native macOS Swift Menu Bar app..."
swiftc -O "$SCRIPT_DIR/main.swift" -o "$SCRIPT_DIR/LLMGatewayBar"

echo "==> Packaging LLMGatewayBar.app..."
APP_DIR="$SCRIPT_DIR/LLMGatewayBar.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"
cp "$SCRIPT_DIR/LLMGatewayBar" "$MACOS_DIR/LLMGatewayBar"
chmod +x "$MACOS_DIR/LLMGatewayBar"

cat << 'EOF' > "$CONTENTS_DIR/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>LLMGatewayBar</string>
    <key>CFBundleIdentifier</key>
    <string>com.ai-credit-proxy.menubar</string>
    <key>CFBundleName</key>
    <string>AgentBridge Status Bar</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

echo "✓ Build complete!"
echo "  Binary:  $SCRIPT_DIR/LLMGatewayBar"
echo "  App:     $APP_DIR"
