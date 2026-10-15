"""End-to-end acceptance test: load a model, generate, verify the audio.

Verification is layered -- file/duration/RMS/spectral checks are automatic; content is
checked by transcribing the result with faster-whisper when it is installed, and the
final timbre/naturalness judgement always needs a human ear.

Usage:
  python e2e_generate.py sfx  [--quant int8] [--prompt "..."] [--seconds 8]
  python e2e_generate.py ttsd [--quant int8] [--minutes 1]
  python e2e_generate.py tts  [--quant int8] [--text "..."] [--ref <参考音频>] [--seconds 6]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "runtime" / "pylibs"))
sys.path.insert(0, str(ROOT / "server"))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from moss_engine import MossEngine, ModelSpec, SAMPLING_RATE  # noqa: E402

CONFIG = json.loads((ROOT / "server" / "config.json").read_text(encoding="utf-8"))
REFS = ROOT / "assets" / "reference"


def resolve(path: str) -> str:
    p = Path(path)
    return str(p if p.is_absolute() else (ROOT / "server" / p).resolve())


def build_engine(quant: str) -> MossEngine:
    specs = {
        key: ModelSpec(
            key, m.get("label", key), m.get("kind", key), resolve(m["path"]), resolve(m["codec_path"]),
            (resolve(m["quant_checkpoint"]) if (m.get("quant_checkpoint") or "").strip() else ""),
            "",
            (resolve(m["voice_file"]) if (m.get("voice_file") or "").strip() else ""),
            (resolve(m["voice_root"]) if (m.get("voice_root") or "").strip() else ""),
        )
        for key, m in CONFIG["models"].items()
    }
    return MossEngine(
        specs,
        quant=quant,
        output_dir=str(ROOT / "outputs"),
        tokenizer_dtype=CONFIG.get("tokenizer_dtype", "float16"),
        tokenizer_device=CONFIG.get("tokenizer_device", "auto"),
        log_sink=lambda m: print("[engine]", m, flush=True),
    )


def analyse(path: Path) -> dict:
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    rms = float(np.sqrt(np.mean(mono**2)))
    peak = float(np.max(np.abs(mono)))
    spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    freqs = np.fft.rfftfreq(len(mono), 1 / sr)
    centroid = float((spec * freqs).sum() / max(spec.sum(), 1e-9))
    flat = float(math.exp(np.mean(np.log(spec + 1e-12))) / max(spec.mean(), 1e-12))
    return {
        "seconds": round(len(mono) / sr, 2),
        "rms_dbfs": round(20 * math.log10(max(rms, 1e-9)), 1),
        "peak_dbfs": round(20 * math.log10(max(peak, 1e-9)), 1),
        "spectral_centroid_hz": round(centroid, 1),
        "spectral_flatness": round(flat, 4),
        "clipped": bool(peak >= 0.999),
    }


def transcribe(path: Path) -> str | None:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    model_dir = os.environ.get("WHISPER_MODEL", str(ROOT / "assets" / "whisper-small"))
    if not Path(model_dir).exists():
        return f"(faster-whisper installed but no model at {model_dir})"
    # Pass an array instead of a path: the local PyAV build is older than what
    # faster-whisper's file decoder expects (`metadata_errors` kwarg).
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if sr != 16000:
        import torch
        import torchaudio

        mono = torchaudio.functional.resample(torch.from_numpy(mono), sr, 16000).numpy()
    model = WhisperModel(model_dir, device="cuda", compute_type="float16")
    segments, info = model.transcribe(mono, language=None, beam_size=1)
    text = " ".join(s.text.strip() for s in segments)
    return f"[{info.language} p={info.language_probability:.2f}] {text}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["sfx", "ttsd", "tts", "vg"])
    ap.add_argument("--quant", default="int8")
    ap.add_argument("--prompt", default="雷声隆隆，雨声淅沥。")
    ap.add_argument("--text", default="大家好，这是单人配音与音色克隆的验收测试，请确认内容完整、音色一致。")
    ap.add_argument("--instruction", default="疲惫沙哑的老年声音缓慢抱怨，带有轻微呻吟。")
    ap.add_argument("--ref", default="", help="参考音频；缺省用音色列表的第一条")
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--minutes", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=1234)
    args = ap.parse_args()

    engine = build_engine(args.quant)
    t0 = time.time()
    if args.kind == "sfx":
        result = engine.generate_sound(args.prompt, seconds=args.seconds, seed=args.seed)
    elif args.kind == "tts":
        presets = engine.voice_presets("tts")
        ref = args.ref or (presets[0]["audio"] if presets else "")
        if not ref:
            raise SystemExit("没有可用参考音频：用 --ref 指定，或在 config.json 的 voice_file/voice_root 放好音色列表")
        print(f"[tts] reference: {ref} | presets: {len(presets)}")
        result = engine.generate_voice_clone(
            args.text,
            prompt_audio=ref,
            seconds=args.seconds,
            seed=args.seed,
        )
    elif args.kind == "vg":
        print(f"[vg] instruction: {args.instruction}")
        result = engine.generate_voice_design(
            args.text,
            args.instruction,
            seconds=args.seconds,
            seed=args.seed,
        )
    else:
        speakers = [
            {
                "tag": "[S1]",
                "ref_audio": str(REFS / "reference_02_s1.wav"),
                "ref_text": "In short, we embarked on a mission to make America great again for all Americans.",
            },
            {
                "tag": "[S2]",
                "ref_audio": str(REFS / "reference_02_s2.wav"),
                "ref_text": "NVIDIA reinvented computing for the first time after 60 years. "
                "In fact, Erwin at IBM knows quite well that the computer has largely been the same since the 60s.",
            },
        ]
        script = (
            "[S1] Listen, let's talk business. China. I'm hearing things. What's the real scoop? "
            "[S2] The pace of innovation there is extraordinary, honestly. "
            "[S1] Extraordinary? I don't like that. Are they winning? "
            "[S2] I wouldn't say winning, but their progress is very promising."
        )
        result = engine.generate_dialogue(script, speakers, max_minutes=args.minutes, seed=args.seed)
    print(f"\n=== generation finished in {time.time() - t0:.1f}s ===")
    for out in result["outputs"]:
        path = Path(out["path"])
        print(f"\n{path.name}: {out['seconds']}s / {out['size_mb']} MB")
        print("  metrics:", analyse(path))
        text = transcribe(path)
        print("  asr    :", "n/a (faster-whisper not installed)" if text is None else text)
    print("\nmeta:", Path(result["meta"]).name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
