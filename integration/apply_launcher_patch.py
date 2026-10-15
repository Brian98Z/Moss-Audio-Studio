from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
DEFAULT_ASAR = Path(r"D:/MossTTSD/client/resources/app.asar")
DEFAULT_BUILD = Path(tempfile.gettempdir()) / "moss-launcher-patch"
WORKBENCH_ROOT = Path(r"D:/MossTTSD")
ASAR_CLI = ["--yes", "@electron/asar@4"]
ICON_ASSETS = HERE / "assets" / "moss-icon"
ASAR_ICON = Path("resources/icon.png")
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
_CONFIG_RE = re.compile(r'const configPath = path\$1\.join\(rootPath, "([^"]+)"\)')
_HREF_RE = re.compile(r'href:\s*"(https?://[^\"]+)"')
CONFIG_FILE_NEW = "moss_config.json"

MAIN_HELPERS = '''/* [packaging] helpers:start */
const configuredWorkbenchRoot = process.env.MOSS_WORKBENCH_ROOT && process.env.MOSS_WORKBENCH_ROOT.trim();
const packagedWorkbenchRoot = path$1.join(process.resourcesPath, "workbench");
const WORKBENCH_ROOT = configuredWorkbenchRoot
  ? configuredWorkbenchRoot
  : fs$1.existsSync(path$1.join(packagedWorkbenchRoot, "server", "run.py"))
    ? packagedWorkbenchRoot
    : process.platform === "win32" ? "D:/MossTTSD" : path$1.join(electron.app.getPath("home"), "MossTTSD");
const WORKBENCH_BACKEND = {
  label: "MOSS 语音工作台（单人配音 / 音色设计 / 多人对话 / 音效）",
  script: path$1.join(WORKBENCH_ROOT, "server", "run.py"),
  cwd: path$1.join(WORKBENCH_ROOT, "server")
};
const DOWNLOADER_SCRIPT = path$1.join(WORKBENCH_ROOT, "tools", "downloader_ui.py");
let downloaderProcess = null;
let downloaderWindow = null;
let downloaderUrl = "";
const stopDownloader = () => {
  const proc = downloaderProcess; downloaderProcess = null; downloaderUrl = "";
  if (downloaderWindow && !downloaderWindow.isDestroyed()) downloaderWindow.close();
  downloaderWindow = null;
  if (!proc) return;
  if (process.platform === "win32") child_process.spawn("taskkill", ["/pid", proc.pid.toString(), "/T", "/F"]);
  else { try { process.kill(-proc.pid, "SIGTERM"); } catch (err) { console.log("stop downloader failed:", err); } }
};
const openDownloaderWindow = (mainWindow) => {
  if (!downloaderUrl) { electron.dialog.showMessageBox(mainWindow, { type: "info", message: "下载中心尚未就绪，请稍后重试。" }); return; }
  if (downloaderWindow && !downloaderWindow.isDestroyed()) { downloaderWindow.focus(); return; }
  downloaderWindow = new electron.BrowserWindow({ width: 1120, height: 800, parent: mainWindow });
  downloaderWindow.on("closed", () => { downloaderWindow = null; });
  downloaderWindow.loadURL(downloaderUrl);
};
const startDownloader = (mainWindow, background) => {
  if (downloaderProcess) { if (!background && downloaderUrl) openDownloaderWindow(mainWindow); return; }
  const configured = process.env.MOSS_TTS_PYTHON;
  const venv = process.platform === "win32" ? path$1.join(WORKBENCH_ROOT, "runtime", "venv", "Scripts", "python.exe") : path$1.join(WORKBENCH_ROOT, "runtime", "venv", "bin", "python3");
  const portable = process.platform === "win32" ? path$1.join(WORKBENCH_ROOT, "python", "python.exe") : path$1.join(WORKBENCH_ROOT, "python", "python3");
  const development = process.platform === "win32" ? path$1.join(WORKBENCH_ROOT, "client", "python", "python.exe") : path$1.join(WORKBENCH_ROOT, "client", "python", "python3");
  const resolvePython = () => [portable, development].find((p) => fs$1.existsSync(p));
  const python = configured && fs$1.existsSync(configured) ? configured : fs$1.existsSync(venv) ? venv : resolvePython();
  if (!fs$1.existsSync(venv)) electron.dialog.showMessageBox({ type: "info", message: "首次使用需准备运行环境（依赖与模型按需下载）", buttons: ["打开环境准备", "稍后"] }).then(({ response }) => {
    if (response !== 0) return;
    const prepPython = resolvePython();
    if (!prepPython) { electron.dialog.showMessageBox({ type: "error", message: "未找到工作台便携 Python。" }); return; }
    const child = child_process.spawn(prepPython, [path$1.join(WORKBENCH_ROOT, "tools", "downloader_ui.py")], { cwd: WORKBENCH_ROOT, detached: true, stdio: "ignore", windowsHide: true }); child.unref();
  });
  if (!python) { mainWindow.webContents.send("gradio-log", "【严重错误】未检测到 Python 解释器，请打开环境准备界面完成初始化。"); return; }
  downloaderProcess = child_process.spawn(python, ["-u", DOWNLOADER_SCRIPT], { cwd: WORKBENCH_ROOT, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  const consume = (chunk) => {
    const text = chunk.toString();
    let m = text.match(/downloader_url\\s*[:=]\\s*[\"'](https?:\\/\\/[^\"']+)/i);
    if (!m) m = text.match(/downloader_port\\s*[:=]\\s*[\"']?(\\d+)/i);
    if (m) { downloaderUrl = m[1].startsWith("http") ? m[1] : `http://127.0.0.1:${m[1]}/`; if (!background) openDownloaderWindow(mainWindow); }
  };
  downloaderProcess.stdout.on("data", consume); downloaderProcess.stderr.on("data", consume);
  downloaderProcess.on("close", () => { downloaderProcess = null; downloaderUrl = ""; if (downloaderWindow && !downloaderWindow.isDestroyed()) downloaderWindow.close(); downloaderWindow = null; });
  setTimeout(() => { if (!downloaderUrl) electron.dialog.showMessageBox(mainWindow, { type: "warning", message: "下载中心尚未就绪，请检查环境准备日志后重试。" }); }, 12000);
};
electron.app.on("will-quit", () => { stopDownloader(); });
electron.ipcMain.on("start-downloader", (event, background) => {
  const win = electron.BrowserWindow.getAllWindows()[0];
  if (win) startDownloader(win, !!background);
});
electron.ipcMain.on("stop-downloader", stopDownloader);
/* [packaging] helpers:end */'''

# These exact old anchors describe the known upstream bundle. Replacements fail closed.
SPAWN_OLD = '    pythonProcess = child_process.spawn(pyEnv, ["-u", demo_path], {\n      cwd: target.cwd,\n      windowsHide: true,'
SPAWN_NEW = SPAWN_OLD + '\n      detached: process.platform !== "win32",'
SAVE_OLD = '    fs__namespace.writeFileSync(configPath, JSON.stringify(newConfig, null, 2));'
SAVE_NEW = '    const mergedConfig = { ...loadConfig(), ...newConfig };\n    fs__namespace.writeFileSync(configPath, JSON.stringify(mergedConfig, null, 2));'
PY_OLD = 'const cudaPyEnv = "D:/MossTTSD/runtime/venv/Scripts/python.exe";'
PY_NEW = 'const cudaPyEnv = path$1.join(WORKBENCH_ROOT, "runtime", "venv", "Scripts", "python.exe");'
PY_FALLBACK_RE = re.compile(r'python/[^"/\\]+/python/python\\.exe')
PY_FALLBACK_NEW = 'python/python.exe'
MAIN_CONFIG_NEW = 'path$1.join(rootPath, "moss_config.json")'
PRELOAD_START = 'startDownloader: (background) => electron.ipcRenderer.send("start-downloader", background),'
PRELOAD_STOP = 'stopDownloader: () => electron.ipcRenderer.send("stop-downloader"),'

@dataclass(frozen=True)
class Legacy:
    """原始启动器里探测出来的旧标识。"""
    title: str
    brand: str
    config: str
    hrefs: tuple[str, ...]

    def leftovers(self) -> tuple[str, ...]:
        words = [self.title, self.brand, self.config]
        for href in self.hrefs:
            u = urlparse(href)
            words += [u.netloc, u.path.strip("/")]
        return tuple(dict.fromkeys(w for w in words if len(w) > 3))


def probe_legacy(root: Path) -> Legacy:
    html = (root / "out/renderer/index.html").read_text(encoding="utf-8")
    m = _TITLE_RE.search(html)
    if not m: raise SystemExit(f"原始 index.html 里找不到 <title>：{root}")
    title = m.group(1)
    brand = re.split(r"\s*(?:——|—|--|[-|·])\s*", title.strip())[0].strip()
    if not brand: raise SystemExit(f"无法从原始标题里取到品牌短名：{title!r}")
    main_js = (root / "out/main/index.js").read_text(encoding="utf-8")
    cfg = _CONFIG_RE.search(main_js)
    renderer = "\n".join(p.read_text(encoding="utf-8") for p in sorted((root / "out/renderer/assets").glob("*.js")))
    return Legacy(title, brand, cfg.group(1) if cfg else CONFIG_FILE_NEW, tuple(sorted(set(_HREF_RE.findall(renderer)))))


def config_anchor(legacy: Legacy) -> str:
    return f'const configPath = path$1.join(rootPath, "{legacy.config}");\n'


def config_join(legacy: Legacy) -> str:
    return f'path$1.join(rootPath, "{legacy.config}")'


def patch_main(source: str, legacy: Legacy) -> str:
    # Idempotent stable region, and all output checks precede writes in main().
    start, end = "/* [packaging] helpers:start */", "/* [packaging] helpers:end */"
    # Existing marked helper block is replaced atomically; pristine bundle uses the backend object anchor.
    if start in source and end in source:
        source = source[:source.index(start)] + MAIN_HELPERS + source[source.index(end) + len(end):]
    elif start in source or end in source:
        raise SystemExit("partial [packaging] helper markers")
    else:
        backend = '''const WORKBENCH_BACKEND = {
  label: "MOSS 语音工作台（单人配音 / 音色设计 / 多人对话 / 音效）",
  script: "D:/MossTTSD/server/run.py",
  cwd: "D:/MossTTSD/server"
};'''
        if backend not in source:
            raise SystemExit("anchor not found: original WORKBENCH_BACKEND")
        source = source.replace(backend, MAIN_HELPERS, 1)
    for old, new, label in ((SPAWN_OLD, SPAWN_NEW, "spawn block"), (SAVE_OLD, SAVE_NEW, "save-config write"), (PY_OLD, PY_NEW, "python path")):
        if old in source and (label != "spawn block" or new not in source): source = source.replace(old, new, 1)
        elif new not in source: raise SystemExit(f"anchor not found: {label}")
    source = source.replace(config_join(legacy), MAIN_CONFIG_NEW, 1)
    source = PY_FALLBACK_RE.sub(PY_FALLBACK_NEW, source)
    # Main renderer remains the local app file; downloader is only a separate window.
    source = source.replace('utils.electronApp.setAppUserModelId("com.electron")', 'utils.electronApp.setAppUserModelId("com.mossworkbench.client")')
    source = source.replace('const pth = path.join(rootPath, folderPath);', 'const pth = path$1.isAbsolute(folderPath) ? folderPath : path$1.join(WORKBENCH_ROOT, folderPath);')
    return source


def patch_preload(source: str) -> str:
    if PRELOAD_START not in source:
        anchor = '  onStopGradio: (config) => {\n    electron.ipcRenderer.send("stop-gradio", config);\n  },'
        if anchor not in source: raise SystemExit("preload stop-gradio anchor mismatch")
        source = source.replace(anchor, anchor + "\n  " + PRELOAD_START + "\n  " + PRELOAD_STOP, 1)
    if PRELOAD_START not in source or PRELOAD_STOP not in source: raise SystemExit("preload downloader marker validation failed")
    return source


def platform_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def _about_slot(source: str, legacy: Legacy) -> str:
    return source


def branding_rules(legacy: Legacy) -> list[tuple[str, str]]:
    rules = [(legacy.title, "MOSS 语音工作台 · 本地部署"), (legacy.brand, "MOSS 语音工作台")]
    for href in legacy.hrefs: rules.append((href, "https://github.com/OpenMOSS/MOSS-TTS"))
    return rules


def branded_intro_re(legacy: Legacy) -> re.Pattern[str]:
    return re.compile(r'children: "' + re.escape(legacy.brand) + r' [^"]*"')


def _links(items: list[str]) -> str:
    return ",\n              ".join(items)


def patch_renderer(root: Path, legacy: Legacy, dry_run: bool = False) -> dict[str, int]:
    # Conservative, data-driven branding cleanup; settings/download UI is intentionally untouched.
    rules = branding_rules(legacy); counts: dict[str, int] = {}
    paths = [root / "out/renderer/index.html", *sorted((root / "out/renderer/assets").glob("*.js"))]
    for file in paths:
        source = file.read_text(encoding="utf-8"); changed = source
        if file.name == "index.html":
            changed = _TITLE_RE.sub("<title>MOSS 语音工作台 · 本地部署</title>", changed, count=1)
        for old, new in rules:
            n = changed.count(old)
            if n: changed = changed.replace(old, new); counts[old] = counts.get(old, 0) + n
        if not dry_run and changed != source: file.write_text(changed, encoding="utf-8")
    return counts


def scrub_asar_metadata(root: Path, legacy: Legacy, dry_run: bool = False) -> dict[str, object]:
    p = root / "package.json"; data = json.loads(p.read_text(encoding="utf-8")); old = legacy.brand
    removed = [k for k in ("author", "homepage") if k in data]
    data["name"] = "moss-voice-workbench"
    for key in removed: data.pop(key, None)
    if not dry_run: p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"name": data["name"], "removed": removed}


def set_asar_icon(root: Path, dry_run: bool = False) -> str:
    icon = ICON_ASSETS / "icon-256.png"
    target = root / ASAR_ICON
    if not icon.exists(): raise SystemExit(f"图标资产缺失: {icon}")
    if not target.parent.exists(): raise SystemExit(f"asar 里没有 {target.parent}，无法换图标")
    if not dry_run: shutil.copyfile(icon, target)
    return f"{target} ({icon.stat().st_size} B)"


def backup_path(asar: Path) -> Path:
    return asar.with_name(asar.name + ".orig-" + time.strftime("%Y%m%d"))


def run_cli(*args: str) -> None:
    cmd = ["npx", *ASAR_CLI, *args]
    result = subprocess.run(cmd, capture_output=True, text=True, shell=(os.name == "nt"))
    if result.stdout: print(result.stdout, end="")
    if result.stderr: print(result.stderr, end="", file=sys.stderr)
    if result.returncode: raise SystemExit(f"asar {' '.join(args)} failed:\n{result.stderr[-400:]}")


def restore(asar: Path) -> int:
    backups = sorted(asar.parent.glob(asar.name + ".orig-*"))
    if not backups: print("no backup found"); return 1
    source = backups[-1]; shutil.copy2(source, asar); print(f"restored {asar} from {source}"); return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch the MOSS Electron launcher safely")
    parser.add_argument("--asar", type=Path, default=DEFAULT_ASAR); parser.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD)
    parser.add_argument("--dry-run", action="store_true"); parser.add_argument("--check", action="store_true")
    parser.add_argument("--restore", action="store_true"); parser.add_argument("--keep-build", action="store_true")
    args = parser.parse_args(); asar = args.asar.resolve()
    if args.restore: return restore(asar)
    if not asar.exists(): raise SystemExit(f"asar not found: {asar}")
    build = args.build_dir.resolve()
    if build.exists(): shutil.rmtree(build)
    build.mkdir(parents=True)
    run_cli("extract", str(asar), str(build))
    root = build / "app" if (build / "app/out").exists() else build
    main_file = root / "out/main/index.js"; preload_file = root / "out/preload/index.js"
    if not main_file.exists(): raise SystemExit(f"main/index.js not found under {build}")
    if not preload_file.exists(): raise SystemExit(f"preload/index.js not found under {build}")
    legacy = probe_legacy(root); original_main = main_file.read_text(encoding="utf-8")
    new_main = patch_main(original_main, legacy); original_preload = preload_file.read_text(encoding="utf-8"); new_preload = patch_preload(original_preload)
    if args.check:
        with tempfile.TemporaryDirectory(prefix="moss-main-check-") as td:
            candidate = Path(td) / "index.js"; candidate.write_text(new_main, encoding="utf-8")
            result = subprocess.run(["node", "--check", str(candidate)], capture_output=True, text=True)
            if result.returncode: print(result.stderr); return 1
        print("ok main/preload transformations and node --check"); return 0
    # Stage complete output in a temporary extracted copy. Never mutate source asar before syntax gates.
    with tempfile.TemporaryDirectory(prefix="moss-patch-stage-") as td:
        stage = Path(td) / "app"; shutil.copytree(root, stage)
        staged_main = stage / "out/main/index.js"; staged_preload = stage / "out/preload/index.js"
        staged_main.write_text(new_main, encoding="utf-8"); staged_preload.write_text(new_preload, encoding="utf-8")
        for file in (staged_main, staged_preload):
            result = subprocess.run(["node", "--check", str(file)], capture_output=True, text=True)
            if result.returncode: raise SystemExit(f"node --check failed; refusing write:\n{result.stderr}")
        patch_renderer(stage, legacy, args.dry_run); scrub_asar_metadata(stage, legacy, args.dry_run); set_asar_icon(stage, args.dry_run)
        if args.dry_run:
            out = Path(tempfile.gettempdir()) / "moss-launcher-patched"; out.mkdir(exist_ok=True)
            (out / "patched_main.js").write_text(new_main, encoding="utf-8"); print(f"dry run: patched copy in {out}"); return 0
        staged_main.write_text(new_main, encoding="utf-8"); staged_preload.write_text(new_preload, encoding="utf-8")
        # pack and replace only after the syntax gates succeeded
        tmpout = asar.with_name(asar.name + ".new")
        run_cli("pack", str(stage), str(tmpout))
        if not backup_path(asar).exists(): shutil.copy2(asar, backup_path(asar))
        os.replace(tmpout, asar)
    print(f"patched {asar} ({asar.stat().st_size} bytes)")
    if not args.keep_build: shutil.rmtree(build, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
