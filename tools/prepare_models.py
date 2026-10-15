"""Finish preparing the MOSS models: merge shards, verify, write a manifest.

Order matters on a nearly-full disk: the merged file is written while the shards are
deleted one by one, so peak extra space is one shard (~5 GB).

Usage:
  python prepare_models.py                # merge every model that still has shards
  python prepare_models.py --model sfx    # one model (ttsd | sfx | tts | vg)
  python prepare_models.py --check        # report only, no changes
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = {
    "ttsd": ROOT / "models" / "openmoss" / "MOSS-TTSD-v1.0",
    "sfx": ROOT / "models" / "openmoss" / "MOSS-SoundEffect",
    "tts": ROOT / "models" / "openmoss" / "MOSS-TTS-v1.5",
    "vg": ROOT / "models" / "openmoss" / "MOSS-VoiceGenerator",
}
HERE = Path(__file__).resolve().parent


def shards(directory: Path) -> list[Path]:
    return sorted(directory.glob("model-*-of-*.safetensors"))


def digest(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while data := f.read(chunk):
            h.update(data)
    return h.hexdigest()


def manifest_for(directory: Path) -> dict:
    entry = {"dir": str(directory), "files": {}}
    for path in sorted(directory.glob("*")):
        if path.is_file():
            entry["files"][path.name] = {"size": path.stat().st_size, "sha256": digest(path)}
    return entry


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="core", help="core (ttsd+sfx) | all | ttsd | sfx | tts | vg")
    ap.add_argument("--manifest-only", action="store_true", help="hash + write MANIFEST.json without merging")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-manifest", action="store_true")
    args = ap.parse_args()

    if args.model == "all":
        keys = list(MODELS)
    elif args.model == "core":
        keys = ["ttsd", "sfx"]   # 日常只需要这两个（codec 是自足的单文件目录，无需合并）
    else:
        keys = [args.model]
    rc = 0
    for key in keys:
        directory = MODELS[key]
        if not directory.is_dir():
            print(f"[{key}] missing directory {directory}")
            rc = 1
            continue
        if args.manifest_only:
            man = manifest_for(directory)
            man["model"] = key
            (directory / "MANIFEST.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
            print(f"[{key}] manifest rewritten for {len(man['files'])} files")
            continue
        pending = shards(directory)
        merged = directory / "model.safetensors"
        state = "merged" if merged.exists() and not pending else (f"{len(pending)} shards" if pending else "EMPTY")
        print(f"[{key}] {directory} -> {state}")
        if args.check:
            continue
        if pending:
            proc = subprocess.run(
                [sys.executable, str(HERE / "merge_shards.py"), str(directory)],
                capture_output=True, text=True,
            )
            print(proc.stdout.strip() or proc.stderr.strip()[-800:])
            if proc.returncode != 0:
                rc = 1
                continue
        if not args.no_manifest:
            man = manifest_for(directory)
            man["model"] = key
            (directory / "MANIFEST.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
            size = sum(f["size"] for f in man["files"].values())
            print(f"[{key}] manifest written, {len(man['files'])} files, {size / 1e9:.2f} GB")
    return rc


if __name__ == "__main__":
    sys.exit(main())
