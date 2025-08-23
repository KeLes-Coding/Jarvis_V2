# agent_manager.py (Refactored V3 - Restored Comments + V4 SSH Forward)

import subprocess
import multiprocessing
import time
import os
import yaml
import logging
import platform
import sys

import re
import atexit
from typing import List, Dict, Any

# 导入现有的 agent_worker
from jarvis.agent import agent_worker

ssh_tunnel_processes = []

# --- 全局基础日志配置 ---
# 为管理器设置一个独特的日志格式，以便与Agent的日志区分开
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [Manager] - %(levelname)s - %(message)s",
    force=True,  # 强制覆盖任何现有配置
)


# --- 新增：程序退出时自动调用的清理函数 ---
def cleanup_ssh_tunnels():
    """
    程序退出时自动调用的清理函数，用于终止所有后台SSH隧道进程。
    """
    logging.info("正在清理后台SSH隧道进程...")
    for process in ssh_tunnel_processes:
        if process.poll() is None:  # 进程仍在运行
            try:
                process.terminate()
                process.wait(timeout=5)
                logging.info(f"已终止SSH隧道进程 (PID: {process.pid})")
            except subprocess.TimeoutExpired:
                process.kill()
                logging.warning(
                    f"强制终止SSH隧道进程 (PID: {process.pid})，因为它没有在5秒内响应"
                )
            except Exception as e:
                logging.error(f"清理SSH隧道进程 (PID: {process.pid}) 时出错: {e}")
    logging.info("SSH隧道清理完毕。")


# --- 新增：注册清理函数 ---
atexit.register(cleanup_ssh_tunnels)


def run_adb_command(command: list[str], timeout: int = 20) -> str:
    """一个通用的ADB命令执行函数"""
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=True, timeout=timeout
        )
        return result.stdout.strip()
    except FileNotFoundError:
        logging.error("错误: 'adb' 命令未找到。请确保它在您的系统 PATH 中。")
        return ""
    except subprocess.CalledProcessError as e:
        logging.error(f"执行 '{' '.join(command)}' 时出错: {e}\n错误输出:\n{e.stderr}")
        return ""
    except subprocess.TimeoutExpired:
        logging.error(f"命令 '{' '.join(command)}' 超时。")
        return ""


def get_available_devices(config: Dict[str, Any]) -> List[str]:
    """
    发现所有来源（本地、远程、隧道）的可用设备并返回唯一的设备序列号列表。
    """
    adb_path = config.get("adb", {}).get("executable_path", "adb")
    all_devices = []
    provider_configs = config.get("main", {}).get("device_providers", {})

    # 1. 本地设备
    if provider_configs.get("local", {}).get("enabled"):
        logging.info("正在从 [本地] 发现设备...")
        output = run_adb_command([adb_path, "devices"])
        if output:
            lines = output.strip().split("\n")
            for line in lines[1:]:
                if "\tdevice" in line:
                    all_devices.append(line.split("\t")[0])

    # 2. 远程IP设备
    remote_ip_config = provider_configs.get("remote_ip", {})
    if remote_ip_config.get("enabled"):
        for remote in remote_ip_config.get("remotes", []):
            host = remote.get("host")
            if host:
                logging.info(f"正在连接到远程主机: {host}...")
                connect_output = run_adb_command([adb_path, "connect", host])
                if (
                    "connected" in connect_output
                    or "already connected" in connect_output
                ):
                    all_devices.append(host)

    # 3. SSH反向隧道设备
    ssh_tunnel_config = provider_configs.get("ssh_reverse_tunnel", {})
    if ssh_tunnel_config.get("enabled"):
        for tunnel in ssh_tunnel_config.get("ssh_reverse_tunnels", []):
            port = tunnel.get("local_port")
            if port:
                address = f"localhost:{port}"
                logging.info(f"正在尝试通过隧道连接设备: {address}")
                connect_output = run_adb_command([adb_path, "connect", address])
                if (
                    "connected" in connect_output
                    or "already connected" in connect_output
                ):
                    all_devices.append(address)

    # 4.SSH正向隧道设备
    ssh_forward_config = provider_configs.get("ssh_forward_tunnel", {})
    if ssh_forward_config.get("enabled"):
        for conn in ssh_forward_config.get("ssh_connections", []):
            user, host, port = conn["ssh_user"], conn["ssh_host"], conn["ssh_port"]
            remote_adb = conn["remote_adb_path"]
            local_port_counter = conn.get("local_start_port", 15555)

            logging.info(f"正在通过SSH [{user}@{host}:{port}] 发现远程设备...")

            ssh_cmd = [
                "ssh",
                f"{user}@{host}",
                "-p",
                str(port),
                f"{remote_adb} devices",
            ]
            try:
                remote_output = subprocess.check_output(ssh_cmd, text=True, timeout=30)
            except Exception as e:
                logging.error(f"通过SSH执行远程ADB命令失败: {e}")
                continue

            remote_devices = []
            for line in remote_output.strip().split("\n")[1:]:
                if "\tdevice" in line:
                    serial = line.split("\t")[0]
                    match = re.match(r"emulator-(\d+)", serial)
                    if match:
                        remote_port = int(match.group(1)) + 1
                        remote_devices.append((serial, remote_port))
                    elif ":" in serial:
                        try:
                            remote_port = int(serial.split(":")[-1])
                            remote_devices.append((serial, remote_port))
                        except ValueError:
                            logging.warning(f"无法从远程设备 '{serial}' 解析端口。")

            if not remote_devices:
                logging.warning(f"在远程服务器 [{host}] 上未发现可用的安卓虚拟机。")
                continue

            for serial, remote_port in remote_devices:
                local_port = local_port_counter
                logging.info(f"为远程设备 '{serial}' (端口:{remote_port}) 建立隧道...")

                tunnel_cmd = [
                    "ssh",
                    "-N",
                    "-f",
                    "-L",
                    f"{local_port}:localhost:{remote_port}",
                    f"{user}@{host}",
                    "-p",
                    str(port),
                ]

                try:
                    # 使用 Popen 在后台启动，并将其添加到全局列表以便后续清理
                    process = subprocess.Popen(tunnel_cmd)
                    ssh_tunnel_processes.append(process)
                    logging.info(
                        f"已启动SSH隧道 (PID: {process.pid}): 本地端口 {local_port} -> 远程端口 {remote_port}"
                    )
                    time.sleep(2)
                except Exception as e:
                    logging.error(f"启动SSH隧道失败: {e}")
                    continue

                local_address = f"localhost:{local_port}"
                connect_output = run_adb_command([adb_path, "connect", local_address])
                if (
                    "connected" in connect_output
                    or "already connected" in connect_output
                ):
                    logging.info(
                        f"成功通过隧道连接到设备: {local_address} (远程: {serial})"
                    )
                    all_devices.append(local_address)
                else:
                    logging.error(
                        f"连接到 {local_address} 失败。请检查隧道或远程ADB服务。"
                    )
                    process.terminate()

                local_port_counter += 1
    # --- 新增逻辑结束 ---

    unique_devices = sorted(list(set(all_devices)))
    logging.info(f"发现 {len(unique_devices)} 台唯一可用设备: {unique_devices}")
    return unique_devices


def agent_process_wrapper(
    device_serial: str, task: str, device_status_dict: Dict[str, str]
):
    """
    这是 Agent 工作进程的包装器。
    它的核心职责是：在调用真正的 agent_worker 前后，正确地更新共享的设备状态。
    """
    try:
        # 1. 在任务开始前，立刻将设备状态标记为 'busy'
        device_status_dict[device_serial] = "busy"
        logging.info(f"设备 [{device_serial}] 已锁定，开始执行任务: '{task[:50]}...'")

        # 2. 调用真正的 Agent 工作函数
        # 注意：agent_worker内部已经有完整的日志和异常处理
        agent_worker(device_serial, task)

    except Exception as e:
        # 这是一个兜底的异常捕获，以防 agent_worker 本身在初始化阶段就崩溃
        logging.error(
            f"设备 [{device_serial}] 的 Agent 包装器捕获到致命错误: {e}", exc_info=True
        )
    finally:
        # 3. 无论任务成功、失败还是崩溃，最后都必须将设备状态改回 'idle'
        device_status_dict[device_serial] = "idle"
        logging.info(f"设备 [{device_serial}] 已释放，任务 '{task[:50]}...' 结束。")


def main():
    """
    主函数，采用基于共享状态的调度策略来管理设备和任务。
    """
    # 1. 加载配置
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        logging.error(
            "错误: config.yaml 未找到！请从 config.template.yaml 复制并修改。"
        )
        return

    main_config = config.get("main", {})
    tasks = main_config.get("tasks", [])

    if not tasks:
        logging.warning("任务列表为空，程序将不执行任何操作。")
        return

    all_devices = get_available_devices(config)
    if not all_devices:
        logging.error("未发现任何可用的安卓设备，程序退出。")
        return

    logging.info("-" * 40)
    logging.info("任务调度器 V3 已启动 (基于状态)")
    logging.info(f"共有 {len(tasks)} 个任务待执行。")
    logging.info("-" * 40)

    # --- 核心改动：使用 Manager 来创建多进程共享的数据结构 ---
    manager = multiprocessing.Manager()

    # a. 共享的任务队列
    task_queue = manager.Queue()
    for task in tasks:
        task_queue.put(task)

    # b. 共享的设备状态字典，初始状态均为 'idle' (空闲)
    device_status = manager.dict({device: "idle" for device in all_devices})

    active_processes = {}

    try:
        while not task_queue.empty() or any(
            p.is_alive() for p in active_processes.values()
        ):
            # --- 步骤 1: 清理已结束的僵尸进程 ---
            finished_devices = [
                device
                for device, process in active_processes.items()
                if not process.is_alive()
            ]
            for device in finished_devices:
                active_processes[device].join()  # 确保进程资源被回收
                del active_processes[device]

            # --- 步骤 2: 寻找空闲设备并分配新任务 ---
            if not task_queue.empty():
                for device_serial in all_devices:
                    # 如果设备状态为空闲，并且没有正在运行的进程，则分配任务
                    if (
                        device_status.get(device_serial) == "idle"
                        and device_serial not in active_processes
                    ):
                        if task_queue.empty():
                            break  # 如果在遍历设备时任务队列变空了，则跳出

                        task_to_run = task_queue.get()

                        logging.info(
                            f"调度新任务: '{task_to_run[:50]}...' -> 分配给空闲设备 [{device_serial}]"
                        )

                        process = multiprocessing.Process(
                            target=agent_process_wrapper,
                            args=(device_serial, task_to_run, device_status),
                        )
                        process.start()
                        active_processes[device_serial] = process

            # 短暂休眠，避免CPU空转
            time.sleep(2)

    except KeyboardInterrupt:
        logging.info("捕获到用户中断信号 (Ctrl+C)，将开始清理...")

    finally:
        # atexit 会在这里自动处理SSH隧道的清理
        logging.info("-" * 40)
        logging.info("所有任务均已执行完毕或程序已中断。调度器正在退出。")


if __name__ == "__main__":
    # 在非Linux系统上，'spawn' 启动方法更稳定
    if platform.system() != "Linux":
        multiprocessing.set_start_method("spawn", force=True)
    main()
