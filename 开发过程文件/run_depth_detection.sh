#!/bin/bash
# Astra Pro 深度检测运行脚本

export DISPLAY=:0
export LD_LIBRARY_PATH=/home/sunrise/AstraSDK/lib:$LD_LIBRARY_PATH

cd ~/AstraSDK/samples/build/bin

echo "========================================"
echo "Orbbec Astra Pro 深度检测"  
echo "========================================"
echo ""
echo "控制:" 
echo "  - ESC: 退出"  
echo "  - 其他键: 暂停/继续"  
echo ""  
echo "检测范围: 0.6m - 3m"  
echo "========================================"  
echo ""  

./SimpleDepthViewer-SFML
