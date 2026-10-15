from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import shutil
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
CONFIG = json.loads((APP_DIR / "config.json").read_text(encoding="utf-8"))
ROOT = Path(os.environ.get("MOSS_DOWNLOAD_ROOT") or ROOT_DIR).resolve()


def _target(item):
    # Config targets are repository-relative POSIX paths, even when running on Windows.
    return ROOT.joinpath(*PurePosixPath(item["target"]).parts)


def _resolve_cfg(path_value: str) -> Path:
    """config 里的路径相对 `server/`（写 `../models/...`），与 app._resolve 同义。"""
    q = Path(str(path_value))
    return q if q.is_absolute() else (APP_DIR / q).resolve()


def _has_weights(path: Path) -> bool:
    return path.is_dir() and ((path / "model.safetensors").is_file() or any(path.glob("model-*-of-*.safetensors")))


# 只有在用默认根（没有 MOSS_DOWNLOAD_ROOT 覆盖）时才允许认「本机已按落盘产物部署」的目录；
# 测试/自定义根下必须严格按该根的落地情况判断。
USING_DEFAULT_ROOT = ROOT == ROOT_DIR


def _usable_without_master(item_id: str, target: Path) -> bool:
    """openmoss-* 条目：除了下母本，本机若有「壳目录 + 落盘 int8 产物」也算该功能可用。"""
    models = CONFIG.get("models") or {}
    if item_id == "openmoss-tokenizer":
        for m in models.values():
            for key in ("codec_path", "codec_path_fallback"):
                if m.get(key) and _has_weights(_resolve_cfg(m[key])):
                    return True
        return False
    key = item_id.split("-", 1)[1]
    m = models.get(key)
    if not m:
        return False
    return target.is_dir() and _has_weights(_resolve_cfg(m.get("quant_checkpoint") or ""))


FFMPEG_LIBS = ("avcodec", "avformat", "avutil", "avfilter", "swscale", "swresample", "avdevice")


def _ffmpeg_ok(path: Path) -> bool:
    """接受两种布局：shared（ffmpeg.exe + libav 家族 DLL）或 static（单个自包含 exe）。

    swscale/swresample 不以 av 开头，所以不能只用 `av*.dll` 通配；静态构建（如 npmmirror 的
    ffmpeg-static，实为 gyan 官方 essentials 静态包）根本没有 DLL，也应视为可用。
    """
    if not (path / "ffmpeg.exe").is_file():
        return False
    libs = [p.name.lower() for p in path.glob("*.dll")]
    if not libs:
        return True
    return all(any(n.startswith(prefix) for n in libs) for prefix in FFMPEG_LIBS)


def _present(item):
    path = _target(item)
    ident = item["id"]
    if ident.startswith("openmoss-"):
        if _has_weights(path):
            return True
        return USING_DEFAULT_ROOT and _usable_without_master(ident, path)
    if ident == "ffmpeg":
        return _ffmpeg_ok(path)
    if ident == "whisper-small":
        return path.is_dir() and (path / "model.bin").is_file() and (path / "model.bin").stat().st_size == 483546902
    if not path.is_file():
        return False
    prefix = (item.get("source") or {}).get("prefix8")
    if prefix:
        # 上游不给确切体积/完整 sha256 时，bytes 只是估值：按数量级判断是否已落盘，
        # 真正的完整性在下载完成时用 sha256 前 8 位校验（与 demucs 自身的 check_checksum 同口径）。
        size = path.stat().st_size
        return item["bytes"] * 0.5 <= size <= item["bytes"] * 1.5
    size = path.stat().st_size
    return size == item["bytes"]


def _sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _modelscope_files(repo: str) -> list[dict]:
    """ModelScope 文件列表（每项带 Path / Size / Sha256），下载与校对共用。"""
    api = f"https://www.modelscope.cn/api/v1/models/{repo}/repo/files?Revision=master&Recursive=true"
    with urllib.request.urlopen(api, timeout=60) as response:
        return [f for f in json.load(response)["Data"]["Files"] if f.get("Type") == "blob"]


def _extract_zip_bin(archive: Path, target: Path) -> None:
    """把 zip 里 `<任意前缀>/bin/*` 平铺到 target（BtbN/gyan 的目录布局），随后自检必需文件。"""
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            parts = PurePosixPath(member.filename).parts
            if member.is_dir() or len(parts) < 3 or parts[-2] != "bin":
                continue
            out = target / parts[-1]
            with bundle.open(member) as inp, out.open("wb") as dst:
                shutil.copyfileobj(inp, dst)
    if not _ffmpeg_ok(target):
        raise ValueError("ffmpeg archive missing required executables or DLLs")


class Downloader:
    def __init__(self):
        self.items = CONFIG["downloads"]["items"]
        self.lock = threading.RLock()
        self.states = {x["id"]: {"status": "idle", "done_bytes": 0, "total_bytes": x["bytes"], "speed_bps": 0.0,
                                 "eta_s": None, "error": "", "verified": None} for x in self.items}
        self.queue = []
        self.current = None
        self.worker = None
        self.cancelled = set()
        self.progress_done = {x["id"]: 0 for x in self.items}
        self.progress_tick = {x["id"]: time.monotonic() for x in self.items}
        self.state_done_last = {x["id"]: 0 for x in self.items}
        self.verifying: set[str] = set()

    def catalog(self):
        return [dict(x) for x in self.items]

    def snapshot(self):
        free = shutil.disk_usage(ROOT).free
        with self.lock:
            rows = []
            for item in self.items:
                row = dict(item)
                row.update(self.states[item["id"]])
                path = _target(item)
                row["present"] = _present(item)
                row["present_bytes"] = path.stat().st_size if path.is_file() else sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() else 0
                # 界面数字必须自洽：0 字节 = 目录为空，只可能来自"复用共享权重"这条已就绪路径，
                # 不能显示成「已存在 (0 B)」；体积与下载包不同时显式给出两个数，别让用户对不上。
                row["shared_only"] = bool(row["present"] and (row["present_bytes"] == 0 or (item["id"].startswith("openmoss-") and not _has_weights(path))))
                approximate = bool((item.get("source") or {}).get("prefix8"))
                # 容差：几十 KB 级的差异（目录里多一个配置文件之类）不算"与下载包不同"，
                # 只有真正换了另一份构建（如 FFmpeg 全量 253 MB vs 下载包 79 MB）才提示。
                tolerance = max(1 << 20, int(item["bytes"] * 0.01))
                row["size_matches"] = None if (row["shared_only"] or approximate) else abs(row["present_bytes"] - item["bytes"]) <= tolerance
                if row["present"] and row["status"] not in ("queued", "running", "verifying"):
                    # 已落盘就不该再显示上一次的下载进度（.part 残留会显示成 616 KB / 78.96 MB）
                    row.update(done_bytes=0, speed_bps=0.0, eta_s=None)
                row["source_label"] = item.get("source_label", "")
                row["target"] = str(path)
                rows.append(row)
            return {"items": rows, "disk": {"free_bytes": free, "root": str(ROOT)}, "required_missing": [r["id"] for r in rows if r["group"] == "required" and not r["present"]], "active": self.current}

    def start(self, ids):
        started, skipped = [], []
        with self.lock:
            known = {x["id"]: x for x in self.items}
            for ident in ids:
                item = known.get(ident)
                if item is None or self.states[ident]["status"] in ("queued", "running") or _present(item):
                    skipped.append(ident)
                    continue
                free = shutil.disk_usage(ROOT).free
                needed = int(item["bytes"] * 1.05)
                if free < needed:
                    raise ValueError(f"Insufficient disk space for {ident}: need {needed}, have {free}")
                self.states[ident].update(status="queued", error="", done_bytes=0, speed_bps=0.0, eta_s=None, verified=None)
                self.progress_done[ident] = 0
                self.state_done_last[ident] = 0
                self.progress_tick[ident] = time.monotonic()
                self.queue.append(ident)
                started.append(ident)
            self._ensure_worker()
        return {"started": started, "skipped": skipped, "error": None}

    def cancel(self, ids):
        canceled = []
        with self.lock:
            for ident in ids:
                if ident in self.states and self.states[ident]["status"] in ("queued", "running"):
                    self.cancelled.add(ident)
                    if ident in self.queue:
                        self.queue.remove(ident)
                        self.states[ident]["status"] = "canceled"
                        self.cancelled.discard(ident)
                    canceled.append(ident)
        return {"canceled": canceled}

    def _ensure_worker(self):
        if self.worker is None or not self.worker.is_alive():
            self.worker = threading.Thread(target=self._run, daemon=True, name="asset-downloader")
            self.worker.start()

    def _run(self):
        while True:
            with self.lock:
                if not self.queue:
                    self.current = None
                    return
                ident = self.queue.pop(0)
                self.current = ident
                state = self.states[ident]
                state.update(status="running", error="")
            try:
                self._download(next(x for x in self.items if x["id"] == ident))
                with self.lock:
                    if ident in self.cancelled:
                        self.states[ident]["status"] = "canceled"
                    else:
                        # 下载过程中每个文件都按 sha256/zip sha/前缀校验过，完成即视为已校对
                        self.states[ident].update(status="done", verified=True, error="")
            except Exception as exc:
                with self.lock:
                    self.states[ident].update(status="error", error=str(exc))
            finally:
                with self.lock:
                    self.cancelled.discard(ident)

    def _download(self, item):
        ident, target, source = item["id"], _target(item), item["source"]
        if source["type"] == "modelscope":
            target.mkdir(parents=True, exist_ok=True)
            files = _modelscope_files(source["repo"])
            total = sum(int(f["Size"]) for f in files)
            with self.lock:
                self.states[ident].update(total_bytes=total, done_bytes=0)
            def fetch(meta):
                if self._is_cancelled(ident):
                    return
                relative = PurePosixPath(meta["Path"])
                dest = target.joinpath(*relative.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                url = f"https://www.modelscope.cn/api/v1/models/{source['repo']}/repo?Revision=master&FilePath={urllib.parse.quote(meta['Path'], safe='')}"
                self._fetch_file(ident, url, dest, int(meta["Size"]), meta.get("Sha256"), total, item)
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(fetch, meta) for meta in files]
                for future in concurrent.futures.as_completed(futures):
                    future.result()
                    if self._is_cancelled(ident):
                        for f in futures:
                            f.cancel()
                        break
        else:
            # 多源候选：主源 → fallback_sources → 兼容旧字段 url_fallback
            variants = [source, *list(source.get("fallback_sources") or [])]
            if source.get("url_fallback"):
                variants.append({**source, "url": source["url_fallback"], "url_fallback": None})
            last_error = None
            for variant in variants:
                try:
                    self._download_one(ident, item, target, variant)
                    last_error = None
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if self._is_cancelled(ident):
                        return
            if last_error:
                raise last_error

    def _download_one(self, ident, item, target: Path, source: dict) -> None:
        """单个源的取件 + 校验（zip 解包 / bin 单文件 / 普通单文件）。"""
        size = int(source.get("bytes") or item["bytes"])
        if source["type"] == "zip":
            # 落成真实的 .zip 名：_fetch_file 自己会再加 .part（避免 xxx.part.part）
            archive = target.with_name(target.name + ".zip")
        elif source["type"] == "bin":
            # 单个可执行文件落进目标目录（目标按目录解释）
            archive = target / str(source.get("name") or "ffmpeg.exe")
        else:
            archive = target
        archive.parent.mkdir(parents=True, exist_ok=True)
        self._fetch_file(ident, source["url"], archive, size, source.get("sha256"), size, item,
                         prefix=source.get("prefix8"))
        if self._is_cancelled(ident):
            return
        if source["type"] == "zip":
            if _sha(archive) != source["sha256"]:
                archive.unlink(missing_ok=True)
                raise ValueError("ffmpeg archive sha256 mismatch")
            _extract_zip_bin(archive, target)
            archive.unlink(missing_ok=True)
        elif source["type"] == "bin" and not _ffmpeg_ok(target):
            raise ValueError("下载的 ffmpeg 不可用（文件缺失或 DLL 不全）")

    def _fetch_file(self, ident, url, dest, size, sha, total, item, prefix=None):
        part = dest.with_name(dest.name + ".part")
        # 有 prefix（= 上游不给确切体积，如 demucs）时 bytes 只是估值，不能当硬性校验；
        # 完整性改由 sha256 前 8 位承担（与 demucs 自身 repo.check_checksum 同口径）。
        exact_size = not prefix
        if dest.is_file() and (not exact_size or dest.stat().st_size == size):
            actual = _sha(dest) if (sha or prefix) else None
            if (not sha and not prefix) or (sha and actual == sha) or (prefix and actual.startswith(prefix)):
                self._account(ident, dest.stat().st_size, total)
                return
            dest.unlink()
        for attempt in range(5):   # GitHub / dl.fbaipublicfiles 在部分网络下几十 KB 就断流：多轮 Range 续传
            have = part.stat().st_size if part.exists() else 0
            if exact_size and have > size:
                part.unlink()
                have = 0
            headers = {"Range": f"bytes={have}-"} if have else {}
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    status = getattr(response, "status", response.getcode())
                    ranged = have > 0 and status == 206
                    if have and not ranged:
                        part.unlink(missing_ok=True)
                        have = 0
                    length = response.headers.get("Content-Length") or ""
                    expected = have + int(length) if length.isdigit() else (size if exact_size else None)
                    mode = "ab" if ranged else "wb"
                    written = have
                    with part.open(mode) as output:
                        while True:
                            if self._is_cancelled(ident):
                                return
                            block = response.read(1 << 20)
                            if not block:
                                break
                            output.write(block)
                            written += len(block)
                            self._report(ident, total, written)
                got = part.stat().st_size
                if expected and got != expected:
                    raise ValueError(f"{dest.name}: size mismatch {got} != {expected}")
                if exact_size and got != size:
                    raise ValueError(f"{dest.name}: size mismatch {got} != {size}")
                actual = _sha(part) if (sha or prefix) else None
                if (sha and actual != sha) or (prefix and not actual.startswith(prefix)):
                    part.unlink(missing_ok=True)
                    dest.unlink(missing_ok=True)
                    if attempt:
                        raise ValueError(f"{dest.name}: checksum mismatch")
                    continue
                part.replace(dest)
                self._account(ident, got, total)
                return
            except Exception as exc:
                if attempt + 1 >= 5:
                    raise ValueError(f"{dest.name}: {exc}") from exc
                time.sleep(min(5.0, 0.5 * (attempt + 1)))   # 保留断点，下一轮用 Range 续传

    def _account(self, ident, size, total):
        with self.lock:
            self.progress_done[ident] += size
            self.state_done_last[ident] = self.progress_done[ident]
            self.states[ident].update(done_bytes=self.progress_done[ident], total_bytes=total)

    def _report(self, ident, total, file_bytes):
        now = time.monotonic()
        with self.lock:
            state = self.states[ident]
            done = self.progress_done[ident] + max(0, file_bytes)
            then = self.progress_tick[ident]
            if now - then >= 0.5:
                speed = (done - self.state_done_last.get(ident, 0)) / (now - then)
                self.progress_tick[ident] = now
                self.state_done_last[ident] = done
                state.update(done_bytes=done, total_bytes=total, speed_bps=round(max(0.0, speed), 1),
                             eta_s=max(0, int((total - done) / speed)) if speed > 0 else None)
            else:
                state.update(done_bytes=done, total_bytes=total)

    # ------------------------------------------------------------------ 落盘校对
    def verify(self, ids):
        """对指定条目做一次落盘校对（逐文件 sha256 / 前缀 / 尺寸）。返回被受理的条目。"""
        with self.lock:
            todo = [i for i in ids if i in self.states and self.states[i]["status"] not in ("queued", "running", "verifying")]
            for ident in todo:
                self.verifying.add(ident)
        if todo:
            threading.Thread(target=self._verify_run, args=(todo,), daemon=True, name="asset-verify").start()
        return {"verifying": todo}

    def _files_to_check(self, item):
        """[(显示名, 绝对路径, 期望 sha256|None, 期望尺寸|None, 期望 sha256 前缀|None)]"""
        source, target = item["source"], _target(item)
        if source["type"] == "modelscope":
            rows = []
            for meta in _modelscope_files(source["repo"]):
                rel = PurePosixPath(meta["Path"])
                rows.append((str(rel), target.joinpath(*rel.parts), meta.get("Sha256") or None, int(meta["Size"]), None))
            return rows
        prefix = source.get("prefix8")
        if source["type"] == "bin":
            path = target / source["name"]
            return [(path.name, path, source.get("sha256") or None, None if prefix else int(item["bytes"]), prefix)]
        return [(target.name, target, source.get("sha256") or None, None if prefix else int(item["bytes"]), prefix)]

    def _verify_item(self, item) -> tuple[bool, int, int]:
        entries = self._files_to_check(item)
        total = sum((e[3] or 0) for e in entries) or 1
        done = matched = 0
        if item["id"] == "ffmpeg":
            # Static and shared FFmpeg builds are both supported; their byte sizes differ.
            ok = _ffmpeg_ok(_target(item))
            path = _target(item) / item["source"]["name"]
            done = path.stat().st_size if path.is_file() else 0
            matched = int(ok)
            with self.lock:
                self.states[item["id"]].update(
                    done_bytes=done, total_bytes=max(done, 1), speed_bps=0.0, eta_s=None,
                    error="" if ok else "ffmpeg 缺失或布局无效")
            return ok, matched, 1
        for name, path, sha, size, prefix in entries:
            if not path.is_file():
                with self.lock:
                    self.states[item["id"]].update(done_bytes=done, total_bytes=total)
                return False, matched, len(entries)
            if prefix:
                ok = _sha(path).startswith(prefix)
            elif sha:
                ok = _sha(path) == sha
            elif size:
                ok = path.stat().st_size == size
            else:
                ok = True
            done += path.stat().st_size
            matched += 1 if ok else 0
            with self.lock:
                self.states[item["id"]].update(done_bytes=done, total_bytes=total, speed_bps=0.0, eta_s=None,
                                               error="" if ok else f"{name}: 校验失败")
            if not ok:
                return False, matched, len(entries)
        return True, matched, len(entries)

    def _verify_run(self, ids):
        for ident in ids:
            item = next(x for x in self.items if x["id"] == ident)
            with self.lock:
                self.states[ident].update(status="verifying", error="", done_bytes=0, speed_bps=0.0, eta_s=None)
            try:
                ok, matched, total = self._verify_item(item)
                with self.lock:
                    error = "" if ok else (
                        f"ffmpeg 缺失或布局无效（{matched}/{total} 个必需文件）" if ident == "ffmpeg"
                        else f"校对未通过（{matched}/{total} 个文件匹配）")
                    self.states[ident].update(status="idle", verified=bool(ok), error=error)
            except Exception as exc:  # noqa: BLE001
                with self.lock:
                    self.states[ident].update(status="idle", verified=False, error=f"校对失败：{exc}")
            finally:
                with self.lock:
                    self.verifying.discard(ident)

    def _is_cancelled(self, ident):
        with self.lock:
            return ident in self.cancelled


ENGINE = Downloader()

def catalog():
    return ENGINE.catalog()

def snapshot():
    return ENGINE.snapshot()

def start(ids):
    return ENGINE.start(ids)

def cancel(ids):
    return ENGINE.cancel(ids)

def verify(ids):
    return ENGINE.verify(ids)
