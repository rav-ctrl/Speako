"""py2app build config for Speako.

Build with:
    python3 setup_py2app.py py2app

Produces dist/Speako.app
"""

import sys

# py2app's modulegraph recursively walks the entire import tree of every
# package listed in `packages`. kokoro-onnx pulls in librosa + numba + scipy +
# sklearn, which overflows Python 3.12's default recursion limit.
sys.setrecursionlimit(20000)

from setuptools import setup

APP = ["app.py"]

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
    # Keep site-packages as real directories on disk, not zipped into
    # python312.zip. Required because sounddevice / espeakng_loader /
    # onnxruntime dlopen native libraries via __file__-relative paths that
    # don't work inside a zip archive.
    "site_packages": True,
    "semi_standalone": False,
    # Only list packages that need their *data files* bundled (rumps, pynput
    # for PyObjC stubs). Don't list the heavyweights (kokoro_onnx,
    # onnxruntime, numpy) — modulegraph walks them recursively and blows up.
    # py2app will still pick up their compiled modules via normal import
    # scanning from app.py.
    # Packages that MUST be kept unzipped on disk because they load native
    # libraries from their own package directory via dlopen (those dylibs
    # cannot be read from inside python312.zip).
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
    ],
    "frameworks": [],
    "iconfile": None,
}

setup(
    app=APP,
    name="Speako",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
