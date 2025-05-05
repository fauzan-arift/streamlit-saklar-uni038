## 📋 Gambaran Proyek
SAKLAR adalah sistem IoT cerdas yang mengotomatisasi kontrol pencahayaan dan pendingin udara berdasarkan deteksi kehadiran manusia dan kondisi lingkungan. Sistem ini menggunakan computer vision, konektivitas IoT, dan AI untuk menciptakan solusi ruang cerdas yang efisien dan responsif.

## 👥 Informasi Tim
**Nama Tim:** INNOV8 - IPB University  
**Kode Tim:** UNI038  
**Anggota Tim:**
- Adhiya Radhin Fasya
- Fauzan Arif Tricahya
- Wandy Chandra Wijaya
- Yasir

## 🛠️ Fitur
- **Deteksi Orang**: Deteksi manusia secara real-time menggunakan model computer vision YOLOv8
- **Kontrol Pencahayaan Otomatis**: Secara otomatis menyalakan/mematikan lampu berdasarkan kehadiran manusia
- **Kontrol AC Cerdas**: Pengelolaan AC cerdas berdasarkan suhu, kehadiran orang, dan jadwal
- **Pemantauan Lingkungan**: Pelacakan suhu real-time dengan sensor DHT11
- **Sistem Penjadwalan**: Penjadwalan fleksibel untuk semua perangkat yang terhubung (harian, mingguan, atau tanggal tertentu)
- **Asisten AI**: Kontrol suara dan wawasan sistem yang didukung oleh Google Gemini
- **Konektivitas IoT**: Integrasi penuh dengan platform IoT Ubidots untuk pemantauan dan kontrol jarak jauh

## 🔧 Komponen Teknis
- Antarmuka web Streamlit
- ESP32-CAM untuk streaming video
- Model YOLOv8 untuk deteksi objek
- Google Gemini untuk kemampuan asisten AI
- Komunikasi MQTT/HTTP dengan Ubidots
- Sensor suhu DHT11

## 📊 Cara Kerja
1. Sistem menggunakan ESP32-CAM untuk streaming video ke antarmuka web
2. YOLOv8 menganalisis frame video untuk mendeteksi orang
3. Berdasarkan hasil deteksi, sistem mengendalikan pencahayaan secara otomatis
4. Data suhu dari DHT11 digunakan untuk pemantauan lingkungan
5. Sistem menyesuaikan pengaturan AC berdasarkan suhu, kehadiran orang, dan preferensi pengguna
6. Pengguna dapat mengontrol perangkat secara manual atau mengatur jadwal melalui antarmuka web
7. Asisten AI menyediakan kontrol suara dan wawasan tentang aktivitas sistem

## 🔍 Kasus Penggunaan
- Ruang kelas cerdas yang secara otomatis mengelola pencahayaan dan pendingin udara
- Ruang kantor dengan kontrol lingkungan otomatis
- Otomasi rumah hemat energi
- Ruang konferensi dengan sistem lingkungan yang responsif
