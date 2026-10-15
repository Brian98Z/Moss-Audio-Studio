# 人声降噪（Tools 第三工具）：调研、选型与实现口径（2026-10-15）

本文是「工具箱增加人声降噪」的调研留档：所有数字均为**本机实测**（脚本与原始日志属临时过程文件，已按约定清理；结论以本文为准，复现命令见各节）。相关的临时目录清理见文末「过程文件」。

---

## 1. 选型结论

| 优先级 | 方案 | 形态 / 体积 | 许可 | 关键依据 |
|---|---|---|---|---|
| **采用（默认引擎）** | **MossFormer2_SE_48K**（ClearerVoice-Studio） | 权重 221,552,019 B（211 MiB）+ vendored 架构代码 78,529 B + `rotary_embedding_torch` 17,423 B | Apache-2.0（代码与权重） | 四档实测**质量与透明性第一**：噪声用例 SI-SDR 增益 +10.91 dB、干净输入 SI-SDR 43.14 dB、CER 0.000–0.029；纯 Python 集成（torch 已是工程依赖，无需外部二进制）；CPU 0.111 s/音频 s，CUDA 0.0397 s/音频 s，显存峰值仅 **486 MB** |
| 备选 | DeepFilterNet 3（预编译 CLI） | `deep-filter.exe` 26,912,256 B + 权重 7,983,136 B | MIT / Apache-2.0 双许可 | 噪声底压制最强（−57.7 dB）、干净输入同样温和（33.60 dB）、RTF 0.092（189.6 s 实测）；代价是外部二进制 + 需镜像取件，且低电平段有数字静音倾向 |
| 轻量档 | DFSMN 48 kHz 因果 ANS（`iic/speech_dfsmn_ans_psm_48k_causal`） | 权重 6,032,057 B + 代码约 174 KB | Apache-2.0 | RTF **0.007**（最快）、CER 最好（0.012）、纯 Python；但干净输入改动明显（12.64 dB）且有 −0.9~−4.1 dB 电平偏移 |
| 兜底 | ffmpeg 内建 `arnndn`（RNNoise） | 权重 299,693 B | 代码 BSD-3 / **权重许可未定** | 零新增依赖、RTF 0.025、真实素材上 +6.12 dB；**权重许可存在分发风险**（见 §6） → 不作为交付路径 |

**被淘汰**（理由见 §5）：ZipEnhancer(16 kHz)、DPDFNet、UVR/FoxJoy VR-arch、Resemble Enhance、`noisereduce`、Demucs/MDX 当降噪器、纯 ffmpeg DSP 作为主引擎。

---

## 2. 本机环境事实

- 运行时：`runtime/venv`（torch 2.10.0+cu130、torchaudio 2.10、soundfile 0.14、scipy 1.18.1、numpy 2.5.4、demucs 4.1.0）+ 覆盖层 `runtime/pylibs`（transformers 5.19、faster-whisper 1.2.1、ctranslate2、onnxruntime 1.31.0、av 19）。**注**：这是评测当时的双栈状态；现已合并为 `runtime/requirements.txt` 一份单环境清单（版本不变）。
- GPU：RTX 5070 Ti，17.07 GB（实测空载余量 ~16.3 GB）。
- FFmpeg：`runtime/ffmpeg`（8.1.2-full），含 `afftdn` / `anlmdn` / `arnndn` / `adeclick` / `adeclip` / `loudnorm` / `speechnorm`（111 个 A→A 滤镜）。
- ASR（用于客观核对）：`models/whisper-small`（CTranslate2，CPU int8）+ faster-whisper；**注意**本机 `av` 与 faster-whisper 1.2.1 不兼容（`av.open` 不接受 `metadata_errors`），必须自行用 soundfile 解码后传 16 kHz numpy 数组（与 `server` 侧现做法一致）。
- 磁盘：D: 23 GB 可用 / C: 35 GB 可用 ⇒ 权重体积需有预算意识（221 MB 可接受）。
- `onnxruntime` 仅 `CPUExecutionProvider`（无 CUDA EP）。

---

## 3. 权重与依赖的获取通道（本机实测，决定方案可行性）

| 通道 | 状态 | 说明 |
|---|---|---|
| ModelScope（`www.modelscope.cn`） | ✓ | curl 与 Python urllib 均可用；工程既有 `tools/download_models.py` 即用此通道。API：`/api/v1/models/<repo>/repo/files?Revision=master&Recursive=true`（列文件）、`/api/v1/models/<repo>/repo?Revision=master&FilePath=<urlencoded>`（取文件） |
| PyPI 镜像（阿里云 / 清华 / 腾讯） | ✓ | 实测 `pip download -i https://mirrors.aliyun.com/pypi/simple/` 10.3 MB/s；`modelscope`、`clearvoice`(0.1.2，含 MossFormer2 架构代码)、`dpdfnet`、`rotary_embedding_torch` 均可取 |
| raw.githubusercontent / api.github.com / codeload | ✓（大文件会中断） | DFN3 权重 `DeepFilterNet3_onnx.tar.gz` 7,983,136 B 取回成功 |
| **gh-proxy.com / ghfast.top** | ✓ | GitHub **release 资产**必须走这里（实测 `deep-filter-0.5.6-x86_64-pc-windows-msvc.exe` 26,912,256 B 完整取回） |
| huggingface.co / hf-mirror.com | ✗ | TLS 握手超时/EOF ⇒ HF-only 权重的方案在本机不可行 |
| pypi.org 直连 | ✗ | 握手超时（须走镜像） |
| objects.githubusercontent.com | ✗ | release 直链取回 0 字节 ⇒ 必须走 gh-proxy |

---

## 4. 实测数据

### 4.1 四档同口径对比（48 kHz；5 类合成噪声各 5 dB SNR + 干净输入；SI-SDR 相对干净参考，CER 相对干净文件 ASR 文本）

| 方法 | ΔSI-SDR 均值 | 噪声底下降 | CER 均值 / 最差 | 干净输入 SI-SDR | 干净输入 CER |
|---|---|---|---|---|---|
| ffmpeg `highpass+afftdn` | −1.43 dB | 6.0 dB | 0.023 / 0.029 | 5.96 dB | 0.029 |
| ffmpeg `highpass+arnndn` | −2.08 dB | 27.1 dB | 0.074 / **0.314** | 3.28 dB | 0.000 |
| ffmpeg `arnndn`（单独）※ | +6.12 dB | 26.0 dB | 0.029 / 0.114 | 14.6 dB | 0.000 |
| DFSMN 48 kHz | +8.62 dB | 33.5 dB | **0.012** / 0.029 | 12.64 dB | 0.000 |
| DeepFilterNet 3 | +8.53 dB | **57.7 dB** | 0.035 / 0.057 | 33.60 dB | 0.029 |
| DeepFilterNet 3（`-a 24`） | +8.38 dB | 44.1 dB | 0.029 / 0.057 | 34.18 dB | 0.029 |
| **MossFormer2_SE_48K** | **+10.91 dB** | 50.5 dB | 0.017 / 0.029 | **43.14 dB** | 0.000 |

※ 来自 4.2 主矩阵（该表口径为 12 用例）。

逐用例 SI-SDR（dB）：

| 用例 | 未降噪 | DFSMN | DFN3 | **MF2** |
|---|---|---|---|---|
| 白噪 5 dB | 5.0 | 15.9 | 16.1 | **16.7** |
| 粉噪 5 dB | 5.0 | 13.5 | 10.5 | **14.6** |
| 棕噪 5 dB | 5.0 | 9.7 | 6.1 | **10.6** |
| 工频 50 Hz 5 dB | 5.0 | 14.2 | 17.5 | **18.6** |
| 脉冲点击 5 dB | 5.0 | 14.8 | 17.5 | **19.0** |
| 干净输入 | 158.0 | 12.6 | 33.6 | **43.1** |

### 4.2 ffmpeg 家族主矩阵（48 kHz；12 用例 × 8 方法）

| 方法 | ΔSI-SDR 均值 | 噪声底下降 | CER 均值 | 最差 CER | 干净输入 SI-SDR |
|---|---|---|---|---|---|
| `afftdn`（轻） | +0.12 dB | 0.4 dB | 0.031 | 0.143 | 50.51 dB |
| `afftdn`（重） | +0.05 dB | 0.3 dB | 0.034 | 0.143 | 54.56 dB |
| `anlmdn` | +0.00 dB | 1.1 dB | 0.039 | 0.143 | 60.41 dB |
| `highpass+afftdn` | −1.54 dB | 6.0 dB | 0.026 | 0.057 | 5.96 dB |
| `highpass+afftdn+anlmdn` | −1.49 dB | 9.0 dB | 0.047 | 0.114 | 5.96 dB |
| `arnndn` | **+6.12 dB** | 26.0 dB | 0.029 | 0.114 | 14.57 dB |
| `highpass+arnndn` | −2.06 dB | 29.3 dB | 0.057 | **0.314** | 3.28 dB |

### 4.3 速度（CPU，实测）

| 方案 | 耗时 | RTF | 备注 |
|---|---|---|---|
| `arnndn` | 60 s 音频 → 1.50 s | 0.025 | 最快 DSP/DNN 滤镜 |
| `afftdn` / `anlmdn` | 60 s → 6.45 / 5.22 s | 0.108 / 0.087 | |
| `highpass+afftdn` / `+anlmdn` | 60 s → 12.98 / 2.74 s | 0.216 / 0.046 | |
| DFSMN 48 kHz | RTF 0.007（CPU） | 0.007 | CUDA 更快但短音频被开销主导（0.136） |
| DeepFilterNet 3 | 189.6 s → 17.38 s | 0.092 | 输出时长与输入完全一致 |
| **MossFormer2_SE_48K** | 前向：CPU 0.111 / CUDA 0.0397 s per 音频 s（长素材稳态） | 0.111 / 0.0397 | CUDA 显存峰值 486 MB；**7.9 s 短素材复测**：CUDA 0.111、CPU 0.086（短素材被 CUDA 初始化开销主导），25 s 素材 CUDA 0.047 |

### 4.4 关键行为特性（写入实现约束）

1. **不要在高通/去点击之后接 `arnndn` 或 DFN3**：实测把 SI-SDR 从 +6.1/+8.5 打成 −2.1/−2.1，脉冲噪声场景 CER 从 0.029 → **0.314**。工频嗡鸣与脉冲点击由神经模型自身处理即可（DFN3 各 +12.5 dB；MF2 18.6/19.0 dB）。
2. **DFN3 只压噪声、不动语音**（独立复核）：5 dB SNR 下语音活跃窗（p90）仅变 0.8–1.0 dB，而噪声底降 41–51 dB；干净输入 p90 −14.3 → −14.5 dBFS、整体 RMS −17.8 → −18.0 dBFS。
3. **DFN3 会在低电平段产生数字静音**：7.9 s 干净素材上合计 1.097 s、最长 0.230 s（起音 0.067→0.097 s、收尾 7.844→7.874 s，位置基本不变）⇒ 需要 `-a/--atten-lim-db` 限幅。
4. **DFN3 输出增益可 >1**（实测触发 1.019–1.075 的 clipping 警告）⇒ 落盘前必须共享衰减。
5. **DFN3 立体声逐通道处理**（输出两通道仍不相关、RMS 一致），输出为 **PCM_16**。
6. **`arnndn` 是 48 kHz-only 滤镜**（`sample_rates[] = {48000, -1}`）：44.1 kHz 素材会被 ffmpeg 静默重采样，导致逐样本指标失真 ⇒ 评测与实现都必须先统一到 48 kHz。
7. **16 kHz 模型的带宽代价**（ZipEnhancer 实测）：8–20 kHz 频带能量占比 −27.0 dB → **−50.7 dB**，10 kHz 高通后 RMS 再降 5.65 dB ⇒ 有效带宽被压到约 8 kHz。

---

## 5. 各方案细节与淘汰理由

| 方案 | 事实 | 结论 |
|---|---|---|
| **ZipEnhancer 16 kHz**（`iic/speech_zipenhancer_ans_multiloss_16k_base`，9.8 MB ONNX / 8.42 MB pytorch） | 其 ONNX 导出**在 onnxruntime 1.31 下不可用**（图内含 NCHWc `ReorderOutput` contrib 节点，报 `Input channels must match the NCHWc block-aligned channel count`，关闭图优化亦复现）；用 vendored 架构 + pytorch 跑通后：**CPU RTF 18.3**，24 s 音频在 CUDA 上 **OOM**（尝试分配 43.30 GB），且把有效带宽压到 8 kHz | **淘汰**：CPU 不可用、GPU 长音频 OOM、16 kHz 带宽损失 |
| **DPDFNet**（Ceva，Apache-2.0 代码与权重） | `dpdfnet` 0.6.0 wheel 可从镜像获取（25 kB 纯 Python），但**权重只在 HuggingFace**（本机不可达），仓库 `onnx_model/` 只有导出脚本 | **淘汰**：权重不可获取 |
| **UVR / MDX-Net / VR-arch（FoxJoy）DeNoise/De-Echo** | 127.1 MB（DeNoise、De-Echo 各）与 223.7 MB（DeEcho-DeReverb）；MDX-Net/UVR 为 MIT，但**降噪/去回声模型没有公开的客观质量数据**；批尺寸固定 1 | **淘汰**：体积大、质量未证、需自实现推理 |
| **Resemble Enhance** | MIT，但 48 kHz 对比中 PESQ 2.84（该组最低），增强器是 CFM 扩散模型（慢） | **淘汰** |
| **`noisereduce`** | MIT、无权重；公开资料显示其伴随论文为方法性，无与神经模型的对比数据；文档说明未提供噪声样本时会以信号自身估计噪声 | **不采用**（未本机实测，仅依公开资料） |
| **Demucs / MDX 当降噪器** | 公开对比中 DEMUCS（33.53 M 参数 / 7.70 GMACs）PESQ 2.27，劣于 DeepFilterNet2 且算力更大 | **不采用**（Stems 用途不变） |
| **DeepFilterNet 3** | 见 §1；MIT/Apache-2.0 双许可；权重 7.98 MB；预编译 exe 26.9 MB（Windows） | **备选**（质量第二、抑噪最强，但需外部二进制） |
| **DFSMN 48 kHz** | 6.03 MB、因果、纯 Python；RTF 0.007 | **轻量档**（若不想加载 221 MB 大模型） |
| **ffmpeg DSP（`afftdn`/`anlmdn`）** | 噪声底略降（0.3–1.1 dB）但 SI-SDR 中性；`afftdn` 的 musical noise 是上游已知问题（其 `gain_smooth` 选项即为缓解） | 仅作轻度修整，不作主引擎 |

---

## 6. 风险与缓解

| 风险 | 实测/来源 | 缓解 |
|---|---|---|
| RNNoise `.rnnn` 权重**许可未定** | xiph/rnnoise issue #284 未答复；`arnndn-models`/`GregorR` 仓库无 LICENSE；各发行版认定不一（Fedora=CC0、Debian/Gentoo=BSD-3） | 不作为交付路径；若要保留，需先向上游确认 |
| DFN3 在低电平段压成数字静音 | 7.9 s 干净素材合计 1.097 s、最长 0.230 s | 用 `-a/--atten-lim-db`（如 24 dB）限幅；交付前用真实素材做人耳复核 |
| DFN3 输出增益 >1 | 实测 1.019–1.075 | 落盘前统一共享衰减至 −1 dBFS（沿用 Stems 的 gain 约定） |
| MF2 分块接缝未验证 | 调研期用的是自拟 4 s 块 / 1 s 重叠 | 实现改用**官方参数**（20 s 块 + 4 s 解码窗）并专门核验接缝 |
| DFSMN 输出电平偏移 | −0.9 ~ −4.1 dB | 需要时加后置增益补偿；或改用 MF2 |
| 16 kHz 模型的带宽损失 | ZipEnhancer：高频占比 −23.7 dB | 不采用 16 kHz 模型 |
| 客观指标口径局限 | SI-SDR 对线性相位变化敏感（`highpass` 行数值偏悲观）；CER 参考文本来自干净文件的 ASR（无人工标注） | 结论以**方法间相对比较**为准；门槛用 §7 的区间值 |
| 本机网络受限 | HF/pypi 直连不可达 | 权重走 ModelScope / PyPI 镜像；GitHub 资产走 gh-proxy |

---

## 7. 验收标准（实现完成后按此核对）

| 项 | 门槛 | 当前 MF2 实测 |
|---|---|---|
| 5–10 dB SNR 合成噪声 SI-SDR 增益 | ≥ +6 dB | +10.91 dB |
| 噪声底下降（最静 0.3 s 窗） | ≥ 25 dB | 50.5 dB |
| 干净输入 SI-SDR（过度抑制） | ≥ 30 dB | 43.14 dB |
| CER 相对未降噪不劣化 | ≤ +0.02 | 0.017（干净输入 0.000） |
| CPU RTF | ≤ 0.3 | 0.111 |
| 输出 | 48 kHz、通道数与输入一致、峰值 ≤ −1 dBFS、时长一致 | 端到端实测通过（见 §7.1） |
| 真实素材人耳试听 | 无金属音/气息被削/接缝 | 待人工确认 |

> 真实输入画像（本机素材实测）：用户录音与上传（`assets/voices/me.wav`、`uploads/*_me.wav`、`assets/reference/*`）噪声底约 −30 dBFS、**SNR ≈ 10–15 dB** ⇒ 降噪确有真实需求；同时存在大量已很干净的素材（p10 达 −45～−85 dBFS），"干净输入不该被改动"是重要约束（这也是 MF2 干净输入 43.14 dB 排第一的价值所在）。

### 7.1 端到端实测记录（2026-10-15，实现完成后）

走真实 HTTP（`POST /api/upload` → `POST /api/denoise/apply` → 轮询 `/api/jobs/<id>` → 取 `/outputs/...`）与真实浏览器（工具页 → 详情页上传 → 任务 → 试听/下载）：

| 项 | 实测 |
|---|---|
| 48 kHz 合成噪声（7.9 s 单声道） | 噪声底 −24.2 → **−76.8 dBFS**（下降 52.6 dB）；SI-SDR **4.99 → 16.69 dB**（+11.7 dB，与 §4.1 的 +10.91 同口径）；峰值 −2.5 dBFS |
| 采样率保持 | 48 kHz 进 → `sample_rate` 48000 出；44.1 kHz 进 → 44100 出（样本数 348390 与输入完全一致） |
| 通道数 | 单声道 → 1 通道；立体声 → 2 通道且两通道各自降噪（−76.8 / −76.6 dBFS） |
| 时长 | 379200 / 348390 样本与输入逐样本一致，无补齐或截断 |
| dry/wet | `mix=0.35` 的结果与 `0.35×湿 + 0.65×干` 最大偏差 **5×10⁻⁵**；噪声底 −27.9 dBFS，位于全降噪（−76.8）与原始（−24.2）之间 |
| 速度 | CUDA 25 s 素材 RTF **0.047**、7.9 s 素材 0.111（短素材被 CUDA 初始化主导）；CPU 7.9 s 素材 RTF **0.086**；7.9 s 音频端到端任务耗时 1.5 s（含模型加载 0.5 s） |
| >20 s 分段路径（25 s 素材） | 严格零样本 **0 个**、最长连续零 **0 样本**、输出时长精确一致；逐秒噪声底均低于输入（最差一秒仍低 2.3 dB），无接缝 |
| 干净输入（44.1 kHz 内置音色） | 最静窗 p10 −64.2 → −65.4 dBFS（未被大幅改动） |
| 负例 | 越界路径 → 400；`mix=1.7` → 422；不存在的文件 → 400；任务列表 `kind=denoise` 可见 |
| GUI（真实浏览器） | 中文/英文两套界面渲染正常，卡片与返回链接携带语言与主题参数；上传 mp3 → 强度 40% → 结果页汇总「时长 0:07 / 采样率 48 kHz / 处理用时 0.6 s」，原始与降噪双播放器可播、下载链接可用；控制台无报错 |
| 权重工具 | `tools/download_denoise_models.py --check` 通过：221,552,019 B，sha256 与元数据一致 |
| 回归 | `integration/full_functional_test.py` 新增第 5 节（降噪 + 页面 + 负例，自造素材不依赖临时目录），与四模型体检同跑通过 |

未复核项：真实人声素材的听感（金属音/气息/接缝）仍需人工确认；引擎在显存不足时的 CPU 退避路径未在真实 OOM 下触发过（代码路径为 `torch.cuda.is_available()` 判定 + 异常退避）。

---

## 8. 实现方案（口径）

**形态**：与 Stems 平级的第三张工具卡片 → `/tools/denoise` → 上传/拖入 → `JobRunner` 队列 → 产物落 `outputs/Denoise/<job_id>/`。

- 引擎 `server/denoise.py`：
  - 解码：soundfile 优先、ffmpeg 兜底（复用 `stems.py` 的做法）；统一 48 kHz；**逐通道处理**（单声道输入即单声道输出，立体声保持立体声）。
  - 推理：`MossFormer2_SE_48K`，官方分块（20 s 块 + 4 s 解码窗），逐块回调写入 `job.params['progress']`（0.05→0.95）。
  - 输出：`dry/wet` 混合（0–100%，默认 100% = 全降噪，提供过度抑制逃生阀）+ 共享衰减至 −1 dBFS + `PCM_16` 落盘（与 Stems 一致）。
  - 发布：`tempfile.mkdtemp` 暂存 → 在 `ARTIFACT_LOCK` 下 `os.replace` 原子落位；`begin_output`/`end_output` 保护活动产物不被删除。
  - **队列语义**：MF2 CPU 亦可跑（0.111 s/音频 s）、显存仅 486 MB ⇒ **不需要卸载已加载的 MOSS 模型**（与 Stems 不同），但仍排在同一条 JobRunner 队列中。
- 依赖：架构代码 vendoring 到 `runtime/pylibs/mossformer2_se/`（Apache-2.0，附来源与许可说明——该包 PyPI 上不存在，必须随包提供）+ `rotary_embedding_torch`、`torchinfo`、`einops`（都在 `runtime/requirements.txt` 里）；`einops` 工程已有。
- 权重：`models/MossFormer2_SE_48K/last_best_checkpoint.pt`（221,552,019 B，sha256 `03692b9f773bbd6bb43b9c5a41f96b1e28affd66e13796b7bec66ad3d8b227c6`），由 `tools/download_denoise_models.py` 经 ModelScope + curl 获取（断点续传 + sha256 校验），**不进安装包**（与既有发布口径一致）。
- 接口：`POST /api/denoise/apply`（JSON `{path, mix}`）→ `{job_id}`；`GET /api/jobs/{id}` 轮询 `params.progress`；产物经 `/outputs/{name:path}` 访问。前端沿用 `stems.js` 的握手（`moss-language`/`moss-theme`）、700→1200 ms 轮询与重试语义。

---

## 9. 过程文件

调研期的评测台、对比脚本、日志与中间 JSON 均为临时过程文件，**已清理**；被淘汰方案的本体（DFN3 二进制与权重、DFSMN/ ZipEnhancer 的 vendored 包与权重、各 wheel 缓存、`bd.rnnn`）同样已删除。留存的只有：

- 本文档（结论与全部关键数据）。
- 采用方案所需的资产：`runtime/pylibs/mossformer2_se/`、`runtime/pylibs/rotary_embedding_torch/`、`models/MossFormer2_SE_48K/`。

清理残留（3.9 MB，可手动删除）：`temp\denoise-bench\wheels\` 下的 `clearvoice-0.1.2-py3-none-any.whl`、`rotary_embedding_torch-0.9.1-py3-none-any.whl`、`torchinfo-1.8.0-py3-none-any.whl` 三个文件在本轮清理时被系统进程占用（`os error 32`，重启后端与全部测试进程退出后仍占用），其余过程文件与 `temp\` 目录均已在 2026-10-15 清理完毕。这三个 wheel 的内容已落在 `runtime/pylibs/`，删除它们不影响运行。

需要复现任一被淘汰方案时，按 §3 的通道与 §5 的仓库/模型 id 重新取件即可（例如 DFN3：`gh-proxy.com` + `Rikorose/DeepFilterNet` releases v0.5.6 与 `models/DeepFilterNet3_onnx.tar.gz`；DFSMN：ModelScope `iic/speech_dfsmn_ans_psm_48k_causal`）。
