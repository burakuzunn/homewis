#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess, threading, time, tkinter as tk
from pathlib import Path
from gpiozero import DigitalInputDevice, DigitalOutputDevice

# ───── Dosya ve PIN Ayarları ─────
BASE_PATH   = Path("/home/cmos/Desktop")
VIDEO_IDLE  = BASE_PATH / "video1.mp4"          # Döngü videosu
VIDEO_EVT   = BASE_PATH / "video2.mp4"          # Tek sefer videosu
MPV_CMD     = "/usr/bin/mpv"

SENSOR_PIN  = 17
RELAY1_PIN  = 27                               # Röle-1: video-1 süresince açık
RELAY2_PIN  = 22                               # Röle-2: video-2 bitince 10 sn açık

LOOP_ARGS = ["--loop", "--fullscreen", "--no-border",
             "--ontop", "--really-quiet", "--force-window=yes"]

# video-2 sonunda son kareyi tut
ONCE_ARGS = ["--fullscreen", "--no-border", "--ontop",
             "--really-quiet", "--keep-open=always", "--force-window=yes"]

# ───── Global Durumlar ─────
status      = None
mpv_proc    = None
lock        = threading.Lock()
playing_evt = False

# Röle & Sensör
relay1 = DigitalOutputDevice(RELAY1_PIN, active_high=True, initial_value=True)   # Başta AÇIK
relay2 = DigitalOutputDevice(RELAY2_PIN, active_high=True, initial_value=False)  # Başta KAPALI
pir    = DigitalInputDevice(SENSOR_PIN, pull_up=False)

# ▶ mpv başlat
def start_mpv(video: Path, loop: bool):
    global mpv_proc
    stop_mpv()
    if not video.exists():
        print(f"[HATA] Video bulunamadı: {video}")
        return
    args = LOOP_ARGS if loop else ONCE_ARGS
    mpv_proc = subprocess.Popen(
        [MPV_CMD, str(video), *args],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

# ▶ mpv durdur
def stop_mpv():
    global mpv_proc
    if mpv_proc and mpv_proc.poll() is None:
        mpv_proc.terminate()
        try:
            mpv_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            mpv_proc.kill()
    mpv_proc = None

# ▶ video-1 + Röle-1
def play_idle():
    status.set("🟢 video1.mp4 döngüde — Röle-1 AÇIK, Röle-2 KAPALI")
    relay2.off()
    time.sleep(0.15)          # çakışma tamponu
    relay1.on()
    start_mpv(VIDEO_IDLE, loop=True)

# ▶ video-2 + Röle-2 süreci
def handle_event():
    global playing_evt
    with lock:
        if playing_evt:
            return
        playing_evt = True

    # Röle-1 kapatılıp video-1 durdurulur
    relay1.off()
    stop_mpv()

    status.set("🔴 Cisim algılandı — video2.mp4 oynuyor")
    start_mpv(VIDEO_EVT, loop=False)
    if mpv_proc:
        mpv_proc.wait()       # video-2 biter, son kare ekranda kalır

    status.set("⚡ Röle-2 AÇIK (10 sn)")
    relay2.on()
    time.sleep(10)
    relay2.off()
    status.set("⚡ Röle-2 KAPALI")

    time.sleep(0.15)
    play_idle()
    with lock:
        playing_evt = False

# ▶ Sensör döngüsü (ilk LOW bekler, kenar tetiklemeli)
def sensor_watcher():
    last = pir.value          # ilk değeri kaydet → açılış tetiklenmez
    while True:
        cur = pir.value
        if cur and not last:  # LOW→HIGH
            threading.Thread(target=handle_event, daemon=True).start()
        last = cur
        time.sleep(0.05)

# ───── Tkinter GUI ─────
root = tk.Tk()
root.configure(bg="black")
root.attributes("-fullscreen", True)
root.attributes("-topmost", True)
root.title("Video + Röle Kontrol")

status = tk.StringVar(value="⏳ Başlatılıyor…")
tk.Label(root, textvariable=status,
         font=("DejaVu Sans", 16), fg="white", bg="black").pack(pady=30)

# Escape → çıkış
def on_close():
    stop_mpv()
    relay1.off(); relay2.off()
    root.destroy()

root.bind("<Escape>", lambda e: on_close())
root.protocol("WM_DELETE_WINDOW", on_close)

play_idle()
threading.Thread(target=sensor_watcher, daemon=True).start()
root.mainloop()
