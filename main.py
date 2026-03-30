#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import threading
import time
import json
import os
import socket
import atexit
import shutil
import signal
from pathlib import Path

import requests
from gpiozero import DigitalInputDevice, DigitalOutputDevice

# ─── Ayarlar ───
BASE = Path("/home/cmos/Desktop/homewis")
VIDEO_IDLE = BASE / "video1-edit.mp4"
VIDEO_EVT  = BASE / "video2-edit.mp4"
RAM_BASE   = Path("/dev/shm")

# Ses dosyaları
SND_HELLO = BASE / "hello.mp3"
SND_MUSIC = BASE / "music.mp3"

MPV          = "/usr/bin/mpv"
AUDIO_PLAYER = "/usr/bin/mpg123"  # Birincil ses oynatıcı (varsa)
SOCKET_PATH  = "/tmp/mpv-socket"

GPIO_SENSOR = 17
GPIO_R1, GPIO_R2 = 27, 22
# 4'lü röleye geçiş için ikinci grup pinleri.
# Gerekirse bu pinleri kart bağlantına göre değiştir.
GPIO_R3, GPIO_R4 = 23, 24
T_GAP = 0.10  # röle geçiş tamponu (sn)

# ─── Zaman parametreleri ───
RELAY_ON_DURATION = 8  # röle açıldıktan sonra ne kadar süre açık kalsın
RELAY_OFF_DELAY   = 8  # röle kapandıktan sonra ne kadar beklesin

# Röleler (aktif-LOW)
relay1 = DigitalOutputDevice(GPIO_R1, active_high=False, initial_value=False)
relay2 = DigitalOutputDevice(GPIO_R2, active_high=False, initial_value=True)
relay3 = DigitalOutputDevice(GPIO_R3, active_high=False, initial_value=True)
relay4 = DigitalOutputDevice(GPIO_R4, active_high=False, initial_value=True)

# PIR: hareket yok = HIGH, hareket var = LOW
pir = DigitalInputDevice(GPIO_SENSOR, pull_up=False)

mpv_proc    = None
playing_evt = False
lock        = threading.Lock()
relay_lock  = threading.Lock()
active_video = "idle"
AUDIO_DEVICE = os.environ.get("AUDIO_DEVICE", "").strip()

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

def detect_audio_device() -> str:
    """
    ALSA çıkış cihazını seç.
    Öncelik: env(AUDIO_DEVICE) > Headphones kartı > default
    """
    if AUDIO_DEVICE:
        return AUDIO_DEVICE
    try:
        out = subprocess.check_output(["aplay", "-L"], text=True, timeout=3)
        if "default:CARD=Headphones" in out:
            return "default:CARD=Headphones"
        if "plughw:CARD=Headphones,DEV=0" in out:
            return "plughw:CARD=Headphones,DEV=0"
    except Exception:
        pass
    return "default"

AUDIO_DEVICE = detect_audio_device()

def set_system_volume_max():
    """
    ALSA ses seviyesini açılışta maksimuma çek.
    Bazı cihazlarda 'PCM' kontrolü aktif olduğu için önce onu dener.
    """
    candidates = []
    if AUDIO_DEVICE:
        candidates.append(["amixer", "-D", AUDIO_DEVICE, "sset", "PCM", "100%"])
    candidates.extend([
        ["amixer", "-c", "Headphones", "sset", "PCM", "100%"],
        ["amixer", "-D", "default", "sset", "PCM", "100%"],
    ])
    for cmd in candidates:
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=2)
            return
        except Exception:
            pass

def maybe_stage_to_ram(src: Path) -> Path:
    """
    Yeterli alan varsa videoyu /dev/shm'ye al.
    Böylece SD kart I/O jitter'i azalır, akıcılık artar.
    """
    try:
        if not src.exists() or not RAM_BASE.exists():
            return src
        target = RAM_BASE / src.name
        stat = os.statvfs(str(RAM_BASE))
        free_bytes = stat.f_frsize * stat.f_bavail
        src_size = src.stat().st_size
        # Bir miktar boşluk payı bırak.
        if free_bytes < src_size + 20 * 1024 * 1024:
            return src
        # Hedef dosya yoksa veya boyutu farklıysa kopyala.
        if (not target.exists()) or (target.stat().st_size != src_size):
            shutil.copy2(src, target)
        return target
    except Exception:
        return src

VIDEO_IDLE_PLAY = maybe_stage_to_ram(VIDEO_IDLE)
VIDEO_EVT_PLAY  = maybe_stage_to_ram(VIDEO_EVT)

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
    # Eski oturumlardan kalmış mpv süreçleri görüntü almayı engelleyebilir.
    subprocess.run(
        ["pkill", "-f", f"/usr/bin/mpv .*--input-ipc-server={SOCKET_PATH}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if os.path.exists(SOCKET_PATH):
        try: os.remove(SOCKET_PATH)
        except: pass
    popen_cmd = [
        MPV, str(VIDEO_IDLE_PLAY),
        f"--input-ipc-server={SOCKET_PATH}",
        "--fullscreen",
        "--osc=no",
        "--osd-level=0",
        "--vo=drm",
        "--gpu-context=drm",
        "--force-window=yes",
        "--really-quiet",
        "--idle=yes",
        "--no-audio",
        "--hwdec=v4l2m2m-copy",
        "--vd-lavc-threads=2",
        "--framedrop=decoder",
        "--video-sync=display-vdrop",
        "--interpolation=no",
        "--cache=yes",
        "--demuxer-max-bytes=64MiB",
        "--demuxer-max-back-bytes=32MiB",
        "--scale=bilinear",
        "--cscale=bilinear",
        "--dscale=bilinear"
    ]
    logf = open("/tmp/homewis_mpv.log", "ab", buffering=0)
    mpv_proc = subprocess.Popen(popen_cmd, stdout=logf, stderr=logf)
    for _ in range(30):
        if mpv_proc.poll() is not None:
            print(f"[Hata] mpv erken kapandi. kod={mpv_proc.returncode}")
            break
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

def mpv_request(cmd: dict, timeout: float = 1.0):
    """
    mpv IPC'den cevap bekleyen komut gönderimi.
    """
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(SOCKET_PATH)
            s.sendall((json.dumps(cmd) + "\n").encode())
            data = s.recv(8192).decode(errors="ignore").strip()
            if not data:
                return None
            return json.loads(data)
    except Exception:
        return None

def mpv_get_property(name: str):
    resp = mpv_request({"command": ["get_property", name]}, timeout=1.0)
    if isinstance(resp, dict) and resp.get("error") == "success":
        return resp.get("data")
    return None

def mpv_load(path: Path, loop: bool):
    global active_video
    mpv_send({"command":["loadfile", str(path), "replace"]})
    mpv_send({"command":["set_property","pause",False]})
    # loop-file dosya bazlı döngüdür; "loop" playlist seviyesidir.
    mpv_send({"command":["set_property","loop-file", "inf" if loop else "no"]})
    mpv_send({"command":["set_property","keep-open","no" if not loop else "yes"]})
    active_video = "idle" if loop else "event"

def wait_until_event_video_finishes(event_path: Path, max_wait: float = 7200.0):
    """
    Event videosu gerçekten bitene kadar bekler.
    ffprobe süresine bağımlı kalmamak için mpv'nin canlı durumunu izler.
    """
    started = time.monotonic()
    wanted = str(event_path)
    while (time.monotonic() - started) < max_wait:
        # EOF'e düşmüşse event oynatma bitmiştir.
        eof_reached = mpv_get_property("eof-reached")
        if eof_reached is True:
            return True

        # keep-open=no olduğunda EOF sonrası mpv idle-active olur.
        idle_active = mpv_get_property("idle-active")
        if idle_active is True:
            return True

        # O an başka dosya yüklenmişse event kapanmış/bitmiş kabul et.
        current_path = mpv_get_property("path")
        if current_path and str(current_path) != wanted:
            return True

        time.sleep(0.2)
    return False

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
    global AUDIO_PLAYER
    if file.exists():
        cmd = None

        # 1) mpg123 (varsa) ALSA default cihazına yönlendir.
        if AUDIO_PLAYER and Path(AUDIO_PLAYER).exists():
            cmd = [AUDIO_PLAYER, "-q", "-o", "alsa", "-a", AUDIO_DEVICE, str(file)]
        # 2) mpv fallback
        elif Path(MPV).exists():
            cmd = [MPV, "--no-video", "--really-quiet", "--ao=alsa", "--volume=100", f"--audio-device=alsa/{AUDIO_DEVICE}", str(file)]
        # 3) sistem path'te mpg123 fallback
        elif shutil.which("mpg123"):
            AUDIO_PLAYER = shutil.which("mpg123")
            cmd = [AUDIO_PLAYER, "-q", "-o", "alsa", "-a", AUDIO_DEVICE, str(file)]

        if cmd is None:
            print("[Hata] Ses oynatıcı bulunamadı (mpg123/mpv).")
            return

        p = subprocess.Popen(cmd)
        audio_procs.append(p)
    else:
        print("Ses dosyası bulunamadı:", file)

def set_relay_groups(group_a_on: bool, group_b_on: bool):
    """
    4'lü röleyi 2'li grup şeklinde yönet:
    - Grup A: relay1 + relay2
    - Grup B: relay3 + relay4
    İki grubun aynı anda ON olmasına izin vermez.
    """
    if group_a_on and group_b_on:
        raise ValueError("Grup A ve Grup B aynı anda ON olamaz")

    with relay_lock:
        # Önce hepsini OFF yap, sonra sadece hedef grubu aç.
        relay1.off()
        relay2.off()
        relay3.off()
        relay4.off()
        time.sleep(T_GAP)
        if group_a_on:
            relay1.on()
            relay2.on()
        elif group_b_on:
            relay3.on()
            relay4.on()

# ─── Boş mod (idle) ───
def idle_mode():
    stop_all_audio()
    set_relay_groups(group_a_on=True, group_b_on=False)
    mpv_load(VIDEO_IDLE_PLAY, loop=True)

# ─── Olay dizisi ───
def event_sequence():
    global playing_evt
    try:
        # 1) İkinci videoyu başlat
        mpv_load(VIDEO_EVT_PLAY, loop=False)

        # 2) HELLO sesini hemen çal
        try:
            play_sound(SND_HELLO)
        except Exception as e:
            print(f"[Uyari] HELLO sesi başlatılamadı: {e}")

        # 3) Röleyi aç (R2 LOW)
        try:
            set_relay_groups(group_a_on=False, group_b_on=True)
        except Exception as e:
            print(f"[Uyari] Röle açma hatası: {e}")

        # 4) Senkron Olmayan Hızlı Bildirim Gönderimi (3-5 saniye takılmayı engeller)
        try:
            send_notification("Event started: playing video2")
        except Exception as e:
            print(f"[Uyari] Bildirim hatası: {e}")

        # 5) MUSIC sesini, önceden saniyesi hesaplanmış HELLO tamamlandıktan sonra çal
        time.sleep(LEN_HELLO)
        try:
            play_sound(SND_MUSIC)
        except Exception as e:
            print(f"[Uyari] MUSIC sesi başlatılamadı: {e}")

        # 6) Röleyi RELAY_ON_DURATION sonra kapat
        time.sleep(RELAY_ON_DURATION)
        try:
            set_relay_groups(group_a_on=True, group_b_on=False)
        except Exception as e:
            print(f"[Uyari] Röle kapama hatası: {e}")

        # 7) Röle kapandıktan sonra RELAY_OFF_DELAY bekle
        time.sleep(RELAY_OFF_DELAY)

        # 8) Event videosunu gerçekten bitene kadar beklet.
        # ffprobe süresi hatalı olsa bile bu adım erken idle'a dönmez.
        wait_until_event_video_finishes(VIDEO_EVT_PLAY)

    except Exception as e:
        print(f"[Hata] event_sequence beklenmeyen hata: {e}")
    finally:
        # 9) Hata çıksa bile işlemler bitince sistemi kilitlememek için mutlaka idle'a dön ve kilidi aç
        idle_mode()
        with lock:
            playing_evt = False

# ─── Sensör izleme ───
def sensor_loop():
    global playing_evt

    # Açılışta PIR hattının stabilize olması için kısa bekleme.
    time.sleep(1.0)

    # Sistemi sadece "hareket yok" durumunu gördükten sonra arm et.
    # Böylece boot anındaki düşük seviye yanlış tetik üretmez.
    armed = pir.is_active
    prev_motion = (not pir.is_active)

    while True:
        motion_now = (not pir.is_active)  # PIR LOW => hareket var

        with lock:
            if (not armed) and (not motion_now):
                armed = True

            # Sadece yükselen kenarda (hareket yok -> hareket var) tetikle
            # ve tetiklemeden önce playing_evt'yi burada işaretle.
            can_trigger = armed and motion_now and (not prev_motion) and (not playing_evt)
            if can_trigger:
                playing_evt = True

        if can_trigger:
            threading.Thread(target=event_sequence, daemon=True).start()

        prev_motion = motion_now
        time.sleep(0.05)

# ─── Temiz çıkış ───
def clean_exit():
    try:
        stop_all_audio()
        set_relay_groups(group_a_on=False, group_b_on=False)
        mpv_quit()
        if os.path.exists(SOCKET_PATH): os.remove(SOCKET_PATH)
    finally:
        os._exit(0)

atexit.register(clean_exit)

# ─── Başlat ───
if __name__ == "__main__":
    # Servis altında istenmeyen SIGINT darbeleri süreci düşürmesin.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, lambda *_: clean_exit())

    set_system_volume_max()
    mpv_start()
    idle_mode()
    threading.Thread(target=sensor_loop, daemon=True).start()

    # GUI varsa ESC ile manuel çıkış; headless modda sonsuz döngüde bekle.
    if os.environ.get("DISPLAY"):
        try:
            import tkinter as tk
            root = tk.Tk(); root.withdraw()
            root.bind("<Escape>", lambda *_: clean_exit())
            root.mainloop()
        except Exception:
            while True:
                time.sleep(1)
    else:
        while True:
            time.sleep(1)
