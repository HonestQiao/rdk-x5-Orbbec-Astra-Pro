#!/usr/bin/env python3
"""
Astra Pro Web Server - 深度图叠加到RGB显示
使用 OpenCV 将深度热力图半透明叠加到彩色图像上
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
import http.server
import socketserver
import threading

os.environ['DISPLAY'] = ':0'

# 全局变量
connected_clients = set()
frame_count = 0
fps = 0
last_fps_time = time.time()
cap_depth = None
cap_color = None

# HTML页面
HTML_CONTENT = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Astra Pro Depth Overlay</title>
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
            max-width: 800px;
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
        .legend {
            display: flex;
            justify-content: center;
            gap: 20px;
            padding: 10px;
            background: #1a1a1a;
            border-radius: 8px;
            border: 1px solid #333;
            font-size: 12px;
        }
        .legend-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .color-box {
            width: 30px;
            height: 15px;
            border-radius: 3px;
        }
        .near { background: linear-gradient(90deg, #ff0000, #ff8800); }
        .mid { background: linear-gradient(90deg, #ff8800, #ffff00); }
        .far { background: linear-gradient(90deg, #ffff00, #0088ff); }
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
        .label { color: #888; font-size: 11px; }
        .value { color: #00d4ff; font-weight: bold; font-size: 14px; }
        .disconnected { color: #ff4444; }
        .connected { color: #44ff44; }
    </style>
</head>
<body>
    <h1>Astra Pro Depth Overlay</h1>
    <div class="container">
        <div class="video-box">
            <div class="video-title">RGB + Depth Overlay (640x480)</div>
            <div class="video-content">
                <canvas id="overlayCanvas"></canvas>
                <canvas id="gridCanvas" class="grid-overlay"></canvas>
            </div>
        </div>

        <div class="legend">
            <div class="legend-item">
                <div class="color-box near"></div>
                <span>Near (0.3-0.8m)</span>
            </div>
            <div class="legend-item">
                <div class="color-box mid"></div>
                <span>Mid (0.8-1.5m)</span>
            </div>
            <div class="legend-item">
                <div class="color-box far"></div>
                <span>Far (1.5m+)</span>
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
        const overlayCanvas = document.getElementById('overlayCanvas');
        const gridCanvas = document.getElementById('gridCanvas');
        const overlayCtx = overlayCanvas.getContext('2d');
        const gridCtx = gridCanvas.getContext('2d');
        let ws = null;
        let reconnectInterval = 1000;

        function resizeCanvases(width, height) {
            if (overlayCanvas.width !== width) {
                overlayCanvas.width = width; overlayCanvas.height = height;
                gridCanvas.width = width; gridCanvas.height = height;
            }
        }

        function drawGrid(distances, width, height) {
            gridCtx.clearRect(0, 0, width, height);
            const cols = 5, rows = 5;
            const cellW = width / cols, cellH = height / rows;

            // Draw grid lines
            gridCtx.strokeStyle = 'rgba(255, 255, 255, 0.5)';
            gridCtx.lineWidth = 1;
            for (let i = 1; i < cols; i++) {
                gridCtx.beginPath(); gridCtx.moveTo(i * cellW, 0); gridCtx.lineTo(i * cellW, height); gridCtx.stroke();
            }
            for (let i = 1; i < rows; i++) {
                gridCtx.beginPath(); gridCtx.moveTo(0, i * cellH); gridCtx.lineTo(width, i * cellH); gridCtx.stroke();
            }

            // Draw distance labels
            gridCtx.font = 'bold 12px Arial';
            gridCtx.textAlign = 'center'; gridCtx.textBaseline = 'middle';
            let distIdx = 0;
            for (let row = 0; row < rows; row++) {
                for (let col = 0; col < cols; col++) {
                    const cx = (col + 0.5) * cellW, cy = (row + 0.5) * cellH;
                    if (distIdx < distances.length) {
                        const dist = distances[distIdx++];
                        const distText = dist.toFixed(2) + 'm';
                        const textW = gridCtx.measureText(distText).width + 8;
                        gridCtx.fillStyle = 'rgba(0, 0, 0, 0.8)';
                        gridCtx.fillRect(cx - textW/2, cy - 8, textW, 16);
                        if (dist < 0.6) gridCtx.fillStyle = '#ff6666';
                        else if (dist < 1.0) gridCtx.fillStyle = '#66ff66';
                        else gridCtx.fillStyle = '#66aaff';
                        gridCtx.fillText(distText, cx, cy);
                    }
                }
            }
        }

        function updateStatus(connected) {
            const statusEl = document.getElementById('status');
            statusEl.textContent = connected ? 'Connected' : 'Disconnected';
            statusEl.className = 'value ' + (connected ? 'connected' : 'disconnected');
        }

        function connect() {
            const wsUrl = 'ws://' + window.location.hostname + ':8001/ws';
            console.log('Connecting to', wsUrl);
            ws = new WebSocket(wsUrl);
            ws.onopen = () => { console.log('Connected'); updateStatus(true); reconnectInterval = 1000; };
            ws.onclose = () => { console.log('Disconnected'); updateStatus(false); setTimeout(connect, reconnectInterval); reconnectInterval = Math.min(reconnectInterval * 2, 30000); };
            ws.onerror = (err) => { console.error('Error:', err); };
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === 'frame') {
                    document.getElementById('fps').textContent = data.fps?.toFixed(1) || '--';
                    document.getElementById('cpu').textContent = (data.cpu_freq || 0) + ' MHz';
                    document.getElementById('temp').textContent = (data.cpu_temp || 0).toFixed(1) + ' C';
                    if (data.overlay) {
                        const img = new Image();
                        img.onload = () => {
                            resizeCanvases(img.width, img.height);
                            overlayCtx.drawImage(img, 0, 0);
                            if (data.distances) drawGrid(data.distances, img.width, img.height);
                        };
                        img.src = 'data:image/jpeg;base64,' + data.overlay;
                    }
                }
            };
        }
        connect();
    </script>
</body>
</html>'''


class HTTPHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode())
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass


def start_http_server():
    with socketserver.TCPServer(('0.0.0.0', 8000), HTTPHandler) as httpd:
        print('[INFO] HTTP server on http://0.0.0.0:8000')
        httpd.serve_forever()


def init_camera():
    global cap_color, cap_depth
    print('[INFO] 查找 Astra Pro 相机...')
    for i in [0, 2, 4, 6]:
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret and frame is not None:
                print(f'[INFO] 彩色相机: /dev/video{i}')
                cap_color = cap
                break
            cap.release()
    for i in [1, 3, 5, 7]:
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret and frame is not None:
                print(f'[INFO] 深度相机: /dev/video{i}')
                cap_depth = cap
                break
            cap.release()
    if cap_color is None:
        print('[WARN] 未找到彩色相机')
    if cap_depth is None:
        print('[WARN] 未找到深度相机')
    return cap_color is not None or cap_depth is not None


def read_frames():
    color_frame = None
    depth_frame = None
    if cap_color and cap_color.isOpened():
        ret, frame = cap_color.read()
        if ret:
            color_frame = frame
    if cap_depth and cap_depth.isOpened():
        ret, frame = cap_depth.read()
        if ret and frame is not None:
            if len(frame.shape) == 3:
                depth_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                depth_frame = frame
    return color_frame, depth_frame


def create_depth_overlay(color_frame, depth_frame, alpha=0.5):
    """将深度热力图叠加到彩色图像上"""
    if color_frame is None:
        color_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(color_frame, "No RGB Camera", (150, 240),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

    if depth_frame is None:
        # 生成模拟深度数据
        depth_frame = np.random.randint(300, 2500, (480, 640), dtype=np.uint16)

    # 确保尺寸一致
    h, w = color_frame.shape[:2]
    if depth_frame.shape != (h, w):
        depth_frame = cv2.resize(depth_frame, (w, h))

    # 深度图彩色化 (Jet colormap)
    # 范围: 300mm (0.3m) 到 2500mm (2.5m)
    min_dist, max_dist = 300, 2500
    depth_norm = np.clip((depth_frame - min_dist) / (max_dist - min_dist) * 255, 0, 255).astype(np.uint8)
    depth_color = cv2.applyColorMap(depth_norm, cv2.COLORMAP_JET)

    # 叠加: alpha 混合
    # overlay = color * (1-alpha) + depth_color * alpha
    overlay = cv2.addWeighted(color_frame, 1 - alpha, depth_color, alpha, 0)

    return overlay, depth_frame


def get_grid_distances(depth, cols=5, rows=5):
    if depth is None:
        return [0.5 + (i % 5) * 0.4 for i in range(25)]
    h, w = depth.shape
    distances = []
    for row in range(rows):
        for col in range(cols):
            cy = int((row + 0.5) * h / rows)
            cx = int((col + 0.5) * w / cols)
            dist_m = min(depth[cy, cx] / 1000.0, 10.0)
            distances.append(dist_m)
    return distances


def get_cpu_info():
    try:
        with open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq', 'r') as f:
            freq = int(f.read().strip()) // 1000
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            temp = int(f.read().strip()) / 1000.0
        return freq, temp
    except:
        return 0, 0.0


async def send_frames():
    global frame_count, fps, last_fps_time
    while True:
        if connected_clients:
            try:
                color_frame, depth_frame = read_frames()

                # 创建叠加图像
                overlay_frame, depth_raw = create_depth_overlay(color_frame, depth_frame, alpha=0.4)

                # 编码
                _, overlay_encoded = cv2.imencode('.jpg', overlay_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                overlay_b64 = base64.b64encode(overlay_encoded).decode('utf-8')

                # 网格距离
                distances = get_grid_distances(depth_raw)

                # FPS
                frame_count += 1
                current_time = time.time()
                if current_time - last_fps_time >= 1.0:
                    fps = frame_count / (current_time - last_fps_time)
                    frame_count = 0
                    last_fps_time = current_time

                # CPU
                cpu_freq, cpu_temp = get_cpu_info()

                # 发送
                msg = json.dumps({
                    'type': 'frame',
                    'overlay': overlay_b64,
                    'distances': distances,
                    'fps': fps,
                    'cpu_freq': cpu_freq,
                    'cpu_temp': cpu_temp
                })

                disconnected = []
                for ws in connected_clients:
                    try:
                        await ws.send(msg)
                    except:
                        disconnected.append(ws)
                for ws in disconnected:
                    connected_clients.discard(ws)
            except Exception as e:
                print(f'[ERROR] Frame: {e}')
        await asyncio.sleep(0.033)


async def handle_websocket(websocket):
    print(f'[INFO] Client connected: {websocket.remote_address}')
    connected_clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        connected_clients.discard(websocket)
        print(f'[INFO] Client disconnected: {websocket.remote_address}')


async def main():
    print('='*60)
    print('Astra Pro Web Server - Depth Overlay')
    print('HTTP: http://localhost:8000')
    print('WebSocket: ws://localhost:8001/ws')
    print('='*60)

    init_camera()

    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    asyncio.create_task(send_frames())

    async with websockets.serve(handle_websocket, '0.0.0.0', 8001):
        print('[INFO] WebSocket server on ws://0.0.0.0:8001/ws')
        await asyncio.Future()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n[INFO] Stopping...')
        if cap_color: cap_color.release()
        if cap_depth: cap_depth.release()
        print('[INFO] Stopped')
