# Jarvis - LLM 驱动的安卓设备操控Agent

Jarvis 是一个由大型语言模型（LLM）驱动的 AI Agent，旨在通过模仿人类用户的交互方式来操作安卓设备，以完成指定的高级任务。

## 功能特性

  * **多模态感知**: 结合屏幕截图和 UI 布局（XML）来全面理解当前设备状态。
  * **LLM 驱动的决策**: 利用大型语言模型（支持 OpenAI, Gemini, Claude）进行“思考”，根据观察到的信息决定下一步操作。
  * **人类行为模拟**: 执行如点击、滑动、输入文本、返回、返回主页等一系列原子操作来与设备交互。
  * **可扩展的 LLM 支持**: 轻松在不同的 LLM 提供商之间切换，并支持通过Agent连接。
  * **详细的执行记录**: 自动为每次任务运行创建独立的文件夹，详细记录每一步的截图、UI 布局、LLM 思考过程和最终行动，便于分析和调试。
  * **并行设备管理**: 能够同时检测多个连接的安卓设备，并为每台设备启动一个独立的Agent进程来执行任务。

## 工作流程

Jarvis V2 的核心是一个“观察-思考-行动”的循环：

1.  **观察 (Observe)**: `Observer` 模块获取当前安卓设备的屏幕截图和 UI 层次结构（XML 文件）。
2.  **思考 (Think)**: `JarvisAgent` 将观察到的信息（截图和简化后的 UI 元素列表）连同任务目标一起发送给 `LLMClient`。LLM 根据这些信息，按照预设的指令（`prompts.py`），以 JSON 格式返回它的思考过程和下一步要执行的具体动作。
3.  **行动 (Act)**: `Actuator` 模块接收来自 LLM 的动作指令，并将其解析为具体的 ADB (Android Debug Bridge) 命令在设备上执行。
4.  **记录 (Record)**: `InfoPoolManager` 会记录下循环中的每一步，包括观察数据、LLM 的响应和行动结果，并保存在本次任务的专属文件夹中。

这个循环会持续进行，直到任务完成或达到预设的最大步骤数。

## 安装指南

1.  **克隆代码库**:

    ```bash
    git clone https://github.com/KeLes-Coding/Jarvis_V2.git
    cd Jarvis_V2
    ```

2.  **安装依赖**:
    ```bash
    pip install -r requirements.txt
    ```

    根据 `config.template.yaml` 和代码中的动态导入，您可能还需要安装：

    ```bash
    
3.  **安卓调试桥 (ADB)**:
    确保您已经安装了 Android SDK Platform-Tools，并且 `adb` 命令在您的系统路径 (PATH) 中。您可以通过运行 `adb devices` 来验证。

## 配置

在运行项目之前，您需要配置您的个人设置：

1.  **创建配置文件**:
    复制 `config.template.yaml` 并将其重命名为 `config.yaml`。

    ```bash
    cp config.template.yaml config.yaml
    ```

2.  **编辑 `config.yaml`**:
    打开 `config.yaml` 文件并填入以下信息：

      * `adb.executable_path`: 如果 `adb` 不在您的系统 PATH 中，请在此处指定其完整路径。
      * `proxy`: 如果您需要通过代理访问 LLM 服务，请启用并设置代理服务器地址。
      * `llm.api_mode`: 选择您要使用的 LLM 提供商 (`openai`, `gemini`, 或 `claude`)。
      * `llm.providers`: 在您选择的提供商下，填入您的 `api_key` 和要使用的 `model` 名称。

    **注意**: `config.yaml` 已被添加到 `.gitignore` 中，以防止您的敏感信息（如 API Key）被意外提交。

## 如何运行

1.  **连接安卓设备**:
    使用 USB 数据线将您的安卓设备连接到电脑，并确保已开启“开发者选项”中的“USB 调试”功能，并已授权您的电脑进行调试。

2.  **定义任务**:
    打开 `agent_manager.py` 文件，在 `main` 函数中，您可以修改传递给 `agent_worker` 的任务描述字符串。

    ```python
    # agent_manager.py

    ...
    # 在这里修改你的任务
    process = multiprocessing.Process(
        target=agent_worker,
        args=(device, "打开维基百科，搜索周杰伦，告诉我他2000年发布的专辑是什么。"),
    )
    ...
    ```

3.  **启动代理**:
    运行 `agent_manager.py`。程序会自动检测所有连接的设备，并为每台设备分配一个代理来执行任务。

    ```bash
    python agent_manager.py
    ```

4.  **查看结果**:
    每次运行的产出，包括日志、截图和详细步骤，都会保存在 `jarvis/runs/` 目录下的一个以时间戳和任务名命名的文件夹中。

## 项目结构

```
.
├── agent_manager.py            # 主入口，管理和启动Agent进程
├── config.template.yaml        # 配置文件模板
├── requirements.txt            # Python依赖
├── jarvis/
│   ├── agent.py                # 核心Agent类，负责编排整个工作流
│   ├── info_pool.py            # 信息池管理器，负责记录和保存运行轨迹
│   ├── logger_setup.py         # 日志系统初始化
│   ├── __init__.py
│   ├── llm/
│   │   ├── client.py           # LLM客户端，支持多家服务并处理代理
│   │   ├── prompts.py          # 存放引导LLM思考的系统提示
│   │   └── __init__.py
│   ├── modules/
│   │   ├── observer.py         # 观察者模块，负责获取设备屏幕和UI信息
│   │   ├── actuator.py         # 执行器模块，负责在设备上执行操作
│   │   └── __init__.py
│   └── runs/                   # (自动创建) 存放所有任务的运行产出
└── ...
```