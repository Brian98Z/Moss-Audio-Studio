"""本地语音识别（ASR）——给「多人对话」页自动填写参考音频逐字稿。

用仓库自带的 whisper-small（CTranslate2 权重，`models/whisper-small`）+ `runtime/pylibs` 里的
faster-whisper 1.2.1，全部离线、不新增依赖、不下载模型。

不走 faster-whisper 自带的 PyAV 解码：本机 `av` 与 1.2.1 不兼容（`av.open()` 不接受
`metadata_errors` 参数），因此这里用 soundfile 解码成 mono float32、重采样到 16 kHz 再交给模型；
这也和引擎里 `_load_wav` 的解码口径一致。
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

ASR_RATE = 16000  # whisper 的输入采样率
_ROOT = Path(__file__).resolve().parent.parent
_PYLIBS = _ROOT / "runtime" / "pylibs"
if _PYLIBS.is_dir() and str(_PYLIBS) not in sys.path:
    sys.path.insert(0, str(_PYLIBS))


def _resample(wav: np.ndarray, sr: int, target: int = ASR_RATE) -> np.ndarray:
    """线性/高质量重采样到 16 kHz；优先 torchaudio，缺了就用线性插值兜底。"""
    if sr == target:
        return wav.astype(np.float32)
    try:
        import torch
        import torchaudio

        return (
            torchaudio.functional.resample(torch.from_numpy(wav), sr, target).cpu().numpy().astype(np.float32)
        )
    except Exception:
        n = max(1, int(round(len(wav) * target / sr)))
        return np.interp(np.linspace(0, len(wav) - 1, n), np.arange(len(wav)), wav).astype(np.float32)


class AsrEngine:
    """懒加载 + 串行化的 whisper 包装（模型只在第一次识别时载入）。"""

    def __init__(
        self,
        model_dir: str,
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 5,
        log=None,
    ) -> None:
        self.model_dir = str(model_dir)
        self.device = device
        self.compute_type = compute_type
        self.beam_size = int(beam_size)
        self._model = None
        self._lock = threading.Lock()
        self._log = log or (lambda _m: None)

    # ------------------------------------------------------------------ 加载
    def ensure(self):
        with self._lock:
            if self._model is None:
                t0 = time.time()
                import faster_whisper

                if not Path(self.model_dir).is_dir():
                    raise RuntimeError(f"ASR 模型目录不存在：{self.model_dir}")
                self._model = faster_whisper.WhisperModel(
                    self.model_dir, device=self.device, compute_type=self.compute_type
                )
                self._log(
                    f"ASR 模型就绪：whisper-small（{self.device}/{self.compute_type}），{time.time() - t0:.1f}s"
                )
            return self._model

    # ------------------------------------------------------------------ 识别
    def transcribe(self, path: str, language: Optional[str] = None) -> dict:
        src = Path(path)
        if not src.is_file():
            raise FileNotFoundError(f"音频不存在：{src}")
        data, sr = sf.read(str(src), dtype="float32", always_2d=True)
        wav = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
        wav = _resample(np.ascontiguousarray(wav), int(sr))

        model = self.ensure()
        t0 = time.time()
        with self._lock:
            try:
                segs, info = model.transcribe(
                    wav,
                    language=(language or None),
                    beam_size=self.beam_size,
                    vad_filter=True,
                    condition_on_previous_text=False,
                )
                text = "".join(s.text for s in segs).strip()
            except Exception:  # VAD 模型缺失等极端情况：退回不切分
                segs, info = model.transcribe(
                    wav,
                    language=(language or None),
                    beam_size=self.beam_size,
                    vad_filter=False,
                    condition_on_previous_text=False,
                )
                text = "".join(s.text for s in segs).strip()
        return {
            "text": text,
            "language": getattr(info, "language", "") or "",
            "language_probability": round(float(getattr(info, "language_probability", 0.0) or 0.0), 3),
            "duration": round(len(wav) / ASR_RATE, 2),
            "elapsed": round(time.time() - t0, 2),
            "source": str(src),
        }
