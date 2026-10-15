# MOSS Voice Workbench

**English** | [Simplified Chinese](README.zh-CN.md)

A fully offline voice & audio workbench around the MOSS speech models, with a desktop client and a built-in
web UI: voice cloning / single-speaker TTS, voice design, sound effects, multi-speaker dialogue, plus two
audio tools — 6-stem separation (Demucs) and vocal denoising (MossFormer2_SE_48K). No cloud service is
involved; audio never leaves this machine.

Detailed reference docs (Chinese): [`docs/API.md`](docs/API.md) · [`docs/CONFIG.md`](docs/CONFIG.md) · [`docs/DENOISE.md`](docs/DENOISE.md)

## Requirements

| | |
|---|---|
| Platform | **Windows x64 only** (tested on Windows 11, RTX 5070 Ti 16 GB, torch 2.10.0+cu130, Python 3.12.10) |
| GPU memory | The three 8B models need ~16 GB with int8 weights; the 1.7B voice-design model needs ~9 GB; denoising only ~0.5 GB. 8B heads are tight — do not run other GPU-heavy apps (including GPU-accelerated browsers) while generating |
| Runtime roots | Development source root: `D:\MossTTSD` (default on Windows). Installed workbench root: `<install>/resources/workbench`; the packaged launcher uses this root, so the install can be relocated. |

## Layout

```
<workbench-root>\ (development checkout or installed resources/workbench)
├─ client\           Electron client + portable Python; launcher: MOSS语音工作台-启动器.exe (MOSS Voice Workbench Launcher)
├─ runtime\          dependencies only — the venv is created on the target machine, never shipped
│   ├─ requirements.txt   every pip dependency, pinned (torch 2.10.0+cu130, transformers 5.19, …)
│   ├─ pylibs\       only the vendored `mossformer2_se` (no PyPI package); put first on sys.path
│   └─ ffmpeg\       bundled ffmpeg + DLLs (an `ffmpeg` on PATH works too)
├─ models\           every weight the backend loads (nothing outside this folder)
│   ├─ openmoss\     MOSS-TTS-v1.5 / TTSD-v1.0 / SoundEffect / VoiceGenerator (+ *-int8-nohead checkpoints)
│   │                and MOSS-Audio-Tokenizer-fp16 (shared codec)
│   ├─ whisper-small\        local ASR weights (CTranslate2)
│   ├─ demucs\       stem-separation weights
│   └─ MossFormer2_SE_48K\   denoising weights + its config.json
├─ assets\           audio assets, not weights: built-in reference voices + demo clips
│   ├─ voices\       15 built-in voice samples + voices.jsonl
│   └─ reference\    demo audio used by the end-to-end test
├─ server\           FastAPI backend: app.py, moss_engine.py, asr.py, stems.py, denoise.py, config.json, web\
├─ tools\            download / merge / tokenizer setup / denoise-weight helpers
├─ integration\      client patch script + end-to-end smoke tests
├─ docs\             API / config / denoise reference docs
├─ uploads\ outputs\ uploaded audio and generated results
└─ start_server.bat  start the backend without the client
```

## Start

### Install

**[Download the Windows x64 installer (latest release)](https://github.com/Brian98Z/Moss-Audio-Studio/releases/latest)** and launch it — the installer includes the workbench and portable Python, so it is ready to use. The build is not code-signed, so Windows SmartScreen may warn about an unknown publisher; check the file against `SHA256SUMS-win-x64.txt` on the release page. (The *Source code* archives auto-attached by GitHub are not installers.)

On first launch, complete these two steps in the interface:

1. Under **Environment preparation**, create `runtime/venv` with the bundled portable Python and install `runtime/requirements.txt` (about 3.4 GB). The package source is chosen automatically (Tsinghua → Alibaba Cloud → official PyPI, switching on failure; the setup log shows which one was used), and PyTorch packages come from `--extra-index-url https://download.pytorch.org/whl/cu130` (about 2.7 GB of the total).
2. In **Download center**, download the required model weights (about 61.8 GB); optional assets such as Demucs, Whisper, and MossFormer2_SE can be downloaded as needed. FFmpeg is also downloaded there (about 83 MB).

The installer contains the workbench application (`server/`, `tools/`, `docs/`, `runtime/requirements.txt`, `runtime/pylibs/`, `python/`, and `assets/`) and portable CPython 3.12. It does not contain `models/`, `runtime/venv/`, `runtime/ffmpeg/`, `outputs/`, or `uploads/`.
### Run from source

Use 64-bit Python 3.12 on Windows x64. From a source checkout, run `python tools/downloader_ui.py` (no arguments) to open the standalone environment/download UI. Prepare `runtime/venv` with that Python and install `runtime/requirements.txt`, including `--extra-index-url https://download.pytorch.org/whl/cu130` for PyTorch; then launch with `start_server.bat` or the venv Python running `server/run.py`.

The development root is the checkout (default `D:\MossTTSD`). For an installed app, the workbench root is `<install>/resources/workbench`; the packaged launcher derives it from the install and supports relocation. Do not assume the development path for an installed copy.

Downloads are placed under the workbench root. `MOSS_DOWNLOAD_ROOT` is only a test override; normal downloads use the fixed workbench root.

First time here? **[Quick Start](docs/QUICKSTART.md)** is a one-page walkthrough: what the app does, the two setup steps with expected sizes and times, FAQ (slow downloads, exit codes 3/4, offline use, uninstall/move), and a directory reference. A [Simplified Chinese version](docs/QUICKSTART.zh-CN.md) is included too.

### Run

1. **Desktop client (recommended)** — double-click `client\MOSS语音工作台-启动器.exe` (MOSS Voice Workbench Launcher). It starts exactly one
   backend (`server\run.py`) and opens the workbench window.
2. **Backend only** — run `start_server.bat`, then open <http://127.0.0.1:17980>.
   `MOSS_HOST` / `MOSS_PORT` override the host and port. `MOSS_WORKBENCH_ROOT` selects the workbench root.
   `MOSS_TTS_PYTHON` is used by environment preparation to discover a base interpreter; it does not override
   the backend interpreter, which must be the exact `runtime/venv` Python.

The interface is available in Chinese and English; the client's settings page switches the language for the
whole workbench, including the embedded tool pages. The settings page also provides light / dark / system
themes and an accent colour.

## Features

| Feature | Where | Route | Notes |
|---|---|---|---|
| Voice cloning / single-speaker TTS | Single speaker tab | `GET`/`POST` `/api/gen/tts` | 3–10 s reference audio (or a built-in voice); 31 languages, mixed zh/en, `[pause 1.5s]` |
| Voice design | Voice design tab | `GET`/`POST` `/api/gen/vg` | Free-text description of the voice; no reference audio needed |
| Sound effects | Sound FX tab | `GET`/`POST` `/api/gen/sfx` | Describe ambience / Foley + target seconds (≈12.5 audio tokens per second) |
| Multi-speaker dialogue | Dialogue tab | `POST` `/api/gen/ttsd` | `[S1]` / `[S2]` script + a reference clip and transcript per speaker |
| Stem separation | Tools → Stems | `POST` `/api/stems/separate` | Six stems, or vocals / instrumental only (`mode`) |
| Vocal denoising | Tools → Denoise | `POST /api/denoise/apply` | 0–100 % strength (dry/wet mix); keeps the input sample rate and channel layout |

All heavy jobs share one GPU queue and run one at a time. The two tools are independent of the MOSS models:
separation unloads the loaded speech model first, denoising does not (its footprint is ~486 MB).

## First use

1. Open the workbench and load a model. Available quantization depends on deployed weights: checkpoint-only deployments enable int8; a full-precision master enables int8, float8, and none. The first load takes roughly 20–40 s; loading another model unloads the previous one.
2. Pick a tab, fill in the inputs and generate. Speech-generation files are written directly under `outputs/<scene>/`; only Stems and Denoise create per-job subdirectories (`outputs/Stems/<job_id>/` and `outputs/Denoise/<job_id>/`). Results can be played, downloaded, deleted, or reused as reference audio.
3. Reference audio may be a built-in voice, an uploaded file or a recording. The dialogue tab has a **Transcribe** button that fills in the transcript with a local Whisper model (CPU, offline).

Sampling defaults follow the official recipes — tts `1.7 / 0.8 / 25 / 1.0`, vg `1.5 / 0.6 / 50 / 1.1`,
ttsd `1.1 / 0.9 / 50 / 1.1`, sfx `1.5 / 0.6 / 50 / 1.2`. Length hints: sound effects ≤ 60 s,
dialogue ≤ 3 minutes per job; longer output needs `tokenizer_device: "cpu"` in `server\config.json`.

## Calling from other programs

Everything is documented in [`docs/API.md`](docs/API.md) with curl / Python / JS examples. The quickest path
is the synchronous `GET /api/gen/*` links, which return WAV bytes directly (metadata in `X-Output-*`
headers); `wait=0` returns a job id to poll instead. Non-ASCII query values must be percent-encoded — let
your HTTP client do it, or use `curl -G --data-urlencode "text=hello"`. `GET /api/gen` lists the endpoints,
Swagger is at `/docs`, CORS is open, and an optional `api_token` can require a token.

## Models & weights

Model weights are **not** shipped with installers, and uploads/results are never packaged. `models\*` can be
rebuilt at any time:

| Command | Purpose |
|---|---|
| `tools\download_models.py --models ttsd,sfx [--dest DIR]` | Download MOSS weights (resumable, sha256-verified) |
| `tools\prepare_models.py [--model tts]` | Merge shards into `model.safetensors` and write `MANIFEST.json` |
| `tools\download_denoise_models.py --check` / `--force` | Verify or re-download the denoising checkpoint (paths and sha256 come from `server\config.json`) |
| `integration\apply_launcher_patch.py` | Re-apply the client patch (the shipped `app.asar` is already patched) |
| `integration\downloader_acceptance.py` | End-to-end check of the download center (catalog, real download + sha256, cancel/resume, verify, zip unpack); run it with a test root |

Quantization depends on deployed weights. A checkpoint-only deployment exposes int8; if you download the full-precision master weights, the engine can use int8, float8, or none. Existing `*-int8-nohead` checkpoints are ready-to-load int8 artifacts; this repository does not include the external tool used to produce them.

### Unified downloader (GUI)

The same assets are also available inside the workbench, in one embedded tab: **Settings → Environment setup** is the
standalone `tools\downloader_ui.py` page (stdlib-only, default port 17990) shown in the shell — section ① prepares the
environment (`runtime\venv` + `runtime\requirements.txt`, ≈3.4 GB, mirror chosen automatically) and section ② downloads
the model weights and the optional resources. The shell starts the helper on demand with `--no-browser`, so no external
window is involved, and a machine whose environment is already complete reports it right there. The same page also opens
standalone at `http://127.0.0.1:17990/` (or as `/downloads` on the workbench port). It downloads into a **fixed location inside the install directory** (shown in the UI,
not configurable) and verifies what it writes: per-file `sha256` from ModelScope, the published `sha256` of
the ffmpeg zip, and the upstream 8-hex prefix for the demucs `.th`. Items already in place show a
**ready · verified** badge; a "verify" action re-hashes anything you want re-checked. Sizes are labelled so that
a locally present artifact never reads as a contradiction: the card header prints the **download package**
(`package 78.96 MB`) and a settled row prints what is actually on disk (`Local 253.24 MB` — e.g. a full ffmpeg
build already in `runtime\ffmpeg`). A model usable from locally present weights (shared codec, existing int8
artifacts) reads `Ready (usable local weights present)` instead of reporting a byte count for an empty folder, and a
settled row never keeps a stale partial-download progress bar.

| Item | Group | Size |
|---|---|---|
| ffmpeg (static build, unpacked flat into `runtime\ffmpeg`) | required | 83 MB |
| openmoss TTSD-v1.0 / SoundEffect / TTS-v1.5 / VoiceGenerator + shared codec (fp32) | required | 61.8 GB |
| demucs `5c90dfd2-34c22ccb.th` | optional (six-stem separation) | 55 MB |
| MossFormer2_SE_48K checkpoint | optional (denoise) | 222 MB |
| whisper-small (CTranslate2) | optional (transcripts) | 486 MB |

The openmoss rows pull the **full-precision masters**; the engine then streams int8 quantization itself on
the first load (measured on VoiceGenerator 1.7B: 28.7 s vs 15.8 s from a pre-quantized artifact, 8.4 GB
VRAM), so upstream `*-int8-nohead` checkpoints are optional. Missing optionals surface as a structured
`need_asset` error (HTTP 409) with a link straight to the download center.

Sources and measured speeds (this workstation, 2026-10-15): **ModelScope ~12–23 MB/s** and the
**npmmirror `ffmpeg-static` mirror ~15–23 MB/s** — that mirror ships gyan's own `essentials` static build, and
its sha256 is pinned in `server/config.json`, so ffmpeg's primary source is the mirror (`type: "bin"`) with the
BtbN zip as `fallback_sources`. GitHub/BtbN, gyan.dev and dl.fbaipublicfiles (demucs) were throttled from this
network (0.01–0.05 MB/s, range requests answered with zero bytes); the downloader still retries with Range
resume, and demucs stays optional so those hosts only matter for users who need stem separation.

## Configuration

`server\config.json` holds host/port, output and upload directories, model registry, ASR settings and the
denoising weight metadata; every field has a default and changes take effect after restarting the backend.
The full field table lives in [`docs/CONFIG.md`](docs/CONFIG.md).

## Building installers

`packaging/` (see its [README](packaging/README.md)) currently delivers a **Windows x64-only** application. The installer excludes `models/`, `runtime/venv/`, `runtime/ffmpeg/`, uploads, and results; first-launch setup downloads dependencies and models. macOS packaging commands below are experimental/incomplete and are not supported deliverables: the bundled runtime is Windows CPython, requirements pin CUDA-only PyTorch, and FFmpeg is win32-x64. Native CPython, CPU/MPS dependencies, and native FFmpeg must be prepared and verified before macOS can be supported.

```bash
cd packaging
npm install && npm run extract && npm run retrofit
npm run dist:win          # NSIS installer     → release/windows/
npm run dist:mac:x64      # incomplete; not a supported build
npm run dist:mac:arm64    # incomplete; not a supported build
```

Windows x64 builds and runs on this machine (Electron 44.7.0, served from the local Electron cache when
present; use `ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/` when GitHub is unreachable).

### Client (asar) patches

`client/resources/app.asar` is a built artifact; the local UI patches live in `integration/` and must be
re-applied whenever that asar is rebuilt. Both scripts extract, patch the single renderer bundle, run
`node --check` on the result, and only then pack — a broken patch never reaches an asar.

```bash
node integration/enable_english_ui.js           client/resources/app.asar            # writes app.asar.new: persisted English UI + translations
node integration/downloads_in_settings_patch.js client/resources/app.asar --apply    # Settings → General settings / Environment setup tabs (backs the asar up first)
```

Both are idempotent: re-running replaces the previously injected block instead of stacking a second one.
`downloads_in_settings_patch.js` appends a self-contained DOM enhancer to the renderer bundle, so the
Settings page keeps working even if the enhancer cannot attach; the Environment setup tab embeds the standalone
`tools/downloader_ui.py` page (port 17990), which contains both the environment section and the model download
section, refits its height to the available space, and retries the load until the page reports ready (so clicking
the tab before the helper has started still ends up showing the page rather than a blank frame).

The macOS workflow is not proof of a usable macOS workbench; its prerequisite runtime assets have not been prepared. See `.github/workflows/build-macos.yml`.

Packaged builds use `<resourcesPath>/workbench` as the workbench root unless `MOSS_WORKBENCH_ROOT` is set; development defaults to `D:/MossTTSD` on Windows. The backend always uses `<workbench>/runtime/venv/Scripts/python.exe` on Windows (or `bin/python3` on Unix); the path must exactly match the interpreter running `server/run.py`. `MOSS_TTS_PYTHON` only helps environment preparation discover a base interpreter. PATH discovery exists only in the environment-preparation module; it is not a backend interpreter fallback.

## License

| Component | License |
|---|---|
| MOSS models and their code (ModelScope `openmoss/MOSS-TTS-v1.5`, `MOSS-TTSD-v1.0`, `MOSS-SoundEffect`, `MOSS-VoiceGenerator`) | Apache-2.0 — free for commercial use |
| MossFormer2_SE_48K (ClearerVoice-Studio) code and weights | Apache-2.0 |
| Demucs and its pretrained weights | see the upstream `facebookresearch/demucs` licence |
| faster-whisper / Whisper, rotary_embedding_torch, torchinfo and the rest of `runtime\pylibs` | permissive (MIT and similar) |
| FFmpeg binaries in `runtime\ffmpeg` | LGPL / GPL depending on the build |

You are responsible for the rights to any voice you clone: a permissive model licence does not grant
permission to imitate someone else's voice.

## Troubleshooting

| Symptom | Fix |
|---|---|
| The client shows an outdated UI | The client only starts the backend; restart the client, and hard-refresh the page (Ctrl+F5) |
| CUDA out of memory while generating | Close other GPU consumers (browsers with hardware acceleration count), or set `tokenizer_device` to `"cpu"` in `server\config.json` to free ~3.5 GB |
| Port 17980 already in use | Start with `set MOSS_PORT=17981` (or edit `port` in `server\config.json`) |
| A quantized option is rejected with 400 | Only `int8` is available for that model; the response states the reason |
| Uploads or results missing from the UI | Check `uploads\` and `outputs\`; files whose job is still running are protected from deletion |
