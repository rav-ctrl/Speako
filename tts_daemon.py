#!/usr/bin/env python3
"""TTS daemon: loads Kokoro ONNX once, serves requests over a Unix socket.

Protocol (line-based, UTF-8):
    SAY\n<text>       -> synth + play; replies OK / SKIP empty / SKIP duplicate
    STOP              -> stop current playback + drain queue; replies OK
    VOICE <name>      -> set voice; replies OK
    SPEED <float>     -> set speed; replies OK
    STATUS            -> replies "<playing|idle> voice=<v> speed=<s> queued=<n>"
    PING              -> replies PONG

For backward compatibility, a request that doesn't start with a known verb
is treated as SAY <text>.
"""

import os
import socket
import sys
import threading
import queue
import signal
from pathlib import Path

import numpy as np
import sounddevice as sd
from kokoro_onnx import Kokoro

HOME = Path.home()
BASE_DIR = HOME / "tts-hotkey"
MODEL_PATH = BASE_DIR / "kokoro-v1.0.onnx"
VOICES_PATH = BASE_DIR / "voices-v1.0.bin"
SOCKET_PATH = BASE_DIR / "tts.sock"
STATE_PATH = BASE_DIR / "state.txt"
LOG_PATH = BASE_DIR / "tts_daemon.log"

DEFAULT_VOICE = os.environ.get("KOKORO_VOICE", "af_sarah")
DEFAULT_SPEED = float(os.environ.get("KOKORO_SPEED", "1.0"))
LANG = os.environ.get("KOKORO_LANG", "en-us")

MAX_MSG_BYTES = 1 << 20  # 1 MiB


def log(msg: str) -> None:
    with open(LOG_PATH, "a") as f:
        f.write(msg.rstrip() + "\n")


class TTSDaemon:
    def __init__(self) -> None:
        log(f"Loading Kokoro model from {MODEL_PATH}")
        self.kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))
        self.q: "queue.Queue[str | None]" = queue.Queue()
        self.lock = threading.Lock()
        self.last_text: str | None = None
        self.voice = DEFAULT_VOICE
        self.speed = DEFAULT_SPEED
        self.playing = False
        self._load_state()
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()
        log(f"Daemon ready; voice={self.voice} speed={self.speed}")

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
            log(f"state load error: {e!r}")

    def _save_state(self) -> None:
        try:
            STATE_PATH.write_text(f"voice={self.voice}\nspeed={self.speed}\n")
        except Exception as e:
            log(f"state save error: {e!r}")

    def _worker_loop(self) -> None:
        while True:
            text = self.q.get()
            if text is None:
                continue
            with self.lock:
                voice = self.voice
                speed = self.speed
            try:
                samples, sr = self.kokoro.create(
                    text, voice=voice, speed=speed, lang=LANG
                )
                samples = np.asarray(samples, dtype=np.float32)
                self.playing = True
                sd.play(samples, sr)
                sd.wait()
            except Exception as e:
                log(f"synthesis error: {e!r}")
            finally:
                self.playing = False

    # --- command handlers -------------------------------------------------

    def cmd_say(self, text: str) -> str:
        text = text.strip()
        if not text:
            return "SKIP empty"
        with self.lock:
            if text == self.last_text:
                return "SKIP duplicate"
            self.last_text = text
        self.q.put(text)
        return f"OK queued ({len(text)} chars)"

    def cmd_stop(self) -> str:
        # Drain the pending queue, then stop the current stream.
        drained = 0
        try:
            while True:
                self.q.get_nowait()
                drained += 1
        except queue.Empty:
            pass
        try:
            sd.stop()
        except Exception as e:
            log(f"sd.stop error: {e!r}")
        with self.lock:
            self.last_text = None
        return f"OK stopped (drained {drained})"

    def cmd_voice(self, name: str) -> str:
        name = name.strip()
        if not name:
            return "ERR empty voice"
        with self.lock:
            self.voice = name
        self._save_state()
        return f"OK voice={name}"

    def cmd_speed(self, val: str) -> str:
        try:
            s = float(val)
        except ValueError:
            return "ERR bad speed"
        s = max(0.5, min(2.0, s))
        with self.lock:
            self.speed = s
        self._save_state()
        return f"OK speed={s}"

    def cmd_status(self) -> str:
        state = "playing" if self.playing else "idle"
        return f"{state} voice={self.voice} speed={self.speed} queued={self.q.qsize()}"

    def handle(self, raw: str) -> str:
        if not raw:
            return "SKIP empty"
        # Split off first line as verb.
        head, _, rest = raw.partition("\n")
        verb = head.strip().upper()
        if verb == "SAY":
            return self.cmd_say(rest)
        if verb == "STOP":
            return self.cmd_stop()
        if verb == "STATUS":
            return self.cmd_status()
        if verb == "PING":
            return "PONG"
        if verb.startswith("VOICE"):
            # Either "VOICE name" on one line or "VOICE\nname"
            parts = head.split(None, 1)
            name = parts[1] if len(parts) > 1 else rest
            return self.cmd_voice(name)
        if verb.startswith("SPEED"):
            parts = head.split(None, 1)
            val = parts[1] if len(parts) > 1 else rest
            return self.cmd_speed(val)
        # Backward compat: treat anything else as raw text to speak.
        return self.cmd_say(raw)


def serve(daemon: TTSDaemon) -> None:
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(SOCKET_PATH))
    os.chmod(SOCKET_PATH, 0o600)
    sock.listen(16)
    log(f"Listening on {SOCKET_PATH}")

    def shutdown(*_a):
        log("Shutting down")
        try:
            sock.close()
        finally:
            if SOCKET_PATH.exists():
                SOCKET_PATH.unlink()
            sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while True:
        try:
            conn, _ = sock.accept()
        except OSError:
            break
        threading.Thread(target=_handle, args=(conn, daemon), daemon=True).start()


def _handle(conn: socket.socket, daemon: TTSDaemon) -> None:
    try:
        chunks = []
        total = 0
        while True:
            buf = conn.recv(4096)
            if not buf:
                break
            chunks.append(buf)
            total += len(buf)
            if total >= MAX_MSG_BYTES:
                break
        raw = b"".join(chunks).decode("utf-8", errors="replace")
        reply = daemon.handle(raw)
        try:
            conn.sendall(reply.encode("utf-8"))
        except OSError:
            pass
    finally:
        conn.close()


def main() -> None:
    if not MODEL_PATH.exists() or not VOICES_PATH.exists():
        sys.stderr.write(
            f"Missing model files. Expected:\n  {MODEL_PATH}\n  {VOICES_PATH}\n"
            "Run setup.sh to download them.\n"
        )
        sys.exit(1)
    daemon = TTSDaemon()
    serve(daemon)


if __name__ == "__main__":
    main()
