"""FastAPI service for MOSS-TTSD-v1.0 (multi-speaker dialogue) and MOSS-SoundEffect.

Endpoints are job-based: heavy work runs on a single GPU worker thread and the UI polls
`/api/jobs/{id}` (or subscribes to `/api/events` for live logs).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import re
import sys
import threading
import time
import uuid
from urllib.parse import quote
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional


import uvicorn
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from asr import AsrEngine
from denoise import denoise_audio
from moss_engine import QUANT_CHOICES, SCENE_DIRS, MossEngine, ModelSpec, available_quants
from stems import separate_stems

import downloads as downloads_api
APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
LOG = logging.getLogger("moss.app")

# --------------------------------------------------------------------------- config
DEFAULTS: dict[str, Any] = {
    "host": "0.0.0.0",
    "port": 17980,
    "quant": "int8",
    "attn_implementation": "auto",
    "tokenizer_dtype": "float16",
    "output_dir": "../outputs",
    "upload_dir": "../uploads",
    "upload_max_bytes": 536870912,
    "cors_origins": ["*"],
    "api_token": "",
    "asr": {
        "model": "../models/whisper-small",
        "device": "cpu",
        "compute_type": "int8",
        "beam_size": 5,
    },
    "models": {
        "ttsd": {
            "label": "MOSS-TTSD-v1.0 · 多人对话配音",
            "kind": "ttsd",
            "path": "../models/openmoss/MOSS-TTSD-v1.0",
            "codec_path": "../models/openmoss/MOSS-Audio-Tokenizer-fp16",
        },
        "sfx": {
            "label": "MOSS-SoundEffect · 音效/环境声",
            "kind": "sfx",
            "path": "../models/openmoss/MOSS-SoundEffect",
            "codec_path": "../models/openmoss/MOSS-Audio-Tokenizer-fp16",
        },
        "tts": {
            "label": "MOSS-TTS-v1.5 · 单人配音 / 音色克隆",
            "kind": "tts",
            "path": "../models/openmoss/MOSS-TTS-v1.5",
            "codec_path": "../models/openmoss/MOSS-Audio-Tokenizer-fp16",
            "quant_checkpoint": "../models/openmoss/MOSS-TTS-v1.5-int8-nohead",
            "voice_file": "../assets/voices/voices.jsonl",
            "voice_root": "../assets/voices",
        },
    },
}


def _resolve(path: str) -> str:
    p = Path(path)
    return str(p if p.is_absolute() else (APP_DIR / p).resolve())


def load_config(path: Path) -> dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULTS))
    if path.exists():
        user = json.loads(path.read_text(encoding="utf-8"))
        for key, value in user.items():
            if key == "models" and isinstance(value, dict):
                for mkey, mval in value.items():
                    cfg["models"].setdefault(mkey, {}).update(mval)
            else:
                cfg[key] = value
    cfg["output_dir"] = _resolve(cfg["output_dir"])
    cfg["upload_dir"] = _resolve(cfg["upload_dir"])
    return cfg


CONFIG_PATH = APP_DIR / "config.json"
CONFIG = load_config(CONFIG_PATH)
OUTPUT_DIR = Path(CONFIG["output_dir"])
UPLOAD_DIR = Path(CONFIG["upload_dir"])
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_MAX_BYTES = int(CONFIG.get("upload_max_bytes", DEFAULTS["upload_max_bytes"]))
ARTIFACT_LOCK = threading.RLock()
ACTIVE_OUTPUTS: dict[str, int] = {}


def _output_key(path: Path) -> str:
    return str(path.resolve())


def _begin_output(path: Path) -> None:
    key = _output_key(path)
    with ARTIFACT_LOCK:
        ACTIVE_OUTPUTS[key] = ACTIVE_OUTPUTS.get(key, 0) + 1


def _end_output(path: Path) -> None:
    key = _output_key(path)
    with ARTIFACT_LOCK:
        count = ACTIVE_OUTPUTS.get(key, 0)
        if count <= 1:
            ACTIVE_OUTPUTS.pop(key, None)
        else:
            ACTIVE_OUTPUTS[key] = count - 1

def _is_output_active(path: Path) -> bool:
    candidate = Path(_output_key(path))
    with ARTIFACT_LOCK:
        return any(
            candidate == Path(active)
            or candidate.is_relative_to(Path(active))
            or Path(active).is_relative_to(candidate)
            for active in ACTIVE_OUTPUTS
        )



def _within(target: Path, roots) -> bool:
    """target 是否落在 roots 中任一目录之内（防 ../ 穿越）。"""
    try:
        resolved = target.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(Path(root).resolve())
            return True
        except ValueError:
            continue
    return False


def _within_outputs(target: Path) -> bool:
    """产物只允许 OUTPUT_DIR 内。"""
    return _within(target, (OUTPUT_DIR,))


# 启动即建好四个场景子目录：单人配音 / 音色设计 / 多人对话 / 音效生成
for _scene in SCENE_DIRS.values():
    (OUTPUT_DIR / _scene).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------- ASR
# 语音识别（本地 whisper-small）：只允许识别「上传目录」与「内置音色目录」里的音频，
# 避免把任意路径喂给接口。模型懒加载，首次识别时才占内存。
ASR_CFG = CONFIG.get("asr") or {}
ASR_ALLOWED_ROOTS = tuple(
    {UPLOAD_DIR}
    | {
        Path(_resolve(m["voice_root"]))
        for m in CONFIG["models"].values()
        if (m.get("voice_root") or "").strip()
    }
)
ASR = AsrEngine(
    model_dir=_resolve(str(ASR_CFG.get("model") or "../models/whisper-small")),
    device=str(ASR_CFG.get("device") or "cpu"),
    compute_type=str(ASR_CFG.get("compute_type") or "int8"),
    beam_size=int(ASR_CFG.get("beam_size") or 5),
    log=lambda msg: BROKER.publish(msg),
)


# ----------------------------------------------------------------------------- logs
class LogBroker:
    """Ring buffer of log lines plus SSE fan-out."""

    def __init__(self, capacity: int = 4000) -> None:
        self._lines: deque[dict] = deque(maxlen=capacity)
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, message: str, level: str = "info", job: Optional[str] = None) -> None:
        entry = {
            "ts": time.time(),
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "job": job,
            "message": message,
        }
        with self._lock:
            self._lines.append(entry)
            subs = list(self._subscribers)
        if self._loop is None:
            return
        for q in subs:
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, entry)
            except Exception:  # noqa: BLE001 - subscriber went away
                pass

    def tail(self, since: float = 0.0) -> list[dict]:
        with self._lock:
            return [e for e in self._lines if e["ts"] > since]

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)


BROKER = LogBroker()


class _BrokerHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            BROKER.publish(self.format(record), level=record.levelname.lower())
        except Exception:  # noqa: BLE001
            pass


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    broker_handler = _BrokerHandler()
    broker_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(broker_handler)


# ----------------------------------------------------------------------------- jobs
class Job:
    def __init__(self, kind: str, params: dict, fn=None) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.params = params
        self.fn = fn
        self.status = "pending"
        self.created = time.time()
        self.started: Optional[float] = None
        self.finished: Optional[float] = None
        self.result: Any = None
        self.error: Optional[str] = None
        self.logs: deque[dict] = deque(maxlen=500)
        self.done = threading.Event()

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "created": self.created,
            "started": self.started,
            "finished": self.finished,
            "elapsed": round((self.finished or time.time()) - (self.started or self.created), 1),
            "result": self.result,
            "error": self.error,
            "params": self.params,
            "logs": list(self.logs),
        }


class JobRunner:
    """Single worker thread: the GPU can only run one generation at a time."""

    def __init__(self, engine: MossEngine, broker: LogBroker) -> None:
        self.engine = engine
        self.broker = broker
        self.jobs: dict[str, Job] = {}
        self._queue: queue.Queue[Job] = queue.Queue()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, name="moss-worker", daemon=True)
        self._thread.start()

    def submit(self, kind: str, params: dict, fn) -> Job:
        job = Job(kind, params, fn)
        with self._lock:
            self.jobs[job.id] = job
        self.broker.publish(f"任务 {job.id} 已排队（{kind}）", job=job.id)
        self._queue.put(job)
        return job

    def run_sync(self, kind: str, params: dict, fn, timeout: float = 600.0) -> Job:
        job = self.submit(kind, params, fn)
        if not job.done.wait(timeout):
            raise TimeoutError(f"{kind} remains queued/running: {job.id}")
        if job.status == "failed":
            raise RuntimeError(job.error or f"{kind} failed")
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def list(self, limit: int = 30) -> list[dict]:
        with self._lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)[:limit]
        return [j.snapshot() for j in jobs]

    def _loop(self) -> None:
        while True:
            job: Job = self._queue.get()
            if job is None:
                return
            job.status = "running"
            job.started = time.time()
            self.broker.publish(f"开始执行 {job.kind}（{job.id}）", job=job.id)
            try:
                result = job.fn(job)
                job.result = result
                job.status = "done"
            except Exception as exc:  # noqa: BLE001
                if job.kind in {"tts", "ttsd", "sfx", "vg"}:
                    try:
                        self.engine.recover_codec_after_failure()
                    except Exception:
                        LOG.exception("codec recovery failed after job %s", job.id)
                job.error = f"{type(exc).__name__}: {exc}"
                job.status = "failed"
                LOG.exception("job %s failed", job.id)
                self.broker.publish(f"任务失败：{job.error}", level="error", job=job.id)
            finally:
                job.finished = time.time()
                job.done.set()
                self.broker.publish(
                    f"任务 {job.id} 结束（{job.status}，{job.finished - (job.started or job.created):.1f}s）",
                    job=job.id,
                )
                self._queue.task_done()


# --------------------------------------------------------------------------- engine
def _has_codec_weights(path: str) -> bool:
    root = Path(path)
    return (root / "model.safetensors").is_file() or any(root.glob("model-*-of-*.safetensors"))


def _has_ct2_model(path: str) -> bool:
    root = Path(path)
    return all((root / name).is_file() for name in ("model.bin", "tokenizer.json", "vocabulary.txt", "config.json"))


def _resolve_codec_paths(primary_path: str, fallback_path: str = "") -> str:
    primary = _resolve(primary_path)
    fallback = _resolve(fallback_path) if fallback_path else ""
    if _has_codec_weights(primary):
        return primary
    if fallback and _has_codec_weights(fallback):
        return fallback
    raise FileNotFoundError(
        f"音频 tokenizer 权重缺失：主路径 {primary} 与回退路径 {fallback or '（未配置）'} 均无 safetensors 权重"
    )


def _resolve_codec_for_key(key: str) -> str:
    model = CONFIG["models"][key]
    selected = _resolve_codec_paths(model["codec_path"], model.get("codec_path_fallback", ""))
    ENGINE.specs[key].codec_path = selected
    return selected


def _build_engine() -> MossEngine:
    specs = {}
    for key, m in CONFIG["models"].items():
        codec = _resolve(m["codec_path"])
        fallback = _resolve(m["codec_path_fallback"]) if m.get("codec_path_fallback") else ""
        if fallback and not _has_codec_weights(codec) and _has_codec_weights(fallback):
            codec = fallback
        specs[key] = ModelSpec(
            key=key,
            label=m.get("label", key),
            kind=m.get("kind", key),
            path=_resolve(m["path"]),
            codec_path=codec,
            quant_checkpoint=(_resolve(m["quant_checkpoint"]) if (m.get("quant_checkpoint") or "").strip() else ""),
            quant_checkpoint_convrot=(_resolve(m["quant_checkpoint_convrot"]) if (m.get("quant_checkpoint_convrot") or "").strip() else ""),
            voice_file=_resolve(m["voice_file"]) if (m.get("voice_file") or "").strip() else "",
            voice_root=_resolve(m["voice_root"]) if (m.get("voice_root") or "").strip() else "",
        )
    return MossEngine(
        specs,
        quant=CONFIG["quant"],
        output_dir=str(OUTPUT_DIR),
        attn_implementation=CONFIG["attn_implementation"],
        tokenizer_dtype=CONFIG.get("tokenizer_dtype", "float16"),
        tokenizer_device=CONFIG.get("tokenizer_device", "auto"),
        tokenizer_swap=bool(CONFIG.get("tokenizer_swap", True)),
        log_sink=lambda msg: BROKER.publish(msg),
        artifact_lock=ARTIFACT_LOCK,
        active_outputs=ACTIVE_OUTPUTS,
    )


_configure_logging()
ENGINE = _build_engine()
RUNNER = JobRunner(ENGINE, BROKER)

app = FastAPI(title="MOSS TTSD / SoundEffect Studio")

# 允许别的应用（含浏览器页面）直接调用本地接口；自定义 X-* 响应头要 expose 才读得到。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(o) for o in (CONFIG.get("cors_origins") or ["*"])],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Job-Id",
        "X-Output-Name",
        "X-Output-Url",
        "X-Output-Path",
        "X-Seconds",
        "X-Elapsed",
        "X-Takes",
    ],
)


# ---------------------------------------------------------------------------- models
class LoadRequest(BaseModel):
    key: str
    quant: Optional[str] = None


class TTSDSpeaker(BaseModel):
    tag: Optional[str] = None
    ref_text: str = ""
    ref_audio: str


class TTSDRequest(BaseModel):
    script: str
    speakers: list[TTSDSpeaker]
    max_minutes: float = 3.0
    seed: int = 0
    temperature: float = 1.1
    top_p: float = 0.9
    top_k: int = 50
    repetition_penalty: float = 1.1
    num_takes: int = 1


class SFXRequest(BaseModel):
    prompt: str
    seconds: float = 10.0
    tokens: Optional[int] = None
    seed: int = 0
    temperature: float = 1.5
    top_p: float = 0.6
    top_k: int = 50
    repetition_penalty: float = 1.2
    num_takes: int = 1


class UnloadRequest(BaseModel):
    key: Optional[str] = None


class VoiceCloneRequest(BaseModel):
    """单人配音 / 音色克隆（MOSS-TTS-v1.5，零样本克隆）。"""

    text: str
    prompt_audio: str
    num_takes: int = 1
    seconds: float = 0.0
    tokens: Optional[int] = None
    language: str = ""
    seed: int = 0
    temperature: float = 1.7
    top_p: float = 0.8
    top_k: int = 25
    repetition_penalty: float = 1.0


class VoiceDesignRequest(BaseModel):
    """音色设计（MOSS-VoiceGenerator 1.7B）：自由文本描述音色/情绪/风格 → 配音，无需参考音频。"""

    text: str
    instruction: str
    num_takes: int = 1
    seconds: float = 0.0
    tokens: Optional[int] = None
    language: str = ""
    seed: int = 0
    temperature: float = 1.5
    top_p: float = 0.6
    top_k: int = 50
    repetition_penalty: float = 1.1


@app.get("/api/downloads")
def downloads_snapshot() -> dict:
    return downloads_api.snapshot()


class DownloadsRequest(BaseModel):
    ids: list[str]


@app.post("/api/downloads/start")
def downloads_start(req: DownloadsRequest) -> dict:
    try:
        return downloads_api.start(req.ids)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/downloads/cancel")
def downloads_cancel(req: DownloadsRequest) -> dict:
    return downloads_api.cancel(req.ids)


@app.post("/api/downloads/verify")
def downloads_verify(req: DownloadsRequest) -> dict:
    """对落盘文件做一次校对（逐文件 sha256/前缀/尺寸），用于给用户一个明确的成功标识。"""
    return downloads_api.verify(req.ids)


def _need_asset(asset: str, message: str) -> None:
    raise HTTPException(409, {"code": "need_asset", "asset": asset, "message": message})


def _ffmpeg_available() -> bool:
    """runtime/ffmpeg 里有 ffmpeg.exe，或 PATH 上有 ffmpeg（stems/denoise 的解码兜底）。"""
    if (ROOT_DIR / "runtime" / "ffmpeg" / "ffmpeg.exe").is_file():
        return True
    return any((Path(p) / "ffmpeg.exe").is_file() for p in os.environ.get("PATH", "").split(os.pathsep) if p)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "moss-ttsd-sfx", "version": 1}


def _environment_state() -> dict[str, Any]:
    return {
        "ready": os.environ.get("MOSS_ENV_READY") == "1",
        "interpreter": os.environ.get("MOSS_ENV_INTERPRETER", sys.executable),
        "torch": os.environ.get("MOSS_ENV_TORCH"),
        "cuda": os.environ.get("MOSS_ENV_CUDA") == "True",
        "cudnn": os.environ.get("MOSS_ENV_CUDNN"),
        "system_cudnn_conflict": os.environ.get("MOSS_ENV_SYSTEM_CUDNN_CONFLICT") == "True",
        "missing": json.loads(os.environ.get("MOSS_ENV_MISSING", "[]")),
    }


def _require_environment() -> None:
    if not _environment_state()["ready"]:
        raise HTTPException(
            409,
            {"error": "need_env", "hint": "请在客户端『环境准备』中一键安装运行环境（≈3.4 GB）"},
        )


@app.get("/api/state")
def state() -> dict:
    st = ENGINE.state()
    st["jobs"] = RUNNER.list(limit=10)
    st["env"] = _environment_state()
    return st


@app.post("/api/models/load")
def models_load(req: LoadRequest) -> dict:
    _require_environment()
    if req.quant and req.quant not in QUANT_CHOICES:
        raise HTTPException(400, f"quant must be one of {QUANT_CHOICES}")
    spec = ENGINE.specs.get(req.key)
    if spec is None:
        raise HTTPException(400, f"unknown model {req.key!r}")
    allowed = available_quants(spec)
    if req.quant and req.quant not in allowed:
        hint = (
            "（float8 / none 需要完整精度权重在位，本机母本已删除——重下后会自动恢复）"
            if req.quant in ("float8", "none")
            else ""
        )
        raise HTTPException(400, f"{spec.label} 当前可用：{allowed or '（无：量化产物与完整精度权重都不在位）'}；"
                                 f"不支持 quant={req.quant}{hint}")

    def run(job: Job) -> dict:
        _resolve_codec_for_key(req.key)
        return ENGINE.load(req.key, req.quant)

    return {"job_id": RUNNER.submit("load", req.model_dump(), run).id}


@app.post("/api/models/unload")
def models_unload(req: UnloadRequest | None = None) -> dict:
    try:
        job = RUNNER.run_sync("unload", {}, lambda _job: ENGINE.unload())
    except TimeoutError as exc:
        raise HTTPException(504, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc
    return job.result


def build_ttsd_run(req: TTSDRequest) -> Callable[[Job], dict]:
    for spk in req.speakers:
        if not Path(spk.ref_audio).exists():
            raise HTTPException(400, f"参考音频不存在: {spk.ref_audio}")

    def run(job: Job) -> dict:
        _resolve_codec_for_key("ttsd")
        return ENGINE.generate_dialogue(
            req.script,
            [s.model_dump() for s in req.speakers],
            max_minutes=req.max_minutes,
            seed=req.seed,
            temperature=req.temperature,
            top_p=req.top_p,
            top_k=req.top_k,
            repetition_penalty=req.repetition_penalty,
            num_takes=req.num_takes,
        )

    return run


@app.post("/api/ttsd/generate")
def ttsd_generate(req: TTSDRequest) -> dict:
    _require_environment()
    """（页面用）提交任务并立刻返回 job_id；外部程序建议用 POST /api/gen/ttsd。"""
    return {"job_id": RUNNER.submit("ttsd", req.model_dump(), build_ttsd_run(req)).id}


def build_sfx_run(req: SFXRequest) -> Callable[[Job], dict]:
    def run(job: Job) -> dict:
        _resolve_codec_for_key("sfx")
        return ENGINE.generate_sound(
            req.prompt,
            seconds=req.seconds,
            tokens=req.tokens,
            seed=req.seed,
            temperature=req.temperature,
            top_p=req.top_p,
            top_k=req.top_k,
            repetition_penalty=req.repetition_penalty,
            num_takes=req.num_takes,
        )

    return run


@app.post("/api/sfx/generate")
def sfx_generate(req: SFXRequest) -> dict:
    _require_environment()
    """（页面用）提交任务并立刻返回 job_id；外部程序建议用 POST /api/gen/sfx。"""
    return {"job_id": RUNNER.submit("sfx", req.model_dump(), build_sfx_run(req)).id}


def build_tts_run(req: VoiceCloneRequest) -> Callable[[Job], dict]:
    if not Path(req.prompt_audio).exists():
        raise HTTPException(400, f"参考音频不存在: {req.prompt_audio}")
    if not req.text.strip():
        raise HTTPException(400, "请填写待转换文本")

    def run(job: Job) -> dict:
        _resolve_codec_for_key("tts")
        return ENGINE.generate_voice_clone(
            req.text,
            prompt_audio=req.prompt_audio,
            num_takes=req.num_takes,
            seconds=req.seconds,
            tokens=req.tokens,
            language=req.language,
            seed=req.seed,
            temperature=req.temperature,
            top_p=req.top_p,
            top_k=req.top_k,
            repetition_penalty=req.repetition_penalty,
        )

    return run


@app.post("/api/tts/generate")
def voice_clone_generate(req: VoiceCloneRequest) -> dict:
    _require_environment()
    """（页面用）提交任务并立刻返回 job_id；外部程序建议用 POST /api/gen/tts。"""
    return {"job_id": RUNNER.submit("tts", req.model_dump(), build_tts_run(req)).id}


def build_vg_run(req: VoiceDesignRequest) -> Callable[[Job], dict]:
    if not req.text.strip():
        raise HTTPException(400, "请填写待转换文本")
    if not req.instruction.strip():
        raise HTTPException(400, "请填写音色描述（instruction）")

    def run(job: Job) -> dict:
        _resolve_codec_for_key("vg")
        return ENGINE.generate_voice_design(
            req.text,
            req.instruction,
            num_takes=req.num_takes,
            seconds=req.seconds,
            tokens=req.tokens,
            language=req.language,
            seed=req.seed,
            temperature=req.temperature,
            top_p=req.top_p,
            top_k=req.top_k,
            repetition_penalty=req.repetition_penalty,
        )

    return run


@app.post("/api/vg/generate")
def voice_design_generate(req: VoiceDesignRequest) -> dict:
    _require_environment()
    """（页面用）提交任务并立刻返回 job_id；外部程序建议用 POST /api/gen/vg。"""
    return {"job_id": RUNNER.submit("vg", req.model_dump(), build_vg_run(req)).id}


@app.get("/api/tts/voices")
def voice_clone_voices() -> dict:
    presets = [entry for entry in ENGINE.voice_presets("tts") if Path(entry["audio"]).is_file()]
    return {
        "voices": [
            {
                "id": entry["id"],
                "name": entry["name"],
                "text": entry["text"],
                "path": entry["audio"],
                "url": f"/api/tts/voice-audio/{entry['id']}",
            }
            for entry in presets
        ]
    }


@app.get("/api/tts/voice-audio/{voice_id}")
def voice_clone_voice_audio(voice_id: str) -> FileResponse:
    """Serve a listed reference voice's audio (allowlist: only the preset table)."""
    for entry in ENGINE.voice_presets("tts"):
        if entry["id"] == voice_id:
            target = Path(entry["audio"]).resolve()
            if not target.is_file():
                raise HTTPException(404, "reference audio missing")
            return FileResponse(str(target), media_type="audio/wav", filename=target.name)
    raise HTTPException(404, "unknown voice")


@app.get("/api/jobs")
def jobs(limit: int = 30) -> dict:
    return {"jobs": RUNNER.list(limit=limit)}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> dict:
    job = RUNNER.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job.snapshot()


@app.post("/api/upload")
async def upload(files: list[UploadFile]) -> dict:
    saved = []
    for f in files:
        name = re.sub(r"[^0-9A-Za-z._\u4e00-\u9fff-]", "_", f.filename or "ref.wav")
        dest = UPLOAD_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}_{name}"
        temp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.upload")
        size = 0
        try:
            with temp.open("wb") as stream:
                while chunk := await f.read(1024 * 1024):
                    size += len(chunk)
                    if size > UPLOAD_MAX_BYTES:
                        raise HTTPException(413, f"file exceeds upload limit ({UPLOAD_MAX_BYTES} bytes)")
                    await asyncio.to_thread(stream.write, chunk)
            if not size:
                raise HTTPException(400, "empty upload")
            os.replace(temp, dest)
            saved.append({"name": f.filename, "path": str(dest), "size_mb": round(size / 1e6, 2)})
        finally:
            temp.unlink(missing_ok=True)
            await f.close()
    if not saved:
        raise HTTPException(400, "没有收到文件")
    return {"files": saved}

class StemRequest(BaseModel):
    path: str
    mode: str = Field(default="six", pattern="^(six|vocals)$")


@app.post("/api/stems/separate")
def stems_separate(req: StemRequest) -> dict:
    # 六轨分离只依赖 demucs 权重 + ffmpeg 解码，与四个 MOSS 模型无关
    if not (ROOT_DIR / "models/demucs/5c90dfd2-34c22ccb.th").is_file():
        _need_asset("demucs", "人声/伴奏分离需要 demucs（约 55 MB）")
    if not _ffmpeg_available():
        _need_asset("ffmpeg", "音频解码需要 ffmpeg（约 90 MB）")
    path = Path(req.path).expanduser().resolve()
    if not _within(path, (UPLOAD_DIR,)) or not path.is_file():
        raise HTTPException(400, "path must refer to an existing uploaded file")
    def run(job: Job) -> dict:
        return separate_stems(
            job, str(path), ENGINE.unload, req.mode,
            upload_root=UPLOAD_DIR, output_root=OUTPUT_DIR,
            artifact_lock=ARTIFACT_LOCK, begin_output=_begin_output, end_output=_end_output,
        )
    return {"job_id": RUNNER.submit("stems", {"path": str(path), "mode": req.mode, "progress": 0.0}, run).id}


@app.get("/api/stems/archive/{job_id}")
def stems_archive(job_id: str) -> FileResponse:
    if not re.fullmatch(r"[0-9a-f]{12}", job_id):
        raise HTTPException(404, "archive not found")
    archive = OUTPUT_DIR / "Stems" / f"{job_id}.zip"
    if not _within_outputs(archive) or not archive.is_file():
        raise HTTPException(404, "archive not found")
    return FileResponse(str(archive), media_type="application/zip", filename=f"stems-{job_id}.zip")


class DenoiseRequest(BaseModel):
    path: str
    mix: float = Field(default=1.0, ge=0.0, le=1.0)


@app.post("/api/denoise/apply")
def denoise_apply(req: DenoiseRequest) -> dict:
    if not Path(_resolve(CONFIG["denoise"]["checkpoint"])).is_file():
        _need_asset("mossformer2", "人声降噪需要 MossFormer2（222 MB）")
    path = Path(req.path).expanduser().resolve()
    if not _within(path, (UPLOAD_DIR,)) or not path.is_file():
        raise HTTPException(400, "path must refer to an existing uploaded file")

    def run(job: Job) -> dict:
        # 注意：不像其它任务那样先 ENGINE.unload —— 降噪是「不依赖语音模型」的旁路，
        # 卸载常驻 TTSD 会拖长下一次配音的冷启动，而显存本身够用（引擎自带 OOM 退避 CPU）。
        return denoise_audio(
            job, str(path), mix=req.mix,
            upload_root=UPLOAD_DIR, output_root=OUTPUT_DIR,
            artifact_lock=ARTIFACT_LOCK, begin_output=_begin_output, end_output=_end_output,
        )

    return {"job_id": RUNNER.submit("denoise", {"path": str(path), "mix": req.mix, "progress": 0.0}, run).id}


def _unlink_if_inactive(target: Path) -> bool:
    with ARTIFACT_LOCK:
        if _is_output_active(target):
            return False
        target.unlink()
        return True


class AsrRequest(BaseModel):
    path: str
    language: Optional[str] = None


@app.post("/api/asr")
def asr(req: AsrRequest) -> dict:
    """参考音频 → 逐字稿（本地 whisper-small，CPU，离线；不依赖任何云服务）。"""
    if not _has_ct2_model(_resolve(ASR_CFG["model"])):
        _need_asset("whisper-small", "逐字稿需要 whisper-small（486 MB）")
    target = Path(req.path)
    if not target.is_absolute():
        target = (ROOT_DIR / target).resolve()
    if not _within(target, ASR_ALLOWED_ROOTS) or not target.is_file():
        raise HTTPException(400, f"音频不存在或不在允许目录（uploads / 内置音色）：{req.path}")
    try:
        result = ASR.transcribe(str(target), language=(req.language or None))
    except Exception as exc:  # noqa: BLE001 — 失败原因要回给界面
        raise HTTPException(500, f"识别失败：{exc}") from exc
    BROKER.publish(
        f"ASR：{target.name} → {result['language']} / {result['duration']}s，用时 {result['elapsed']}s"
    )
    return result


@app.get("/api/outputs")
def outputs(limit: int = 200) -> dict:
    items = []
    found = sorted(OUTPUT_DIR.rglob("*.wav"), key=lambda x: x.stat().st_mtime, reverse=True)
    for p in found[:limit]:
        rel = p.relative_to(OUTPUT_DIR).as_posix()
        items.append(
            {
                "name": rel,
                "scene": rel.split("/", 1)[0] if "/" in rel else "",
                "size_mb": round(p.stat().st_size / 1e6, 2),
                "mtime": p.stat().st_mtime,
                "url": "/outputs/" + quote(rel, safe="/"),
            }
        )
    return {"dir": str(OUTPUT_DIR), "scenes": list(dict.fromkeys(SCENE_DIRS.values())), "items": items}


@app.delete("/api/outputs/{name:path}")
def delete_output(name: str) -> dict:
    target = (OUTPUT_DIR / name).resolve()
    if not _within_outputs(target) or not target.is_file():
        raise HTTPException(404, "file not found")
    if not _unlink_if_inactive(target):
        raise HTTPException(409, "output is being generated")
    return {"deleted": name}
@app.delete("/api/outputs")
def delete_all_outputs() -> dict:
    deleted = 0
    freed_bytes = 0
    for entry in OUTPUT_DIR.rglob("*"):
        if entry.is_symlink():
            continue
        target = entry.resolve()
        if not _within_outputs(target) or not target.is_file():
            continue
        size = target.stat().st_size
        if not _unlink_if_inactive(target):
            continue
        deleted += 1
        freed_bytes += size
    return {"deleted": deleted, "freed_mb": round(freed_bytes / 1e6, 2)}



@app.get("/api/logs")
def logs(since: float = 0.0) -> dict:
    return {"lines": BROKER.tail(since)}


@app.get("/api/events")
async def events(request: Request) -> StreamingResponse:
    q = BROKER.subscribe()

    async def gen():
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
        finally:
            BROKER.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/outputs/{name:path}")
def get_output(name: str) -> FileResponse:
    target = (OUTPUT_DIR / name).resolve()
    if not _within_outputs(target) or not target.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(str(target), media_type="audio/wav", filename=Path(name).name)


# ----------------------------------------------- 对外「一站式」接口（给别的应用调用）
# 目的：外部程序不必理解「先加载模型 → 提交任务 → 轮询 → 下载」这套流程，
# 一次 HTTP 调用就拿到音频字节（`wait=0` 则返回 job_id 自行轮询）。
# 与页面共用同一套请求模型、同一套生成代码、同一条单线程队列（不会并发抢 GPU）。
class SimpleTTSRequest(VoiceCloneRequest):
    wait: bool = True
    timeout: float = 600.0


class SimpleVGRequest(VoiceDesignRequest):
    wait: bool = True
    timeout: float = 600.0


class SimpleSFXRequest(SFXRequest):
    wait: bool = True
    timeout: float = 600.0


class SimpleTTSDRequest(TTSDRequest):
    wait: bool = True
    timeout: float = 600.0


def _token_of(request: Request, token: Optional[str]) -> Optional[str]:
    return token or request.headers.get("X-API-Token") or None


def _check_api_token(token: Optional[str]) -> None:
    """config 里设了 api_token 才校验；默认空 = 不校验（本机脚本可直接调）。"""
    expected = str(CONFIG.get("api_token") or "").strip()
    if expected and (token or "") != expected:
        raise HTTPException(401, "缺少或错误的 API token（用 ?token=... 或 X-API-Token 头）")


def _wait_job(job: Job, timeout: float) -> None:
    deadline = time.time() + max(1.0, float(timeout))
    while job.status not in ("done", "failed") and time.time() < deadline:
        time.sleep(0.4)


def _audio_response(job: Job) -> Response:
    outputs = (job.result or {}).get("outputs") or []
    if not outputs:
        raise HTTPException(500, "任务完成但没有产物")
    rel = str(outputs[0]["name"])
    target = OUTPUT_DIR / rel
    if not target.is_file():
        raise HTTPException(500, f"产物文件不存在：{rel}")
    headers = {
        "X-Job-Id": job.id,
        "X-Output-Name": quote(rel, safe=""),          # 含场景子目录，如 单人配音/tts_xxx.wav
        "X-Output-Url": "/outputs/" + quote(rel, safe="/"),
        "X-Output-Path": quote(str(target), safe=""),
        "X-Seconds": str(outputs[0].get("seconds", "")),
        "X-Elapsed": f"{(job.finished or 0) - (job.started or 0):.1f}",
        "X-Takes": str(len(outputs)),
    }
    return Response(content=target.read_bytes(), media_type="audio/wav", headers=headers)


def _simple_generate(
    kind: str,
    req: Any,
    build_run: Callable[[Any], Callable[[Job], dict]],
    token: Optional[str],
) -> Response:
    _require_environment()
    _check_api_token(token)
    # 模型加载由引擎在任务内部完成（ENGINE.generate_* 会 _ensure 对应模型并自动卸载上一个），
    # 所以 wait=0 能真正立刻返回；wait=1 的等待时间自然包含首次加载的 ~25 s。
    job = RUNNER.submit(kind, req.model_dump(), build_run(req))
    if not req.wait:
        return JSONResponse({"job_id": job.id, "status": job.status, "poll": f"/api/jobs/{job.id}"})
    _wait_job(job, req.timeout)
    if job.status == "failed":
        raise HTTPException(500, f"生成失败：{job.error}")
    if job.status != "done":
        raise HTTPException(504, f"等待超时（{req.timeout:.0f}s），任务仍在跑：GET /api/jobs/{job.id}")
    return _audio_response(job)


def _resolve_voice_ref(voice: str) -> str:
    """voice 支持：内置音色 id（voice-2）、名称（🇨🇳 磁性男声）、音频文件名或去扩展名（zh_1 / zh_1.wav），
    也可以直接给服务器上的音频路径。"""
    target = Path(voice).name
    for entry in ENGINE.voice_presets("tts"):
        if voice in (entry.get("id"), entry.get("name")):
            return str(entry["audio"])
        audio = Path(str(entry.get("audio") or ""))
        if target and target in (audio.name, audio.stem):
            return str(entry["audio"])
    if Path(voice).is_file():
        return voice
    raise HTTPException(
        400,
        f"未找到内置音色 {voice!r}：可用 voice=<id|名称|文件名>（GET /api/tts/voices 查看），"
        "或直接给 prompt_audio=<服务器音频路径>",
    )


@app.get("/api/gen")
def gen_capabilities() -> dict:
    """这四个功能怎么调（给别的应用看的入口说明）。"""
    return {
        "service": "MOSS 语音工作台",
        "base": "/api/gen",
        "auth": "config.json 的 api_token 为空则不需要；设了就要带 ?token= 或 X-API-Token 头",
        "endpoints": {
            "tts": "单人配音/音色克隆：GET/POST /api/gen/tts（text, voice=<id|名称|文件名>，或 prompt_audio=<服务器音频路径>；seed, seconds, num_takes）",
            "vg": "音色设计：GET/POST /api/gen/vg（text, instruction, seed, seconds, num_takes）",
            "sfx": "音效生成：GET/POST /api/gen/sfx（prompt, seconds, seed, num_takes）",
            "ttsd": "多人对话：POST /api/gen/ttsd（script, speakers[{ref_audio, ref_text, tag}]）；GET 需 speakers=<JSON 数组>",
        },
        "wait": "默认 wait=1：本次请求等到生成完，直接返回 wav；wait=0：立刻返回 {job_id, poll}",
        "timeout": "wait=1 时的最长等待秒数（默认 600；首次会含模型加载 ~25s）",
        "headers": "响应头 X-Job-Id / X-Output-Name / X-Output-Url / X-Output-Path / X-Seconds / X-Elapsed / X-Takes（文件名与路径已 URL 编码）",
        "voices": "GET /api/tts/voices 列内置音色（id/name/path），GET /api/tts/voice-audio/<id> 取试听",
        "docs": "Swagger: /docs ；OpenAPI: /openapi.json ；详细示例见 docs/API.md",
    }


@app.post("/api/gen/tts")
def gen_tts(request: Request, req: SimpleTTSRequest, token: Optional[str] = None) -> Response:
    """单人配音 / 音色克隆 → 直接返回 wav。"""
    return _simple_generate("tts", req, build_tts_run, _token_of(request, token))


@app.get("/api/gen/tts")
def gen_tts_url(
    request: Request,
    text: str,
    voice: str = "",
    prompt_audio: str = "",
    seconds: float = 0.0,
    seed: int = 0,
    temperature: float = 1.7,
    top_p: float = 0.8,
    top_k: int = 25,
    repetition_penalty: float = 1.0,
    num_takes: int = 1,
    wait: bool = True,
    timeout: float = 600.0,
    token: Optional[str] = None,
) -> Response:
    """链接直调：/api/gen/tts?text=你好&voice=zh_1"""
    ref = prompt_audio or (_resolve_voice_ref(voice) if voice else "")
    if not ref:
        raise HTTPException(400, "请给 voice=<内置音色 id 或名称>，或 prompt_audio=<服务器上的音频路径>")
    req = SimpleTTSRequest(
        text=text,
        prompt_audio=ref,
        seconds=seconds,
        seed=seed,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        repetition_penalty=repetition_penalty,
        num_takes=num_takes,
        wait=wait,
        timeout=timeout,
    )
    return _simple_generate("tts", req, build_tts_run, _token_of(request, token))


@app.post("/api/gen/vg")
def gen_vg(request: Request, req: SimpleVGRequest, token: Optional[str] = None) -> Response:
    """音色设计 → 直接返回 wav。"""
    return _simple_generate("vg", req, build_vg_run, _token_of(request, token))


@app.get("/api/gen/vg")
def gen_vg_url(
    request: Request,
    text: str,
    instruction: str,
    seconds: float = 0.0,
    seed: int = 0,
    temperature: float = 1.5,
    top_p: float = 0.6,
    top_k: int = 50,
    repetition_penalty: float = 1.1,
    num_takes: int = 1,
    wait: bool = True,
    timeout: float = 600.0,
    token: Optional[str] = None,
) -> Response:
    """链接直调：/api/gen/vg?text=你好&instruction=温暖平静的中年男声"""
    req = SimpleVGRequest(
        text=text,
        instruction=instruction,
        seconds=seconds,
        seed=seed,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        repetition_penalty=repetition_penalty,
        num_takes=num_takes,
        wait=wait,
        timeout=timeout,
    )
    return _simple_generate("vg", req, build_vg_run, _token_of(request, token))


@app.post("/api/gen/sfx")
def gen_sfx(request: Request, req: SimpleSFXRequest, token: Optional[str] = None) -> Response:
    """音效生成 → 直接返回 wav。"""
    return _simple_generate("sfx", req, build_sfx_run, _token_of(request, token))


@app.get("/api/gen/sfx")
def gen_sfx_url(
    request: Request,
    prompt: str,
    seconds: float = 10.0,
    tokens: Optional[int] = None,
    seed: int = 0,
    temperature: float = 1.5,
    top_p: float = 0.6,
    top_k: int = 50,
    repetition_penalty: float = 1.2,
    num_takes: int = 1,
    wait: bool = True,
    timeout: float = 600.0,
    token: Optional[str] = None,
) -> Response:
    """链接直调：/api/gen/sfx?prompt=雨声&seconds=5"""
    req = SimpleSFXRequest(
        prompt=prompt,
        seconds=seconds,
        tokens=tokens,
        seed=seed,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        repetition_penalty=repetition_penalty,
        num_takes=num_takes,
        wait=wait,
        timeout=timeout,
    )
    return _simple_generate("sfx", req, build_sfx_run, _token_of(request, token))


@app.post("/api/gen/ttsd")
def gen_ttsd(request: Request, req: SimpleTTSDRequest, token: Optional[str] = None) -> Response:
    """多人对话 → 直接返回 wav。"""
    return _simple_generate("ttsd", req, build_ttsd_run, _token_of(request, token))


@app.get("/api/gen/ttsd")
def gen_ttsd_url(
    request: Request,
    script: str,
    speakers: str,
    max_minutes: float = 3.0,
    seed: int = 0,
    num_takes: int = 1,
    wait: bool = True,
    timeout: float = 600.0,
    token: Optional[str] = None,
) -> Response:
    """链接直调：speakers 传 JSON 数组，如 [{"tag":"[S1]","ref_audio":"...","ref_text":"..."}]"""
    try:
        parsed = json.loads(speakers)
        assert isinstance(parsed, list) and parsed
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            400,
            'speakers 需要非空 JSON 数组，例如 '
            '[{"tag":"[S1]","ref_audio":"D:/MossTTSD/uploads/xx.wav","ref_text":"该段逐字稿"}]'
            f"（解析失败：{exc}）",
        ) from exc
    req = SimpleTTSDRequest(
        script=script,
        speakers=parsed,
        max_minutes=max_minutes,
        seed=seed,
        num_takes=num_takes,
        wait=wait,
        timeout=timeout,
    )
    return _simple_generate("ttsd", req, build_ttsd_run, _token_of(request, token))


@app.get("/tools", response_class=HTMLResponse)
def tools_page() -> HTMLResponse:
    return _ui_page("tools.html")


@app.get("/tools/stems", response_class=HTMLResponse)
def stems_page() -> HTMLResponse:
    return _ui_page("stems.html")


@app.get("/tools/denoise", response_class=HTMLResponse)
def denoise_page() -> HTMLResponse:
    return _ui_page("denoise.html")


class UiStaticFiles(StaticFiles):
    """把前端资源标记为 `no-cache`：浏览器每次回源校验（命中 ETag 得到 304）。
    这样界面文件改动后刷新即生效，不会被客户端磁盘缓存里的旧脚本挂住。"""

    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", UiStaticFiles(directory=str(APP_DIR / "web")), name="static")


def _ui_build() -> str:
    """前端构建戳：取 `web/` 下最新改动时间，用来给资源 URL 加版本号。

    这里只做“尽力而为”的取值：目录边写边读（编辑器改文件、清理临时文件）时
    `glob` 与 `stat` 之间条目可能消失，任何一个条目失败都不能让页面 500。
    """
    web = APP_DIR / "web"
    newest = 0.0
    try:
        entries = list(web.glob("*"))
    except OSError:
        entries = []
    for entry in entries:
        try:
            newest = max(newest, entry.stat().st_mtime)
        except OSError:
            continue
    return str(int(newest))


def _ui_page(name: str) -> HTMLResponse:
    """返回带构建戳的前端页面：`__UI_BUILD__` 会被替换成当前值。

    `/static` 已带 `no-cache`（每次回源校验），这里再加版本号是为了让长期存活的
    客户端浏览器配置也绝不可能继续跑旧脚本 —— 界面一改，URL 就变。
    """
    html = (APP_DIR / "web" / name).read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__UI_BUILD__", _ui_build()))


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return _ui_page("index.html")

@app.get("/downloads", response_class=HTMLResponse)
def downloads_page() -> HTMLResponse:
    return _ui_page("downloads.html")


def main() -> None:
    host = os.environ.get("MOSS_HOST", CONFIG["host"])
    port = int(os.environ.get("MOSS_PORT", CONFIG["port"]))
    print(json.dumps({"server_port": port}), flush=True)
    BROKER.publish(f"MOSS TTSD/SoundEffect 服务启动：http://127.0.0.1:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


@app.on_event("startup")
async def _on_startup() -> None:
    BROKER.bind_loop(asyncio.get_running_loop())
    if CONFIG.get("preload"):
        for key in CONFIG["preload"]:
            RUNNER.submit("load", {"key": key}, lambda job, k=key: (_resolve_codec_for_key(k), ENGINE.load(k))[1])


if __name__ == "__main__":
    main()
