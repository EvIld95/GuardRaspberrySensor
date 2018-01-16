#!/usr/bin/python
import os
import glob
import time
import spidev
import wiringpi
import pyrebase
import requests
import json

url = "http://52.236.165.15:80/backend/v1/notification"
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

sendedTimestamp = {'LPGSensor' : 0, 'COSensor': 0, 'TempSensor': 0, 'FlameSensor': 0}

os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')
wiringpi.wiringPiSetup()

flameSensorPin = 0
wiringpi.pinMode(flameSensorPin, 0)

base_dir = '/sys/bus/w1/devices/'
device_folder = glob.glob(base_dir + '28*')[0]
device_file = device_folder + '/w1_slave'

delay = 2.0
LPGSensor = 0
COSensor = 1

previousLPGValue = 0
previousCOValue = 0
previousTemp = 0.0
previousFlame = -1

spi = spidev.SpiDev()
spi.open(0, 0)

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
dataUpdate = { "COSensor" : { "value" : 0 },
               "LPGSensor" : { "value" : 0 },
               "FlameSensor" : { "value" : 0 },
               "TempSensor" : { "value" : 0 } }
firebaseDB.child("sensor").child(raspberrySerial).update(dataUpdate)


while True:
    
    print("----Kolejny pomiar-------")
    valueFlame = int(not wiringpi.digitalRead(flameSensorPin))
    LPGvalue = readadc(LPGSensor)
    tempValue = read_temp()
    print("Temp Value %f" % tempValue)
    print("LPGSensor: %d" % LPGvalue)
    if(valueFlame == 0):
        print("FlameSensor: OK!")
    else:
        print("FlameSensor: Detected Fire!")
    
    COValue = readadc(COSensor)
    print("COSensor: %d" % COValue)
    time.sleep(delay)
        
    if(abs(COValue - previousCOValue) > 30):
        dataUpdate = { "COSensor" : { "value" : normalizeValue(float(COValue)) } }
        firebaseDB.child("sensor").child(raspberrySerial).update(dataUpdate)

    if(abs(LPGvalue - previousLPGValue) > 30):
        dataUpdate = { "LPGSensor" : { "value" : normalizeValue(float(LPGvalue)) } }
        firebaseDB.child("sensor").child(raspberrySerial).update(dataUpdate)

    if(previousFlame != valueFlame):
        dataUpdate = { "FlameSensor" : { "value" : valueFlame } }
        firebaseDB.child("sensor").child(raspberrySerial).update(dataUpdate)

    if(tempValue != previousTemp):
        dataUpdate = { "TempSensor" : { "value" : tempValue } }
        firebaseDB.child("sensor").child(raspberrySerial).update(dataUpdate)

    allData = []
    if(COValue > 0.3*1024):
        data = { "serial" : raspberrySerial, "sensorType" : "COSensor", "value" : COValue }
        allData.append(data)
        
    if(LPGvalue > 0.3*1024):
        data = { "serial" : raspberrySerial, "sensorType" : "LPGSensor", "value" : LPGvalue }
        allData.append(data)
        
    if(valueFlame > 0):
        data = { "serial" : raspberrySerial, "sensorType" : "FlameSensor", "value" : valueFlame }
        allData.append(data)
        
    if(tempValue > 30):
        data = { "serial" : raspberrySerial, "sensorType" : "TempSensor", "value" : tempValue }
        allData.append(data)

    if allData != []:
        print((time.time() - sendedTimestamp[allData[0]['sensorType']]))        
    
    if allData != [] and (time.time() - sendedTimestamp[allData[0]['sensorType']] > 60):
        requests.post(url, json=allData, headers=headers)
        for item in allData:
            sendedTimestamp[item['sensorType']] = time.time()
        print("Send notification")
    previousLPGValue = LPGvalue
    previousCOValue = COValue
    previousTemp = tempValue
    previousFlame = valueFlame



    
