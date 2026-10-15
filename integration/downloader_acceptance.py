"""统一下载器端到端验收（回归用）。

用法：
  python integration/downloader_acceptance.py api        --base http://127.0.0.1:17980 --root <测试根>
  python integration/downloader_acceptance.py standalone --port 17990 --root <测试根> [--python <解释器>]

用测试根（`MOSS_DOWNLOAD_ROOT`）跑，不会碰安装目录里的真实权重；`standalone` 模式会自起/自停独立界面。
覆盖：目录形状/分组/体积 → 真下载(ModelScope)+sha256 → 取消+断点续传 → 主动校对 → zip 解包逻辑。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

EXPECTED = {
    "ffmpeg": ("required", 82_797_568),
    "openmoss-tokenizer": ("required", 7_101_116_247),
    "openmoss-tts": ("required", 16_995_701_633),
    "openmoss-ttsd": ("required", 16_727_055_254),
    "openmoss-sfx": ("required", 16_727_042_030),
    "openmoss-vg": ("required", 4_244_249_582),
    "demucs": ("optional", None),
    "mossformer2": ("optional", 221_552_019),
    "whisper-small": ("optional", 486_236_531),
}
MOSSFORMER2_SHA = "03692b9f773bbd6bb43b9c5a41f96b1e28affd66e13796b7bec66ad3d8b227c6"
FAST_ITEM = "mossformer2"      # ModelScope 快源（本机 ~12 MB/s），用于真下载/续传/校验链路
FAILURES: list[str] = []


def check(ok: bool, what: str, detail: str = "") -> bool:
    print(f"  [{'ok' if ok else 'FAIL'}] {what}{(' — ' + detail) if detail else ''}", flush=True)
    if not ok:
        FAILURES.append(f"{what}{(' — ' + detail) if detail else ''}")
    return ok


def api(base: str, method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_ready(base: str, timeout: float = 25.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            api(base, "GET", "/api/downloads")
            return True
        except Exception:
            time.sleep(0.4)
    return False


def item_of(snap: dict, iid: str) -> dict | None:
    return next((i for i in snap.get("items", []) if i.get("id") == iid), None)


def poll(base: str, iid: str, terminal: set[str], timeout: float, label: str) -> dict:
    end, last, shown = time.time() + timeout, None, 0
    while time.time() < end:
        it = item_of(api(base, "GET", "/api/downloads"), iid) or {}
        if it.get("status") != last and shown < 14:
            print(f"    · {label} status={it.get('status')} "
                  f"{it.get('done_bytes', 0)/1e6:.1f}/{it.get('bytes', 0)/1e6:.1f} MB "
                  f"{it.get('speed_bps', 0)/1e6:.1f} MB/s eta={it.get('eta_s')} verified={it.get('verified')}")
            last, shown = it.get("status"), shown + 1
        if it.get("status") in terminal:
            return it
        time.sleep(1.0)
    return item_of(api(base, "GET", "/api/downloads"), iid) or {}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def section_catalog(base: str, root: Path) -> None:
    print("\n[1/5] 目录/分组/体积/固定落地根")
    snap = api(base, "GET", "/api/downloads")
    items = snap.get("items", [])
    check(len(items) == 9, "目录 9 个条目", f"实际 {len(items)}")
    for iid, (group, size) in EXPECTED.items():
        it = item_of(snap, iid)
        if it is None:
            check(False, f"条目 {iid} 存在")
            continue
        check(it.get("group") == group, f"{iid} 分组 = {group}", f"实际 {it.get('group')}")
        if size is not None:
            check(int(it.get("bytes") or 0) == size, f"{iid} 体积 = {size}", f"实际 {it.get('bytes')}")
        check(Path(str(it.get("target", ""))).as_posix().startswith(root.as_posix().rstrip("/")),
              f"{iid} 落地在固定根下", str(it.get("target")))
    check(isinstance(snap.get("required_missing"), list), "required_missing 是列表")
    check(int(snap.get("disk", {}).get("free_bytes", -1)) > 0, "disk.free_bytes > 0")
    check(str(snap.get("disk", {}).get("root", "")) == str(root), "disk.root = 固定安装根",
          f"{snap.get('disk', {}).get('root')}")


def section_download(base: str, root: Path) -> None:
    print(f"\n[2/5] 真下载 + 校验（{FAST_ITEM}）")
    api(base, "POST", "/api/downloads/start", {"ids": [FAST_ITEM]})
    it = poll(base, FAST_ITEM, {"done", "error", "canceled"}, timeout=900, label="first")
    check(it.get("status") == "done", "下载完成", f"status={it.get('status')} err={it.get('error')}")
    check(it.get("verified") is True, "完成即带成功标识 verified=true", f"verified={it.get('verified')}")
    check(it.get("present") is True, "present=true")
    f = root / "models" / "MossFormer2_SE_48K" / "last_best_checkpoint.pt"
    check(f.is_file() and f.stat().st_size == EXPECTED[FAST_ITEM][1], "落盘体积正确", str(f))
    check(f.is_file() and sha256(f) == MOSSFORMER2_SHA, "sha256 与上游一致")


def section_resume(base: str, root: Path) -> None:
    print(f"\n[3/5] 取消 + 断点续传（{FAST_ITEM}）")
    target = root / "models" / "MossFormer2_SE_48K" / "last_best_checkpoint.pt"
    target.unlink(missing_ok=True)
    for p in target.parent.glob("*.part"):
        p.unlink()
    api(base, "POST", "/api/downloads/start", {"ids": [FAST_ITEM]})
    time.sleep(4.0)
    api(base, "POST", "/api/downloads/cancel", {"ids": [FAST_ITEM]})
    it = poll(base, FAST_ITEM, {"canceled", "error", "done"}, timeout=90, label="cancel")
    parts = list(target.parent.glob("*.part"))
    if it.get("status") == "done":
        print("    · 取消前已下完，改为校验哈希")
    else:
        check(it.get("status") == "canceled", "取消被受理", f"status={it.get('status')}")
        check(bool(parts), "取消后保留断点 .part", f"parts={[p.name for p in parts]}")
    api(base, "POST", "/api/downloads/start", {"ids": [FAST_ITEM]})
    it = poll(base, FAST_ITEM, {"done", "error", "canceled"}, timeout=900, label="resume")
    check(it.get("status") == "done", "续传后完成", f"status={it.get('status')} err={it.get('error')}")
    check(target.is_file() and sha256(target) == MOSSFORMER2_SHA, "续传后哈希仍正确")


def section_verify(base: str, root: Path) -> None:
    print(f"\n[4/5] 主动校对（{FAST_ITEM}）")
    api(base, "POST", "/api/downloads/verify", {"ids": [FAST_ITEM]})
    end, it = time.time() + 600, {}
    while time.time() < end:
        it = item_of(api(base, "GET", "/api/downloads"), FAST_ITEM) or {}
        if it.get("status") != "verifying":
            break
        time.sleep(1.0)
    check(it.get("verified") is True, "校对通过 verified=true", f"verified={it.get('verified')} err={it.get('error')}")


def section_extract(root: Path) -> None:
    print("\n[5/5] zip 解包逻辑（合成包，不依赖 GitHub 慢源）")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
    import downloads as engine  # noqa: PLC0415

    work = root / "_ziptest"
    work.mkdir(parents=True, exist_ok=True)
    archive = work / "synthetic.zip"
    names = ["ffmpeg.exe", "ffprobe.exe", "avcodec-62.dll", "avformat-62.dll", "avutil-60.dll",
             "avfilter-11.dll", "swscale-9.dll", "swresample-6.dll", "avdevice-62.dll"]
    with zipfile.ZipFile(archive, "w") as z:
        for n in names:
            z.writestr(f"ffmpeg-n8.1-latest-win64-gpl-shared-8.1/bin/{n}", b"x" * 32)
        z.writestr("ffmpeg-n8.1-latest-win64-gpl-shared-8.1/doc/notes.txt", b"ignore me")
    out = work / "ffmpeg"
    engine._extract_zip_bin(archive, out)          # 应当平铺 bin/* 且自检通过
    got = sorted(p.name for p in out.glob("*"))
    check(sorted(names) == got, "bin/* 平铺到目标目录", f"{got}")
    check(engine._ffmpeg_ok(out) is True, "_ffmpeg_ok 认可该布局（含 swscale/swresample）")


def section_ffmpeg_item(base: str, root: Path) -> None:
    print("\n[6/6] 真下载 ffmpeg（国内镜像主源）+ 可执行性")
    api(base, "POST", "/api/downloads/start", {"ids": ["ffmpeg"]})
    it = poll(base, "ffmpeg", {"done", "error", "canceled"}, timeout=900, label="ffmpeg")
    check(it.get("status") == "done", "ffmpeg 下载完成", f"status={it.get('status')} err={it.get('error')}")
    check(it.get("verified") is True, "ffmpeg verified=true", f"verified={it.get('verified')}")
    check(it.get("present") is True, "ffmpeg present=true")
    exe = root / "runtime" / "ffmpeg" / "ffmpeg.exe"
    check(exe.is_file(), "落盘 ffmpeg.exe", str(exe))
    if exe.is_file():
        try:
            out = subprocess.run([str(exe), "-version"], capture_output=True, text=True, timeout=60)
            first = ((out.stdout or out.stderr) or "").splitlines()[0] if (out.stdout or out.stderr) else ""
            check(out.returncode == 0 and "ffmpeg version" in first.lower(), "下载的 ffmpeg.exe 可执行", first[:90])
        except Exception as exc:  # noqa: BLE001
            check(False, "下载的 ffmpeg.exe 可执行", repr(exc))


def run_checks(base: str, root: Path) -> None:
    section_catalog(base, root)
    section_download(base, root)
    section_resume(base, root)
    section_verify(base, root)
    section_extract(root)
    section_ffmpeg_item(base, root)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["api", "standalone"])
    ap.add_argument("--base", default="")
    ap.add_argument("--port", type=int, default=17990)
    ap.add_argument("--root", required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    proc = None
    try:
        if args.mode == "standalone":
            base = f"http://127.0.0.1:{args.port}"
            env = dict(os.environ, MOSS_DOWNLOAD_ROOT=str(root))
            cmd = [args.python, str(Path(args.repo) / "tools" / "downloader_ui.py"),
                   "--port", str(args.port), "--root", str(root), "--no-browser"]
            print(f"启动独立界面: {' '.join(cmd)}")
            proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if not wait_ready(base, 30):
                try:
                    print((proc.stdout.read() or "")[:3000] if proc.stdout else "")
                except Exception:
                    pass
                return 1
            print(f"独立界面就绪: {base}")
        else:
            base = args.base or "http://127.0.0.1:17980"
            if not wait_ready(base, 20):
                print(f"服务端未就绪: {base}")
                return 1
        run_checks(base, root)
    finally:
        if proc is not None:
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
                else:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                pass

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
