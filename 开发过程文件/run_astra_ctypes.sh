#!/bin/bash
# 使用 Astra SDK 自带的 OpenNI2 库运行 ctypes 版本

export DISPLAY=:0
export LD_LIBRARY_PATH=/home/sunrise/AstraSDK/lib:/home/sunrise/AstraSDK/lib/Plugins/openni2:$LD_LIBRARY_PATH

cd /home/sunrise/Projects/usb_hobot_stereonet
sudo -E python3 astra_ctypes_depth.py
