#!/usr/bin/env python3
"""
Astra Pro 深度相机 - OpenNI2 版本
使用 openni Python 模块读取深度数据
"""

import sys
import os

# 设置路径
os.environ['OPENNI2_REDIST'] = '/usr/lib/aarch64-linux-gnu'
sys.path.insert(0, '/home/sunrise/.local/lib/python3.10/site-packages')

import numpy as np
import cv2
import time
from openni import openni2
from openni import _openni2 as c_api


def initialize_camera():
    """初始化 OpenNI2 相机"""
    print("[INFO] 初始化 OpenNI2...")

    try:
        openni2.initialize()
        print("[INFO] OpenNI2 初始化成功")
    except Exception as e:
        print(f"[ERROR] OpenNI2 初始化失败: {e}")
        return None, None

    try:
        dev = openni2.Device.open_any()
        print(f"[INFO] 设备已打开: {dev.get_device_info().name}")
    except Exception as e:
        print(f"[ERROR] 无法打开设备: {e}")
        openni2.unload()
        return None, None

    # 创建深度流
    try:
        depth_stream = dev.create_depth_stream()
        depth_stream.set_video_mode(
            c_api.OniVideoMode(
                pixelFormat=c_api.OniPixelFormat.ONI_PIXEL_FORMAT_DEPTH_1_MM,
                resolutionX=640,
                resolutionY=480,
                fps=30
            )
        )
        depth_stream.start()
        print("[INFO] 深度流已启动: 640x480@30fps")
    except Exception as e:
        print(f"[ERROR] 深度流启动失败: {e}")
        openni2.unload()
        return None, None

    # 创建彩色流
    try:
        color_stream = dev.create_color_stream()
        color_stream.set_video_mode(
            c_api.OniVideoMode(
                pixelFormat=c_api.OniPixelFormat.ONI_PIXEL_FORMAT_RGB888,
                resolutionX=640,
                resolutionY=480,
                fps=30
            )
        )
        color_stream.start()
        print("[INFO] 彩色流已启动: 640x480@30fps")
    except Exception as e:
        print(f"[WARN] 彩色流启动失败: {e}")
        color_stream = None

    return depth_stream, color_stream


def read_frames(depth_stream, color_stream):
    """读取帧数据"""
    depth_frame = None
    color_frame = None

    if depth_stream:
        try:
            frame = depth_stream.read_frame()
            depth_data = np.frombuffer(frame.get_buffer_as_uint16(), dtype=np.uint16)
            depth_frame = depth_data.reshape((480, 640))
        except Exception as e:
            print(f"[WARN] 深度读取失败: {e}")

    if color_stream:
        try:
            frame = color_stream.read_frame()
            color_data = np.frombuffer(frame.get_buffer_as_uint8(), dtype=np.uint8)
            color_frame = color_data.reshape((480, 640, 3))
            # RGB to BGR
            color_frame = cv2.cvtColor(color_frame, cv2.COLOR_RGB2BGR)
        except Exception as e:
            print(f"[WARN] 彩色读取失败: {e}")

    return depth_frame, color_frame


def colorize_depth(depth, min_dist=300, max_dist=5000):
    """深度图彩色化"""
    if depth is None:
        return None

    depth_clipped = np.clip(depth, min_dist, max_dist)
    depth_norm = ((depth_clipped - min_dist) / (max_dist - min_dist) * 255).astype(np.uint8)
    depth_color = cv2.applyColorMap(depth_norm, cv2.COLORMAP_JET)

    return depth_color


def create_overlay(color_frame, depth_frame, alpha=0.4):
    """创建叠加图像"""
    if color_frame is None:
        color_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    if depth_frame is None:
        return color_frame

    # 深度彩色化
    depth_color = colorize_depth(depth_frame)

    # 调整大小匹配
    if depth_color.shape[:2] != color_frame.shape[:2]:
        depth_color = cv2.resize(depth_color, (color_frame.shape[1], color_frame.shape[0]))

    # 叠加
    overlay = cv2.addWeighted(color_frame, 1 - alpha, depth_color, alpha, 0)

    return overlay


def get_grid_distances(depth, cols=5, rows=5):
    """获取网格中心点距离"""
    if depth is None:
        return [0.5 + (i % 5) * 0.3 for i in range(25)]

    h, w = depth.shape
    distances = []
    for row in range(rows):
        for col in range(cols):
            cy = int((row + 0.5) * h / rows)
            cx = int((col + 0.5) * w / cols)
            dist_m = min(depth[cy, cx] / 1000.0, 10.0)
            distances.append(dist_m)
    return distances


def main():
    """主函数"""
    print("=" * 60)
    print("Astra Pro Depth Camera - OpenNI2 Version")
    print("=" * 60)

    depth_stream, color_stream = initialize_camera()

    if depth_stream is None:
        print("[ERROR] 相机初始化失败")
        return

    print("\n[INFO] 按 'q' 退出，按 's' 保存截图\n")

    frame_count = 0
    start_time = time.time()
    fps = 0

    try:
        while True:
            depth_frame, color_frame = read_frames(depth_stream, color_stream)

            if depth_frame is not None:
                frame_count += 1

                # 计算 FPS
                elapsed = time.time() - start_time
                if elapsed >= 1.0:
                    fps = frame_count / elapsed
                    frame_count = 0
                    start_time = time.time()

                # 创建叠加图像
                overlay = create_overlay(color_frame, depth_frame, alpha=0.4)

                # 获取中心点距离
                center_y, center_x = depth_frame.shape[0] // 2, depth_frame.shape[1] // 2
                center_dist = depth_frame[center_y, center_x]

                # 显示信息
                cv2.putText(overlay, f"FPS: {fps:.1f}", (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(overlay, f"Dist: {center_dist/1000:.2f}m", (10, 60),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                # 显示
                cv2.imshow("Astra Pro Depth Overlay", overlay)

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                elif key == ord('s'):
                    filename = f"depth_{time.strftime('%Y%m%d_%H%M%S')}.png"
                    cv2.imwrite(filename, overlay)
                    print(f"[INFO] 已保存: {filename}")

    except KeyboardInterrupt:
        print("\n[INFO] 用户中断")

    finally:
        print("[INFO] 清理资源...")
        if depth_stream:
            depth_stream.stop()
        if color_stream:
            color_stream.stop()
        try:
            openni2.unload()
        except:
            pass
        cv2.destroyAllWindows()
        print("[INFO] 程序退出")


if __name__ == '__main__':
    main()
