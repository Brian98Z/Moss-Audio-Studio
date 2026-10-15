"""Download MOSS-TTSD-v1.0 / MOSS-SoundEffect / MOSS-TTS-v1.5 / MOSS-VoiceGenerator (+ the shared audio
tokenizer) from ModelScope.

These are the **full-precision masters**: with them on disk the engine needs no pre-quantized artifact —
it streams int8 quantization itself on load (`QuantoConfig`), just slower on the first load per model.

Resumable (HTTP Range), sha256-verified against ModelScope metadata, parallel streams.
Usage:
  python download_models.py [--models ttsd,sfx,tts,vg,tok] [--workers 4]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

API = "https://www.modelscope.cn/api/v1/models/{repo}/repo/files?Revision=master&Recursive=true"
RAW = "https://www.modelscope.cn/api/v1/models/{repo}/repo?Revision=master&FilePath={path}"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = {
    "ttsd": ("openmoss/MOSS-TTSD-v1.0", os.path.join(ROOT, "models", "openmoss", "MOSS-TTSD-v1.0")),
    "sfx": ("openmoss/MOSS-SoundEffect", os.path.join(ROOT, "models", "openmoss", "MOSS-SoundEffect")),
    # 单人配音 / 音色克隆（旗舰 8B delay 模型）。15.83 GB；D: 装上落盘 int8 产物后剩余空间不够时，
    # 用 --dest 指向空间充足的盘。
    "tts": ("openmoss/MOSS-TTS-v1.5", os.path.join(ROOT, "models", "openmoss", "MOSS-TTS-v1.5")),
    # 音色设计（1.7B delay，自由文本描述 -> 音色，无需参考音频）。4.24 GB，可与 tts 共用 codec。
    "vg": ("openmoss/MOSS-VoiceGenerator", os.path.join(ROOT, "models", "openmoss", "MOSS-VoiceGenerator")),
    # 共享音频 codec 母本（fp32 7.1 GB）。四个模型都要它：没有落盘 int8 产物时，引擎会直接加载它，
    # 按 tokenizer_dtype 转半精度。下载到 -fp32 目录，然后把 config.json 里的 codec_path 指过来。
    "tok": ("openmoss/MOSS-Audio-Tokenizer", os.path.join(ROOT, "models", "openmoss", "MOSS-Audio-Tokenizer-fp32")),
}


def list_files(repo: str):
    with urllib.request.urlopen(API.format(repo=repo), timeout=60) as r:
        data = json.load(r)
    return [f for f in data["Data"]["Files"] if f["Type"] == "blob"]


def sha256_of(path: str, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def fetch_one(repo: str, path: str, out_dir: str, size: int, sha: str | None, retries: int = 8) -> str:
    dest = os.path.join(out_dir, path.replace("/", os.sep))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        if not sha or sha256_of(dest) == sha:
            return f"skip {path}"
    url = RAW.format(repo=repo, path=urllib.parse.quote(path))
    for attempt in range(1, retries + 1):
        have = os.path.getsize(dest) if os.path.exists(dest) else 0
        if have > size:
            os.remove(dest)
            have = 0
        cmd = ["curl", "-sSL", "--fail", "--retry", "5", "--retry-delay", "3",
               "-C", "-", "-o", dest, url]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as exc:
            if attempt == retries:
                raise RuntimeError(f"download failed: {path} ({exc})") from exc
            time.sleep(min(30, 2 * attempt))
            continue
        got = os.path.getsize(dest) if os.path.exists(dest) else 0
        if got == size:
            break
    got = os.path.getsize(dest) if os.path.exists(dest) else 0
    if got != size:
        raise RuntimeError(f"size mismatch {path}: {got} != {size}")
    if sha:
        actual = sha256_of(dest)
        if actual != sha:
            raise RuntimeError(f"sha256 mismatch {path}: {actual} != {sha}")
    return f"ok   {path} ({size / 1e9:.2f} GB)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="ttsd,sfx")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dest", default="", help="输出目录覆盖（只允许单个模型；默认写到 models/openmoss/<name>）")
    args = ap.parse_args()
    import urllib.parse  # noqa: F401  (used indirectly by fetch_one)

    keys = [k.strip() for k in args.models.split(",") if k.strip()]
    if args.dest and len(keys) != 1:
        raise SystemExit("--dest 只能配合单个模型使用")
    jobs = []
    for key in keys:
        repo, out_dir = TARGETS[key]
        if args.dest:
            out_dir = os.path.abspath(args.dest)
        files = list_files(repo)
        total = sum(f["Size"] for f in files)
        print(f"[{key}] {repo} -> {out_dir}  files={len(files)} total={total / 1e9:.2f} GB", flush=True)
        for f in files:
            jobs.append((repo, f["Path"], out_dir, f["Size"], f.get("Sha256"), key))

    fails = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(fetch_one, *j[:5]): j for j in jobs}
        done = 0
        for fut in cf.as_completed(futs):
            j = futs[fut]
            done += 1
            try:
                print(f"[{done}/{len(jobs)}] {fut.result()}", flush=True)
            except Exception as exc:  # noqa: BLE001
                fails += 1
                print(f"[{done}/{len(jobs)}] FAIL {j[1]}: {exc}", flush=True)
    print("DONE" if not fails else f"DONE with {fails} failures", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
