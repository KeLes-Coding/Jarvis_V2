import subprocess
import multiprocessing
import time
import os

from jarvis.agent import agent_worker


def get_connected_devices() -> list[str]:
    """
    通过ADB识别当前连接的、状态为 'device' 的安卓设备。

    Returns:
        一个包含所有合格设备序列号的列表。
    """
    devices = []
    try:
        # 执行 adb devices 命令
        # text=True 使输出为字符串，capture_output=True 捕获标准输出和错误
        result = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, check=True
        )

        # 按行分割输出
        lines = result.stdout.strip().split("\n")

        # 从第二行开始解析 (第一行是 "List of devices attached")
        for line in lines[1:]:
            if "\tdevice" in line:
                # 分割行以获取设备序列号
                serial_number = line.split("\t")[0]
                devices.append(serial_number)

        return devices

    except FileNotFoundError:
        print("错误：'adb' 命令未找到。")
        print(
            "请确保您已安装 Android SDK Platform-Tools 并且 'adb' 在您的系统 PATH 中。"
        )
        return []
    except subprocess.CalledProcessError as e:
        print(f"执行 'adb devices' 时出错: {e}")
        print(f"错误输出:\n{e.stderr}")
        return []


# def agent_worker(device_serial: str):
#     """
#     模拟Agent工作的函数。每个Agent都是一个独立的进程。
#     它接收一个设备序列号并模拟对其进行处理。

#     Args:
#         device_serial: 分配给此Agent的设备序列号。
#     """
#     pid = os.getpid()
#     print(f"[Agent - PID: {pid}] 已启动，并分配到设备: {device_serial}")

#     # --- 在这里替换为您未来的真实Agent逻辑 ---
#     print(f"[Agent - PID: {pid}] 正在处理设备 {device_serial}...")
#     # 模拟工作耗时
#     time.sleep(5)
#     print(f"[Agent - PID: {pid}] 已完成对设备 {device_serial} 的工作。")
#     # --- 真实逻辑结束 ---


def main():
    """
    主函数，用于发现设备并分配给Agent。
    """
    print("正在检测已连接的安卓设备...")
    connected_devices = get_connected_devices()

    if not connected_devices:
        print("未检测到任何处于 'device' 状态的安卓设备。请检查您的连接和ADB授权。")
        return

    print(f"检测到 {len(connected_devices)} 台设备: {connected_devices}")
    print("-" * 30)

    processes = []

    # 为每台设备创建一个Agent进程
    for device in connected_devices:
        # 创建进程，目标是 agent_worker 函数，参数是设备序列号
        process = multiprocessing.Process(
            target=agent_worker,
            # args=(device, "打开计算器，计算123乘以456，告诉我答案是多少"),
            # args=(device, "打开维基百科，搜索周杰伦，告诉我他2000年发布的专辑是什么。"),
            args=(device, "滑动屏幕。"),
        )
        processes.append(process)
        process.start()  # 启动进程

    # 等待所有Agent进程完成
    print("所有Agent已启动，等待它们完成工作...")
    for process in processes:
        process.join()  # 阻塞主程序，直到该子进程结束

    print("-" * 30)
    print("所有Agent均已完成其任务。程序退出。")


if __name__ == "__main__":
    # 使用 if __name__ == "__main__": 是 multiprocessing 的最佳实践
    # 它可以防止在某些操作系统上（如Windows）出现子进程无限递归创建的问题
    main()
