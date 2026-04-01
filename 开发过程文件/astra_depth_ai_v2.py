#!/usr/bin/env python3
"""
Orbbec Astra Pro 深度 + AI 检测程序
使用 Astra SDK C API 通过 ctypes 调用
"""
import ctypes
import os
import numpy as np
import cv2
import time
import sys

# 设置库路径
astra_path = '/home/sunrise/AstraSDK/lib'
os.environ['LD_LIBRARY_PATH'] = astra_path + ':' + os.environ.get('LD_LIBRARY_PATH', '')

# 加载库
astra_core = ctypes.CDLL(f'{astra_path}/libastra_core.so')
astra = ctypes.CDLL(f'{astra_path}/libastra.so')

# 类型定义
astra_streamsetconnection_t = ctypes.c_void_p
astra_reader_t = ctypes.c_void_p
astra_depthstream_t = ctypes.c_void_p
astra_reader_frame_t = ctypes.c_void_p
astra_depthframe_t = ctypes.c_void_p

class AstraDepthReader:
    def __init__(self):
        self.sensor = astra_streamsetconnection_t()
        self.reader = astra_reader_t()
        self.depth_stream = astra_depthstream_t()
        self.initialized = False
        
    def initialize(self):
        result = astra_core.astra_initialize()
        if result != 0:
            print('Failed to initialize Astra SDK')
            return False
        
        astra_core.astra_streamset_open(b'device/default', ctypes.byref(self.sensor))
        astra_core.astra_reader_create(self.sensor, ctypes.byref(self.reader))
        astra.astra_reader_get_depthstream(self.reader, ctypes.byref(self.depth_stream))
        astra_core.astra_stream_start(self.depth_stream)
        
        self.initialized = True
        print('[OK] Astra depth reader initialized')
        return True
    
    def read_depth(self):
        if not self.initialized:
            return None
            
        astra_core.astra_update()
        
        frame = astra_reader_frame_t()
        result = astra_core.astra_reader_open_frame(self.reader, 0, ctypes.byref(frame))
        
        if result != 0 or not frame:
            return None
        
        depth_frame = astra_depthframe_t()
        astra.astra_frame_get_depthframe(frame, ctypes.byref(depth_frame))
        
        if not depth_frame:
            return None
        
        # 获取深度数据长度
        depth_length = ctypes.c_uint32()
        astra.astra_depthframe_get_data_byte_length(depth_frame, ctypes.byref(depth_length))
        
        # 复制数据
        depth_data = (ctypes.c_int16 * (depth_length.value // 2))()
        astra.astra_depthframe_copy_data(depth_frame, depth_data)
        
        # 获取尺寸 (假设640x480)
        width, height = 640, 480
        
        # 关闭帧
        astra_core.astra_reader_close_frame(frame)
        
        # 转换为numpy数组
        depth_array = np.ctypeslib.as_array(depth_data).reshape((height, width))
        return depth_array
    
    def terminate(self):
        if self.initialized:
            astra_core.astra_terminate()
            self.initialized = False

def main():
    print('='*60)
    print('Orbbec Astra Pro Depth + AI Detection')
    print('='*60)
    
    reader = AstraDepthReader()
    if not reader.initialize():
        return
    
    print('\nReading depth frames (press Ctrl+C to stop)...\n')
    
    try:
        for i in range(100):
            depth = reader.read_depth()
            if depth is not None:
                # 计算中心点深度
                center_depth = depth[240, 320]
                print(f'Frame {i}: shape={depth.shape}, center={center_depth}mm')
            else:
                print(f'Frame {i}: no data')
            time.sleep(0.033)
    except KeyboardInterrupt:
        print('\nStopping...')
    finally:
        reader.terminate()
        print('Done!')

if __name__ == '__main__':
    main()
