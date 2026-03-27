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

MPV          = "/usr/bin/mpv"
AUDIO_PLAYER = "/usr/bin/mpg123"  # Ses çakışmasını önlemek için mpg123
SOCKET_PATH  = "/tmp/mpv-socket"

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

# ─── Süre Hesaplamaları (Sadece Sistem İlk Açıldığında 1 Kere Çalışır) ───
def duration(path: Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error",
            "-show_entries","format=duration",
            "-of","json", str(path)
        ], text=True, timeout=5)
        return float(json.loads(out)["format"]["duration"])
    except:
        return 1.0

# Videonun ve ilk sesin süresini en baştan belleğe alıyoruz
LEN_EVT   = duration(VIDEO_EVT)
LEN_HELLO = duration(SND_HELLO)

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
        try: os.remove(SOCKET_PATH)
        except: pass
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
            s.settimeout(1.0)
            s.connect(SOCKET_PATH)
            s.sendall((json.dumps(cmd)+"\n").encode())
    except Exception as e:
        pass

def mpv_load(path: Path, loop: bool):
    mpv_send({"command":["loadfile", str(path), "replace"]})
    mpv_send({"command":["set_property","pause",False]})
    mpv_send({"command":["set_property","loop", "inf" if loop else "no"]})
    if not loop:
        mpv_send({"command":["set_property","keep-open","yes"]})

def mpv_quit():
    mpv_send({"command":["quit"]})

# ─── Yardımcılar ───
def _send_telegram_async(text: str):
    """ Telegram isteğini arka planda atarak ana kodun (roleyi dondurmanın) önüne geçer """
    token   = "<YOUR_TELEGRAM_BOT_TOKEN>"
    chat_id = "<CHAT_ID>"
    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=3)
        print(f"[Bildirim Gönderildi]: {text}")
    except Exception as e:
        print(f"[Bildirim Hatası]: {e}")

def send_notification(text: str):
    # Ana işlemi meşgul etmemek için bildirimi ayrı bir Thread (iş parçacığı) ile gönder
    threading.Thread(target=_send_telegram_async, args=(text,), daemon=True).start()

def play_sound(file: Path):
    if file.exists():
        # mpg123 kullanılarak ses kanalı çakışmaları (-q = quiet formatı) önlenir
        p = subprocess.Popen([AUDIO_PLAYER, "-q", str(file)])
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

    try:
        # 1) İkinci videoyu başlat
        mpv_load(VIDEO_EVT, loop=False)

        # 2) HELLO sesini hemen çal
        play_sound(SND_HELLO)

        # 3) Röleyi aç (R2 LOW)
        relay1.off(); time.sleep(T_GAP); relay2.on()

        # 4) Senkron Olmayan Hızlı Bildirim Gönderimi (3-5 saniye takılmayı engeller)
        send_notification("Event started: playing video2")

        # 5) MUSIC sesini, önceden saniyesi hesaplanmış HELLO tamamlandıktan sonra çal
        time.sleep(LEN_HELLO)
        play_sound(SND_MUSIC)

        # 6) Röleyi RELAY_ON_DURATION sonra kapat
        time.sleep(RELAY_ON_DURATION)
        relay2.off(); time.sleep(T_GAP); relay1.on()

        # 7) Röle kapandıktan sonra RELAY_OFF_DELAY bekle
        time.sleep(RELAY_OFF_DELAY)

        # 8) Eğer ayarlanan yukarıdaki tüm süreler (hello + role1 + role2) VIDEO_EVT'den kısaysa
        # videonun aniden kesilmemesi için videonun bitiş süresine kadar beklet.
        kalan_video_suresi = LEN_EVT - (LEN_HELLO + RELAY_ON_DURATION + RELAY_OFF_DELAY)
        if kalan_video_suresi > 0:
            time.sleep(kalan_video_suresi)

    finally:
        # 9) Hata çıksa bile işlemler bitince sistemi kilitlememek için mutlaka idle'a dön ve kilidi aç
        idle_mode()
        with lock:
            playing_evt = False

# ─── Sensör izleme ───
def sensor_loop():
    while True:
        with lock:
            can_trigger = (not pir.is_active) and (not playing_evt)
            
        if can_trigger:
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
        os._exit(0)

atexit.register(clean_exit)

# ─── Başlat ───
if __name__ == "__main__":
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
