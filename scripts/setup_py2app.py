"""py2app build config for Speako.

Run via build_dmg.sh (which cd's to the repo root first):
    python scripts/setup_py2app.py py2app

Produces dist/Speako.app
"""

import sys

# kokoro-onnx's deep dependency tree (librosa + numba + scipy + sklearn)
# overflows Python 3.12's default recursion limit during modulegraph scan.
sys.setrecursionlimit(20000)

from setuptools import setup

APP = ["src/app.py"]

PLIST = {
    "CFBundleName": "Speako",
    "CFBundleDisplayName": "Speako",
    "CFBundleIdentifier": "com.user.speako",
    "CFBundleVersion": "1.0.0",
    "CFBundleShortVersionString": "1.0.0",
    "LSUIElement": True,
    "NSMicrophoneUsageDescription":
        "Not used, but declared for sounddevice compatibility.",
    "LSMinimumSystemVersion": "11.0",
}

OPTIONS = {
    "argv_emulation": False,
    "plist": PLIST,
    "site_packages": True,
    "semi_standalone": False,
    # Packages that MUST be kept unzipped on disk because they load native
    # libraries from their own package directory via dlopen.
    "packages": [
        "rumps",
        "pynput",
        "sounddevice",       # ships libportaudio.dylib
        "espeakng_loader",   # ships the espeak-ng binary + data
        "onnxruntime",       # ships libonnxruntime.*.dylib
    ],
    "includes": [
        "queue",
        "threading",
        "urllib.request",
        "pyperclip",
        "num2words",
    ],
    "frameworks": [],
    "iconfile": "assets/Speako.icns",
}

setup(
    app=APP,
    name="Speako",
    data_files=[
        ("", [
            "assets/menubar_iconTemplate.png",
            "assets/menubar_iconTemplate@2x.png",
        ]),
    ],
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
