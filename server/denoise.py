"""Offline vocal denoise engine (MossFormer2_SE_48K) for the FastAPI service.

与 `stems.py` 同一套约定：解码 → 在共享 GPU 工作线程内推理 → 暂存目录 → 原子发布。
差异：
  * 逐通道处理（单声道入→单声道出；立体声入→立体声出），不改动通道布局；
  * 输出保持**输入采样率**（内部统一 48 kHz 推理，再重采样回原采样率）；
  * 支持 dry/wet 混合（`mix`，1.0 = 全降噪），给过度抑制留逃生阀；
  * 引擎为纯 Python + torch（无外部二进制），CPU 亦可跑（实测 0.111 s/音频 s，
    显存峰值 486 MB）⇒ **不卸载已加载的 MOSS 模型**。

架构代码与依赖（runtime/pylibs：mossformer2_se / rotary_embedding_torch / torchinfo 均为
vendoring，上游零改动）；权重与下载链接见 models/MossFormer2_SE_48K/config.json。
"""
from __future__ import annotations

import gc
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from math import gcd
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf
import torch
import torchaudio

LOG = logging.getLogger("moss.denoise")

ROOT_DIR = Path(__file__).resolve().parent.parent
_CONFIG = json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8"))
_checkpoint = Path(_CONFIG["denoise"]["checkpoint"])
CHECKPOINT = _checkpoint if _checkpoint.is_absolute() else (Path(__file__).resolve().parent / _checkpoint).resolve()
UPLOAD_DIR = ROOT_DIR / "uploads"
OUTPUT_DIR = ROOT_DIR / "outputs"
FFMPEG = ROOT_DIR / "runtime" / "ffmpeg" / "ffmpeg.exe"

SAMPLE_RATE = 48000
MAX_WAV_VALUE = 32768.0
WIN_LEN = 1920          # 40 ms @ 48 kHz
WIN_INC = 384           # 8 ms @ 48 kHz
FFT_LEN = 1920
NUM_MELS = 60
ONE_TIME_DECODE_SECONDS = 20
DECODE_WINDOW_SECONDS = 4

DOWNLOAD_HINT = ("python tools\\download_denoise_models.py"
                 "（权重 221 MB，见 server/config.json 的 denoise.download_url）")


def _ffmpeg_path() -> str:
    if FFMPEG.is_file():
        return str(FFMPEG)
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise FileNotFoundError(f"ffmpeg binary unavailable: expected {FFMPEG} or ffmpeg on PATH")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _decode_audio(path: Path) -> tuple[np.ndarray, int]:
    """Decode via soundfile first; compressed/unsupported containers use ffmpeg.

    返回 (channels, samples) float32 与**原始采样率**（不做声道增删）。
    """
    try:
        audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
    except (RuntimeError, sf.SoundFileError):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        try:
            proc = subprocess.run(
                [_ffmpeg_path(), "-y", "-nostdin", "-v", "error", "-i", str(path), "-vn",
                 "-f", "wav", str(wav_path)],
                capture_output=True, text=True, check=False,
            )
            if proc.returncode:
                raise ValueError(f"ffmpeg could not decode audio: {proc.stderr.strip()[-1000:]}")
            audio, rate = sf.read(str(wav_path), dtype="float32", always_2d=True)
        finally:
            wav_path.unlink(missing_ok=True)
    if not len(audio) or rate <= 0:
        raise ValueError("audio file contains no samples")
    return np.ascontiguousarray(audio.T), rate


def _to_rate(audio: np.ndarray, rate: int, target: int) -> np.ndarray:
    """(channels, samples) 线性相位重采样到 target（axis=-1）。"""
    if rate == target:
        return audio
    from scipy.signal import resample_poly
    factor = gcd(rate, target)
    return resample_poly(audio, target // factor, rate // factor, axis=-1).astype(np.float32, copy=False)


def _load_model(device: torch.device):
    """构造官方 TestNet 并严格加载权重（checkpoint 键含 `mossformer.` 前缀，与 TestNet 对齐）。"""
    if not CHECKPOINT.is_file():
        raise FileNotFoundError(
            f"人声降噪模型权重缺失：{CHECKPOINT}\n请先运行 {DOWNLOAD_HINT}")
    from mossformer2_se.mossformer2_se_wrapper import MossFormer2_SE_48K

    model = MossFormer2_SE_48K(None).model
    state = torch.load(str(CHECKPOINT), map_location="cpu", weights_only=False)
    if isinstance(state, dict) and "state_dict" in state and isinstance(state["state_dict"], dict):
        state = state["state_dict"]
    model.load_state_dict(state, strict=True)
    model.eval().to(device)
    return model


def _features(x: np.ndarray, device: torch.device) -> torch.Tensor:
    """官方 compute_fbank 等价：kaldi fbank(60) + 一阶/二阶差分 → (1, T, 180)。"""
    audio = torch.from_numpy(np.ascontiguousarray(x * MAX_WAV_VALUE, dtype=np.float32)).unsqueeze(0)
    fbank = torchaudio.compliance.kaldi.fbank(
        audio, dither=1.0,
        frame_length=WIN_LEN / SAMPLE_RATE * 1000.0,
        frame_shift=WIN_INC / SAMPLE_RATE * 1000.0,
        num_mel_bins=NUM_MELS, sample_frequency=SAMPLE_RATE, window_type="hamming")
    delta1 = torchaudio.functional.compute_deltas(fbank.transpose(0, 1)).transpose(0, 1)
    delta2 = torchaudio.functional.compute_deltas(delta1.transpose(0, 1)).transpose(0, 1)
    return torch.cat((fbank, delta1, delta2), dim=1).unsqueeze(0).to(device)


def _enhance_segment(model, seg: np.ndarray, device: torch.device) -> np.ndarray:
    """单段（48 kHz，长度 ≤ 4 s）推理：mask 乘到非居中 STFT 上后 iSTFT。"""
    with torch.inference_mode():
        feat = _features(seg, device)
        pred = model(feat)[-1]
        wav = torch.from_numpy(np.ascontiguousarray(seg * MAX_WAV_VALUE, dtype=np.float32)).to(device)
        window = torch.hamming_window(WIN_LEN, periodic=False, device=device)
        spec = torch.stft(wav, n_fft=FFT_LEN, hop_length=WIN_INC, win_length=WIN_LEN,
                          window=window, center=False, return_complex=True)
        mask = pred[0]
        if mask.ndim == 3 and mask.shape[-1] == 2:
            mask = torch.view_as_complex(mask.contiguous())
        if mask.ndim == 2:
            mask = mask.transpose(0, 1)
        frames = min(spec.shape[-1], mask.shape[-1])
        decoded = torch.istft(spec[..., :frames] * mask[..., :frames], n_fft=FFT_LEN,
                              hop_length=WIN_INC, win_length=WIN_LEN, window=window, center=False)
        out = decoded.detach().cpu().numpy().astype(np.float32)
    if out.size < len(seg):
        out = np.pad(out, (0, len(seg) - out.size))
    return out[:len(seg)] / MAX_WAV_VALUE


def enhance_48k(model, x: np.ndarray, device: torch.device,
                progress: Callable[[float], None] | None = None) -> np.ndarray:
    """48 kHz 单通道整段降噪；>20 s 时按官方口径分段（4 s 窗、3 s 步长）。

    分段沿用官方 decode 的边界处理：每段丢弃两端 give_up 秒，首段只丢尾部。
    """
    total = len(x)
    window = int(SAMPLE_RATE * DECODE_WINDOW_SECONDS)
    if total <= SAMPLE_RATE * ONE_TIME_DECODE_SECONDS:
        if progress:
            progress(0.5)
        return _enhance_segment(model, x, device)

    stride = int(window * 0.75)
    give_up = (window - stride) // 2
    # 官方对尾部的补零口径：把长度补到窗口/步长的整数关系，保证最后一段完整
    if total < window:
        x = np.concatenate([x, np.zeros(window - total, dtype=np.float32)])
    elif total < window + stride:
        x = np.concatenate([x, np.zeros(window + stride - total, dtype=np.float32)])
    elif (total - window) % stride != 0:
        x = np.concatenate([x, np.zeros(total - (total - window) // stride * stride, dtype=np.float32)])

    out = np.zeros(len(x), dtype=np.float32)
    idx = 0
    written_upto = 0
    segments = max(1, (len(x) - window) // stride + 1)
    done = 0
    while idx + window <= len(x):
        seg = x[idx:idx + window]
        enhanced = _enhance_segment(model, seg, device)
        if idx == 0:
            out[0:window - give_up] = enhanced[:window - give_up]
            written_upto = window - give_up
        else:
            out[idx + give_up:idx + window - give_up] = enhanced[give_up:window - give_up]
            written_upto = idx + window - give_up
        idx += stride
        done += 1
        if progress:
            progress(0.05 + 0.9 * done / segments)
    # 尾部整段补写（官方循环会丢掉最后 give_up 秒）：用最后一个完整窗的输出收尾
    if written_upto < len(x):
        start = max(0, len(x) - window)
        seg = x[start:start + window]
        if len(seg) < window:
            seg = np.pad(seg, (0, window - len(seg)))
        tail = _enhance_segment(model, seg, device)
        out[written_upto:] = tail[written_upto - start:]
    return out[:total]


def denoise_audio(
    job,
    upload_path: str,
    mix: float = 1.0,
    *,
    upload_root: Path = UPLOAD_DIR,
    output_root: Path = OUTPUT_DIR,
    artifact_lock=None,
    begin_output=None,
    end_output=None,
) -> dict:
    """在共享工作线程内做整段降噪，并把结果原子发布到 outputs/Denoise/<job_id>/。"""
    target = Path(upload_path).expanduser().resolve()
    if not _inside(target, Path(upload_root)) or not target.is_file():
        raise ValueError("path must refer to an existing uploaded file")
    mix = float(mix)
    if not 0.0 <= mix <= 1.0:
        raise ValueError("mix must be between 0.0 and 1.0")

    started = time.monotonic()
    model = None
    stage = None
    denoise_root = Path(output_root) / "Denoise"
    final_dir = denoise_root / job.id
    lock = artifact_lock
    if begin_output:
        begin_output(denoise_root)
    try:
        job.params["progress"] = 0.02
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        audio, in_rate = _decode_audio(target)
        channels, samples = audio.shape
        job.params["progress"] = 0.05
        resampled = _to_rate(audio, in_rate, SAMPLE_RATE)
        model = _load_model(device)
        processed = np.empty_like(resampled)

        def progress(value):
            job.params["progress"] = round(min(0.95, value), 4)

        for index in range(channels):
            base = index / channels * 0.9 + 0.05
            span = 0.9 / channels
            processed[index] = enhance_48k(
                model, np.ascontiguousarray(resampled[index]), device,
                progress=lambda value, base=base, span=span: progress(base + span * value))

        # dry/wet：mix=1 全降噪；mix<1 按样本与原信号混合（逃生阀）
        wet = processed if mix >= 1.0 else (mix * processed + (1.0 - mix) * resampled).astype(np.float32)
        restored = _to_rate(wet, SAMPLE_RATE, in_rate) if in_rate != SAMPLE_RATE else wet
        restored = restored[:, :samples]

        denoise_root.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{job.id}-", dir=denoise_root))
        staged_dir = stage / job.id
        staged_dir.mkdir()
        name = f"{target.stem}_denoised.wav"
        peak = float(np.max(np.abs(restored))) if restored.size else 0.0
        ceiling = 10 ** (-1.0 / 20.0)
        gain = min(1.0, ceiling / peak) if peak > 0 else 1.0
        sf.write(str(staged_dir / name), (restored * gain).T, in_rate, subtype="PCM_16", format="WAV")
        if lock:
            lock.acquire()
        try:
            if final_dir.exists():
                raise FileExistsError(f"denoise output already exists for job {job.id}")
            os.replace(staged_dir, final_dir)
        except Exception:
            import shutil
            shutil.rmtree(final_dir, ignore_errors=True)
            raise
        finally:
            if lock:
                lock.release()
        job.params["progress"] = 1.0
        return {
            "outputs": [{
                "stem": "denoised",
                "name": f"Denoise/{job.id}/{name}",
                "label": f"{target.stem}（降噪 {round(mix * 100)}%）",
                "url": f"/outputs/Denoise/{job.id}/{name}",
            }],
            "seconds": round(samples / in_rate, 3),
            "sample_rate": in_rate,
            "mix": mix,
            "gain": round(gain, 4),
            "device": device.type,
            "elapsed": round(time.monotonic() - started, 2),
        }
    finally:
        if end_output:
            end_output(denoise_root)
        if stage is not None:
            import shutil
            shutil.rmtree(stage, ignore_errors=True)
        if model is not None:
            del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
