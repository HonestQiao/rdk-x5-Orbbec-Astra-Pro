#!/usr/bin/env python3
"""
Astra Pro Web Server - OpenCV Version
使用 OpenCV VideoCapture 直接访问相机
- HTTP + WebSocket 统一在端口 8000
"""

import asyncio
import websockets
import os
import sys
import numpy as np
import cv2
import json
import base64
import time

# 设置显示环境
os.environ['DISPLAY'] = ':0'

# 全局变量
connected_clients = set()
frame_count = 0
fps = 0
last_fps_time = time.time()
cap_depth = None
cap_color = None

# HTML页面
HTML_PAGE = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Astra Pro Depth Visual</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: #fff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 10px;
            min-height: 100vh;
        }
        h1 { margin-bottom: 15px; color: #00d4ff; font-size: 20px; }
        .container {
            display: flex;
            flex-direction: column;
            gap: 15px;
            width: 100%;
            max-width: 640px;
        }
        .video-box {
            background: #1a1a1a;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #333;
        }
        .video-title {
            background: #252525;
            padding: 8px 12px;
            font-size: 14px;
            font-weight: 600;
            color: #aaa;
        }
        .video-content {
            position: relative;
            width: 100%;
        }
        .video-content canvas {
            width: 100%;
            display: block;
            background: #000;
        }
        .grid-overlay {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
        }
        .status-bar {
            background: #1a1a1a;
            padding: 12px 15px;
            display: flex;
            justify-content: space-around;
            font-size: 13px;
            border-radius: 8px;
            border: 1px solid #333;
        }
        .status-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 4px;
        }
        .label {
            color: #888;
            font-size: 11px;
        }
        .value {
            color: #00d4ff;
            font-weight: bold;
            font-size: 14px;
        }
        .disconnected { color: #ff4444; }
        .connected { color: #44ff44; }
    </style>
</head>
<body>
    <h1>Astra Pro Depth Visualizer</h1>
    <div class="container">
        <div class="video-box">
            <div class="video-title">RGB Camera (640x480)</div>
            <div class="video-content">
                <canvas id="rgbCanvas"></canvas>
            </div>
        </div>
        <div class="video-box">
            <div class="video-title">Depth Map - Jet Colormap</div>
            <div class="video-content">
                <canvas id="depthCanvas"></canvas>
                <canvas id="gridCanvas" class="grid-overlay"></canvas>
            </div>
        </div>
        <div class="status-bar">
            <div class="status-item">
                <span class="label">FPS</span>
                <span class="value" id="fps">--</span>
            </div>
            <div class="status-item">
                <span class="label">CPU Freq</span>
                <span class="value" id="cpu">--</span>
            </div>
            <div class="status-item">
                <span class="label">Temp</span>
                <span class="value" id="temp">--</span>
            </div>
            <div class="status-item">
                <span class="label">Status</span>
                <span class="value disconnected" id="status">Disconnected</span>
            </div>
        </div>
    </div>

    <script>
        const rgbCanvas = document.getElementById('rgbCanvas');
        const depthCanvas = document.getElementById('depthCanvas');
        const gridCanvas = document.getElementById('gridCanvas');
        const rgbCtx = rgbCanvas.getContext('2d');
        const depthCtx = depthCanvas.getContext('2d');
        const gridCtx = gridCanvas.getContext('2d');

        let ws = null;
        let reconnectInterval = 1000;

        function resizeCanvases(width, height) {
            if (rgbCanvas.width !== width) {
                rgbCanvas.width = width;
                rgbCanvas.height = height;
                depthCanvas.width = width;
                depthCanvas.height = height;
                gridCanvas.width = width;
                gridCanvas.height = height;
            }
        }

        function drawGrid(distances, width, height) {
            gridCtx.clearRect(0, 0, width, height);

            const cols = 5;
            const rows = 5;
            const cellW = width / cols;
            const cellH = height / rows;

            // Draw grid lines
            gridCtx.strokeStyle = 'rgba(255, 255, 255, 0.4)';
            gridCtx.lineWidth = 1;

            for (let i = 1; i < cols; i++) {
                gridCtx.beginPath();
                gridCtx.moveTo(i * cellW, 0);
                gridCtx.lineTo(i * cellW, height);
                gridCtx.stroke();
            }
            for (let i = 1; i < rows; i++) {
                gridCtx.beginPath();
                gridCtx.moveTo(0, i * cellH);
                gridCtx.lineTo(width, i * cellH);
                gridCtx.stroke();
            }

            // Draw distance labels
            gridCtx.font = 'bold 14px Arial';
            gridCtx.textAlign = 'center';
            gridCtx.textBaseline = 'middle';

            let distIdx = 0;
            for (let row = 0; row < rows; row++) {
                for (let col = 0; col < cols; col++) {
                    const cx = (col + 0.5) * cellW;
                    const cy = (row + 0.5) * cellH;

                    if (distIdx < distances.length) {
                        const dist = distances[distIdx++];
                        const distText = dist.toFixed(2) + 'm';

                        // Background
                        const textW = gridCtx.measureText(distText).width + 10;
                        gridCtx.fillStyle = 'rgba(0, 0, 0, 0.7)';
                        gridCtx.fillRect(cx - textW/2, cy - 10, textW, 20);

                        // Text color based on distance
                        if (dist < 0.6) gridCtx.fillStyle = '#ff4444';
                        else if (dist < 1.5) gridCtx.fillStyle = '#44ff44';
                        else gridCtx.fillStyle = '#4488ff';

                        gridCtx.fillText(distText, cx, cy);
                    }
                }
            }
        }

        function updateStatus(connected) {
            const statusEl = document.getElementById('status');
            if (connected) {
                statusEl.textContent = 'Connected';
                statusEl.className = 'value connected';
            } else {
                statusEl.textContent = 'Disconnected';
                statusEl.className = 'value disconnected';
            }
        }

        function connect() {
            const wsUrl = 'ws://' + window.location.host + '/ws';
            console.log('Connecting to', wsUrl);

            ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                console.log('WebSocket connected');
                updateStatus(true);
                reconnectInterval = 1000;
            };

            ws.onclose = () => {
                console.log('WebSocket disconnected');
                updateStatus(false);
                setTimeout(connect, reconnectInterval);
                reconnectInterval = Math.min(reconnectInterval * 2, 30000);
            };

            ws.onerror = (err) => {
                console.error('WebSocket error:', err);
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);

                if (data.type === 'frame') {
                    document.getElementById('fps').textContent = data.fps?.toFixed(1) || '--';
                    document.getElementById('cpu').textContent = (data.cpu_freq || 0) + ' MHz';
                    document.getElementById('temp').textContent = (data.cpu_temp || 0).toFixed(1) + ' C';

                    if (data.rgb) {
                        const img = new Image();
                        img.onload = () => {
                            resizeCanvases(img.width, img.height);
                            rgbCtx.drawImage(img, 0, 0);
                        };
                        img.src = 'data:image/jpeg;base64,' + data.rgb;
                    }

                    if (data.depth) {
                        const img = new Image();
                        img.onload = () => {
                            depthCtx.drawImage(img, 0, 0);
                            if (data.distances) {
                                drawGrid(data.distances, img.width, img.height);
                            }
                        };
                        img.src = 'data:image/jpeg;base64,' + data.depth;
                    }
                }
            };
        }

        connect();
    </script>
</body>
</html>'''


def init_camera():
    """使用 OpenCV 初始化 Astra Pro 相机"""
    global cap_color, cap_depth

    # 查找 Astra 相机设备
    print("[INFO] 正在查找 Astra Pro 相机...")

    # 尝试打开彩色相机 (通常是 /dev/video0 或 video2)
    for i in [0, 2, 4]:
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                print(f"[INFO] 找到彩色相机: /dev/video{i}")
                cap_color = cap
                break
            cap.release()

    # 尝试打开深度相机 (通常是 /dev/video1 或 video3)
    for i in [1, 3, 5]:
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                print(f"[INFO] 找到深度相机: /dev/video{i}")
                cap_depth = cap
                break
            cap.release()

    if cap_color is None:
        print("[WARN] 未找到彩色相机，使用模拟图像")
    if cap_depth is None:
        print("[WARN] 未找到深度相机，使用模拟深度")

    return cap_color is not None or cap_depth is not None


def read_frames():
    """读取相机帧"""
    color_frame = None
    depth_frame = None

    if cap_color and cap_color.isOpened():
        ret, color_frame = cap_color.read()
        if not ret:
            color_frame = None

    if cap_depth and cap_depth.isOpened():
        ret, depth_raw = cap_depth.read()
        if ret and depth_raw is not None:
            # 深度数据通常是 16-bit 或需要转换
            if len(depth_raw.shape) == 3:
                depth_frame = cv2.cvtColor(depth_raw, cv2.COLOR_BGR2GRAY)
            else:
                depth_frame = depth_raw
        else:
            depth_frame = None

    return color_frame, depth_frame


def colorize_depth_jet(depth, min_dist=100, max_dist=2000):
    """将深度数据转换为彩色热力图"""
    if depth is None:
        return np.zeros((480, 640, 3), dtype=np.uint8)

    # 归一化到 0-255
    depth_norm = np.clip((depth - min_dist) / (max_dist - min_dist) * 255, 0, 255).astype(np.uint8)

    # 应用 Jet colormap
    depth_color = cv2.applyColorMap(depth_norm, cv2.COLORMAP_JET)

    return depth_color


def get_grid_distances(depth, cols=5, rows=5):
    """获取网格中心点距离 (模拟)"""
    if depth is None:
        return [1.0 + (i % 3) * 0.5 for i in range(cols * rows)]

    h, w = depth.shape
    distances = []

    for row in range(rows):
        for col in range(cols):
            cy = int((row + 0.5) * h / rows)
            cx = int((col + 0.5) * w / cols)
            dist_mm = depth[cy, cx]
            # 转换为米 (假设值)
            dist_m = min(dist_mm / 1000.0, 10.0)
            distances.append(dist_m)

    return distances


def get_cpu_info():
    """获取CPU信息"""
    try:
        with open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq', 'r') as f:
            freq = int(f.read().strip()) // 1000
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            temp = int(f.read().strip()) / 1000.0
        return freq, temp
    except:
        return 0, 0.0


async def send_frames():
    """发送帧到所有客户端"""
    global frame_count, fps, last_fps_time

    while True:
        if connected_clients:
            try:
                color_frame, depth_frame = read_frames()

                # 如果没有真实数据，创建模拟数据
                if color_frame is None:
                    color_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                    # 添加测试图案
                    cv2.putText(color_frame, "No RGB Camera", (150, 240),
                               cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

                if depth_frame is None:
                    depth_frame = np.random.randint(500, 2000, (480, 640), dtype=np.uint16)

                # 深度图彩色化
                depth_color = colorize_depth_jet(depth_frame)

                # 编码为 JPEG
                _, rgb_encoded = cv2.imencode('.jpg', color_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                _, depth_encoded = cv2.imencode('.jpg', depth_color, [cv2.IMWRITE_JPEG_QUALITY, 80])

                rgb_base64 = base64.b64encode(rgb_encoded).decode('utf-8')
                depth_base64 = base64.b64encode(depth_encoded).decode('utf-8')

                # 获取网格距离
                distances = get_grid_distances(depth_frame)

                # 计算 FPS
                frame_count += 1
                current_time = time.time()
                elapsed = current_time - last_fps_time
                if elapsed >= 1.0:
                    fps = frame_count / elapsed
                    frame_count = 0
                    last_fps_time = current_time

                # 获取CPU信息
                cpu_freq, cpu_temp = get_cpu_info()

                # 构建消息
                message = {
                    'type': 'frame',
                    'rgb': rgb_base64,
                    'depth': depth_base64,
                    'distances': distances,
                    'fps': fps,
                    'cpu_freq': cpu_freq,
                    'cpu_temp': cpu_temp
                }

                # 发送给所有客户端
                msg_json = json.dumps(message)
                disconnected = []
                for ws in connected_clients:
                    try:
                        await ws.send(msg_json)
                    except:
                        disconnected.append(ws)

                # 清理断开连接
                for ws in disconnected:
                    connected_clients.discard(ws)

            except Exception as e:
                print(f'[ERROR] Frame processing: {e}')

        await asyncio.sleep(0.033)  # ~30fps


async def handle_websocket(websocket, path):
    """处理 WebSocket 连接"""
    if path != '/ws':
        return

    print(f'[INFO] Client connected: {websocket.remote_address}')
    connected_clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        connected_clients.discard(websocket)
        print(f'[INFO] Client disconnected: {websocket.remote_address}')


async def process_request(path, request_headers):
    """处理 HTTP 请求"""
    if path == '/' or path == '/index.html':
        return (
            200,
            [('Content-Type', 'text/html'), ('Content-Length', str(len(HTML_PAGE)))],
            HTML_PAGE.encode()
        )
    return None


async def main():
    print('='*60)
    print('Astra Pro Web Server (OpenCV)')
    print('Open http://localhost:8000 in your browser')
    print('='*60)

    # 初始化相机
    print('[INFO] 正在初始化相机...')
    init_camera()

    # 启动帧发送任务
    asyncio.create_task(send_frames())

    # 启动组合服务器
    async with websockets.serve(
        handle_websocket,
        '0.0.0.0',
        8000,
        process_request=process_request
    ):
        print('[INFO] Server started on http://0.0.0.0:8000')
        print('[INFO] WebSocket endpoint: ws://0.0.0.0:8000/ws')
        await asyncio.Future()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n[INFO] Stopping...')
        if cap_color:
            cap_color.release()
        if cap_depth:
            cap_depth.release()
        print('[INFO] Server stopped')
