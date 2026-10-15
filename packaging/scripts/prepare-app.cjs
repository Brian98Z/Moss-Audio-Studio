#!/usr/bin/env node
/**
 * 把解包出来的上游客户端改造成**平台化**启动器（Windows 与 macOS 共用同一份产物）。
 *
 * 上游产物（app/out/main/index.js，经 integration/apply_launcher_patch.py 打过补丁）把工作台根目录、
 * 解释器路径和「停止后端」都写死在 Windows 形态上：
 *   - WORKBENCH_BACKEND.script = "D:/MossTTSD/server/run.py"
 *   - cudaPyEnv = "D:/MossTTSD/runtime/venv/Scripts/python.exe"
 *   - 退出时 child_process.spawn("taskkill", ["/pid", ...])   ← macOS 没有 taskkill
 * 本脚本只做这五处等价替换，不改变任何其它行为；每处都要求**恰好命中一次**，命中数不对直接报错退出
 * （上游产物结构一变就显式失败，而不是静默打出坏包）。
 *
 * 换行处理：解包产物是 CRLF。先归一化成 LF 做替换，写回时再还原成原来的换行，避免整文件抖动。
 *
 * 用法：
 *   node scripts/prepare-app.cjs          # 就地改造 app/
 *   node scripts/prepare-app.cjs --check  # 只校验是否已改造（不改文件）
 */
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const ROOT = path.resolve(__dirname, "..");            // packaging/
const APP_DIR = path.join(ROOT, "app");
const MAIN = path.join(APP_DIR, "out", "main", "index.js");
const MARKER = "[packaging]";                          // 改造标记（幂等 + 可检查）

const T1_OLD = [
  'const WORKBENCH_BACKEND = {',
  '  label: "MOSS 语音工作台（单人配音 / 音色设计 / 多人对话 / 音效）",',
  '  script: "D:/MossTTSD/server/run.py",',
  '  cwd: "D:/MossTTSD/server"',
  '};',
].join("\n");

const T1_NEW = [
  `// ${MARKER} 工作台根目录：环境变量优先，其次打包资源目录，最后开发树默认路径。`,
  'const configuredWorkbenchRoot = process.env.MOSS_WORKBENCH_ROOT && process.env.MOSS_WORKBENCH_ROOT.trim();',
  'const packagedWorkbenchRoot = path$1.join(process.resourcesPath, "workbench");',
  'const WORKBENCH_ROOT = configuredWorkbenchRoot',
  '  ? configuredWorkbenchRoot',
  '  : fs$1.existsSync(path$1.join(packagedWorkbenchRoot, "server", "run.py"))',
  '    ? packagedWorkbenchRoot',
  '    : process.platform === "win32" ? "D:/MossTTSD" : path$1.join(electron.app.getPath("home"), "MossTTSD");',
  'const WORKBENCH_BACKEND = {',
  '  label: "MOSS 语音工作台（单人配音 / 音色设计 / 多人对话 / 音效）",',
  '  script: path$1.join(WORKBENCH_ROOT, "server", "run.py"),',
  '  cwd: path$1.join(WORKBENCH_ROOT, "server")',
  '};',
].join("\n");
const T2_OLD = [
  '    const configuredPyEnv = process.env.MOSS_TTS_PYTHON;',
  '    const cudaPyEnv = "D:/MossTTSD/runtime/venv/Scripts/python.exe";',
  '    pyEnv = configuredPyEnv && fs$1.existsSync(configuredPyEnv)',
  '      ? configuredPyEnv',
  '      : fs$1.existsSync(cudaPyEnv)',
  '        ? cudaPyEnv',
  '        : bundledPyEnv;',
  '    if (!fs$1.existsSync(pyEnv)) {',
  '      win.webContents.send(',
  '        `gradio-log`,',
  '        `【严重错误】未检测到 Python 环境，请确认 python 文件夹是否已拷贝到 exe 同级目录!`',
  '      );',
  '      return;',
  '    }',
].join("\n");

const T2_NEW = [
  '    const configuredPyEnv = process.env.MOSS_TTS_PYTHON;',
  `    // ${MARKER} 优先使用指定解释器与工作台 venv，首次准备阶段回退到随包便携 Python。`,
  '    const venvPyEnv = process.platform === "win32"',
  '      ? path$1.join(WORKBENCH_ROOT, "runtime", "venv", "Scripts", "python.exe")',
  '      : path$1.join(WORKBENCH_ROOT, "runtime", "venv", "bin", "python3");',
  '    const portablePyEnv = process.platform === "win32"',
  '      ? path$1.join(WORKBENCH_ROOT, "python", "python.exe")',
  '      : path$1.join(WORKBENCH_ROOT, "python", "python3");',
  '    const developmentPyEnv = process.platform === "win32"',
  '      ? path$1.join(WORKBENCH_ROOT, "client", "python", "python.exe")',
  '      : path$1.join(WORKBENCH_ROOT, "client", "python", "python3");',
  '    const resolveBundledPython = () => {',
  '      if (fs$1.existsSync(portablePyEnv)) return portablePyEnv;',
  '      if (fs$1.existsSync(developmentPyEnv)) return developmentPyEnv;',
  '      throw new Error("未找到工作台便携解释器: " + portablePyEnv + " 或 " + developmentPyEnv);',
  '    };',
  '    pyEnv = configuredPyEnv && fs$1.existsSync(configuredPyEnv)',
  '      ? configuredPyEnv',
  '      : fs$1.existsSync(venvPyEnv) ? venvPyEnv : resolveBundledPython();',
  '    if (!fs$1.existsSync(venvPyEnv)) {',
  '      electron.dialog.showMessageBox({ type: "info", message: "首次使用需准备运行环境（约 3.4 GB 依赖 + 模型按需下载）", buttons: ["打开环境准备", "稍后"] })',
  '        .then(({ response }) => {',
  '          if (response !== 0) return;',
  '          let prepPython;',
  '          try { prepPython = resolveBundledPython(); } catch (err) { console.error("环境准备启动失败:", err); return; }',
  '          const child = child_process.spawn(prepPython, [path$1.join(WORKBENCH_ROOT, "tools", "downloader_ui.py")], { cwd: WORKBENCH_ROOT, detached: true, stdio: "ignore", windowsHide: true });',
  '          child.unref();',
  '        });',
  '    }',
  '    if (!fs$1.existsSync(pyEnv)) {',
  '      win.webContents.send("gradio-log", `【严重错误】未检测到 Python 解释器，请打开“环境准备”界面完成初始化。`);',
  '      return;',
  '    }',
].join("\n");

// 后端入口缺失时的提示：上游写死「请确认 D:\MossTTSD 是否完整」，改成跟随实际根目录。
// T3_OLD 需要匹配文件里的两个反斜杠 → 用 String.raw；T3_NEW 里的 ${...} 是产物代码，必须转义成字面量。
const T3_OLD = String.raw`请确认 D:\\MossTTSD 是否完整!`;
const T3_NEW = `请确认工作台根目录 \${WORKBENCH_ROOT} 是否完整!`;

const T4_OLD = [
  '    pythonProcess = child_process.spawn(pyEnv, ["-u", demo_path], {',
  '      cwd: target.cwd,',
  '      windowsHide: true,',
].join("\n");

const T4_NEW = [
  '    pythonProcess = child_process.spawn(pyEnv, ["-u", demo_path], {',
  '      cwd: target.cwd,',
  '      windowsHide: true,',
  `      // ${MARKER} macOS/Linux 让后端自成进程组，退出时才能连同子进程一起收掉；Windows 保持原行为。`,
  '      detached: process.platform !== "win32",',
].join("\n");

const T5_OLD = '      child_process.spawn("taskkill", ["/pid", pythonProcess.pid.toString(), "/T", "/F"]);';

const T5_NEW = [
  `      // ${MARKER} Windows 用 taskkill 收进程树；macOS/Linux 用进程组信号。`,
  '      if (process.platform === "win32") {',
  T5_OLD,
  '      } else {',
  '        try {',
  '          process.kill(-pythonProcess.pid, "SIGTERM");',
  '        } catch (err) {',
  '          console.log("kill backend failed:", err);',
  '        }',
  '      }',
].join("\n");

const TRANSFORMS = [
  ["工作台根目录/入口按平台解析", T1_OLD, T1_NEW],
  ["解释器路径按平台解析 + 缺解释器提示", T2_OLD, T2_NEW],
  ["后端缺失提示跟随实际根目录", T3_OLD, T3_NEW],
  ["spawn 增加 detached（非 Windows）", T4_OLD, T4_NEW],
  ["停止后端：taskkill → 进程组信号", T5_OLD, T5_NEW],
];

function countOf(haystack, needle) {
  let count = 0, index = haystack.indexOf(needle);
  while (index !== -1) { count += 1; index = haystack.indexOf(needle, index + needle.length); }
  return count;
}

function main() {
  const checkOnly = process.argv.includes("--check");
  if (!fs.existsSync(MAIN)) {
    console.error(`fail 未找到启动器入口 ${MAIN}（先运行 npm run extract）`);
    return 1;
  }
  const raw = fs.readFileSync(MAIN, "utf8");
  const crlf = countOf(raw, "\r\n");
  const lf = countOf(raw, "\n");
  if (crlf && crlf !== lf) console.error(`warn 文件换行不统一（CRLF ${crlf} / LF ${lf}），按 CRLF 归一化处理`);
  const eol = crlf ? "\r\n" : "\n";
  let source = eol === "\r\n" ? raw.split("\r\n").join("\n") : raw;
  const already = source.includes(MARKER);

  if (checkOnly) {
    if (!already) { console.error("fail 未完成平台化改造（缺少改造标记）"); return 1; }
    const missing = TRANSFORMS.filter(([, , newText]) => !source.includes(newText)).map(([label]) => label);
    if (missing.length) { console.error("fail 改造不完整：", missing.join("；")); return 1; }
    console.log(`ok 启动器已平台化改造（换行 ${eol === "\r\n" ? "CRLF" : "LF"}）`);
    return 0;
  }

  if (already) {
    const legacyRoot = 'const WORKBENCH_ROOT = process.env.MOSS_WORKBENCH_ROOT && process.env.MOSS_WORKBENCH_ROOT.trim()\n  ? process.env.MOSS_WORKBENCH_ROOT.trim()\n  : process.platform === "win32"\n    ? "D:/MossTTSD"\n    : path$1.join(electron.app.getPath("home"), "MossTTSD");';
    const upgradedRoot = T1_NEW;
    if (source.includes(legacyRoot)) source = source.replace(legacyRoot, upgradedRoot);
    const oldPython = 'const configuredPyEnv = process.env.MOSS_TTS_PYTHON;\n    // [packaging] venv 解释器按平台取（Windows: Scripts/python.exe；macOS/Linux: bin/python3），\n    // [packaging] 都没有时 Windows 不再兜底，macOS/Linux 允许走 PATH 上的 python3。\n    const venvPyEnv = process.platform === "win32"\n      ? path$1.join(WORKBENCH_ROOT, "runtime", "venv", "Scripts", "python.exe")\n      : path$1.join(WORKBENCH_ROOT, "runtime", "venv", "bin", "python3");\n    const pathPyEnv = process.platform === "win32" ? "" : "python3";\n    pyEnv = configuredPyEnv && fs$1.existsSync(configuredPyEnv)\n      ? configuredPyEnv\n      : fs$1.existsSync(venvPyEnv)\n        ? venvPyEnv\n        : fs$1.existsSync(bundledPyEnv)\n          ? bundledPyEnv\n          : pathPyEnv;\n    const pyEnvIsPath = pyEnv.includes("/") || pyEnv.includes("\\\\");\n    if (!pyEnv || (pyEnvIsPath && !fs$1.existsSync(pyEnv))) {\n      win.webContents.send(\n        `gradio-log`,\n        `【严重错误】未检测到可用的 Python 解释器。请安装工作台运行时（预期：${venvPyEnv}），或用环境变量 MOSS_TTS_PYTHON 指定解释器。`\n      );\n      return;\n    }';
    if (source.includes(oldPython)) source = source.replace(oldPython, T2_NEW);
    fs.writeFileSync(MAIN, eol === "\r\n" ? source.split("\n").join("\r\n") : source);
    console.log("ok   升级既有平台补丁");
  } else {
    for (const [label, oldText, newText] of TRANSFORMS) {
      const hits = countOf(source, oldText);
      if (hits !== 1) {
        console.error(`fail 「${label}」锚点命中 ${hits} 处（要求恰好 1 处）——上游产物结构可能已变，请人工核对后再改脚本`);
        return 1;
      }
      source = source.split(oldText).join(newText);
      console.log(`ok   ${label}`);
    }
    fs.writeFileSync(MAIN, eol === "\r\n" ? source.split("\n").join("\r\n") : source);
    console.log(`ok   已写回 ${path.relative(ROOT, MAIN)}`);
  }

  // 语法闸门：改造后的 main 必须能被 Node 解析（生成式编辑不能只凭「替换成功」就认为有效）。
  try {
    execFileSync(process.execPath, ["--check", MAIN], { stdio: "pipe" });
    console.log("ok   node --check 通过");
  } catch (err) {
    console.error("fail node --check 未通过：", String(err.stderr || err).slice(0, 600));
    return 1;
  }

  // electron-builder 的 afterPack 钩子必须位于工作区（app/）内 ⇒ 把钩子复制进去，并在 files 里排除它。
  const hookSrc = path.join(ROOT, "scripts", "after-pack.cjs");
  const hookDst = path.join(APP_DIR, "scripts", "after-pack.cjs");
  fs.mkdirSync(path.dirname(hookDst), { recursive: true });
  fs.copyFileSync(hookSrc, hookDst);
  console.log(`ok   已放置 afterPack 钩子 ${path.relative(ROOT, hookDst)}`);
  try {
    execFileSync(process.execPath, ["--check", hookDst], { stdio: "pipe" });
  } catch (err) {
    console.error("fail 钩子语法检查未通过：", String(err.stderr || err).slice(0, 400));
    return 1;
  }
  return 0;
}

process.exit(main());
