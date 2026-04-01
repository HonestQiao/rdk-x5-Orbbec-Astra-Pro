#!/usr/bin/env python3
"""简化测试 - Astra SDK ctypes"""
import ctypes
import os
import sys

os.environ['DISPLAY'] = ':0'
os.environ['LD_LIBRARY_PATH'] = '/home/sunrise/AstraSDK/lib:/home/sunrise/AstraSDK/lib/Plugins/openni2:' + os.environ.get('LD_LIBRARY_PATH', '')

sys.path.insert(0, '/home/sunrise/AstraSDK/lib')
sys.path.insert(0, '/home/sunrise/AstraSDK/lib/Plugins/openni2')

print("Loading libraries...")
ctypes.CDLL('/home/sunrise/AstraSDK/lib/libastra_core.so', ctypes.RTLD_GLOBAL)
astra_core = ctypes.CDLL('/home/sunrise/AstraSDK/lib/libastra_core.so')
astra = ctypes.CDLL('/home/sunrise/AstraSDK/lib/libastra.so')
print("Libraries loaded")

print("Initializing Astra...")
rc = astra_core.astra_initialize()
print(f"astra_initialize: rc={rc}")

if rc != 0:
    print("Failed to initialize")
    exit(1)

sensor = ctypes.c_void_p()
print("Opening device...")
rc = astra_core.astra_streamset_open(b"device/default", ctypes.byref(sensor))
print(f"astra_streamset_open: rc={rc}, sensor={sensor.value}")

if rc != 0:
    print("Failed to open device")
    astra_core.astra_terminate()
    exit(1)

print("SUCCESS! Device opened")
astra_core.astra_streamset_close(sensor)
astra_core.astra_terminate()
print("Cleanup done")
