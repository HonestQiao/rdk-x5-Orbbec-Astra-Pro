# USB Astar Pro 深度相机 - Web 可视化

## 功能概述

通过 Web 浏览器实时显示 Orbbec Astra Pro 深度相机的 RGB 彩色图像和深度图像，支持深度伪彩色叠加显示。

## 硬件环境

- **相机**: Orbbec Astra Pro (USB 2.0)
  - RGB: 1280×720
  - Depth: 640×480
  - 深度范围: 0.4m ~ 8m
- **开发板**: RDK X5 (地平线)

## 软件架构

```
┌─────────────────┐     WebSocket      ┌─────────────────┐
│   浏览器        │ ◄──────────────► │  Python 服务端   │
│   Web 界面      │                   │  astra_web_    │
│   RGB + Depth   │    HTTP API       │  rgb_depth_v2   │
└─────────────────┘ ◄──────────────► └────────┬────────┘
                                               │
                                        ┌──────┴──────┐
                                        │  Astra SDK  │
                                        │ libastra.so │
                                        └─────────────┘
```

## 快速开始

### 1. 安装 Astra SDK

```bash
# 下载 Astra SDK
cd /home/sunrise
git clone https://github.com/HonestQiao/AstraSDK
cd AstraSDK
mkdir build && cd build
cmake ..
make
sudo make install
```

### 2. 运行 Web 服务

```bash
# 启动服务（默认端口 8000）
sudo python3 astra_web_rgb_depth_v2.py

# 指定参数
sudo python3 astra_web_rgb_depth_v2.py --max-dist 5000 --invalid-color black
```

### 3. 访问 Web 界面

- RGB + Depth 叠加显示: `http://<设备IP>:8000`
- WebSocket 实时流: `ws://<设备IP>:8001/ws`

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--max-dist` | 最远检测距离(mm) | 8000 |
| `--invalid-color` | 无效深度颜色 | black |

## Web 界面功能

- RGB 彩色图像显示
- 深度图像伪彩色显示（近红远蓝）
- RGB + Depth 透明度叠加
- 网格距离标注
- 参数动态调节

## 文件说明

```
usb_hobot_stereonet/
├── astra_web_rgb_depth_v2.py   # 主程序 (Web服务)
└── 开发过程文件/                 # 调试过程文件
```

## License

MIT
