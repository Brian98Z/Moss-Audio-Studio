#!/usr/bin/env python3
"""独立下载器界面（**仅 stdlib**）。

用途：装完主程序 / 依赖环境就绪后，用它拉起「下载中心」。它**不依赖 pip 环境、不依赖工作台服务端**
（17980），所以环境没装好也能先把模型拉下来。

页面与后端逻辑复用同一份文件，避免第二套实现：
- 页面：`server/web/downloads.html`（+ `.js` / `.css`，以及它引用的 `style.css`/`theme.js`/`i18n.js`）
- 引擎：`server/downloads.py`（`catalog()` / `snapshot()` / `start(ids)` / `cancel(ids)`）

API:
  GET  /api/downloads         -> 原下载状态
  POST /api/downloads/start   <- {ids:[...]}
  POST /api/downloads/cancel  <- {ids:[...]}
  POST /api/downloads/verify  <- {ids:[...]}
  GET  /api/env/status        -> 环境状态、解释器、torch/CUDA 信息
  GET  /api/env/log           -> 日志尾部及进度
  POST /api/env/start         <- {mirror:"tsinghua|pypi|aliyun", retry?:true}
  POST /api/env/cancel        -> 取消准备
  GET  /api/health            -> {ok:true}
  GET  / | /downloads         -> 环境准备 + 下载中心

启动后会打印一行 JSON（供启动器解析端口）。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import env_setup

REPO_DIR = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_DIR / "server"
WEB_DIR = SERVER_DIR / "web"
DEFAULT_PORT = 17990
PORT_SCAN = 11

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}
_ENV_PANEL = '''<style>#envPanel{padding-bottom:0}#envPanel + .page{padding-top:0}</style><section id="envPanel" class="page downloads-page"><header class="hero"><h1>① 环境准备</h1><p>首次使用需准备运行环境（约 3.4 GB 依赖 + 模型按需下载）</p></header><div class="panel"><p>Python 解释器：<code id="envPython">检测中…</code></p><label>软件源：<select id="envMirror"><option value="auto">自动切换（清华→阿里云→PyPI）</option><option value="tsinghua">清华 PyPI 镜像</option><option value="pypi">PyPI 官方源</option><option value="aliyun">阿里云镜像</option></select></label><div class="download-actions"><button id="envStart">一键安装环境依赖</button><button id="envCancel">取消</button><button id="envRetry">换源重试</button></div><progress id="envProgress" max="100" value="0"></progress><span id="envProgressText"></span><pre id="envLog" style="max-height:14em;overflow:auto;white-space:pre-wrap"></pre></div></section>'''.encode('utf-8')

_ENV_SCRIPT = '''<script>(function(){try{parent.postMessage({type:'moss-env-ready'},'*')}catch(e){}const $=id=>document.getElementById(id);async function call(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});return r.json()}async function refresh(){try{const s=await call('/api/env/status');$('envPython').textContent=s.interpreter||'未找到 Python 3.12 x64';$('envProgress').value=s.percent||0;$('envProgressText').textContent='已下载 '+(s.downloaded_gb||0)+' GB / ≈3.4 GB · '+s.percent+'%';const l=await call('/api/env/log');$('envLog').textContent=l.lines.join('\\n');$('envLog').scrollTop=$('envLog').scrollHeight;if(s.state==='ready'){$('envPanel').innerHTML='<section class="panel"><h2>① 环境准备</h2><p><strong>✓ 本机环境已完成</strong>：依赖已就绪，无需重新安装。</p><p style="opacity:.75">torch '+(s.torch_version||'—')+(s.cuda_available==null?'':' / CUDA '+(s.cuda_available?'可用':'不可用'))+'</p><button type="button" id="envRebuild">重新安装</button></section>';var rb=$('envRebuild');if(rb){rb.onclick=()=>call('/api/env/start',{mirror:'auto',retry:true})}}}catch(e){}setTimeout(refresh,1200)}$('envStart').onclick=()=>call('/api/env/start',{mirror:$('envMirror').value});$('envCancel').onclick=()=>call('/api/env/cancel',{});$('envRetry').onclick=()=>call('/api/env/start',{mirror:$('envMirror').value,retry:true});refresh()})();</script>'''.encode('utf-8')


def load_engine():
    """导入 server/downloads.py（仅 stdlib，不 import fastapi）。"""
    if str(SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(SERVER_DIR))
    import downloads  # noqa: PLC0415

    missing = [n for n in ("snapshot", "start", "cancel", "verify") if not callable(getattr(downloads, n, None))]
    if missing:
        raise RuntimeError(f"server/downloads.py 缺少接口: {', '.join(missing)}")
    return downloads


def ui_build() -> str:
    """缓存戳：取 server/web 下最新 mtime，供页面 `?v=__UI_BUILD__` 使用（与工作台同一语义）。"""
    try:
        newest = max((p.stat().st_mtime for p in WEB_DIR.glob("*") if p.is_file()), default=0.0)
    except OSError:
        newest = 0.0
    return str(int(newest))


class Handler(BaseHTTPRequestHandler):
    server_version = "MossDownloaderUI/1.0"
    protocol_version = "HTTP/1.1"
    engine = None

    # 轮询很频繁，静音访问日志
    def log_message(self, fmt, *args):  # noqa: A003
        pass

    # ---------------------------------------------------------------- helpers
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8")) or {}
        except Exception:  # noqa: BLE001
            return {}

    def _static(self, url_path: str) -> None:
        rel = url_path.strip("/") or "downloads.html"
        # 页面里引用的是工作台的 /static/xxx 路径，这里同时兼容带前缀与不带前缀
        if rel.startswith("static/"):
            rel = rel[len("static/"):]
        target = (WEB_DIR / rel).resolve()
        try:
            target.relative_to(WEB_DIR.resolve())
        except ValueError:
            self._json({"error": "invalid path"}, 403)
            return
        if target.is_dir():
            target = target / "downloads.html"
        if not target.is_file():
            # 目录访问 / 未知资源：给下载中心页面兜底，便于直接打开 /
            if rel in ("", "downloads", "downloads/"):
                target = WEB_DIR / "downloads.html"
            else:
                self._json({"error": f"not found: {rel}"}, 404)
                return
        body = target.read_bytes()
        if target.suffix.lower() == ".html":
            body = body.replace(b"__UI_BUILD__", ui_build().encode())
            if target.name == "downloads.html":
                body = body.replace(b'<div class="page downloads-page">', _ENV_PANEL + b'<div class="page downloads-page">', 1)
                body = body.replace(b'<div class="panel">\n    <p data-i18n="downloadsMasterNote">', '<div class="panel"><h2>② 下载模型</h2>\n    <p data-i18n="downloadsMasterNote">'.encode('utf-8'), 1)
                body = body.replace(b'</body>', _ENV_SCRIPT + b'</body>', 1)
        self._send(200, body, MIME.get(target.suffix.lower(), "application/octet-stream"))

    # ---------------------------------------------------------------- routing
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/api/env/status", "/api/env/status/"):
            self._json(env_setup.MANAGER.status())
            return
        if path in ("/api/env/log", "/api/env/log/"):
            self._json(env_setup.MANAGER.log_snapshot())
            return
        if path in ("/api/downloads", "/api/downloads/"):
            try:
                self._json(self.engine.snapshot())
            except Exception as exc:  # noqa: BLE001
                self._json({"error": repr(exc)}, 500)
            return
        if path in ("/api/health", "/health"):
            self._json({"ok": True, "mode": "standalone"})
            return
        if path.startswith("/api/"):
            self._json({"error": f"unknown endpoint: {path}"}, 404)
            return
        self._static(path)

    do_HEAD = do_GET

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        body = self._read_json()
        ids = body.get("ids") or ([body["id"]] if body.get("id") else [])
        try:
            if path in ("/api/env/start", "/api/env/start/"):
                self._json(env_setup.MANAGER.start(body.get("mirror"), bool(body.get("retry"))))
                return
            if path in ("/api/env/cancel", "/api/env/cancel/"):
                self._json(env_setup.MANAGER.cancel())
                return
            if path in ("/api/downloads/start", "/api/downloads/start/"):
                self._json(self.engine.start(ids))
                return
            if path in ("/api/downloads/cancel", "/api/downloads/cancel/"):
                self._json(self.engine.cancel(ids))
                return
            if path in ("/api/downloads/verify", "/api/downloads/verify/"):
                self._json(self.engine.verify(ids))
                return
        except Exception as exc:  # noqa: BLE001
            self._json({"error": repr(exc)}, 500)
            return
        self._json({"error": f"unknown endpoint: {path}"}, 404)


def probe_health(host: str, port: int, timeout: float = 0.8) -> bool:
    """已有同款服务在跑就不再起第二个。

    Windows 下 SO_REUSEADDR 允许多个进程同时绑同一端口，重复触发（页签重开、首启弹窗 + 页签）
    会留下多个实例、请求落到哪个不确定；这里先探活，命中就用现有的。
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(b"GET /api/env/status HTTP/1.0\r\n\r\n")
            data = b""
            while len(data) < 8192:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b'"state"' in data:
                    return True
            return False
    except OSError:
        return False


class _Server(ThreadingHTTPServer):
    # 不要 SO_REUSEADDR：宁可让第二个实例绑失败、由端口扫描换端口，也不要两个进程抢同一端口。
    allow_reuse_address = False
    daemon_threads = True


def main() -> int:
    ap = argparse.ArgumentParser(description="独立下载器界面（仅 stdlib）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--root", default="", help="落地根目录（默认仓库根，可用 MOSS_DOWNLOAD_ROOT 覆盖）")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器（供启动器/测试用）")
    args = ap.parse_args()

    if args.root:
        os.environ["MOSS_DOWNLOAD_ROOT"] = str(Path(args.root).expanduser().resolve())

    try:
        Handler.engine = load_engine()
    except Exception as exc:  # noqa: BLE001
        print(f"[downloader] 无法加载下载引擎：{exc}", file=sys.stderr, flush=True)
        print(f"[downloader] 期望文件：{SERVER_DIR / 'downloads.py'}", file=sys.stderr, flush=True)
        return 2

    if probe_health(args.host, args.port):
        print(json.dumps({"downloader_port": args.port,
                          "downloader_url": f"http://{args.host}:{args.port}/",
                          "already_running": True}), flush=True)
        return 0

    httpd = None
    last_err: Exception | None = None
    for port in range(args.port, args.port + PORT_SCAN):
        try:
            httpd = _Server((args.host, port), Handler)
            break
        except OSError as exc:
            last_err = exc
    if httpd is None:
        print(f"[downloader] 端口 {args.port}..{args.port + PORT_SCAN - 1} 都不可用：{last_err}",
              file=sys.stderr, flush=True)
        return 1

    httpd.daemon_threads = True
    port = int(httpd.server_address[1])
    url = f"http://{args.host}:{port}/"
    print(json.dumps({"downloader_port": port, "downloader_url": url}), flush=True)
    if not args.no_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
