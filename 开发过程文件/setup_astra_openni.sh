#!/bin/bash
# Orbbec Astra Pro OpenNI 驱动配置脚本
# 配置环境变量，确保 OpenNI Python 模块能找到驱动

echo "================================"
echo "Astra Pro OpenNI 驱动配置"
echo "================================"

# 查找 OpenNI2 库文件位置
OPENNI2_REDIST=""
for path in /usr/lib /usr/local/lib /usr/lib/aarch64-linux-gnu; do
    if [ -f "$path/libOpenNI2.so" ] || [ -d "$path/OpenNI2" ]; then
        OPENNI2_REDIST="$path"
        break
    fi
done

if [ -z "$OPENNI2_REDIST" ]; then
    echo "[ERROR] 未找到 OpenNI2 库文件"
    exit 1
fi

echo "[INFO] OpenNI2 库路径: $OPENNI2_REDIST"

# 设置环境变量
export OPENNI2_INCLUDE=/usr/include/openni2
export OPENNI2_REDIST=$OPENNI2_REDIST

# 添加到 .bashrc
echo "" >> ~/.bashrc
echo "# Astra Pro OpenNI 配置" >> ~/.bashrc
echo "export OPENNI2_INCLUDE=/usr/include/openni2" >> ~/.bashrc
echo "export OPENNI2_REDIST=$OPENNI2_REDIST" >> ~/.bashrc

echo "[INFO] 环境变量已设置"

# 添加 udev 规则（允许非 root 访问）
echo "[INFO] 配置 udev 规则..."
sudo tee /etc/udev/rules.d/99-obcamera.rules > /dev/null << 'EOF'
# Orbbec Astra Pro
SUBSYSTEM=="usb", ATTR{idProduct}=="0403", ATTR{idVendor}=="2bc5", MODE:="0666", OWNER:="root", GROUP:="video"
SUBSYSTEM=="usb", ATTR{idProduct}=="0501", ATTR{idVendor}=="2bc5", MODE:="0666", OWNER:="root", GROUP:="video"
SUBSYSTEM=="usb", ATTR{idProduct}=="0601", ATTR{idVendor}=="2bc5", MODE:="0666", OWNER:="root", GROUP:="video"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger

echo "[INFO] udev 规则已更新"

# 检查用户是否在 video 组
if ! groups | grep -q video; then
    echo "[WARN] 当前用户不在 video 组，添加中..."
    sudo usermod -a -G video $USER
    echo "[WARN] 请重新登录或重启系统使权限生效"
fi

# 测试 OpenNI
echo ""
echo "[INFO] 测试 OpenNI 配置..."
python3 << 'EOF'
import os
import sys

os.environ['OPENNI2_REDIST'] = os.environ.get('OPENNI2_REDIST', '/usr/lib')

try:
    from openni import openni2
    openni2.initialize()
    print("[OK] OpenNI2 初始化成功")

    # 尝试列出设备
    try:
        dev = openni2.Device.open_any()
        info = dev.get_device_info()
        print(f"[OK] 设备已连接: {info.name}")
        print(f"[OK] 设备 URI: {info.uri}")

        # 检查支持的传感器
        if dev.has_sensor(openni2.SENSOR_DEPTH):
            print("[OK] 支持深度传感器")
        if dev.has_sensor(openni2.SENSOR_COLOR):
            print("[OK] 支持彩色传感器")

        dev.close()
    except Exception as e:
        print(f"[WARN] 未找到设备: {e}")
        print("[INFO] 请检查摄像头是否连接")

    openni2.unload()
    print("[OK] OpenNI2 测试完成")

except ImportError as e:
    print(f"[ERROR] OpenNI Python 模块未安装: {e}")
    print("[INFO] 运行: pip3 install openni")
except Exception as e:
    print(f"[ERROR] OpenNI 测试失败: {e}")
EOF

echo ""
echo "================================"
echo "配置完成!"
echo "================================"
echo ""
echo "使用方法:"
echo "  1. 重新加载环境变量: source ~/.bashrc"
echo "  2. 或直接运行: export OPENNI2_REDIST=$OPENNI2_REDIST"
echo "  3. 然后运行程序: python3 astra_depth_ai.py"
echo ""
echo "如果设备未找到:"
echo "  - 检查摄像头连接: lsusb | grep Orbbec"
echo "  - 重新插拔摄像头"
echo "  - 重启系统使 udev 规则生效"
echo ""
