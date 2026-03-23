import os
import re
import subprocess
import sys
import time
import argparse
import ctypes
from threading import Thread
from pathlib import Path

import server


ROOT = Path(__file__).resolve().parent
CLOUDFLARED = ROOT / "cloudflared.exe"
PUBLIC_URL_PATTERN = re.compile(r"https://[a-z0-9-]+(?:\.[a-z0-9-]+)*\.trycloudflare\.com\b", re.IGNORECASE)


def copy_text_to_clipboard(text: str) -> bool:
    if os.name != "nt":
        return False
    GMEM_MOVEABLE = 0x0002
    CF_UNICODETEXT = 13
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
    if not handle:
        return False
    locked = kernel32.GlobalLock(handle)
    if not locked:
        kernel32.GlobalFree(handle)
        return False
    ctypes.memmove(locked, ctypes.addressof(data), size)
    kernel32.GlobalUnlock(handle)
    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(handle)
        return False
    try:
        user32.EmptyClipboard()
        user32.SetClipboardData(CF_UNICODETEXT, handle)
        handle = None
        return True
    finally:
        user32.CloseClipboard()
        if handle:
            kernel32.GlobalFree(handle)


def write_public_url_note(public_url: str) -> Path | None:
    desktop = Path.home() / "Desktop"
    note_path = desktop / "global_news_public_url.txt"
    try:
        note_path.write_text(
            "Global News Public URL\n\n"
            f"{public_url}\n\n"
            "Keep the share window open while others are visiting this address.\n",
            encoding="utf-8",
        )
        return note_path
    except Exception:
        return None


def forward_tunnel_output(tunnel_proc: subprocess.Popen[str], copy_on_match: bool = False) -> None:
    announced = False
    assert tunnel_proc.stdout is not None
    for raw_line in tunnel_proc.stdout:
        line = raw_line.rstrip()
        if not line:
            continue
        print(f"[cloudflared] {line}")
        if announced:
            continue
        match = PUBLIC_URL_PATTERN.search(line)
        if match:
            announced = True
            public_url = match.group(0)
            print("")
            print(f"Public URL: {public_url}")
            if copy_on_match:
                copied = copy_text_to_clipboard(public_url)
                print("Copied to clipboard." if copied else "Failed to copy to clipboard.")
            note_path = write_public_url_note(public_url)
            if note_path:
                print(f"Saved URL note: {note_path}")
            print("Share this URL with others while this window remains open.")
            print("")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--copy", action="store_true", help="Copy the public URL to clipboard once detected.")
    args = parser.parse_args()

    if not CLOUDFLARED.exists():
        print("cloudflared.exe not found. Please download it first.")
        return 1

    local_url = f"http://127.0.0.1:{server.PORT}"
    env = os.environ.copy()
    env.setdefault("NEWS_AGENT_HOST", "0.0.0.0")

    server_proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env)
    time.sleep(2)
    tunnel_proc = subprocess.Popen(
        [str(CLOUDFLARED), "tunnel", "--url", local_url],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output_thread = Thread(target=forward_tunnel_output, args=(tunnel_proc, args.copy), daemon=True)
    output_thread.start()
    print(f"Local server: {local_url}")
    print("Public tunnel starting...")
    try:
        server_proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        tunnel_proc.terminate()
        server_proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
