#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess, threading, time, json, os
from pathlib import Path
from gpiozero import DigitalInputDevice, DigitalOutputDevice
import socket, atexit

# ─── Ayarlar ───
BASE = Path("/home/cmos/Desktop")
VIDEO_IDLE = BASE / "video1.mp4"
VIDEO_EVT  = BASE / "video2.mp4"
MPV = "/usr/bin/mpv"
SOCKET_PATH = "/tmp/mpv-socket"

GPIO_SENSOR, GPIO_R1, GPIO_R2 = 17, 27, 22
T_GAP = 0.10  # röle geçiş tamponu

relay1 = DigitalOutputDevice(GPIO_R1, active_high=False, initial_value=False)
relay2 = DigitalOutputDevice(GPIO_R2, active_high=False, initial_value=True)
pir    = DigitalInputDevice(GPIO_SENSOR, pull_up=False)

mpv_proc = None
lock = threading.Lock()
playing_evt = False

# ─── mpv kontrolü ───
def mpv_start():
    global mpv_proc
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
    mpv_proc = subprocess.Popen([
        MPV, str(VIDEO_IDLE),
        "--input-ipc-server=" + SOCKET_PATH,
        "--fullscreen", "--no-border", "--ontop", "--force-window=yes",
        "--loop", "--really-quiet", "--idle=yes"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for _ in range(30):
        if os.path.exists(SOCKET_PATH):
            return
        time.sleep(0.1)
    print("[mpv_start] Uyarı: mpv socket oluşmadı.")

def mpv_send(command: dict):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(SOCKET_PATH)
            client.sendall((json.dumps(command) + "\n").encode("utf-8"))
    except Exception as e:
        print(f"[mpv_send] Hata: {e}")

def mpv_loadfile(path: Path, loop=False):
    mpv_send({ "command": ["loadfile", str(path), "replace"] })
    mpv_send({ "command": ["set_property", "pause", False] })
    mpv_send({ "command": ["set_property", "loop", "inf" if loop else "no"] })
    if not loop:
        mpv_send({ "command": ["set_property", "keep-open", "yes"] })

def mpv_quit():
    mpv_send({ "command": ["quit"] })

# ─── video süresi ───
def video_len(path: Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path)], text=True)
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return 1.0

LEN_EVT = video_len(VIDEO_EVT)

# ─── Röle geçişi ───
def switch_relays(active: str):
    if active == 'R1':
        relay2.off(); time.sleep(T_GAP); relay1.on()
    else:
        relay1.off(); time.sleep(T_GAP); relay2.on()

# ─── video1 döngüsü ───
def idle_mode():
    switch_relays('R1')
    mpv_loadfile(VIDEO_IDLE, loop=True)

# ─── video2 + 10 sn röle2 modu ───
def event_sequence():
    global playing_evt
    with lock:
        if playing_evt:
            return
        playing_evt = True

    mpv_loadfile(VIDEO_EVT, loop=False)
    time.sleep(LEN_EVT)

    switch_relays('R2')
    time.sleep(10)

    idle_mode()
    with lock:
        playing_evt = False

# ─── Sensör izleme ───
def sensor_loop():
    while True:
        if pir.is_active:
            if not playing_evt:
                threading.Thread(target=event_sequence, daemon=True).start()
            # 🧠 Bir kere tetikledikten sonra kişi sensör önünden çekilene kadar bekle
            while pir.is_active:
                time.sleep(0.1)
        time.sleep(0.05)

# ─── Çıkışta temizle ───
def clean_exit():
    try:
        relay1.off(); relay2.off()
        mpv_quit()
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)
    except: pass

atexit.register(clean_exit)

# ─── Başlat ───
mpv_start()
threading.Thread(target=sensor_loop, daemon=True).start()
idle_mode()

# ESC ile çıkış
try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.bind("<Escape>", lambda *_: exit(0))
    root.mainloop()
except:
    while True: time.sleep(1)
