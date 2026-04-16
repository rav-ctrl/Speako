#!/usr/bin/env bash
# build_dmg.sh — build "Speako.app" with py2app, then package as a DMG.
#
# Usage (from repo root):
#   bash scripts/build_dmg.sh
#
# Output:
#   dist/Speako.app
#   dist/Speako-1.0.0.dmg
set -euo pipefail

# Always work from the repo root regardless of where the script is invoked.
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

APP_NAME="Speako"
VERSION="1.0.0"
DMG_NAME="Speako-${VERSION}.dmg"
BUILD_VENV=".buildenv"
DIST_DIR="dist"
STAGING_DIR="dist/dmg_staging"

echo "==> Locating a compatible Python (3.11 or 3.12)"
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
Python 3.10–3.12 on macOS arm64.

Install with Homebrew:
    brew install python@3.12

Then re-run:
    bash scripts/build_dmg.sh
EOF
    exit 1
fi

PY_VER="$("${PY_BIN}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
echo "    using ${PY_BIN} (Python ${PY_VER})"

echo "==> Creating build venv with ${PY_BIN}"
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
pip install py2app rumps pynput pyperclip sounddevice kokoro-onnx

echo "==> Cleaning prior build output"
rm -rf build "${DIST_DIR}/${APP_NAME}.app" "${DIST_DIR}/${DMG_NAME}" "${STAGING_DIR}"

echo "==> Building .app with py2app"
python scripts/setup_py2app.py py2app

APP_PATH="${DIST_DIR}/${APP_NAME}.app"
if [ ! -d "${APP_PATH}" ]; then
    echo "ERROR: ${APP_PATH} was not produced."
    exit 1
fi

# py2app zips sounddevice into python312.zip, but its bundled libportaudio.dylib
# can't be loaded from inside a zip. Strip the zipped copies so the on-disk
# version takes over.
echo "==> Stripping sounddevice from python312.zip (portaudio dlopen fix)"
ZIP_PATH="${APP_PATH}/Contents/Resources/lib/python312.zip"
if [ -f "${ZIP_PATH}" ]; then
    (cd "${APP_PATH}/Contents/Resources/lib" && \
        zip -d python312.zip \
            "sounddevice.pyc" \
            "_sounddevice.pyc" \
            "_sounddevice_data/*" 2>/dev/null) || true
fi

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
