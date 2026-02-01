import RPi.GPIO as GPIO
import time

GPIO.setmode(GPIO.BCM) 
GPIO.setup(25, GPIO.IN) 

print("Leyendo GPIO 25... (Ctrl+C para salir)")

try:
    while True:
        estado = GPIO.input(25)
        if estado == GPIO.HIGH:
            print("⚡ GPIO 25 en HIGH (1)")
        else:
            print("⚫ GPIO 25 en LOW (0)")
        
        time.sleep(0.5) # Lee cada medio segundo

except KeyboardInterrupt:
    GPIO.cleanup()