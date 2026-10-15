# MOSS 语音工作台

[English](README.md) | **中文**

基于 MOSS 语音模型的**全离线**语音与音频工作台，带桌面客户端与内置网页界面：音色克隆 / 单人配音、
音色设计、音效生成、多人对话配音，外加两个音频工具 —— 六轨分离（Demucs）与人声降噪
（MossFormer2_SE_48K）。全程不依赖云服务，音频不出本机。

详细参考文档：[`docs/API.md`](docs/API.md) · [`docs/CONFIG.md`](docs/CONFIG.md) · [`docs/DENOISE.md`](docs/DENOISE.md)

## 环境要求

| | |
|---|---|
| 平台 | **当前仅支持 Windows x64**（Windows 11 实测：RTX 5070 Ti 16 GB、torch 2.10.0+cu130、Python 3.12.10） |
| 显存 | 三个 8B 模型 int8 权重约占 16 GB；1.7B 音色设计约 9 GB；降噪约 0.5 GB。8B 余量很小，生成时**不要**同时开其它吃显存的程序（含开硬件加速的浏览器） |
| 运行根目录 | 开发源码根目录为 checkout（Windows 默认 `D:\MossTTSD`）；安装态工作台根目录为 `<install>/resources/workbench`，随安装位置变化，可重定位。 |

## 目录结构

```
<workbench-root>\（开发源码 checkout 或安装态 resources/workbench）
├─ client\           Electron 客户端 + 便携 Python；启动器 MOSS语音工作台-启动器.exe
├─ runtime\          只放依赖清单，venv 在目标机自建、不随包
│   ├─ requirements.txt   全部 pip 依赖的固定版本（torch 2.10.0+cu130、transformers 5.19 等）
│   ├─ pylibs\       只放 PyPI 没有的 vendored 包 mossformer2_se（置顶 sys.path）
│   └─ ffmpeg\       工程内 ffmpeg + DLL（PATH 上有 ffmpeg 亦可）
├─ models\           后端加载的全部权重都在这一个目录下
│   ├─ openmoss\     MOSS-TTS-v1.5 / TTSD-v1.0 / SoundEffect / VoiceGenerator（含 *-int8-nohead 产物）
│   │                与 MOSS-Audio-Tokenizer-fp16（四个模型共用的 codec）
│   ├─ whisper-small\        本地 ASR 权重（CTranslate2）
│   ├─ demucs\       六轨分离权重
│   └─ MossFormer2_SE_48K\   降噪权重与其 config.json
├─ assets\           音频资产（非权重）：内置参考音色与示例音频
│   ├─ voices\       15 个内置音色 wav + voices.jsonl
│   └─ reference\    端到端测试用示例音频
├─ server\           FastAPI 后端：app.py、moss_engine.py、asr.py、stems.py、denoise.py、config.json、web\
├─ tools\            模型下载 / 合并 / codec 准备 / 降噪权重工具
├─ integration\      客户端补丁脚本与端到端冒烟测试
├─ docs\             接口、配置、降噪参考文档
├─ uploads\ outputs\ 上传素材与生成结果
└─ start_server.bat  只启动后端（不起客户端）
```

## 启动方式

### 安装

安装桌面应用后即可启动使用。安装包自带工作台本体与便携 Python；首次启动后，在界面中完成两步准备：

1. 在「环境准备」中使用随包便携 Python 创建 `runtime/venv`，并安装 `runtime/requirements.txt` 依赖（约 3.4 GB）。安装源会自动选择（清华 → 阿里云 → 官方 PyPI，失败自动切换，界面日志会写明实际使用的源），PyTorch 软件包通过 `--extra-index-url https://download.pytorch.org/whl/cu130` 获取（约占其中 2.7 GB）。
2. 在「设置 → 模型下载」下载必需模型权重（约 61.8 GB）；Demucs、Whisper、MossFormer2_SE 等可选资源按需下载。FFmpeg 也在此下载（约 83 MB）。

安装包包含工作台本体（`server/`、`tools/`、`docs/`、`runtime/requirements.txt`、`runtime/pylibs/`、`python/`、`assets/`）及便携 CPython 3.12；不包含 `models/`、`runtime/venv/`、`runtime/ffmpeg/`、`outputs/`、`uploads/`。
### 从源码运行

要求 Windows x64 与 64 位 Python 3.12。在源码 checkout 根目录执行 `python tools/downloader_ui.py`（不带参数）打开独立环境准备/下载界面；用该 Python 创建 `runtime/venv` 并安装 `runtime/requirements.txt`，安装时包含 PyTorch 源 `--extra-index-url https://download.pytorch.org/whl/cu130`；然后运行 `start_server.bat`，或用 venv Python 启动 `server/run.py`。

开发根目录就是源码 checkout（Windows 默认 `D:\MossTTSD`）。安装后则使用 `<install>/resources/workbench`；客户端根据安装位置解析工作台根目录，支持迁移，不应假定它在开发路径。

下载内容固定落在工作台根目录。`MOSS_DOWNLOAD_ROOT` 仅供测试覆盖，正常使用时下载根目录不可配置。

第一次使用？请看 **[快速上手](docs/QUICKSTART.zh-CN.md)**：一页说明这个软件能做什么、两步准备工作（含体积与耗时预期）、常见问题（下载慢、退出码 3/4、能否离线、如何卸载或迁移）以及目录速查。也提供[英文版](docs/QUICKSTART.md)。

### 再启动

1. **桌面客户端（推荐）**：双击 `client\MOSS语音工作台-启动器.exe`。它只会拉起**一个**后端
   （`server\run.py`），然后打开工作台窗口。
2. **只起后端**：运行 `start_server.bat`，浏览器打开 <http://127.0.0.1:17980>。
   `MOSS_HOST` / `MOSS_PORT` 覆盖监听地址与端口，`MOSS_WORKBENCH_ROOT` 选择工作台根目录。
   `MOSS_TTS_PYTHON` 仅供环境准备模块发现基础解释器，不会覆盖后端解释器；后端必须由路径完全匹配的
   `runtime/venv` Python 启动。

界面提供中文与英文两套；设置页切换的语言对整个工作台生效（含内嵌的工具页）。设置页还提供
浅色 / 暗黑 / 跟随系统三档主题与主配色。

## 功能

| 功能 | 位置 | 路由 | 说明 |
|---|---|---|---|
| 音色克隆 / 单人配音 | 「单人配音」页 | `GET`/`POST` `/api/gen/tts` | 3–10 秒参考音频（或用内置音色）；31 种语言、中英混说、`[pause 1.5s]` 停顿控制 |
| 音色设计 | 「音色设计」页 | `GET`/`POST` `/api/gen/vg` | 用自由文本描述音色，**不需要**参考音频 |
| 音效生成 | 「音效生成」页 | `GET`/`POST` `/api/gen/sfx` | 描述环境声 / 拟音 + 目标时长（1 秒 ≈ 12.5 audio token） |
| 多人对话配音 | 「对话配音」页 | `POST` `/api/gen/ttsd` | `[S1]`/`[S2]` 脚本 + 每位说话人的参考音频与逐字稿 |
| 六轨分离 | 工具页 → Stems | `POST` `/api/stems/separate` | 六轨，或只要 `vocals` / `instrumental`（`mode`） |
| 人声降噪 | 工具页 → 降噪 | `POST` `/api/denoise/apply` | 0–100% 降噪强度（dry/wet 混合）；输出保持输入采样率与通道布局 |

所有重任务共用同一条 GPU 队列、同一时刻只跑一个。两个工具不依赖 MOSS 模型：分轨会先卸载已加载的
语音模型，降噪不会（它只占约 486 MB）。

## 第一次使用

1. 打开工作台并加载模型。量化档取决于部署的权重：仅有量化 checkpoint 时可用 int8；下载完整精度母本后可用 int8、float8、none。首次加载约 20–40 秒，加载另一个模型会自动卸载前一个。
2. 选功能页、填输入、生成。语音生成结果直接写入 `outputs/<场景>/`（WAV 与任务 JSON）；只有 Stems、Denoise 按任务建子目录：`outputs/Stems/<job_id>/`、`outputs/Denoise/<job_id>/`。可试听、下载、删除，也能当作参考音频复用。
3. 参考音频可以是内置音色、上传文件或自己录的音频。「对话配音」页每位说话人旁有 **识别逐字稿** 按钮，用本地 Whisper（CPU、纯离线）自动转写并填入。

采样参数采用官方推荐值 —— tts `1.7 / 0.8 / 25 / 1.0`、vg `1.5 / 0.6 / 50 / 1.1`、
ttsd `1.1 / 0.9 / 50 / 1.1`、sfx `1.5 / 0.6 / 50 / 1.2`。长度建议：音效 ≤ 60 秒、对话 ≤ 3 分钟/次；
要更长就把 `server\config.json` 的 `tokenizer_device` 设为 `"cpu"`。

## 在别的程序里调用

接口用法见 [`docs/API.md`](docs/API.md)（curl / Python / JS 示例齐全）。最省事的是同步链接
`GET /api/gen/*`：直接返回 WAV 字节（元数据在 `X-Output-*` 响应头）；传 `wait=0` 则立刻返回任务 id 自行轮询。
**URL 里的中文必须百分号编码** —— 让 HTTP 客户端自动编码，或 `curl -G --data-urlencode "text=你好"`。
`GET /api/gen` 列接口、`/docs` 是 Swagger、跨域已开、可选 `api_token` 鉴权。

## 模型与权重

模型权重**不随安装包发布**，上传素材与生成结果也不会被打包。`models\*` 可随时重建：

| 命令 | 用途 |
|---|---|
| `tools\download_models.py --models ttsd,sfx [--dest DIR]` | 下载 MOSS 权重（断点续传 + sha256 校验） |
| `tools\prepare_models.py [--model tts]` | 把分片合并成 `model.safetensors` 并写出 `MANIFEST.json` |
| `tools\download_denoise_models.py --check` / `--force` | 校验或重下降噪权重（路径与 sha256 取自 `server\config.json`） |
| `integration\apply_launcher_patch.py` | 重新给客户端打补丁（现成 `app.asar` 已打好） |

可用量化档取决于部署的权重：仅部署量化 checkpoint 时提供 int8；下载完整精度母本后，引擎可在线量化并提供 int8、float8、none。`*-int8-nohead` 是可直接加载的 int8 产物；本仓库不含生成该落盘产物所用的外部工具。

## 配置

`server\config.json` 管监听地址与端口、输出与上传目录、模型注册表、ASR 与降噪权重元数据；
每个字段都有默认值，改完**重启后端**生效。完整字段表见 [`docs/CONFIG.md`](docs/CONFIG.md)。

## 打包安装包

`packaging/`（详见其 [README](packaging/README.md)）当前仅交付 **Windows x64** 应用。安装包不含 `models/`、`runtime/venv/`、`runtime/ffmpeg/`、上传素材与生成结果；依赖与模型在首次启动后准备和下载。macOS 打包命令仍属未完成实验，不是受支持交付：随包是 Windows CPython、requirements 固定 CUDA 版 PyTorch、FFmpeg 仅有 win32-x64。macOS 要可用，必须先按平台准备并验收原生 CPython、CPU/MPS 依赖与原生 FFmpeg。

```bash
cd packaging
npm install && npm run extract && npm run retrofit
npm run dist:win          # NSIS 安装包 → release/windows/
npm run dist:mac:x64      # 前置未完成，不是受支持构建
npm run dist:mac:arm64    # 前置未完成，不是受支持构建
```

Windows x64 可在本机构建并实际运行（Electron 44.7.0，优先用本机缓存；GitHub 不通时设
`ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/`）。当前 macOS workflow 不代表可用的 macOS 工作台；其运行时前置尚未准备，详见 `.github/workflows/build-macos.yml`。

### 客户端 asar 补丁

`client/resources/app.asar` 是构建产物，本仓库的界面补丁在 `integration/`，**每次重打该 asar 后都要重跑**。两个脚本都会解包、改渲染层 bundle、对结果跑 `node --check`，通过后才回打包——坏补丁不会写进 asar。

```bash
node integration/enable_english_ui.js           client/resources/app.asar            # 生成 app.asar.new：持久化英文界面与翻译
node integration/downloads_in_settings_patch.js client/resources/app.asar --apply     # 设置页「通用设置 / 模型下载」页签（应用前先备份）
```

两者都可重复执行：再跑一次是替换已注入的块，不会叠加。`downloads_in_settings_patch.js` 追加的是自包含的 DOM 增强脚本，即使挂不上也不影响设置页本身；「模型下载」页签内嵌后端 `/downloads` 页面，按可视高度自适应，并在每次切回时重新加载（后端重启后能自愈此前失败的加载）。

打包态工作台根目录默认为 `<resourcesPath>/workbench`，可由 `MOSS_WORKBENCH_ROOT` 覆盖；开发态 Windows 默认 `D:/MossTTSD`。Windows 后端始终必须由 `<workbench>/runtime/venv/Scripts/python.exe` 启动，且运行解释器路径必须完全匹配；`MOSS_TTS_PYTHON` 仅供环境准备模块发现基础解释器，不能覆盖后端解释器。PATH 发现只存在于环境准备模块，不是后端回退分支。

## 许可

| 组件 | 许可 |
|---|---|
| MOSS 模型与代码（ModelScope `openmoss/MOSS-TTS-v1.5`、`MOSS-TTSD-v1.0`、`MOSS-SoundEffect`、`MOSS-VoiceGenerator`） | Apache-2.0 —— 可免费商用 |
| MossFormer2_SE_48K（ClearerVoice-Studio）代码与权重 | Apache-2.0 |
| Demucs 及其预训练权重 | 见上游 `facebookresearch/demucs` 许可 |
| faster-whisper / Whisper、rotary_embedding_torch、torchinfo 及 `runtime\pylibs` 其余依赖 | 宽松许可（MIT 等） |
| `runtime\ffmpeg` 内的 FFmpeg 二进制 | 按构建为 LGPL / GPL |

克隆音色的授权需自行取得：模型许可宽松**不代表**可以随意模仿他人声音。

## 常见问题

| 现象 | 处理 |
|---|---|
| 客户端显示旧界面 | 客户端只在启动时拉起后端：重启客户端，并 Ctrl+F5 强刷页面 |
| 生成时 CUDA out of memory | 关掉其它占用显存的程序（开硬件加速的浏览器也算），或把 `server\config.json` 的 `tokenizer_device` 改成 `"cpu"` 让出约 3.5 GB |
| 17980 端口被占用 | 用 `set MOSS_PORT=17981` 启动，或改 `server\config.json` 的 `port` |
| 选某个量化档被 400 拒绝 | 该模型只有 `int8` 可用，响应里会写明原因 |
| 界面上找不到上传素材或结果 | 看 `uploads\` 与 `outputs\`；任务正在跑时对应产物受删除保护 |
