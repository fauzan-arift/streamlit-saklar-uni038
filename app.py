import streamlit as st
import cv2
import time
import json
import requests
import numpy as np
import paho.mqtt.client as mqtt
from ultralytics import YOLO
import google.generativeai as genai  
import datetime 
import socket 

# === Konfigurasi Ubidots ===
UBIDOTS_TOKEN = st.secrets["UBIDOTS_TOKEN"]
DEVICE_LABEL = st.secrets["DEVICE_LABEL"]
VARIABLE_CAMERA = st.secrets["VARIABLE_CAMERA"]
VARIABLE_LIGHT = st.secrets["VARIABLE_LIGHT"]
VARIABLE_COUNT = st.secrets["VARIABLE_COUNT"]
VARIABLE_AC = st.secrets["VARIABLE_AC"]
VARIABLE_TEMPERATURE = st.secrets["VARIABLE_TEMPERATURE"]
VARIABLE_DHT11 = st.secrets["VARIABLE_DHT11"]

BROKER = st.secrets["BROKER"]
PORT = int(st.secrets["PORT"])

# === Gemini API Configuration ===
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)

# === Init State ===
st.session_state.setdefault("log", [])
st.session_state.setdefault("camera_on", False)
st.session_state.setdefault("lamp", 0)
st.session_state.setdefault("count", 0)
st.session_state.setdefault("last_sent", 0)
st.session_state.setdefault("camera_option", "ESP32-CAM")  # Ubah default ke ESP32-CAM
st.session_state.setdefault("esp32_url", "")
st.session_state.setdefault("stop_clicks", 0)
st.session_state.setdefault("activity_history", [])
st.session_state.setdefault("chat_history", [])
st.session_state.setdefault("ai_enabled", False)
st.session_state.setdefault("ac_power", 0)
st.session_state.setdefault("ac_temperature", 25)
st.session_state.setdefault("current_temperature", 25.60)
st.session_state.setdefault("schedules", {
    "ac": {"enabled": False, "on_time": "07:00", "off_time": "22:00", "days": ["Sen", "Sel", "Rab", "Kam", "Jum"], "date_specific": False, "specific_date": None},
    "light": {"enabled": False, "on_time": "18:00", "off_time": "06:00", "days": ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"], "date_specific": False, "specific_date": None}
})
st.session_state.setdefault("last_dht11_read", 0)
st.session_state.setdefault("auto_ac_enabled", False)
st.session_state.setdefault("auto_ac_temp_threshold", 27.0)  # Suhu ambang batas untuk menyalakan AC
st.session_state.setdefault("auto_ac_people_threshold", 1)   # Minimal jumlah orang untuk menyalakan AC
st.session_state.setdefault("auto_ac_empty_delay", 5)        # Tunda mematikan AC (menit) saat ruangan kosong
st.session_state.setdefault("auto_ac_last_empty_time", None) # Waktu terakhir ruangan kosong

# === Load YOLOv8 Model ===
if "model" not in st.session_state:
    st.session_state.model = YOLO("yolov8n.pt")
model = st.session_state.model


# === MQTT Setup ===
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        st.session_state.log.append("✅ Terhubung ke Ubidots")
    else:
        st.session_state.log.append(f"❌ Gagal terhubung, kode: {rc}")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload)
        val = payload.get("value", 0)
        st.session_state.camera_on = bool(val)
    except Exception as e:
        st.session_state.log.append(f"Error MQTT: {e}")


# === MQTT Setup with improved error handling ===
def setup_mqtt():
    try:
        client = mqtt.Client()
        client.username_pw_set(UBIDOTS_TOKEN, "")
        client.on_connect = on_connect
        client.on_message = on_message
        
        # Try to connect with timeout
        try:
            # Log the broker address for debugging
            st.session_state.log.append(f"🔌 Mencoba terhubung ke broker: {BROKER}:{PORT}")
            client.connect(BROKER, PORT, 10)  # Reduced timeout (10 seconds)
            client.subscribe(f"/v2.0/devices/{DEVICE_LABEL}/{VARIABLE_CAMERA}")
            client.loop_start()
            return client
        except socket.gaierror:
            st.session_state.log.append("❌ Error: Tidak dapat menyelesaikan nama host broker MQTT")
            st.error("Tidak dapat terhubung ke broker MQTT - periksa koneksi internet Anda")
            return None
        except socket.timeout:
            st.session_state.log.append("❌ Error: Koneksi MQTT timeout")
            st.error("Koneksi ke broker MQTT timeout - server mungkin tidak tersedia")
            return None
        except Exception as e:
            st.session_state.log.append(f"❌ Error MQTT: {str(e)}")
            st.error(f"Gagal terhubung ke broker MQTT: {str(e)}")
            return None
            
    except Exception as e:
        st.session_state.log.append(f"❌ Error saat inisialisasi MQTT: {str(e)}")
        return None

# Update the session state initialization to handle failed MQTT connections
if "client" not in st.session_state:
    mqtt_client = setup_mqtt()
    st.session_state.mqtt_connected = (mqtt_client is not None)
    st.session_state.client = mqtt_client
else:
    st.session_state.mqtt_connected = (st.session_state.client is not None)


st.session_state.setdefault("client", setup_mqtt())


# === Fungsi Kirim ke Ubidots ===
def send_ubidots(var, val):
    try:
        # Check if MQTT client exists and is connected
        if not st.session_state.mqtt_connected or st.session_state.client is None:
            st.session_state.log.append(f"⚠️ MQTT tidak terhubung, mencoba mengirim dengan HTTP: {var}={val}")
            
            # Fallback to HTTP API if MQTT is not available
            url = f"https://industrial.api.ubidots.com/api/v1.6/devices/{DEVICE_LABEL}/{var}/values"
            payload = {"value": val}
            headers = {"X-Auth-Token": UBIDOTS_TOKEN, "Content-Type": "application/json"}
            
            response = requests.post(url, json=payload, headers=headers)
            if response.status_code == 201:
                st.session_state.log.append(f"📤 HTTP: {var} = {val} berhasil")
            else:
                st.session_state.log.append(f"❌ HTTP error ({response.status_code}): {response.text}")
        else:
            # Use MQTT if connected
            topic = f"/v2.0/devices/{DEVICE_LABEL}/{var}"
            payload = json.dumps({"value": val})
            st.session_state.client.publish(topic, payload)
            st.session_state.log.append(f"📤 MQTT: {var} = {val}")

        # Log activity for AI summary regardless of method
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        activity = f"[{timestamp}] Kirim {var}={val} ke Ubidots"
        st.session_state.activity_history.append(activity)
        
        # Store last sent time
        st.session_state.last_sent = time.time()
        
    except Exception as e:
        st.session_state.log.append(f"❌ Gagal kirim ke Ubidots: {e}")


# === Setup Gemini Model ===
def setup_gemini_model():
    # Create a Gemini model instance
    # Choose the model based on your needs (gemini-pro is text-only)
    model = genai.GenerativeModel('gemini-2.0-flash')
    return model


if "gemini_model" not in st.session_state:
    try:
        st.session_state.gemini_model = setup_gemini_model()
    except Exception as e:
        st.session_state.log.append(f"❌ Error saat menyiapkan Gemini: {str(e)}")


# === Extract IP from user input ===
def extract_ip_address(text):
    import re
    # Pattern for IPv4 address with optional port (e.g., 192.168.1.1:81)
    ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b'
    matches = re.findall(ip_pattern, text)
    if matches:
        return matches[0]
    return None


# === Validate IP address ===
def is_valid_ip_address(ip):
    import re
    # Basic validation for IPv4 address format
    pattern = r'^(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?$'
    if not re.match(pattern, ip):
        return False

    # Check each octet is in valid range (0-255)
    parts = ip.split(':')[0].split('.')
    return all(0 <= int(part) <= 255 for part in parts)


# === Fungsi AI Assistant dengan Gemini ===
def generate_ai_response(prompt):
    try:
        # Create context with the activity history
        context = """
        Kamu adalah asisten AI untuk sistem IoT. Kamu dapat membantu:
        1. Memberikan ringkasan aktivitas sistem
        2. Mengontrol perangkat IoT seperti kamera dan lampu
        3. Memberikan informasi tentang jumlah orang terdeteksi
        4. Memberikan saran untuk pengaturan sistem
        
        Perangkat yang tersedia:
        - Kamera (camera): on/off
        - Lampu (lamp): on/off
        - Sensor jumlah orang (people)
        """

        # Add activity history to context
        if st.session_state.activity_history:
            context += "\n\nRiwayat aktivitas terbaru:\n"
            for activity in st.session_state.activity_history[-10:]:
                context += f"- {activity}\n"

        # Setup chat history for context
        chat_history = []
        if st.session_state.chat_history:
            for msg in st.session_state.chat_history[-5:]:  # Last 5 messages for context
                # Create content properly according to Gemini's requirements
                content = [{"text": msg["content"]}]
                role = "user" if msg["role"] == "user" else "model"
                chat_history.append({"role": role, "parts": content})

        # Add the latest context and prompt
        messages = [
            {"role": "user", "parts": [{"text": context}]},
            {"role": "model", "parts": [{"text": "Saya mengerti konteks sistem IoT dan siap membantu."}]},
        ]

        # Add chat history if available
        if chat_history:
            messages.extend(chat_history)

        # Add the current prompt
        messages.append({"role": "user", "parts": [{"text": prompt}]})

        # Generate response
        response = st.session_state.gemini_model.generate_content(messages)

        return response.text
    except Exception as e:
        return f"❌ Error AI: {str(e)}"


# === Generate Activity Summary ===
def generate_activity_summary():
    # This function generates a summary of recent system activities
    try:
        prompt = "Berikan ringkasan aktivitas sistem berdasarkan riwayat aktivitas terbaru."
        return generate_ai_response(prompt)
    except Exception as e:
        return f"❌ Error saat menghasilkan ringkasan: {str(e)}"


# === Process AI Commands ===
def process_ai_command(response, user_input):
    # Check for commands in the user input and AI response
    commands = {
        "camera_on": ["nyalakan kamera", "hidupkan kamera", "aktifkan kamera"],
        "camera_off": ["matikan kamera", "nonaktifkan kamera"],
        "lamp_on": ["nyalakan lampu", "hidupkan lampu"],
        "lamp_off": ["matikan lampu", "padamkan lampu"],
        "set_esp32_ip": ["gunakan ip", "alamat ip", "hubungkan ke ip", "gunakan esp32", "pakai esp32"],
        # Tambahkan commands untuk AC
        "ac_on": ["nyalakan ac", "hidupkan ac", "aktifkan ac"],
        "ac_off": ["matikan ac", "nonaktifkan ac"],
        "set_temp": ["atur suhu", "set suhu", "ubah suhu", "suhu ac"]
    }

    combined_text = (user_input + " " + response).lower()
    executed_commands = []

    # Check if there's an IP address in the user input
    ip_address = extract_ip_address(user_input)
    if ip_address and is_valid_ip_address(ip_address):
        st.session_state.esp32_url = ip_address
        st.session_state.camera_option = "ESP32-CAM"
        executed_commands.append(f"URL ESP32-CAM diatur ke {ip_address}")
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        st.session_state.activity_history.append(f"[{timestamp}] URL ESP32-CAM diatur ke {ip_address}")
    elif any(keyword in user_input.lower() for keyword in ["ip", "alamat", "esp32"]):
        # Detected IP-related keywords but couldn't find valid IP
        executed_commands.append("Format IP address tidak valid. Gunakan format: 192.168.1.100")

    # Check for camera and other commands
    for cmd, triggers in commands.items():
        for trigger in triggers:
            if trigger in combined_text:
                if cmd == "camera_on" and not st.session_state.camera_on:
                    st.session_state.camera_on = True
                    send_ubidots(VARIABLE_CAMERA, 1)
                    executed_commands.append("Kamera dinyalakan")
                elif cmd == "camera_off" and st.session_state.camera_on:
                    st.session_state.camera_on = False
                    send_ubidots(VARIABLE_CAMERA, 0)
                    executed_commands.append("Kamera dimatikan")
                elif cmd == "lamp_on" and st.session_state.lamp == 0:
                    st.session_state.lamp = 1
                    send_ubidots(VARIABLE_LIGHT, 1)
                    executed_commands.append("Lampu dinyalakan")
                elif cmd == "lamp_off" and st.session_state.lamp == 1:
                    st.session_state.lamp = 0
                    send_ubidots(VARIABLE_LIGHT, 0)
                    executed_commands.append("Lampu dimatikan")
                # AC commands
                elif cmd == "ac_on" and st.session_state.ac_power == 0:
                    st.session_state.ac_power = 1
                    send_ubidots(VARIABLE_AC, 1)
                    send_ubidots(VARIABLE_TEMPERATURE, st.session_state.ac_temperature)
                    executed_commands.append(f"AC dinyalakan (suhu: {st.session_state.ac_temperature}°C)")
                elif cmd == "ac_off" and st.session_state.ac_power == 1:
                    st.session_state.ac_power = 0
                    send_ubidots(VARIABLE_AC, 0)
                    executed_commands.append("AC dimatikan")
                elif cmd == "set_temp":
                    import re
                    temp_match = re.search(r'(\d{1,2})(?:\s*)(derajat|°C|celsius)', combined_text.lower())
                    if temp_match:
                        new_temp = int(temp_match.group(1))
                        if 16 <= new_temp <= 30:  # Range suhu AC yang umum
                            st.session_state.ac_temperature = new_temp
                            send_ubidots(VARIABLE_TEMPERATURE, new_temp)
                            executed_commands.append(f"Suhu AC diatur ke {new_temp}°C")
                        else:
                            executed_commands.append("Suhu harus antara 16-30°C")
                break

    return executed_commands

# === Fungsi Kontrol Otomatis AC ===
def auto_control_ac():
    if not st.session_state.auto_ac_enabled:
        return
    
    current_temp = st.session_state.current_temperature
    people_count = st.session_state.count
    threshold_temp = st.session_state.auto_ac_temp_threshold
    people_threshold = st.session_state.auto_ac_people_threshold
    
    # Log untuk debugging
    st.session_state.log.append(f"🤖 Auto AC: Suhu={current_temp}°C, Orang={people_count}")
    
    # Kondisi untuk menyalakan AC: 
    # 1. Suhu ruangan melebihi ambang batas, DAN
    # 2. Ada orang dalam ruangan (jumlah >= threshold)
    if current_temp >= threshold_temp and people_count >= people_threshold:
        if st.session_state.ac_power == 0:
            # Nyalakan AC jika belum menyala
            st.session_state.ac_power = 1
            
            # Atur suhu AC berdasarkan jumlah orang (semakin banyak orang, semakin dingin)
            # Base temperature 25°C, kurangi 0.5°C untuk setiap orang (minimal 18°C)
            dynamic_temp = max(18, 25 - (people_count * 0.5))
            st.session_state.ac_temperature = int(dynamic_temp)
            
            # Kirim ke Ubidots
            send_ubidots(VARIABLE_AC, 1)
            send_ubidots(VARIABLE_TEMPERATURE, st.session_state.ac_temperature)
            
            # Log aktivitas
            timestamp = time.strftime("%H:%M:%S", time.localtime())
            activity = f"[{timestamp}] AC dinyalakan otomatis (Suhu: {current_temp}°C, Orang: {people_count})"
            st.session_state.activity_history.append(activity)
            st.session_state.log.append(f"🤖 {activity}")
            
            # Reset waktu terakhir ruangan kosong
            st.session_state.auto_ac_last_empty_time = None
    
    # Kondisi untuk mematikan AC:
    # 1. Ruangan kosong (dengan delay), ATAU
    # 2. Suhu ruangan di bawah ambang batas - 2°C (histeresis untuk mencegah on/off terlalu sering)
    elif people_count < people_threshold:
        current_time = time.time()
        
        # Catat waktu saat ruangan mulai kosong
        if st.session_state.auto_ac_last_empty_time is None:
            st.session_state.auto_ac_last_empty_time = current_time
            st.session_state.log.append(f"🤖 Ruangan kosong, mulai penghitung waktu")
        
        # Cek apakah sudah melewati delay
        empty_time_minutes = (current_time - st.session_state.auto_ac_last_empty_time) / 60
        if empty_time_minutes >= st.session_state.auto_ac_empty_delay and st.session_state.ac_power == 1:
            # Matikan AC setelah ruangan kosong selama delay yang ditentukan
            st.session_state.ac_power = 0
            send_ubidots(VARIABLE_AC, 0)
            
            # Log aktivitas
            timestamp = time.strftime("%H:%M:%S", time.localtime())
            activity = f"[{timestamp}] AC dimatikan otomatis (ruangan kosong selama {empty_time_minutes:.1f} menit)"
            st.session_state.activity_history.append(activity)
            st.session_state.log.append(f"🤖 {activity}")
    
    elif current_temp < (threshold_temp - 2.0) and st.session_state.ac_power == 1:
        # Matikan AC jika suhu sudah cukup dingin (threshold - 2°C)
        st.session_state.ac_power = 0
        send_ubidots(VARIABLE_AC, 0)
        
        # Log aktivitas
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        activity = f"[{timestamp}] AC dimatikan otomatis (suhu sudah dingin: {current_temp}°C)"
        st.session_state.activity_history.append(activity)
        st.session_state.log.append(f"🤖 {activity}")
    
    elif people_count >= people_threshold and st.session_state.ac_power == 1:
        # Atur ulang suhu AC berdasarkan jumlah orang saat AC sudah menyala
        dynamic_temp = max(18, 25 - (people_count * 0.5))
        new_temp = int(dynamic_temp)
        
        # Hanya update jika ada perubahan
        if new_temp != st.session_state.ac_temperature:
            st.session_state.ac_temperature = new_temp
            send_ubidots(VARIABLE_TEMPERATURE, new_temp)
            
            # Log aktivitas
            timestamp = time.strftime("%H:%M:%S", time.localtime())
            activity = f"[{timestamp}] Suhu AC disesuaikan: {new_temp}°C (Orang: {people_count})"
            st.session_state.activity_history.append(activity)
            st.session_state.log.append(f"🤖 {activity}")

# === Fungsi Streaming ESP32-CAM MJPEG ===
def esp32_stream_generator(url):
    st.session_state.log.append(f"🔄 Menghubungkan ke ESP32-CAM: {url}")
    
    # Pengaturan koneksi ultra-low-latency dengan header yang dioptimalkan
    session = requests.Session()
    session.headers.update({
        'Connection': 'keep-alive',
        'Accept': 'multipart/x-mixed-replace; boundary=frame',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
        'X-Requested-With': 'XMLHttpRequest'  # Mengurangi overhead HTTP
    })
    
    # Strategi connection pooling yang lebih agresif
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=2,
        pool_maxsize=2,
        max_retries=3,
        pool_block=False
    )
    session.mount('http://', adapter)
    
    # Variabel monitoring
    connection_attempts = 0
    max_connection_attempts = 5
    connection_backoff = 0.3  # Lebih cepat retry
    stream_start_time = time.time()
    max_stream_duration = 30  # Refresh koneksi setiap 30 detik untuk reliability
    
    while connection_attempts < max_connection_attempts and st.session_state.camera_on:
        try:
            # Timeout yang lebih agresif
            timeout = (1.5, 1.5)  # (connect timeout, read timeout) - lebih agresif
            
            # Stream dengan buffer rendah
            stream = session.get(url, stream=True, timeout=timeout)
            
            if stream.status_code != 200:
                st.session_state.log.append(f"❌ Koneksi gagal: HTTP {stream.status_code}")
                connection_attempts += 1
                time.sleep(connection_backoff)
                continue
                
            # Buffer minimal untuk low-latency
            byte_buffer = bytearray()
            last_frame_time = time.time()
            frame_count = 0
            last_successful_frame = time.time()
            consecutive_empty_frames = 0
            
            # Pengaturan chunk size lebih kecil untuk responsivitas lebih baik
            for chunk in stream.iter_content(chunk_size=1024):  # Chunk size yang lebih kecil
                if not st.session_state.camera_on:
                    break
                    
                # Refresh koneksi lebih sering
                if time.time() - stream_start_time > max_stream_duration:
                    st.session_state.log.append("🔄 ESP32-CAM connection refresh...")
                    break
                
                if not chunk:
                    consecutive_empty_frames += 1
                    if consecutive_empty_frames > 2:  # Lebih agresif dalam reconnect
                        break
                    time.sleep(0.01)  # Tunggu sangat singkat
                    continue
                
                consecutive_empty_frames = 0
                byte_buffer.extend(chunk)
                
                # Optimized frame extraction dengan algoritma Boyer-Moore sederhana
                start_idx = byte_buffer.find(b'\xff\xd8')
                end_idx = byte_buffer.find(b'\xff\xd9')
                
                if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
                    frame_data = byte_buffer[start_idx:end_idx + 2]
                    byte_buffer = byte_buffer[end_idx + 2:]  # Clear processed data
                    
                    try:
                        # Decode optimized dengan opsi hardware acceleration
                        frame = cv2.imdecode(
                            np.frombuffer(frame_data, dtype=np.uint8),
                            cv2.IMREAD_COLOR
                        )
                        
                        if frame is not None and frame.size > 0:
                            # Dynamic frame rate control - skip frames saat CPU load tinggi
                            current_time = time.time()
                            if current_time - last_successful_frame < 0.03:  # ~30fps limit
                                continue
                                
                            # Pre-resize untuk performa
                            frame = cv2.resize(frame, (320, 240), interpolation=cv2.INTER_AREA)
                            
                            last_successful_frame = current_time
                            frame_count += 1
                            
                            # Performance metrics
                            if frame_count % 10 == 0:
                                fps = 10 / max(0.001, current_time - last_frame_time)
                                last_frame_time = current_time
                                if frame_count % 30 == 0:
                                    st.session_state.log.append(f"📊 ESP32-CAM: {fps:.1f} FPS")
                            
                            yield frame
                        else:
                            # Handle invalid frame dengan cepat
                            if time.time() - last_successful_frame > 0.5:  # Reduced timeout
                                break
                    
                    except Exception as e:
                        if time.time() - last_successful_frame > 0.5:
                            break
                
                # Aggressive timeout untuk disconnection
                if time.time() - last_successful_frame > 1.0:  # Reduced timeout
                    break
                
                # Prevent buffer bloat dengan clearing agresif
                if len(byte_buffer) > 8192:  # Reduced max buffer (8KB)
                    byte_buffer = byte_buffer[-2048:]  # Keep only last 2KB
            
            # Close dan retry dengan efisien
            stream.close()
            
            if st.session_state.camera_on:
                connection_attempts += 1
                time.sleep(connection_backoff)
        
        except requests.exceptions.Timeout:
            connection_attempts += 1
            time.sleep(connection_backoff)
        
        except Exception as e:
            st.session_state.log.append(f"❌ Error: {str(e)[:40]}")
            connection_attempts += 1
            time.sleep(connection_backoff)
    
    # Cleanup
    if 'stream' in locals():
        try:
            stream.close()
        except:
            pass
    
    if 'session' in locals():
        try:
            session.close()
        except:
            pass
    
    yield None
    
# === Format ESP32 URL ===
def format_esp32_url(url):
    # Format URL dengan benar untuk ESP32-CAM
    if not url.startswith("http"):
        url = "http://" + url

    # Pastikan port 81 ada
    if ":81" not in url:
        # Hapus port lain jika ada
        if ":" in url[8:]:  # 8 karakter = "http://" 
            parts = url.split(":")
            url = parts[0] + ":" + parts[1].split("/")[0]  # Ambil bagian host saja
            url = url + ":81"
        else:
            url = url + ":81"

    # Pastikan path /stream ada di akhir
    if not url.endswith("/stream"):
        # Hapus path lain jika ada
        if "/" in url[8:] and ":" in url:
            # Ambil base URL dengan port
            base_parts = url.split("/")
            url = base_parts[0] + "//" + base_parts[2]
            if ":" not in url:
                url = url + ":81"
            url = url + "/stream"
        else:
            url = url + "/stream"

    return url


# === Add this helper function at the top level ===
def optimize_frame_for_detection(frame):
    """Ultra-optimized frame processing for detection"""
    # Buat salinan frame untuk menghindari modifikasi asli
    original_frame = frame.copy()
    
    # Resize dengan rasio aspect yang dipertahankan
    height, width = frame.shape[:2]
    target_size = 320  # Ukuran yang seimbang antara kecepatan dan akurasi
    
    # Hitung scale yang mempertahankan aspect ratio
    scale = target_size / max(height, width)
    new_height = int(height * scale)
    new_width = int(width * scale)
    
    # Resize dengan metode yang tepat untuk kamera
    detection_frame = cv2.resize(frame, (new_width, new_height), 
                      interpolation=cv2.INTER_AREA)
    
    # Padding untuk membuat square (jika diperlukan YOLOv8)
    if new_height != new_width:
        top = bottom = max(0, (target_size - new_height) // 2)
        left = right = max(0, (target_size - new_width) // 2)
        detection_frame = cv2.copyMakeBorder(detection_frame, top, bottom, left, right, 
                                  cv2.BORDER_CONSTANT, value=(0, 0, 0))
    
    # Pengurangan noise minimal dan selektif
    # Menggunakan Gaussian Blur yang ringan hanya pada frame yang akan dideteksi
    detection_frame = cv2.GaussianBlur(detection_frame, (3, 3), 0)
    
    return detection_frame, original_frame

# === Fungsi Baca Data DHT11 ===
def read_dht11_data():
    try:
        # Baca data dari Ubidots (DHT11 dikirim dari ESP32 ke Ubidots)
        url = f"https://industrial.api.ubidots.com/api/v1.6/devices/{DEVICE_LABEL}/{VARIABLE_DHT11}/values/?token={UBIDOTS_TOKEN}"
        response = requests.get(url)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("results") and len(data["results"]) > 0:
                temperature = data["results"][0]["value"]
                st.session_state.current_temperature = temperature
                st.session_state.log.append(f"🌡️ Suhu DHT11: {temperature}°C")
                
                # Log activity for AI summary
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                activity = f"[{timestamp}] Suhu DHT11 dibaca: {temperature}°C"
                st.session_state.activity_history.append(activity)
                
                return temperature
        return None
    except Exception as e:
        st.session_state.log.append(f"❌ Gagal membaca data DHT11: {e}")
        return None

# === Fungsi Cek dan Jalankan Jadwal ===
def check_and_run_schedules():
    # Get current time and date info
    current_time = time.strftime("%H:%M")
    current_date = datetime.date.today()
    # Get day of week (0 is Monday in Python's datetime)
    day_idx = datetime.datetime.now().weekday()
    day_names = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
    current_day = day_names[day_idx]
    
    # Cek jadwal AC
    if st.session_state.schedules["ac"]["enabled"]:
        ac_on_time = st.session_state.schedules["ac"]["on_time"]
        ac_off_time = st.session_state.schedules["ac"]["off_time"]
        should_run_ac_schedule = False
        
        # Check if schedule should run based on day/date setting
        if st.session_state.schedules["ac"]["date_specific"]:
            # Specific date scheduling
            specific_date = st.session_state.schedules["ac"]["specific_date"]
            # Check if today matches the specific date
            if specific_date and current_date == specific_date:
                should_run_ac_schedule = True
        elif st.session_state.schedules["ac"].get("days"):
            # Weekly scheduling (specific days)
            if current_day in st.session_state.schedules["ac"]["days"]:
                should_run_ac_schedule = True
        else:
            # Daily scheduling (every day)
            should_run_ac_schedule = True
            
        # Run schedule if conditions are met
        if should_run_ac_schedule:
            # Logika untuk menyalakan/mematikan AC berdasarkan jadwal
            if current_time == ac_on_time and st.session_state.ac_power == 0:
                st.session_state.ac_power = 1
                send_ubidots(VARIABLE_AC, 1)
                send_ubidots(VARIABLE_TEMPERATURE, st.session_state.ac_temperature)
                st.session_state.log.append(f"🕒 Jadwal: AC dinyalakan ({current_time})")
                
                # Log activity for AI summary
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                activity = f"[{timestamp}] AC dinyalakan otomatis sesuai jadwal"
                st.session_state.activity_history.append(activity)
                
            elif current_time == ac_off_time and st.session_state.ac_power == 1:
                st.session_state.ac_power = 0
                send_ubidots(VARIABLE_AC, 0)
                st.session_state.log.append(f"🕒 Jadwal: AC dimatikan ({current_time})")
                
                # Log activity for AI summary
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                activity = f"[{timestamp}] AC dimatikan otomatis sesuai jadwal"
                st.session_state.activity_history.append(activity)
    
    # Cek jadwal Lampu - similar logic as AC
    if st.session_state.schedules["light"]["enabled"]:
        light_on_time = st.session_state.schedules["light"]["on_time"]
        light_off_time = st.session_state.schedules["light"]["off_time"]
        should_run_light_schedule = False
        
        # Check if schedule should run based on day/date setting
        if st.session_state.schedules["light"]["date_specific"]:
            # Specific date scheduling
            specific_date = st.session_state.schedules["light"]["specific_date"]
            # Check if today matches the specific date
            if specific_date and current_date == specific_date:
                should_run_light_schedule = True
        elif st.session_state.schedules["light"].get("days"):
            # Weekly scheduling (specific days)
            if current_day in st.session_state.schedules["light"]["days"]:
                should_run_light_schedule = True
        else:
            # Daily scheduling (every day)
            should_run_light_schedule = True
            
        # Run schedule if conditions are met
        if should_run_light_schedule:
            # Logika untuk menyalakan/mematikan lampu berdasarkan jadwal
            if current_time == light_on_time and st.session_state.lamp == 0:
                st.session_state.lamp = 1
                send_ubidots(VARIABLE_LIGHT, 1)
                st.session_state.log.append(f"🕒 Jadwal: Lampu dinyalakan ({current_time})")
                
                # Log activity for AI summary
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                activity = f"[{timestamp}] Lampu dinyalakan otomatis sesuai jadwal"
                st.session_state.activity_history.append(activity)
                
            elif current_time == light_off_time and st.session_state.lamp == 1:
                st.session_state.lamp = 0
                send_ubidots(VARIABLE_LIGHT, 0)
                st.session_state.log.append(f"🕒 Jadwal: Lampu dimatikan ({current_time})")
                
                # Log activity for AI summary
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                activity = f"[{timestamp}] Lampu dimatikan otomatis sesuai jadwal"
                st.session_state.activity_history.append(activity)
                
# Info jadwal - improved display with advanced scheduling info
def format_schedule_info(device_type):
    schedule = st.session_state.schedules[device_type]
    if not schedule["enabled"]:
        return "Nonaktif"
        
    time_info = f"Nyala: {schedule['on_time']}, Mati: {schedule['off_time']}"
    
    if schedule["date_specific"]:
        date_str = schedule["specific_date"].strftime("%d/%m/%Y") if schedule["specific_date"] else "belum dipilih"
        return f"Aktif - Tanggal {date_str} ({time_info})"
    elif schedule.get("days"):
        return f"Aktif - {', '.join(schedule['days'])} ({time_info})"
    else:
        return f"Aktif - Setiap hari ({time_info})"

# === UI ===
st.title("🔆SAKLAR: Smart Automated Kinetics for Lighting & Air Regulation❄️")

# Create tabs for different functionality
tab1, tab2, tab3 = st.tabs(["Kamera & Deteksi", "AC & Jadwal", "AI Assistant"])

with tab1:
    
    st.text_input("Masukkan URL IP ESP32-CAM", key="esp32_url")

    start = st.button("🔄 Mulai Kamera")
    stop = st.button("⛔ Stop Kamera")

    frame_placeholder = st.empty()
    status_placeholder = st.empty()
    detail_placeholder = st.empty()

with tab2:
    st.header("🌡️ Kontrol AC & Penjadwalan")
    
    # Tampilkan suhu dari DHT11
    temp_col, refresh_col = st.columns([3, 1])
    with temp_col:
        st.subheader(f"Suhu Ruangan: {st.session_state.current_temperature}°C")
    with refresh_col:
        if st.button("🔄 Refresh"):
            read_dht11_data()
    
    # Kontrol AC
    st.subheader("Kontrol AC")
    ac_col1, ac_col2 = st.columns(2)
    
    with ac_col1:
        ac_state = st.toggle("AC Power", value=bool(st.session_state.ac_power))
        if ac_state != bool(st.session_state.ac_power):
            st.session_state.ac_power = 1 if ac_state else 0
            send_ubidots(VARIABLE_AC, st.session_state.ac_power)
            
            # Log activity
            timestamp = time.strftime("%H:%M:%S", time.localtime())
            activity = f"[{timestamp}] AC {'dinyalakan' if ac_state else 'dimatikan'} manual"
            st.session_state.activity_history.append(activity)
    
    with ac_col2:
        new_temp = st.slider("Suhu AC", min_value=16, max_value=30, value=st.session_state.ac_temperature)
        if new_temp != st.session_state.ac_temperature:
            st.session_state.ac_temperature = new_temp
            if st.session_state.ac_power == 1:
                send_ubidots(VARIABLE_TEMPERATURE, new_temp)
                
                # Log activity
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                activity = f"[{timestamp}] Suhu AC diubah ke {new_temp}°C"
                st.session_state.activity_history.append(activity)
    
    # Tambahkan bagian kontrol otomatis AC (setelah kontrol manual AC)
    st.subheader("Kontrol Otomatis AC")

    auto_ac_enabled = st.toggle("Aktifkan Kontrol Otomatis AC", 
                             value=st.session_state.auto_ac_enabled,
                             help="AC akan otomatis menyala/mati berdasarkan suhu dan jumlah orang")

    # Update state
    st.session_state.auto_ac_enabled = auto_ac_enabled

    if auto_ac_enabled:
        # Tampilkan pengaturan kontrol otomatis
        col1, col2 = st.columns(2)
        
        with col1:
            # Slider untuk ambang suhu
            temp_threshold = st.slider("Ambang Suhu (°C)", 
                                     min_value=24.0, 
                                     max_value=32.0, 
                                     value=st.session_state.auto_ac_temp_threshold,
                                     step=0.5,
                                     help="AC akan menyala jika suhu melebihi nilai ini")
            st.session_state.auto_ac_temp_threshold = temp_threshold
        
        with col2:
            # Slider untuk ambang jumlah orang
            people_threshold = st.slider("Minimal Jumlah Orang", 
                                       min_value=0, 
                                       max_value=5, 
                                       value=st.session_state.auto_ac_people_threshold,
                                       help="AC akan menyala jika jumlah orang sama atau lebih dari nilai ini")
            st.session_state.auto_ac_people_threshold = people_threshold
        
        # Delay untuk mematikan AC saat ruangan kosong
        empty_delay = st.slider("Tunda Mematikan AC (menit)", 
                              min_value=0, 
                              max_value=30, 
                              value=st.session_state.auto_ac_empty_delay,
                              help="Waktu tunda sebelum mematikan AC saat ruangan kosong")
        st.session_state.auto_ac_empty_delay = empty_delay
        
        # Info tentang logika kontrol
        st.info("""
        **🤖 Logika Kontrol Otomatis:**
        1. AC akan **menyala** jika suhu ruangan ≥ ambang suhu DAN jumlah orang ≥ minimal jumlah orang
        2. AC akan **mati** jika ruangan kosong selama waktu tunda yang ditentukan
        3. AC akan **mati** jika suhu ruangan turun 2°C di bawah ambang suhu
        4. Suhu AC akan otomatis disesuaikan berdasarkan jumlah orang (semakin banyak orang, semakin dingin)
        """)
        
        # Tampilkan status terakhir
        if st.session_state.auto_ac_last_empty_time:
            empty_time_minutes = (time.time() - st.session_state.auto_ac_last_empty_time) / 60
            st.caption(f"⏱️ Ruangan kosong selama {empty_time_minutes:.1f} menit")
    else:
        st.caption("Kontrol otomatis AC dinonaktifkan. Atur AC secara manual atau dengan jadwal.")
    
    # Penjadwalan
    st.subheader("Penjadwalan Perangkat")
    
    # Tab penjadwalan
    sched_tab1, sched_tab2 = st.tabs(["Jadwal AC", "Jadwal Lampu"])
    
    with sched_tab1:
        # Enable/disable schedule
        ac_enabled = st.checkbox("Aktifkan Jadwal AC", 
                             value=st.session_state.schedules["ac"]["enabled"])
        # Update the dictionary directly
        st.session_state.schedules["ac"]["enabled"] = ac_enabled
        
        # Schedule type selector
        ac_schedule_type = st.radio("Tipe Jadwal:", 
                                ["Harian", "Mingguan", "Tanggal Spesifik"],
                                horizontal=True,
                                index=1 if st.session_state.schedules["ac"].get("days") else 0 if not st.session_state.schedules["ac"].get("date_specific") else 2)
        
        # Update schedule type based on selection
        st.session_state.schedules["ac"]["date_specific"] = (ac_schedule_type == "Tanggal Spesifik")
        
        # Day selection for weekly schedule
        if ac_schedule_type == "Mingguan":
            days_options = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
            selected_days = st.multiselect("Pilih Hari", 
                                         days_options,
                                         default=st.session_state.schedules["ac"].get("days", ["Sen", "Sel", "Rab", "Kam", "Jum"]))
            
            st.session_state.schedules["ac"]["days"] = selected_days
        
        # Date selection for specific date schedule
        elif ac_schedule_type == "Tanggal Spesifik":
            selected_date = st.date_input("Pilih Tanggal", 
                                         value=st.session_state.schedules["ac"].get("specific_date", datetime.date.today()))
            
            st.session_state.schedules["ac"]["specific_date"] = selected_date
        
        # Time selection
        ac_col1, ac_col2 = st.columns(2)
        with ac_col1:
            # Convert string time to datetime.time object
            ac_on_hour, ac_on_minute = map(int, st.session_state.schedules["ac"]["on_time"].split(":"))
            ac_on_time = datetime.time(hour=ac_on_hour, minute=ac_on_minute)
            
            ac_on_time_input = st.time_input("Waktu Nyala AC", value=ac_on_time)
            # Convert back to string format
            st.session_state.schedules["ac"]["on_time"] = f"{ac_on_time_input.hour:02d}:{ac_on_time_input.minute:02d}"
        
        with ac_col2:
            # Convert string time to datetime.time object
            ac_off_hour, ac_off_minute = map(int, st.session_state.schedules["ac"]["off_time"].split(":"))
            ac_off_time = datetime.time(hour=ac_off_hour, minute=ac_off_minute)
            
            ac_off_time_input = st.time_input("Waktu Mati AC", value=ac_off_time)
            # Convert back to string format
            st.session_state.schedules["ac"]["off_time"] = f"{ac_off_time_input.hour:02d}:{ac_off_time_input.minute:02d}"

    with sched_tab2:
        # Enable/disable schedule
        light_enabled = st.checkbox("Aktifkan Jadwal Lampu", 
                                value=st.session_state.schedules["light"]["enabled"])
        # Update the dictionary directly
        st.session_state.schedules["light"]["enabled"] = light_enabled
        
        # Schedule type selector
        light_schedule_type = st.radio("Tipe Jadwal:", 
                                   ["Harian", "Mingguan", "Tanggal Spesifik"],
                                   horizontal=True,
                                   index=1 if st.session_state.schedules["light"].get("days") else 0 if not st.session_state.schedules["light"].get("date_specific") else 2,
                                   key="light_schedule_type")
        
        # Update schedule type based on selection
        st.session_state.schedules["light"]["date_specific"] = (light_schedule_type == "Tanggal Spesifik")
        
        # Day selection for weekly schedule
        if light_schedule_type == "Mingguan":
            light_days_options = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
            light_selected_days = st.multiselect("Pilih Hari", 
                                              light_days_options,
                                              default=st.session_state.schedules["light"].get("days", ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]),
                                              key="light_days")
            
            st.session_state.schedules["light"]["days"] = light_selected_days
        
        # Date selection for specific date schedule
        elif light_schedule_type == "Tanggal Spesifik":
            light_selected_date = st.date_input("Pilih Tanggal", 
                                             value=st.session_state.schedules["light"].get("specific_date", datetime.date.today()),
                                             key="light_date")
            
            st.session_state.schedules["light"]["specific_date"] = light_selected_date
        
        # Time selection
        light_col1, light_col2 = st.columns(2)
        with light_col1:
            # Convert string time to datetime.time object
            light_on_hour, light_on_minute = map(int, st.session_state.schedules["light"]["on_time"].split(":"))
            light_on_time = datetime.time(hour=light_on_hour, minute=light_on_minute)
            
            light_on_time_input = st.time_input("Waktu Nyala Lampu", value=light_on_time, key="light_on_time")
            # Convert back to string format
            st.session_state.schedules["light"]["on_time"] = f"{light_on_time_input.hour:02d}:{light_on_time_input.minute:02d}"
        
        with light_col2:
            # Convert string time to datetime.time object
            light_off_hour, light_off_minute = map(int, st.session_state.schedules["light"]["off_time"].split(":"))
            light_off_time = datetime.time(hour=light_off_hour, minute=light_off_minute)
            
            light_off_time_input = st.time_input("Waktu Mati Lampu", value=light_off_time, key="light_off_time")
            # Convert back to string format
            st.session_state.schedules["light"]["off_time"] = f"{light_off_time_input.hour:02d}:{light_off_time_input.minute:02d}"
    
    # Info jadwal
    st.info(f"""
    ⏰ **Status Jadwal:**
    - AC: {format_schedule_info("ac")}
    - Lampu: {format_schedule_info("light")}
    """)

with tab3:
    st.header("💬 AI Assistant (Powered by Google Gemini)")

    # Toggle for AI Assistant
    st.checkbox("Aktifkan AI Assistant", key="ai_enabled")

    if st.session_state.ai_enabled:
        # Generate summary button
        if st.button("🔍 Dapatkan Ringkasan Aktivitas"):
            summary = generate_activity_summary()
            st.session_state.chat_history.append({"role": "user", "content": "Berikan ringkasan aktivitas sistem"})
            st.session_state.chat_history.append({"role": "assistant", "content": summary})

        # Chat interface
        user_input = st.text_input("Ketik perintah atau pertanyaan:",
                                   placeholder="contoh: nyalakan kamera, matikan lampu, berapa orang terdeteksi?")

        if user_input:
            st.session_state.chat_history.append({"role": "user", "content": user_input})

            # Generate AI response
            ai_response = generate_ai_response(user_input)

            # Process any commands in the response, passing both user input and AI response
            executed_cmds = process_ai_command(ai_response, user_input)
            if executed_cmds:
                ai_response += "\n\n*Tindakan yang dilakukan:*\n" + "\n".join([f"- {cmd}" for cmd in executed_cmds])

            st.session_state.chat_history.append({"role": "assistant", "content": ai_response})

        # Display chat history
        st.subheader("Riwayat Chat")
        chat_container = st.container()
        with chat_container:
            for message in st.session_state.chat_history:
                if message["role"] == "user":
                    st.markdown(f"**🧑 Anda:** {message['content']}")
                else:
                    st.markdown(f"**🤖 AI Assistant:** {message['content']}")

        # Add a clear chat button
        if st.button("🗑️ Bersihkan Riwayat Chat"):
            st.session_state.chat_history = []
            st.rerun()
    else:
        st.info("Aktifkan AI Assistant untuk menggunakan fitur ini.")

# === Tombol Start & Stop ===
if start:
    st.session_state.camera_on = True
    st.session_state.stop_clicks = 0
    send_ubidots(VARIABLE_CAMERA, 1)

    # Log for AI
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    st.session_state.activity_history.append(f"[{timestamp}] Kamera diaktifkan")

if stop:
    st.session_state.stop_clicks += 1
    if st.session_state.stop_clicks >= 2:
        st.session_state.camera_on = False
        st.session_state.stop_clicks = 0
        send_ubidots(VARIABLE_CAMERA, 0)
        send_ubidots(VARIABLE_LIGHT, 0)
        send_ubidots(VARIABLE_COUNT, 0)

        # Log for AI
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        st.session_state.activity_history.append(f"[{timestamp}] Kamera dan lampu dimatikan")
    else:
        st.session_state.camera_on = False
        send_ubidots(VARIABLE_CAMERA, 0)
        send_ubidots(VARIABLE_LIGHT, 0)
        send_ubidots(VARIABLE_COUNT, 0)

        # Log for AI
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        st.session_state.activity_history.append(f"[{timestamp}] Kamera dan lampu dimatikan")

# === Streaming dan Deteksi ===
if st.session_state.camera_on:
    try:
        # Ambil URL dari input
        url = st.session_state.esp32_url.strip()

        if not url:
            st.error("⚠️ URL ESP32-CAM tidak boleh kosong!")
            st.session_state.camera_on = False
        else:
            # Format URL dengan benar
            url = format_esp32_url(url)
            st.session_state.log.append(f"📡 URL ESP32 final: {url}")

            # Buat generator baru
            frame_iterator = esp32_stream_generator(url)

        last_frame_time = time.time()
        frame_count = 0
        no_new_frame_count = 0
        last_count = -1
        last_ubidots_send = time.time()
        skip_frames = 0
        reconnect_time = time.time()
        frame_display_time = time.time()
        
        # Variabel untuk mengelola deteksi
        detection_cooldown = 0
        detection_interval = 3  # Hanya deteksi setiap 3 frame
        last_valid_count = 0  # Simpan hasil deteksi terakhir yang valid
        detection_confidence = 0  # Confidence level untuk hasil deteksi

        while st.session_state.camera_on:
            try:
                # Adaptive frame skipping yang lebih cerdas
                current_time = time.time()
                elapsed = current_time - frame_display_time

                # Skip threshold dinamis berdasarkan performa sistem dan status deteksi
                if detection_confidence > 0:  # Ada orang terdeteksi, prioritaskan akurasi
                    if elapsed > 0.2:       
                        skip_threshold = 3   # Kurangi skipping saat ada deteksi
                    elif elapsed > 0.15:    
                        skip_threshold = 2
                    else:                   
                        skip_threshold = 1   # Hampir tidak skip saat deteksi aktif
                else:  # Tidak ada orang, prioritaskan performa
                    if elapsed > 0.2:       
                        skip_threshold = 5
                    elif elapsed > 0.15:   
                        skip_threshold = 4
                    elif elapsed > 0.10:    
                        skip_threshold = 3
                    elif elapsed > 0.05:    
                        skip_threshold = 2
                    else:                  
                        skip_threshold = 1

                # Skip processing berdasarkan threshold
                skip_frames += 1
                if skip_frames % skip_threshold != 0:
                    time.sleep(0.001)  # Minimal sleep
                    continue

                # Force reconnect ESP32-CAM secara periodik
                if time.time() - reconnect_time > 120:
                    st.session_state.log.append("🔄 Periodic ESP32-CAM reconnection...")
                    frame_iterator = esp32_stream_generator(url)
                    reconnect_time = time.time()
                    continue

                try:
                    # Ambil frame dengan timeout
                    frame_start = time.time()
                    frame = next(frame_iterator)
                    
                    # Jika timeout >1 detik, log warning
                    if time.time() - frame_start > 1.0:
                        st.session_state.log.append("⚠️ Slow frame acquisition")

                    # Handle frame kosong
                    if frame is None:
                        no_new_frame_count += 1
                        if no_new_frame_count > 5:
                            st.session_state.log.append("🔄 Connection issue - reinitializing...")
                            frame_iterator = esp32_stream_generator(url)
                            no_new_frame_count = 0
                            reconnect_time = time.time()
                        time.sleep(0.2)
                        continue

                    no_new_frame_count = 0  # Reset counter
                    
                    # Simpan frame original untuk display
                    display_frame = frame.copy()
                    
                    # Hanya lakukan deteksi pada interval tertentu untuk mengurangi beban
                    detection_cooldown += 1
                    if detection_cooldown >= detection_interval:
                        # Optimasi frame untuk deteksi tanpa mengubah frame display
                        detection_frame, _ = optimize_frame_for_detection(frame)
                        
                        try:
                            # Deteksi dengan parameter optimal untuk ESP32-CAM dengan efisiensi
                            results = model.predict(
                                detection_frame,
                                verbose=False,
                                conf=0.35,      # Threshold deteksi
                                iou=0.45,       # Threshold NMS sedikit lebih tinggi
                                agnostic_nms=True,
                                max_det=5,      # Kurangi max deteksi untuk performa
                                classes=[0]     # Hanya manusia
                            )
                            
                            # Proses hasil deteksi
                            boxes = results[0].boxes
                            people_boxes = [box for box in boxes if int(box.cls[0]) == 0 and float(box.conf[0]) > 0.4]
                            new_count = len(people_boxes)
                            
                            # State persistence - mempertahankan deteksi antara freeze
                            if new_count > 0:
                                last_valid_count = new_count
                                detection_confidence = 5  # Reset confidence level
                            elif detection_confidence > 0:
                                # Pertahankan deteksi terakhir dengan confidence menurun
                                detection_confidence -= 1
                                new_count = last_valid_count if detection_confidence > 0 else 0
                            
                            count = new_count
                            
                            # Gambar bounding box pada frame display jika ada orang
                            if people_boxes:
                                # Gambar bounding box langsung ke display_frame
                                scaled_boxes = []
                                h, w = display_frame.shape[:2]
                                h_ratio = h / detection_frame.shape[0]
                                w_ratio = w / detection_frame.shape[1]
                                
                                for box in people_boxes:
                                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                                    # Skala ulang koordinat
                                    x1 = int(x1 * w_ratio)
                                    y1 = int(y1 * h_ratio)
                                    x2 = int(x2 * w_ratio)
                                    y2 = int(y2 * h_ratio)
                                    
                                    # Gambar kotak persegi panjang pada frame display
                                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        
                        except Exception as e:
                            st.session_state.log.append(f"⚠️ Detection error: {str(e)[:50]}")
                            # Jika error, gunakan count terakhir yang valid
                            count = last_valid_count if detection_confidence > 0 else 0
                        
                        detection_cooldown = 0  # Reset cooldown
                    
                    # Gunakan display_frame untuk UI
                    frame = display_frame
                except StopIteration:
                    st.session_state.log.append("🔄 Stream ended - reconnecting...")
                    frame_iterator = esp32_stream_generator(url)
                    time.sleep(0.5)
                    continue

                except Exception as e:
                    st.session_state.log.append(f"⚠️ Stream error: {str(e)}")
                    time.sleep(0.5)
                    continue

                # Update state jika ada perubahan jumlah orang
                if count != last_count:
                    timestamp = time.strftime("%H:%M:%S", time.localtime())
                    st.session_state.activity_history.append(f"[{timestamp}] Terdeteksi {count} orang")
                    last_count = count
                    st.session_state.count = count
                    st.session_state.lamp = 1 if count > 0 else 0

                # Kirim data ke Ubidots dengan interval lebih panjang
                now = time.time()
                if now - last_ubidots_send > 5.0:  # 5 detik
                    send_ubidots(VARIABLE_LIGHT, st.session_state.lamp)
                    send_ubidots(VARIABLE_COUNT, count)
                    
                    # Kirim status AC jika ada perubahan
                    if st.session_state.ac_power:
                        send_ubidots(VARIABLE_AC, st.session_state.ac_power)
                        send_ubidots(VARIABLE_TEMPERATURE, st.session_state.ac_temperature)
                    
                    last_ubidots_send = now

                # Baca data DHT11 setiap 30 detik
                if now - st.session_state.last_dht11_read > 30.0:
                    read_dht11_data()
                    st.session_state.last_dht11_read = now

                # Cek jadwal setiap menit
                if int(now) % 60 == 0:
                    check_and_run_schedules()

                # Kontrol otomatis AC setiap 15 detik
                if now - last_ubidots_send > 5.0 or int(now) % 15 == 0:
                    auto_control_ac()

                # Tampilkan frame dengan interval untuk mengurangi beban
                if time.time() - frame_display_time > 0.1:  # Max 10 FPS UI updates
                    cv2.putText(frame, f"Jumlah Orang: {count}", (10, 30), 
                               cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 100, 100), 2)
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    frame_placeholder.image(frame_rgb, channels="RGB", use_container_width=True)
                    frame_display_time = time.time()

                # Update UI status dengan interval lebih rendah
                if frame_count % 15 == 0:
                    status_placeholder.markdown(
                        f"👥 **Jumlah Orang:** `{count}` &nbsp;&nbsp; 💡 **Lampu:** `{'ON' if st.session_state.lamp else 'OFF'}`"
                    )
                    detail_placeholder.markdown(f"""
                    **ℹ️ Detail**  
                    - Terakhir Kirim: `{time.strftime('%H:%M:%S', time.localtime(last_ubidots_send))}`  
                    - Status Kamera: `{'Aktif' if st.session_state.camera_on else 'Nonaktif'}`  
                    - URL ESP32-CAM: `{url}`  
                    """)

                frame_count += 1
                # Log FPS dengan interval lebih jarang
                if frame_count % 50 == 0:
                    fps = 50 / (time.time() - last_frame_time)
                    last_frame_time = time.time()
                    st.session_state.log.append(f"📈 FPS: {fps:.1f}")

                # Pengontrol kecepatan loop
                time.sleep(0.01)

            except Exception as e:
                st.session_state.log.append(f"❌ Error: {str(e)}")
                time.sleep(0.1)

    except Exception as e:
        st.session_state.log.append(f"❌ Error pada sistem kamera: {str(e)}")
        st.session_state.camera_on = False

# === Info Saat Kamera Mati ===
if not st.session_state.camera_on:
    detail_placeholder.markdown(f"""
    ### ℹ️ Detail  
    - Terakhir Kirim: `{time.strftime('%H:%M:%S', time.localtime(st.session_state.get("last_sent", time.time())))}`  
    - Status Kamera: `{'Aktif' if st.session_state.camera_on else 'Nonaktif'}`  
    - URL ESP32-CAM: `{st.session_state.esp32_url}`  
    - Suhu Ruangan: `{st.session_state.current_temperature}°C`
    - Status AC: `{'ON' if st.session_state.ac_power else 'OFF'} ({st.session_state.ac_temperature}°C)`
    """)

# Tampilkan log terakhir
with st.expander("Log System", expanded=False):
    for log in st.session_state.log[-10:]:
        st.write(log)
