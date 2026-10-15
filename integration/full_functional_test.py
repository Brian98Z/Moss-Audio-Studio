"""Full functional test of the workbench: every model x load/generate/fetch, plus the
whole non-generation surface (state / voices / voice-audio / upload / outputs / jobs /
logs / unload) and the cheap 400 guards.

Usage: runtime\\venv\\Scripts\\python.exe full_functional_test.py
环境变量 MOSS_BASE 可改目标（默认 http://127.0.0.1:17980），用于在备用端口验收。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = os.environ.get("MOSS_BASE", "http://127.0.0.1:17980")
ROOT = Path(r"D:\MossTTSD")
REFS = ROOT / "assets" / "reference"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (f" — {detail}" if detail else ""), flush=True)


def call(path: str, payload=None, method: str = "GET", timeout: float = 600):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, (json.loads(body) if body[:1] in (b"{", b"[") else body)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def wait_job(job_id: str, timeout: float = 1800):
    t0 = time.time()
    while time.time() - t0 < timeout:
        _, job = call(f"/api/jobs/{job_id}")
        if isinstance(job, dict) and job.get("status") in ("done", "failed"):
            return job, time.time() - t0
        time.sleep(2)
    return {"status": "timeout", "error": f">{timeout}s"}, time.time() - t0


def multipart_upload(path: Path) -> tuple[int, dict]:
    boundary = "----omp" + uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="files"; filename="{path.name}"\r\n'.encode(),
        b"Content-Type: audio/wav\r\n\r\n",
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(BASE + "/api/upload", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode("utf-8", "replace")}


print("=== 0 · backend up", flush=True)
for _ in range(60):
    try:
        call("/api/health"); break
    except Exception: time.sleep(2)
else:
    raise SystemExit("backend did not come up")
code, health = call("/api/health")
check("GET /api/health", code == 200 and health.get("status") == "ok", str(health))

print("=== 1 · static surface", flush=True)
code, page_raw = call("/")
page = page_raw.decode("utf-8", "replace") if isinstance(page_raw, bytes) else str(page_raw)
check("GET / 返回工作台页面", code == 200 and "MOSS 语音工作台" in page, f"{len(page)} 字符")
for tab in ("ttsd", "tts", "vg", "sfx", "models", "help"):
    check(f"页面含标签页 {tab}", f'data-tab="{tab}"' in page and f'id="tab-{tab}"' in page)
for asset in ("/static/app.js", "/static/style.css"):
    code, _ = call(asset)
    check(f"GET {asset}", code == 200, str(code))

state_ts = time.time()
code, state = call("/api/state")
keys = [m["key"] for m in state["models"]]
check("GET /api/state 四模型", code == 200 and keys == ["ttsd", "sfx", "tts", "vg"], str(keys))
check("每个模型目录存在", all(m["exists"] for m in state["models"]),
      str({m["key"]: m["exists"] for m in state["models"]}))
check("默认量化 = int8", state.get("default_quant") == "int8", str(state.get("default_quant")))
check("每模型都挂了 int8-nohead 落盘产物",
      all("-int8-nohead" in (m.get("quant_checkpoint") or "") for m in state["models"]),
      str({m["key"]: Path(m.get("quant_checkpoint") or "-").name for m in state["models"]}))
code, voices = call("/api/tts/voices")
vlist = voices.get("voices", []) if isinstance(voices, dict) else []
check("GET /api/tts/voices", code == 200 and len(vlist) == 15, f"{len(vlist)} 条")
ref_path = Path(vlist[0]["path"])
check("音色参考 wav 存在", ref_path.is_file(), ref_path.name)
code, audio = call(f"/api/tts/voice-audio/{vlist[0]['id']}")
check("GET /api/tts/voice-audio/<id> 返回音频", code == 200 and len(audio) > 1000 and bytes(audio[:4]) == b"RIFF",
      f"{len(audio)} 字节")

code, up = multipart_upload(ref_path)
up_ok = code == 200 and up.get("files") and Path(up["files"][0]["path"]).is_file()
check("POST /api/upload 上传参考音频", up_ok, str(up.get("files", [{}])[0].get("path", up))[:80])
uploaded_path = up["files"][0]["path"] if up_ok else str(ref_path)

print("=== 2 · 输入校验（不发 GPU 任务）", flush=True)
code, body = call("/api/vg/generate", {"text": "x", "instruction": "  "}, "POST")
check("vg 缺 instruction → 400", code == 400, str(body)[:60])
code, body = call("/api/tts/generate", {"text": "x", "prompt_audio": "Z:\\nope.wav"}, "POST")
check("tts 参考音频不存在 → 400", code == 400, str(body)[:60])
code, body = call("/api/models/load", {"key": "nope", "quant": "int8"}, "POST")
if code == 200:  # 也可能在入口就被 400 拒绝（当前实现）
    job, _ = wait_job(body.get("job_id", ""), timeout=60)
    check("未知模型键 → 拒绝", job.get("status") == "failed", str(job.get("error"))[:70])
else:
    check("未知模型键 → 拒绝", code == 400, f"{code} {str(body)[:60]}")

PLAN = [
    ("tts", "单人配音 / 音色克隆", lambda: {"text": "这一句用来验证单人配音接口是否完好。", "prompt_audio": uploaded_path,
                                            "seconds": 0, "seed": 2026}),
    ("vg", "音色设计", lambda: {"text": "这一句用来验证音色设计接口是否完好。",
                                "instruction": "温暖平静的成年男声，语速中等，吐字清晰。", "seconds": 0, "seed": 2026}),
    ("ttsd", "多人对话", lambda: {"script": "[S1] 接口测试开始。 [S2] 两人对白也正常。",
                                  "speakers": [
                                      {"tag": "[S1]", "ref_audio": str(REFS / "reference_02_s1.wav"),
                                       "ref_text": "In short, we embarked on a mission to make America great again for all Americans."},
                                      {"tag": "[S2]", "ref_audio": str(REFS / "reference_02_s2.wav"),
                                       "ref_text": "NVIDIA reinvented computing for the first time after 60 years. In fact, Erwin at IBM knows quite well that the computer has largely been the same since the 60s."},
                                  ], "max_minutes": 0.3, "seed": 2026}),
    ("sfx", "音效", lambda: {"prompt": "雪地踩雪的清脆嘎吱声。", "seconds": 4, "seed": 2026}),
]

print("=== 3 · 四模型逐个体检（int8 落盘产物）", flush=True)
for key, label, payload_fn in PLAN:
    print(f"--- {key} ({label})", flush=True)
    mark = time.time()
    code, res = call("/api/models/load", {"key": key, "quant": "int8"}, "POST")
    job, secs = wait_job(res.get("job_id", ""))
    ok = job.get("status") == "done"
    check(f"{key}: 加载", ok, f"{secs:.1f}s | {job.get('error') or ''}")
    _, st = call("/api/state")
    loaded = st.get("loaded") or {}
    check(f"{key}: 加载的是 int8", loaded.get("quant") == "int8", str(loaded.get("quant")))
    _, lg = call(f"/api/logs?since={mark - 1}")
    msgs = [ln.get("message", "") if isinstance(ln, dict) else str(ln) for ln in lg.get("lines", [])]
    on_disk = [m for m in msgs if "已从落盘量化权重加载" in m]
    check(f"{key}: 走落盘量化产物", bool(on_disk) and "-int8-nohead" in on_disk[-1],
          (on_disk[-1] if on_disk else "未在日志中找到落盘加载记录")[:100])
    if not ok:
        continue
    code, res = call(f"/api/{key}/generate", payload_fn(), "POST")
    job, secs = wait_job(res.get("job_id", ""))
    ok = job.get("status") == "done" and job.get("result", {}).get("outputs")
    check(f"{key}: 生成", ok, f"{secs:.1f}s | {job.get('error') or ''}")
    if not ok:
        continue
    out = job["result"]["outputs"][0]
    code, wav = call("/outputs/" + urllib.parse.quote(out["name"]))
    check(f"{key}: 取回 wav", code == 200 and len(wav) > 1000 and bytes(wav[:4]) == b"RIFF",
          f"{out['name']} {out['seconds']}s {out['size_mb']}MB")
    _, outs = call("/api/outputs")
    check(f"{key}: 出现在输出列表", any(i["name"] == out["name"] for i in outs["items"]), out["name"])
    _, jl = call("/api/jobs")
    check(f"{key}: 任务在 /api/jobs 中", any(j["id"] == job["id"] for j in jl.get("jobs", [])), job["id"])

print("=== 4 · 卸载 + 目录", flush=True)
code, res = call("/api/models/unload", {}, "POST")
_, st = call("/api/state")
check("POST /api/models/unload", st.get("loaded") is None, str(st.get("loaded")))
check("输出目录存在", Path(st["output_dir"]).is_dir(), st["output_dir"])

print("=== 5 · 降噪（MossFormer2_SE_48K，独立于 MOSS 模型）", flush=True)
# 自造噪声素材：内置参考音色 + 白噪（≈5 dB SNR）。不依赖任何外部临时文件，跑完即删。
import numpy as np  # noqa: E402  (仅本节需要)
import soundfile as sf  # noqa: E402
import tempfile  # noqa: E402
from math import gcd  # noqa: E402
from scipy.signal import resample_poly  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="moss-denoise-"))
raw, raw_sr = sf.read(str(ref_path), dtype="float32", always_2d=True)
speech = raw.mean(axis=1)
if raw_sr != 48000:
    g = gcd(raw_sr, 48000)
    speech = resample_poly(speech, 48000 // g, raw_sr // g).astype(np.float32)
    clean_sr = 48000
else:
    clean_sr = raw_sr
rng = np.random.default_rng(20261015)
noise = rng.standard_normal(len(speech)).astype(np.float32)
noise *= float(np.sqrt(np.mean(speech.astype(np.float64) ** 2))) / (float(np.sqrt(np.mean(noise.astype(np.float64) ** 2))) * 1.78)
noisy = (speech + noise).astype(np.float32)
noisy_path = work / "denoise_input.wav"
sf.write(str(noisy_path), noisy, clean_sr)


def quiet_db(sig, rate, win=0.3):
    """最安静窗口的 RMS（dBFS）——降噪效果的主指标。"""
    w = int(win * rate)
    if len(sig) < w:
        return 20 * float(np.log10(np.sqrt(np.mean(sig.astype(np.float64) ** 2)) + 1e-12))
    step = max(1, w // 4)
    return min(20 * float(np.log10(np.sqrt(np.mean(sig[i:i + w].astype(np.float64) ** 2)) + 1e-12))
               for i in range(0, len(sig) - w + 1, step))


code, up2 = multipart_upload(noisy_path)
den_ok = code == 200 and up2.get("files") and Path(up2["files"][0]["path"]).is_file()
check("降噪：上传素材", den_ok, str(up2)[:80])
den_path = up2["files"][0]["path"] if den_ok else str(noisy_path)

code, res = call("/api/denoise/apply", {"path": den_path, "mix": 1.0}, "POST")
job, secs = wait_job(res.get("job_id", ""), timeout=600)
dres = job.get("result") or {}
outs = dres.get("outputs") or []
check("降噪：任务完成", code == 200 and job.get("status") == "done" and bool(outs),
      f"{secs:.1f}s | {job.get('error') or ''}")
if outs:
    out = outs[0]
    code, wav = call("/outputs/" + urllib.parse.quote(out["name"]))
    wet_path = work / "denoise_output.wav"
    wet_path.write_bytes(wav if isinstance(wav, bytes) else bytes(wav))
    wet, wet_sr = sf.read(str(wet_path), dtype="float32", always_2d=True)
    q_in, q_out = quiet_db(noisy, clean_sr), quiet_db(wet[:, 0], wet_sr)
    check("降噪：取回产出 wav", code == 200 and len(wav) > 1000 and bytes(wav[:4]) == b"RIFF",
          f"{out['name']} {len(wav)} 字节")
    check("降噪：噪声底显著下降（>30 dB）", q_out < q_in - 30, f"{q_in:.1f} → {q_out:.1f} dBFS")
    check("降噪：输出采样率 = 输入", wet_sr == clean_sr, f"{wet_sr} vs {clean_sr}")
    check("降噪：时长与输入一致（±0.1 s）", abs(len(wet) - len(noisy)) <= 0.1 * clean_sr,
          f"{len(wet)} vs {len(noisy)}")
    check("降噪：单声道进出单声道", wet.shape[1] == 1, str(wet.shape))
    check("降噪：未削顶", float(np.abs(wet).max()) < 0.999, f"峰值 {20*float(np.log10(float(np.abs(wet).max())+1e-12)):.1f} dBFS")
    check("降噪：结果字段齐全", {"seconds", "sample_rate", "mix", "elapsed"} <= set(dres),
          str(sorted(dres)))
    check("降噪：进度已回填 1.0", (job.get("params") or {}).get("progress") in (1.0, 1),
          str((job.get("params") or {}).get("progress")))

    code, res2 = call("/api/denoise/apply", {"path": den_path, "mix": 0.35}, "POST")
    job2, secs2 = wait_job(res2.get("job_id", ""), timeout=600)
    outs2 = (job2.get("result") or {}).get("outputs") or []
    check("降噪：dry/wet 任务完成", job2.get("status") == "done" and bool(outs2), f"{secs2:.1f}s | {job2.get('error') or ''}")
    if outs2:
        code, wav2 = call("/outputs/" + urllib.parse.quote(outs2[0]["name"]))
        (work / "denoise_mix.wav").write_bytes(wav2 if isinstance(wav2, bytes) else bytes(wav2))
        mix_audio, mix_sr = sf.read(str(work / "denoise_mix.wav"), dtype="float32", always_2d=True)
        check("降噪：mix=0.35 后的噪声底高于全降噪", quiet_db(mix_audio[:, 0], mix_sr) > q_out,
              f"{quiet_db(mix_audio[:,0], mix_sr):.1f} vs 全降噪 {q_out:.1f} dBFS")
        check("降噪：mix 回填正确", (job2.get("result") or {}).get("mix") == 0.35,
              str((job2.get("result") or {}).get("mix")))

code, body = call("/api/denoise/apply", {"path": "Z:\\nope.wav", "mix": 1.0}, "POST")
check("降噪：越界路径 → 400/422", code in (400, 422), f"{code} {str(body)[:60]}")
code, body = call("/api/denoise/apply", {"path": den_path, "mix": 1.7}, "POST")
check("降噪：mix 越界 → 422", code == 422, f"{code} {str(body)[:60]}")

code, page = call("/tools/denoise?language=chinese")
text = page.decode("utf-8", "replace") if isinstance(page, bytes) else str(page)
check("降噪：/tools/denoise 页面", code == 200 and "denoise.js" in text and "降噪" in text, f"{len(text)} 字符")
code, tools_page = call("/tools")
ttext = tools_page.decode("utf-8", "replace") if isinstance(tools_page, bytes) else str(tools_page)
check("降噪：工具页有第三张卡片", '/tools/denoise' in ttext and 'id="denoise"' in ttext, f"{len(ttext)} 字符")

for leftover in work.glob("*"):
    leftover.unlink()
work.rmdir()

print("\n=== 汇总 ===", flush=True)
failed = [n for n, ok, _ in RESULTS if not ok]
print(f"总计 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)}，失败 {len(failed)}", flush=True)
for n in failed:
    print("  FAILED:", n, flush=True)
print("RESULT:", "PASS" if not failed else "FAIL", flush=True)
