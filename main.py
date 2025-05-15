#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess, threading, time, tkinter as tk, json
from pathlib import Path
from gpiozero import DigitalInputDevice, DigitalOutputDevice

# ─── Dosyalar & GPIO ───
BASE = Path("/home/cmos/Desktop")
VIDEO_IDLE, VIDEO_EVT = BASE / "video1.mp4", BASE / "video2.mp4"
MPV = "/usr/bin/mpv"

GPIO_SENSOR, GPIO_R1, GPIO_R2 = 17, 27, 22    # pin numaraları (BCM)
T_GAP = 0.10                                   # röle geçiş tamponu (sn)

# Röleler aktif-LOW  (LOW = çekik)
relay1 = DigitalOutputDevice(GPIO_R1, active_high=False, initial_value=True)  # HIGH = serbest
relay2 = DigitalOutputDevice(GPIO_R2, active_high=False, initial_value=True)
pir    = DigitalInputDevice(GPIO_SENSOR, pull_up=False)

LOOP_ARGS = ["--loop", "--fullscreen", "--no-border", "--ontop", "--really-quiet", "--force-window=yes"]
ONCE_ARGS = ["--fullscreen", "--no-border", "--ontop", "--really-quiet",
             "--keep-open=always", "--force-window=yes"]

status = None
mpv_proc = None
lock, playing_evt = threading.Lock(), False

# ─── video-2 süresi (sn) ───
def video_len(path: Path) -> float:
    try:
        meta = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)], text=True)
        return float(json.loads(meta)["format"]["duration"])
    except Exception:
        return 1.0

LEN_EVT = video_len(VIDEO_EVT)

# ─── mpv yardımcıları ───
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
def switch_relays(new_active: str):
    """new_active: 'R1' veya 'R2'"""
    if new_active == 'R1':
        relay2.off()             # R2 HIGH (pasif)
        time.sleep(T_GAP)
        relay1.on()              # R1 LOW (aktif)
    else:  # 'R2'
        relay1.off()             # R1 HIGH
        time.sleep(T_GAP)
        relay2.on()              # R2 LOW

# ─── video-1 döngü modu ───
def idle_mode():
    switch_relays('R1')
    status.set("🟢 video1 döngüde — R1 LOW, R2 HIGH")
    mpv_start(VIDEO_IDLE, loop=True)

# ─── video-2 + 10 s sekansı ───
def event_sequence():
    global playing_evt
    with lock:
        if playing_evt:
            return
        playing_evt = True

    # video-2 sırasında R1 LOW kalacak
    status.set("🔴 video2 oynuyor — R1 LOW, R2 HIGH")
    mpv_stop()
    mpv_start(VIDEO_EVT, loop=False)
    time.sleep(LEN_EVT)          # video-2 uzunluğu

    # 10 s boyunca R2 LOW, R1 HIGH
    switch_relays('R2')
    status.set("⚡ R2 LOW (10 s)")
    time.sleep(10)

    # Döngüye dön
    idle_mode()
    with lock:
        playing_evt = False

# ─── Sensör kenar tetikleme ───
def sensor_loop():
    last = pir.value
    while True:
        cur = pir.value
        if cur and not last:
            threading.Thread(target=event_sequence, daemon=True).start()
        last = cur
        time.sleep(0.05)

# ─── Tkinter GUI ───
root = tk.Tk()
root.configure(bg="black")
root.attributes("-fullscreen", True, "-topmost", True)
root.title("Video + Röle Kontrol")

status = tk.StringVar(value="⏳ Başlatılıyor…")
tk.Label(root, textvariable=status, font=("DejaVu Sans", 16),
         fg="white", bg="black").pack(pady=30)

def clean_exit(*_):
    mpv_stop()
    relay1.off(); relay2.off()
    root.destroy()

root.bind("<Escape>", clean_exit)
root.protocol("WM_DELETE_WINDOW", clean_exit)

idle_mode()
threading.Thread(target=sensor_loop, daemon=True).start()
root.mainloop()
