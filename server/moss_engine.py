"""MOSS-TTSD / MOSS-SoundEffect inference engine.

One 8.4B model is kept resident at a time (16 GB card): loading a second model unloads
the first. Quantization uses optimum-quanto through transformers' `QuantoConfig`, which
quantizes layer-by-layer while the checkpoint streams in, so peak host RAM stays around
one shard instead of the full bf16 model.
"""
from __future__ import annotations

import functools
import gc
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import soundfile as sf
import torch

LOG = logging.getLogger("moss.engine")

SAMPLING_RATE = 24000          # processor.model_config.sampling_rate
TOKENS_PER_SECOND = 12.5       # 1 s of audio == 12.5 audio tokens
QUANT_CHOICES = ("int8", "int8+convrot", "float8", "none")
# 「int8+convrot」= 同一套 quanto int8，但 checkpoint 里少数层的权重在 RHT 旋转基（名单见该目录的 convrot.json）；
# 本模型端到端实测：int8 4.684% → 只转 3 层 1.483%（全层旋转反而 2.899%）。


def setup_cuda_backends() -> None:
    """The model card disables the broken cuDNN SDPA backend and keeps the fallbacks."""
    try:
        torch.backends.cuda.enable_cudnn_sdp(False)
        torch.backends.cuda.enable_flash_sdp(True)
        torch.backends.cuda.enable_mem_efficient_sdp(True)
        torch.backends.cuda.enable_math_sdp(True)
    except Exception:  # noqa: BLE001 - older torch builds lack some switches
        LOG.warning("could not configure torch SDPA backends", exc_info=True)


def resolve_attn_implementation(dtype: torch.dtype, device: str) -> str:
    import importlib.util

    if device == "cuda" and dtype in (torch.float16, torch.bfloat16):
        if importlib.util.find_spec("flash_attn") is not None:
            major, _ = torch.cuda.get_device_capability()
            if major >= 8:
                return "flash_attention_2"
        return "sdpa"
    return "eager" if device == "cpu" else "sdpa"


@dataclass
class ModelSpec:
    key: str
    label: str
    kind: str            # "ttsd" | "sfx" | "tts" | "vg"
    path: str
    codec_path: str
    quant_checkpoint: str = ""            # optional on-disk quanto checkpoint (fast startup)
    quant_checkpoint_convrot: str = ""    # 同上，但少数层权重在 RHT 旋转基（需运行时挂激活旋转钩子）
    # kind == "tts"（单人配音 / 音色克隆）：本地参考音色列表
    voice_file: str = ""
    voice_root: str = ""


@dataclass
class LoadedModel:
    spec: ModelSpec
    processor: Any
    model: Any
    quant: str
    load_seconds: float
    torch_dtype: torch.dtype
    loaded_at: float = field(default_factory=time.time)


def _mem_info() -> dict:
    info: dict[str, Any] = {}
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        info["vram_used_gb"] = round((total - free) / 1e9, 2)
        info["vram_total_gb"] = round(total / 1e9, 2)
    info["ram_used_gb"] = None
    try:
        import psutil  # noqa: PLC0415

        vm = psutil.virtual_memory()
        info["ram_used_gb"] = round((vm.total - vm.available) / 1e9, 2)
        info["ram_total_gb"] = round(vm.total / 1e9, 2)
    except Exception:  # noqa: BLE001
        pass
    return info


def _has_full_precision_weights(path: str) -> bool:
    """A model dir keeps its config/tokenizer/remote code even after the big weights are
    moved off the system drive; online quantization and fp8 need those weights back."""
    root = Path(path)
    if any((root / name).exists() for name in ("model.safetensors", "pytorch_model.bin")):
        return True
    return bool(list(root.glob("model-*-of-*.safetensors")))


def available_quants(spec: "ModelSpec") -> list[str]:
    """该模型当前**真正可用**的量化档，**第一个即默认档**（= 已优化的落盘产物）。

    判据是数据而不是硬编码名单，所以权重增减会自动反映到界面：
      - `int8`：落盘 checkpoint 在位（部署走的优化产物）**或**完整精度权重在位（可在线量化）
      - `int8+convrot`：仅当该模型配了旋转基 checkpoint（`convrot.json` 那套）
      - `float8` / `none`：必须有完整精度权重 —— 2026-10-14 母本全部删除后它们自动从可选列表消失，
        把权重放回（或重下）后自动恢复，不需要改代码。
    """
    has_ckpt = bool(spec.quant_checkpoint) and os.path.isfile(
        os.path.join(spec.quant_checkpoint, "model.safetensors")
    )
    has_rot = bool(spec.quant_checkpoint_convrot) and os.path.isfile(
        os.path.join(spec.quant_checkpoint_convrot, "model.safetensors")
    )
    has_full = _has_full_precision_weights(spec.path)
    quants: list[str] = []
    if has_ckpt or has_full:
        quants.append("int8")
    if has_rot:
        quants.append("int8+convrot")
    if has_full:
        quants += ["float8", "none"]
    return quants


def _from_pretrained_dtype(cls, path: str, dtype: torch.dtype, **kwargs):
    """transformers 5 renamed `torch_dtype` to `dtype`; support both."""
    try:
        return cls.from_pretrained(path, dtype=dtype, **kwargs)
    except TypeError:
        return cls.from_pretrained(path, torch_dtype=dtype, **kwargs)


def _install_convrot_hooks(model, checkpoint_dir: str, log) -> int:
    """落盘 checkpoint 若带 `convrot.json`（少数层的权重在旋转基），必须为这些层旋转激活。

    名单由 checkpoint 自己声明（见 `convrot_runtime.py` 与归档 `quantformats/quanto_ondisk.py --rot-topk`）；
    没有该文件就是普通 checkpoint，不做任何事。
    """
    import sys

    server_dir = str(Path(__file__).resolve().parent)
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)
    try:
        from convrot_runtime import install_convrot_hooks
    except ImportError as exc:  # 部署缺文件时宁可明确报错，也不要静默算出错结果
        log(f"convrot: 该 checkpoint 声明了旋转基，但运行时支持缺失（{exc}）——结果会错，请检查 server/convrot_runtime.py")
        return 0
    return install_convrot_hooks(model, checkpoint_dir, log=log)


# 四个生成场景 -> outputs 下的子目录名（产物按场景分目录存放）
# 注意：引擎内部对「音色设计」用的 kind 是 voicegen（HTTP 路由键是 vg），两个都映射到同一目录。
SCENE_DIRS = {
    "tts": "单人配音",
    "vg": "音色设计",
    "voicegen": "音色设计",
    "ttsd": "多人对话",
    "sfx": "音效生成",
}


class MossEngine:
    def __init__(
        self,
        specs: dict[str, ModelSpec],
        *,
        quant: str = "int8",
        device: str = "cuda",
        output_dir: str,
        attn_implementation: str = "auto",
        tokenizer_dtype: str = "float16",
        tokenizer_device: str = "auto",
        tokenizer_swap: bool = True,
        log_sink=None,
        artifact_lock=None,
        active_outputs: Optional[dict[str, int]] = None,
    ) -> None:
        if quant not in QUANT_CHOICES:
            raise ValueError(f"quant must be one of {QUANT_CHOICES}")
        self.specs = specs
        self.quant = quant
        self.device = device if torch.cuda.is_available() else "cpu"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for _scene in SCENE_DIRS.values():
            (self.output_dir / _scene).mkdir(parents=True, exist_ok=True)
        self.attn_implementation = attn_implementation
        self.tokenizer_dtype = getattr(torch, tokenizer_dtype)
        self.tokenizer_dtype_name = tokenizer_dtype
        self.tokenizer_device = tokenizer_device
        self.tokenizer_swap = tokenizer_swap
        self.log_sink = log_sink or (lambda msg: LOG.info("%s", msg))
        self._loaded: Optional[LoadedModel] = None
        self._codec_swap = False
        self._voice_cache: Optional[list[dict]] = None
        self._lock = threading.RLock()
        self.artifact_lock = artifact_lock or threading.RLock()
        self.active_outputs: dict[str, int] = active_outputs if active_outputs is not None else {}

    # ------------------------------------------------------------------ status
    def state(self) -> dict:
        with self._lock:
            loaded = self._loaded
            codec_paths = sorted({s.codec_path for s in self.specs.values() if s.codec_path})
            return {
                "device": self.device,
                "default_quant": self.quant,
                "quant_choices": list(QUANT_CHOICES),
                "models": [
                    {
                        "key": s.key,
                        "label": s.label,
                        "kind": s.kind,
                        "codec_path": s.codec_path,
                        "path": s.path,
                        "exists": os.path.isdir(s.path),
                        "loaded": bool(loaded and loaded.spec.key == s.key),
                        "quant": loaded.quant if loaded and loaded.spec.key == s.key else None,
                        "quant_checkpoint": s.quant_checkpoint,
                        # 该模型真正可用的档；第一个 = 默认（已优化的落盘产物）。UI 只列这些。
                        "quants": available_quants(s),
                        "size_gb": round(_model_disk_gb(s), 2),
                    }
                    for s in self.specs.values()
                ],
                "loaded": (
                    None
                    if loaded is None
                    else {
                        "key": loaded.spec.key,
                        "label": loaded.spec.label,
                        "quant": loaded.quant,
                        "load_seconds": round(loaded.load_seconds, 1),
                        "dtype": str(loaded.torch_dtype).replace("torch.", ""),
                        "loaded_at": loaded.loaded_at,
                    }
                ),
                # codec（音频 tokenizer）是四个模型共用的，体积单独报一份，不混进每个模型的 size_gb
                "codec": {
                    "path": codec_paths[0] if len(codec_paths) == 1 else f"（{len(codec_paths)} 个路径）",
                    "size_gb": round(sum(_dir_size(p) for p in codec_paths) / 1e9, 2),
                },
                "memory": _mem_info(),
                "output_dir": str(self.output_dir),
            }

    # ------------------------------------------------------------------- load
    def load(self, key: str, quant: Optional[str] = None) -> dict:
        spec = self.specs.get(key)
        if spec is None:
            raise KeyError(f"unknown model {key!r}")
        if not os.path.isdir(spec.path):
            raise FileNotFoundError(f"model directory missing: {spec.path}")
        quant = quant or self.quant
        with self._lock:
            if self._loaded is not None and self._loaded.spec.key == key and self._loaded.quant == quant:
                self.log_sink(f"{spec.label} already loaded ({quant})")
                return self.state()
            self.unload()
            started = time.time()
            self.log_sink(f"加载 {spec.label}（量化={quant}）…")
            processor, model, dtype = self._load_pair(spec, quant)
            gc.collect()
            if self.device == "cuda":
                torch.cuda.empty_cache()
            self._loaded = LoadedModel(spec, processor, model, quant, time.time() - started, dtype)
            mem = _mem_info()
            alloc = reserved = 0.0
            if self.device == "cuda":
                alloc = torch.cuda.memory_allocated() / 1e9
                reserved = torch.cuda.memory_reserved() / 1e9
            self.log_sink(
                f"{spec.label} 就绪，用时 {self._loaded.load_seconds:.1f}s，"
                f"显存 {mem.get('vram_used_gb')}/{mem.get('vram_total_gb')} GB"
                f"（张量 {alloc:.2f} GB / 缓存 {reserved:.2f} GB）"
            )
            return self.state()

    def unload(self) -> dict:
        with self._lock:
            if self._loaded is None:
                return self.state()
            key = self._loaded.spec.key
            self._loaded = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
            self.log_sink(f"已卸载 {key}")
            return self.state()

    def _load_pair(self, spec: ModelSpec, quant: str):
        from transformers import AutoModel

        dtype = torch.bfloat16
        attn = self.attn_implementation
        if attn == "auto":
            attn = resolve_attn_implementation(dtype, self.device)

        processor = self._load_processor(spec)
        # `AutoProcessor` loads the codec in fp32 (~7 GB host RAM). Swap it for a
        # bf16 copy on the target device so the 8B model still has room.
        processor.audio_tokenizer = None
        gc.collect()
        codec_device = self._codec_device()
        codec_dtype = torch.float32 if codec_device == "cpu" else self.tokenizer_dtype
        codec = _from_pretrained_dtype(
            AutoModel,
            spec.codec_path,
            codec_dtype,
            trust_remote_code=True,
            attn_implementation="eager",
        ).eval()
        codec = codec.to(device=codec_device, dtype=codec_dtype)
        processor.audio_tokenizer = codec
        self._codec_swap = bool(
            self.tokenizer_swap and codec_device == "cuda" and self.tokenizer_dtype != torch.float32
        )
        apply_codec_autocast(
            processor,
            self.tokenizer_dtype
            if codec_device == "cuda" and self.tokenizer_dtype != torch.float32
            else None,
        )
        self.log_sink(
            f"音频 tokenizer 已就绪（{self.tokenizer_dtype_name} @ {codec_device}）"
        )

        model = self._load_llm(spec, quant, dtype, attn)
        return processor, model, dtype

    @staticmethod
    def _load_processor(spec: ModelSpec):
        """`AutoProcessor` forwards its own kwargs (e.g. `revision`) into the remote
        processor's constructor, which rejects unknown keys -- call the dynamic class
        from `auto_map` directly instead."""
        import json as _json

        cfg_path = Path(spec.path) / "processor_config.json"
        if cfg_path.exists():
            auto_map = _json.loads(cfg_path.read_text(encoding="utf-8")).get("auto_map", {})
            target = auto_map.get("AutoProcessor")
            if target:
                from transformers.dynamic_module_utils import get_class_from_dynamic_module

                cls = get_class_from_dynamic_module(target, spec.path, trust_remote_code=True)
                return cls.from_pretrained(
                    spec.path, trust_remote_code=True, codec_path=spec.codec_path
                )
        from transformers import AutoProcessor

        return AutoProcessor.from_pretrained(
            spec.path, trust_remote_code=True, codec_path=spec.codec_path
        )

    def _codec_device(self) -> str:
        """fp32 codec (~7 GB) only fits next to an 8.4B model on a big card; otherwise CPU."""
        if self.tokenizer_device in ("cpu", "cuda"):
            return self.tokenizer_device
        if self.device != "cuda":
            return "cpu"
        if self.tokenizer_dtype in (torch.float16, torch.bfloat16):
            return "cuda"
        _, total = torch.cuda.mem_get_info()
        return "cuda" if total / 1e9 >= 24 else "cpu"

    def _load_llm(self, spec: ModelSpec, quant: str, dtype: torch.dtype, attn: str):
        from transformers import AutoModel

        kwargs: dict[str, Any] = {
            "trust_remote_code": True,
            "attn_implementation": attn,
        }
        # 「int8+convrot」= 同一套 quanto int8，只换 checkpoint（少数层权重在旋转基，需挂激活旋转钩子）
        convrot_ckpt = spec.quant_checkpoint_convrot if (spec.quant_checkpoint_convrot and "convrot" in quant.lower()) else ""
        checkpoint = convrot_ckpt or spec.quant_checkpoint
        effective_quant = "int8" if convrot_ckpt else quant
        if checkpoint and os.path.isdir(checkpoint):
            model = self._load_quant_checkpoint(spec, effective_quant, dtype, checkpoint)
            if model is not None:
                return model
        if effective_quant != "none":
            if not _has_full_precision_weights(spec.path):
                raise RuntimeError(
                    f"{spec.label} 的完整精度权重不在 {spec.path}（为腾出系统盘空间已移出）。"
                    f"请选 int8（走落盘量化权重），或把 model.safetensors 放回该目录后再用 {effective_quant}。"
                )
            from transformers import QuantoConfig

            qcfg = QuantoConfig(weights="int8" if effective_quant == "int8" else "float8", activations=None)
            try:
                model = _from_pretrained_dtype(
                    AutoModel,
                    spec.path,
                    dtype,
                    quantization_config=qcfg,
                    device_map={"": self.device},
                    low_cpu_mem_usage=True,
                    **kwargs,
                )
                self.log_sink(f"已按 {effective_quant} 逐层量化加载（流式）")
                return model.eval()
            except Exception as exc:  # noqa: BLE001
                self.log_sink(f"流式量化加载失败（{exc}），退回 CPU 载入后量化")
                gc.collect()

            from optimum.quanto import freeze, qfloat8, qint8, quantize

            model = _from_pretrained_dtype(AutoModel, spec.path, dtype, **kwargs)
            quantize(model, weights=qint8 if effective_quant == "int8" else qfloat8, activations=None)
            freeze(model)
            return model.to(self.device).eval()

        # unquantized: 8.4B bf16 does not fit 16 GB, let accelerate place it
        if not _has_full_precision_weights(spec.path):
            raise RuntimeError(
                f"{spec.label} 的完整精度权重不在 {spec.path}（为腾出系统盘空间已移出）。"
                f"bf16 直跑需把 model.safetensors 放回；int8 请用落盘量化权重。"
            )
        try:
            model = _from_pretrained_dtype(
                AutoModel,
                spec.path,
                dtype,
                device_map="auto",
                low_cpu_mem_usage=True,
                max_memory={0: "15GiB", "cpu": "26GiB"},
                **kwargs,
            )
        except TypeError:
            model = _from_pretrained_dtype(AutoModel, spec.path, dtype, **kwargs).to(self.device)
        return model.eval()

    def _load_quant_checkpoint(self, spec: ModelSpec, quant: str, dtype: torch.dtype, checkpoint: str = ""):
        """Load a `tools/quantize.py` artefact: quanto's own qmap + int8/fp8 shards."""
        from transformers import AutoModel
        from optimum.quanto.models.transformers_models import QuantizedTransformersModel

        class _QuantizedAutoModel(QuantizedTransformersModel):
            auto_class = _trust_remote_auto_model(AutoModel)

        try:
            model = _QuantizedAutoModel.from_pretrained(
                checkpoint or spec.quant_checkpoint, dtype=dtype, trust_remote_code=True
            )
            model = model.to(self.device).eval()
            rotated = _install_convrot_hooks(model, checkpoint or spec.quant_checkpoint, self.log_sink)
            self.log_sink(
                f"已从落盘量化权重加载（{checkpoint or spec.quant_checkpoint}，quant={quant}）"
                + (f"，其中 {rotated} 层在旋转基（已挂激活旋转钩子）" if rotated else "")
            )
            return model
        except Exception as exc:  # noqa: BLE001
            self.log_sink(f"落盘量化权重加载失败（{exc}），回退到在线量化")
            return None

    # -------------------------------------------------------------- inference
    def _ensure(self, key: str) -> LoadedModel:
        with self._lock:
            if self._loaded is None or self._loaded.spec.key != key:
                self.load(key)
            assert self._loaded is not None
            return self._loaded

    def generate_sound(
        self,
        prompt: str,
        *,
        seconds: float = 10.0,
        tokens: Optional[int] = None,
        seed: int = 0,
        temperature: float = 1.5,
        top_p: float = 0.6,
        top_k: int = 50,
        repetition_penalty: float = 1.2,
        num_takes: int = 1,
    ) -> dict:
        loaded = self._ensure("sfx")
        processor, model = loaded.processor, loaded.model
        if tokens is None:
            tokens = max(1, int(round(seconds * TOKENS_PER_SECOND)))
        wavs: list[np.ndarray] = []
        for take in range(num_takes):
            if seed:
                torch.manual_seed(seed + take)
            self._codec_to("cpu")
            conversations = [[processor.build_user_message(ambient_sound=prompt, tokens=tokens)]]
            batch = processor(conversations, mode="generation")
            input_ids = batch["input_ids"].to(self.device)
            attention_mask = batch["attention_mask"].to(self.device)
            started = time.time()
            with torch.no_grad():
                outputs = self._generate(
                    model,
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=tokens + 128,
                    audio_temperature=temperature,
                    audio_top_p=top_p,
                    audio_top_k=top_k,
                    audio_repetition_penalty=repetition_penalty,
                )
            self._codec_to("cuda")
            wavs.append(_first_waveform(processor, outputs, self.log_sink))
            del outputs, batch, input_ids, attention_mask
            self._free_gpu()
            self.log_sink(
                f"音效第 {take + 1}/{num_takes} 条完成，用时 {time.time() - started:.1f}s"
            )
        return self._save(
            wavs,
            "sfx",
            {
                "prompt": prompt,
                "tokens": tokens,
                "seed": seed,
                "takes": num_takes,
                "quant": loaded.quant,
                "quant_checkpoint": loaded.spec.quant_checkpoint,
                "quant_checkpoint_convrot": loaded.spec.quant_checkpoint_convrot,
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "repetition_penalty": repetition_penalty,
            },
        )

    def generate_dialogue(
        self,
        script: str,
        speakers: list[dict],
        *,
        max_minutes: float = 3.0,
        seed: int = 0,
        temperature: float = 1.1,
        top_p: float = 0.9,
        top_k: int = 50,
        repetition_penalty: float = 1.1,
        num_takes: int = 1,
    ) -> dict:
        """speakers: [{"ref_audio": path, "ref_text": "[S1] ..."}, ...] in script order."""
        loaded = self._ensure("ttsd")
        processor, model = loaded.processor, loaded.model
        if not speakers:
            raise ValueError("至少需要一个说话人参考音频")

        ref_wavs, prompt_texts = [], []
        for i, spk in enumerate(speakers):
            wav = _load_wav(spk["ref_audio"])
            ref_wavs.append(wav)
            tag = spk.get("tag") or f"[S{i + 1}]"
            transcript = (spk.get("ref_text") or "").strip()
            if not transcript:
                self.log_sink(
                    f"⚠️ 说话人 {tag} 没填参考音频逐字稿：韵律对齐会变差（可在页面上点「识别逐字稿」自动转写）"
                )
            prompt_texts.append(f"{tag} {transcript}".strip())

        reference_codes = _timed(self.log_sink, "参考音频编码", lambda: processor.encode_audios_from_wav(ref_wavs, sampling_rate=SAMPLING_RATE))
        concat_prompt = torch.cat(ref_wavs, dim=-1)
        prompt_audio = _timed(
            self.log_sink,
            "提示音频编码",
            lambda: processor.encode_audios_from_wav([concat_prompt], sampling_rate=SAMPLING_RATE)[0],
        )

        full_text = " ".join(prompt_texts) + " " + script.strip()
        max_new_tokens = max(256, int(round(max_minutes * 60 * TOKENS_PER_SECOND)))

        wavs: list[np.ndarray] = []
        for take in range(num_takes):
            if seed:
                torch.manual_seed(seed + take)
            self._codec_to("cpu")
            conversations = [
                [
                    processor.build_user_message(text=full_text, reference=reference_codes),
                    processor.build_assistant_message(audio_codes_list=[prompt_audio]),
                ]
            ]
            batch = processor(conversations, mode="continuation")
            input_ids = batch["input_ids"].to(self.device)
            attention_mask = batch["attention_mask"].to(self.device)
            started = time.time()
            with torch.no_grad():
                outputs = self._generate(
                    model,
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=max_new_tokens,
                    audio_temperature=temperature,
                    audio_top_p=top_p,
                    audio_top_k=top_k,
                    audio_repetition_penalty=repetition_penalty,
                )
            self._codec_to("cuda")
            wav = _first_waveform(processor, outputs, self.log_sink)
            wavs.append(wav)
            del outputs, batch, input_ids, attention_mask
            self._free_gpu()
            self.log_sink(
                f"对话第 {take + 1}/{num_takes} 条完成：{len(wav) / SAMPLING_RATE:.1f}s，"
                f"用时 {time.time() - started:.1f}s"
            )
        return self._save(
            wavs,
            "ttsd",
            {
                "script": script,
                "speakers": [
                    {"tag": s.get("tag"), "ref_text": s.get("ref_text"), "ref_audio": s.get("ref_audio")}
                    for s in speakers
                ],
                "max_minutes": max_minutes,
                "seed": seed,
                "takes": num_takes,
                "quant": loaded.quant,
                "quant_checkpoint": loaded.spec.quant_checkpoint,
                "quant_checkpoint_convrot": loaded.spec.quant_checkpoint_convrot,
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "repetition_penalty": repetition_penalty,
            },
        )

    # ------------------------------------------------------- single speaker
    def voice_presets(self, key: str = "tts") -> list[dict]:
        """音色列表：本地参考音频 + 示例文本（与独立版 MOSS-TTS 演示同一份 wav/jsonl）。"""
        spec = self.specs.get(key)
        if spec is None or not spec.voice_file:
            return []
        if self._voice_cache is not None:
            return self._voice_cache
        entries: list[dict] = []
        voice_file = Path(spec.voice_file)
        if voice_file.is_file():
            root = Path(spec.voice_root) if spec.voice_root else voice_file.parent
            for line in voice_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:  # noqa: BLE001 - 单行坏数据不该让整个列表消失
                    continue
                relative = str(payload.get("role", "")).strip()
                text = str(payload.get("text", "")).strip()
                if not relative:
                    continue
                audio = (root / relative).resolve()
                if not audio.is_file():
                    continue
                entries.append(
                    {
                        "id": f"voice-{len(entries) + 1}",
                        "name": str(payload.get("name", "")).strip() or audio.stem,
                        "audio": str(audio),
                        "text": text,
                    }
                )
        self._voice_cache = entries
        return entries

    def generate_voice_clone(
        self,
        text: str,
        *,
        prompt_audio: str,
        num_takes: int = 1,
        seconds: float = 0.0,
        tokens: Optional[int] = None,
        language: str = "",
        seed: int = 0,
        temperature: float = 1.7,
        top_p: float = 0.8,
        top_k: int = 25,
        repetition_penalty: float = 1.0,
    ) -> dict:
        """零样本音色克隆：一段参考音频 + 待转文本 → 同一音色的单人配音。

        官方配方（MOSS-TTS-v1.5 model card「Voice cloning」）：`build_user_message(text, reference=[音频])`
        + `mode="generation"`，与 MOSS-TTSD/SoundEffect 共用同一套 MossTTSDelay 处理器。

        参考音频在这里自己解码 + 编码成 audio codes 再传进去：处理器的路径分支会走
        `torchaudio.load`，而本机 torchaudio 2.10 委托的 torchcodec 原生库加载不了
        （`Could not load this library: ...libtorchcodec_image.dll`）；用 soundfile 解码
        （`_load_wav`）后走 `encode_audios_from_wav`，与 ttsd 的续写路径同款，顺带把
        codec 的显存腾挪留在生成阶段。
        """
        loaded = self._ensure("tts")
        processor, model = loaded.processor, loaded.model
        if not str(text or "").strip():
            raise ValueError("text is required")
        prompt_path = Path(prompt_audio).expanduser()
        if not prompt_path.is_file():
            raise FileNotFoundError(f"参考音频不存在: {prompt_audio}")

        if tokens is None and seconds:
            tokens = max(1, int(round(float(seconds) * TOKENS_PER_SECOND)))
        max_new_tokens = int(tokens) if tokens else 4096

        ref_wav = _load_wav(str(prompt_path))
        reference_codes = _timed(
            self.log_sink,
            "参考音频编码",
            lambda: processor.encode_audios_from_wav([ref_wav], sampling_rate=SAMPLING_RATE),
        )
        message_kwargs: dict[str, Any] = {"text": str(text).strip(), "reference": reference_codes}
        if tokens:
            message_kwargs["tokens"] = int(tokens)
        if language.strip():
            message_kwargs["language"] = language.strip()
        message = processor.build_user_message(**message_kwargs)

        wavs: list[np.ndarray] = []
        for take in range(max(1, int(num_takes))):
            if seed:
                torch.manual_seed(int(seed) + take)
            # 生成阶段把 codec 让给主模型的 KV cache（与 ttsd/sfx 同一套显存腾挪）
            self._codec_to("cpu")
            conversations = [[message]]
            batch = processor(conversations, mode="generation")
            input_ids = batch["input_ids"].to(self.device)
            attention_mask = batch["attention_mask"].to(self.device)
            started_at = time.time()
            with torch.no_grad():
                outputs = self._generate(
                    model,
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=max_new_tokens,
                    audio_temperature=temperature,
                    audio_top_p=top_p,
                    audio_top_k=top_k,
                    audio_repetition_penalty=repetition_penalty,
                )
            self._codec_to("cuda")
            wav = _first_waveform(processor, outputs, self.log_sink)
            wavs.append(wav)
            del outputs, batch, input_ids, attention_mask
            self._free_gpu()
            self.log_sink(
                f"单人配音第 {take + 1}/{num_takes} 条完成：{len(wav) / SAMPLING_RATE:.1f}s，"
                f"用时 {time.time() - started_at:.1f}s"
            )
        return self._save(
            wavs,
            "tts",
            {
                "text": str(text).strip(),
                "prompt_audio": str(prompt_path),
                "language": language.strip(),
                "seconds": seconds,
                "tokens": max_new_tokens,
                "seed": seed,
                "takes": int(num_takes),
                "quant": loaded.quant,
                "quant_checkpoint": loaded.spec.quant_checkpoint,
                "quant_checkpoint_convrot": loaded.spec.quant_checkpoint_convrot,
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "repetition_penalty": repetition_penalty,
            },
            sample_rate=int(getattr(processor.model_config, "sampling_rate", SAMPLING_RATE)),
        )

    def generate_voice_design(
        self,
        text: str,
        instruction: str,
        *,
        key: str = "vg",
        num_takes: int = 1,
        seconds: float = 0.0,
        tokens: Optional[int] = None,
        language: str = "",
        seed: int = 0,
        temperature: float = 1.5,
        top_p: float = 0.6,
        top_k: int = 50,
        repetition_penalty: float = 1.1,
    ) -> dict:
        """音色设计：自由文本描述 + 待转文本 → 目标音色/情绪的配音，**无需参考音频**。

        官方配方（MOSS-VoiceGenerator model card）：`build_user_message(text, instruction)`
        + `mode="generation"`。描述与文本一起 tokenize 后送同一个 MossTTSDelay 模型
        （1.7B，与 8B 的单人配音/对话共用处理器代码），因此这里不碰参考音频，
        codec 只在末尾解码时用得上。模型卡推荐采样 1.5 / 0.6 / 50 / 1.1。
        """
        loaded = self._ensure(key)
        processor, model = loaded.processor, loaded.model
        if not str(text or "").strip():
            raise ValueError("text is required")
        if not str(instruction or "").strip():
            raise ValueError("instruction is required")

        if tokens is None and seconds:
            tokens = max(1, int(round(float(seconds) * TOKENS_PER_SECOND)))
        max_new_tokens = int(tokens) if tokens else 4096

        message_kwargs: dict[str, Any] = {
            "text": str(text).strip(),
            "instruction": str(instruction).strip(),
        }
        if tokens:
            message_kwargs["tokens"] = int(tokens)
        if language.strip():
            message_kwargs["language"] = language.strip()
        message = processor.build_user_message(**message_kwargs)

        wavs: list[np.ndarray] = []
        for take in range(max(1, int(num_takes))):
            if seed:
                torch.manual_seed(int(seed) + take)
            # 生成阶段把 codec 让给主模型的 KV cache（与 ttsd/sfx/单人配音同一套显存腾挪）
            self._codec_to("cpu")
            conversations = [[message]]
            batch = processor(conversations, mode="generation")
            input_ids = batch["input_ids"].to(self.device)
            attention_mask = batch["attention_mask"].to(self.device)
            started_at = time.time()
            with torch.no_grad():
                outputs = self._generate(
                    model,
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=max_new_tokens,
                    audio_temperature=temperature,
                    audio_top_p=top_p,
                    audio_top_k=top_k,
                    audio_repetition_penalty=repetition_penalty,
                )
            self._codec_to("cuda")
            wav = _first_waveform(processor, outputs, self.log_sink)
            wavs.append(wav)
            del outputs, batch, input_ids, attention_mask
            self._free_gpu()
            self.log_sink(
                f"音色设计第 {take + 1}/{num_takes} 条完成：{len(wav) / SAMPLING_RATE:.1f}s，"
                f"用时 {time.time() - started_at:.1f}s"
            )
        return self._save(
            wavs,
            "voicegen",
            {
                "text": str(text).strip(),
                "instruction": str(instruction).strip(),
                "language": language.strip(),
                "seconds": seconds,
                "tokens": max_new_tokens,
                "seed": seed,
                "takes": int(num_takes),
                "quant": loaded.quant,
                "quant_checkpoint": loaded.spec.quant_checkpoint,
                "quant_checkpoint_convrot": loaded.spec.quant_checkpoint_convrot,
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "repetition_penalty": repetition_penalty,
            },
            sample_rate=int(getattr(processor.model_config, "sampling_rate", SAMPLING_RATE)),
        )

    def _generate(self, model, **kwargs):
        """`model.generate` + 一次显存不足降级重试（清缓存 + 生成长度砍到 60%）。

        Windows 上 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments` 不可用（实测只有告警、无收益），
        所以抗 OOM 靠三件事：生成期把 codec 让到 CPU（`_codec_to`）、每个 take 结束清缓存
        （`_free_gpu`）、以及这里的最后一次降级。仍失败就抛出，让任务明确失败而不是卡死。
        """
        try:
            return model.generate(**kwargs)
        except torch.cuda.OutOfMemoryError:
            gc.collect()
            torch.cuda.empty_cache()
            before = int(kwargs.get("max_new_tokens") or 0)
            after = max(64, int(before * 0.6)) if before else 0
            if not after:
                raise
            self.log_sink(
                f"显存不足：已清缓存，生成长度 {before} → {after} token 重试一次"
                "（再失败请降低时长上限 / 生成条数）"
            )
            kwargs["max_new_tokens"] = after
            return model.generate(**kwargs)

    def _codec_to(self, device: str) -> None:
        """Move codec with recovery; use float32 on CPU for safe codec execution."""
        loaded = self._loaded
        if not self._codec_swap or loaded is None:
            return
        codec = getattr(loaded.processor, "audio_tokenizer", None)
        if codec is None:
            return
        params = iter(codec.parameters())
        first = next(params, None)
        if first is None:
            return
        if first.device.type == device and all(p.device.type == device for p in params):
            return
        started = time.time()
        dtype = torch.float32 if device == "cpu" else self.tokenizer_dtype
        try:
            codec.to(device=device, dtype=dtype)
            if any(p.device.type != device for p in codec.parameters()):
                raise RuntimeError(f"audio codec did not fully move to {device}")
        except Exception:
            self._loaded = None
            self._codec_swap = False
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
            raise
        self._free_gpu()
        free, _ = torch.cuda.mem_get_info() if self.device == "cuda" else (0, 0)
        self.log_sink(
            f"codec 移至 {device}（{time.time() - started:.1f}s），当前显存余量 {free / 1e9:.2f} GB"
        )


    def recover_codec_after_failure(self) -> None:
        """Restore the codec to its normal device, or invalidate the cached pair."""
        loaded = self._loaded
        if loaded is None or not self._codec_swap:
            return
        codec = getattr(loaded.processor, "audio_tokenizer", None)
        if codec is None:
            return
        try:
            codec.to(device="cuda", dtype=self.tokenizer_dtype)
            if any(p.device.type != "cuda" for p in codec.parameters()):
                raise RuntimeError("audio codec did not restore fully to cuda")
        except Exception:
            self._loaded = None
            self._codec_swap = False
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
            raise
    def _free_gpu(self) -> None:
        gc.collect()
        if self.device == "cuda":
            torch.cuda.empty_cache()

    def _scene_dir(self, kind: str) -> Path:
        """产物落盘目录：outputs/<场景>/（未知 kind 落到同名子目录并自动创建）。"""
        d = self.output_dir / SCENE_DIRS.get(kind, kind)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save(
        self,
        wavs: Iterable[np.ndarray],
        kind: str,
        meta: dict,
        sample_rate: int = SAMPLING_RATE,
    ) -> dict:
        wavs = list(wavs)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        scene_dir = self._scene_dir(kind)
        arrays = _limit_shared_peak(wavs, self.log_sink)
        written: list[dict] = []
        output_keys = [str((scene_dir / f"{kind}_{stamp}{f'_{i + 1}' if len(wavs) > 1 else ''}.wav").resolve()) for i in range(len(wavs))]
        output_keys.append(str((scene_dir / f"{kind}_{stamp}.json").resolve()))
        with self.artifact_lock:
            for key in output_keys:
                self.active_outputs[key] = self.active_outputs.get(key, 0) + 1
            try:
                for i, wav in enumerate(arrays):
                    suffix = f"_{i + 1}" if len(arrays) > 1 else ""
                    path = scene_dir / f"{kind}_{stamp}{suffix}.wav"
                    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
                    try:
                        sf.write(str(temp), wav, int(sample_rate), subtype="PCM_16", format="WAV")
                        os.replace(temp, path)
                    finally:
                        temp.unlink(missing_ok=True)
                    written.append({"path": str(path), "name": path.relative_to(self.output_dir).as_posix(),
                                    "seconds": round(len(wav) / float(sample_rate), 2),
                                    "size_mb": round(path.stat().st_size / 1e6, 2)})
                return self._finalize(kind, stamp, written, meta)
            finally:
                for key in output_keys:
                    count = self.active_outputs.get(key, 0)
                    if count <= 1:
                        self.active_outputs.pop(key, None)
                    else:
                        self.active_outputs[key] = count - 1

    def _finalize(self, kind: str, stamp: str, written: list[dict], meta: dict) -> dict:
        meta_path = self._scene_dir(kind) / f"{kind}_{stamp}.json"
        temp = meta_path.with_name(f".{meta_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp.write_text(json.dumps({**meta, "outputs": written}, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, meta_path)
        finally:
            temp.unlink(missing_ok=True)
        return {"kind": kind, "outputs": written, "meta": str(meta_path)}



def _limit_shared_peak(wavs: list[np.ndarray], log=None, ceiling_db: float = -1.0) -> list[np.ndarray]:
    """Apply one attenuation-only gain to all takes before PCM quantization."""
    peak = max((float(np.max(np.abs(wav))) for wav in wavs if wav.size), default=0.0)
    limit = 10 ** (ceiling_db / 20.0)
    if peak <= limit or peak <= 0.0:
        return wavs
    gain = limit / peak
    if log is not None:
        log(f"共享峰值 {20 * np.log10(peak):.1f} dBFS 超限，全部音频衰减 {20 * np.log10(gain):.1f} dB")
    return [wav * gain for wav in wavs]


def _model_disk_gb(spec: "ModelSpec") -> float:
    """该模型实际占用的落盘体积（GB）= 权重壳 + 落盘量化产物，两者不重复计数。

    只算 `spec.path` 会得到 0.02 GB —— 权重搬进 `quant_checkpoint`（或 F: 母本盘）后，壳里只剩
    配置/分词/远程代码；2026-10-14 修掉的正是这个显示错误。
    """
    shell = _dir_size(spec.path) if os.path.isdir(spec.path) else 0
    ckpt = 0
    if spec.quant_checkpoint and os.path.isdir(spec.quant_checkpoint):
        a, b = os.path.abspath(spec.quant_checkpoint), os.path.abspath(spec.path)
        try:
            inside = os.path.commonpath([a, b]) == b
        except ValueError:  # 不同盘符
            inside = False
        if not inside:
            ckpt = _dir_size(spec.quant_checkpoint)
    return (shell + ckpt) / 1e9


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _load_wav(path: str) -> torch.Tensor:
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    wav = torch.from_numpy(data.T)  # [C, T]
    if wav.shape[0] > 1:
        # 多声道一律混成单声道：MOSS 的参考音频按单声道处理。不混的话，
        # 立体声参考得到 [2, T]、单声道得到 [1, T]，多人对话里
        # `torch.cat(ref_wavs, dim=-1)` 会直接报
        # "Sizes of tensors must match except in dimension 1. Expected size 2 but got size 1"。
        wav = wav.mean(dim=0, keepdim=True)
    if sr != SAMPLING_RATE:
        import torchaudio

        wav = torchaudio.functional.resample(wav, sr, SAMPLING_RATE)
    return wav


def _first_waveform(processor, outputs, log=None) -> np.ndarray:
    """`decode()` drops messages without text content, so read the audio channels directly."""
    wavs: list[torch.Tensor] = []
    collected: list[tuple[int, torch.Tensor]] = []
    for start_length, generation_ids in outputs:
        collected.append((start_length, generation_ids))

    def decode_all():
        out: list[torch.Tensor] = []
        for start_length, generation_ids in collected:
            try:
                out.extend(processor._parse_audio_codes(start_length, generation_ids[:, 1:]))
            except AttributeError:  # older processors: fall back to the public path
                for message in processor.decode([(start_length, generation_ids)]):
                    if message is not None:
                        out.extend(message.audio_codes_list)
        return out

    if log is not None:
        wavs = _timed(log, "音频码解码", decode_all)
    else:
        wavs = decode_all()
    if not wavs:
        raise RuntimeError("模型没有产出音频（生成的 token 全为 pad）")
    audio = torch.cat([w.reshape(-1) for w in wavs], dim=0)
    return audio.detach().float().cpu().numpy()


CODEC_AUTOCAST_METHODS = ("encode_audios_from_wav", "decode_audio_codes", "encode_audios", "decode_codes")


def _autocast_wrap(fn, dtype: torch.dtype):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with torch.autocast("cuda", dtype=dtype):
            return fn(*args, **kwargs)

    return wrapper


def _trust_remote_auto_model(base):
    """Quanto calls `auto_class.from_config(config)` without kwargs; remote-code
    architectures reject that (they need trust_remote_code=True)."""

    class _Proxy:
        @classmethod
        def from_config(cls, config, **kwargs):
            kwargs.setdefault("trust_remote_code", True)
            return base.from_config(config, **kwargs)

        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            kwargs.setdefault("trust_remote_code", True)
            return base.from_pretrained(*args, **kwargs)

    return _Proxy


def apply_codec_autocast(processor, dtype: torch.dtype | None) -> None:
    """Half-precision codec weights only work when every op inside is autocast-wrapped:
    the repo code casts intermediates with `.float()` and then feeds convolutions whose
    weights are half, which raises a dtype mismatch unpatched."""
    if dtype is None:
        return
    for name in CODEC_AUTOCAST_METHODS:
        fn = getattr(processor, name, None)
        if fn is not None:
            setattr(processor, name, _autocast_wrap(fn, dtype))


def _timed(log, label: str, fn):
    started = time.time()
    try:
        return fn()
    finally:
        log(f"{label}耗时 {time.time() - started:.1f}s")
