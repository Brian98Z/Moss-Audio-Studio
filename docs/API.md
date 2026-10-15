# 本地接口（给别的应用调用）

服务地址：`http://127.0.0.1:17980`（启动 GUI 客户端即随启；或双击 `start_server.bat` 单独启动）。

- 交互式文档（可直接试）：<http://127.0.0.1:17980/docs> ｜ 机器可读：`/openapi.json` ｜ 能力清单：`GET /api/gen`
- 四个功能共用一条 GPU 单线程队列：调用会**排队**执行，不会并发抢显存；引擎会自动加载所需模型并卸载上一个（首次约 25 s）。

## 一分钟上手

```bash
# 音效：直接返回 wav 字节
curl -o rain.wav "http://127.0.0.1:17980/api/gen/sfx?prompt=rain%20on%20a%20tin%20roof&seconds=5"

# 单人配音（内置音色用文件名/id/名称都行：zh_1 / voice-2 / 🇨🇳%20磁性男声）
curl -o hello.wav "http://127.0.0.1:17980/api/gen/tts?text=%E4%BD%A0%E5%A5%BD&voice=zh_1"

# 浏览器地址栏直接粘贴上面这两条 URL 也能出音频（等价于「用链接调用」）
```

## 四个功能

| 功能 | 路由 | 关键参数 | 说明 |
|---|---|---|---|
| 单人配音 / 音色克隆 | `GET`/`POST` `/api/gen/tts` | `text`, `voice`（内置音色 id/名称/文件名）或 `prompt_audio`（服务器上音频路径）, `seed`, `seconds`, `num_takes` | 参考音频 3–10 s 最稳 |
| 音色设计 | `GET`/`POST` `/api/gen/vg` | `text`, `instruction`（音色描述）, `seed`, `seconds`, `num_takes` | 不需要参考音频 |
| 音效生成 | `GET`/`POST` `/api/gen/sfx` | `prompt`, `seconds`, `tokens`, `seed`, `num_takes` | 1 秒 ≈ 12.5 audio token |
| 多人对话 | `POST` `/api/gen/ttsd`（`GET` 亦可，见下） | `script`（`[S1]`/`[S2]` 轮次）, `speakers[{tag, ref_audio, ref_text}]`, `max_minutes`, `seed`, `num_takes` | 每位说话人：参考音频 + **该段逐字稿**（不一致会拖坏韵律，可用 `/api/asr` 转写） |

## 两种调用方式

| 模式 | 参数 | 返回 |
|---|---|---|
| **同步**（默认） | `wait=1`，可加 `timeout=600` | `Content-Type: audio/wav` 的原始字节；元数据在响应头（见下） |
| **异步** | `wait=0` | 立刻 `{"job_id":"...","status":"pending","poll":"/api/jobs/<id>"}`；轮询 `GET /api/jobs/<id>` 到 `status=done`，再从 `result.outputs[0].name` 取 `/outputs/<name>` |

响应头（同步模式；文件名与路径已 URL 编码，需 `decodeURIComponent`）：

| 头 | 含义 |
|---|---|
| `X-Job-Id` | 任务 id（可在 `/api/jobs/<id>` 复核） |
| `X-Output-Name` | 相对产物路径，如 `音效生成/sfx_20261014_161346.wav` |
| `X-Output-Url` | `/outputs/音效生成/sfx_....wav`（可直接下载/播放） |
| `X-Output-Path` | 服务器上的绝对路径 |
| `X-Seconds` / `X-Elapsed` / `X-Takes` | 音频时长 / 任务耗时 / 条数 |

## 示例

### Python（标准库即可）

```python
import urllib.parse, urllib.request

def tts(text, voice="zh_1", base="http://127.0.0.1:17980"):
    url = f"{base}/api/gen/tts?" + urllib.parse.urlencode({"text": text, "voice": voice, "seed": 3})
    with urllib.request.urlopen(url, timeout=600) as r:
        return r.read(), r.headers          # wav 字节 + 响应头

audio, headers = tts("你好，这是接口调用。")
open("out.wav", "wb").write(audio)
print(headers["X-Output-Name"], headers["X-Seconds"])
```

### 多人对话（POST JSON）

```python
import json, urllib.request

payload = {
    "script": "[S1] 大家好，欢迎来到本期节目。[S2] 今天聊聊本地语音模型。",
    "speakers": [
        {"tag": "[S1]", "ref_audio": r"D:\MossTTSD\assets\voices\zh_1.wav", "ref_text": "参考音频的逐字稿"},
        {"tag": "[S2]", "ref_audio": r"D:\MossTTSD\assets\voices\zh_6.wav", "ref_text": "第二位的逐字稿"},
    ],
    "max_minutes": 2, "seed": 1234, "wait": True,
}
req = urllib.request.Request("http://127.0.0.1:17980/api/gen/ttsd",
                            data=json.dumps(payload).encode(),
                            headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=900) as r:
    open("dialogue.wav", "wb").write(r.read())
```

### 网页里调用（JS，跨域已开）

```js
// 简单请求：CORS 已允许任意来源（见「鉴权与跨域」）
const res = await fetch('http://127.0.0.1:17980/api/gen/vg?' + new URLSearchParams({
  text: '你好，我在网页里调用本地语音工作台。',
  instruction: '温暖平静的成年男声，语速中等',
  seconds: 0,
}));
const blob = await res.blob();
document.querySelector('audio').src = URL.createObjectURL(blob);
console.log(res.headers.get('X-Output-Name'));   // 需要在 expose_headers 里，已配好
```

### 参考音频从哪来

1. **内置音色**（15 条，无需上传）：`GET /api/tts/voices` 拿 `id` / `name` / `path`，`voice=` 传 id、名称或文件名；`GET /api/tts/voice-audio/<id>` 可试听（只收 id）。
2. **自己的音频**：`POST /api/upload`（multipart，字段名 `files`，可多个）→ 返回 `{"files":[{"path": "D:\\MossTTSD\\uploads\\...wav", ...}]}` → 把 `path` 传给 `prompt_audio` / `ref_audio`。
3. 也可以直接给服务器上已有的音频路径（`assets\voices\*.wav` 等）。

### 顺带：参考音频转逐字稿

`POST /api/asr {"path": "<音频路径>"}` → `{"text": "...", "language": "zh", "duration": 6.87, "elapsed": 2.96}`（本地 whisper-small，CPU，离线；只允许 `uploads\` 与内置音色目录）。

## 产物落盘

任务完成后音频会保存在 `outputs/` 下：四个语音生成场景直接写入 `outputs/<场景>/`；Stems 与 Denoise 按任务分目录，分别为 `outputs/Stems/<job_id>/` 和 `outputs/Denoise/<job_id>/`。同步响应里也直接给出字节，所以外部程序**不需要**再读文件。

- 列出全部产物：`GET /api/outputs`
- 下载/播放：`GET /outputs/<X-Output-Url 里的相对路径>`
- 删除单个：`DELETE /api/outputs/<相对路径>`；清空：`DELETE /api/outputs`
- 一键清理按钮与上面这个 DELETE 同义（只删文件，不删除必要的场景目录）

## 鉴权与跨域

- **鉴权**：`server\config.json` 里 `"api_token": ""`（默认）= 不校验，本机脚本直接调。设成任意字符串后，`/api/gen/*` 要求带 `?token=<值>` 或请求头 `X-API-Token: <值>`，否则 `401`。
- **跨域（CORS）**：默认 `"cors_origins": ["*"]`，并 `expose_headers` 了全部 `X-*` 响应头（浏览器里 `res.headers.get('X-Output-Name')` 才读得到）。只想放行特定页面时改成 `["http://localhost:3000"]` 这类列表。
- ⚠️ 服务默认监听 `0.0.0.0`（局域网可访问）。要只限本机，把 `config.json` 的 `host` 改成 `127.0.0.1`；对外网暴露时请务必设置 `api_token`。

## 错误码

| 码 | 含义 |
|---|---|
| 400 | 参数问题（如缺 `text`/`instruction`、参考音频路径不存在、`voice` 找不到、`speakers` 不是合法 JSON 数组） |
| 401 | 已设 `api_token` 但未带/带错 token |
| 404 | 路由或任务/产物不存在 |
| 500 | 生成失败（`detail` 里是引擎的异常信息，如显存不足） |
| 504 | `wait=1` 等待超过 `timeout`：任务仍在后台跑，用 `GET /api/jobs/<id>` 继续查 |
| 409 | 缺少运行环境返回 `{"error":"need_env", ...}`；缺少资源时返回 FastAPI `detail` 包装后的 `need_asset` 对象（见下文）。 |

## 模型下载 / 下载中心（模型与组件）

页面 `/downloads`（工作台「设置 → 模型下载」页签内嵌；独立打开时标题为「下载中心」）与独立界面
`tools\downloader_ui.py`（仅 stdlib，默认端口 17990，可由客户端启动器拉起）共用同一套接口。落地位置固定为
**安装目录**，不接受自定义路径；下载完成即按上游哈希校验并置 `verified=true`，条目按状态显示「已就绪·已校对」
或「已就绪·未校对」（`verified` 是后端内存态，重启后回到未校对，重跑校对即可）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/downloads` | `items[]`（`bytes`/`present`/`present_bytes`/`shared_only`/`size_matches`/`status`/`done_bytes`/`speed_bps`/`eta_s`/`verified`/`target`/`group`/`enables`）、`disk.free_bytes`、`disk.root`、`required_missing`、`active` |
| POST | `/api/downloads/start` | `{"ids":[...]}` → `{"started":[...],"skipped":[...]}`。全局同时只跑 1 个条目（条目内 4 连接）；已有/磁盘不足会跳过或报错 |
| POST | `/api/downloads/cancel` | `{"ids":[...]}`：在 chunk 边界停下并保留 `.part`，再次 start 即断点续传 |
| POST | `/api/downloads/verify` | `{"ids":[...]}`：逐文件重算 sha256（demucs 用前 8 位十六进制；ffmpeg 用必需文件齐全）并写回 `verified` |

体积语义：`bytes` 是**下载包**体积（界面头部显示「下载包 X」），`present_bytes` 是磁盘实际占用（界面显示「本机 Y」，目录为空时为 0）。`shared_only=true` 表示该条目靠本机已有权重即可用（共享 codec、已有 int8 产物），此时不再显示 0 字节；`size_matches=false` 表示磁盘那份与下载包体积不同（例如本机是全量 ffmpeg 构建），两者都只是提示，不改变 `present`/`verified` 判定。已落盘且不在下载中的条目 `done_bytes` 归零，避免残留 `.part` 被显示成下载进度。

缺件时功能接口返回 HTTP 409 `need_asset`。FastAPI 会将 `HTTPException` 的字典内容放入 `detail` 字段，实际 JSON 为 `{"detail":{"code":"need_asset","asset":"<id>","message":"..."}}`——把 `asset` 转成 `/downloads?need=<id>` 链接即可。

```bash
curl -s http://127.0.0.1:17980/api/downloads | python -m json.tool | head -40
curl -s -X POST -H 'Content-Type: application/json' -d '{"ids":["whisper-small"]}' \
     http://127.0.0.1:17980/api/downloads/start
```

## 页面用的接口（同样可用，但更啰嗦）

`POST /api/{tts|vg|sfx|ttsd}/generate` 立即返回 `{"job_id": ...}`，客户端再轮询 `/api/jobs/<id>`；另有 `/api/state`、`/api/models/load`、`/api/models/unload`、`/api/logs`、`/api/events`（SSE）等。外部程序一般直接用本文档的 `/api/gen/*` 就够了。
`GET /api/state` 返回 `env` 字段：`ready`、`interpreter`、`torch`、`cuda`、`cudnn`、`system_cudnn_conflict`、`missing`，反映后端启动预检状态。生成接口缺少运行环境时返回 HTTP 409，包含 `error: "need_env"` 与准备提示。缺少可选资源时返回 HTTP 409 `need_asset`；FastAPI 会将 `HTTPException` 内容包装进 `detail`，实际 JSON 为 `{"detail":{"code":"need_asset","asset":"…","message":"…"}}`。

独立标准库环境准备界面（`python tools/downloader_ui.py`）使用自己的接口：`GET /api/env/status`、`GET /api/env/log`、`POST /api/env/start`、`POST /api/env/cancel`。这些接口由独立 UI 服务提供（默认端口 17990），不是工作台后端路由。

## 本地六轨分离（Demucs）

`POST /api/stems/separate` 接收 JSON `{"path":"<上传文件路径>"}`，返回 `{"job_id":"..."}`。先用现有 `POST /api/upload` 上传音频，再将返回的 `files[].path` 传入；服务只接受 `uploads/` 根目录内的现有文件。分离任务进入与 TTS 共用的单 GPU 队列，执行前卸载 MOSS 引擎；无需云服务。

轮询 `GET /api/jobs/<job_id>`，完成后 `result` 包含 `outputs`（`stem`、`name`、`url`）、`seconds`、`sample_rate`（44100）、`archive_url`。`params.progress` 为 0–1 进度。六个 stem：`drums`、`bass`、`other`、`vocals`、`guitar`、`piano`；`other` 是其它伴奏声部，不保证是纯旋律。WAV 输出为双声道 44100 Hz，路径 `/outputs/Stems/<job_id>/<stem>.wav`。一次下载 ZIP：`GET /api/stems/archive/<job_id>`。

GUI：工具页 `/tools` 先显示 Stems 图标入口，点击进入 `/tools/stems`；详情页「返回工具 / Back to Tools」返回入口页并保留全局语言。支持文件选择、拖入、分离进度、六轨试听与单轨 WAV/整包 ZIP 下载。模型落在 `models/demucs/5c90dfd2-34c22ccb.th`；处理采用 7 秒重叠分块，结果音轨时长一致。

工具页另有「人声分离 / Vocal separation」独立入口。API 同一端点传 `{"path":"<上传文件路径>","mode":"vocals"}`，仅输出 `vocals.wav` 与 `instrumental.wav`；默认 `mode="six"` 保持六轨分离。伴奏由原混音减去提取人声得到，使用同一个本地 Demucs 模型，不是另一套云服务；人声与伴奏可能有模型分离残留。两轨可分别试听下载，或下载 ZIP，详情页保留返回工具功能。

## 本地音频降噪（MossFormer2_SE_48K）

`POST /api/denoise/apply` 接收 JSON `{"path":"<上传文件路径>","mix":1.0}`，返回 `{"job_id":"..."}`。同样先用 `POST /api/upload` 上传，再把返回的 `files[].path` 传入；服务只接受 `uploads/` 根目录内的现有文件。`mix` 是降噪强度，取值 0–1（默认 `1.0` = 全降噪；越小混回越多的原始声音），越界返回 422。

轮询 `GET /api/jobs/<job_id>`，完成后 `result`：

| 字段 | 含义 |
|---|---|
| `outputs[]` | 每条含 `stem`（固定 `denoised`）、`name`（`Denoise/<任务ID>/<原文件名>_denoised.wav`）、`label`、`url`（`/outputs/<name>`，可直接播放/下载） |
| `seconds` | 输出时长（秒） |
| `sample_rate` | 输出采样率，**与输入一致**（44.1 kHz 进就 44.1 kHz 出；内部统一按 48 kHz 推理后再重采样回原采样率） |
| `mix` / `gain` | 实际使用的降噪强度 / 防削顶整体增益（未触顶恒为 1.0） |
| `device` / `elapsed` | 推理设备（`cuda`/`cpu`）与处理耗时（秒） |

`params.progress` 为 0–1 进度。任务进入与 TTS 共用的同一 GPU 队列，但**不卸载**当前语音模型（降噪是独立于 MOSS 的旁路，卸载只会拖长下一次配音的冷启动；显存不足时引擎自动退回 CPU）。

音频处理约定：单声道进单声道出、立体声进立体声出（**逐通道**处理，不做单声道下混）；超过 20 秒按 4 秒窗、3 秒步长分段推理后拼接，首尾不丢样本；峰值超过 -1 dBFS 时整体衰减。产物删除与 Stems 一致：正在跑的任务不会让接口删掉对应输出。输入解码走工程内 ffmpeg，wav/mp3/flac/m4a 等均可。

GUI：工具页第三张卡片进入 `/tools/denoise`，页面「返回工具 / Back to Tools」保留全局语言；支持文件选择/拖入、0–100% 强度滑块、进度、原始与降噪结果 A/B 试听、结果下载。

权重核实与补下：`python tools/download_denoise_models.py --check`（只校验现状）或 `--force`（重新下载，curl 断点续传 + sha256 校验）。选型对比、四档实测与验收口径见 `docs/DENOISE.md`。
