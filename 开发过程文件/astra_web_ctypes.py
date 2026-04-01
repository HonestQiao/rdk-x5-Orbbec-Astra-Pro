#!/usr/bin/env python3
"""
Astra Pro Web Server - 使用 ctypes 调用 Astra SDK 获取真实深度数据
"""

import asyncio
import websockets
import ctypes
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

# Astra SDK 路径设置
ASTRA_SDK_PATH = '/home/sunrise/AstraSDK'
ASTRA_LIB_PATH = f'{ASTRA_SDK_PATH}/lib'

# 必须在加载库之前设置环境变量
os.environ['DISPLAY'] = ':0'
os.environ['LD_LIBRARY_PATH'] = f"{ASTRA_LIB_PATH}:{ASTRA_LIB_PATH}/Plugins/openni2:{os.environ.get('LD_LIBRARY_PATH', '')}"

# 加载 Astra SDK 库
ctypes.CDLL(f'{ASTRA_LIB_PATH}/libastra_core.so', ctypes.RTLD_GLOBAL)
astra_core = ctypes.CDLL(f'{ASTRA_LIB_PATH}/libastra_core.so')
astra = ctypes.CDLL(f'{ASTRA_LIB_PATH}/libastra.so')

# 定义类型
astra_streamsetconnection_t = ctypes.c_void_p
astra_reader_t = ctypes.c_void_p
astra_depthstream_t = ctypes.c_void_p
astra_reader_frame_t = ctypes.c_void_p
astra_depthframe_t = ctypes.c_void_p

class AstraImageMetadata(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("pixelFormat", ctypes.c_int32),
        ("reserved", ctypes.c_uint32)
    ]

# HTML页面
HTML_CONTENT = '''<!DOCTYPE html>
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
    <h1>Astra Pro Depth Visualizer (Real Data)</h1>
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
            console.log('Resizing canvases to:', width, 'x', height);
            if (overlayCanvas.width !== width || overlayCanvas.height !== height) {
                overlayCanvas.width = width;
                overlayCanvas.height = height;
                gridCanvas.width = width;
                gridCanvas.height = height;
                console.log('Canvas resized');
            }
        }

        function drawGrid(distances, width, height) {
            gridCtx.clearRect(0, 0, width, height);
            const cols = 5, rows = 5;
            const cellW = width / cols, cellH = height / rows;
            gridCtx.strokeStyle = 'rgba(255, 255, 255, 0.5)';
            gridCtx.lineWidth = 1;
            for (let i = 1; i < cols; i++) {
                gridCtx.beginPath(); gridCtx.moveTo(i * cellW, 0); gridCtx.lineTo(i * cellW, height); gridCtx.stroke();
            }
            for (let i = 1; i < rows; i++) {
                gridCtx.beginPath(); gridCtx.moveTo(0, i * cellH); gridCtx.lineTo(width, i * cellH); gridCtx.stroke();
            }
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
                    if (data.overlay) {
                        const img = new Image();
                        img.onload = () => {
                            console.log('Image loaded, size:', img.width, 'x', img.height);
                            resizeCanvases(img.width, img.height);
                            // Clear and draw
                            overlayCtx.fillStyle = '#000';
                            overlayCtx.fillRect(0, 0, overlayCanvas.width, overlayCanvas.height);
                            overlayCtx.drawImage(img, 0, 0);
                            if (data.distances) {
                                console.log('Drawing grid with', data.distances.length, 'distances');
                                drawGrid(data.distances, img.width, img.height);
                            }
                        };
                        img.onerror = (err) => {
                            console.error('Image load error:', err);
                        };
                        img.src = 'data:image/jpeg;base64,' + data.overlay;
                    } else {
                        console.warn('No overlay data in frame');
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

class AstraCamera:
    """Astra Pro 相机封装 - 使用 ctypes"""
    def __init__(self):
        self.sensor = astra_streamsetconnection_t()
        self.reader = astra_reader_t()
        self.depth_stream = astra_depthstream_t()
        self.initialized = False
        self.width = 640
        self.height = 480

    def initialize(self):
        print("[INFO] 初始化 Astra SDK...")
        rc = astra_core.astra_initialize()
        if rc != 0:
            print(f"[ERROR] astra_initialize failed: {rc}")
            return False
        print("[INFO] Astra SDK 初始化成功")

        rc = astra_core.astra_streamset_open(b"device/default", ctypes.byref(self.sensor))
        if rc != 0:
            print(f"[ERROR] astra_streamset_open failed: {rc}")
            astra_core.astra_terminate()
            return False
        print(f"[INFO] 设备已打开")

        rc = astra_core.astra_reader_create(self.sensor, ctypes.byref(self.reader))
        if rc != 0:
            print(f"[ERROR] astra_reader_create failed: {rc}")
            astra_core.astra_streamset_close(self.sensor)
            astra_core.astra_terminate()
            return False
        print("[INFO] Reader 创建成功")

        rc = astra.astra_reader_get_depthstream(self.reader, ctypes.byref(self.depth_stream))
        if rc != 0:
            print(f"[ERROR] astra_reader_get_depthstream failed: {rc}")
            astra_core.astra_reader_destroy(ctypes.byref(self.reader))
            astra_core.astra_streamset_close(self.sensor)
            astra_core.astra_terminate()
            return False
        print("[INFO] 深度流获取成功")

        rc = astra_core.astra_stream_start(self.depth_stream)
        if rc != 0:
            print(f"[ERROR] astra_stream_start failed: {rc}")
            astra_core.astra_reader_destroy(ctypes.byref(self.reader))
            astra_core.astra_streamset_close(self.sensor)
            astra_core.astra_terminate()
            return False
        print("[INFO] 深度流已启动")

        self.initialized = True
        return True

    def read_depth(self):
        if not self.initialized:
            return None

        astra_core.astra_update()
        frame = astra_reader_frame_t()
        rc = astra_core.astra_reader_open_frame(self.reader, 100, ctypes.byref(frame))

        if rc != 0:
            return None

        try:
            depth_frame = astra_depthframe_t()
            rc = astra.astra_frame_get_depthframe(frame, ctypes.byref(depth_frame))
            if rc != 0:
                astra_core.astra_reader_close_frame(ctypes.byref(frame))
                return None

            depth_length = ctypes.c_uint32()
            astra.astra_depthframe_get_data_byte_length(depth_frame, ctypes.byref(depth_length))

            if depth_length.value == 0:
                astra_core.astra_reader_close_frame(ctypes.byref(frame))
                return None

            num_pixels = depth_length.value // 2
            depth_buffer = (ctypes.c_int16 * num_pixels)()
            astra.astra_depthframe_copy_data(depth_frame, depth_buffer)

            metadata = AstraImageMetadata()
            astra.astra_depthframe_get_metadata(depth_frame, ctypes.byref(metadata))
            self.width = metadata.width
            self.height = metadata.height

            depth_array = np.ctypeslib.as_array(depth_buffer).copy()
            depth_array = depth_array.reshape((self.height, self.width))

            return depth_array

        finally:
            astra_core.astra_reader_close_frame(ctypes.byref(frame))

    def release(self):
        if not self.initialized:
            return
        print("[INFO] 释放资源...")
        astra_core.astra_stream_stop(self.depth_stream)
        astra_core.astra_reader_destroy(ctypes.byref(self.reader))
        astra_core.astra_streamset_close(self.sensor)
        astra_core.astra_terminate()
        self.initialized = False
        print("[INFO] 资源已释放")

def colorize_depth(depth, min_dist=600, max_dist=8000):
    """Astra Pro 深度范围: 0.6m-8m (600-8000mm)"""
    if depth is None:
        return None
    # 过滤无效值 (0 表示无效)
    valid_mask = depth > 0
    if not np.any(valid_mask):
        # 全是无效值，返回提示图像
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(img, "No valid depth data", (120, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        return img
    # 只处理有效值
    depth_norm = np.zeros_like(depth, dtype=np.uint8)
    depth_valid = depth[valid_mask]
    depth_norm[valid_mask] = np.clip((depth_valid - min_dist) / (max_dist - min_dist) * 255, 0, 255).astype(np.uint8)
    return cv2.applyColorMap(depth_norm, cv2.COLORMAP_JET)

def get_grid_distances(depth, cols=5, rows=5):
    """获取网格距离，处理无效值"""
    if depth is None:
        return [0.0] * 25
    h, w = depth.shape
    distances = []
    for row in range(rows):
        for col in range(cols):
            cy = int((row + 0.5) * h / rows)
            cx = int((col + 0.5) * w / cols)
            dist_mm = depth[cy, cx]
            # 0 表示无效值
            if dist_mm > 0:
                dist_m = min(dist_mm / 1000.0, 10.0)
            else:
                dist_m = 0.0
            distances.append(dist_m)
    return distances

# 全局变量
connected_clients = set()
camera = AstraCamera()
frame_count = 0
fps = 0
last_fps_time = time.time()

async def send_frames():
    global frame_count, fps, last_fps_time
    debug_counter = 0
    while True:
        if connected_clients:
            try:
                depth = camera.read_depth()
                if depth is not None:
                    frame_count += 1
                    current_time = time.time()
                    if current_time - last_fps_time >= 1.0:
                        fps = frame_count / (current_time - last_fps_time)
                        frame_count = 0
                        last_fps_time = current_time

                    # 调试输出 (每30帧一次)
                    debug_counter += 1
                    if debug_counter >= 30:
                        valid_count = np.sum(depth > 0)
                        if valid_count > 0:
                            min_val = np.min(depth[depth > 0])
                            max_val = np.max(depth[depth > 0])
                            center = depth[depth.shape[0]//2, depth.shape[1]//2]
                            img_h, img_w = depth_color.shape[:2]
                            print(f"[DEBUG] Depth: valid={valid_count}, min={min_val}mm, max={max_val}mm, center={center}mm, img={img_w}x{img_h}")
                        else:
                            print(f"[DEBUG] Depth: NO VALID DATA (all zeros)")
                        debug_counter = 0

                    # 深度彩色化 (Astra Pro: 600-8000mm)
                    depth_color = colorize_depth(depth, 600, 8000)

                    # 确保图像有效
                    if depth_color is None:
                        depth_color = np.zeros((480, 640, 3), dtype=np.uint8)
                        cv2.putText(depth_color, "No depth", (250, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)

                    # 编码为 JPEG
                    ret, depth_encoded = cv2.imencode('.jpg', depth_color, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if not ret:
                        print("[ERROR] JPEG encode failed")
                        continue
                    depth_b64 = base64.b64encode(depth_encoded).decode('utf-8')

                    # 网格距离
                    distances = get_grid_distances(depth)

                    # 发送
                    msg_data = {
                        'type': 'frame',
                        'overlay': depth_b64,
                        'distances': distances,
                        'fps': fps
                    }
                    msg = json.dumps(msg_data)
                    msg_size = len(msg)
                    if debug_counter == 1:  # 每30帧的第一帧
                        print(f"[DEBUG] Sending: img_size={len(depth_b64)} bytes, msg_size={msg_size} bytes, clients={len(connected_clients)}")

                    disconnected = []
                    send_success = 0
                    for ws in connected_clients:
                        try:
                            await ws.send(msg)
                            send_success += 1
                        except Exception as e:
                            print(f"[WARN] Send failed: {e}")
                            disconnected.append(ws)
                    for ws in disconnected:
                        connected_clients.discard(ws)
                    if debug_counter == 1:
                        print(f"[DEBUG] Sent to {send_success} clients, {len(disconnected)} failed")
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
    print('Astra Pro Web Server - ctypes with Real Depth')
    print('HTTP: http://localhost:8000')
    print('WebSocket: ws://localhost:8001/ws')
    print('='*60)

    if not camera.initialize():
        print("[ERROR] 相机初始化失败")
        return

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
        camera.release()
        print('[INFO] Stopped')
