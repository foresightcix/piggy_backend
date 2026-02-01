import serial
import time
import os
from dotenv import load_dotenv

# Configuración del puerto
# /dev/ttyS0 es el puerto serial por defecto en RPi 3/4/Zero con Bluetooth
# /dev/ttyAMA0 es el puerto serial en RPi antiguas o si desactivas Bluetooth

load_dotenv()
PORT = os.getenv('SERIAL_PORT', '/dev/ttyS0')
BAUD = int(os.getenv('SERIAL_BAUDRATE', 9600))

def enviar_dato_serial(dato: int=0):
    """
    Envía un dato por el puerto serial definido en el .env
    """
    try:
        with serial.Serial(PORT, BAUD, timeout=1) as ser:
            time.sleep(2) 
            if ser.is_open:
                dato_codificado = str(dato).encode('utf-8')
                ser.write(dato_codificado)
                print(f"Éxito: Se envió '{dato}' al puerto {PORT} | baud {BAUD}")
            else:
                print("Error: No se pudo abrir el puerto.")
                
    except serial.SerialException as e:
        print(f"Error de conexión serial: {e}")
    except Exception as e:
        print(f"Ocurrió un error inesperado: {e}")

if __name__ == "__main__":
    numero = input("Ingresa el número a enviar: ")
    enviar_dato_serial(numero)