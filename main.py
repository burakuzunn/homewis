#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess, threading, time, tkinter as tk
from pathlib import Path
from gpiozero import DigitalInputDevice, DigitalOutputDevice

# ───── Dosya ve PIN Ayarları ─────
BASE_PATH   = Path("/home/cmos/Desktop")
VIDEO_IDLE  = BASE_PATH / "video1.mp4"
VIDEO_EVT   = BASE_PATH / "video2.mp4"
MPV_CMD     = "/usr/bin/mpv"  # Genellikle Raspberry Pi'de mpv bu dizindedir

SENSOR_PIN  = 17
RELAY_PIN   = 27

LOOP_ARGS = ["--loop", "--fullscreen", "--no-border",
             "--ontop", "--really-quiet", "--force-window=yes"]
ONCE_ARGS = ["--fullscreen", "--no-border",
             "--ontop", "--really-quiet", "--force-window=yes"]

# ───── Global Durumlar ─────
status      = None
mpv_proc    = None
state_lock  = threading.Lock()
playing_evt = False

# Röle ve Sensör başlat
relay = DigitalOutputDevice(RELAY_PIN, active_high=True, initial_value=False)
pir   = DigitalInputDevice(SENSOR_PIN, pull_up=False)

# ▶ mpv video oynatıcı başlat
def start_mpv(video: Path, loop: bool):
    global mpv_proc
    stop_mpv()
    args = LOOP_ARGS if loop else ONCE_ARGS
    if not video.exists():
        print(f"[HATA] Video dosyası bulunamadı: {video}")
        return
    mpv_proc = subprocess.Popen(
        [MPV_CMD, str(video), *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

# ▶ mpv video durdur
def stop_mpv():
    global mpv_proc
    if mpv_proc and mpv_proc.poll() is None:
        mpv_proc.terminate()
        try:
            mpv_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            mpv_proc.kill()
    mpv_proc = None

# ▶ Bekleme videosu
def play_idle():
    status.set("🟢 Bekleme: video1.mp4 döngüde")
    start_mpv(VIDEO_IDLE, loop=True)

# ▶ Olay videosu ve röle tetikleme
def handle_event():
    global playing_evt
    with state_lock:
        if playing_evt:
            return
        playing_evt = True

    status.set("🔴 Hareket: video2.mp4 oynatılıyor")
    start_mpv(VIDEO_EVT, loop=False)

    if mpv_proc:
        mpv_proc.wait()

    status.set("⚡ Röle ON (10 s)")
    relay.on()
    time.sleep(10)
    relay.off()
    status.set("⚡ Röle OFF")

    play_idle()
    with state_lock:
        playing_evt = False

# ▶ Sensör izleme döngüsü
def sensor_watcher():
    while True:
        pir.wait_for_active()
        threading.Thread(target=handle_event, daemon=True).start()
        time.sleep(0.2)

# ───── Tkinter GUI Arayüzü ─────
root = tk.Tk()
root.configure(bg="black")
root.attributes("-fullscreen", True)
root.attributes("-topmost", True)
root.title("Video + Röle Kontrol")

status = tk.StringVar(value="⏳ Başlatılıyor…")
tk.Label(root, textvariable=status,
         font=("DejaVu Sans", 16), fg="white", bg="black").pack(pady=30)

# Başlangıç videoyu başlat
play_idle()
# Sensör dinleyicisini başlat
threading.Thread(target=sensor_watcher, daemon=True).start()

def on_close():
    stop_mpv()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()
