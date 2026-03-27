# AI Agent Kurulum Görevi: RPi Kiosk Sistemi

## Görev Özeti
Hedef sistem, kullanıcı adı `cmos` olan ve işletim sistemi (Raspberry Pi OS Desktop) kurulmuş bir Raspberry Pi'dir. Görevin senin (AI Agent) tarafından SSH veya doğrudan terminal üzerinden tek seferde yapılandırılması beklenmektedir.

Lütfen aşağıdaki adımları sırasıyla terminal üzerinde çalıştırarak kurulumu tamamla:

---

### ADIM 1: Gerekli Paketlerin Kurulumu
Aşağıdaki komutları çalıştırarak depo önbelleğini güncelle ve bağımlılıkları (`mpv`, `ffmpeg`, `gpiozero`, `mpg123`) kur:
```bash
sudo apt update
sudo apt install -y mpv ffmpeg python3-gpiozero mpg123
```

### ADIM 2: Dizin Kontrolü ve Dosyaların Konumlandırılması
Ana dizin `/home/cmos/Desktop` olmalıdır. Klasör hazır değilse oluştur.
```bash
mkdir -p /home/cmos/Desktop
cd /home/cmos/Desktop
```
**Aksiyon:** Kod içeriğini içeren `main.py` dosyasını ile beraber `video1.mp4` ve `video2.mp4` medya dosyalarını bu klasöre (`/home/cmos/Desktop`) aktar veya oluştur.

### ADIM 3: İzinlerin Ayarlanması
Dosyaların çalıştırılabilir olduğundan ve doğru kullanıcı yetkilerine sahip olduğundan emin ol:
```bash
chmod +x /home/cmos/Desktop/main.py
sudo chown -R cmos:cmos /home/cmos/Desktop/
```

### ADIM 4: Otomatik Başlatma (Auto-Start) Yapılandırması
Sistemin elektrik geldiğinde masaüstü açılır açılmaz komut dosyasını otomatik başlatması için RPi standart `.desktop` autostart yöntemini kullan. Aşağıdaki komut bloğunu doğrudan çalıştırarak autostart dosyasını yarat:

```bash
mkdir -p /home/cmos/.config/autostart

cat << 'EOF' > /home/cmos/.config/autostart/kiosk_startup.desktop
[Desktop Entry]
Type=Application
Name=Homewis Kiosk AutoStart
Exec=/usr/bin/python3 /home/cmos/Desktop/main.py
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

sudo chown -R cmos:cmos /home/cmos/.config/autostart
```
*(Not: Raspberry Pi OS Wayland veya X11 fark etmeksizin standart Desktop Entry yöntemi arka planda arayüz ayağa kalktığında Python scriptini tetikleyecektir.)*

### ADIM 5: Sistemi Yeniden Başlatma
Tüm yapılandırmalar bittiğinde test etmek için cihazı yeniden başlat:
```bash
sudo reboot
```

---
**Agent Notu:** Kod içerisinde `/tmp/mpv-socket` oluşturulacağı ve donanım pinleri (PIR: 17, R1: 27, R2: 22) kullanılacağı için herhangi bir donanım yetkisi sorunu yaşanırsa kullanıcıyı bilgilendir. İşlemleri tamamladığında durumu raporla.
