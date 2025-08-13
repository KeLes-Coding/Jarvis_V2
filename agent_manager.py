# agent_manager.py (修改后)

import subprocess
import multiprocessing
import time
import os
import yaml
from abc import ABC, abstractmethod
import logging
from typing import List, Dict, Any

# 导入现有的 agent_worker
from jarvis.agent import agent_worker

# 设置一个基础的日志记录器，以便在加载完整配置前就能看到日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


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


class DeviceProvider(ABC):
    """
    设备提供者的抽象基类。
    每个子类负责通过一种特定的方式发现并提供安卓设备列表。
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.adb_path = config.get("adb", {}).get("executable_path", "adb")

    @abstractmethod
    def get_devices(self) -> List[str]:
        """
        发现并返回一个设备序列号列表。
        对于远程设备，序列号通常是 'ip:port' 的格式。
        """
        pass


class LocalDeviceProvider(DeviceProvider):
    """通过本地 'adb devices' 命令发现设备。"""

    def get_devices(self) -> List[str]:
        logging.info("正在从 [本地] 发现设备...")
        command = [self.adb_path, "devices"]
        output = run_adb_command(command)
        if not output:
            return []

        devices = []
        lines = output.strip().split("\n")
        for line in lines[1:]:
            if "\tdevice" in line:
                serial_number = line.split("\t")[0]
                devices.append(serial_number)
                logging.info(f"  [本地] 发现设备: {serial_number}")
        return devices


class RemoteIpDeviceProvider(DeviceProvider):
    """通过 'adb connect' 连接到公网/局域网IP的设备。"""

    def get_devices(self) -> List[str]:
        remote_hosts = self.config.get("remotes", [])
        if not remote_hosts:
            return []

        logging.info("正在从 [远程IP] 发现设备...")
        all_remote_devices = []
        for host_info in remote_hosts:
            host = host_info.get("host")
            if not host:
                continue

            logging.info(f"  正在连接到远程主机: {host}...")
            # 1. 连接设备
            connect_command = [self.adb_path, "connect", host]
            connect_output = run_adb_command(connect_command)
            if "connected" in connect_output or "already connected" in connect_output:
                logging.info(f"  成功连接到 {host}")
                # 连接成功后，该设备会出现在 `adb devices` 列表中，其序列号就是 host
                all_remote_devices.append(host)
            else:
                logging.error(f"  无法连接到 {host}。请检查网络和ADB配置。")

        return all_remote_devices


class SshReverseTunnelDeviceProvider(DeviceProvider):
    """
    处理通过SSH反向隧道连接的设备。

    此提供者假设您（用户）已经手动建立了从服务器2到服务器1的反向SSH隧道。
    例如，在服务器2上运行了类似这样的命令:
    ssh -R 5038:localhost:5037 -N -f user@server1_ip

    这条命令会将服务器1上的5038端口的流量转发到服务器2的本地ADB服务端口（默认为5037）。
    我们只需要在配置中告诉Agent，服务器1的哪个本地端口对应一个隧道设备即可。
    """

    def get_devices(self) -> List[str]:
        tunnels = self.config.get("ssh_reverse_tunnels", [])
        if not tunnels:
            return []

        logging.info("正在从 [SSH反向隧道] 发现设备...")
        connected_devices = []
        for tunnel in tunnels:
            local_port = tunnel.get("local_port")
            if not local_port:
                continue

            # 设备地址就是服务器1的localhost加上指定的本地端口
            device_address = f"localhost:{local_port}"
            logging.info(f"  正在尝试通过隧道连接设备: {device_address}")

            connect_command = [self.adb_path, "connect", device_address]
            connect_output = run_adb_command(connect_command)

            if "connected" in connect_output or "already connected" in connect_output:
                logging.info(f"  成功通过隧道连接到 {device_address}")
                connected_devices.append(device_address)
            else:
                logging.error(
                    f"  无法通过隧道 {device_address} 连接设备。请确认SSH隧道已建立并且端口正确。"
                )

        return connected_devices


def main():
    """
    主函数，用于加载配置、发现设备、分配任务并启动Agent。
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
        logging.warning(
            "任务列表为空，程序将不执行任何操作。请在 config.yaml 中定义任务。"
        )
        return

    # 2. 初始化设备提供者
    providers = []
    provider_configs = main_config.get("device_providers", {})
    if provider_configs.get("local", {}).get("enabled"):
        providers.append(LocalDeviceProvider(config))
    if provider_configs.get("remote_ip", {}).get("enabled"):
        providers.append(RemoteIpDeviceProvider(provider_configs.get("remote_ip")))
    if provider_configs.get("ssh_reverse_tunnel", {}).get("enabled"):
        providers.append(
            SshReverseTunnelDeviceProvider(provider_configs.get("ssh_reverse_tunnel"))
        )

    # 3. 汇总所有可用设备
    all_available_devices = []
    for provider in providers:
        all_available_devices.extend(provider.get_devices())

    if not all_available_devices:
        logging.error("未发现任何可用的安卓设备。请检查您的连接和配置。程序退出。")
        return

    # 去重
    all_available_devices = sorted(list(set(all_available_devices)))

    logging.info("-" * 30)
    logging.info(f"任务调度开始！")
    logging.info(
        f"发现 {len(all_available_devices)} 台可用设备: {all_available_devices}"
    )
    logging.info(f"共有 {len(tasks)} 个任务待执行。")
    logging.info("-" * 30)

    # 4. 创建工作队列 (设备, 任务)
    # 简单轮询调度：将任务依次分配给设备
    work_queue = []
    for i, task in enumerate(tasks):
        device = all_available_devices[i % len(all_available_devices)]
        work_queue.append((device, task))
        logging.info(f"任务 '{task[:30]}...' 已分配给设备 [{device}]")

    # 5. 并行启动 Agent
    processes = []
    for device, task in work_queue:
        process = multiprocessing.Process(
            target=agent_worker,
            args=(device, task),
        )
        processes.append(process)
        process.start()
        # 稍微错开启动时间，避免同时初始化造成日志混乱
        time.sleep(2)

    # 6. 等待所有 Agent 进程完成
    logging.info("所有Agent已启动，等待它们完成工作...")
    for process in processes:
        process.join()

    logging.info("-" * 30)
    logging.info("所有Agent均已完成其任务。程序退出。")


if __name__ == "__main__":
    # 在Windows和macOS上，multiprocessing的默认启动方法可能不同
    # 'fork' 是Linux上的默认值，通常更高效
    # 'spawn' 在所有平台上都可用，更稳定但开销稍大
    if os.name != "posix":
        multiprocessing.set_start_method("spawn", force=True)
    main()
