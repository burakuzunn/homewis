#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess, threading, time, tkinter as tk, json
from pathlib import Path
from gpiozero import DigitalInputDevice, DigitalOutputDevice

# ───── Dosya & PIN ─────
BASE_PATH  = Path("/home/cmos/Desktop")
VIDEO_IDLE = BASE_PATH / "video1.mp4"
VIDEO_EVT  = BASE_PATH / "video2.mp4"
MPV_CMD    = "/usr/bin/mpv"

SENSOR_PIN, RELAY1_PIN, RELAY2_PIN = 17, 27, 22  # GPIO

# Röleler aktif-LOW
relay1 = DigitalOutputDevice(RELAY1_PIN, active_high=False, initial_value=True)
relay2 = DigitalOutputDevice(RELAY2_PIN, active_high=False, initial_value=True)
pir    = DigitalInputDevice(SENSOR_PIN, pull_up=False)

LOOP_ARGS  = ["--loop", "--fullscreen", "--no-border", "--ontop", "--really-quiet", "--force-window=yes"]
ONCE_ARGS  = ["--fullscreen", "--no-border", "--ontop", "--really-quiet",
              "--keep-open=always", "--force-window=yes"]

status, mpv_proc = None, None
lock, playing_evt = threading.Lock(), False

# ───── Yardımcı: video süresi (sn) ─────
def video_length(path: Path) -> float:
    try:
        info = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of", "json", str(path)],
            text=True)
        return float(json.loads(info)['format']['duration'])
    except Exception:
        return 0

LEN_EVT = max(1, video_length(VIDEO_EVT))  # yedeğe karşı

# ▶ mpv başlat / durdur
def start_mpv(video: Path, loop: bool):
    global mpv_proc
    stop_mpv()
    args = LOOP_ARGS if loop else ONCE_ARGS
    mpv_proc = subprocess.Popen([MPV_CMD, str(video), *args],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def stop_mpv():
    global mpv_proc
    if mpv_proc and mpv_proc.poll() is None:
        mpv_proc.terminate()
        try: mpv_proc.wait(timeout=2)
        except subprocess.TimeoutExpired: mpv_proc.kill()
    mpv_proc = None

# ▶ video-1 + röle-1
def play_idle():
    status.set("🟢 video1 döngüde — Röle-1 ON")
    relay2.off(); time.sleep(0.15); relay1.on()
    start_mpv(VIDEO_IDLE, loop=True)

# ▶ video-2 + röle-2
def handle_event():
    global playing_evt
    with lock:
        if playing_evt: return
        playing_evt = True

    relay1.off(); stop_mpv()
    status.set("🔴 video2 oynuyor"); start_mpv(VIDEO_EVT, loop=False)

    time.sleep(LEN_EVT)  # video süresi kadar bekle

    status.set("⚡ Röle-2 ON (10 s)"); relay2.on()
    time.sleep(10); relay2.off(); status.set("⚡ Röle-2 OFF")

    time.sleep(0.15); play_idle()
    with lock: playing_evt = False

# ▶ Sensör kenar tetikleme
def sensor_watcher():
    last = pir.value
    while True:
        cur = pir.value
        if cur and not last: threading.Thread(target=handle_event, daemon=True).start()
        last = cur; time.sleep(0.05)

# ───── Tkinter GUI ─────
root = tk.Tk(); root.configure(bg="black"); root.attributes("-fullscreen", True, "-topmost", True)
root.title("Video + Röle Kontrol")
status = tk.StringVar(value="⏳ Başlatılıyor…")
tk.Label(root, textvariable=status, font=("DejaVu Sans", 16),
         fg="white", bg="black").pack(pady=30)
def on_close(*_): stop_mpv(); relay1.off(); relay2.off(); root.destroy()
root.bind("<Escape>", on_close); root.protocol("WM_DELETE_WINDOW", on_close)

play_idle()
threading.Thread(target=sensor_watcher, daemon=True).start()
root.mainloop()
