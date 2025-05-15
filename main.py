#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess, threading, time, json, tkinter as tk
from pathlib import Path
from gpiozero import DigitalInputDevice, DigitalOutputDevice

# ─── Dosyalar & GPIO ───
BASE = Path("/home/cmos/Desktop")
VIDEO_IDLE, VIDEO_EVT = BASE / "video1.mp4", BASE / "video2.mp4"
MPV = "/usr/bin/mpv"

GPIO_SENSOR, GPIO_R1, GPIO_R2 = 17, 27, 22
T_GAP = 0.10  # röle geçiş tamponu

# Röleler aktif-LOW
relay1 = DigitalOutputDevice(GPIO_R1, active_high=False, initial_value=True)
relay2 = DigitalOutputDevice(GPIO_R2, active_high=False, initial_value=True)
pir    = DigitalInputDevice(GPIO_SENSOR, pull_up=False)

LOOP_ARGS = ["--loop", "--fullscreen", "--no-border", "--ontop", "--really-quiet", "--force-window=yes"]
ONCE_ARGS = ["--fullscreen", "--no-border", "--ontop", "--really-quiet",
             "--keep-open=always", "--force-window=yes"]

mpv_proc = None
lock, playing_evt = threading.Lock(), False

def video_len(path: Path) -> float:
    try:
        meta = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)], text=True)
        return float(json.loads(meta)["format"]["duration"])
    except Exception:
        return 1.0

LEN_EVT = video_len(VIDEO_EVT)

# ─── mpv helpers ───
def mpv_start(path: Path, loop: bool):
    global mpv_proc
    mpv_stop()
    args = LOOP_ARGS if loop else ONCE_ARGS
    mpv_proc = subprocess.Popen([MPV, str(path), *args],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def mpv_stop():
    global mpv_proc
    if mpv_proc and mpv_proc.poll() is None:
        mpv_proc.terminate()
        try:
            mpv_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            mpv_proc.kill()
    mpv_proc = None

# ─── Röle değiştirme ───
def switch_relays(active: str):
    if active == 'R1':
        relay2.off(); time.sleep(T_GAP); relay1.on()
    else:
        relay1.off(); time.sleep(T_GAP); relay2.on()

# ─── video-1 döngü ───
def idle_mode():
    print("→ idle: R1 LOW, R2 HIGH")
    switch_relays('R1')
    mpv_start(VIDEO_IDLE, loop=True)

# ─── video-2 + 10 s ───
def event_sequence():
    global playing_evt
    with lock:
        if playing_evt: return
        playing_evt = True

    print("→ event: video-2 başlıyor")
    mpv_stop(); mpv_start(VIDEO_EVT, loop=False)
    time.sleep(LEN_EVT)

    print("→ R2 LOW (10 s)")
    switch_relays('R2')
    time.sleep(10)

    idle_mode()
    with lock:
        playing_evt = False

# ─── sensör izle ───
def sensor_loop():
    last = pir.value
    while True:
        cur = pir.value
        if cur and not last:
            threading.Thread(target=event_sequence, daemon=True).start()
        last = cur
        time.sleep(0.05)

# ─── Gizli Tk penceresi (sadece ESC yakalamak için) ───
root = tk.Tk(); root.withdraw()   # pencere gizli

def clean_exit(*_):
    mpv_stop(); relay1.off(); relay2.off(); root.destroy()

root.bind("<Escape>", clean_exit)
threading.Thread(target=sensor_loop, daemon=True).start()
idle_mode()
root.mainloop()
