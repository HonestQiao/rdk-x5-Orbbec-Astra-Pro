#!/usr/bin/env python3
"""
Orbbec Astra Pro 深度检测程序
仅使用深度数据进行物体检测和距离测量
"""
import ctypes
import os
import numpy as np
import cv2
import time
import signal

astra_path = '/home/sunrise/AstraSDK/lib'
os.environ['LD_LIBRARY_PATH'] = astra_path + ':' + os.environ.get('LD_LIBRARY_PATH', '')

astra_core = ctypes.CDLL(f'{astra_path}/libastra_core.so')
astra = ctypes.CDLL(f'{astra_path}/libastra.so')

is_stop = False
DISP_W, DISP_H = 800, 480

def signal_handler(sig, frame):
    global is_stop
    is_stop = True

class AstraDepthCamera:
    def __init__(self):
        self.sensor = ctypes.c_void_p()
        self.reader = ctypes.c_void_p()
        self.depth_stream = ctypes.c_void_p()
        self.initialized = False
        
    def initialize(self):
        result = astra_core.astra_initialize()
        if result != 0:
            print('[ERROR] Failed to initialize Astra SDK')
            return False
        
        astra_core.astra_streamset_open(b'device/default', ctypes.byref(self.sensor))
        astra_core.astra_reader_create(self.sensor, ctypes.byref(self.reader))
        astra.astra_reader_get_depthstream(self.reader, ctypes.byref(self.depth_stream))
        astra_core.astra_stream_start(self.depth_stream)
        
        self.initialized = True
        print('[OK] Astra depth camera initialized')
        return True
    
    def read_depth(self):
        astra_core.astra_update()
        frame = ctypes.c_void_p()
        
        if astra_core.astra_reader_open_frame(self.reader, 0, ctypes.byref(frame)) != 0 or not frame:
            return None
        
        depth_frame = ctypes.c_void_p()
        if astra.astra_frame_get_depthframe(frame, ctypes.byref(depth_frame)) != 0 or not depth_frame:
            astra_core.astra_reader_close_frame(frame)
            return None
        
        length = ctypes.c_uint32()
        astra.astra_depthframe_get_data_byte_length(depth_frame, ctypes.byref(length))
        
        depth = None
        if length.value > 0:
            depth_data = (ctypes.c_int16 * (length.value // 2))()
            astra.astra_depthframe_copy_data(depth_frame, depth_data)
            depth = np.ctypeslib.as_array(depth_data).reshape((480, 640))
        
        astra_core.astra_reader_close_frame(frame)
        return depth
    
    def release(self):
        if self.initialized:
            astra_core.astra_terminate()
            self.initialized = False

def colorize_depth(depth, min_dist=300, max_dist=5000):
    if depth is None:
        return np.zeros((480, 640, 3), dtype=np.uint8)
    depth_clipped = np.clip(depth, min_dist, max_dist)
    depth_norm = ((depth_clipped - min_dist) / (max_dist - min_dist) * 255).astype(np.uint8)
    return cv2.applyColorMap(depth_norm, cv2.COLORMAP_JET)

def detect_by_depth(depth, min_depth=600, max_depth=3000):
    if depth is None:
        return []
    
    valid_mask = ((depth >= min_depth) & (depth <= max_depth)).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    valid_mask = cv2.morphologyEx(cv2.morphologyEx(valid_mask, cv2.MORPH_OPEN, kernel), cv2.MORPH_CLOSE, kernel)
    
    contours, _ = cv2.findContours(valid_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    detections = []
    for cnt in contours[:5]:
        area = cv2.contourArea(cnt)
        if area < 5000:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        cx, cy = x + w // 2, y + h // 2
        distance = int(depth[min(cy, 479), min(cx, 639)])
        if distance >= 600:
            detections.append({'box': [x, y, x+w, y+h], 'dist': distance/1000.0, 'id': len(detections)+1, 'cx': cx, 'cy': cy})
    
    return detections

def main():
    global is_stop
    signal.signal(signal.SIGINT, signal_handler)
    
    print('='*60)
    print('Orbbec Astra Pro Depth Detection')
    print('='*60)
    
    camera = AstraDepthCamera()
    if not camera.initialize():
        return
    
    cv2.namedWindow('Depth Detection', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('Depth Detection', DISP_W, DISP_H)
    cv2.moveWindow('Depth Detection', 0, 0)
    
    print('\n[INFO] Running... Press Q to exit\n')
    
    frame_count, start_time, fps = 0, time.time(), 0
    
    try:
        while not is_stop:
            depth = camera.read_depth()
            
            if depth is None:
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
            
            # 绘制检测框
            for det in detections:
                x, y, w, h = det['box']
                cv2.rectangle(depth_color, (x, y), (x+w, y+h), (0, 255, 0), 2)
                cv2.circle(depth_color, (det['cx'], det['cy']), 3, (0, 0, 255), -1)
                label = f"#{det['id']}: {det['dist']:.2f}m"
                cv2.putText(depth_color, label, (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            
            # 调整大小并添加信息
            display = cv2.resize(depth_color, (DISP_W, DISP_H))
            
            # 信息面板
            cv2.putText(display, f'FPS: {fps:.1f}', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.putText(display, f'Objects: {len(detections)}', (200, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.putText(display, 'Q - Quit', (10, DISP_H-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            
            # 深度图例
            cv2.putText(display, 'Near (Red)', (DISP_W-150, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            cv2.putText(display, 'Far (Blue)', (DISP_W-150, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
            
            cv2.imshow('Depth Detection', display)
            
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
