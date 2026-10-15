# MOSS Voice Workbench — Quick Start

## What it is

MOSS Voice Workbench is a desktop app for creating and processing audio on your own computer.
The app and inference run locally; model files and Python dependencies are downloaded when you first set it up.
After setup, generation can run offline.
**Tech stack:** Electron desktop app, local Python service, and MOSS speech models.

## What it can do

- **Single-speaker voice generation and voice cloning:** make speech using a built-in voice or your own reference audio.
- **Voice design:** describe a voice in text and generate speech without reference audio.
- **Dialogue generation:** create multi-speaker dialogue with speaker-tagged scripts and reference audio.
- **Sound-effect generation:** generate sound effects and ambience from a text prompt.
- **Audio separation:** separate vocals, drums, bass, piano, guitar, and other accompaniment, or extract vocals and instrumental accompaniment as two tracks.
- **Denoising:** reduce background noise, hiss, and hum.
- **Speech recognition:** transcribe audio with the optional local Whisper Small model.

## Quick start

1. **Install** — Install and launch MOSS Voice Workbench. On first launch, it will prompt you to prepare the environment.
2. **Prepare the environment** — In **Environment Setup**, install the dependencies using the bundled Python. This downloads about **3.4 GB**. PyTorch is about **2.7 GB** and took about **15 minutes** on the tested connection; actual time depends on your network. The default package-source fallback is Tsinghua → Alibaba Cloud → official PyPI; PyTorch uses `--extra-index-url https://download.pytorch.org/whl/cu130`.
3. **Download models** — Open **Settings → Environment setup** and download the required models (about **61.8 GB**) and FFmpeg (about **83 MB**). Demucs, Whisper Small, and MossFormer2 SE are optional resources you can download as needed. Downloads are stored under the workbench installation directory.
4. **Start using it** — Open the workbench and choose a generation mode or audio tool. Allow the model to load when prompted. TTS/voice-generation outputs go directly under `outputs/<scene>/`; only Stems and Denoise use per-job directories: `outputs/Stems/<job_id>/` and `outputs/Denoise/<job_id>/`. Uploaded audio is stored under `uploads/`.

### Run from source

On Windows x64, use 64-bit Python 3.12. From the source checkout root, run `python tools/downloader_ui.py` with no arguments to open the standalone environment/download UI. Create `runtime/venv` with Python 3.12, install `runtime/requirements.txt` including `--extra-index-url https://download.pytorch.org/whl/cu130`, then start with `start_server.bat` or the venv Python running `server/run.py`. The development root is the checkout (default `D:\MossTTSD`); an installed app uses `<install>/resources/workbench`, which can move with the installation.

## FAQ

**A download or setup is stuck at 0% or very slow.**
Environment setup downloads several gigabytes, and progress may not move steadily. Check your connection to the download sources and make sure you have enough disk space. The package installer may be trying another configured source; let it continue. Model and FFmpeg downloads may take time depending on your connection and file size.

**The app says the environment is missing, or the backend exits with code 3 or 4.**
Exit code **3** means the expected `runtime/venv` interpreter is missing. Exit code **4** means the backend was started by a different interpreter path, or the venv interpreter failed the `torch`/`torchaudio` preflight. Start the backend through the matching venv Python; rerun Environment Setup if the venv dependencies are incomplete. `MOSS_TTS_PYTHON` is only used to discover a base interpreter during environment preparation; it does not override the backend interpreter.

**Can I resume an interrupted download?**
Yes. Start the same item again in Settings → Environment setup; partial downloads are retained and resumed.

**Do I need an NVIDIA GPU?**
No. The app can run on CPU, but generation will be slower. For GPU acceleration, a CUDA 13-capable NVIDIA driver is a system prerequisite.

**Can I use the app offline?**
The app runs inference locally and does not require a cloud service. Initial environment and model downloads require an internet connection. Once the required dependencies and model files are present, generation can run offline.

**Where are models and generated files stored?**
Downloads go to fixed locations under the workbench installation directory: dependencies in `runtime/venv/`, FFmpeg in `runtime/ffmpeg/`, and model weights in `models/`. Generated files go to `outputs/`; uploaded audio goes to `uploads/`. `MOSS_DOWNLOAD_ROOT` is for testing only; do not set it for normal use.

**How do I uninstall or move the workbench?**
Uninstall it using the operating system's normal app-uninstall method. To move it, close the app and move or back up the entire workbench root, retaining `models/`, `runtime/`, and `assets/`, then launch it from the new location. Make sure the destination has enough disk space. Back up `outputs/` separately if you want to keep generated audio.

## Environment variables & directory quick reference

| Variable or folder | Purpose |
|---|---|
| `MOSS_TTS_PYTHON` | Base Python candidate for environment preparation only; it does not select the backend interpreter. The backend requires the exact `runtime/venv` Python. |
| `MOSS_WORKBENCH_ROOT` | Set the workbench root; normally leave unset. Defaults to the installed workbench directory (development default: `D:\MossTTSD`). |
| `MOSS_DOWNLOAD_ROOT` | Test-only override for the download root; do not set for normal use. |
| `server/` | Local backend service. |
| `tools/` | Environment setup and Download Center. |
| `runtime/requirements.txt` | Python dependency list. |
| `runtime/venv/` · `runtime/ffmpeg/` · `runtime/pylibs/` | Installed Python environment, FFmpeg, and bundled local libraries. |
| `models/` | Downloaded speech and audio-processing model weights. |
| `python/` | Bundled portable CPython 3.12. |
| `assets/` | Built-in reference voices and assets. |
| `outputs/` | Generated audio. |
| `uploads/` | Uploaded audio. |
| `docs/` | User and configuration documentation. |

## More docs

- [Quick Start in Simplified Chinese](QUICKSTART.zh-CN.md)
- [Configuration and directory details](CONFIG.md)
- [Local API reference](API.md)
