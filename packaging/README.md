# Packaging project — MOSS Voice Workbench client (Windows x64 supported; macOS runtime incomplete)
Builds installers for the Electron client from the shipped client distribution in `../client/`.

The installer includes the workbench application and portable CPython 3.12 under
`<install>/resources/workbench/` (`server/`, `tools/`, `docs/`, `runtime/requirements.txt`, `runtime/pylibs/`,
`python/`, and `assets/`). It excludes `models/`, `runtime/venv/`, `runtime/ffmpeg/`, `outputs/`, and
`uploads/`; these are downloaded or created after installation.

On first launch, use **Environment preparation** to create `runtime/venv` with the bundled Python and install
`runtime/requirements.txt` (about 3.4 GB). The package source is chosen automatically (Tsinghua → Alibaba Cloud →
official PyPI, switching on failure; the log shows which one was used), and PyTorch packages come from
`--extra-index-url https://download.pytorch.org/whl/cu130` (about 2.7 GB of the total). Then use **Settings → Model downloads** to download required
models (about 61.8 GB), optional model assets as needed, and FFmpeg (about 83 MB). Downloads go to the fixed
workbench root; `MOSS_DOWNLOAD_ROOT` is a test-only override.

Build commands are unchanged; see **Commands** below.

## What it does

1. `npm run extract` — unpacks `../client/resources/app.asar` into `app/` (the build input; git-ignored, reproducible).
   That asar is shipped verbatim, so it must already carry the local UI patches: run
   `integration/enable_english_ui.js` and `integration/downloads_in_settings_patch.js` (see the root README's
   *Client (asar) patches*) **before** extracting whenever the asar has been rebuilt.
2. `npm run retrofit` — makes the launcher **platform-aware** (`scripts/prepare-app.cjs`):
   - workbench root: `MOSS_WORKBENCH_ROOT` → else `<resourcesPath>/workbench` in packaged builds → else `D:/MossTTSD` on Windows or `~/MossTTSD` on macOS/Linux in development;
   - environment-preparation base interpreter discovery: `MOSS_TTS_PYTHON` → bundled workbench Python → adjacent client Python → `PATH` (only in `tools/env_setup.py`);
   - backend interpreter: exact `<workbench>/runtime/venv/Scripts/python.exe` on Windows (or `bin/python3` on Unix), with no `MOSS_TTS_PYTHON` or PATH override;
   - stopping the backend: `taskkill` on Windows, a process-group signal elsewhere.
   Every substitution is anchored and must hit exactly once, then `node --check` gates the result.
3. `npm run dist:win` / `npm run dist:mac:<arch>` — electron-builder with `electron-builder.yml`. **Only Windows x64 is currently supported.** macOS packages are not usable workbench deliverables until native CPython, CPU/MPS dependencies, and native FFmpeg are prepared and verified; current requirements pin CUDA PyTorch and current FFmpeg is win32-x64.

## Editing the shipped asar

`client/resources/app.asar` is the verbatim build input, so every UI or default-value change has to
land **inside that asar** before `extract`. Two rules keep that safe:

- **Prefer an equal-length byte replacement** when only literals change (theme defaults, fallback
  colours, endpoint strings). Pad to equal length where needed (`'light'` → `'dark' `, or
  `'light';` → `'dark';;`). Then verify three things: the file size is unchanged, the asar header
  still parses, and the entry count matches the original. The header, offsets and `unpacked` flags
  stay untouched, which is the lowest-risk possible edit.
- **Never `asar pack` the whole tree by hand.** The shipped asar carries a large `unpacked` set
  (~100 MB here); a manual repack drops those flags, inlines the files and grows the archive
  (83.3 MB → 86.2 MB), which can break anything that needs a real file path. Let electron-builder
  repack it in `dist:*` instead.

Integration patches must be idempotent. A patch that removes a previously injected runtime with a
lazy regex (`[\s\S]*?` between anchors) and re-injects it will, when re-run on an already-patched
asar, swallow adjacent code — this happened here and deleted the `StemsTools` component definition,
so React failed to mount and the window came up blank. Guard every injection with "is the target
already current?" and fail loudly on an anchor mismatch instead of editing a file you do not
recognise. Verify with a known-symbol grep **and** a real launch; a second run over a copy should be
byte-identical.

Because `dist:*` only packs `packaging/app/`, changing the asar always means re-running
`extract` (and `retrofit`) first — otherwise the installer silently ships the previous copy.

## Commands

```bash
npm install                     # electron 44.7.0 + electron-builder + @electron/asar
npm run extract
npm run retrofit                 # add --check to only verify an already prepared app/
npm run check                   # verify the platform retrofit is present

npm run dist:win:dir            # unpacked Windows app (fast smoke build) → ../release/windows-dir/
npm run dist:win                # NSIS installer        → ../release/windows/
npm run dist:mac:x64            # dmg + zip (macOS only)  → ../release/macos/
npm run dist:mac:arm64
```

**Windows NSIS without GitHub access.** electron-builder's NSIS support downloads `nsis-3.0.4.1` and
`nsis-resources-3.4.1` from GitHub. When that is blocked, fetch both archives from
`https://npmmirror.com/mirrors/electron-builder-binaries/<name>/<name>.7z`, verify the `nsis-resources-3.4.1`
SHA-512 (base64: `Dqd6g+2buwwvoG1Vyf6BHR1b+25QMmPcwZx40atOT57gH27rkjOei1L0JTldxZu4NFoEmW4kJgZ3DlSWVON3+Q==`)
and extract them into one directory, then point `ELECTRON_BUILDER_NSIS_DIR` at it:

```bash
ELECTRON_BUILDER_NSIS_DIR="F:/OMP/projects/发布工具包/electron/windows/shared/nsis-3.0.4.1" npm run dist:win
```

That directory must contain `Bin/makensis.exe`, `Include/`, `Plugins/`, `Stubs/` and `elevate.exe`.

Icons come from `build/` (`icon.ico` for Windows, `icon.icns` for macOS, rendered from
`../integration/assets/moss-icon/moss-icon.svg`). `scripts/after-pack.cjs` ad-hoc signs the macOS bundle
(no Developer ID certificate is available; this is not notarisation).

## Verification status

| Artifact | Built where | Status |
|---|---|---|
| Windows x64 NSIS installer | this machine | **built, installed and launched** — evidence below |
| macOS x64 / arm64 dmg + zip | — | **not supported / incomplete**; native runtime prerequisites are not prepared |

Windows evidence (2026-10-15, electron-builder 26.15.3, Electron 44.7.0):

- installer `MOSS-Voice-Workbench-Setup-1.0.0-win-x64.exe` — 221,255,508 B,
  sha256 `b0e454a85d6040bfd6cbe4b1e01a4f7c7dbd5aa99da04cb0d1961879f86f6b78`
  (`release/windows/SHA256SUMS-win-x64.txt`); published as GitHub release `v1.0.0`
  (tag target `4f94d4b`), both assets verified by size and server-side sha256 digest;
- payload asar: 11,117 entries, build defaults `themeMode = 'dark'` and primary `#6a6ef6`
  (9 occurrences, no `#f77612` leftover), injected `StemsTools` component definition present;
- real launch: the packaged window rendered the workbench UI from the installed
  `resources/app.asar` (CDP page target inside the install tree);
- silent install (`/S /D=…`): exit 0, 7,927 files / 843,327,026 B, installed launcher
  `MOSS语音工作台.exe` 246,406,656 B with the bundled `resources/workbench/python/python.exe`;
  silent uninstall: exit 0, install directory removed, no desktop/Start-menu shortcut residue.
  The environment-preparation service (port 17990) is started by the settings tab rather than at
  launch, so it was not running in the install-only smoke; that page was verified separately in the
  development client.

Not verified: Windows ARM64, Windows versions other than the build machine's, upgrade-over-install, shell
integration. The installer is **not code-signed** (no certificate available) — SmartScreen will warn.

Electron distributions are fetched from `%LOCALAPPDATA%/electron/Cache` when present (44.7.0 win32-x64 is
cached on this machine); set `ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/` when GitHub is
unreachable.

**macOS targets can only be built on macOS.** electron-builder refuses them elsewhere (“Build for macOS is
supported only on macOS”), and a hand-assembled `.app` is not a substitute: the official macOS distribution
stores framework links (`…/Versions/Current`, `Resources`, `Libraries`) as symlinks that Windows extraction
flattens into regular files, and editing the bundle invalidates Electron's code signature — fatal on Apple
silicon. Use `.github/workflows/build-macos.yml` or any Mac.

## Runtime prerequisites on the target machine

The workbench and portable interpreter are included under `<install>/resources/workbench/`, as listed above.
After installation, prepare `<root>/runtime/venv` with the bundled Python; the venv and model weights are
created/downloaded on the target machine. Downloads are rooted in the workbench directory; `MOSS_DOWNLOAD_ROOT`
is only a test override. A reachable local backend port is also required (default 17980).

The client shows the backend log in its window; missing interpreter / missing `server/run.py` are reported
there with the resolved paths. `MOSS_TTS_PYTHON` selects a base interpreter candidate for environment preparation only; the backend always requires the exact `runtime/venv` Python under the selected workbench root. `MOSS_WORKBENCH_ROOT` can select that root.
