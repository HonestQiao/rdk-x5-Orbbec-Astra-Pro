#!/usr/bin/env python3
"""
Orbbec Astra Pro 深度 + AI 检测程序
使用Astra SDK读取深度，OpenCV读取RGB，Hobot DNN进行AI检测
"""
import ctypes
import os
import sys
import numpy as np
import cv2
import time
import signal

# 设置库路径
astra_path = '/home/sunrise/AstraSDK/lib'
os.environ['LD_LIBRARY_PATH'] = astra_path + ':' + os.environ.get('LD_LIBRARY_PATH', '')

# 加载Astra库
astra_core = ctypes.CDLL(f'{astra_path}/libastra_core.so')
astra = ctypes.CDLL(f'{astra_path}/libastra.so')

# 全局变量
is_stop = False
DISP_W, DISP_H = 800, 480

def signal_handler(sig, frame):
    global is_stop
    is_stop = True

class AstraCamera:
    """Astra Pro相机封装"""
    def __init__(self):
        self.sensor = ctypes.c_void_p()
        self.reader = ctypes.c_void_p()
        self.depth_stream = ctypes.c_void_p()
        self.initialized = False
        self.cap = None
        
    def initialize(self):
        # 初始化Astra SDK深度
        result = astra_core.astra_initialize()
        if result != 0:
            print('[ERROR] Failed to initialize Astra SDK')
            return False
        
        astra_core.astra_streamset_open(b'device/default', ctypes.byref(self.sensor))
        astra_core.astra_reader_create(self.sensor, ctypes.byref(self.reader))
        astra.astra_reader_get_depthstream(self.reader, ctypes.byref(self.depth_stream))
        astra_core.astra_stream_start(self.depth_stream)
        
        # 初始化OpenCV RGB
        self.cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        self.initialized = True
        print('[OK] Astra camera initialized')
        return True
    
    def read_frames(self):
        """读取深度和RGB帧"""
        # 读取深度
        astra_core.astra_update()
        frame = ctypes.c_void_p()
        depth = None
        
        if astra_core.astra_reader_open_frame(self.reader, 0, ctypes.byref(frame)) == 0 and frame:
            depth_frame = ctypes.c_void_p()
            if astra.astra_frame_get_depthframe(frame, ctypes.byref(depth_frame)) == 0 and depth_frame:
                length = ctypes.c_uint32()
                astra.astra_depthframe_get_data_byte_length(depth_frame, ctypes.byref(length))
                
                if length.value > 0:
                    depth_data = (ctypes.c_int16 * (length.value // 2))()
                    astra.astra_depthframe_copy_data(depth_frame, depth_data)
                    depth = np.ctypeslib.as_array(depth_data).reshape((480, 640))
            astra_core.astra_reader_close_frame(frame)
        
        # 读取RGB
        ret, color = self.cap.read()
        if not ret:
            color = None
            
        return color, depth
    
    def release(self):
        if self.initialized:
            self.cap.release()
            astra_core.astra_terminate()
            self.initialized = False

def colorize_depth(depth_data, min_dist=300, max_dist=5000):
    """深度图彩色化"""
    if depth_data is None:
        return np.zeros((480, 640, 3), dtype=np.uint8)
    
    depth_clipped = np.clip(depth_data, min_dist, max_dist)
    depth_norm = ((depth_clipped - min_dist) / (max_dist - min_dist) * 255).astype(np.uint8)
    return cv2.applyColorMap(depth_norm, cv2.COLORMAP_JET)

def detect_by_depth(depth_data, min_depth=600, max_depth=3000):
    """基于深度的目标检测"""
    if depth_data is None:
        return []
    
    valid_mask = ((depth_data >= min_depth) & (depth_data <= max_depth)).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    valid_mask = cv2.morphologyEx(valid_mask, cv2.MORPH_OPEN, kernel)
    valid_mask = cv2.morphologyEx(valid_mask, cv2.MORPH_CLOSE, kernel)
    
    contours, _ = cv2.findContours(valid_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    detections = []
    for cnt in contours[:5]:
        area = cv2.contourArea(cnt)
        if area < 5000:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        cx, cy = x + w // 2, y + h // 2
        distance = int(depth_data[cy, cx]) if 0 <= cy < 480 and 0 <= cx < 640 else 0
        if distance >= 600:
            detections.append({'box': [x, y, x+w, y+h], 'dist': distance/1000.0, 'id': len(detections)+1})
    
    return detections

def main():
    global is_stop
    signal.signal(signal.SIGINT, signal_handler)
    
    print('='*60)
    print('Orbbec Astra Pro Depth + AI Detection')
    print('='*60)
    
    camera = AstraCamera()
    if not camera.initialize():
        return
    
    cv2.namedWindow('Astra Depth + AI', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('Astra Depth + AI', DISP_W, DISP_H)
    cv2.moveWindow('Astra Depth + AI', 0, 0)
    
    print('\n[INFO] Running... Press Q to exit\n')
    
    frame_count, start_time, fps = 0, time.time(), 0
    
    try:
        while not is_stop:
            color, depth = camera.read_frames()
            
            if color is None:
                continue
            
            # 深度检测
            detections = detect_by_depth(depth, 600, 3000)
            
            # 计算FPS
            frame_count += 1
            elapsed = time.time() - start_time
            if elapsed >= 1.0:
                fps = frame_count / elapsed
                frame_count, start_time = 0, time.time()
            
            # 深度图彩色化
            depth_color = colorize_depth(depth, 300, 8000)
            
            # 创建显示画面
            rgb_small = cv2.resize(color, (400, 300))
            depth_small = cv2.resize(depth_color, (400, 300))
            
            # 绘制检测框
            for det in detections:
                x, y, w, h = det['box']
                sx, sy = int(x * 400/640), int(y * 300/480)
                sw, sh = int(w * 400/640), int(h * 300/480)
                cv2.rectangle(rgb_small, (sx, sy), (sx+sw, sy+sh), (0, 255, 0), 2)
                cv2.putText(rgb_small, f"#{det['id']}: {det['dist']:.2f}m", (sx, sy-5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            
            # 合成画面
            canvas = np.zeros((DISP_H, DISP_W, 3), dtype=np.uint8)
            canvas[0:300, 0:400] = rgb_small
            canvas[0:300, 400:800] = depth_small
            
            # 信息面板
            cv2.putText(canvas, f'FPS: {fps:.1f}', (10, 330), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.putText(canvas, f'Objects: {len(detections)}', (150, 330), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.putText(canvas, 'Q - Quit', (10, 360), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            
            cv2.imshow('Astra Depth + AI', canvas)
            
            if cv2.waitKey(1) & 0xFF in [ord('q'), 27]:
                break
                
    except KeyboardInterrupt:
        pass
    finally:
        print('\n[INFO] Cleaning up...')
        camera.release()
        cv2.destroyAllWindows()
        print('[INFO] Done!')

if __name__ == '__main__':
    main()
