# MOSS 语音工作台快速开始

## 这是什么

MOSS 语音工作台是在本机运行的语音生成与音频处理工具。
模型推理在本机完成，不需要云端推理服务。
首次使用时，先准备 Python 依赖，再从「设置 → 环境准备」获取模型和组件。
安装包自带工作台、便携 Python、内置参考音色及必要运行文件；模型和运行环境按需下载。
技术栈：Electron 桌面客户端 + Python 本地服务 + MOSS 语音模型。

## 能做什么

- 单人配音：使用内置音色生成语音，也可用参考音频克隆音色。
- 音色设计：用文字描述希望生成的音色，无需参考音频。
- 多人对话：为不同说话人指定参考音频与台词，合成对话。
- 音效生成：根据文字提示生成音效。
- 音频拆分：分离人声、鼓组、贝斯、钢琴、吉他及其他伴奏；也可单独提取人声与伴奏。
- 降噪：去除背景噪声、嘶声与电流声，净化音频。
- 语音识别：使用本地 whisper-small 将音频转成文字（需下载可选模型）。

## 快速上手

1. **安装**：安装并启动 MOSS 语音工作台。
2. **环境准备**：首次启动按提示进入「环境准备」，使用随包 Python 创建运行环境并安装依赖，约 **3.4 GB**。PyTorch 约 **2.7 GB**，实测下载约 **15 分钟**；实际时间随网络而异。软件源默认自动切换：清华 → 阿里云 → 官方 PyPI；PyTorch 使用 `--extra-index-url https://download.pytorch.org/whl/cu130`。
3. **下载模型**：在「设置 → 环境准备」下载必需模型（约 **61.8 GB**）和 FFmpeg（约 **83 MB**）。Demucs、whisper-small、MossFormer2_SE 等为可选资源，可按需下载。
4. **开始使用**：回到工作台，选择配音、音色设计、多人对话或音效生成；音频拆分、降噪等在「工具」页打开。TTS 等语音结果直接写入 `outputs/<场景>/`；只有 Stems、Denoise 使用任务子目录：`outputs/Stems/<job_id>/`、`outputs/Denoise/<job_id>/`。上传音频位于 `uploads/`。

### 从源码运行

要求 Windows x64 与 64 位 Python 3.12。在源码 checkout 根目录执行 `python tools/downloader_ui.py`（不带参数）打开独立环境准备/下载界面；用 Python 3.12 创建 `runtime/venv`，安装 `runtime/requirements.txt` 并使用 PyTorch 源 `--extra-index-url https://download.pytorch.org/whl/cu130`，然后运行 `start_server.bat` 或用 venv Python 启动 `server/run.py`。开发根目录是源码 checkout（Windows 默认 `D:\MossTTSD`）；安装态工作台根目录为 `<install>/resources/workbench`，随安装位置变化。

## 常见问题

- **下载卡在 0% 或速度很慢怎么办？** 检查网络是否可访问下载源，并预留足够磁盘空间；大型模型下载时间取决于网络和文件大小。依赖安装与模型下载是两个独立步骤。
- **提示缺少环境，或出现退出码 3/4？** 退出码 **3** 表示预期的 `runtime/venv` 解释器不存在；退出码 **4** 表示后端由其它解释器路径启动，或 venv 的 `torch`/`torchaudio` 预检失败。应由路径完全匹配的 venv Python 启动后端；依赖不全时重新执行环境准备。`MOSS_TTS_PYTHON` 仅供环境准备阶段发现基础解释器，不会覆盖后端解释器。
- **下载中断后要从头开始吗？** 不必。下载器保留临时分片，再次启动该下载会尝试断点续传。
- **一定要有显卡吗？** 不一定；没有 NVIDIA 显卡时可以使用 CPU。需要 GPU 加速时，系统需具备 CUDA 13 驱动。
- **能完全离线使用吗？** 推理在本机进行；但首次准备环境和下载所需模型、组件时需要联网。下载齐全后可离线推理。
- **模型放在哪里？** 模型位于工作台根目录下的 `models/`；运行环境在 `runtime/venv/`，FFmpeg 在 `runtime/ffmpeg/`。
- **如何卸载或迁移？** 关闭工作台后可卸载应用。若要迁移已有下载内容，请将整个工作台根目录一并备份或移动；保留 `models/`、`runtime/` 与 `assets/`，并在新位置启动工作台。请先确认目标磁盘空间充足。

## 环境变量与目录速查

| 名称 | 用途 |
|---|---|
| `MOSS_WORKBENCH_ROOT` | 指定工作台根目录；默认使用安装目录中的工作台位置。 |
| `MOSS_TTS_PYTHON` | 仅供环境准备模块发现基础 Python；后端始终要求路径完全匹配的 `runtime/venv` 解释器。 |
| `MOSS_DOWNLOAD_ROOT` | 仅供测试覆盖下载根目录；正常使用不要设置。 |

| 目录 | 内容 |
|---|---|
| `server/` | 本地后端服务与工作台界面。 |
| `tools/` | 下载中心与环境准备界面。 |
| `runtime/` | `requirements.txt`、`pylibs/`、环境 `venv/` 与 FFmpeg `ffmpeg/`。 |
| `models/` | 下载的语音及音频处理模型权重。 |
| `python/` | 随包便携 CPython 3.12。 |
| `assets/` | 内置参考音色与素材。 |
| `outputs/` | 生成的音频结果。 |
| `uploads/` | 上传的音频素材。 |
| `docs/` | 使用与配置文档。 |

## 更多文档

- [快速开始（英文）](QUICKSTART.md)
- [配置说明](CONFIG.md)
- [API 文档](API.md)
