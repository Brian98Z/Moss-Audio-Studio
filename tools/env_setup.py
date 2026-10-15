#!/usr/bin/env python3
"""首启 Python 运行环境准备（仅标准库）。"""
from __future__ import annotations

import os
import platform
import re
import signal
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

TORCH_INDEX = "https://download.pytorch.org/whl/cu130"
PYPI_DEFAULT = "https://pypi.tuna.tsinghua.edu.cn/simple"
PYPI_FALLBACKS = ("aliyun", "pypi")
FALLBACK_ERRORS = ("no matching distribution", "could not find a version", "read timed out", "connection")
MIRRORS = {
    "auto": PYPI_DEFAULT,
    "tsinghua": "https://pypi.tuna.tsinghua.edu.cn/simple",
    "pypi": "https://pypi.org/simple",
    "aliyun": "https://mirrors.aliyun.com/pypi/simple",
}
ESTIMATED_BYTES = 3_400_000_000


def workbench_root() -> Path:
    override = os.environ.get("MOSS_WORKBENCH_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    script_root = Path(__file__).resolve().parent.parent
    if script_root.is_dir():
        return script_root
    if sys.platform == "win32":
        return Path(r"D:\MossTTSD")
    return Path.home() / "MossTTSD"

def _is_python312_x64(path: str) -> bool:
    try:
        result = subprocess.run(
            [path, "-c", "import struct,sys;print(f'{sys.version_info.major}.{sys.version_info.minor} {struct.calcsize(\"P\")*8}')"],
            capture_output=True, text=True, timeout=12, check=False,
        )
        return result.returncode == 0 and result.stdout.strip() == "3.12 64"
    except (OSError, subprocess.SubprocessError):
        return False


def resolve_interpreter(root: Path | None = None) -> str | None:
    root = root or workbench_root()
    candidates = []
    if os.environ.get("MOSS_TTS_PYTHON"):
        candidates.append(os.environ["MOSS_TTS_PYTHON"])
    candidates.extend((str(root / "python" / "python.exe"),
                       str(root.parent / "client" / "python" / "python.exe"),
                       str(root / "client" / "python" / "python.exe")))
    import shutil
    found = shutil.which("python") or shutil.which("python3")
    if found:
        candidates.append(found)
    for candidate in candidates:
        if Path(candidate).is_file() and _is_python312_x64(candidate):
            return str(Path(candidate).resolve())
    return None


class EnvironmentSetup:
    def __init__(self, root: Path | None = None):
        self.root = root or workbench_root()
        self.lock = threading.RLock()
        self.state = "idle"
        self.error = None
        self.python = resolve_interpreter(self.root)
        self.mirror = "auto"
        self.active_mirror = None
        self.active_torch_index = None
        self.dependencies_complete = False
        self.downloaded = 0
        self.cuda_available = None
        self.torch_version = None
        self.logs = deque(maxlen=100)
        self.process = None
        self.thread = None
        self.cancel_requested = False

    @property
    def venv_python(self) -> Path:
        return self.root / "runtime" / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")

    def status(self) -> dict:
        with self.lock:
            return {"state": self.state, "root": str(self.root), "interpreter": self.python,
                    "mirror": self.mirror, "actual_mirror": self.active_mirror,
                    "torch_index": self.active_torch_index,
                    "venv_python": str(self.venv_python),
                    "downloaded_bytes": self.downloaded,
                    "percent": 100 if self.dependencies_complete else min(100, round(self.downloaded * 100 / ESTIMATED_BYTES)),
                    "downloaded_gb": round(self.downloaded / 1e9, 2),
                    "estimated_gb": 3.4, "torch_version": self.torch_version,
                    "cuda_available": self.cuda_available, "error": self.error}

    def log_snapshot(self) -> dict:
        with self.lock:
            return {"lines": list(self.logs), "downloaded_bytes": self.downloaded,
                    "percent": 100 if self.dependencies_complete else min(100, round(self.downloaded * 100 / ESTIMATED_BYTES)),
                    "downloaded_gb": round(self.downloaded / 1e9, 2), "estimated_gb": 3.4}

    def start(self, mirror: str | None = None, force: bool = False) -> dict:
        with self.lock:
            if self.state not in ("idle", "error", "canceled"):
                return {"started": False, "state": self.state, "error": "环境准备正在运行"}
            if not self.python:
                self.error = "未找到符合要求的 Python 3.12 x64 解释器"
                self.state = "error"
                self.logs.append(self.error)
                return {"started": False, "state": self.state, "error": self.error}
            selected = mirror or self.mirror
            if selected not in MIRRORS:
                return {"started": False, "error": "未知镜像"}
            self.mirror = selected
            self.error = None
            self.cancel_requested = False
            self.logs.clear()
            self.state = "venv"
            self.thread = threading.Thread(target=self._run, args=(False,), daemon=True)
            self.thread.start()
            return {"started": True, "state": self.state, "mirror": selected}

    def _append_line(self, line: str) -> None:
        with self.lock:
            self.logs.append(line)
            match = re.search(r"(?:Downloading|Using cached)\s+(.+?)\s+\(([^)]+)\)", line, re.I)
            if match:
                size = re.search(r"([\d.]+)\s*(B|kB|KB|MB|GB|MiB|GiB)", match.group(2), re.I)
                if size:
                    value = float(size.group(1))
                    unit = size.group(2).lower()
                    factor = {"b": 1, "kb": 1000, "mb": 1_000_000, "gb": 1_000_000_000,
                              "mib": 1_048_576, "gib": 1_073_741_824}[unit]
                    self.downloaded += int(value * factor)

    def _run_command(self, command: list[str], phase: str) -> tuple[int, str]:
        with self.lock:
            if self.cancel_requested:
                raise _Canceled()
            self.state = phase
        self._append_line("$ " + subprocess.list2cmdline(command))
        kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                  "text": True, "encoding": "utf-8", "errors": "replace", "bufsize": 1}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(command, **kwargs)
        with self.lock:
            if self.cancel_requested:
                proc.kill()
            self.process = proc
        tail = ""
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            tail = line
            self._append_line(line)
        code = proc.wait()
        with self.lock:
            self.process = None
        return code, tail


    def _install_requirements(self, venv: Path, requirements: Path) -> None:
        mirror_order = [self.mirror] if self.mirror != "auto" else ["tsinghua", *PYPI_FALLBACKS]
        torch_order = [TORCH_INDEX]
        for mirror in mirror_order:
            for torch_index in torch_order:
                command = [str(venv), "-m", "pip", "install", "--only-binary=:all:",
                           "-r", str(requirements), "--extra-index-url", torch_index,
                           "-i", MIRRORS[mirror]]
                with self.lock:
                    self.active_mirror = mirror
                    self.active_torch_index = torch_index
                    self.logs.append(f"使用 PyPI 源：{mirror} ({MIRRORS[mirror]})")
                    self.logs.append(f"使用 torch extra-index：{torch_index}")
                code, tail = self._run_command(command, "pip-deps")
                if self.cancel_requested:
                    raise _Canceled()
                if code == 0:
                    return
                failure = "\n".join(self.logs).lower()
                can_retry = self.mirror == "auto" and any(token in failure for token in FALLBACK_ERRORS)
                if not can_retry or mirror == mirror_order[-1]:
                    raise RuntimeError(f"pip-deps失败（退出码 {code}）：{tail}")
                self.logs.append(f"源 {mirror} 安装失败，切换下一个 PyPI 源")
        raise RuntimeError("所有 PyPI 镜像均安装失败")
    def _run(self, force: bool) -> None:
        try:
            root = self.root
            venv = self.venv_python
            requirements = root / "runtime" / "requirements.txt"
            if not requirements.is_file():
                raise RuntimeError(f"依赖清单不存在：{requirements}")
            if not venv.is_file():
                code, tail = self._run_command([self.python, "-m", "venv", str(venv.parent.parent)], "venv")
                self._check(code, tail, "创建虚拟环境")
            commands = [
                ([str(venv), "-m", "pip", "install", "-U", "pip"], "pip-upgrade"),
            ]
            for command, phase in commands:
                code, tail = self._run_command(command, phase)
                self._check(code, tail, phase)
            with self.lock:
                self.state = "pip-deps"
            self._install_requirements(venv, requirements)
            with self.lock:
                self.dependencies_complete = True
                self.logs.append("依赖安装完成，正在校验 torch/CUDA")
            command = [str(venv), "-c", "import torch,torchaudio;print(torch.__version__, torch.cuda.is_available())"]
            code, tail = self._run_command(command, "verify")
            self._check(code, tail, "verify")
            with self.lock:
                self.torch_version, cuda = tail.split()[:2]
                self.cuda_available = cuda.lower() == "true"
                self.state = "ready"
                self._append_line("环境准备完成")
        except _Canceled:
            with self.lock:
                self.state = "canceled"
                self._append_line("已取消环境准备")
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.state = "error"
                self.error = str(exc)
                self._append_line("错误：" + self.error)

    def _check(self, code: int, tail: str, phase: str) -> None:
        if self.cancel_requested:
            raise _Canceled()
        if code:
            raise RuntimeError(f"{phase}失败（退出码 {code}）：{tail}")

    def cancel(self) -> dict:
        with self.lock:
            if self.state in ("idle", "ready", "error", "canceled"):
                return {"canceled": False, "state": self.state}
            self.cancel_requested = True
            proc = self.process
            self.logs.append("正在终止安装进程树…")
        if proc and proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/pid", str(proc.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            else:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        return {"canceled": True, "state": "canceling"}


class _Canceled(Exception):
    pass


MANAGER = EnvironmentSetup()
