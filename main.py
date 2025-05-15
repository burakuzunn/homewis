#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess, threading, time, tkinter as tk, json
from pathlib import Path
from gpiozero import DigitalInputDevice, DigitalOutputDevice

# ─── Dosya & GPIO ───
BASE       = Path("/home/cmos/Desktop")
VIDEO_IDLE = BASE / "video1.mp4"
VIDEO_EVT  = BASE / "video2.mp4"
MPV        = "/usr/bin/mpv"

PIN_SENSOR, PIN_R1, PIN_R2 = 17, 27, 22    # GPIO numaraları
TAMPON = 0.10                               # röle geçiş tamponu (saniye)

# Röleler aktif-LOW (LOW=ÇEKİK)
relay1 = DigitalOutputDevice(PIN_R1, active_high=False, initial_value=True)  # HIGH=serbest
relay2 = DigitalOutputDevice(PIN_R2, active_high=False, initial_value=True)
pir    = DigitalInputDevice(PIN_SENSOR, pull_up=False)

LOOP_ARGS = ["--loop", "--fullscreen", "--no-border", "--ontop", "--really-quiet", "--force-window=yes"]
ONCE_ARGS = ["--fullscreen", "--no-border", "--ontop", "--really-quiet",
             "--keep-open=always", "--force-window=yes"]

status, mpv_proc = None, None
lock, playing_evt = threading.Lock(), False

# ─── video süresi (saniye) ───
def video_seconds(path: Path) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)], text=True)
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return 1.0

LEN_EVT = video_seconds(VIDEO_EVT)

# ─── mpv helpers ───
def mpv_start(video: Path, loop: bool):
    global mpv_proc
    mpv_stop()
    args = LOOP_ARGS if loop else ONCE_ARGS
    mpv_proc = subprocess.Popen([MPV, str(video), *args],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def mpv_stop():
    global mpv_proc
    if mpv_proc and mpv_proc.poll() is None:
        mpv_proc.terminate()
        try: mpv_proc.wait(timeout=2)
        except subprocess.TimeoutExpired: mpv_proc.kill()
    mpv_proc = None

# ─── durumlar ───
def idle_mode():
    status.set("🟢 video1 döngüde — R1 LOW, R2 HIGH")
    # geçiş: önce R1 LOW, sonra kısa tamponla R2 HIGH
    relay1.on()                  # R1 LOW (aktif)
    time.sleep(TAMPON)
    relay2.off()                 # R2 HIGH (pasif)
    mpv_start(VIDEO_IDLE, loop=True)

def event_sequence():
    global playing_evt
    with lock:
        if playing_evt: return
        playing_evt = True

    # Geçiş 1: R2 LOW → tampon → R1 HIGH
    relay2.on()                  # yeni röle LOW
    time.sleep(TAMPON)
    relay1.off()                 # eski röle HIGH
    mpv_stop()

    status.set("🔴 video2 oynuyor")
    mpv_start(VIDEO_EVT, loop=False)
    time.sleep(LEN_EVT)          # video süresi

    status.set("⚡ R2 10 sn LOW")
    time.sleep(10)               # R2 hâlâ LOW

    # Geçiş 2: R1 LOW → tampon → R2 HIGH
    relay1.on()                  # R1 LOW
    time.sleep(TAMPON)
    relay2.off()                 # R2 HIGH
    status.set("⚡ R2 HIGH, R1 LOW")

    idle_mode()
    with lock: playing_evt = False

# ─── sensör izleme ───
def sensor_loop():
    last = pir.value
    while True:
        cur = pir.value
        if cur and not last:
            threading.Thread(target=event_sequence, daemon=True).start()
        last = cur
        time.sleep(0.05)

# ─── GUI ───
root = tk.Tk()
root.configure(bg="black")
root.attributes("-fullscreen", True)
root.attributes("-topmost", True)
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
