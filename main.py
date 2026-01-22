import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
import requests
import io
import pygame
import threading
import time

# --- CONFIGURACIÓN ---
SUPABASE_URL = "https://TU_ID_PROYECTO.supabase.co/functions/v1/cerebro-voz"
SUPABASE_KEY = "TU_ANON_KEY_AQUI"

# Configuración de Audio (Optimizado para Whisper)
SAMPLE_RATE = 16000  # 16kHz es suficiente y más ligero que 44.1kHz
CHANNELS = 1         # Mono (menos datos que enviar)
DTYPE = 'int16'      # Formato estándar

# Variable para controlar la grabación
grabando = False
audio_data = []

def grabar_audio():
    """Hilo que se encarga de llenar el buffer de audio mientras 'grabando' sea True"""
    global audio_data
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE) as stream:
        print("\n👂 ESCUCHANDO... (Habla ahora)")
        while grabando:
            # Leemos chunks de 1024 frames
            data, overflowed = stream.read(1024)
            audio_data.append(data)

def reproducir_respuesta(audio_bytes):
    """Reproduce el MP3 recibido directamente desde la memoria RAM"""
    print("🗣️ REPRODUCIENDO RESPUESTA...")
    
    # Inicializar mixer de pygame
    pygame.mixer.init()
    
    # Cargar bytes en un objeto de archivo virtual (en memoria)
    sonido_virtual = io.BytesIO(audio_bytes)
    
    try:
        pygame.mixer.music.load(sonido_virtual)
        pygame.mixer.music.play()
        
        # Esperar a que termine de hablar
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
            
    except Exception as e:
        print(f"Error reproduciendo audio: {e}")

def main():
    global grabando, audio_data
    
    print("--- 🎙️ CLIENTE DE VOZ FINANCIERO ---")
    print("Este script graba tu voz, la envía a Supabase y reproduce la respuesta.")

    while True:
        try:
            input("\n🔴 Presiona [ENTER] para empezar a hablar...")
            
            # 1. INICIAR GRABACIÓN
            audio_data = [] # Limpiar buffer anterior
            grabando = True
            
            # Usamos un hilo para no bloquear el input de "parar"
            t = threading.Thread(target=grabar_audio)
            t.start()
            
            input("⬛ Presiona [ENTER] para enviar consulta...")
            grabando = False # Esto detiene el while del hilo
            t.join() # Esperamos a que el hilo cierre limpio
            
            print("🚀 PROCESANDO Y ENVIANDO AUDIO...")

            # 2. CONVERTIR A WAV EN MEMORIA
            # Concatenamos todos los fragmentos de audio
            recording = np.concatenate(audio_data, axis=0)
            
            # Crear un archivo WAV virtual en memoria RAM
            wav_virtual = io.BytesIO()
            wav.write(wav_virtual, SAMPLE_RATE, recording)
            wav_virtual.seek(0) # Rebobinar al inicio del archivo virtual

            # 3. ENVIAR A SUPABASE
            headers = { "Authorization": f"Bearer {SUPABASE_KEY}" }
            files = { 
                "file": ("consulta.wav", wav_virtual, "audio/wav") 
            }

            inicio_req = time.time()
            response = requests.post(SUPABASE_URL, headers=headers, files=files)
            fin_req = time.time()

            if response.status_code == 200:
                print(f"✅ Respuesta recibida en {round(fin_req - inicio_req, 2)} segs")
                
                # 4. REPRODUCIR RESPUESTA
                reproducir_respuesta(response.content)
            else:
                print(f"❌ Error del servidor: {response.status_code} - {response.text}")

        except KeyboardInterrupt:
            print("\n👋 Saliendo...")
            break

if __name__ == "__main__":
    main()