@echo off
rem ----------------------------------------------------------- MOSS voice workbench
rem Self-contained since 2026-10-14: torch runtime venv + transformers 5.x overlay
rem both live under this folder (runtime\venv, runtime\pylibs), so nothing outside
rem D:\MossTTSD is required.
setlocal
chcp 65001 >nul
set "ROOT=%~dp0"
set "PYTHON=%ROOT%runtime\venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo [ERROR] Backend venv interpreter not found: %PYTHON%
  echo         Run Environment preparation first. MOSS_TTS_PYTHON is only used to discover the base interpreter for preparation.
  exit /b 3
)
set "PYTHONPATH=%ROOT%runtime\pylibs"
set "PYTHONIOENCODING=utf-8"
rem 不再设置 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True —— Windows 上该选项不受支持
rem （只有告警、无收益）。抗 OOM 改由引擎负责：生成期把 codec 让到 CPU、每个 take 结束清缓存、
rem 以及显存不足时清缓存并把生成长度降到 60% 重试一次（moss_engine._generate）。
cd /d "%ROOT%server"
"%PYTHON%" -u run.py %*
