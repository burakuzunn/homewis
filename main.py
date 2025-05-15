#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess, threading, time, json, os, socket, atexit
from pathlib import Path
from gpiozero import DigitalInputDevice, DigitalOutputDevice

# ─── Ayarlar ───
BASE = Path("/home/cmos/Desktop")
VIDEO_IDLE = BASE / "video1.mp4"
VIDEO_EVT  = BASE / "video2.mp4"
MPV = "/usr/bin/mpv"
SOCKET_PATH = "/tmp/mpv-socket"

GPIO_SENSOR, GPIO_R1, GPIO_R2 = 17, 27, 22
T_GAP = 0.10                   # röle geçiş tamponu (sn)

# Röleler aktif-LOW
relay1 = DigitalOutputDevice(GPIO_R1, active_high=False, initial_value=False)  # LOW = çekik
relay2 = DigitalOutputDevice(GPIO_R2, active_high=False, initial_value=True)   # HIGH = serbest
pir    = DigitalInputDevice(GPIO_SENSOR, pull_up=False, bounce_time=0.1)

mpv_proc = None
playing_evt = False
lock = threading.Lock()

# ─── mpv yardımcıları ───
def mpv_start():
    global mpv_proc
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
    mpv_proc = subprocess.Popen([
        MPV, str(VIDEO_IDLE),
        f"--input-ipc-server={SOCKET_PATH}",
        "--fullscreen", "--no-border", "--ontop",
        "--force-window=yes", "--really-quiet", "--idle=yes"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # socket hazır olana kadar bekle (≤3 s)
    for _ in range(30):
        if os.path.exists(SOCKET_PATH):
            break
        time.sleep(0.1)

def mpv_send(cmd: dict):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(SOCKET_PATH)
            s.sendall((json.dumps(cmd) + "\n").encode())
    except Exception as e:
        print("[mpv_send]", e)

def mpv_load(path: Path, loop: bool):
    mpv_send({"command": ["loadfile", str(path), "replace"]})
    mpv_send({"command": ["set_property", "pause", False]})
    mpv_send({"command": ["set_property", "loop", "inf" if loop else "no"]})
    if not loop:
        mpv_send({"command": ["set_property", "keep-open", "yes"]})

def mpv_quit():
    mpv_send({"command": ["quit"]})

# ─── video süresi ───
def duration(path: Path) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of", "json", str(path)],
            text=True)
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return 1.0

LEN_EVT = duration(VIDEO_EVT)

# ─── Röle geçişi ───
def switch_relays(active: str):
    if active == "R1":
        relay2.off(); time.sleep(T_GAP); relay1.on()
    else:
        relay1.off(); time.sleep(T_GAP); relay2.on()

# ─── Senaryo akışı ───
def idle_mode():
    switch_relays("R1")
    mpv_load(VIDEO_IDLE, loop=True)

def event_sequence():
    global playing_evt
    with lock:
        if playing_evt:
            return
        playing_evt = True

    mpv_load(VIDEO_EVT, loop=False)
    time.sleep(LEN_EVT)

    switch_relays("R2")
    time.sleep(10)

    idle_mode()
    with lock:
        playing_evt = False

# ─── Sensör izleme (sürekli HIGH denetimi) ───
def sensor_loop():
    while True:
        if pir.is_active and not playing_evt:          # HIGH + sistem boşta
            threading.Thread(target=event_sequence, daemon=True).start()
        time.sleep(0.05)

# ─── Temiz çıkış ───
def clean_exit():
    try:
        relay1.off(); relay2.off()
        mpv_quit()
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)
    finally:
        exit(0)

atexit.register(clean_exit)

# ─── Başlat ───
mpv_start()
idle_mode()
threading.Thread(target=sensor_loop, daemon=True).start()

# ESC ile çıkış (isteğe bağlı)
try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.bind("<Escape>", lambda *_: clean_exit())
    root.mainloop()
except:
    while True:
        time.sleep(1)
