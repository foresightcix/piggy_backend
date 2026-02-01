import os
import io
import json, time
import threading
import asyncio
import requests
import sounddevice as sd
import soundfile as sf
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_async_client 
from serial_test import enviar_dato_serial


load_dotenv()

INPUT_CTRL = True  # <--- TRUE = Botón GPIO, FALSE = Teclado (Enter/Ctrl+C)
GPIO_PIN = 25      # Pin físico del botón
SAMPLE_RATE = 44100

# IDs y URLs
SUPABASE_URL = "https://mntnwbnpnsgyvmybfuqn.supabase.co"
SUPABASE_KEY = "sb_publishable_EFKqBeNCOHx47vyFv2-2KA_fR3hQkrp" # Necesitas la KEY publica (anon) o service_role
USUARIO_ID = "d4266198-2e99-41df-8b98-0793da30944c" # ID del niño para las pruebas
CUENTA_PRINCIPAL_ID = "30c0bcf3-2dee-4d85-a5c4-568e81fc3eab"         # ID de la billetera origen
BASE_URL = "https://mntnwbnpnsgyvmybfuqn.supabase.co/functions/v1/"


# --- ⚙️ CONFIGURACIÓN ---
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

try:
    import RPi.GPIO as GPIO
    if INPUT_CTRL:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(GPIO_PIN, GPIO.IN)
except ImportError:
    print("⚠️ RPi.GPIO no encontrado. Forzando modo Teclado.")
    INPUT_CTRL = False

def esperar_activacion():
    """
    Bloquea el flujo hasta que el usuario dé la señal de inicio.
    - Modo GPIO: Espera flanco de bajada (apretar botón).
    - Modo Teclado: Espera ENTER.
    """
    if not INPUT_CTRL:
        input("\n⌨️  [ENTER] para empezar a hablar...")
        return

    print(f"\n🔘 [Esperando BOTÓN en GPIO {GPIO_PIN} para hablar...]")
    
    # Bucle de espera no bloqueante (permite que Ctrl+C mate el script)
    while True:
        # Si el botón baja a 0 (LOW), es que se presionó
        if GPIO.input(GPIO_PIN) == GPIO.LOW:
            # Pequeño debounce para evitar falsos positivos
            time.sleep(0.05)
            if GPIO.input(GPIO_PIN) == GPIO.LOW:
                return # Salimos de la espera, comenzamos a grabar
        time.sleep(0.1)

def debe_seguir_grabando():
    """
    Devuelve True si debemos seguir grabando, False si debemos parar.
    - Modo GPIO: Devuelve True mientras el botón siga presionado (LOW).
    - Modo Teclado: Siempre True (el stop se maneja por excepción KeyboardInterrupt).
    """
    if not INPUT_CTRL:
        return True
    
    # En modo GPIO, seguimos grabando solo si el botón sigue presionado (LOW)
    return GPIO.input(GPIO_PIN) == GPIO.LOW

# --- ⚡ REALTIME CALLBACK (Lo que pasa cuando llega dinero) ---
def procesar_cambio_realtime(payload):
    """
    Parsea el payload específico de la librería Realtime de Python.
    Estructura: payload['data']['record']
    """
    try:
        enviar_dato_serial(3)
        # 1. Normalización: Aseguramos que sea un diccionario accesible
        # Si la librería devuelve un objeto complejo, intentamos convertirlo
        datos = payload
        if hasattr(payload, 'model_dump'): # Pydantic v2 (común en libs modernas)
            datos = payload.model_dump()
        elif hasattr(payload, '__dict__'):
            datos = payload.__dict__
            
        # 2. Navegación: Entramos a 'data' -> 'record'
        # (Basado en tu log: {'data': {'record': {...}}})
        info_realtime = datos.get('data', {})
        registro = info_realtime.get('record', {})

        if not registro:
            # A veces llegan eventos de 'system' sin registro, los ignoramos
            return

        # 3. Extracción de datos
        # Convertimos a str() por seguridad para comparar UUIDs
        destino_id = str(registro.get('cuenta_destino_id'))
        monto = registro.get('monto')
        descripcion = registro.get('descripcion') or "un depósito"

        # Debug para ver qué está leyendo (puedes borrarlo luego)
        # print(f"DEBUG: Destino={destino_id} | Monto={monto}")

        # 4. Lógica de negocio: ¿Es para mí?
        # Asegúrate de que CUENTA_PRINCIPAL_ID sea un string en tus constantes
        if destino_id == str(CUENTA_PRINCIPAL_ID):
            print(f"\n🔔 REALTIME: ¡Llegaron {monto} soles!")
            
            frase = f"¡Oink! Acaban de llegar {monto} soles para ti."
            
            # Hablar inmediatamente
            hablar_chanchito(frase)
            print("\n🎤 [ENTER] para hablar...")

    except Exception as e:
        print(f"❌ Error procesando payload: {e}")
        # Tip: Imprime el payload crudo si vuelve a fallar para diagnosticar
        # print(payload)
    finally:
        enviar_dato_serial(1)

async def motor_realtime_async():
    print("📡 Iniciando conexión Async con Supabase...")
    
    # 1. Crear cliente
    async_supabase = await create_async_client(SUPABASE_URL, SUPABASE_KEY)
    
    # 2. Wrapper para conectar el callback
    def callback_wrapper(payload):
        procesar_cambio_realtime(payload)

    # 3. Suscribirse
    channel = async_supabase.channel('cambios_movimientos')
    await channel.on_postgres_changes(
        event="INSERT",
        schema="public",
        table="movimientos",
        callback=callback_wrapper
    ).subscribe()

    print("✅ Escuchando cambios en tiempo real.")

    # 4. Mantener vivo el loop asíncrono
    while True:
        await asyncio.sleep(1)

def iniciar_hilo_realtime():
    """Lanza el proceso asíncrono en un hilo separado para no bloquear el micrófono"""
    def run_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(motor_realtime_async())

    hilo = threading.Thread(target=run_loop, daemon=True)
    hilo.start()

# --- 🔌 CAPA DE CONEXIÓN (APIs) ---

def consultar_cuentas_api(usuario_id):
    endpoint = "account-resume"
    url = f"{BASE_URL}{endpoint}"
    print(f"📡 Consultando: {url}")
    
    try:
        # Usamos POST con params como indicaste en tu snippet anterior
        response = requests.post(url, params={"usuario_id": usuario_id})
        if response.status_code == 200:
            return response.json()
        return {"error": response.text}
    except Exception as e:
        return {"error": str(e)}

def realizar_transaccion_api(destino, monto, descripcion):
    endpoint = "transaction"
    url = f"{BASE_URL}{endpoint}"
    print(f"📡 Transacción: {url}")

    params = {
        "usuario_id": USUARIO_ID,
        "origen": CUENTA_PRINCIPAL_ID,
        "destino": destino,
        "monto": monto,
        "descripcion": descripcion
    }
    try:
        response = requests.post(url, params=params)
        if response.status_code == 200:
            return response.json()
        return {"error": response.text}
    except Exception as e:
        return {"error": str(e)}

def crear_meta_api(meta_monto, nombre_meta):
    endpoint = "create-savings-account"
    url = f"{BASE_URL}{endpoint}"
    print(f"📡 Creando Meta: {url}")

    params = {
        "usuario_id": USUARIO_ID,
        "meta": meta_monto,
        "nombre_meta": nombre_meta
    }
    try:
        response = requests.post(url, params=params)
        if response.status_code == 200:
            return response.json()
        return {"error": response.text}
    except Exception as e:
        return {"error": str(e)}

# --- 🧠 LÓGICA DE HERRAMIENTAS (Tools GPT) ---

def tool_crear_meta(monto, motivo):
    """Acción: El niño crea una meta."""
    resultado = crear_meta_api(monto, motivo)
    return json.dumps(resultado)

def tool_consultar_ahorros():
    """Acción: El niño pregunta cuánto tiene."""
    datos = consultar_cuentas_api(USUARIO_ID)
    return json.dumps(datos)

def tool_enviar_dinero_a_meta(monto, nombre_meta):
    """
    Acción: Mover dinero a una meta.
    LÓGICA: Busca el ID basándose en 'meta_descripcion' del JSON de la API.
    """
    print(f"🔍 Buscando meta '{nombre_meta}' en la lista de cuentas...")
    
    # 1. Obtenemos el JSON completo
    datos = consultar_cuentas_api(USUARIO_ID)
    
    # 2. Accedemos a la lista correcta 'mis_cuentas'
    # Si la API da error o no trae la lista, usamos una lista vacía para no romper el código
    lista_cuentas = datos.get('mis_cuentas', [])
    
    id_destino = None
    meta_encontrada_nombre = ""

    # 3. Iteramos buscando coincidencias
    for cuenta in lista_cuentas:
        # Extraemos la descripción (ej: "cine", "celular")
        descripcion_db = cuenta.get('meta_descripcion')
        
        # Verificamos que no sea None (la cuenta 'simple' tiene None)
        if descripcion_db:
            # Comparamos ignorando mayúsculas/minúsculas
            # Ej: Si niño dice "Cine" y en DB está "cine", esto da True
            if nombre_meta.lower() in descripcion_db.lower():
                id_destino = cuenta.get('id')
                meta_encontrada_nombre = descripcion_db
                break
            
    # 4. Manejo de error si NO existe la meta
    if not id_destino:
        print(f"❌ No se encontró la meta '{nombre_meta}'")
        # Devolvemos un JSON explicativo para que GPT sepa qué decirle al niño
        return json.dumps({
            "error": "meta_no_encontrada",
            "mensaje": f"No encontré ninguna meta con el nombre '{nombre_meta}'.",
            "cuentas_disponibles": [c.get('meta_descripcion') for c in lista_cuentas if c.get('meta_descripcion')]
        })

    # 5. Si SÍ existe, ejecutamos la transacción
    print(f"✅ Meta encontrada: {meta_encontrada_nombre} (ID: {id_destino})")
    
    resultado = realizar_transaccion_api(
        destino=id_destino,
        monto=monto,
        descripcion=f"Ahorro enviado a {meta_encontrada_nombre}"
    )
    return json.dumps(resultado)

# Schema para OpenAI
tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "crear_meta",
            "description": "Crea una meta de ahorro nueva.",
            "parameters": {
                "type": "object",
                "properties": {
                    "monto": {"type": "number"},
                    "motivo": {"type": "string"}
                },
                "required": ["monto", "motivo"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_ahorros",
            "description": "Consulta solo el saldo total ahorrado."
        }
    },
    {
        "type": "function",
        "function": {
            "name": "enviar_dinero_a_meta",
            "description": "Envía dinero a una meta existente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "monto": {"type": "number"},
                    "nombre_meta": {"type": "string"}
                },
                "required": ["monto", "nombre_meta"]
            }
        }
    }
]

# --- 🔊 AUDIO (Input/Output) ---
def grabar_audio():
    print("🔴 GRABANDO... (Suelta el botón / Ctrl+C para terminar)")
    audio_data = []
    
    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16') as stream:
            while True:
                # 1. Leemos audio del micro
                data, overflow = stream.read(1024)
                audio_data.append(data)
                
                # 2. Verificamos condición de parada
                if not debe_seguir_grabando():
                    print("✅ Botón soltado. Procesando...")
                    break
                    
    except KeyboardInterrupt:
        if INPUT_CTRL: print("\n⚠️ Interrupción manual.")
        else: print("\n✅ Grabación finalizada (Teclado).")

    if not audio_data or len(audio_data) < 2: return None
    
    full_audio = np.concatenate(audio_data, axis=0)
    wav_buffer = io.BytesIO()
    sf.write(wav_buffer, full_audio, SAMPLE_RATE, format='WAV')
    wav_buffer.seek(0)
    wav_buffer.name = "audio.wav"

    return wav_buffer

def transcribir_audio(audio_buffer):
    # El prompt guía el estilo. Le damos ejemplos de "Soles con céntimos"
    prompt_contexto = "El precio es 3.50, 4.90, 1.20 soles. Quiero ahorrar 10.50. Gasté 4.90."
    
    return client.audio.transcriptions.create(
        model="whisper-1", 
        file=audio_buffer, 
        language="es",
        prompt=prompt_contexto # <--- ESTO HACE LA MAGIA
    ).text

def hablar_chanchito(texto):
    print(f"🐷 Chanchito dice: {texto}")
    try:
        response = client.audio.speech.create(
            model="tts-1-hd",
            voice="nova", # Voz infantil/amable
            input=texto
        )
        # Reproducción segura en memoria
        audio_bytes = io.BytesIO(response.content)
        data, fs = sf.read(audio_bytes)
        sd.play(data, fs)
        sd.wait()
    except Exception as e:
        print(f"❌ Error audio: {e}")


# --- 🚀 BUCLE PRINCIPAL ---

def main():

    iniciar_hilo_realtime()

    print("🐷 SISTEMA CHANCHITO ACTIVO")
    print(f"🕹️  MODO DE CONTROL: {'BOTÓN GPIO' if INPUT_CTRL else 'TECLADO'}")
    
    system_prompt = """
    Eres el 'Chanchito', una alcancía mágica con acento peruano amigable.
    Tu misión es ser ULTRA BREVE y reaccionar según la acción que acabas de realizar.

    🚨 REGLA DE ORO DE MONEDA (IMPORTANTE):
    1. **PRESUPOSICIÓN**: "3.50" son SOLES. "$20" son SOLES. Solo si dicen "Dólares" cambia la moneda.
    2. **INTERPRETACIÓN**: Si dicen "uno veinte", asume que es 1.20 (1 sol con 20 céntimos).

    🎙️ REGLA DE FORMATO PARA TU VOZ (OBLIGATORIO):
    Como vas a ser leído por un sintetizador de voz, NUNCA escribas cifras decimales simples (como "1.20 soles"). DEBES ESCRIBIRLO ASÍ:
    - **Singular:** No digas "1 soles". Di **"1 sol"** o **"1 sol con 20 céntimos"**.
    - **Plural:** Di **"5 soles"** o **"5 soles con 50 céntimos"**.
    - **Solo céntimos:** Di **"20 céntimos"** (no "0.20 soles").
    - **Ejemplo Incorrecto:** "Listos tus 1.20 soles".
    - **Ejemplo Correcto:** "Listos tu sol con veinte céntimos".

    REGLAS DE COMPORTAMIENTO SEGÚN LA ACCIÓN:

    1. **SI ACABAS DE AHORRAR (`enviar_dinero_a_meta`):**
    - ¡NO DIGAS EL SALDO TOTAL!
    - Solo confirma el monto y la meta.
    - Ejemplo: "¡Oink! Guardado tu sol con 50 céntimos para la bicicleta."

    2. **SI ACABAS DE CREAR UNA META (`crear_meta`):**
    - Celebra la nueva ilusión.
    - Ejemplo: "¡Genial! Meta creada. ¡A juntar esos soles!"

    3. **SI SOLO CONSULTAN SALDO (`consultar_ahorros`):**
    - Di el Gran Total primero, luego "para gastar" y agrupa el resto en "ahorros".
    - Ejemplo: "Tienes 100 soles en total. 20 soles con 50 céntimos para gastar."

    4. **SI ES EDUCACIÓN O CHARLA:**
    - Responde en 1 sola frase simpática.

    REGLA GENERAL:
    - ¡Sé entusiasta pero muy corto! (Máximo 2 frases).
    """

    while True:

        esperar_activacion()
        
        # 1. Escuchar
        
        enviar_dato_serial(2)
        audio = grabar_audio()
        #enviar_dato_serial(1)

        if not audio: continue
        else: enviar_dato_serial(1)
        
        enviar_dato_serial(3)
        texto_usuario = transcribir_audio(audio)
        print(f"🗣️  Niño: {texto_usuario}")

        if not texto_usuario: continue

        # 2. Pensar
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": texto_usuario}
        ]
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=tools_schema,
            tool_choice="auto"
        )
        mensaje_ia = response.choices[0].message
        
        # 3. Ejecutar Herramientas (si aplica)
        if mensaje_ia.tool_calls:
            messages.append(mensaje_ia)
            
            for tool in mensaje_ia.tool_calls:
                fn_name = tool.function.name
                args = json.loads(tool.function.arguments)
                
                print(f"⚙️ Ejecutando: {fn_name}...")
                
                if fn_name == "crear_meta":
                    res = tool_crear_meta(args["monto"], args["motivo"])
                elif fn_name == "consultar_ahorros":
                    res = tool_consultar_ahorros()
                elif fn_name == "enviar_dinero_a_meta":
                    res = tool_enviar_dinero_a_meta(args["monto"], args["nombre_meta"])
                else:
                    res = "{}"

                messages.append({
                    "tool_call_id": tool.id,
                    "role": "tool",
                    "name": fn_name,
                    "content": str(res)
                })

            # Generar respuesta final hablada post-herramienta
            final_response = client.chat.completions.create(
                model="gpt-4o", messages=messages
            )
            texto_final = final_response.choices[0].message.content
            hablar_chanchito(texto_final)
            enviar_dato_serial(1)
            
        else:
            # Respuesta directa (Educación financiera / Charla)
            hablar_chanchito(mensaje_ia.content)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 ¡Oink bye!")