#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess, threading, time, tkinter as tk
from pathlib import Path
from gpiozero import DigitalInputDevice, DigitalOutputDevice

# ───── Dosya ve PIN Ayarları ─────
BASE_PATH   = Path("/home/cmos/Desktop")
VIDEO_IDLE  = BASE_PATH / "video1.mp4"
VIDEO_EVT   = BASE_PATH / "video2.mp4"
MPV_CMD     = "/usr/bin/mpv"  # mpv yolu

SENSOR_PIN  = 17
RELAY1_PIN  = 27  # Röle 1 – video1 oynarken açık
RELAY2_PIN  = 22  # Röle 2 – video2 bittikten sonra 10 sn açık

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
relay1 = DigitalOutputDevice(RELAY1_PIN, active_high=True, initial_value=False)
relay2 = DigitalOutputDevice(RELAY2_PIN, active_high=True, initial_value=False)
pir    = DigitalInputDevice(SENSOR_PIN, pull_up=False)

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

# ▶ Bekleme videosu + röle1 açık
def play_idle():
    status.set("🟢 Bekleme: video1.mp4 döngüde, Röle1 açık")
    relay2.off()  # Her ihtimale karşı
    relay1.on()
    start_mpv(VIDEO_IDLE, loop=True)

# ▶ Olay videosu + röle2 süreci
def handle_event():
    global playing_evt
    with state_lock:
        if playing_evt:
            return
        playing_evt = True

    # Röle1'i kapat, video1'i durdur
    status.set("🔄 Geçiş: Röle1 kapatılıyor")
    relay1.off()
    stop_mpv()

    # Video2 oynat
    status.set("🔴 Hareket algılandı: video2.mp4 oynatılıyor")
    start_mpv(VIDEO_EVT, loop=False)
    if mpv_proc:
        mpv_proc.wait()

    # Röle2'yi 10 sn çalıştır
    status.set("⚡ Röle2 ON (10 sn)")
    relay2.on()
    time.sleep(10)
    relay2.off()
    status.set("⚡ Röle2 OFF")

    # Başa dön
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

# Başlangıçta video1 ve röle1 aktif
play_idle()

# Sensör izleyici başlat
threading.Thread(target=sensor_watcher, daemon=True).start()

def on_close():
    stop_mpv()
    relay1.off()
    relay2.off()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()
