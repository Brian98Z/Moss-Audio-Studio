"""End-to-end smoke test of the patched launcher.

Launches the GUI client, waits for the workbench backend it spawns to answer on its
port, checks that the served page is the workbench UI (including the single-speaker tab
and its voice list endpoint), then shuts the launcher (and its python child) down.

Usage: python smoke_launcher.py [--keep-running]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

LAUNCHER = Path(r"D:\MossTTSD\client\MOSS语音工作台-启动器.exe")
PORT = 17980


def http_get(url: str, timeout: float = 4.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-running", action="store_true")
    args = ap.parse_args()

    proc = subprocess.Popen(
        [str(LAUNCHER)],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    print(f"launcher pid {proc.pid}")

    checks: list[tuple[str, bool]] = []
    deadline = time.time() + 180
    while time.time() < deadline:
        code, body = http_get(f"http://127.0.0.1:{PORT}/api/health")
        if code == 200:
            print(f"backend health: {body.strip()}")
            code2, page = http_get(f"http://127.0.0.1:{PORT}/")
            title = page.split("<title>")[1].split("</title>")[0] if "<title>" in page else "?"
            print(f"served page title: {title}")
            checks.append(("页面是工作台", "MOSS 语音工作台" in title))
            checks.append(("含单人配音标签页", 'data-tab="tts"' in page))
            checks.append(("含音色设计标签页", 'data-tab="vg"' in page and 'id="tab-vg"' in page))
            code3, voices = http_get(f"http://127.0.0.1:{PORT}/api/tts/voices")
            try:
                count = len(json.loads(voices)["voices"])
            except Exception:  # noqa: BLE001
                count = -1
            print(f"/api/tts/voices -> {code3}, {count} voices")
            checks.append(("单后端已注册单人配音模型", "/api/tts/generate" in page or code3 == 200))
            code4, state = http_get(f"http://127.0.0.1:{PORT}/api/state")
            keys = []
            try:
                keys = [m.get("key") for m in json.loads(state).get("models", [])]
            except Exception:  # noqa: BLE001
                pass
            print(f"/api/state models -> {code4}, {keys}")
            checks.append(("已注册音色设计模型 vg", "vg" in keys))
            break
        time.sleep(2)

    if not checks:
        print("RESULT: FAIL (launcher did not bring the workbench backend up)")
        ok = False
    else:
        for name, passed in checks:
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = all(passed for _name, passed in checks)
        print("RESULT:", "PASS" if ok else "FAIL")

    if not args.keep_running:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        time.sleep(1)
        print("launcher stopped")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
