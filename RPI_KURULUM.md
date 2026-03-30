# Homewis - Raspberry Pi Tam Kurulum Rehberi

Bu rehber, baska bir Raspberry Pi cihazda projeyi tek seferde kurup otomatik calisacak hale getirmek icin hazirlandi.
Hedef: cihaz acilsin -> servis otomatik baslasin -> video/sensor/role/ses sistemi stabil calissin.

Varsayimlar:
- Raspberry Pi OS (Bookworm) kurulu
- Kullanici adi `cmos`
- Proje yolu: `/home/cmos/Desktop/homewis`

---

## 1) Sistem paketleri

```bash
sudo apt update
sudo apt install -y \
  mpv ffmpeg mpg123 \
  python3-gpiozero python3-requests \
  git curl
```

Istege bagli ama faydali:
```bash
sudo apt install -y alsa-utils
```

---

## 2) Projeyi klonla / guncelle

```bash
mkdir -p /home/cmos/Desktop
cd /home/cmos/Desktop

# Ilk kurulum
git clone https://github.com/burakuzunn/homewis.git

# Guncelleme
cd /home/cmos/Desktop/homewis
git pull
```

Sahiplik/izin:
```bash
sudo chown -R cmos:cmos /home/cmos/Desktop/homewis
chmod +x /home/cmos/Desktop/homewis/start
```

### 2.1) Repo key (SSH) ile erisim - onerilen

Yeni RPi cihazda private/public repo erisimi icin en temiz yontem SSH key kullanmaktir.

1) Cihazda key uret:
```bash
ssh-keygen -t ed25519 -C "homewis-rpi" -f /home/cmos/.ssh/homewis_rpi -N ""
```

2) Public key'i gor:
```bash
cat /home/cmos/.ssh/homewis_rpi.pub
```

3) GitHub tarafinda ekle:
- Sadece bu repo icin: **Deploy key** (Read-only veya Read/Write)
- Hesap genelinde: **SSH key**

4) SSH config yaz:
```bash
cat > /home/cmos/.ssh/config <<'EOF'
Host github-homewis
  HostName github.com
  User git
  IdentityFile /home/cmos/.ssh/homewis_rpi
  IdentitiesOnly yes
EOF
chmod 600 /home/cmos/.ssh/config
```

5) Repo remote'unu SSH'e cevir:
```bash
cd /home/cmos/Desktop/homewis
git remote set-url origin git@github-homewis:burakuzunn/homewis.git
git remote -v
```

6) Test:
```bash
ssh -T git@github-homewis
git -C /home/cmos/Desktop/homewis pull
```

> Not:
> - Private key dosyasi: `/home/cmos/.ssh/homewis_rpi`
> - Bu dosya kesinlikle repoya konulmaz, paylasilmaz.
> - `git remote -v` cikisinda token/PAT gozukecek sekilde URL kullanma.

---

## 3) Medya dosyalari kontrolu

Asagidaki dosyalar proje klasorunde olmalı:
- `main.py`
- `video1-edit.mp4`
- `video2-edit.mp4`
- `hello.mp3`
- `music.mp3`

Kontrol:
```bash
ls -lh /home/cmos/Desktop/homewis
```

---

## 4) GPIO ve role pinleri (guncel yapi)

`main.py` icindeki guncel pin/plani:
- PIR sensor: `GPIO 17`
- Grup A roleler: `GPIO 27` (R1), `GPIO 22` (R2)
- Grup B roleler: `GPIO 23` (R3), `GPIO 24` (R4)

Role guvenlik mantigi:
- Sadece `1+2` birlikte acilir **veya** `3+4` birlikte acilir
- Iki grup ayni anda acilamaz
- Her geciste once hepsi kapanir, kisa bekleme (`T_GAP`) sonra hedef grup acilir

> Donanim notu: role kartin pin baglantin farkliysa sadece `GPIO_R1..GPIO_R4` degerlerini degistir.

---

## 5) Ses cikisi ayari (hoparlor)

Kod acilista uygun ALSA cihazi secmeye calisir. Gerekirse elle sabitle:

1) Cihazlari listele:
```bash
aplay -L
```

2) Servise ses cihazini tanimla (ornek):
```bash
sudo systemctl edit homewis-kiosk.service
```
Acilan dosyaya ekle:
```ini
[Service]
Environment=AUDIO_DEVICE=default:CARD=Headphones
```
Sonra:
```bash
sudo systemctl daemon-reload
sudo systemctl restart homewis-kiosk.service
```

Ses testi:
```bash
speaker-test -c 2 -t wav -D default
```

---

## 6) Boot ve video donmama (DRM/KMS) ayarlari

`mpv` DRM uzerinden calisiyor (`--vo=drm`, `--gpu-context=drm`), bu nedenle KMS aktif olmali.

`/boot/firmware/config.txt` (bazı sistemlerde `/boot/config.txt`) icinde su satirlarin oldugunu kontrol et:
```ini
dtoverlay=vc4-kms-v3d
max_framebuffers=2
```

GPU bellegi dusukse akicilik bozulabilir. Ornek:
```ini
gpu_mem=128
```

Degisiklikten sonra reboot:
```bash
sudo reboot
```

---

## 7) Systemd servisini olustur (en kritik adim)

`/etc/systemd/system/homewis-kiosk.service` dosyasini su icerikle olustur:

```ini
[Unit]
Description=Homewis DRM kiosk player
After=multi-user.target sound.target
Wants=multi-user.target

[Service]
Type=simple
User=cmos
Group=cmos
SupplementaryGroups=video render audio input
WorkingDirectory=/home/cmos/Desktop/homewis
Environment=HOME=/home/cmos
Environment=HOMEWIS_PROFILE=ultra
Environment=HOMEWIS_RENDER_TARGET=drm
Environment=PYTHONUNBUFFERED=1
StandardInput=null
ExecStart=/usr/bin/python3 /home/cmos/Desktop/homewis/main.py
Restart=always
RestartSec=2
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Etkinlestir:
```bash
sudo systemctl daemon-reload
sudo systemctl enable homewis-kiosk.service
sudo systemctl restart homewis-kiosk.service
```

Durum:
```bash
systemctl --no-pager --full status homewis-kiosk.service
```

---

## 8) Tek komutla restart / deploy

Projedeki `start` scripti eski processleri temizleyip servisi yeniden baslatir:
```bash
cd /home/cmos/Desktop/homewis
./start
```

---

## 9) Dogrulama checklisti

1. Cihaz acildiginda servis otomatik kalkiyor mu?
2. `video1-edit.mp4` loop sorunsuz mu?
3. Sensor tetiklenince `video2-edit.mp4` basliyor mu?
4. `video2` oynarken ikinci tetikleme gelmiyor mu?
5. Roleler grup mantiginda mi?
   - ya `1+2`
   - ya `3+4`
   - ikisi birden asla degil
6. Ses dosyalari (`hello.mp3`, `music.mp3`) dogru cikiyor mu?

---

## 10) Sorun giderme (hizli)

### Servis durumu / log
```bash
systemctl --no-pager --full status homewis-kiosk.service
sudo journalctl -u homewis-kiosk.service -n 200 --no-pager
```

### Canli log
```bash
sudo journalctl -u homewis-kiosk.service -f
```

### mpv soket/kalinti temizligi
```bash
sudo pkill -f "/home/cmos/Desktop/homewis/main.py" || true
sudo pkill -f "/usr/bin/mpv .*--input-ipc-server=/tmp/mpv-socket" || true
sudo pkill -x mpg123 || true
sudo rm -f /tmp/mpv-socket
```

### GPIO busy
Genelde ayni scriptin ikinci kopyasi calisiyordur. Once eski processleri oldur, sonra `./start`.

### Siyah ekran / video takilmasi
- `dtoverlay=vc4-kms-v3d` aktif mi kontrol et
- video dosyalari yerinde mi kontrol et
- `journalctl` ve `/tmp/homewis_mpv.log` kontrol et
- SD kart yavas ise medya dosyalarini hizli karta tasimayi dusun

---

## 11) Son notlar

- Kod mpv IPC icin `/tmp/mpv-socket` kullanir.
- `main.py` icinde event kilidi vardir; event oynarken yeni event baslatmaz.
- Role gecisleri yazilim seviyesinde kilitli (interlock) calisir.
