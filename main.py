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

import requests                     # for send_notification()
from gpiozero import DigitalInputDevice, DigitalOutputDevice

# ─── Ayarlar ───
BASE = Path("/home/cmos/Desktop")
VIDEO_IDLE = BASE / "video1.mp4"
VIDEO_EVT  = BASE / "video2.mp4"

# Ses dosyaları (aynı klasörde hello.mp3 ve music.mp3 olsun)
SND_HELLO = BASE / "hello.mp3"
SND_MUSIC = BASE / "music.mp3"

MPV = "/usr/bin/mpv"
SOCKET_PATH = "/tmp/mpv-socket"

GPIO_SENSOR, GPIO_R1, GPIO_R2 = 17, 27, 22      # BCM numaraları
T_GAP = 0.10                                    # röle geçiş tamponu (sn)

# Röleler aktif-LOW
relay1 = DigitalOutputDevice(GPIO_R1, active_high=False, initial_value=False)  # LOW = çekik (açık)
relay2 = DigitalOutputDevice(GPIO_R2, active_high=False, initial_value=True)   # HIGH = serbest (kapalı)

# PIR: “hareket yok = HIGH”, “hareket var = LOW”
pir = DigitalInputDevice(GPIO_SENSOR, pull_up=False)

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
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "json", str(path)],
            text=True)
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return 1.0

LEN_EVT = duration(VIDEO_EVT)

# ─── Röle geçişi ───
def switch_relays(active: str):
    if active == "R1":                               # video-1 süresince
        relay2.off(); time.sleep(T_GAP); relay1.on()
    else:                                            # video-2 + 10 sn
        relay1.off(); time.sleep(T_GAP); relay2.on()

# ─── Yardımcılar ───
def send_notification(text: str):
    """
    Örnek: Telegram Bot API kullanarak mesaj gönderme.
    Token ve chat_id değerlerini kendinize göre ayarlayın.
    """
    token = "<YOUR_TELEGRAM_BOT_TOKEN>"
    chat_id = "<CHAT_ID>"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": text})

def play_sound_sequence(files):
    """
    Dosyaları sırayla oynatır (bloklayarak).
    mpv kullanıyor; başka bir kütüphane tercih ederseniz değiştirebilirsiniz.
    """
    for f in files:
        if f.exists():
            subprocess.run([MPV, "--no-video", "--really-quiet", str(f)])
        else:
            print("Ses dosyası bulunamadı:", f)

# ─── Senaryo akışı ───
def idle_mode():
    switch_relays("R1")              # R1 LOW, R2 HIGH
    mpv_load(VIDEO_IDLE, loop=True)

def event_sequence():
    global playing_evt
    with lock:
        if playing_evt:
            return
        playing_evt = True

    # 1) Etkinlik başladığında hemen mesaj gönder
    try:
        send_notification("Event started: playing video2")
    except Exception as e:
        print("Notification failed:", e)

    # 2) İki ses dosyasını sırayla çal
    play_sound_sequence([SND_HELLO, SND_MUSIC])

    # 3) Olay videosunu başlat
    mpv_load(VIDEO_EVT, loop=False)
    time.sleep(LEN_EVT)              # video-2 süresi

    # 4) Röle2'yi 10 saniye aktif et
    switch_relays("R2")
    time.sleep(10)

    # 5) Yeniden boş moduna dön
    idle_mode()
    with lock:
        playing_evt = False

# ─── Sensör izleme ───
def sensor_loop():
    while True:
        # LOW = hareket var, ve henüz oynatılmıyorsa
        if (not pir.is_active) and (not playing_evt):
            threading.Thread(target=event_sequence, daemon=True).start()
            # kişi sensör alanındayken yeniden tetikleme yapma
            while not pir.is_active:
                time.sleep(0.1)
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

# ESC ile çıkış (isteğe bağlı GUI)
try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.bind("<Escape>", lambda *_: clean_exit())
    root.mainloop()
except:
    while True:
        time.sleep(1)
