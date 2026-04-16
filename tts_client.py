#!/usr/bin/env python3
"""TTS client: copies the current selection via Cmd+C, sends it to the daemon."""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pyperclip

SOCKET_PATH = Path.home() / "tts-hotkey" / "tts.sock"

COPY_APPLESCRIPT = 'tell application "System Events" to keystroke "c" using command down'


def copy_selection() -> str:
    prior = ""
    try:
        prior = pyperclip.paste()
    except Exception:
        pass

    # Clear so we can detect whether Cmd+C actually produced something.
    try:
        pyperclip.copy("")
    except Exception:
        pass

    subprocess.run(["osascript", "-e", COPY_APPLESCRIPT], check=False)

    # Give the OS a beat to populate the pasteboard.
    text = ""
    for _ in range(20):
        time.sleep(0.02)
        try:
            text = pyperclip.paste()
        except Exception:
            text = ""
        if text:
            break

    if not text and prior:
        # Restore prior clipboard if copy produced nothing.
        try:
            pyperclip.copy(prior)
        except Exception:
            pass
    return text or ""


def send(text: str) -> str:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(str(SOCKET_PATH))
    try:
        s.sendall(text.encode("utf-8"))
        s.shutdown(socket.SHUT_WR)
        reply = s.recv(4096).decode("utf-8", errors="replace")
    finally:
        s.close()
    return reply


def main() -> int:
    if not SOCKET_PATH.exists():
        sys.stderr.write(f"TTS daemon socket not found at {SOCKET_PATH}\n")
        return 1
    text = copy_selection()
    if not text.strip():
        sys.stderr.write("No selected text.\n")
        return 0
    try:
        reply = send(text)
    except Exception as e:
        sys.stderr.write(f"Failed to reach daemon: {e!r}\n")
        return 1
    print(reply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
