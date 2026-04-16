# Speako

A lightweight macOS menu bar app that reads any copied text aloud using high-quality local TTS. Powered by [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx) — everything runs on-device, no API keys, no internet required after initial setup.

## Features

- **Instant playback** — sentence-level chunked synthesis means speech starts in under a second, even for long text
- **Global hotkey** — press `⌃⌥⌘\` (Ctrl+Option+Cmd+Backslash) from any app
- **Menu bar controls** — pick from 11 voices, adjust speed (0.75x–1.5x), stop mid-speech
- **Fully local** — no cloud APIs, no data leaves your machine
- **Lightweight** — sits in the menu bar with no Dock icon

## Installation

### Option A: Download the DMG (easiest)

1. Go to [Releases](../../releases) and download the latest `Speako-x.x.x.dmg`
2. Open the DMG and drag **Speako** to **Applications**
3. Right-click the app → **Open** (required once for unsigned apps)
4. Grant **Accessibility** permission when prompted (System Settings → Privacy & Security → Accessibility)
5. First launch downloads the Kokoro voice model (~350 MB) — this is a one-time download

### Option B: Build from source

**Requirements:**
- macOS 11+
- Python 3.11 or 3.12 (`brew install python@3.12`)
- ~1 GB disk space for the build environment

```bash
git clone https://github.com/your-username/Speako.git
cd Speako
bash scripts/build_dmg.sh
```

This creates:
- `dist/Speako.app` — the standalone app
- `dist/Speako-1.0.0.dmg` — the installer DMG

Then drag `Speako.app` to `/Applications` and launch.

## Usage

1. **Copy text** with `⌘C` in any app
2. **Press `⌃⌥⌘\`** (Ctrl + Option + Cmd + Backslash)
3. Speako reads the clipboard aloud

Or click the microphone icon in the menu bar → **Speak selection**.

### Menu bar options

| Action | Description |
|--------|-------------|
| **Speak selection** | Read whatever is on the clipboard |
| **Stop** | Stop playback immediately (⌘.) |
| **Voice** | Choose from 11 Kokoro voices |
| **Speed** | Adjust playback speed (0.75x, 1.0x, 1.25x, 1.5x) |
| **Open log** | View the app log for debugging |

### Available voices

| Voice ID | Description |
|----------|-------------|
| `af_sarah` | American Female (default) |
| `af_heart` | American Female |
| `af_bella` | American Female |
| `af_nicole` | American Female |
| `af_sky` | American Female |
| `am_adam` | American Male |
| `am_michael` | American Male |
| `bf_emma` | British Female |
| `bf_isabella` | British Female |
| `bm_george` | British Male |
| `bm_lewis` | British Male |

## How it works

Speako uses a producer/consumer pipeline for streaming TTS:

1. Text is split into sentences at punctuation boundaries (`. ! ? ;`)
2. A **synth producer** thread synthesizes each sentence with Kokoro ONNX
3. A **playback consumer** thread plays audio chunks back-to-back via PortAudio
4. The producer stays 1–2 chunks ahead, so transitions between sentences are seamless

This means speech starts within ~0.5 seconds regardless of total text length.

## Project structure

```
Speako/
├── src/
│   └── app.py                  # Main application
├── scripts/
│   ├── build_dmg.sh            # Build script (venv + py2app + DMG)
│   └── setup_py2app.py         # py2app configuration
├── assets/
│   ├── Speako.icns             # App icon
│   ├── icon.svg                # App icon source
│   ├── menubar_icon.svg        # Menu bar icon source
│   ├── menubar_iconTemplate.png    # Menu bar icon (1x)
│   └── menubar_iconTemplate@2x.png # Menu bar icon (2x Retina)
├── README.md
├── LICENSE
└── .gitignore
```

## Runtime data

On first launch, Speako downloads the Kokoro v1.0 model files (~350 MB) to:

```
~/Library/Application Support/Speako/
├── kokoro-v1.0.onnx     # Voice model
├── voices-v1.0.bin      # Voice embeddings
├── state.txt            # Saved voice + speed preferences
└── app.log              # Runtime log
```

## Troubleshooting

**App won't open / "damaged" warning:**
Right-click → Open, or run: `xattr -cr /Applications/Speako.app`

**Hotkey doesn't work globally:**
Re-grant Accessibility: System Settings → Privacy & Security → Accessibility → remove Speako, re-add it, toggle on. Quit and relaunch the app.

**No audio output:**
Check `~/Library/Application Support/Speako/app.log` for errors. Verify your output device is working with other apps.

**Model download fails:**
Manually download [kokoro-v1.0.onnx](https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx) and [voices-v1.0.bin](https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin) into `~/Library/Application Support/Speako/`.

## Tech stack

- [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx) — TTS engine
- [ONNX Runtime](https://onnxruntime.ai/) — model inference
- [rumps](https://github.com/jaredks/rumps) — macOS menu bar framework
- [pynput](https://github.com/moses-palmer/pynput) — global hotkey listener
- [sounddevice](https://python-sounddevice.readthedocs.io/) — audio playback via PortAudio
- [py2app](https://py2app.readthedocs.io/) — macOS .app bundling

## License

MIT License — see [LICENSE](LICENSE).
