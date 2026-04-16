#!/usr/bin/env python3
"""Speako — macOS menu bar TTS app powered by Kokoro ONNX.

Copy any text, press the hotkey (⌃⌥⌘\\), and hear it spoken aloud.
Uses sentence-level chunked synthesis for instant playback regardless
of text length.

Bundled as a standalone .app via py2app. See scripts/build_dmg.sh.
"""

import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np
import pyperclip
import rumps
import sounddevice as sd
from pynput import keyboard

APP_NAME = "Speako"
APP_SUPPORT = Path.home() / "Library" / "Application Support" / APP_NAME
MODEL_PATH = APP_SUPPORT / "kokoro-v1.0.onnx"
VOICES_PATH = APP_SUPPORT / "voices-v1.0.bin"
STATE_PATH = APP_SUPPORT / "state.txt"
LOG_PATH = APP_SUPPORT / "app.log"

MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

VOICES = [
    "af_sarah", "af_heart", "af_bella", "af_nicole", "af_sky",
    "am_adam", "am_michael",
    "bf_emma", "bf_isabella",
    "bm_george", "bm_lewis",
]
SPEEDS = [0.75, 1.0, 1.25, 1.5]
LANG = "en-us"

APP_SUPPORT.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    try:
        with open(LOG_PATH, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Model bootstrap
# ---------------------------------------------------------------------------

def _download(url: str, dest: Path) -> None:
    log(f"Downloading {url} -> {dest}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(dest)


def ensure_models() -> None:
    missing = [p for p in (MODEL_PATH, VOICES_PATH) if not p.exists()]
    if not missing:
        return
    rumps.notification(
        APP_NAME,
        "Downloading voice model",
        "~350 MB — one-time download.",
    )
    if not MODEL_PATH.exists():
        _download(MODEL_URL, MODEL_PATH)
    if not VOICES_PATH.exists():
        _download(VOICES_URL, VOICES_PATH)
    rumps.notification(APP_NAME, "Voice model ready", "")


# ---------------------------------------------------------------------------
# Synth worker
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(r'(?<=[.!?;])\s+|\n+')


def _split_sentences(text: str) -> list[str]:
    """Split text into sentence-sized chunks for streaming synthesis."""
    parts = _SENTENCE_RE.split(text)
    chunks: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # If a chunk is very long (no punctuation), split at commas.
        if len(p) > 400:
            sub = [s.strip() for s in p.split(",") if s.strip()]
            chunks.extend(sub)
        else:
            chunks.append(p)
    return chunks or [text.strip()]


# Sentinel pushed into the audio queue to signal end-of-text.
_END = object()


class Synth:
    def __init__(self) -> None:
        import traceback as _tb
        self._tb = _tb
        from kokoro_onnx import Kokoro
        log("Loading Kokoro model")
        self.kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))

        # Incoming text requests (full clipboard payloads).
        self.text_q: "queue.Queue[str | None]" = queue.Queue()
        # Pre-synthesized audio chunks ready for playback (producer→consumer).
        self.audio_q: "queue.Queue[tuple[np.ndarray, int] | object]" = queue.Queue(maxsize=2)

        self.lock = threading.Lock()
        self.last_text: str | None = None
        self.voice = "af_sarah"
        self.speed = 1.0
        self.playing = False
        self._stop_flag = threading.Event()

        self._load_state()
        threading.Thread(target=self._synth_producer, daemon=True).start()
        threading.Thread(target=self._play_consumer, daemon=True).start()
        log(f"Synth ready (voice={self.voice} speed={self.speed})")

    def _load_state(self) -> None:
        if not STATE_PATH.exists():
            return
        try:
            for line in STATE_PATH.read_text().splitlines():
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k == "voice" and v:
                    self.voice = v
                elif k == "speed":
                    self.speed = float(v)
        except Exception as e:
            log(f"state load: {e!r}")

    def _save_state(self) -> None:
        try:
            STATE_PATH.write_text(f"voice={self.voice}\nspeed={self.speed}\n")
        except Exception as e:
            log(f"state save: {e!r}")

    def _synth_producer(self) -> None:
        """Pull full text from text_q, split into sentences, synthesize each
        one, and push (samples, sr) onto audio_q for the consumer."""
        while True:
            text = self.text_q.get()
            if text is None:
                continue
            self._stop_flag.clear()
            with self.lock:
                voice, speed = self.voice, self.speed
            chunks = _split_sentences(text)
            log(f"producer: {len(text)} chars → {len(chunks)} chunks")
            for i, chunk in enumerate(chunks):
                if self._stop_flag.is_set():
                    log("producer: stop flag, aborting")
                    break
                log(f"producer: synth chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")
                try:
                    samples, sr = self.kokoro.create(
                        chunk, voice=voice, speed=speed, lang=LANG
                    )
                    samples = np.asarray(samples, dtype=np.float32)
                    log(f"producer: chunk {i+1} ok samples={samples.shape} sr={sr}")
                except Exception as e:
                    log(f"producer: synth error chunk {i+1}: {e!r}\n{self._tb.format_exc()}")
                    continue
                # Blocking put — if audio_q is full (size 2), we wait here
                # until the consumer finishes playing the current chunk.
                # Check stop flag while waiting.
                while not self._stop_flag.is_set():
                    try:
                        self.audio_q.put((samples, sr), timeout=0.2)
                        break
                    except queue.Full:
                        continue
            # Signal end-of-text so consumer knows to go idle.
            if not self._stop_flag.is_set():
                self.audio_q.put(_END)

    def _play_consumer(self) -> None:
        """Pull pre-synthesized (samples, sr) from audio_q and play them
        back-to-back for gapless streaming."""
        while True:
            item = self.audio_q.get()
            if item is _END or item is None:
                self.playing = False
                continue
            samples, sr = item
            try:
                self.playing = True
                sd.play(samples, sr)
                sd.wait()
            except Exception as e:
                log(f"consumer: play error: {e!r}")
            # Don't set self.playing = False here — next chunk may be ready
            # immediately. We set it False on _END or stop().

    def say(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return "empty"
        with self.lock:
            if text == self.last_text:
                return "duplicate"
            self.last_text = text
        self.text_q.put(text)
        return "queued"

    def stop(self) -> None:
        # 1. Signal producer to abort current synthesis.
        self._stop_flag.set()
        # 2. Drain text queue (pending full-text requests).
        try:
            while True:
                self.text_q.get_nowait()
        except queue.Empty:
            pass
        # 3. Drain audio queue (pre-synthesized chunks waiting to play).
        try:
            while True:
                self.audio_q.get_nowait()
        except queue.Empty:
            pass
        # 4. Stop current playback.
        try:
            sd.stop()
        except Exception as e:
            log(f"sd.stop: {e!r}")
        self.playing = False
        with self.lock:
            self.last_text = None

    def set_voice(self, v: str) -> None:
        with self.lock:
            self.voice = v
        self._save_state()

    def set_speed(self, s: float) -> None:
        with self.lock:
            self.speed = max(0.5, min(2.0, s))
        self._save_state()


# ---------------------------------------------------------------------------
# Clipboard read
# ---------------------------------------------------------------------------

def grab_selection() -> str:
    """Return whatever text is currently on the clipboard.

    Workflow: user copies text with Cmd+C themselves, then presses the hotkey.
    No keystroke simulation, no Apple Events / Automation permission needed.
    """
    try:
        return (pyperclip.paste() or "").strip()
    except Exception as e:
        log(f"clipboard read failed: {e!r}")
        return ""


# ---------------------------------------------------------------------------
# Menu bar
# ---------------------------------------------------------------------------

class TTSApp(rumps.App):
    def __init__(self, synth: Synth) -> None:
        # Resolve menu bar icon relative to the app bundle or script location.
        icon_path = None
        for base in [
            Path(sys.executable).resolve().parent.parent / "Resources",  # py2app bundle
            Path(__file__).resolve().parent.parent / "assets",            # dev/script mode
        ]:
            candidate = base / "menubar_iconTemplate.png"
            if candidate.exists():
                icon_path = str(candidate)
                break
        super().__init__("Speako", icon=icon_path, template=True, quit_button=None)
        if icon_path:
            log(f"Menu bar icon: {icon_path}")
        else:
            log("Menu bar icon not found, using text fallback")
        self.synth = synth

        self.speak_item = rumps.MenuItem("Speak selection", callback=self.on_speak)
        self.stop_item = rumps.MenuItem("Stop", callback=self.on_stop, key=".")

        self.voice_menu = rumps.MenuItem("Voice")
        for v in VOICES:
            self.voice_menu.add(rumps.MenuItem(v, callback=self.on_voice))
        self.speed_menu = rumps.MenuItem("Speed")
        for s in SPEEDS:
            self.speed_menu.add(rumps.MenuItem(f"{s:g}×", callback=self.on_speed))

        self.status_item = rumps.MenuItem("Status: idle")
        self.status_item.set_callback(None)

        self.menu = [
            self.speak_item,
            self.stop_item,
            None,
            self.voice_menu,
            self.speed_menu,
            None,
            self.status_item,
            rumps.MenuItem("Open log", callback=self.on_open_log),
            None,
            rumps.MenuItem("Quit Speako", callback=rumps.quit_application, key="q"),
        ]

        self._mark_voice(self.synth.voice)
        self._mark_speed(str(self.synth.speed))
        rumps.Timer(self._tick, 1).start()

    def on_speak(self, _):
        threading.Thread(target=self._do_speak, daemon=True).start()

    def _do_speak(self) -> None:
        text = grab_selection()
        if not text:
            rumps.notification(
                APP_NAME,
                "Clipboard is empty",
                "Copy text with ⌘C first, then press ⌃⌥⌘\\.",
            )
            return
        preview = text.replace("\n", " ")
        if len(preview) > 60:
            preview = preview[:57] + "…"
        rumps.notification(APP_NAME, "Speaking", preview)
        self.synth.say(text)

    def on_stop(self, _):
        self.synth.stop()

    def on_voice(self, item):
        self.synth.set_voice(item.title)
        self._mark_voice(item.title)

    def on_speed(self, item):
        val = float(item.title.rstrip("×"))
        self.synth.set_speed(val)
        self._mark_speed(str(val))

    def on_open_log(self, _):
        subprocess.run(["open", str(LOG_PATH)], check=False)

    def _mark_voice(self, current: str) -> None:
        for name, item in self.voice_menu.items():
            item.state = 1 if name == current else 0

    def _mark_speed(self, current: str) -> None:
        try:
            target = f"{float(current):g}×"
        except ValueError:
            return
        for name, item in self.speed_menu.items():
            item.state = 1 if name == target else 0

    def _tick(self, _):
        state = "playing" if self.synth.playing else "idle"
        self.status_item.title = (
            f"Status: {state} · {self.synth.voice} · {self.synth.speed:g}×"
        )
        # Don't overwrite the icon with emoji — just keep the template icon.
        # Status is visible in the menu's status line.


# ---------------------------------------------------------------------------
# Hotkey listener (pynput)
# ---------------------------------------------------------------------------

def start_hotkey(app: TTSApp) -> None:
    def on_activate():
        app.on_speak(None)

    hk = keyboard.GlobalHotKeys({"<ctrl>+<alt>+<cmd>+\\": on_activate})
    hk.daemon = True
    hk.start()
    log("Hotkey listener started")


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main() -> None:
    log(f"Starting {APP_NAME}")
    try:
        ensure_models()
    except Exception as e:
        log(f"model download failed: {e!r}")
        rumps.notification(APP_NAME, "Model download failed", str(e))
        sys.exit(1)

    try:
        synth = Synth()
    except Exception as e:
        log(f"synth init failed: {e!r}")
        rumps.notification(APP_NAME, "Synth init failed", str(e))
        sys.exit(1)

    app = TTSApp(synth)
    start_hotkey(app)
    app.run()


if __name__ == "__main__":
    main()
