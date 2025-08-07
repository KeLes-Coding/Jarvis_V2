# jarvis/modules/observer.py (最终版，包含坐标和可点击属性)

import subprocess
import logging
import re
import xml.etree.ElementTree as ET
import os
import time
from typing import List, Dict, Any, Tuple


class Observer:
    def __init__(self, adb_path: str, device_serial: str):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.adb_path = adb_path
        self.device_serial = device_serial
        self.local_temp_path = f"temp_{self.device_serial}_{int(time.time() * 1000)}"

    def _execute_adb_command(self, command: list[str], timeout: int = 20) -> bool:
        # ... 此方法无需修改 ...
        base_cmd = [self.adb_path, "-s", self.device_serial]
        full_command = base_cmd + command
        self.logger.debug(f"执行ADB命令: {' '.join(full_command)}")
        try:
            subprocess.run(
                full_command,
                check=True,
                timeout=timeout,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            return True
        except subprocess.TimeoutExpired:
            self.logger.error(f"ADB命令超时: {' '.join(full_command)}")
            return False
        except subprocess.CalledProcessError as e:
            self.logger.error(
                f"ADB命令执行失败: {' '.join(full_command)}\nStderr: {e.stderr.strip()}"
            )
            return False
        except Exception as e:
            self.logger.error(f"执行ADB命令时发生未知错误: {e}")
            return False

    def get_screenshot_bytes(self) -> bytes | None:
        # ... 此方法无需修改 ...
        remote_path = "/data/local/tmp/screenshot.png"
        local_path = f"{self.local_temp_path}_screen.png"
        try:
            if not self._execute_adb_command(["shell", "screencap", "-p", remote_path]):
                return None
            if not self._execute_adb_command(["pull", remote_path, local_path]):
                return None
            with open(local_path, "rb") as f:
                return f.read()
        finally:
            self._execute_adb_command(["shell", "rm", remote_path])
            if os.path.exists(local_path):
                os.remove(local_path)

    def get_layout_xml(self) -> str | None:
        # ... 此方法无需修改 ...
        remote_path = "/data/local/tmp/uidump.xml"
        local_path = f"{self.local_temp_path}_uidump.xml"
        try:
            if not self._execute_adb_command(
                ["shell", "uiautomator", "dump", remote_path]
            ):
                return None
            if not self._execute_adb_command(["pull", remote_path, local_path]):
                return None
            with open(local_path, "r", encoding="utf-8") as f:
                return f.read()
        finally:
            self._execute_adb_command(["shell", "rm", remote_path])
            if os.path.exists(local_path):
                os.remove(local_path)

    def _parse_bounds(self, bounds_str: str) -> Tuple[int, int, int, int]:
        # ... 此方法无需修改 ...
        coords = [int(n) for n in re.findall(r"\d+", bounds_str)]
        if len(coords) == 4:
            return coords[0], coords[1], coords[2], coords[3]
        return 0, 0, 0, 0

    def _is_element_actionable(self, node: ET.Element) -> bool:
        # ... 此方法无需修改 ...
        is_interactive = (
            node.get("clickable") == "true"
            or node.get("long-clickable") == "true"
            or node.get("focusable") == "true"
        )
        has_text = node.get("text", "") != "" or node.get("content-desc", "") != ""
        is_visible = node.get("displayed") != "false"
        if not is_visible or node.get("enabled") != "true":
            return False
        return is_interactive or has_text

    def _parse_and_simplify_xml(self, xml_content: str) -> List[Dict[str, Any]]:
        # --- 此方法无需修改，它已经提取了我们需要的所有信息 ---
        simplified_elements = []
        if not xml_content:
            return simplified_elements
        try:
            root = ET.fromstring(xml_content)
            uid_counter = 1
            for node in root.iter():
                if self._is_element_actionable(node):
                    bounds_str = node.get("bounds")
                    bounds = self._parse_bounds(bounds_str)
                    element_data = {
                        "uid": uid_counter,
                        "class": node.get("class"),
                        "text": node.get("text", ""),
                        "content_desc": node.get("content-desc", ""),
                        "resource_id": node.get("resource-id", ""),
                        "bounds": bounds,
                        "center": (
                            (bounds[0] + bounds[2]) // 2,
                            (bounds[1] + bounds[3]) // 2,
                        ),
                        "clickable": node.get("clickable") == "true",
                        "password": node.get("password") == "true",
                        "checkable": node.get("checkable") == "true",
                        "checked": node.get("checked") == "true",
                        "selected": node.get("selected") == "true",
                    }
                    simplified_elements.append(element_data)
                    uid_counter += 1
        except ET.ParseError as e:
            self.logger.error(
                f"XML解析失败: {e}\n--- XML Content ---\n{xml_content[:500]}..."
            )
        return simplified_elements

    # --- 唯一的修改点：get_current_observation ---
    def get_current_observation(self) -> dict:
        """获取并格式化观察数据，格式化字符串时【新增】坐标和可点击属性。"""
        self.logger.info("正在获取当前设备观察数据...")
        screenshot = self.get_screenshot_bytes()
        xml = self.get_layout_xml()

        simplified_elements = self._parse_and_simplify_xml(xml)

        simplified_elements_str = ""
        for el in simplified_elements:
            all_parts = []

            # 1. 身份信息
            text_info = f"text='{el['text']}'" if el["text"] else ""
            desc_info = f"desc='{el['content_desc']}'" if el["content_desc"] else ""
            id_info = f"id='{el['resource_id']}'" if el["resource_id"] else ""
            all_parts.extend([part for part in [text_info, desc_info, id_info] if part])

            # 2. 状态信息
            if el.get("password"):
                all_parts.append("is_password")
            if el.get("checkable"):
                all_parts.append("checkable")
                all_parts.append("checked" if el.get("checked") else "unchecked")
            if el.get("selected"):
                all_parts.append("selected")

            # 3. --- 新增：行为和空间信息 ---
            if el.get("clickable"):
                all_parts.append("clickable")

            b = el.get("bounds")
            if b:
                # 格式化bounds使其更易读
                all_parts.append(f"bounds=[{b[0]},{b[1]}][{b[2]},{b[3]}]")

            # 最终拼接
            simplified_elements_str += f"[{el['uid']}] {el['class'].split('.')[-1]} {{{', '.join(all_parts)}}}\n"

        return {
            "screenshot_bytes": screenshot,
            "xml_content": xml,
            "simplified_elements_list": simplified_elements,
            "simplified_elements_str": simplified_elements_str,
        }
