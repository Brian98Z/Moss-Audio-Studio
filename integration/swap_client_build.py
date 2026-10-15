"""用 `.new` 暂存件替换客户端构建（`resources\\app.asar` + 启动器 exe），替换前校验并在替换后复核 md5。

用法：
  python integration/swap_client_build.py --check            :: 只看状态，不动文件
  python integration/swap_client_build.py                    :: 替换（要求客户端已完全退出）
  python integration/swap_client_build.py --client DIR       :: 自定义 client 目录

为什么必须退出客户端：运行中的 Electron 一直映射 `app.asar`，Windows 也锁定 exe 映像文件，
`os.replace` 会报 WinError 32/5；而且这次替换**会改变文件长度**（图标/元数据都变了），
不能像旧流程那样「长度不变就原地覆写」——运行中进程手里是旧长度的 section，写坏风险很大。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_CLIENT = Path(r"D:\MossTTSD\client")


def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def launcher_exe(client: Path) -> Path:
    hits = sorted(client.glob("*启动器*.exe"))
    if len(hits) != 1:
        raise SystemExit(f"启动器 exe 定位失败（找到 {len(hits)} 个）：{hits}")
    return hits[0]


def running(image: str) -> list[str]:
    proc = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
                          capture_output=True, text=True, errors="replace")
    return [ln for ln in proc.stdout.splitlines() if image.lower() in ln.lower()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default=str(DEFAULT_CLIENT))
    ap.add_argument("--check", action="store_true", help="只报告状态，不替换")
    args = ap.parse_args()

    client = Path(args.client)
    exe = launcher_exe(client)
    pairs = [(client / "resources" / "app.asar", client / "resources" / "app.asar.new"),
             (exe, exe.with_name(exe.name + ".new"))]

    procs = running(exe.name)
    print(f"客户端进程: {'运行中 ' + str(len(procs)) + ' 个' if procs else '已退出'}")
    pairs = [(target, staged) for target, staged in pairs if staged.exists()]
    if not pairs:
        raise SystemExit("没有发现任何 `.new` 暂存件（先用 apply_launcher_patch.py / exe_branding.js 生成）")
    for target, staged in pairs:
        same = target.exists() and md5(target) == md5(staged)
        print(f"{target.name}: target={target.stat().st_size} B / staged={staged.stat().st_size} B"
              f" / 内容{'相同' if same else '不同'}")
    if args.check:
        return 0
    if procs:
        raise SystemExit("客户端仍在运行 —— 请完全退出后重跑（Electron 映射着 app.asar，替换会失败）")

    for target, staged in pairs:
        staged_md5 = md5(staged)
        before = md5(target) if target.exists() else "-"
        os.replace(staged, target)
        after = md5(target)
        if after != staged_md5:
            raise SystemExit(f"替换后 md5 与暂存件不一致：{target}")
        print(f"替换 {target.name}: {before} -> {after}（{target.stat().st_size} B）")
    print("替换完成；接下来跑 integration\\smoke_launcher.py 做端到端验证")
    return 0


if __name__ == "__main__":
    sys.exit(main())
