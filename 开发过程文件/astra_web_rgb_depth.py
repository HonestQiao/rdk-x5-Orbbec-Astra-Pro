#!/usr/bin/env python3
"""
Astra Pro Web Server - RGB + Depth 叠加显示
使用 Astra SDK 同时读取 RGB 和深度流
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
astra_colorstream_t = ctypes.c_void_p
astra_reader_frame_t = ctypes.c_void_p
astra_depthframe_t = ctypes.c_void_p
astra_colorframe_t = ctypes.c_void_p

class AstraImageMetadata(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("pixelFormat", ctypes.c_int32),
        ("reserved", ctypes.c_uint32)
    ]

# HTML页面 - RGB + Depth 叠加
HTML_CONTENT = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Astra Pro RGB + Depth Overlay</title>
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
            background: #000;
        }
        .video-content canvas {
            width: 100%;
            display: block;
        }
        .legend {
            display: flex;
            justify-content: center;
            gap: 15px;
            padding: 10px;
            background: #1a1a1a;
            border-radius: 8px;
            border: 1px solid #333;
            font-size: 11px;
            flex-wrap: wrap;
        }
        .legend-item {
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .color-box {
            width: 30px;
            height: 12px;
            border-radius: 2px;
        }
        .near { background: #ff0040; }
        .mid { background: #ff8000; }
        .far { background: #ffff00; }
        .vfar { background: #00aaff; }
        .status-bar {
            background: #1a1a1a;
            padding: 10px 15px;
            display: flex;
            justify-content: space-around;
            font-size: 12px;
            border-radius: 8px;
            border: 1px solid #333;
        }
        .status-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 3px;
        }
        .label { color: #888; font-size: 10px; }
        .value { color: #00d4ff; font-weight: bold; font-size: 13px; }
        .disconnected { color: #ff4444; }
        .connected { color: #44ff44; }
        .controls {
            background: #1a1a1a;
            padding: 12px 15px;
            border-radius: 8px;
            border: 1px solid #333;
            display: flex;
            align-items: center;
            gap: 15px;
        }
        .controls label {
            font-size: 12px;
            color: #aaa;
            white-space: nowrap;
        }
        .controls input[type="range"] {
            flex: 1;
            height: 6px;
            -webkit-appearance: none;
            background: #333;
            border-radius: 3px;
            outline: none;
        }
        .controls input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 14px;
            height: 14px;
            background: #00d4ff;
            border-radius: 50%;
            cursor: pointer;
        }
        .controls span {
            font-size: 12px;
            color: #00d4ff;
            min-width: 35px;
            text-align: right;
        }
    </style>
</head>
<body>
    <h1>Astra Pro RGB + Depth Overlay</h1>
    <div class="container">
        <div class="video-box">
            <div class="video-title">RGB Camera + Depth Overlay (红=近, 蓝=远)</div>
            <div class="video-content">
                <canvas id="mainCanvas"></canvas>
            </div>
        </div>

        <div class="controls">
            <label>深度透明度:</label>
            <input type="range" id="alphaSlider" min="0" max="80" value="35">
            <span id="alphaValue">35%</span>
        </div>

        <div class="legend">
            <div class="legend-item">
                <div class="color-box near"></div>
                <span>0.3-0.8m</span>
            </div>
            <div class="legend-item">
                <div class="color-box mid"></div>
                <span>0.8-1.5m</span>
            </div>
            <div class="legend-item">
                <div class="color-box far"></div>
                <span>1.5-3m</span>
            </div>
            <div class="legend-item">
                <div class="color-box vfar"></div>
                <span>3m+</span>
            </div>
        </div>

        <div class="status-bar">
            <div class="status-item">
                <span class="label">FPS</span>
                <span class="value" id="fps">--</span>
            </div>
            <div class="status-item">
                <span class="label">RGB</span>
                <span class="value" id="rgbStatus">--</span>
            </div>
            <div class="status-item">
                <span class="label">Depth</span>
                <span class="value" id="depthStatus">--</span>
            </div>
            <div class="status-item">
                <span class="label">Status</span>
                <span class="value disconnected" id="status">Disconnected</span>
            </div>
        </div>
    </div>

    <script>
        const canvas = document.getElementById('mainCanvas');
        const ctx = canvas.getContext('2d');
        const alphaSlider = document.getElementById('alphaSlider');
        const alphaValue = document.getElementById('alphaValue');
        let ws = null;
        let reconnectInterval = 1000;
        let targetAlpha = 0.35;
        let currentAlpha = 0.35;

        alphaSlider.addEventListener('input', (e) => {
            targetAlpha = e.target.value / 100;
            alphaValue.textContent = e.target.value + '%';
        });

        function resizeCanvas(width, height) {
            if (canvas.width !== width || canvas.height !== height) {
                canvas.width = width;
                canvas.height = height;
            }
        }

        function updateStatus(connected, hasRgb, hasDepth) {
            const statusEl = document.getElementById('status');
            statusEl.textContent = connected ? 'Connected' : 'Disconnected';
            statusEl.className = 'value ' + (connected ? 'connected' : 'disconnected');

            const rgbEl = document.getElementById('rgbStatus');
            rgbEl.textContent = hasRgb ? 'OK' : 'NO';
            rgbEl.style.color = hasRgb ? '#44ff44' : '#ff4444';

            const depthEl = document.getElementById('depthStatus');
            depthEl.textContent = hasDepth ? 'OK' : 'NO';
            depthEl.style.color = hasDepth ? '#44ff44' : '#ff4444';
        }

        function drawNoSignal() {
            ctx.fillStyle = '#111';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.strokeStyle = '#333';
            ctx.lineWidth = 2;
            ctx.strokeRect(10, 10, canvas.width - 20, canvas.height - 20);
            ctx.fillStyle = '#666';
            ctx.font = '16px Arial';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText('Waiting for camera...', canvas.width/2, canvas.height/2);
        }

        function connect() {
            const wsUrl = 'ws://' + window.location.hostname + ':8001/ws';
            ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                updateStatus(true, false, false);
                reconnectInterval = 1000;
            };

            ws.onclose = () => {
                updateStatus(false, false, false);
                drawNoSignal();
                setTimeout(connect, reconnectInterval);
                reconnectInterval = Math.min(reconnectInterval * 2, 30000);
            };

            ws.onerror = (err) => {
                console.error('WebSocket error:', err);
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === 'frame') {
                        document.getElementById('fps').textContent = data.fps?.toFixed(1) || '--';
                        updateStatus(true, data.has_rgb, data.has_depth);

                        if (data.overlay) {
                            const img = new Image();
                            img.onload = () => {
                                resizeCanvas(img.width, img.height);
                                ctx.drawImage(img, 0, 0);
                            };
                            img.src = 'data:image/jpeg;base64,' + data.overlay;
                        }
                    }
                } catch (e) {
                    console.error('Parse error:', e);
                }
            };
        }

        canvas.width = 640;
        canvas.height = 480;
        drawNoSignal();
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
    """Astra Pro 相机封装 - RGB + Depth"""
    def __init__(self):
        self.sensor = astra_streamsetconnection_t()
        self.reader = astra_reader_t()
        self.depth_stream = astra_depthstream_t()
        self.color_stream = astra_colorstream_t()
        self.initialized = False
        self.depth_width = 640
        self.depth_height = 480
        self.color_width = 640
        self.color_height = 480
        self.has_color = False
        # OpenCV 作为 RGB 后备
        self.rgb_cap = None
        self.use_opencv_rgb = False

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

        # 获取深度流
        rc = astra.astra_reader_get_depthstream(self.reader, ctypes.byref(self.depth_stream))
        if rc != 0:
            print(f"[ERROR] astra_reader_get_depthstream failed: {rc}")
            astra_core.astra_reader_destroy(ctypes.byref(self.reader))
            astra_core.astra_streamset_close(self.sensor)
            astra_core.astra_terminate()
            return False
        print("[INFO] 深度流获取成功")

        # 启动深度流
        rc = astra_core.astra_stream_start(self.depth_stream)
        if rc != 0:
            print(f"[ERROR] astra_stream_start (depth) failed: {rc}")
            astra_core.astra_reader_destroy(ctypes.byref(self.reader))
            astra_core.astra_streamset_close(self.sensor)
            astra_core.astra_terminate()
            return False
        print("[INFO] 深度流已启动")

        # 尝试获取彩色流 (Astra SDK 方式)
        try:
            rc = astra.astra_reader_get_colorstream(self.reader, ctypes.byref(self.color_stream))
            if rc == 0:
                print("[INFO] 彩色流获取成功 (Astra SDK)")
                rc = astra_core.astra_stream_start(self.color_stream)
                if rc == 0:
                    print("[INFO] 彩色流已启动 (Astra SDK)")
                    self.has_color = True
                else:
                    print(f"[WARN] 彩色流启动失败 (Astra SDK): {rc}")
                    self.color_stream = None
            else:
                print(f"[INFO] 彩色流不可用 (Astra SDK): {rc}")
                self.color_stream = None
        except Exception as e:
            print(f"[INFO] 彩色流初始化异常 (Astra SDK): {e}")
            self.color_stream = None

        # 如果 Astra SDK 方式不行，尝试 OpenCV UVC 方式
        if not self.has_color:
            print("[INFO] 尝试通过 OpenCV 打开 RGB 摄像头...")
            # 尝试常见的视频设备号
            for device_id in [4, 2, 0, 6, 8]:
                self.rgb_cap = cv2.VideoCapture(device_id)
                if self.rgb_cap.isOpened():
                    self.rgb_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    self.rgb_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    self.rgb_cap.set(cv2.CAP_PROP_FPS, 30)
                    # 测试读取一帧
                    ret, test_frame = self.rgb_cap.read()
                    if ret and test_frame is not None:
                        print(f"[INFO] RGB 摄像头已打开 (OpenCV /dev/video{device_id})")
                        self.use_opencv_rgb = True
                        self.has_color = True
                        break
                    else:
                        self.rgb_cap.release()
                        self.rgb_cap = None

            if not self.use_opencv_rgb:
                print("[WARN] 无法通过 OpenCV 打开 RGB 摄像头，将只显示深度")

        self.initialized = True
        return True

    def read_frames(self):
        """读取 RGB 和深度帧"""
        if not self.initialized:
            return None, None

        depth_array = None
        color_array = None

        # 如果使用 OpenCV 读取 RGB
        if self.use_opencv_rgb and self.rgb_cap:
            ret, color_array = self.rgb_cap.read()
            if ret and color_array is not None:
                if color_array.shape[:2] != (480, 640):
                    color_array = cv2.resize(color_array, (640, 480))

        # 通过 Astra SDK 读取深度 (和可能的 RGB)
        astra_core.astra_update()
        frame = astra_reader_frame_t()
        rc = astra_core.astra_reader_open_frame(self.reader, 100, ctypes.byref(frame))

        if rc == 0:
            try:
                # 读取深度帧
                depth_frame = astra_depthframe_t()
                rc = astra.astra_frame_get_depthframe(frame, ctypes.byref(depth_frame))
                if rc == 0:
                    depth_length = ctypes.c_uint32()
                    astra.astra_depthframe_get_data_byte_length(depth_frame, ctypes.byref(depth_length))
                    if depth_length.value > 0:
                        num_pixels = depth_length.value // 2
                        depth_buffer = (ctypes.c_int16 * num_pixels)()
                        astra.astra_depthframe_copy_data(depth_frame, depth_buffer)
                        metadata = AstraImageMetadata()
                        astra.astra_depthframe_get_metadata(depth_frame, ctypes.byref(metadata))
                        self.depth_width = metadata.width
                        self.depth_height = metadata.height
                        depth_array = np.ctypeslib.as_array(depth_buffer).copy()
                        depth_array = depth_array.reshape((self.depth_height, self.depth_width))

                # 如果通过 Astra SDK 读取 RGB
                if not self.use_opencv_rgb and self.has_color and self.color_stream:
                    color_frame = astra_colorframe_t()
                    rc = astra.astra_frame_get_colorframe(frame, ctypes.byref(color_frame))
                    if rc == 0:
                        color_length = ctypes.c_uint32()
                        astra.astra_colorframe_get_data_byte_length(color_frame, ctypes.byref(color_length))
                        if color_length.value > 0:
                            # RGB888 = 3 bytes per pixel
                            num_pixels = color_length.value // 3
                            color_buffer = (ctypes.c_uint8 * color_length.value)()
                            astra.astra_colorframe_copy_data(color_frame, color_buffer)
                            color_metadata = AstraImageMetadata()
                            astra.astra_colorframe_get_metadata(color_frame, ctypes.byref(color_metadata))
                            self.color_width = color_metadata.width
                            self.color_height = color_metadata.height
                            color_array = np.ctypeslib.as_array(color_buffer).copy()
                            color_array = color_array.reshape((self.color_height, self.color_width, 3))
                            # RGB to BGR for OpenCV
                            color_array = cv2.cvtColor(color_array, cv2.COLOR_RGB2BGR)
            finally:
                astra_core.astra_reader_close_frame(ctypes.byref(frame))

        return color_array, depth_array

    def release(self):
        if not self.initialized:
            return
        print("[INFO] 释放资源...")
        if self.has_color and self.color_stream:
            astra_core.astra_stream_stop(self.color_stream)
        astra_core.astra_stream_stop(self.depth_stream)
        astra_core.astra_reader_destroy(ctypes.byref(self.reader))
        astra_core.astra_streamset_close(self.sensor)
        astra_core.astra_terminate()
        if self.rgb_cap:
            self.rgb_cap.release()
        self.initialized = False
        print("[INFO] 资源已释放")

def colorize_depth(depth, min_dist=300, max_dist=5000):
    """深度图彩色化 - Jet 色图"""
    if depth is None:
        return None

    valid_mask = depth > 0
    if not np.any(valid_mask):
        return None

    # 归一化到 0-255 (反转: 近=红，远=蓝)
    depth_norm = np.zeros_like(depth, dtype=np.uint8)
    depth_valid = depth[valid_mask]
    # 反转映射: 近距离值大(红)，远距离值小(蓝)
    depth_norm[valid_mask] = np.clip(255 - (depth_valid - min_dist) / (max_dist - min_dist) * 255, 0, 255).astype(np.uint8)

    # 应用 Jet 色图
    depth_color = cv2.applyColorMap(depth_norm, cv2.COLORMAP_JET)

    return depth_color

def create_overlay(rgb, depth, alpha=0.35):
    """创建 RGB + 深度叠加图像"""
    if rgb is None and depth is None:
        # 都没有数据
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(img, "No camera data", (180, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (128, 128, 128), 2)
        return img

    if rgb is None:
        # 只有深度
        depth_color = colorize_depth(depth)
        if depth_color is not None:
            return depth_color
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(img, "No RGB data", (200, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (128, 128, 128), 2)
        return img

    # 有 RGB
    if rgb.shape[:2] != (480, 640):
        rgb = cv2.resize(rgb, (640, 480))

    if depth is None:
        # 只有 RGB
        return rgb

    # 深度彩色化
    depth_color = colorize_depth(depth)
    if depth_color is None:
        return rgb

    # 调整深度图大小匹配 RGB
    if depth_color.shape[:2] != rgb.shape[:2]:
        depth_color = cv2.resize(depth_color, (rgb.shape[1], rgb.shape[0]))

    # 创建叠加图像 (alpha 混合)
    overlay = cv2.addWeighted(rgb, 1 - alpha, depth_color, alpha, 0)

    return overlay

# 全局变量
connected_clients = set()
camera = AstraCamera()
frame_count = 0
fps = 0
last_fps_time = time.time()

async def send_frames():
    global frame_count, fps, last_fps_time
    while True:
        if connected_clients:
            try:
                rgb_frame, depth_frame = camera.read_frames()

                has_rgb = rgb_frame is not None
                has_depth = depth_frame is not None

                if has_rgb or has_depth:
                    frame_count += 1
                    current_time = time.time()
                    if current_time - last_fps_time >= 1.0:
                        fps = frame_count / (current_time - last_fps_time)
                        frame_count = 0
                        last_fps_time = current_time

                    # 创建叠加图像 (默认 35% 深度透明度)
                    overlay = create_overlay(rgb_frame, depth_frame, alpha=0.35)

                    # 编码为 JPEG
                    ret, encoded = cv2.imencode('.jpg', overlay, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if ret:
                        b64 = base64.b64encode(encoded).decode('utf-8')

                        msg_data = {
                            'type': 'frame',
                            'overlay': b64,
                            'fps': fps,
                            'has_rgb': has_rgb,
                            'has_depth': has_depth
                        }
                        msg = json.dumps(msg_data)

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
                import traceback
                traceback.print_exc()

        await asyncio.sleep(0.033)  # ~30fps

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
    print('Astra Pro Web Server - RGB + Depth Overlay')
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
        print('[INFO] Press Ctrl+C to stop')
        await asyncio.Future()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n[INFO] Stopping...')
        camera.release()
        print('[INFO] Stopped')
