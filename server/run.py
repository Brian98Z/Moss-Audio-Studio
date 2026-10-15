"""Bootstrap for the MOSS workbench server.

Puts `..\\runtime\\ffmpeg` on PATH and `..\\runtime\\pylibs` first on sys.path — that directory
holds the vendored `mossformer2_se` (no PyPI package exists for it); on the original two-stack
install it also carried the transformers 5.x / quanto overlay — then hands control to
`app.main()`.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUNTIME = ROOT / "runtime"
VENV = RUNTIME / "venv"
EXPECTED_PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")
FFMPEG = RUNTIME / "ffmpeg" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
ENV_HINT = "首次使用需先准备运行环境：请在客户端『环境准备』中一键安装（≈3.4 GB）"

if not EXPECTED_PYTHON.is_file():
    print(ENV_HINT, flush=True)
    raise SystemExit(3)

if Path(sys.executable).resolve() != EXPECTED_PYTHON.resolve():
    print(f"{ENV_HINT}（当前解释器：{sys.executable}）", flush=True)
    raise SystemExit(4)

import subprocess

probe = subprocess.run(
    [
        sys.executable,
        "-c",
        "import torch, torchaudio; print(torch.__version__); print(torch.cuda.is_available()); print(torch.backends.cudnn.version())",
    ],
    capture_output=True,
    text=True,
)
if probe.returncode:
    print("运行环境尚未安装完整：请在客户端『环境准备』中一键安装（≈3.4 GB）", flush=True)
    raise SystemExit(4)

torch_version, cuda_available, cudnn_version = probe.stdout.splitlines()[:3]
system_cudnn = Path(os.environ.get("WINDIR", r"C:\WINDOWS")) / "SYSTEM32" / "cudnn64_9.dll"
system_cudnn_conflict = False
if os.name == "nt" and system_cudnn.is_file():
    kernel_dlls = ("cudnn_ops64_9.dll", "cudnn_engines_precompiled64_9.dll", "cudnn_cnn64_9.dll")
    missing_kernels = [name for name in kernel_dlls if not (system_cudnn.parent / name).is_file()]
    system_cudnn_conflict = bool(missing_kernels)
    if system_cudnn_conflict:
        print(
            f"[WARN] 检测到系统级 cuDNN 9（不完整）：{system_cudnn} —— "
            f"可能劫持其它 CUDA 程序的 DLL 解析并导致 0xc0000409 崩溃；"
            f"工作台自身使用 torch 自带 cuDNN（实测 {cudnn_version}，不受影响）。建议删除该文件或补全安装。",
            flush=True,
        )
os.environ["MOSS_ENV_READY"] = "1"
os.environ["MOSS_ENV_INTERPRETER"] = str(Path(sys.executable).resolve())
os.environ["MOSS_ENV_TORCH"] = torch_version
os.environ["MOSS_ENV_CUDA"] = cuda_available
os.environ["MOSS_ENV_CUDNN"] = cudnn_version
os.environ["MOSS_ENV_SYSTEM_CUDNN_CONFLICT"] = str(system_cudnn_conflict)
os.environ["MOSS_ENV_MISSING"] = "[]"
print(
    f"环境就绪：解释器={sys.executable}，torch={torch_version}，CUDA可用={cuda_available}，cuDNN={cudnn_version}",
    flush=True,
)

if not FFMPEG.is_file():
    print("警告：未检测到 ffmpeg，请前往下载中心安装；部分接口可能不可用。", flush=True)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FFMPEG_DIR = ROOT / "runtime" / "ffmpeg"
if FFMPEG_DIR.is_dir():
    os.environ["PATH"] = str(FFMPEG_DIR) + os.pathsep + os.environ.get("PATH", "")
OVERLAY = ROOT / "runtime" / "pylibs"

if OVERLAY.is_dir() and str(OVERLAY) not in sys.path:
    sys.path.insert(0, str(OVERLAY))

os.chdir(HERE)
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import app  # noqa: E402  (path setup must run first)

if __name__ == "__main__":
    app.main()
