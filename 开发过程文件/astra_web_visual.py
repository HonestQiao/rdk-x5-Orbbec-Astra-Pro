#!/usr/bin/env python3
"""
Astra Pro Web-style Depth Visualizer
参考: RDK官方web_depth_visual效果
- 上下分屏显示
- Jet热力图深度
- 网格距离标注
- 系统状态显示
"""

import ctypes
import os
import numpy as np
import cv2
import time
import signal

# Astra SDK路径
astra_path = '/home/sunrise/AstraSDK/lib'
os.environ['LD_LIBRARY_PATH'] = astra_path + ':' + os.environ.get('LD_LIBRARY_PATH', '')

# 加载库
astra_core = ctypes.CDLL(f'{astra_path}/libastra_core.so')
astra = ctypes.CDLL(f'{astra_path}/libastra.so')

# 全局变量
is_stop = False

# 显示配置
RGB_W, RGB_H = 640, 480
DEPTH_W, DEPTH_H = 640, 480
GRID_COLS, GRID_ROWS = 5, 5

def signal_handler(sig, frame):
    global is_stop
    is_stop = True

def get_cpu_freq():
    """获取CPU频率(MHz)"""
    try:
        with open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq', 'r') as f:
            return int(f.read().strip()) // 1000
    except:
        return 0

def get_cpu_temp():
    """获取CPU温度(°C)"""
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return int(f.read().strip()) / 1000.0
    except:
        return 0.0

class AstraCamera:
    def __init__(self):
        self.sensor = ctypes.c_void_p()
        self.reader = ctypes.c_void_p()
        self.depth_stream = ctypes.c_void_p()
        self.color_stream = ctypes.c_void_p()
        self.initialized = False
        
    def initialize(self):
        print('[INFO] Initializing Astra camera...')
        
        # 初始化Astra
        if astra_core.astra_initialize() != 0:
            print('[ERROR] Failed to initialize Astra')
            return False
        
        # 打开设备
        astra_core.astra_streamset_open(b'device/default', ctypes.byref(self.sensor))
        
        # 创建reader
        astra_core.astra_reader_create(self.sensor, ctypes.byref(self.reader))
        
        # 获取深度流
        astra.astra_reader_get_depthstream(self.reader, ctypes.byref(self.depth_stream))
        astra_core.astra_stream_start(self.depth_stream)
        
        # 尝试获取彩色流
        try:
            astra.astra_reader_get_colorstream(self.reader, ctypes.byref(self.color_stream))
            astra_core.astra_stream_start(self.color_stream)
            print('[OK] RGB stream started')
        except:
            self.color_stream = None
            print('[WARN] RGB stream not available')
        
        self.initialized = True
        print('[OK] Camera initialized')
        return True
    
    def read_frames(self):
        astra_core.astra_update()
        
        # 读取深度帧
        depth = None
        frame = ctypes.c_void_p()
        if astra_core.astra_reader_open_frame(self.reader, 0, ctypes.byref(frame)) == 0 and frame.value:
            depth_frame = ctypes.c_void_p()
            if astra.astra_frame_get_depthframe(frame, ctypes.byref(depth_frame)) == 0 and depth_frame.value:
                length = ctypes.c_uint32()
                astra.astra_depthframe_get_data_byte_length(depth_frame, ctypes.byref(length))
                if length.value > 0:
                    depth_data = (ctypes.c_int16 * (length.value // 2))()
                    astra.astra_depthframe_copy_data(depth_frame, depth_data)
                    depth = np.ctypeslib.as_array(depth_data).reshape((DEPTH_H, DEPTH_W))
            astra_core.astra_reader_close_frame(frame)
        
        # 读取彩色帧
        color = None
        if self.color_stream and self.color_stream.value:
            frame = ctypes.c_void_p()
            if astra_core.astra_reader_open_frame(self.reader, 0, ctypes.byref(frame)) == 0 and frame.value:
                color_frame = ctypes.c_void_p()
                if astra.astra_frame_get_colorframe(frame, ctypes.byref(color_frame)) == 0 and color_frame.value:
                    # 获取彩色数据
                    length = ctypes.c_uint32()
                    astra.astra_colorframe_get_data_byte_length(color_frame, ctypes.byref(length))
                    if length.value > 0:
                        color_data = (ctypes.c_uint8 * length.value)()
                        astra.astra_colorframe_copy_data(color_frame, color_data)
                        color = np.ctypeslib.as_array(color_data).reshape((RGB_H, RGB_W, 3))
                astra_core.astra_reader_close_frame(frame)
        
        return color, depth
    
    def release(self):
        if self.initialized:
            astra_core.astra_terminate()
            self.initialized = False

def colorize_depth_jet(depth_data, min_dist=200, max_dist=1500):
    """深度图Jet热力图彩色化"""
    if depth_data is None:
        return np.zeros((DEPTH_H, DEPTH_W, 3), dtype=np.uint8)
    
    # 裁剪到有效范围
    depth_clipped = np.clip(depth_data, min_dist, max_dist)
    
    # 归一化到0-255
    depth_norm = ((depth_clipped - min_dist) / (max_dist - min_dist) * 255).astype(np.uint8)
    
    # 应用Jet颜色映射
    depth_color = cv2.applyColorMap(depth_norm, cv2.COLORMAP_JET)
    
    return depth_color

def draw_grid_and_distance(canvas, depth_data, grid_cols=5, grid_rows=5):
    """绘制网格和距离标注"""
    if depth_data is None:
        return canvas
    
    h, w = canvas.shape[:2]
    cell_w = w // grid_cols
    cell_h = h // grid_rows
    
    # 绘制网格线
    for i in range(1, grid_cols):
        x = i * cell_w
        cv2.line(canvas, (x, 0), (x, h), (255, 255, 255), 1)
    for i in range(1, grid_rows):
        y = i * cell_h
        cv2.line(canvas, (y, 0), (y, h), (255, 255, 255), 1)  # 修正：应为(w, y)
    
    for i in range(1, grid_rows):
        y = i * cell_h
        cv2.line(canvas, (0, y), (w, y), (255, 255, 255), 1)
    
    # 在每个网格中心标注距离
    for row in range(grid_rows):
        for col in range(grid_cols):
            cx = col * cell_w + cell_w // 2
            cy = row * cell_h + cell_h // 2
            
            # 获取深度值
            depth_mm = int(depth_data[min(cy, DEPTH_H-1), min(cx, DEPTH_W-1)])
            depth_m = depth_mm / 1000.0
            
            # 显示距离文本
            text = f'{depth_m:.2f}m'
            (text_w, text_h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            
            # 背景
            cv2.rectangle(canvas, 
                         (cx - text_w//2 - 2, cy - text_h//2 - 2),
                         (cx + text_w//2 + 2, cy + text_h//2 + 2),
                         (0, 0, 0), -1)
            
            # 文字
            cv2.putText(canvas, text, 
                       (cx - text_w//2, cy + text_h//2),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    
    return canvas

def create_web_visual(color, depth, fps, cpu_freq, cpu_temp):
    """创建类似RDK web visual的效果"""
    # 如果RGB不可用，创建灰色图像
    if color is None:
        rgb_display = np.zeros((RGB_H, RGB_W, 3), dtype=np.uint8)
        cv2.putText(rgb_display, 'RGB Not Available', (RGB_W//2-100, RGB_H//2),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (128, 128, 128), 2)
    else:
        rgb_display = color.copy()
    
    # 深度图彩色化
    depth_color = colorize_depth_jet(depth, 200, 1500)
    
    # 在深度图上绘制网格和距离
    depth_display = draw_grid_and_distance(depth_color, depth, GRID_COLS, GRID_ROWS)
    
    # 调整大小到相同宽度
    target_w = 640
    rgb_resized = cv2.resize(rgb_display, (target_w, 360))
    depth_resized = cv2.resize(depth_display, (target_w, 360))
    
    # 创建状态栏
    status_h = 40
    status_bar = np.zeros((status_h, target_w, 3), dtype=np.uint8)
    status_bar[:] = (40, 40, 40)  # 深灰色背景
    
    # 状态信息
    status_text = f'fps: {fps:.1f}  cpu: {cpu_freq}  temp: {cpu_temp:.1f}'
    cv2.putText(status_bar, status_text, (10, 28),
               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
    
    # D-Robotics logo位置
    logo_text = 'D-Robotics'
    (logo_w, _), _ = cv2.getTextSize(logo_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.putText(status_bar, logo_text, (target_w - logo_w - 10, 28),
               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 150, 255), 1)
    
    # 合成最终画面
    # 顶部RGB，中间深度图，底部状态栏
    final_h = 360 + 360 + status_h
    final_canvas = np.zeros((final_h, target_w, 3), dtype=np.uint8)
    
    final_canvas[0:360, 0:target_w] = rgb_resized
    final_canvas[360:720, 0:target_w] = depth_resized
    final_canvas[720:720+status_h, 0:target_w] = status_bar
    
    # 添加分隔线
    cv2.line(final_canvas, (0, 360), (target_w, 360), (100, 100, 100), 2)
    cv2.line(final_canvas, (0, 720), (target_w, 720), (100, 100, 100), 2)
    
    return final_canvas

def main():
    global is_stop
    signal.signal(signal.SIGINT, signal_handler)
    
    print('='*60)
    print('Astra Pro Web-style Depth Visualizer')
    print('参考: RDK web_depth_visual')
    print('='*60)
    
    camera = AstraCamera()
    if not camera.initialize():
        return
    
    # 创建窗口
    cv2.namedWindow('Astra Web Visual', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('Astra Web Visual', 640, 760)
    cv2.moveWindow('Astra Web Visual', 0, 0)
    
    print('\n[INFO] Running... Press Q to exit\n')
    
    # 统计
    frame_count, start_time, fps = 0, time.time(), 0.0
    
    try:
        while not is_stop:
            # 读取帧
            color, depth = camera.read_frames()
            
            # 计算FPS
            frame_count += 1
            elapsed = time.time() - start_time
            if elapsed >= 1.0:
                fps = frame_count / elapsed
                frame_count, start_time = 0, time.time()
            
            # 获取系统状态
            cpu_freq = get_cpu_freq()
            cpu_temp = get_cpu_temp()
            
            # 创建显示画面
            display = create_web_visual(color, depth, fps, cpu_freq, cpu_temp)
            
            # 显示
            cv2.imshow('Astra Web Visual', display)
            
            # 按键处理
            key = cv2.waitKey(1) & 0xFF
            if key in [ord('q'), 27]:  # Q或ESC
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
