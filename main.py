#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import threading
import time
import json
import os
import socket
import atexit
from pathlib import Path

import requests
from gpiozero import DigitalInputDevice, DigitalOutputDevice

# ─── Ayarlar ───
BASE = Path("/home/cmos/Desktop")
VIDEO_IDLE = BASE / "video1.mp4"
VIDEO_EVT  = BASE / "video2.mp4"

# Ses dosyaları
SND_HELLO = BASE / "hello.mp3"
SND_MUSIC = BASE / "music.mp3"

MPV         = "/usr/bin/mpv"
SOCKET_PATH = "/tmp/mpv-socket"

GPIO_SENSOR, GPIO_R1, GPIO_R2 = 17, 27, 22
T_GAP = 0.10  # röle geçiş tamponu (sn)

# ─── Zaman parametreleri ───
RELAY_ON_DURATION = 8  # röle açıldıktan sonra ne kadar süre açık kalsın
RELAY_OFF_DELAY   = 8  # röle kapandıktan sonra ne kadar beklesin

# Röleler (aktif-LOW)
relay1 = DigitalOutputDevice(GPIO_R1, active_high=False, initial_value=False)
relay2 = DigitalOutputDevice(GPIO_R2, active_high=False, initial_value=True)

# PIR: hareket yok = HIGH, hareket var = LOW
pir = DigitalInputDevice(GPIO_SENSOR, pull_up=False)

mpv_proc    = None
playing_evt = False
lock        = threading.Lock()

# ─── Audio proses yönetimi ───
audio_procs = []
def stop_all_audio():
    global audio_procs
    for p in audio_procs:
        try: p.terminate()
        except: pass
    audio_procs = []

# ─── mpv kontrol ───
def mpv_start():
    global mpv_proc
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
    mpv_proc = subprocess.Popen([
        MPV, str(VIDEO_IDLE),
        f"--input-ipc-server={SOCKET_PATH}",
        "--fullscreen","--no-border","--ontop",
        "--force-window=yes","--really-quiet","--idle=yes"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if os.path.exists(SOCKET_PATH): break
        time.sleep(0.1)

def mpv_send(cmd: dict):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(SOCKET_PATH)
            s.sendall((json.dumps(cmd)+"\n").encode())
    except Exception as e:
        print("[mpv_send]", e)

def mpv_load(path: Path, loop: bool):
    mpv_send({"command":["loadfile", str(path), "replace"]})
    mpv_send({"command":["set_property","pause",False]})
    mpv_send({"command":["set_property","loop", "inf" if loop else "no"]})
    if not loop:
        mpv_send({"command":["set_property","keep-open","yes"]})

def mpv_quit():
    mpv_send({"command":["quit"]})

def duration(path: Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error",
            "-show_entries","format=duration",
            "-of","json", str(path)
        ], text=True)
        return float(json.loads(out)["format"]["duration"])
    except:
        return 1.0

# ─── Yardımcılar ───
def send_notification(text: str):
    token   = "<YOUR_TELEGRAM_BOT_TOKEN>"
    chat_id = "<CHAT_ID>"
    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": text})

def play_sound(file: Path):
    if file.exists():
        p = subprocess.Popen([MPV, "--no-video","--really-quiet", str(file)])
        audio_procs.append(p)
    else:
        print("Ses dosyası bulunamadı:", file)

# ─── Boş mod (idle) ───
def idle_mode():
    stop_all_audio()
    relay1.on()    # R1 LOW (açık)
    relay2.off()   # R2 HIGH (kapalı)
    mpv_load(VIDEO_IDLE, loop=True)

# ─── Olay dizisi ───
def event_sequence():
    global playing_evt
    with lock:
        if playing_evt:
            return
        playing_evt = True

    # 1) İkinci videoyu başlat
    mpv_load(VIDEO_EVT, loop=False)

    # 2) HELLO sesini hemen çal
    play_sound(SND_HELLO)

    # 3) Röleyi aç (R2 LOW)
    relay1.off(); time.sleep(T_GAP); relay2.on()

    # 4) Bildirim
    try: send_notification("Event started: playing video2")
    except Exception as e: print("Notif err:", e)

    # 5) MUSIC sesini, HELLO tamamlandıktan sonra çal
    time.sleep(duration(SND_HELLO))
    play_sound(SND_MUSIC)

    # 6) Röleyi RELAY_ON_DURATION sonra kapat
    time.sleep(RELAY_ON_DURATION)
    relay2.off(); time.sleep(T_GAP); relay1.on()

    # 7) Röle kapandıktan sonra RELAY_OFF_DELAY bekle
    time.sleep(RELAY_OFF_DELAY)

    # 8) İşlem bitince idle moda dön
    idle_mode()
    playing_evt = False

# ─── Sensör izleme ───
def sensor_loop():
    while True:
        if (not pir.is_active) and (not playing_evt):
            threading.Thread(target=event_sequence, daemon=True).start()
            while not pir.is_active:
                time.sleep(0.1)
        time.sleep(0.05)

# ─── Temiz çıkış ───
def clean_exit():
    try:
        stop_all_audio()
        relay1.off(); relay2.off()
        mpv_quit()
        if os.path.exists(SOCKET_PATH): os.remove(SOCKET_PATH)
    finally:
        exit(0)

atexit.register(clean_exit)

# ─── Başlat ───
mpv_start()
idle_mode()
threading.Thread(target=sensor_loop, daemon=True).start()

# ESC ile manuel çıkış
try:
    import tkinter as tk
    root = tk.Tk(); root.withdraw()
    root.bind("<Escape>", lambda *_: clean_exit())
    root.mainloop()
except:
    while True:
        time.sleep(1)
