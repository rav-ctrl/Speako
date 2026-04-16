#!/usr/bin/env bash
# build_dmg.sh — build "Speako.app" with py2app, then package as a DMG.
#
# Usage:
#   bash build_dmg.sh
#
# Output:
#   dist/Speako.app
#   dist/Speako-1.0.0.dmg
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="Speako"
VERSION="1.0.0"
DMG_NAME="Speako-${VERSION}.dmg"
BUILD_VENV=".buildenv"
DIST_DIR="dist"
STAGING_DIR="dist/dmg_staging"

echo "==> Locating a compatible Python (3.11 or 3.12)"
# kokoro-onnx needs onnxruntime>=1.20.1, which has no wheels for Python 3.9
# or Python 3.13 on macOS arm64. 3.11 and 3.12 are the sweet spot.
PY_BIN=""
for candidate in python3.12 python3.11 \
    /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 \
    /usr/local/bin/python3.12 /usr/local/bin/python3.11; do
    if command -v "${candidate}" >/dev/null 2>&1; then
        PY_BIN="$(command -v "${candidate}")"
        break
    fi
done

if [ -z "${PY_BIN}" ]; then
    cat <<EOF

ERROR: No Python 3.11 or 3.12 found.

kokoro-onnx requires onnxruntime>=1.20.1, which ships wheels only for
Python 3.10–3.12 on macOS arm64. Your default python3 is too old (3.9).

Install one with Homebrew and re-run:
    brew install python@3.12

Then re-run:
    bash ~/Documents/GitHub/Speako/build_dmg.sh
EOF
    exit 1
fi

PY_VER="$("${PY_BIN}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
echo "    using ${PY_BIN} (Python ${PY_VER})"

echo "==> Creating build venv with ${PY_BIN}"
# If an existing venv was built with the wrong Python, scrap it.
if [ -d "${BUILD_VENV}" ]; then
    EXISTING_VER="$("${BUILD_VENV}/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "")"
    if [ "${EXISTING_VER}" != "${PY_VER}" ]; then
        echo "    existing venv uses Python ${EXISTING_VER:-unknown}; recreating"
        rm -rf "${BUILD_VENV}"
    fi
fi
if [ ! -d "${BUILD_VENV}" ]; then
    "${PY_BIN}" -m venv "${BUILD_VENV}"
fi
# shellcheck source=/dev/null
source "${BUILD_VENV}/bin/activate"

echo "==> Installing build dependencies"
pip install --upgrade pip wheel
# Let kokoro-onnx pull in onnxruntime + numpy at its required versions; don't
# pin numpy ourselves or pip will backtrack through every kokoro-onnx release.
pip install py2app rumps pynput pyperclip sounddevice kokoro-onnx

echo "==> Cleaning prior build output"
rm -rf build "${DIST_DIR}/${APP_NAME}.app" "${DIST_DIR}/${DMG_NAME}" "${STAGING_DIR}"

echo "==> Building .app with py2app (alias=false, standalone)"
python setup_py2app.py py2app

APP_PATH="${DIST_DIR}/${APP_NAME}.app"
if [ ! -d "${APP_PATH}" ]; then
    echo "ERROR: ${APP_PATH} was not produced."
    exit 1
fi

# py2app duplicates single-file modules into both python312.zip AND
# Resources/lib/python3.12/. The zip-internal copy wins on import, which
# breaks sounddevice because it dlopens libportaudio.dylib via __file__,
# and dlopen can't read from inside a zip. Strip the zipped copies so the
# on-disk version (with its sibling _sounddevice_data/) takes over.
echo "==> Stripping sounddevice + portaudio data from python312.zip"
ZIP_PATH="${APP_PATH}/Contents/Resources/lib/python312.zip"
if [ -f "${ZIP_PATH}" ]; then
    (cd "${APP_PATH}/Contents/Resources/lib" && \
        zip -d python312.zip \
            "sounddevice.pyc" \
            "_sounddevice.pyc" \
            "_sounddevice_data/*" 2>/dev/null) || true
fi

# Optional: ad-hoc codesign so Gatekeeper at least records a signature.
# This does NOT notarize; users will still need to right-click -> Open once.
echo "==> Ad-hoc codesigning"
codesign --force --deep --sign - "${APP_PATH}" || true

echo "==> Staging DMG contents"
mkdir -p "${STAGING_DIR}"
cp -R "${APP_PATH}" "${STAGING_DIR}/"
ln -s /Applications "${STAGING_DIR}/Applications"

echo "==> Building DMG with hdiutil"
hdiutil create \
    -volname "${APP_NAME}" \
    -srcfolder "${STAGING_DIR}" \
    -ov -format UDZO \
    "${DIST_DIR}/${DMG_NAME}"

rm -rf "${STAGING_DIR}"

echo ""
echo "Done."
echo "  App: ${APP_PATH}"
echo "  DMG: ${DIST_DIR}/${DMG_NAME}"
echo ""
echo "Install:"
echo "  1. Open ${DIST_DIR}/${DMG_NAME}"
echo "  2. Drag 'Speako' to Applications."
echo "  3. Launch it. macOS will prompt for Accessibility (hotkey + Cmd+C)."
echo "     Grant in System Settings → Privacy & Security → Accessibility."
echo "  4. First launch downloads the voice model (~350 MB) into"
echo "     ~/Library/Application Support/Speako/"
echo ""
echo "Note: the app is ad-hoc signed, not notarized. First launch will"
echo "      require right-click → Open to bypass Gatekeeper."
