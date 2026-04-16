#!/usr/bin/env python3
"""macOS menu bar UI for the TTS daemon.

Run: ~/tts-hotkey/.venv/bin/python3 tts_menubar.py

Menu:
    🔊 TTS
    ├── Speak selection          (⌘⇧R equivalent)
    ├── Stop
    ├── ─────────
    ├── Voice ▸  (list of Kokoro voices, current has a bullet)
    ├── Speed ▸  (0.75 / 1.0 / 1.25 / 1.5)
    ├── ─────────
    ├── Status: idle | voice=af_sarah | speed=1.0 | queued=0
    └── Quit
"""

import socket
import subprocess
import sys
from pathlib import Path

import rumps

BASE_DIR = Path.home() / "tts-hotkey"
SOCKET_PATH = BASE_DIR / "tts.sock"
VENV_PY = BASE_DIR / ".venv" / "bin" / "python3"
CLIENT = BASE_DIR / "tts_client.py"

# Common Kokoro v1.0 voices. The daemon accepts any name Kokoro recognises;
# users can add more here if they want them in the picker.
VOICES = [
    "af_sarah", "af_heart", "af_bella", "af_nicole", "af_sky",
    "am_adam", "am_michael",
    "bf_emma", "bf_isabella",
    "bm_george", "bm_lewis",
]
SPEEDS = [0.75, 1.0, 1.25, 1.5]


def send(cmd: str, timeout: float = 2.0) -> str:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(SOCKET_PATH))
        s.sendall(cmd.encode("utf-8"))
        s.shutdown(socket.SHUT_WR)
        return s.recv(4096).decode("utf-8", errors="replace")
    finally:
        s.close()


class TTSApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("🔊", quit_button=None)
        self.speak_item = rumps.MenuItem("Speak selection",
                                         callback=self.on_speak,
                                         key="r")
        self.stop_item = rumps.MenuItem("Stop", callback=self.on_stop, key=".")
        self.voice_menu = rumps.MenuItem("Voice")
        for v in VOICES:
            self.voice_menu.add(rumps.MenuItem(v, callback=self.on_voice))
        self.speed_menu = rumps.MenuItem("Speed")
        for s in SPEEDS:
            self.speed_menu.add(
                rumps.MenuItem(f"{s:g}×", callback=self.on_speed)
            )
        self.status_item = rumps.MenuItem("Status: …")
        self.status_item.set_callback(None)  # non-clickable

        self.menu = [
            self.speak_item,
            self.stop_item,
            None,
            self.voice_menu,
            self.speed_menu,
            None,
            self.status_item,
            None,
            rumps.MenuItem("Quit", callback=rumps.quit_application, key="q"),
        ]

        self._refresh_state()
        rumps.Timer(self._tick, 2).start()

    # --- actions ----------------------------------------------------------

    def on_speak(self, _):
        # Reuse the client so Cmd+C selection grab is identical to the hotkey path.
        try:
            subprocess.Popen([str(VENV_PY), str(CLIENT)])
        except Exception as e:
            rumps.notification("TTS", "Speak failed", str(e))

    def on_stop(self, _):
        try:
            send("STOP")
        except Exception as e:
            rumps.notification("TTS", "Stop failed", str(e))

    def on_voice(self, item):
        try:
            reply = send(f"VOICE {item.title}")
            if reply.startswith("OK"):
                self._mark_voice(item.title)
        except Exception as e:
            rumps.notification("TTS", "Voice change failed", str(e))

    def on_speed(self, item):
        val = item.title.rstrip("×")
        try:
            reply = send(f"SPEED {val}")
            if reply.startswith("OK"):
                self._mark_speed(val)
        except Exception as e:
            rumps.notification("TTS", "Speed change failed", str(e))

    # --- state ------------------------------------------------------------

    def _mark_voice(self, current: str) -> None:
        for name, item in self.voice_menu.items():
            item.state = 1 if name == current else 0

    def _mark_speed(self, current: str) -> None:
        target = f"{float(current):g}×"
        for name, item in self.speed_menu.items():
            item.state = 1 if name == target else 0

    def _refresh_state(self) -> None:
        try:
            reply = send("STATUS", timeout=0.5)
        except Exception:
            self.title = "🔇"
            self.status_item.title = "Status: daemon unreachable"
            return
        self.status_item.title = f"Status: {reply}"
        # Parse "state voice=x speed=y queued=n"
        parts = dict(
            p.split("=", 1) for p in reply.split() if "=" in p
        )
        voice = parts.get("voice")
        speed = parts.get("speed")
        if voice:
            self._mark_voice(voice)
        if speed:
            self._mark_speed(speed)
        self.title = "🔊" if reply.startswith("playing") else "🔉"

    def _tick(self, _sender):
        self._refresh_state()


def main() -> int:
    if not SOCKET_PATH.exists():
        sys.stderr.write(
            f"Daemon socket not found at {SOCKET_PATH}. Start the daemon first.\n"
        )
    TTSApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
