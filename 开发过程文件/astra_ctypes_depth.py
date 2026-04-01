#!/usr/bin/env python3
"""
Astra Pro 深度相机 - ctypes 调用 Astra SDK
直接使用 libastra.so 获取深度数据
"""

import ctypes
import os
import numpy as np
import cv2
import time

# Astra SDK 路径
ASTRA_SDK_PATH = '/home/sunrise/AstraSDK'
ASTRA_LIB_PATH = f'{ASTRA_SDK_PATH}/lib'

# 设置库路径 (必须在加载库之前)
os.environ['LD_LIBRARY_PATH'] = f"{ASTRA_LIB_PATH}:{os.environ.get('LD_LIBRARY_PATH', '')}"

# 使用 RTLD_GLOBAL 加载，确保符号对其他库可见
ctypes.CDLL(f'{ASTRA_LIB_PATH}/libastra_core.so', ctypes.RTLD_GLOBAL)
astra_core = ctypes.CDLL(f'{ASTRA_LIB_PATH}/libastra_core.so')
astra = ctypes.CDLL(f'{ASTRA_LIB_PATH}/libastra.so')

# 定义类型
astra_streamsetconnection_t = ctypes.c_void_p
astra_reader_t = ctypes.c_void_p
astra_depthstream_t = ctypes.c_void_p
astra_reader_frame_t = ctypes.c_void_p
astra_depthframe_t = ctypes.c_void_p
astra_frame_index_t = ctypes.c_int32


class AstraImageMetadata(ctypes.Structure):
    """astra_image_metadata_t"""
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("pixelFormat", ctypes.c_int32),  # astra_pixel_format_t
        ("reserved", ctypes.c_uint32)
    ]


class AstraDepthCamera:
    """Astra Pro 深度相机封装"""

    def __init__(self):
        self.sensor = astra_streamsetconnection_t()
        self.reader = astra_reader_t()
        self.depth_stream = astra_depthstream_t()
        self.initialized = False
        self.width = 640
        self.height = 480

    def initialize(self):
        """初始化 SDK 和相机"""
        print("[INFO] 初始化 Astra SDK...")

        # 初始化 SDK
        rc = astra_core.astra_initialize()
        if rc != 0:
            print(f"[ERROR] astra_initialize failed: {rc}")
            return False
        print("[INFO] Astra SDK 初始化成功")

        # 打开设备
        rc = astra_core.astra_streamset_open(b"device/default", ctypes.byref(self.sensor))
        if rc != 0:
            print(f"[ERROR] astra_streamset_open failed: {rc}")
            astra_core.astra_terminate()
            return False
        print(f"[INFO] 设备已打开: sensor={self.sensor.value}")

        # 创建 reader
        rc = astra_core.astra_reader_create(self.sensor, ctypes.byref(self.reader))
        if rc != 0:
            print(f"[ERROR] astra_reader_create failed: {rc}")
            astra_core.astra_streamset_close(self.sensor)
            astra_core.astra_terminate()
            return False
        print(f"[INFO] Reader 创建成功: reader={self.reader.value}")

        # 获取深度流
        rc = astra.astra_reader_get_depthstream(self.reader, ctypes.byref(self.depth_stream))
        if rc != 0:
            print(f"[ERROR] astra_reader_get_depthstream failed: {rc}")
            astra_core.astra_reader_destroy(ctypes.byref(self.reader))
            astra_core.astra_streamset_close(self.sensor)
            astra_core.astra_terminate()
            return False
        print(f"[INFO] 深度流获取成功: stream={self.depth_stream.value}")

        # 启动流
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

    def read_depth(self, timeout_ms=100):
        """
        读取一帧深度数据
        返回: (depth_data, width, height) 或 (None, 0, 0)
        depth_data 是 numpy 数组 (height, width), dtype=int16, 单位: mm
        """
        if not self.initialized:
            return None, 0, 0

        # 更新 SDK 状态
        astra_core.astra_update()

        # 获取帧
        frame = astra_reader_frame_t()
        rc = astra_core.astra_reader_open_frame(self.reader, timeout_ms, ctypes.byref(frame))

        if rc != 0:
            return None, 0, 0

        try:
            # 提取深度帧
            depth_frame = astra_depthframe_t()
            rc = astra.astra_frame_get_depthframe(frame, ctypes.byref(depth_frame))
            if rc != 0:
                print(f"[WARN] astra_frame_get_depthframe failed: {rc}")
                astra_core.astra_reader_close_frame(ctypes.byref(frame))
                return None, 0, 0

            # 获取数据长度
            depth_length = ctypes.c_uint32()
            astra.astra_depthframe_get_data_byte_length(depth_frame, ctypes.byref(depth_length))

            if depth_length.value == 0:
                astra_core.astra_reader_close_frame(ctypes.byref(frame))
                return None, 0, 0

            # 分配内存并复制数据
            num_pixels = depth_length.value // 2  # int16 = 2 bytes
            depth_buffer = (ctypes.c_int16 * num_pixels)()
            astra.astra_depthframe_copy_data(depth_frame, depth_buffer)

            # 获取元数据
            metadata = AstraImageMetadata()
            astra.astra_depthframe_get_metadata(depth_frame, ctypes.byref(metadata))

            self.width = metadata.width
            self.height = metadata.height

            # 转换为 numpy 数组
            depth_array = np.ctypeslib.as_array(depth_buffer).copy()
            depth_array = depth_array.reshape((self.height, self.width))

            return depth_array, self.width, self.height

        finally:
            # 关闭帧
            astra_core.astra_reader_close_frame(ctypes.byref(frame))

    def release(self):
        """释放资源"""
        if not self.initialized:
            return

        print("[INFO] 释放资源...")

        # 停止流
        astra_core.astra_stream_stop(self.depth_stream)

        # 销毁 reader
        astra_core.astra_reader_destroy(ctypes.byref(self.reader))

        # 关闭设备
        astra_core.astra_streamset_close(self.sensor)

        # 终止 SDK
        astra_core.astra_terminate()

        self.initialized = False
        print("[INFO] 资源已释放")


def colorize_depth(depth, min_dist=300, max_dist=5000):
    """深度图彩色化 (Jet colormap)"""
    if depth is None:
        return None

    # 归一化到 0-255
    depth_norm = np.clip((depth - min_dist) / (max_dist - min_dist) * 255, 0, 255).astype(np.uint8)

    # 应用 Jet colormap
    depth_color = cv2.applyColorMap(depth_norm, cv2.COLORMAP_JET)

    return depth_color


def main():
    """测试程序"""
    print("=" * 60)
    print("Astra Pro Depth Camera - ctypes version")
    print("=" * 60)

    camera = AstraDepthCamera()

    if not camera.initialize():
        print("[ERROR] 相机初始化失败")
        return

    print("\n[INFO] 按 'q' 退出，按 's' 保存截图\n")

    frame_count = 0
    start_time = time.time()
    fps = 0

    try:
        while True:
            # 读取深度
            depth, width, height = camera.read_depth()

            if depth is not None:
                frame_count += 1

                # 计算 FPS
                elapsed = time.time() - start_time
                if elapsed >= 1.0:
                    fps = frame_count / elapsed
                    frame_count = 0
                    start_time = time.time()

                # 获取中心点距离
                center_y, center_x = height // 2, width // 2
                center_dist = depth[center_y, center_x]

                # 彩色化
                depth_color = colorize_depth(depth, 300, 5000)

                # 显示信息
                cv2.putText(depth_color, f"FPS: {fps:.1f}", (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(depth_color, f"Dist: {center_dist}mm", (10, 60),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.putText(depth_color, f"Res: {width}x{height}", (10, 90),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

                # 显示
                cv2.imshow("Astra Pro Depth", depth_color)

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                elif key == ord('s'):
                    filename = f"depth_{time.strftime('%Y%m%d_%H%M%S')}.png"
                    cv2.imwrite(filename, depth_color)
                    print(f"[INFO] 已保存: {filename}")

    except KeyboardInterrupt:
        print("\n[INFO] 用户中断")

    finally:
        camera.release()
        cv2.destroyAllWindows()
        print("[INFO] 程序退出")


if __name__ == '__main__':
    main()
