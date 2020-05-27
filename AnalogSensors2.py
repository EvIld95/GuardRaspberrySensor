#!/usr/bin/python
import os
import glob
import time
import spidev
import wiringpi
import pyrebase
import requests
import json
import subprocess
import signal
import os
from mq import *

url = "http://40.113.150.71:8080/backend/v1/notification"
urlPIR = "http://40.113.150.71:8080/backend/v1/PIRnotification"
urlGetOwner = "http://40.113.150.71:8080/backend/v1/devices/raspberryOwner"

headers = {'Content-type': 'application/json'}
config = {
    "apiKey": "AIzaSyCHL_Er9JtpQbadJtoaZbvYusIY-tBRVC0",
    "authDomain": "guardapp-ac65a.firebaseapp.com",
    "databaseURL": "https://guardapp-ac65a.firebaseio.com",
    "projectId": "guardapp-ac65a",
    "storageBucket": "guardapp-ac65a.appspot.com",
    "messagingSenderId": "299985780377"
}

firebase = pyrebase.initialize_app(config)
firebaseDB = firebase.database()

sendedTimestamp = {'CO2Sensor' : 0, 'COSensor': 0, 'TempSensor': 0, 'PIRSensor': 0}

os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')
wiringpi.wiringPiSetup()



#flameSensorPin = 0
pirSensorPin = 1

#wiringpi.pinMode(flameSensorPin, 0)
wiringpi.pinMode(pirSensorPin, 0)

base_dir = '/sys/bus/w1/devices/'
device_folder = glob.glob(base_dir + '28*')[0]
device_file = device_folder + '/w1_slave'

delay = 2.0
CO2Sensor = 0
COSensor = 1

previousCO2Value = 0
previousCOValue = 0
previousTemp = 0.0
previousPIR = -1

COTreshold = 0.7
CO2Treshold = 0.35
TempTreshold = 30.0

spi = spidev.SpiDev()
spi.open(0, 0)

mq = MQ()

def readadc(adcnum):
    if adcnum > 7 or adcnum < 0:
        return -1
    r = spi.xfer2([1, 8 + adcnum << 4, 0])
    data = ((r[1] & 3) << 8) + r[2]
    return data

def read_temp_raw():
    f = open(device_file, 'r')
    lines = f.readlines()
    f.close()
    return lines
 
def read_temp():
    lines = read_temp_raw()
    while lines[0].strip()[-3:] != 'YES':
        time.sleep(0.2)
        lines = read_temp_raw()
    equals_pos = lines[1].find('t=')
    if equals_pos != -1:
        temp_string = lines[1][equals_pos+2:]
        temp_c = float(temp_string) / 1000.0
        return temp_c

def normalizeValue(value):
    return value/1024

def getSerial():
  # Extract serial from cpuinfo file
  cpuserial = "0000000000000000"
  try:
    f = open('/proc/cpuinfo','r')
    for line in f:
      if line[0:6]=='Serial':
        cpuserial = line[10:26]
    f.close()
  except:
    cpuserial = "ERROR000000000"

  return cpuserial

#save raspberry serial with 
raspberrySerial = getSerial()

jsonData = {'serial': raspberrySerial}
owner = 'unknown'
while owner=='unknown':
    r = requests.post(urlGetOwner, json=jsonData, headers=headers)
    time.sleep(5)
    owner = r.json()["owner"]
    print("Waiting")
    
ownerWithoutDot = owner.replace(".", "")

dataUpdate = { "COSensor" : { "value" : 0 },
               "CO2Sensor" : { "value" : 0 },
               "TempSensor" : { "value" : 0 } }
firebaseDB.child("sensor").child(raspberrySerial).update(dataUpdate)
dataUpdate = { "isOn" : 0 }
firebaseDB.child("stream").child(raspberrySerial).update(dataUpdate)
dataUpdate = { raspberrySerial : 0 }
firebaseDB.child("devices").update(dataUpdate)
dataUpdate = { "tempTreshold" : 30.0, "CO2Treshold": 0.35, "COTreshold": 0.7, "cameraAlwaysOn": False}
match = firebaseDB.child("settings").child(ownerWithoutDot).get()
if(match.val() == None):
    firebaseDB.child("settings").child(ownerWithoutDot).update(dataUpdate)


isCameraAlwaysOn = False
cameraIsRunningAlways = False
pro = -1
def stream_handler(message):
    global pro
    global cameraIsRunningAlways
    global firebaseDB
    
    cameraAlwaysOn = firebaseDB.child("settings").child(ownerWithoutDot).child("cameraAlwaysOn").get()
    print("IsCameraAlwaysOn: ", cameraAlwaysOn.val())
    if(cameraAlwaysOn.val() == False):
        isOn = message["data"]
        if(cameraIsRunningAlways == True and pro != -1):
            os.killpg(os.getpgid(pro.pid), signal.SIGTERM)
        if(isOn == 1):
            pro = subprocess.Popen('/home/pi/Desktop/RaspberrySensor/Camera/monitoring-script/monitoring.sh', stdout=subprocess.PIPE,shell=True,preexec_fn=os.setsid)
        elif pro != -1:
            os.killpg(os.getpgid(pro.pid), signal.SIGTERM)
        cameraIsRunningAlways = False
    elif cameraIsRunningAlways == False:
        if pro != -1:
            os.killpg(os.getpgid(pro.pid), signal.SIGTERM)
        pro = subprocess.Popen('/home/pi/Desktop/RaspberrySensor/Camera/monitoring-script/monitoring.sh', stdout=subprocess.PIPE,shell=True,preexec_fn=os.setsid)
        cameraIsRunningAlways = True

         
        

def checkIfSendInfoNotificationAllowed():
    for item in allData:
        if (time.time() - sendedTimestamp[item['sensorType']] > 60):
            return True
    return False

def settingsStream_handler(message):
    global COTreshold
    global CO2Treshold
    global TempTreshold
    global isCameraAlwaysOn
    COTreshold = message["data"]["COTreshold"]
    CO2Treshold = message["data"]["CO2Treshold"]
    TempTreshold = message["data"]["tempTreshold"]
    isCameraAlwaysOn = message["data"]["cameraAlwaysOn"]
    
my_settingsStream = firebaseDB.child("settings").child(ownerWithoutDot).stream(settingsStream_handler)
my_stream = firebaseDB.child("stream").child(raspberrySerial).child("isOn").stream(stream_handler)

def getPPM(volts):
    zeroPointVoltage = 0.325
    DCGain = 6
    CO2Curve = [2.602, zeroPointVoltage, 0.2/(2.602-3)] 
    if ((volts/DCGain) < zeroPointVoltage):
        return pow(10, ((volts/DCGain)-CO2Curve[1])/CO2Curve[2]+CO2Curve[0])
    else:
        return 0

while True:
    #valuePIR = int(wiringpi.digitalRead(pirSensorPin)) 
    CO2value = readadc(CO2Sensor)
    print("CO2 Sensor analog read: ", CO2value)
    CO2value = getPPM((CO2value/1024)*5)
    if CO2value == 0:
        CO2value = 399

    perc = mq.MQPercentage()
    
    tempValue = read_temp()
    print("Temp Value %f" % tempValue)
    print("CO2Sensor ppm: %d" % CO2value)
        
    #COValue = readadc(COSensor)
    COValue = perc["CO"]
    print("COSensor: %g ppm" % perc["CO"])
    time.sleep(delay)
        
    if(abs(COValue - previousCOValue) > 20):
        dataUpdate = { "COSensor" : { "value" : normalizeValue(float(COValue)) } }
        firebaseDB.child("sensor").child(raspberrySerial).update(dataUpdate)

    if(abs(CO2value - previousCO2Value) > 10):
        dataUpdate = { "CO2Sensor" : { "value" : float(CO2value) } }
        firebaseDB.child("sensor").child(raspberrySerial).update(dataUpdate)

    if(tempValue != previousTemp):
        dataUpdate = { "TempSensor" : { "value" : tempValue } }
        firebaseDB.child("sensor").child(raspberrySerial).update(dataUpdate)

    allData = []
    if(COValue > COTreshold*1024):
        data = { "serial" : raspberrySerial, "sensorType" : "COSensor", "value" : COValue }
        allData.append(data)
        
    if(CO2value < CO2Treshold*1024):
        data = { "serial" : raspberrySerial, "sensorType" : "CO2Sensor", "value" : CO2value }
        allData.append(data)
        
    if(tempValue > TempTreshold):
        data = { "serial" : raspberrySerial, "sensorType" : "TempSensor", "value" : tempValue }
        allData.append(data)       
    
    if allData != [] and checkIfSendInfoNotificationAllowed():
        requests.post(url, json=allData, headers=headers)
        for item in allData:
            sendedTimestamp[item['sensorType']] = time.time()
        
    previousCO2Value = CO2value
    previousCOValue = COValue
    previousTemp = tempValue



    
