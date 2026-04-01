#!/usr/bin/env python3
"""
Astra Pro + Web Server - RGB + Depth 叠加显示 v2
修复对齐问题和透明度调节
"""

import asyncio
import websockets
import ctypes
import os
import sys
import argparse
import numpy as np
import cv2
import json
import base64
import time
import http.server
import socketserver
import threading

# 命令行参数
parser = argparse.ArgumentParser(description='Astra Pro RGB + Depth Web Server')
parser.add_argument('--max-dist', type=int, default=8000, help='最远距离(mm)，默认8000')
parser.add_argument('--invalid-color', type=str, choices=['black', 'white'], default='black', help='无效深度颜色，默认black')
args = parser.parse_args()

MAX_DIST = args.max_dist
INVALID_COLOR = [0, 0, 0] if args.invalid_color == 'black' else [255, 255, 255]
print(f"[INFO] 参数: max_dist={MAX_DIST}mm, invalid_color={args.invalid_color}")

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

# HTML页面 - 前端分别渲染RGB和深度，用户控制叠加
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
            max-width: 900px;
        }
        .main-display {
            background: #1a1a1a;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #333;
            position: relative;
        }
        .video-title {
            background: #252525;
            padding: 8px 12px;
            font-size: 14px;
            font-weight: 600;
            color: #aaa;
        }
        .canvas-container {
            position: relative;
            width: 100%;
            background: #000;
        }
        .canvas-container canvas {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            display: block;
        }
        #rgbCanvas { z-index: 1; }
        #depthCanvas { z-index: 2; mix-blend-mode: screen; }
        .controls {
            background: #1a1a1a;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #333;
        }
        .control-row {
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 10px;
        }
        .control-row:last-child { margin-bottom: 0; }
        .control-row label {
            font-size: 13px;
            color: #aaa;
            min-width: 100px;
        }
        .control-row input[type="range"] {
            flex: 1;
            height: 8px;
            -webkit-appearance: none;
            background: #333;
            border-radius: 4px;
            outline: none;
        }
        .control-row input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 18px;
            height: 18px;
            background: #00d4ff;
            border-radius: 50%;
            cursor: pointer;
        }
        .control-row span {
            font-size: 13px;
            color: #00d4ff;
            min-width: 50px;
            text-align: right;
        }
        .checkbox-row {
            display: flex;
            gap: 20px;
            align-items: center;
        }
        .checkbox-row label {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: #aaa;
            cursor: pointer;
        }
        .checkbox-row input[type="checkbox"] {
            width: 18px;
            height: 18px;
            accent-color: #00d4ff;
        }
        .legend {
            display: flex;
            justify-content: center;
            gap: 20px;
            padding: 12px;
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
            height: 14px;
            border-radius: 3px;
        }
        .near { background: #ff0000; }
        .mid { background: #ffff00; }
        .far { background: #00ffff; }
        .vfar { background: #0000ff; }
        .status-bar {
            background: #1a1a1a;
            padding: 12px 15px;
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
        .dual-view {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        .view-box {
            background: #1a1a1a;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #333;
        }
        .view-box .title {
            background: #252525;
            padding: 6px 10px;
            font-size: 12px;
            color: #888;
        }
        .view-box canvas {
            width: 100%;
            display: block;
            background: #000;
        }
    </style>
</head>
<body>
    <h1>Astra Pro RGB + Depth Overlay</h1>
    <div class="container">

        <div class="main-display">
            <div class="video-title">叠加显示 (底层=RGB, 上层=深度热图)</div>
            <div class="canvas-container" id="container">
                <canvas id="rgbCanvas"></canvas>
                <canvas id="depthCanvas"></canvas>
            </div>
        </div>

        <div class="controls">
            <div class="control-row">
                <label>深度透明度:</label>
                <input type="range" id="alphaSlider" min="0" max="100" value="40">
                <span id="alphaValue">40%</span>
            </div>
            <div class="checkbox-row">
                <label><input type="checkbox" id="showRgb" checked> 显示 RGB</label>
                <label><input type="checkbox" id="showDepth" checked> 显示深度</label>
                <label><input type="checkbox" id="showRawDepth" checked> 原始深度图</label>
            </div>
        </div>

        <div class="dual-view" id="rawViews">
            <div class="view-box">
                <div class="title">RGB 原图</div>
                <canvas id="rawRgbCanvas"></canvas>
            </div>
            <div class="view-box">
                <div class="title">深度热图</div>
                <canvas id="rawDepthCanvas"></canvas>
            </div>
        </div>

        <div class="dual-view" id="extraViews">
            <div class="view-box">
                <div class="title">灰度图 (原始深度)</div>
                <canvas id="grayCanvas"></canvas>
            </div>
            <div class="view-box">
                <div class="title">深度网格图</div>
                <canvas id="gridCanvas"></canvas>
            </div>
        </div>

        <div class="legend">
            <div class="legend-item">
                <div class="color-box near"></div>
                <span>近 (红)</span>
            </div>
            <div class="legend-item">
                <div class="color-box mid"></div>
                <span>中近 (黄)</span>
            </div>
            <div class="legend-item">
                <div class="color-box far"></div>
                <span>中远 (青)</span>
            </div>
            <div class="legend-item">
                <div class="color-box vfar"></div>
                <span>远 (蓝)</span>
            </div>
        </div>

        <div class="status-bar">
            <div class="status-item">
                <span class="label">FPS</span>
                <span class="value" id="fps">--</span>
            </div>
            <div class="status-item">
                <span class="label">分辨率</span>
                <span class="value" id="resolution">--</span>
            </div>
            <div class="status-item">
                <span class="label">Status</span>
                <span class="value disconnected" id="status">Disconnected</span>
            </div>
        </div>
    </div>

    <script>
        const container = document.getElementById('container');
        const rgbCanvas = document.getElementById('rgbCanvas');
        const depthCanvas = document.getElementById('depthCanvas');
        const rawRgbCanvas = document.getElementById('rawRgbCanvas');
        const rawDepthCanvas = document.getElementById('rawDepthCanvas');
        const grayCanvas = document.getElementById('grayCanvas');
        const gridCanvas = document.getElementById('gridCanvas');
        const rgbCtx = rgbCanvas.getContext('2d');
        const depthCtx = depthCanvas.getContext('2d');
        const rawRgbCtx = rawRgbCanvas.getContext('2d');
        const rawDepthCtx = rawDepthCanvas.getContext('2d');
        const grayCtx = grayCanvas.getContext('2d');
        const gridCtx = gridCanvas.getContext('2d');

        const alphaSlider = document.getElementById('alphaSlider');
        const alphaValue = document.getElementById('alphaValue');
        const showRgbCheck = document.getElementById('showRgb');
        const showDepthCheck = document.getElementById('showDepth');
        const showRawCheck = document.getElementById('showRawDepth');
        const rawViews = document.getElementById('rawViews');
        const extraViews = document.getElementById('extraViews');

        let ws = null;
        let reconnectInterval = 1000;
        let currentAlpha = 0.4;

        // 控制事件
        alphaSlider.addEventListener('input', (e) => {
            currentAlpha = e.target.value / 100;
            alphaValue.textContent = e.target.value + '%';
            depthCanvas.style.opacity = currentAlpha;
        });

        showRgbCheck.addEventListener('change', (e) => {
            rgbCanvas.style.display = e.target.checked ? 'block' : 'none';
        });

        showDepthCheck.addEventListener('change', (e) => {
            depthCanvas.style.display = e.target.checked ? 'block' : 'none';
        });

        showRawCheck.addEventListener('change', (e) => {
            rawViews.style.display = e.target.checked ? 'grid' : 'none';
        });

        function resizeCanvases(width, height) {
            // 设置容器高度保持比例
            const containerWidth = container.clientWidth;
            const containerHeight = Math.round(containerWidth * height / width);
            container.style.height = containerHeight + 'px';

            // 主显示画布
            if (rgbCanvas.width !== width || rgbCanvas.height !== height) {
                rgbCanvas.width = width;
                rgbCanvas.height = height;
                depthCanvas.width = width;
                depthCanvas.height = height;
            }

            // 原始视图画布
            const rawWidth = Math.floor(width / 2);
            const rawHeight = Math.floor(height / 2);
            if (rawRgbCanvas.width !== rawWidth) {
                rawRgbCanvas.width = rawWidth;
                rawRgbCanvas.height = rawHeight;
                rawDepthCanvas.width = rawWidth;
                rawDepthCanvas.height = rawHeight;
            }

            // 灰度图和网格图画布
            if (grayCanvas.width !== rawWidth) {
                grayCanvas.width = rawWidth;
                grayCanvas.height = rawHeight;
                gridCanvas.width = rawWidth;
                gridCanvas.height = rawHeight;
            }
        }

        function drawGrid(distances, width, height) {
            // 清空画布
            gridCtx.clearRect(0, 0, gridCanvas.width, gridCanvas.height);

            // 绘制半透明背景
            gridCtx.fillStyle = 'rgba(0, 0, 0, 0.3)';
            gridCtx.fillRect(0, 0, gridCanvas.width, gridCanvas.height);

            const cols = 10, rows = 10;
            const cellW = gridCanvas.width / cols;
            const cellH = gridCanvas.height / rows;

            // 绘制网格线
            gridCtx.strokeStyle = 'rgba(255, 255, 255, 0.6)';
            gridCtx.lineWidth = 1;
            for (let i = 0; i <= cols; i++) {
                gridCtx.beginPath();
                gridCtx.moveTo(i * cellW, 0);
                gridCtx.lineTo(i * cellW, gridCanvas.height);
                gridCtx.stroke();
            }
            for (let i = 0; i <= rows; i++) {
                gridCtx.beginPath();
                gridCtx.moveTo(0, i * cellH);
                gridCtx.lineTo(gridCanvas.width, i * cellH);
                gridCtx.stroke();
            }

            // 绘制距离数值
            gridCtx.font = 'bold 9px Arial';
            gridCtx.textAlign = 'center';
            gridCtx.textBaseline = 'middle';

            let distIdx = 0;
            for (let row = 0; row < rows; row++) {
                for (let col = 0; col < cols; col++) {
                    const cx = (col + 0.5) * cellW;
                    const cy = (row + 0.5) * cellH;

                    if (distIdx < distances.length) {
                        const dist = distances[distIdx++];
                        const distText = dist > 0 ? dist.toFixed(2) + 'm' : '--';

                        // 根据距离选择颜色
                        if (dist < 0.6) gridCtx.fillStyle = '#ff6666';
                        else if (dist < 1.2) gridCtx.fillStyle = '#66ff66';
                        else gridCtx.fillStyle = '#66aaff';

                        // 绘制文字背景
                        const textW = gridCtx.measureText(distText).width + 4;
                        gridCtx.fillStyle = 'rgba(0, 0, 0, 0.7)';
                        gridCtx.fillRect(cx - textW/2, cy - 6, textW, 12);

                        // 绘制文字
                        if (dist < 0.6) gridCtx.fillStyle = '#ff6666';
                        else if (dist < 1.2) gridCtx.fillStyle = '#66ff66';
                        else gridCtx.fillStyle = '#66aaff';
                        gridCtx.fillText(distText, cx, cy);
                    }
                }
            }
        }

        function updateStatus(connected, width, height) {
            const statusEl = document.getElementById('status');
            statusEl.textContent = connected ? 'Connected' : 'Disconnected';
            statusEl.className = 'value ' + (connected ? 'connected' : 'disconnected');
            document.getElementById('resolution').textContent = connected && width ? `${width}x${height}` : '--';
        }

        function drawWaiting() {
            rgbCtx.fillStyle = '#111';
            rgbCtx.fillRect(0, 0, rgbCanvas.width, rgbCanvas.height);
            rgbCtx.strokeStyle = '#333';
            rgbCtx.lineWidth = 2;
            rgbCtx.strokeRect(10, 10, rgbCanvas.width - 20, rgbCanvas.height - 20);
            rgbCtx.fillStyle = '#666';
            rgbCtx.font = '16px Arial';
            rgbCtx.textAlign = 'center';
            rgbCtx.textBaseline = 'middle';
            rgbCtx.fillText('Waiting for camera...', rgbCanvas.width/2, rgbCanvas.height/2);
        }

        function connect() {
            const wsUrl = 'ws://' + window.location.hostname + ':8001/ws';
            ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                updateStatus(true, 0, 0);
                reconnectInterval = 1000;
            };

            ws.onclose = () => {
                updateStatus(false, 0, 0);
                drawWaiting();
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
                        updateStatus(true, data.width, data.height);

                        // RGB 图像
                        if (data.rgb) {
                            const rgbImg = new Image();
                            rgbImg.onload = () => {
                                resizeCanvases(rgbImg.width, rgbImg.height);
                                rgbCtx.drawImage(rgbImg, 0, 0);
                                if (showRawCheck.checked) {
                                    rawRgbCtx.drawImage(rgbImg, 0, 0, rawRgbCanvas.width, rawRgbCanvas.height);
                                }
                            };
                            rgbImg.src = 'data:image/jpeg;base64,' + data.rgb;
                        }

                        // 深度图像
                        if (data.depth) {
                            const depthImg = new Image();
                            depthImg.onload = () => {
                                depthCtx.clearRect(0, 0, depthCanvas.width, depthCanvas.height);
                                depthCtx.drawImage(depthImg, 0, 0);
                                if (showRawCheck.checked) {
                                    rawDepthCtx.drawImage(depthImg, 0, 0, rawDepthCanvas.width, rawDepthCanvas.height);
                                }
                            };
                            depthImg.src = 'data:image/jpeg;base64,' + data.depth;
                        }

                        // 灰度图 (原始深度)
                        if (data.gray) {
                            const grayImg = new Image();
                            grayImg.onload = () => {
                                grayCtx.drawImage(grayImg, 0, 0, grayCanvas.width, grayCanvas.height);
                            };
                            grayImg.src = 'data:image/jpeg;base64,' + data.gray;
                        }

                        // 网格距离数据
                        if (data.distances && data.depth_width && data.depth_height) {
                            drawGrid(data.distances, data.depth_width, data.depth_height);
                        }
                    }
                } catch (e) {
                    console.error('Parse error:', e);
                }
            };
        }

        // 初始化
        rgbCanvas.width = 640;
        rgbCanvas.height = 480;
        depthCanvas.width = 640;
        depthCanvas.height = 480;
        rawRgbCanvas.width = 320;
        rawRgbCanvas.height = 240;
        rawDepthCanvas.width = 320;
        rawDepthCanvas.height = 240;
        grayCanvas.width = 320;
        grayCanvas.height = 240;
        gridCanvas.width = 320;
        gridCanvas.height = 240;
        container.style.height = '360px';
        depthCanvas.style.opacity = currentAlpha;
        drawWaiting();
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
            for device_id in [4, 2, 0, 6, 8]:
                self.rgb_cap = cv2.VideoCapture(device_id)
                if self.rgb_cap.isOpened():
                    self.rgb_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    self.rgb_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    self.rgb_cap.set(cv2.CAP_PROP_FPS, 30)
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
                            num_pixels = color_length.value // 3
                            color_buffer = (ctypes.c_uint8 * color_length.value)()
                            astra.astra_colorframe_copy_data(color_frame, color_buffer)
                            color_metadata = AstraImageMetadata()
                            astra.astra_colorframe_get_metadata(color_frame, ctypes.byref(color_metadata))
                            self.color_width = color_metadata.width
                            self.color_height = color_metadata.height
                            color_array = np.ctypeslib.as_array(color_buffer).copy()
                            color_array = color_array.reshape((self.color_height, self.color_width, 3))
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

def colorize_depth(depth, min_dist=300):
    """深度图彩色化 - JET色图: 近=暖色(红), 远=冷色(蓝)"""
    global MAX_DIST, INVALID_COLOR

    if depth is None:
        return None

    valid_mask = depth > 0
    h, w = depth.shape

    # 创建输出图像，默认填充无效颜色
    depth_norm = np.zeros((h, w), dtype=np.uint8)

    if np.any(valid_mask):
        depth_valid = depth[valid_mask].astype(np.float32)

        # 归一化到 0-255: 近(min_dist)=255, 远(MAX_DIST)=0
        # 这样 JET 色图会把近处映射为红色，远处映射为蓝色
        normalized = 255 - np.clip((depth_valid - min_dist) / (MAX_DIST - min_dist) * 255, 0, 255)
        depth_norm[valid_mask] = normalized.astype(np.uint8)

    # 应用 JET 色图
    depth_colored = cv2.applyColorMap(depth_norm, cv2.COLORMAP_JET)

    # 无效区域设置为指定颜色
    depth_colored[~valid_mask] = INVALID_COLOR

    return depth_colored

def gray_depth(depth, min_dist=300):
    """生成灰度深度图 - 近=白(255), 远=黑(0)"""
    global MAX_DIST

    if depth is None:
        return None

    valid_mask = depth > 0
    h, w = depth.shape

    # 默认填充白色（用于无效深度）
    gray = np.full((h, w), 255, dtype=np.uint8)

    if np.any(valid_mask):
        depth_valid = depth[valid_mask].astype(np.float32)
        # 归一化: 近=min_dist -> 255(白), 远=MAX_DIST -> 0(黑)
        gray_values = 255 - np.clip((depth_valid - min_dist) / (MAX_DIST - min_dist) * 255, 0, 255)
        gray[valid_mask] = gray_values.astype(np.uint8)

    # 转3通道以便JPEG编码
    gray_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return gray_bgr

def get_grid_distances(depth, cols=10, rows=10):
    """获取网格中心点距离 (米)"""
    if depth is None:
        return [0.0] * (cols * rows)

    h, w = depth.shape
    distances = []

    for row in range(rows):
        for col in range(cols):
            cy = int((row + 0.5) * h / rows)
            cx = int((col + 0.5) * w / cols)
            dist_mm = depth[cy, cx]

            if dist_mm > 0:
                dist_m = min(dist_mm / 1000.0, 10.0)  # 限制最大10米
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

                    msg_data = {
                        'type': 'frame',
                        'fps': fps,
                        'has_rgb': has_rgb,
                        'has_depth': has_depth,
                        'width': 640,
                        'height': 480
                    }

                    # RGB 编码
                    if has_rgb:
                        if rgb_frame.shape[:2] != (480, 640):
                            rgb_frame = cv2.resize(rgb_frame, (640, 480))
                        ret, rgb_encoded = cv2.imencode('.jpg', rgb_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        if ret:
                            msg_data['rgb'] = base64.b64encode(rgb_encoded).decode('utf-8')

                    # 深度编码
                    if has_depth:
                        depth_color = colorize_depth(depth_frame)
                        if depth_color is not None:
                            if depth_color.shape[:2] != (480, 640):
                                depth_color = cv2.resize(depth_color, (640, 480))
                            ret, depth_encoded = cv2.imencode('.jpg', depth_color, [cv2.IMWRITE_JPEG_QUALITY, 85])
                            if ret:
                                msg_data['depth'] = base64.b64encode(depth_encoded).decode('utf-8')

                        # 灰度图编码
                        gray_img = gray_depth(depth_frame)
                        if gray_img is not None:
                            if gray_img.shape[:2] != (480, 640):
                                gray_img = cv2.resize(gray_img, (640, 480))
                            ret, gray_encoded = cv2.imencode('.jpg', gray_img, [cv2.IMWRITE_JPEG_QUALITY, 85])
                            if ret:
                                msg_data['gray'] = base64.b64encode(gray_encoded).decode('utf-8')

                        # 网格距离
                        msg_data['distances'] = get_grid_distances(depth_frame)
                        msg_data['depth_width'] = depth_frame.shape[1]
                        msg_data['depth_height'] = depth_frame.shape[0]

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
    print('Astra Pro Web Server - RGB + Depth Overlay v2')
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
