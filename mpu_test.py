import os
import smbus2
import time
import math
import requests
import json
import io
import sounddevice as sd
import soundfile as sf
from serial_test import enviar_dato_serial
from openai import OpenAI
from dotenv import load_dotenv

# --- 1. CONFIGURACIÓN E INICIO ---
load_dotenv() 

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_FUNCTION_URL = os.getenv("SUPABASE_FUNCTION_URL")
USUARIO_ID = os.getenv("USUARIO_ID")

client = OpenAI(api_key=OPENAI_API_KEY)

# --- ⚙️ CALIBRACIÓN DEL GESTO ---
UMBRAL_ALTO = 250.0        # Valor para considerar "Pico" (El "90" que pediste)
UMBRAL_BAJO = 30.0        # Valor para considerar "Descenso" (Debe bajar de esto para validar)
TIEMPO_MAXIMO = 3.0       # Tienes 3 segundos para completar la secuencia Pico -> Bajo -> Pico

# --- CONFIGURACIÓN MPU6050 ---
ADDR = 0x68
PWR_MGMT_1 = 0x6B
GYRO_SCALE = 131.0 

def init_mpu(bus):
    bus.write_byte_data(ADDR, PWR_MGMT_1, 0)

def read_raw_data(bus, addr):
    high = bus.read_byte_data(ADDR, addr)
    low = bus.read_byte_data(ADDR, addr+1)
    val = (high << 8) | low
    if val > 32768:
        val = val - 65536
    return val

# --- 2. CEREBRO (API + GPT) ---

def consultar_ultimo_movimiento():
    endpoint = f"{SUPABASE_FUNCTION_URL}/last-transaction"
    params = {"solicitante_id": USUARIO_ID}
    print(f"📡 Consultando API...")
    try:
        response = requests.post(endpoint, params=params, timeout=5)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"❌ Error API: {e}")
        return None

def humanizar_respuesta(datos_json):
    if not datos_json:
        return "Lo siento, no pude conectar con tu alcancía."

    print("🧠 Generando respuesta...")
    try:
        # Prompt con tus reglas de oro
        prompt = f"""
        Eres el 'Chanchito', una alcancía mágica peruana.
        Dato técnico: {json.dumps(datos_json)}
        
        🎙️ REGLAS DE VOZ:
        1. Asume SOLES peruanos.
        2. NO digas "1.50 soles", di "Un sol con cincuenta céntimos".
        3. Sé muy breve (1 frase).
        4. Celebra si es ingreso, informa si es gasto.
        5. No menciones cuentas, ids, ni nigun dato tecnico 
        
        Ejemplo: "¡Oink! Tu último movimiento fue un gasto de diez soles con noventa céntimos en helados."
        """
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error GPT: {e}")
        return "Hubo un error técnico."

def hablar(texto):
    print(f"🔊 Chanchito dice: '{texto}'")
    try:
        response = client.audio.speech.create(
            model="tts-1", voice="fable", input=texto
        )
        audio_bytes = io.BytesIO(response.content)
        data, fs = sf.read(audio_bytes)
        sd.play(data, fs)
        sd.wait()
    except Exception as e:
        print(f"❌ Error Audio: {e}")

# --- 3. BUCLE PRINCIPAL (MÁQUINA DE ESTADOS) ---
def main():
    try:
        bus = smbus2.SMBus(1)
        init_mpu(bus)
        
        print("\n🐷 SENSOR ACTIVO: Modo Doble-Shake")
        print(f"ℹ️  Instrucción: Agitar (> {UMBRAL_ALTO}) -> Pausa (< {UMBRAL_BAJO}) -> Agitar (> {UMBRAL_ALTO})")
        print(f"⏱️  Tiempo límite: {TIEMPO_MAXIMO} segundos")
        
        # Variables de estado
        estado = 0  # 0: Esperando 1er pico, 1: Esperando bajada, 2: Esperando 2do pico
        tiempo_inicio_secuencia = 0
        
        enviar_dato_serial(1) # Cara normal
        time.sleep(1)

        while True:

            # --- GIROSCOPIO ---
            gx = read_raw_data(bus, 0x43) / GYRO_SCALE
            gy = read_raw_data(bus, 0x45) / GYRO_SCALE
            gz = read_raw_data(bus, 0x47) / GYRO_SCALE
            
            # Magnitud del movimiento
            giro_total = math.sqrt(gx**2 + gy**2 + gz**2)
            current_time = time.time()

            # --- RESET POR TIEMPO ---
            # Si estamos en medio de una secuencia (estado > 0) y pasó el tiempo límite
            if estado > 0 and (current_time - tiempo_inicio_secuencia > TIEMPO_MAXIMO):
                print("⏳ Tiempo agotado. Secuencia cancelada.")
                estado = 0 # Volver al inicio

            # --- MÁQUINA DE ESTADOS ---
            
            # Estado 0: Esperando el PRIMER sacudón fuerte
            if estado == 0:
                if giro_total > UMBRAL_ALTO:
                    print(f"1️⃣  Primer pico detectado! ({giro_total:.0f}) -> Esperando descenso...")
                    estado = 1
                    tiempo_inicio_secuencia = current_time
            
            # Estado 1: Esperando que el usuario frene o baje la mano (Descenso)
            elif estado == 1:
                if giro_total < UMBRAL_BAJO:
                    # Solo avanzamos si realmente bajó la intensidad
                    print(f"📉  Descenso confirmado ({giro_total:.0f}) -> ¡Dale el segundo golpe!")
                    estado = 2
            
            # Estado 2: Esperando el SEGUNDO sacudón fuerte
            elif estado == 2:
                if giro_total > UMBRAL_ALTO:
                    print(f"2️⃣  Segundo pico detectado! ({giro_total:.0f}) -> ✅ ¡ACCIÓN!")
                    
                    # --- EJECUTAR ACCIÓN ---
                    enviar_dato_serial(3) # Cara procesando
                    
                    datos = consultar_ultimo_movimiento()
                    frase = humanizar_respuesta(datos)
                    hablar(frase)
                    
                    # --- RESET FINAL ---
                    print("💤 Enfriando sensor...")
                    enviar_dato_serial(1)
                    time.sleep(2) # Pausa para evitar rebotes
                    estado = 0 # Reiniciamos lógica
                    print("✅ Listo para nueva secuencia.\n")

            time.sleep(0.05) # Muestreo rápido

    except KeyboardInterrupt:
        print("\n👋 Apagando.")
        try: enviar_dato_serial(0) 
        except: pass
    except Exception as e:
        print(f"\n❌ Error crítico: {e}")

if __name__ == "__main__":
    main()