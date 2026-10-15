"""Download and verify the optional MossFormer2 denoise checkpoint.

Usage: python download_denoise_models.py [--check | --force] [--dest DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def sha256_of(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_path(value: str) -> Path:
    """`server/config.json` 里的相对路径以 `server/` 为基准（与 app.py 的 _resolve 一致）。"""
    path = Path(value)
    return path if path.is_absolute() else (ROOT / "server" / path).resolve()


def load_targets() -> list[dict[str, Any]]:
    server_config = ROOT / "server" / "config.json"
    if server_config.is_file():
        try:
            data = json.loads(server_config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"无法读取 {server_config}: {exc}") from exc
        block = data.get("denoise") if isinstance(data, dict) else None
        if isinstance(block, dict):
            checkpoint = block.get("checkpoint")
            size = block.get("size_bytes")
            if not checkpoint or not size or not block.get("sha256") or not block.get("download_url"):
                raise RuntimeError("server/config.json 的 denoise 配置缺少 checkpoint/size_bytes/sha256/download_url")
            return [{
                "path": resolve_path(checkpoint), "size": int(size), "sha256": block["sha256"],
                "url": block["download_url"], "fallback": block.get("download_url_fallback"),
                "note": block.get("note", ""),
            }]

    targets: list[dict[str, Any]] = []
    for config_path in sorted((ROOT / "models").glob("*/config.json")):
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"无法读取 {config_path}: {exc}") from exc
        for item in data.get("files", []):
            relpath = item.get("path")
            size = item.get("size_bytes")
            if not relpath or size is None or not item.get("sha256") or not item.get("url"):
                raise RuntimeError(f"{config_path} 中 files[] 条目缺少必需字段")
            targets.append({
                "path": config_path.parent / relpath, "size": int(size), "sha256": item["sha256"],
                "url": item["url"], "fallback": item.get("url_fallback"), "note": data.get("label", ""),
            })
    if not targets:
        raise RuntimeError("未找到降噪权重元数据：server/config.json 的 denoise 区块及 models/*/config.json 的 files[] 均不存在")
    return targets


def verify(path: Path, expected_size: int, expected_sha: str) -> tuple[bool, int, str | None]:
    if not path.is_file():
        return False, 0, None
    actual_size = path.stat().st_size
    actual_sha = sha256_of(path)
    return actual_size == expected_size and actual_sha.lower() == expected_sha.lower(), actual_size, actual_sha


def fetch(path: Path, urls: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for url in urls:
        command = ["curl", "-sSL", "--fail", "--retry", "5", "--retry-delay", "3",
                   "-C", "-", "-o", str(path), url]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            return
        error_lines = result.stderr.strip().splitlines()
        last_line = error_lines[-1] if error_lines else "(curl 未提供错误详情)"
        errors.append(f"curl exit {result.returncode}: {last_line}")
    raise RuntimeError("；".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description="下载并校验可选 MossFormer2 降噪权重")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只校验现有文件，不下载")
    mode.add_argument("--force", action="store_true", help="强制重新下载")
    parser.add_argument("--dest", help="目标目录覆盖（文件名仍取元数据中的 checkpoint）")
    args = parser.parse_args()

    try:
        targets = load_targets()
    except (RuntimeError, ValueError) as exc:
        print(f"fail 元数据: {exc}", file=sys.stderr)
        return 1

    failed = False
    for target in targets:
        path: Path = target["path"]
        if args.dest:
            path = Path(args.dest).expanduser().resolve() / path.name
        valid, actual_size, actual_sha = verify(path, target["size"], target["sha256"])
        if valid and not args.force:
            print(f"{'ok' if args.check else 'skip'} {path} ({actual_size} B, sha256 {actual_sha})", flush=True)
        elif args.check:
            hash_text = actual_sha if actual_sha else "缺失"
            print(f"fail {path}: size {actual_size}/{target['size']} B, sha256 {hash_text} (expected {target['sha256']})", flush=True)
            failed = True
        else:
            try:
                urls = [target["url"]]
                if target.get("fallback") and target["fallback"] not in urls:
                    urls.append(target["fallback"])
                fetch(path, urls)
                valid, actual_size, actual_sha = verify(path, target["size"], target["sha256"])
                if not valid:
                    print(f"fail {path}: size {actual_size}/{target['size']} B, sha256 {actual_sha or '缺失'} (expected {target['sha256']})", flush=True)
                    failed = True
                    continue
                print(f"ok {path} ({actual_size} B, sha256 {actual_sha})", flush=True)
            except (OSError, RuntimeError) as exc:
                print(f"fail {path}: {exc}", flush=True)
                failed = True
                continue
        if not failed and valid and not args.check:
            print(f"引擎权重可用：{path}；安装包不包含这些权重。", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
