"""Offline six-stem Demucs separation helpers for the FastAPI service."""
from __future__ import annotations

import gc
import os
import shutil
import logging
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf
import torch
from demucs.apply import apply_model
from demucs.pretrained import get_model

LOG = logging.getLogger("moss.stems")
ROOT_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT_DIR / "models" / "demucs"
UPLOAD_DIR = ROOT_DIR / "uploads"
OUTPUT_DIR = ROOT_DIR / "outputs"

FFMPEG = ROOT_DIR / "runtime" / "ffmpeg" / "ffmpeg.exe"


def _ffmpeg_path() -> str:
    if FFMPEG.is_file():
        return str(FFMPEG)
    fallback = shutil.which("ffmpeg")
    if fallback:
        return fallback
    raise FileNotFoundError(f"ffmpeg binary unavailable: expected {FFMPEG} or ffmpeg on PATH")
SAMPLE_RATE = 44100
SEGMENT_SECONDS = 7
STEMS = ("drums", "bass", "other", "vocals", "guitar", "piano")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _decode_audio(path: Path) -> tuple[np.ndarray, int]:
    """Decode via soundfile first; compressed/unsupported containers use ffmpeg."""
    try:
        audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
    except (RuntimeError, sf.SoundFileError):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        try:
            proc = subprocess.run(
                [_ffmpeg_path(), "-y", "-nostdin", "-v", "error", "-i", str(path), "-vn", "-ac", "2", "-ar", str(SAMPLE_RATE), "-f", "wav", str(wav_path)],
                capture_output=True, text=True, check=False,
            )
            if proc.returncode:
                raise ValueError(f"ffmpeg could not decode audio: {proc.stderr.strip()[-1000:]}")
            audio, rate = sf.read(str(wav_path), dtype="float32", always_2d=True)
        finally:
            wav_path.unlink(missing_ok=True)
    if not len(audio) or rate <= 0:
        raise ValueError("audio file contains no samples")
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    elif audio.shape[1] > 2:
        audio = audio[:, :2]
    if rate != SAMPLE_RATE:
        from scipy.signal import resample_poly
        from math import gcd
        factor = gcd(rate, SAMPLE_RATE)
        audio = resample_poly(audio, SAMPLE_RATE // factor, rate // factor, axis=0).astype(np.float32, copy=False)
    return np.ascontiguousarray(audio.T), SAMPLE_RATE


def _load_demucs():
    checkpoint = MODEL_DIR / "5c90dfd2-34c22ccb.th"
    if not checkpoint.is_file():
        raise FileNotFoundError(f"Demucs checkpoint missing: {checkpoint}")
    model = get_model("5c90dfd2", repo=MODEL_DIR)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return model.to(device).eval(), device


def separate_stems(
    job,
    upload_path: str,
    unload_engine: Callable[[], object],
    mode: str = "six",
    *,
    upload_root: Path = UPLOAD_DIR,
    output_root: Path = OUTPUT_DIR,
    artifact_lock=None,
    begin_output=None,
    end_output=None,
) -> dict:
    """Separate audio on the GPU worker and atomically publish the complete result."""
    target = Path(upload_path).expanduser().resolve()
    if not _inside(target, Path(upload_root)) or not target.is_file():
        raise ValueError("path must refer to an existing uploaded file")

    started = time.monotonic()
    unload_engine()
    model = None
    stage = None
    stems_root = Path(output_root) / "Stems"
    final_dir = stems_root / job.id
    archive = stems_root / f"{job.id}.zip"
    lock = artifact_lock
    if begin_output:
        begin_output(stems_root)
    try:
        job.params["progress"] = 0.02
        model, device = _load_demucs()
        mix, sample_rate = _decode_audio(target)
        total_samples = mix.shape[-1]
        chunk = torch.from_numpy(mix).unsqueeze(0)
        reference = chunk.mean(dim=1)
        mean, std = reference.mean(), reference.std().clamp_min(1e-8)
        normalized = (chunk - mean) / std

        def progress(info):
            total = info.get("audio_length", total_samples)
            offset = info.get("segment_offset", 0)
            job.params["progress"] = min(0.95, round(0.05 + 0.9 * offset / max(total, 1), 4))

        with torch.inference_mode():
            estimates = apply_model(model, normalized, shifts=0, split=True, segment=SEGMENT_SECONDS,
                                    overlap=0.25, device=device, callback=progress)[0]
        estimates = estimates * std + mean
        accumulated = {stem: estimates[index].float().cpu().numpy() for index, stem in enumerate(model.sources)}
        del normalized, chunk, estimates
        output_stems = STEMS
        if mode == "vocals":
            accumulated["instrumental"] = (mix - accumulated["vocals"]).astype(np.float32, copy=False)
            output_stems = ("vocals", "instrumental")

        stems_root = Path(output_root) / "Stems"
        stems_root.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{job.id}-", dir=stems_root))
        staged_dir = stage / job.id
        staged_dir.mkdir()
        outputs = []
        peak = max((float(np.max(np.abs(accumulated[s]))) for s in output_stems if accumulated[s].size), default=0.0)
        ceiling = 10 ** (-1.0 / 20.0)
        gain = min(1.0, ceiling / peak) if peak > 0 else 1.0
        for stem in output_stems:
            dest = staged_dir / f"{stem}.wav"
            sf.write(str(dest), (accumulated[stem] * gain).T, sample_rate, subtype="PCM_16", format="WAV")
            outputs.append({"stem": stem, "name": f"Stems/{job.id}/{stem}.wav",
                            "url": f"/outputs/Stems/{job.id}/{stem}.wav"})
        staged_archive = stage / f"{job.id}.zip"
        with zipfile.ZipFile(staged_archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for output in outputs:
                zf.write(staged_dir / Path(output["name"]).name,
                         arcname=f"{job.id}/{Path(output['name']).name}")
        if lock:
            lock.acquire()
        try:
            if final_dir.exists() or archive.exists():
                raise FileExistsError(f"stems output already exists for job {job.id}")
            os.replace(staged_dir, final_dir)
            os.replace(staged_archive, archive)
        except Exception:
            import shutil
            shutil.rmtree(final_dir, ignore_errors=True)
            archive.unlink(missing_ok=True)
            raise
        finally:
            if lock:
                lock.release()
        job.params["progress"] = 1.0
        return {"outputs": outputs, "seconds": round(total_samples / sample_rate, 3),
                "sample_rate": sample_rate, "archive_url": f"/api/stems/archive/{job.id}",
                "elapsed": round(time.monotonic() - started, 2)}
    finally:
        if end_output:
            end_output(stems_root)
        if stage is not None:
            import shutil
            shutil.rmtree(stage, ignore_errors=True)
        if model is not None:
            del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
