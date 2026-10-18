import serial
import time

arduino = serial.Serial("/dev/ttyACM0", 115200, timeout=1)
time.sleep(2)

def command(text):
    arduino.write((text + "\n").encode())
    print("Sent:", text)

command("SPEED 500")

command("MOVE 90")
time.sleep(3)

command("MOVE -90")
time.sleep(3)

command("MOVE 15.5")

arduino.close()
