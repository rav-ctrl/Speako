#!/usr/bin/env bash
# setup.sh — install deps, fetch Kokoro v1.0 model, install launchd + Hammerspoon config.
set -euo pipefail

BASE_DIR="${HOME}/tts-hotkey"
VENV="${BASE_DIR}/.venv"
MODEL="${BASE_DIR}/kokoro-v1.0.onnx"
VOICES="${BASE_DIR}/voices-v1.0.bin"
PLIST_LABEL="com.user.tts-daemon"
PLIST_PATH="${HOME}/Library/LaunchAgents/${PLIST_LABEL}.plist"
UI_LABEL="com.user.tts-menubar"
UI_PLIST_PATH="${HOME}/Library/LaunchAgents/${UI_LABEL}.plist"
HS_CONFIG="${HOME}/.hammerspoon/init.lua"

MODEL_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
VOICES_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

cd "${BASE_DIR}"

echo "==> Checking Hammerspoon"
if [ ! -d "/Applications/Hammerspoon.app" ] && ! command -v hs >/dev/null 2>&1; then
    cat <<EOF

Hammerspoon is not installed. Install it before continuing:
  brew install --cask hammerspoon
  # or download from https://www.hammerspoon.org

Re-run this script after installing Hammerspoon.
EOF
    exit 1
fi

echo "==> Creating Python venv at ${VENV}"
if [ ! -d "${VENV}" ]; then
    python3 -m venv "${VENV}"
fi
# shellcheck source=/dev/null
source "${VENV}/bin/activate"

echo "==> Installing Python dependencies"
pip install --upgrade pip
pip install kokoro-onnx sounddevice numpy pyperclip rumps

echo "==> Downloading Kokoro v1.0 model files"
if [ ! -f "${MODEL}" ]; then
    curl -L --fail -o "${MODEL}" "${MODEL_URL}"
else
    echo "    ${MODEL} already present, skipping"
fi
if [ ! -f "${VOICES}" ]; then
    curl -L --fail -o "${VOICES}" "${VOICES_URL}"
else
    echo "    ${VOICES} already present, skipping"
fi

echo "==> Installing Hammerspoon config"
mkdir -p "${HOME}/.hammerspoon"
if [ -e "${HS_CONFIG}" ] && [ ! -L "${HS_CONFIG}" ]; then
    cp "${HS_CONFIG}" "${HS_CONFIG}.bak.$(date +%s)"
    echo "    backed up existing ${HS_CONFIG}"
fi
ln -sf "${BASE_DIR}/init.lua" "${HS_CONFIG}"

echo "==> Writing launchd plist to ${PLIST_PATH}"
mkdir -p "${HOME}/Library/LaunchAgents"
cat > "${PLIST_PATH}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV}/bin/python3</string>
        <string>${BASE_DIR}/tts_daemon.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>${BASE_DIR}</string>
    <key>StandardOutPath</key>
    <string>${BASE_DIR}/tts_daemon.out.log</string>
    <key>StandardErrorPath</key>
    <string>${BASE_DIR}/tts_daemon.err.log</string>
</dict>
</plist>
PLIST

echo "==> Writing menu bar launchd plist to ${UI_PLIST_PATH}"
cat > "${UI_PLIST_PATH}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${UI_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV}/bin/python3</string>
        <string>${BASE_DIR}/tts_menubar.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>${BASE_DIR}</string>
    <key>StandardOutPath</key>
    <string>${BASE_DIR}/tts_menubar.out.log</string>
    <key>StandardErrorPath</key>
    <string>${BASE_DIR}/tts_menubar.err.log</string>
</dict>
</plist>
PLIST

echo "==> Loading launchd agents"
launchctl unload "${PLIST_PATH}" 2>/dev/null || true
launchctl load "${PLIST_PATH}"
launchctl unload "${UI_PLIST_PATH}" 2>/dev/null || true
launchctl load "${UI_PLIST_PATH}"

cat <<EOF

Setup complete.

Next steps:
  1. Open Hammerspoon.app and click 'Reload Config' (or it will pick up init.lua on launch).
  2. Grant Hammerspoon Accessibility permission in System Settings → Privacy & Security.
  3. Look for the 🔊 icon in your menu bar.
  4. Select text anywhere and press Cmd+Shift+R (or use the menu).

Logs:
  ${BASE_DIR}/tts_daemon.log  /  tts_daemon.err.log
  ${BASE_DIR}/tts_menubar.err.log
EOF
