// IR sensör pini (E18-D80NK)
const int sensorPin = 2;

// Röle pinleri (aktif LOW)
const int relay1 = 7;  // Cisim ALGILANDI → aktif
const int relay2 = 8;  // Cisim YOK → aktif

void setup() {
  Serial.begin(9600);

  pinMode(sensorPin, INPUT);
  pinMode(relay1, OUTPUT);
  pinMode(relay2, OUTPUT);

  // Röleler başlangıçta PASİF (HIGH)
  digitalWrite(relay1, HIGH);
  digitalWrite(relay2, HIGH);

  Serial.println("IR sensör ile kontrol başladı.");
}

void loop() {
  int sensorValue = digitalRead(sensorPin);

  if (sensorValue == LOW) {
    // Cisim ALGILANDI → Röle1 aktif, Röle2 pasif
    digitalWrite(relay1, LOW);   // çalıştır
    digitalWrite(relay2, HIGH);  // durdur
    Serial.println("→ Cisim ALGILANDI → Röle1 ON");
  } else {
    // Cisim YOK → Röle2 aktif, Röle1 pasif
    digitalWrite(relay1, HIGH);  // durdur
    digitalWrite(relay2, LOW);   // çalıştır
    Serial.println("← Cisim YOK → Röle2 ON");
  }

  // Güvenlik: İki röle aynı anda aktifse kapat
  if (digitalRead(relay1) == LOW && digitalRead(relay2) == LOW) {
    Serial.println("⚠️ HATA: Her iki röle aktif! Kapatılıyor.");
    digitalWrite(relay1, HIGH);
    digitalWrite(relay2, HIGH);
  }

  delay(300);
}
