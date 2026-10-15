# MOSS 语音工作台 · 配置与接口说明

> 给「上层应用 / AI agent」看的调用说明书。**所有示例均为本机实测通过的命令**（2026-10-14，RTX 5070 Ti 16 GB）。
> 服务地址：`http://127.0.0.1:17980` ｜ 交互式文档：`/docs`（Swagger）｜ 机器可读：`/openapi.json` ｜ 能力清单：`GET /api/gen`

---

## 0. 一页速览（想直接调用就看这段）

```bash
# 1) 起服务（二选一）
D:\MossTTSD\start_server.bat                      # 独立启动（浏览器访问 http://127.0.0.1:17980）
#   或双击 D:\MossTTSD\client\MOSS语音工作台-启动器.exe（客户端，会拉起同一个后端）

# 2) 自检
curl -s http://127.0.0.1:17980/api/health          # {"status":"ok",...}
curl -s http://127.0.0.1:17980/api/gen             # 四个功能的调用清单（JSON）

# 3) 直接出音频（同步，返回 wav 字节）
#    ⚠️ URL 里的中文必须百分号编码：浏览器 / requests / httpx / fetch 会自动编码，**curl 手拼 URL 不会**，
#       服务端 HTTP 解析器会直接回 400 `Invalid HTTP request received.`（实测）。所以中文参数一律用 -G --data-urlencode：
curl -o 音效.wav -G "http://127.0.0.1:17980/api/gen/sfx" --data-urlencode "prompt=雨点打在铁皮屋顶" --data-urlencode "seconds=5"
curl -o 配音.wav -G "http://127.0.0.1:17980/api/gen/tts" --data-urlencode "text=你好" --data-urlencode "voice=zh_1"
curl -o 设计.wav -G "http://127.0.0.1:17980/api/gen/vg" --data-urlencode "text=你好" --data-urlencode "instruction=温暖平静的成年男声"
# 多人对话是唯一必须 POST JSON 体的（script + 每位说话人的参考音频与逐字稿；中文放 body 里，无编码问题）：
curl -o 对话.wav -X POST http://127.0.0.1:17980/api/gen/ttsd -H "Content-Type: application/json" -d '{"script":"[S1] 大家好，欢迎来到本期节目。[S2] 今天聊聊本地语音模型。","speakers":[{"tag":"[S1]","ref_audio":"D:/MossTTSD/assets/voices/zh_1.wav","ref_text":"不管怎么样我和湯姆还是要感谢贝尔卡金的元首不然以后再见我们也成了丧失了"},{"tag":"[S2]","ref_audio":"D:/MossTTSD/assets/voices/me.wav","ref_text":"你是否听说过比特币,却对它一直拌解你是否对区块链充满好奇,却不知从何学起"}],"max_minutes":1,"seed":1234}'
#    ⚠️ Windows 中文控制台（GBK/CP936）会把命令行里的中文转成 GBK 再交给 curl，服务端按 UTF-8 解码 → 文本变乱码，
#       但 HTTP 仍然是 200（**静默出错**，实测：GBK 传参生成的音频 ASR 回读是 "Except it's you"，本意是「要念的文本」）。
#       这种环境请把 JSON 体存成 UTF-8 文件后 `curl --data-binary @body.json`，或改用客户端库（requests / httpx / fetch 自动 UTF-8）。
```

- 四个功能：**单人配音/音色克隆** `tts`、**音色设计** `vg`、**音效生成** `sfx`、**多人对话** `ttsd`。
- **URL 参数里的中文/空格/`&` 必须百分号编码**：HTTP 客户端库（requests / httpx / fetch / 浏览器）会自动编码，**curl 手拼 URL 不会** → 用 `-G --data-urlencode`，或改走 POST JSON 体（四个端点都支持 POST）。
- 一次调用完成「按需加载模型 → 生成 → 落盘 → 返回音频」；**首次调用含模型加载约 25 s**，之后同模型只需生成时间（实测 sfx 6.8 s / vg 18.4 s / tts 26 s / ttsd 29.3 s）。
- 产物按场景落盘：语音生成结果直接写入 `outputs/<单人配音|音色设计|多人对话|音效生成>/`（WAV 与任务 JSON）；Stems 与 Denoise 按任务写入 `outputs/Stems/<job_id>/`、`outputs/Denoise/<job_id>/`。
- **一次只驻留一个模型**（16 GB 卡），调另一个模型会自动卸载前一个——所以频繁交替调用四个功能会反复付加载时间。

---

## 1. 配置文件 `D:\MossTTSD\server\config.json`

改完**重启后端**生效（客户端：先「停止」再「启动」）。所有字段都有默认值，缺省不影响启动。

| 字段 | 默认 | 说明 |
|---|---|---|
| `host` | `0.0.0.0` | 监听地址。⚠️ 默认局域网可见；只给本机用就改 `127.0.0.1`。环境变量 `MOSS_HOST` 可覆盖 |
| `port` | `17980` | 端口。环境变量 `MOSS_PORT` 可覆盖（`MOSS_PORT=17981 python -u run.py`） |
| `quant` | `int8` | 默认量化档。可选 `int8` / `float8` / `none`（及模型提供时的其他档）；实际可用项由权重决定：仅部署量化 checkpoint 时为 int8，完整精度母本在位时可用 int8 / float8 / none |
| `attn_implementation` | `auto` | 注意力实现（`auto`/`sdpa`/…）；无 flash-attn，引擎已按官方文档回退 |
| `tokenizer_dtype` | `float16` | 音频 codec 精度；`float16` 是同码本前提（bf16 会错 39.7%） |
| `tokenizer_device` | `auto` | codec 放 GPU 还是 CPU；改 `"cpu"` 可再让出 3.55 GB 显存（参考音频编码/解码走 CPU） |
| `tokenizer_swap` | `true` | 生成期把 codec 挪到 CPU、解码前挪回 GPU（省 ~4 GB 显存峰值） |
| `output_dir` | `../outputs` | 产物根目录（相对 `server\`）。四类语音生成场景直接在此目录下写文件；只有 Stems 与 Denoise 在任务执行时创建 `Stems/<job_id>/`、`Denoise/<job_id>/` |
| `upload_dir` | `../uploads` | `POST /api/upload` 的落盘处 |
| `upload_max_bytes` | `536870912` | `/api/upload` 单文件字节上限（默认 512 MiB），以分块写入并拒绝超限文件 |
| `cors_origins` | `["*"]` | 跨域白名单。要收紧写 `["http://localhost:3000"]`；响应头 `X-Output-*` 已 `expose` |
| `api_token` | `""` | 空 = 不校验。设成任意字符串后 `/api/gen/*` 要求 `?token=<值>` 或请求头 `X-API-Token`（否则 401） |
| `asr.model` | `../models/whisper-small` | 本地 ASR 权重（CTranslate2，483 MB，仓库自带） |
| `asr.device` / `asr.compute_type` | `cpu` / `int8` | ASR 算力；`cuda`+`int8_float16` 更快但会抢显存 |
| `asr.beam_size` | `5` | 识别束宽 |
| `denoise.checkpoint` / `sha256` / `size_bytes` / `download_url` / `download_url_fallback` | — | 降噪引擎（MossFormer2_SE_48K）的权重元数据。**独立于 `models` 注册表**，因此不会出现在工作台模型列表里；`tools\download_denoise_models.py --check`（只校验）或 `--force`（重下，断点续传 + sha256）按这组字段工作。权重缺失时 `/api/denoise/apply` 直接报错并在消息里给出该命令 |
| `models.<key>.*` | — | 四个模型的注册表（见下） |
| `models.<key>.codec_path_fallback` | `../models/openmoss/MOSS-Audio-Tokenizer-fp32` | codec 回退：`codec_path` 里没有权重时改用它（只下母本的用户拿到的是 fp32 母本）。`/api/state` 反映实际生效路径 |
| `downloads.items[]` | — | **统一下载器目录**（9 条）。字段：`id`、`group`（`required`/`optional`）、`label`/`label_en`、`notes`、`bytes`、`target`、`enables`、`source`。`source` 四种：`{type:"modelscope", repo}`、`{type:"url", url, url_fallback?, sha256?, prefix8?}`、`{type:"zip", url, sha256}`（把包内 `<前缀>/bin/*` 平铺到目标目录）、`{type:"bin", url, name, sha256}`（单个可执行文件落进目标目录，如 `ffmpeg.exe`）。任意源都可带 `fallback_sources:[…]`：按顺序尝试，前一个失败（限流/校验不过）自动换下一个。ffmpeg 的判定 `_ffmpeg_ok` 同时接受 **shared**（exe + libav 家族 DLL）与 **static**（单个自包含 exe）两种布局，不再要求 ffprobe。落地根**固定为安装目录**（`server/` 的上一级），只有测试用环境变量 `MOSS_DOWNLOAD_ROOT` 能覆盖；`bytes` 只用于磁盘预检与进度分母，带 `prefix8` 的条目（demucs 上游不公布完整 sha256/确切体积）按数量级判定是否已落盘，完整性由 sha256 前 8 位承担 |

**`models` 注册表字段**：`label`（界面名）、`kind`（引擎内部类型；⚠️ 音色设计的 kind 是 `voicegen`，HTTP 路由键才是 `vg`）、`path`（模型目录）、`codec_path`（共用 codec）、`quant_checkpoint`（落盘 int8 产物目录，优先于 `quant` 选项）、`voice_file` / `voice_root`（内置音色表与目录，仅 tts 有）。

其它相关环境变量：`MOSS_HOST`、`MOSS_PORT`（服务端）；`MOSS_TTS_PYTHON`（环境准备模块发现基础解释器时使用）与 `MOSS_WORKBENCH_ROOT`（客户端选择工作台根目录）。打包态默认根目录为 `<resourcesPath>/workbench`，开发态 Windows 默认 checkout `D:\MossTTSD`；下载内容固定落在工作台根目录，只有测试用环境变量 `MOSS_DOWNLOAD_ROOT` 能覆盖。
后端解释器与基础解释器发现是两件事：`server/run.py` 只接受 `<workbench>/runtime/venv/Scripts/python.exe`（Windows）或对应平台的 `bin/python3`，且必须是实际运行进程的同一路径；缺失 venv 返回退出码 3，使用其它解释器或 venv 依赖预检失败返回 4。没有后端 PATH 回退。PATH 探测只在 `tools/env_setup.py` 的环境准备阶段使用；`MOSS_TTS_PYTHON` 不会覆盖后端解释器。
安装包包含 `server/`、`tools/`、`docs/`、`runtime/requirements.txt`、`runtime/pylibs/`、`python/`（便携 CPython 3.12）与 `assets/`；不包含 `models/`、`runtime/venv/`、`runtime/ffmpeg/`、`outputs/`、`uploads/`。首次启动需在「环境准备」中安装依赖（约 3.4 GB），再在「设置 → 模型下载」下载模型；必需模型约 61.8 GB，FFmpeg 约 83 MB。
`GET /api/state` 的 `env` 对象包含 `ready`、`interpreter`、`torch`、`cuda`、`cudnn`、`system_cudnn_conflict`、`missing`。`MOSS_ENV_READY`、`MOSS_ENV_INTERPRETER`、`MOSS_ENV_TORCH`、`MOSS_ENV_CUDA`、`MOSS_ENV_CUDNN`、`MOSS_ENV_SYSTEM_CUDNN_CONFLICT`、`MOSS_ENV_MISSING` 是 `server/run.py` 与应用之间的内部握手字段，不是用户配置开关，勿手动设置。

独立环境准备界面（`python tools/downloader_ui.py`）的接口为 `GET /api/env/status`、`GET /api/env/log`、`POST /api/env/start`、`POST /api/env/cancel`；它们属于独立 UI 服务，不是工作台 FastAPI 后端路由。

---

## 2. 目录与关键文件

| 路径 | 内容 |
|---|---|
| `D:\MossTTSD\server\` | `app.py`（FastAPI：模型管理/任务队列/SSE/对外接口）、`moss_engine.py`（推理引擎）、`asr.py`（本地 whisper）、`denoise.py`（降噪引擎，MossFormer2_SE_48K）、`stems.py`（Demucs 分轨）、`config.json`、`web\`（前端：`index.html`/`app.js`/`i18n.js` 中英文词条、`tools.html`、`stems.*`、`denoise.*`） |
| `D:\MossTTSD\runtime\` | `requirements.txt`（**单环境**依赖清单，pip 可直接安装）；`venv\`（按该清单装出来的解释器环境）；`pylibs\`（只放 PyPI 没有的 vendored 包 `mossformer2_se`，`run.py` 会把它插到 `sys.path` 最前）；`ffmpeg\`（工程内 ffmpeg + DLL） |
| `<workbench>\models\openmoss\` | 四个模型、`MOSS-Audio-Tokenizer-fp16` 与可选 `*-int8-nohead` checkpoint。完整精度母本若部署在模型目录，则会按可用权重增加 int8/float8/none 选项；仅 checkpoint 部署仅提供 int8 |
| `D:\MossTTSD\models\whisper-small\` | 本地 ASR 权重（CTranslate2，483 MB） |
| `D:\MossTTSD\models\demucs\` | 分轨权重 `5c90dfd2-34c22ccb.th` |
| `D:\MossTTSD\outputs\` | 语音生成按场景落盘；Stems 与 Denoise 各自使用任务子目录 |
| `D:\MossTTSD\uploads\` | 上传的参考音频 |
| `D:\MossTTSD\assets\reference\` | 端到端测试用示例音频（`integration\full_functional_test.py` 的输入） |
| `D:\MossTTSD\outputs\` | 语音生成按场景直接落盘；Stems 与 Denoise 目录下包含按 `job_id` 分开的任务结果 |
| `D:\MossTTSD\docs\API.md` | 对外接口参考（更细的调用示例） |
| `D:\MossTTSD\docs\DENOISE.md` | 降噪选型结论、四档实测对比、取件通道、淘汰理由与验收口径 |

全局界面语言：设置页提供 **中文**（默认）与 **英文** 两个选项（英文界面里显示为 `Chinese` / `English`；配置值仍是 `chinese` / `english`）；英文标签为 `Language`，按钮为 `Save / Reset`，首页顶栏为 `Start / Refresh / Stop`。保存后立即切换，`client\config.json` 保存偏好；重置恢复中文。五个目录入口位于「文件目录 / Folders」分区。工具页集成本地 Stems 音频分轨与本地人声降噪（`/tools/denoise`），同样跟随全局语言；嵌入工具通过 `?language=english|chinese` 初始化并接收 `{type: "moss-language", language}` 消息。**Web 语音工作台（`server\web\index.html`，即首页 iframe）自 2026-10-15 起也已接入同一套语言机制**：页面加载时向父窗口发 `{type: "moss-language-request"}`，外壳答以当前语言；外壳切换语言时向所有 iframe 广播；独立用浏览器打开时可用 `?language=english` 指定（无参数默认中文）。词条在 `server\web\i18n.js`（中/英各 164 条 + `t()`/`applyStatic()`），静态文案在 `index.html` 上挂 `data-i18n`，动态文案在 `app.js` 走 `t()`。模型名里的中文描述来自 `config.json` 的 `models.*.label`，英文界面按模型 key 用页面词条显示（不改服务端配置与接口结构）。界面语言不改变生成内容的语言。

首页顶栏中间的服务链接显示后端地址（`http://127.0.0.1:<port>/`，由 `checkPort()` 动态取，未启动时不渲染），点击用**系统默认浏览器**打开网页版 —— 走主进程既有的 `setWindowOpenHandler → shell.openExternal`，不在 Electron 内开新窗口。

**全局界面主题（2026-10-15）**：设置页**最上方**「外观 / Appearance」提供 **浅色 / 暗黑 / 跟随系统** 三档与 **主配色**（8 个预设色块 + 原生取色器 + `恢复默认`）。改动立即生效并即时落盘到 `client\config.json`：

```json
{ "language": "english", "fp16": true, "theme": { "mode": "dark", "primary": "#52c41a" } }
```

- `mode`：`light` | `dark` | `system`（`system` 跟 `prefers-color-scheme`，系统明暗变化时外壳与页面自动跟随）。
- `primary`：`#rrggbb`，或 `""` = **不覆盖各自默认**（外壳 `#f77612`、工作台 `#6a6ef6`、Stems 页自带绿）⇒ 没选颜色时浅色/暗色与改造前逐像素一致。

传播链路（与语言同一套，权威来源是外壳）：

1. **外壳**：启动读 `config.json` 的 `theme`，写 `<html data-theme>`，并按需覆盖 antd `ConfigProvider` 的 `colorPrimary` + 一组暗色 token。⚠️ 包里 antd 被 tree-shaking（只有 `defaultAlgorithm`），**没有** `darkAlgorithm`，所以暗色是用 ~22 个 token（`colorBgBase`/`colorBgContainer`/`colorBgHeader`/`colorText*`/`colorBorder*`/`colorSplit`…）覆盖实现的；其中**主色淡底系列**（`colorPrimaryBg`/`colorPrimaryBgHover`/`controlItemBgActive`/`controlItemBgHover`/`colorPrimaryBorder*`）必须由运行时**按当前主色现算**：亮色算法给的 `colorPrimaryBg` 是接近白色的淡色（如 `#6a6ef6` → `#f0f3ff`），暗色下配浅色文字会看不清（踩过：语言下拉框选中项、侧栏菜单选中态）；**状态类淡底**同理，`colorWarningBg`/`colorErrorBg`/`colorSuccessBg`/`colorInfoBg`（+ `BgHover`/`Border`）在 token 表里写死为暗色淡底（亮色算法默认给 `#fffbe6`/`#fff2f0` 这类近白色，暗色下整块看不清 —— 踩过：关于页的用户协议 Alert）。切换时 `window.__mossRerenderTheme()` 让根组件重渲染，token 立即生效。
2. **iframe**：外壳把 `?theme=<mode>&primary=<hex>` 拼到两个 iframe 的 src（首页 iframe 由 `setSrc` 追加、Tools iframe 由注入的 `StemsTools` 追加），并广播 `{type:'moss-theme', mode, primary}`；页面侧 `server\web\theme.js` 的优先级为 **外壳消息 > URL 参数 > localStorage > 默认**，还会向父窗口发 `{type:'moss-theme-request'}` 主动索取一次。只对 `127.0.0.1` / `localhost` 的来源应答与投递。
3. **页面落地**：`theme.js` 写 `<html data-theme="light|dark">` 与 `--accent*`（`--accent` / `--accent-strong` / `--accent-weak` / `--accent-soft` / `--accent-fg`；亮底压暗、暗底提亮，`--accent-fg` 按亮度取黑/白）。CSS 侧：`style.css` 亮/暗两套基色变量（`--bg`/`--bg-soft`/`--panel`/`--field`/`--text`/`--muted`/`--tab-fg`/`--line`/`--line-strong`/`--hero-glow`/`--ok`/`--warn`/`--danger`/`--shadow`）、`tools.html` 用 `--t-*`、`stems.css` 把原字面量收成 93 个槽位（`:root` 存原值、`html[data-theme="dark"]` 只重映射）。**改主题只动这些变量，不要往规则里塞死色值**。

维护提示：`theme.js` 必须放在各页 `<head>` 的样式表**之前**（首帧就定好 `data-theme`，暗色不会先白闪）。外壳自带的写死颜色（设置页/首页画布 `background-color:white`、左侧菜单 `#f5f5f0`、关于页卡片 `#f5f5f5`、停止页 `#f6ece4`/`#937965`、外链 `#1677ff`、品牌 `#f77612`）已由补丁换成 `var(--moss-*, 原值)`；新增硬编码颜色会破坏暗色。给外壳加主题相关 CSS 请写在补丁的哨兵块内（`/* ---- moss-theme:begin ---- */` … `/* ---- moss-theme:end ---- */`），构建时整块替换（旧包上的无哨兵追加块也会被清掉）。

前端资源缓存：`/static/*` 一律带 `Cache-Control: no-cache`（每次回源校验，命中 ETag 得 304），且 `/`、`/tools`、`/tools/stems` 返回的 HTML 会把资源 URL 里的 `__UI_BUILD__` 替换成 `server\web\` 下最新改动时间戳 ⇒ 改了前端刷新即生效，长期存活的客户端浏览器配置也不会继续跑旧脚本（2026-10-15 之前踩过：`app.js` 被 Chromium 启发式缓存复用，页面停在旧版）。

2026-10-14 修复外壳按钮无响应：移除重复语言监听器，翻译时断开 MutationObserver，仅在文字改变时写入再恢复监听，避免相同文案和双监听器引发无限微任务循环。构建器会替换全部旧注入块，只保留一个监听器。更新时先退出客户端，执行 `node integration\enable_english_ui.js` 生成 `client\resources\app.asar.new`，再运行 `python integration\swap_client_build.py` 替换并重启。⚠️ `swap_client_build.py` 的进程探测对**非 ASCII 进程名**（`MOSS语音工作台-启动器.exe`）会误报「已退出」，替换会以 `WinError 5` 失败；动手前请用 `tasklist | findstr MOSS` 自行确认客户端已完全退出。

补丁构建器（2026-10-15 加固）：所有 slice 锚点（`ConfigSettings` / `FolderItem` / `App()` 等）都校验 `-1` 并直接抛错，注入后还有产物自检（关键组件与握手标记必须在位）⇒ 上游渲染包改名时**报错退出**，不会静默打出被截断的坏包；运行时的移除/注入已做空行归一化，重复重建**字节稳定**（连续三次重建哈希一致）。语言桥接只向 `127.0.0.1` / `localhost` 的 iframe 投递，并只应答来自本机后端的 `moss-language-request`。工作台侧对同语言广播做短路（语言未变不重渲染、不重拉 `/api/state`）——外壳的 MutationObserver 会在任意 DOM 变动时广播语言。

稳定性整改：Tools iframe 跨侧栏导航保留，活动任务期间禁止替换输入，轮询网络错误重试同一任务；结果翻译更新不替换音频播放器。补丁构建器可在已注入包上重复执行，不重复声明组件。模型卸载进入同一 GPU 队列并保持同步响应；codec CPU 执行使用 float32，生成异常后恢复设备或使缓存失效。Stems 使用配置中的上传/输出根目录，暂存后发布产物，共享衰减增益防止 PCM 削波，ZIP 下载不依赖进程内任务记录。

运行依赖：`runtime\ffmpeg` 包含 FFmpeg 及其 DLL，服务优先使用本工程版本（缺失时回退 PATH 上的 ffmpeg）；依赖由 `runtime\requirements.txt` 一份**单环境**清单描述（torch 2.10.0+cu130 需带 `--extra-index-url https://download.pytorch.org/whl/cu130`），PyPI 没有的 `mossformer2_se` 以 vendored 目录随包提供。移除 Windows 不支持的 expandable_segments 环境设置。本轮未打安装包（2026-10-15 已补齐 Web 工作台国际化，见第 2 节）。

启动/停止：

```bash
# 启动（独立）
D:\MossTTSD\start_server.bat
# 启动（等价，可改端口）
cd /d D:\MossTTSD\server && set MOSS_PORT=17980 && D:\MossTTSD\runtime\venv\Scripts\python.exe -u run.py
# 停止：关掉窗口，或在 PowerShell 里执行
Stop-Process -Id (Get-NetTCPConnection -LocalPort 17980 -State Listen).OwningProcess -Force
# （等效写法：netstat -ano | findstr :17980 找到 PID → taskkill /PID <pid> /F）
```

---

## 3. 四个功能的调用卡

通用约定（下文所有接口）：

| 项 | 值 |
|---|---|
| 同步 | `wait=1`（默认）：本次请求等到生成完，**返回 `Content-Type: audio/wav` 的原始字节** |
| 异步 | `wait=0`：**立刻**返回 `{"job_id":"…","status":"pending","poll":"/api/jobs/<id>"}`；轮询到 `status=done` 后取 `result.outputs[]` |
| 超时 | `timeout`（默认 600 s）：`wait=1` 最长等待；超时返回 504，任务仍在后台跑 |
| 鉴权 | `api_token` 为空则无需；否则 `?token=` 或 `X-API-Token` 头 |
| 编码 | URL 里的参数值必须百分号编码（UTF-8）：中文、空格、`&`、`#` 等。curl 用 `-G --data-urlencode`；客户端库与浏览器会自动做。⚠️ 若控制台代码页是 GBK/CP936，中文会在交给 curl 前就被转成 GBK（静默产出乱码文本，HTTP 仍 200）⇒ 体走 UTF-8 文件 `--data-binary @body.json` |
| `seconds` / `tokens` | **建议留 0**（让模型自定长度）。填了会按该 token 预算提前收尾、可能截短长句 |

### 3.1 单人配音 / 音色克隆 `tts`

```bash
# GET（链接直调；中文参数用 -G --data-urlencode，否则 400 Invalid HTTP request received.）
curl -o a.wav -G "http://127.0.0.1:17980/api/gen/tts" --data-urlencode "text=要念的文本" --data-urlencode "voice=zh_1" --data-urlencode "seed=1234"
# POST（JSON）
curl -o a.wav -X POST http://127.0.0.1:17980/api/gen/tts -H "Content-Type: application/json" \
  -d '{"text":"要念的文本","prompt_audio":"D:/MossTTSD/assets/voices/zh_1.wav","seconds":0,"seed":1234,"wait":true}'
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `text` | ✅ | 要念的文本 |
| `voice` / `prompt_audio` | ✅ 二选一 | `voice` 支持内置音色 **id**（`voice-2`）/ **名称**（`🇨🇳 磁性男声`）/ **文件名**（`zh_1` 或 `zh_1.wav`）；`prompt_audio` 直接给服务器上的音频路径（上传件或 `assets\voices\*.wav`） |
| `num_takes` | | 条数（默认 1），产物 `_1/_2…` 后缀 |
| `seconds` / `tokens` | | 时长上限（建议 0） |
| `language` | | 留空自动；克隆音色与文本语言无关 |
| `seed` | | **批量生产务必固定**（0 = 随机，音色会漂移） |
| 采样 | | 官方推荐 `temperature 1.7 / top_p 0.8 / top_k 25 / repetition_penalty 1.0`（已为默认） |

### 3.2 音色设计 `vg`（无需参考音频）

```bash
curl -o b.wav -G "http://127.0.0.1:17980/api/gen/vg" --data-urlencode "text=要念的文本" --data-urlencode "instruction=温暖平静的成年男声，语速中等" --data-urlencode "seed=1234"
```

参数：`text`✅、`instruction`✅（自由文本描述性别/年龄/音质/情绪/语速/口音），采样默认 `1.5 / 0.6 / 50 / 1.1`。
想把设计出的音色固定下来：下载生成结果 → 当作 `tts` 的参考音频做克隆。

### 3.3 音效生成 `sfx`

```bash
curl -o c.wav -G "http://127.0.0.1:17980/api/gen/sfx" --data-urlencode "prompt=雨点打在铁皮屋顶" --data-urlencode "seconds=5" --data-urlencode "seed=1234"
```

参数：`prompt`✅（环境声/拟音描述，中英皆可）、`seconds`（默认 10，建议 ≤60）、`tokens`（1 秒 ≈ 12.5），采样默认 `1.5 / 0.6 / 50 / 1.2`。

### 3.4 多人对话 `ttsd`

```bash
curl -o d.wav -X POST http://127.0.0.1:17980/api/gen/ttsd -H "Content-Type: application/json" -d '{
  "script": "[S1] 大家好，欢迎来到本期节目。[S2] 今天聊聊本地语音模型。",
  "speakers": [
    {"tag":"[S1]","ref_audio":"D:/MossTTSD/assets/voices/zh_1.wav","ref_text":"不管怎么样我和湯姆还是要感谢贝尔卡金的元首不然以后再见我们也成了丧失了"},
    {"tag":"[S2]","ref_audio":"D:/MossTTSD/assets/voices/me.wav","ref_text":"你是否听说过比特币,却对它一直拌解你是否对区块链充满好奇,却不知从何学起"}
  ],
  "max_minutes": 2, "seed": 1234, "wait": true
}'
```

| 参数 | 说明 |
|---|---|
| `script` | 脚本，用 `[S1]`/`[S2]` 标轮次，一句一段 |
| `speakers[]` | 每位：`tag`、`ref_audio`（路径）、`ref_text`（**该段参考音频的逐字稿，必须逐字一致**；内置音色的 `text` 已是 2026-10-14 的 ASR 转写真值可直接用，自己的音频用 `POST /api/asr {"path": …}` 现场转写） |
| `max_minutes` | 时长上限（默认 3；建议 ≤3） |
| `num_takes` / `seed` | 同上 |
| 采样 | 默认 `1.1 / 0.9 / 50 / 1.1` |

> 上面两条 `ref_text` 就是对应音频的逐字稿（2026-10-14 已把内置音色表 15 条的 `text` 全部换成 `/api/asr` 转写真值，见 §7）。**你自己的参考音频**仍须现场 `POST /api/asr` 转写——逐字一致是硬要求。
> GET 形式也可用（适合链接拼装）：`/api/gen/ttsd?script=…&speakers=<URL 编码的 JSON 数组>&wait=0`（中文同样要百分号编码）

---

## 4. 参考音频：内置音色 / 上传 / 转逐字稿

```bash
# 内置 15 条音色（id / 名称 / 路径 / 试听；id 即行号 voice-1..voice-15）
curl -s http://127.0.0.1:17980/api/tts/voices
curl -s -o hear.wav http://127.0.0.1:17980/api/tts/voice-audio/voice-2

# 上传自己的参考音频（multipart，字段名 files，可多个）→ 拿 path 填 prompt_audio
curl -s -F "files=@D:/my/ref.wav" http://127.0.0.1:17980/api/upload

# 参考音频 → 逐字稿（本地 whisper，CPU，离线；多人对话的 ref_text 用这个）
curl -s -X POST http://127.0.0.1:17980/api/asr -H "Content-Type: application/json" \
  -d '{"path":"D:/MossTTSD/uploads/xxxx.wav"}'
# → {"text":"…","language":"zh","duration":6.87,"elapsed":2.96}
```

`/api/asr` 只允许 `uploads\` 与内置音色目录内的音频；也可用 `GET /api/gen/tts?…` 时对 `voice=` 直接发音。

⚠️ **内置音色表已按音频实测重标（2026-10-14）**：原表 30 行里 `en_4.wav` 被 **17 行**重复引用（名字却遍及 English News / 한국어 / Español / Français / … / Türkçe，实际全是同一段英文新闻）⇒ 现**去重为 15 行，与 `assets\voices\` 里 15 个 wav 一一对应**，并补进原本没被引用的 `zh_2.wav`。`id` 取行号（`voice-1..voice-15`，前 14 个 id 与去重前一致）。
条目名格式统一为 **`语言旗 + 男/女声 · 描述`**，三个字段均已实测：
- `语言`：`/api/asr` 检测（🇨🇳 ×8 / 🇺🇸 ×6 / 🇯🇵 ×1）；
- `性别`：基频（40 ms 自相关，最小 lag 修正倍频）＋谱质心交叉判定 —— 已确定的 10 条（中文/日文）分布清晰（男 114–158 Hz / 女 194–281 Hz），英语条目以同语言已知男声 `en_4`（P25 109 / 中位 121 / P75 134 Hz）为基准，其余 5 条四分位区间整体高于该男声带 ⇒ 判女声；
- `text`：30 行旧的 `text` 与音频**逐条都对不上（30/30）**，已全部换成 `/api/asr` 真值（备份 `voices.jsonl.bak-20261014`）。
⚠️ `描述` 是风格/内容标签（如「ニュース」「Taylor Swift」），**不代表音频实际念了什么**——按需试听确认。
⚠️ 改名后**旧名称形式失效**（`voice=<名称>` 找不到）；`voice=<id>` 与 `voice=<文件名>`（如 `zh_1`、`zh_2`）不受影响。

---

## 5. 响应头与错误码

同步模式的音频响应头（文件名/路径已 URL 编码，需 `decodeURIComponent` / `urllib.parse.unquote`）：

| 头 | 含义 |
|---|---|
| `X-Job-Id` | 任务 id（可用 `/api/jobs/<id>` 复核） |
| `X-Output-Name` | 相对路径，如 `音效生成/sfx_20261014_162059.wav` |
| `X-Output-Url` | `/outputs/音效生成/sfx_….wav`（可直接下载/播放） |
| `X-Output-Path` | 服务器绝对路径 |
| `X-Seconds` / `X-Elapsed` / `X-Takes` | 音频时长 / 任务耗时 / 条数 |

| 码 | 含义 |
|---|---|
| 400 | 参数问题：缺 `text`/`instruction`、参考音频路径不存在、`voice` 找不到、`speakers` 不是合法 JSON 数组 |
| 401 | 已设 `api_token` 但未带/带错 |
| 404 | 路由、任务或产物不存在 |
| 500 | 生成失败（`detail` 是引擎异常，如显存不足） |
| 504 | `wait=1` 超时；任务仍在跑，用 `GET /api/jobs/<id>` 继续查 |

异步/管理类接口：`GET /api/jobs`、`GET /api/jobs/<id>`、`GET /api/state`、`GET /api/outputs`（列产物）、`DELETE /api/outputs/<相对路径>`（删单个）、`DELETE /api/outputs`（清空，保留四个场景目录）、`GET /api/logs`、`GET /api/events`（SSE 日志）、`POST /api/models/load`、`POST /api/models/unload`。

---

## 6. 给 agent 的调用配方

```
1. 探活：GET /api/health → status=ok；GET /api/gen 拿能力清单（含每个端点的参数提示）
2. 选参考音色（克隆/对话用）：GET /api/tts/voices → 用 file 名（如 zh_1）或 id；或 POST /api/upload 传自己的音频
3. 需要逐字稿（多人对话 ref_text）：POST /api/asr {"path": "<音频路径>"} → text
4. 生成：GET/POST /api/gen/{tts|vg|sfx|ttsd}，wait=1（默认）直接拿 wav（**GET 的非 ASCII 参数必须百分号编码**，中文建议直接走 POST JSON 体）；
   长文本/多 take 建议 wait=0 拿 job_id，再 GET /api/jobs/<id> 轮询（2–5 s 间隔）
5. 落盘：把响应体写成 .wav（RIFF 头校验 b[:4]==b'RIFF'）；元数据读 X-Output-* 头
6. 验收：语音用 ASR（/api/asr 或外部）回读核对文本完整性；音效只能靠频谱/结构 + 人耳（ASR 对纯音效会幻觉）
```

**要点**：① 首次调用含 ~25 s 模型加载，`timeout` 别小于 300 s；② 一次只驻留一个模型，四个功能交替调用会反复加载；③ `seed` 固定才能复现，批量生产每个 take 显式给 seed；④ `seconds`/`tokens` 留 0；⑤ 产物同时会落盘在 `outputs\<场景>\`，需要时可复用而不必重生成。

---

## 7. 已知坑（都踩过）

| 现象 | 原因 / 处理 |
|---|---|
| 首次调用慢（~25 s）或报 504 | 模型加载时间被算进首次请求；把 `timeout` 放到 300–600 s，或先 `POST /api/models/load` |
| 生成到一半显存不足失败 | 16 GB 卡一次只驻留一个主模型；先 `POST /api/models/unload`，或把 `tokenizer_device` 设为 `"cpu"` |
| 多人对话克隆质量差 / 韵律怪 | `ref_text` 必须与参考音频**逐字一致**；没填逐字稿时日志会给出警告，可用「识别逐字稿」/`/api/asr` 转写 |
| 参考音频单声道/立体声混用曾报张量形状错误 | 已于 2026-10-14 修复（`_load_wav` 统一混单声道），现在任意采样率/声道/格式（wav/flac/mp3）都能混用 |
| `assets\voices\voices.jsonl` 的 `text` 曾**全表**与音频不符（2026-10-14 已修复） | 旧 30 行标注用 `/api/asr` 逐条复核，**30/30 全部对不上**（例：`zh_1` 旧写「欢迎关注模思智能…」，实际是「不管怎么样我和湯姆…」）；现表内 15 条 `text` 均为对应音频的 ASR 真值（备份 `voices.jsonl.bak-20261014`）⇒ 可直接当 `ref_text`；**自己的参考音频**仍须现场 `POST /api/asr` |
| 内置音色表原来「30 条」其实只有 14 个不同音频（2026-10-14 已去重为 15） | `en_4.wav` 曾被 17 行重复引用（名字却是 English News / 한국어 / Español / … / Türkçe，实际同一段英文新闻），`zh_2.wav` 存在却未被引用 ⇒ 已去重为 15 行（14 个原有音频 + `zh_2`），与目录 wav **一一对应**；语言旗与性别均按音频实测重标（依据见 §4）。旧的名字形式 `voice=<名称>` 不再匹配，`voice=<id>`（前 14 个未变）与 `voice=<文件名>` 有效 |
| curl 返回 400，响应体就一行 `Invalid HTTP request received.` | URL 里带了未编码的中文/空格（HTTP 客户端库会自动编码，curl 手拼 URL 不会），服务端 uvicorn h11 拒绝非 ASCII 请求行 ⇒ 用 `curl -G --data-urlencode "k=v"`，或把参数放 POST JSON body |
| 生成出的音频内容不对/像乱码，但 HTTP 200（静默） | 命令行里的非 ASCII 参数被本地代码页转码：Windows 中文控制台是 GBK/CP936，日志里会出现 `text=%d2%aa%c4%ee…`（GBK）而不是 UTF-8 的 `%E8%A6%81%E5%BF%B5…`。实测 GBK 传参生成的音频 ASR 回读是 "Except it's you"（本意「要念的文本」）⇒ 把 JSON 体存成 **UTF-8 文件**用 `curl --data-binary @body.json`，或改用客户端库（`-G --data-urlencode` 只解决「未编码被拒」，解决不了代码页转码） |
| 输出列表/产物看不到 | 产物按场景分子目录存放，用 `GET /api/outputs`（返回相对路径 + 场景）而非只看根目录 |
| 局域网能访问，担心被滥用 | 默认 `host: 0.0.0.0`：改 `127.0.0.1`，或设 `api_token` + 收紧 `cors_origins` |
| 想让 agent 自动发现本服务 | 本文件 + `D:\MossTTSD\docs\API.md`；技能侧见 `skill://text-to-audio-relay`（本地 MOSS 工作台条目） |

---

## 8. 机器可读摘要（供程序解析）

```json
{
  "service": "MOSS 语音工作台",
  "base_url": "http://127.0.0.1:17980",
  "health": "/api/health",
  "capabilities": "/api/gen",
  "openapi": "/openapi.json",
  "auth": {"type": "optional-header-or-query", "header": "X-API-Token", "query": "token", "config_key": "api_token"},
  "endpoints": {
    "tts":  {"path": "/api/gen/tts",  "methods": ["GET", "POST"], "required": ["text", "voice|prompt_audio"]},
    "vg":   {"path": "/api/gen/vg",   "methods": ["GET", "POST"], "required": ["text", "instruction"]},
    "sfx":  {"path": "/api/gen/sfx",  "methods": ["GET", "POST"], "required": ["prompt"]},
    "ttsd": {"path": "/api/gen/ttsd", "methods": ["POST", "GET"], "required": ["script", "speakers[]"]}
  },
  "common_params": {"wait": true, "timeout": 600, "seconds": 0, "seed": 0, "num_takes": 1},
  "encoding": "URL query values MUST be percent-encoded UTF-8 (non-ASCII rejected by the HTTP parser with 400 'Invalid HTTP request received.'); curl users: -G --data-urlencode, or send params in a POST JSON body",
  "response": {"sync": "audio/wav bytes", "headers": ["X-Job-Id", "X-Output-Name", "X-Output-Url", "X-Output-Path", "X-Seconds", "X-Elapsed", "X-Takes"]},
  "output_dirs": ["单人配音", "音色设计", "多人对话", "音效生成"],
  "aux": {"/api/upload": "multipart files -> path", "/api/asr": "{\"path\": \"...\"} -> text", "/api/tts/voices": "15 presets (id|name|filename)", "/api/jobs/{id}": "poll"}
}
```
