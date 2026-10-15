// Move the Download Center into the Settings page as two tabs: 通用设置 / 模型下载.
//
// The workbench shell (Electron renderer bundle) has a Settings page whose content is the
// theme block plus the config form. This script appends a *self-contained, fail-safe* DOM
// enhancer to that bundle: it renders a two-tab bar at the top of the Settings page, keeps the
// existing settings as the first tab, and shows the backend's /downloads page in an iframe as
// the second tab. It never touches React's own code, so the worst case is "the extra tab bar
// does not appear" — the Settings page itself keeps working.
//
// Usage:
//   node integration/downloads_in_settings_patch.js [path-to-app.asar] [--apply]
//
// Without --apply it writes <asar>.new (nothing is overwritten). With --apply it first backs the
// original up to <asar>.bak-settings-tabs, then replaces it in place.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const args = process.argv.slice(2);
const apply = args.includes('--apply');
const asar = path.resolve(args.find((a) => !a.startsWith('--')) || 'D:/MossTTSD/client/resources/app.asar');
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'moss-settings-tabs-'));
const extracted = path.join(work, 'app');
const output = asar + '.new';
const asarCli = ['--yes', '@electron/asar@4'];
const MARK = '[moss] settings-tabs';

function run(argv) {
  const r = spawnSync('npx', [...asarCli, ...argv], { encoding: 'utf8', shell: true });
  if (r.stdout) process.stdout.write(r.stdout);
  if (r.stderr) process.stderr.write(r.stderr);
  if (r.status !== 0) throw new Error(`asar command failed (${r.status}): ${argv.join(' ')}`);
}

// ---------------------------------------------------------------------------
// Injected enhancer (plain ES5 + DOM, no React, idempotent, re-applies on re-render)
// ---------------------------------------------------------------------------
const ENHANCER = `
/* ${MARK} begin */
(function () {
  var BAR = 'data-moss-settings-tabs';
  var PANEL = 'data-moss-settings-tabs-panel';
  var ENV_URL = 'http://127.0.0.1:17990/';   // 独立「环境准备 / 下载」界面
  var envStarted = false;
  var envPoll = null;
  var envFrame = null;
  var envLoaded = '';

  function isZh() {
    var head = (document.body && document.body.innerText || '').slice(0, 3000);
    return /设置|首页|关于|外观/.test(head);
  }

  function labels() {
    // 环境准备与模型下载是同一个页面（17990 = downloads.html + 环境准备段），只留一个页签。
    return isZh() ? ['通用设置', '环境准备'] : ['General', 'Environment setup'];
  }

  // 内嵌页的主题与语言跟随外壳：theme.js / i18n.js 的取值优先级是
  // 「外壳消息 > URL 参数 > 本地缓存 > 默认」，这里两路都给。
  function envUrl() {
    return ENV_URL + '?language=' + (isZh() ? 'chinese' : 'english') + '&theme=' + shellMode();
  }

  function lumaOf(rgb) {
    var m = /rgba?\\(\\s*(\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)(?:\\s*,\\s*([\\d.]+))?/.exec(rgb || '');
    if (!m) return null;
    if (m[4] !== undefined && parseFloat(m[4]) < 0.5) return null;   // 近乎透明，忽略
    return 0.2126 * +m[1] + 0.7152 * +m[2] + 0.0722 * +m[3];
  }

  // 外壳当前明暗。Electron 壳里 html/body 往往是透明的，真正的底色在某个容器上，
  // 所以先扫容器底色、再退到文字色（浅色主题=深色文字），最后才用系统偏好兜底。
  function shellMode() {
    var scope = [];
    if (document.body) scope.push(document.body);
    if (document.documentElement) scope.push(document.documentElement);
    var extra = document.querySelectorAll('div,nav,aside,header,main,section');
    for (var i = 0; i < extra.length && i < 500; i++) scope.push(extra[i]);
    var j, lv;
    for (j = 0; j < scope.length; j++) {
      lv = lumaOf(getComputedStyle(scope[j]).backgroundColor);
      if (lv !== null) return lv < 128 ? 'dark' : 'light';
    }
    for (j = 0; j < scope.length; j++) {
      lv = lumaOf(getComputedStyle(scope[j]).color);
      if (lv !== null) return lv < 128 ? 'light' : 'dark';   // 深色文字 → 浅色主题
    }
    try {
      if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) return 'light';
    } catch (e) {}
    return 'dark';
  }

  // 内嵌页会向父窗口要主题；这里代为应答，保证页签内的页面与外壳同色。
  window.addEventListener('message', function (event) {
    var data = event.data || {};
    if (data.type === 'moss-theme-request' && event.source) {
      try { event.source.postMessage({ type: 'moss-theme', mode: shellMode(), primary: '' }, '*'); } catch (e) {}
    }
    if (data.type === 'moss-env-ready') {
      // 17990 页面加载完成。跨源 fetch 会被 CORS 挡掉，不能拿它当就绪判据，只能等页面主动上报。
      clearInterval(envPoll);
      envPoll = null;
      if (envFrame) {
        envFrame.setAttribute('data-ready', '1');
        // theme.js 以「外壳消息」为权威来源，这里把当前明暗推过去，切主题后重载即同色。
        try {
          envFrame.contentWindow.postMessage({ type: 'moss-theme', mode: shellMode(), primary: '' }, '*');
        } catch (e) {}
      }
    }
  });

  function findRoot() {
    var divs = document.querySelectorAll('div[style*="padding: 50px"],div[style*="padding:50px"]');
    for (var i = 0; i < divs.length; i++) {
      var t = divs[i].textContent || '';
      if (/外观|文件目录|Appearance|Folders/.test(t)) return divs[i];
    }
    return null;
  }

  function build(root) {
    var bar = document.createElement('div');
    bar.setAttribute(BAR, '1');
    bar.style.cssText = 'display:flex;gap:6px;margin:0 0 16px 0;padding-bottom:10px;border-bottom:1px solid rgba(128,128,128,.22)';
    var envPanel = document.createElement('div');
    envPanel.setAttribute(PANEL, '1');
    envPanel.style.cssText = 'display:none';
    envFrame = document.createElement('iframe');
    envFrame.style.cssText = 'width:100%;height:100%;border:0;background:transparent';
    envPanel.appendChild(envFrame);
    var active = 0;
    var texts = labels();
    var buttons = [];

    function apply() {
      for (var i = 0; i < buttons.length; i++) {
        var on = i === active;
        buttons[i].style.cssText = 'cursor:pointer;padding:6px 14px;border:0;border-radius:8px;font-size:14px;font-family:inherit;' +
          (on ? 'background:rgba(106,110,246,.18);font-weight:600' : 'background:transparent;opacity:.7');
      }
      var kids = root.children;
      for (var j = 0; j < kids.length; j++) {
        var el = kids[j];
        if (el === bar || el === envPanel) continue;
        el.style.display = active === 0 ? '' : 'none';
      }
      envPanel.style.display = active === 1 ? '' : 'none';
      if (active === 1) {
        // 「环境准备」：首次点开时拉起独立的 17990 界面（--no-browser，不开外部窗口）。
        // 服务还没起来时 iframe 是空的：按 3s 重载重试（连接被拒是瞬时的，代价可忽略），
        // 页面加载成功会 postMessage('moss-env-ready')，由上面的监听器停止重试。
        if (!envStarted) {
          envStarted = true;
          try { if (window.api && window.api.openEnvSetup) window.api.openEnvSetup(); } catch (e) {}
        }
        var url = envUrl();
        if (envFrame.getAttribute('data-ready') === '1' && envLoaded === url) {
          clearInterval(envPoll);
          envPoll = null;
        } else if (!envPoll) {
          // 首次打开、服务还没起、或外壳换了主题/语言 → 用新参数重新加载
          envLoaded = url;
          envFrame.setAttribute('src', url);
          envPoll = setInterval(function () {
            envFrame.removeAttribute('src');
            setTimeout(function () { envFrame.setAttribute('src', url); }, 20);
          }, 3000);
        }
        try { fit(); } catch (e) {}
      }
    }

    for (var k = 0; k < texts.length; k++) {
      (function (idx) {
        var b = document.createElement('button');
        b.type = 'button';
        b.textContent = texts[idx];
        b.setAttribute(BAR + '-btn', String(idx));
        b.addEventListener('click', function () { active = idx; apply(); });
        bar.appendChild(b);
        buttons.push(b);
      })(k);
    }
    root.insertBefore(bar, root.firstChild);
    root.appendChild(envPanel);
    apply();
  }

  function ensure() {
    var root = findRoot();
    if (!root) return;
    var bar = root.querySelector('[' + BAR + ']');
    if (bar) {
      // Settings page re-rendered? Keep the bar first and clear stale inline styles.
      if (root.firstChild !== bar) root.insertBefore(bar, root.firstChild);
      var btns = bar.querySelectorAll('button');
      if (btns.length && bar.getAttribute('data-active') === null) return;
      return;
    }
    try { build(root); } catch (e) { /* fail-safe: leave the page untouched */ }
  }

  var pending = false;
  function schedule() {
    if (pending) return;
    pending = true;
    setTimeout(function () { pending = false; try { ensure(); } catch (e) {} }, 120);
  }

  function fit() {
    var hosts = document.querySelectorAll('[' + PANEL + ']');
    var viewport = document.documentElement.clientHeight;   // 视口内高（已扣掉滚动条）
    for (var n = 0; n < hosts.length; n++) {
      var host = hosts[n];
      if (!host || host.style.display === 'none') continue;
      var parent = host.parentElement;
      var padBottom = parent ? (parseFloat(getComputedStyle(parent).paddingBottom) || 0) : 0;
      var top = host.getBoundingClientRect().top;
      host.style.height = Math.max(240, Math.round(viewport - top - padBottom - 6)) + 'px';
    }
  }

  function ensureStyle() {
    if (document.getElementById('moss-settings-tabs-style')) return;
    var s = document.createElement('style');
    s.id = 'moss-settings-tabs-style';
    // 设置页自带的主题分区上边框/上间距会和页签栏的底边框叠成两条线，去掉重复的那条。
    s.textContent = '.settings-theme-section{border-top:0 !important;margin-top:0 !important;padding-top:0 !important}';
    document.head.appendChild(s);
  }

  function start() {
    try { ensure(); ensureStyle(); } catch (e) {}
    window.addEventListener('resize', function () { try { fit(); } catch (e) {} });
    new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
/* ${MARK} end */
`;

// ---------------------------------------------------------------------------

run(['extract', asar, extracted]);
const assets = path.join(extracted, 'out', 'renderer', 'assets');
const bundles = fs.readdirSync(assets).filter((f) => f.endsWith('.js'));
if (bundles.length !== 1) throw new Error(`expected one renderer bundle, found ${bundles.length}: ${bundles}`);
const bundlePath = path.join(assets, bundles[0]);
let source = fs.readFileSync(bundlePath, 'utf8');

const BEGIN = '/* ' + MARK + ' begin */';
const END = '/* ' + MARK + ' end */';
const start = source.indexOf(BEGIN);
if (start >= 0) {
  const stop = source.indexOf(END);
  if (stop > start) {
    source = source.slice(0, start) + source.slice(stop + END.length);
    console.log(`[settings-tabs] replaced the existing enhancer in ${bundles[0]}`);
  }
}
fs.writeFileSync(bundlePath, source.replace(/\s*$/, '\n') + ENHANCER, 'utf8');
console.log(`[settings-tabs] injected enhancer (${ENHANCER.length} bytes) into ${bundles[0]}`);

// Syntax gate BEFORE packing.
const check = spawnSync('node', ['--check', bundlePath], { encoding: 'utf8', shell: true });
if (check.status !== 0) {
  process.stderr.write(check.stdout || '');
  process.stderr.write(check.stderr || '');
  throw new Error('node --check failed on the patched bundle; asar NOT written');
}
console.log('[settings-tabs] node --check passed');

// ---------------------------------------------------------------------------
// Client wiring: let the settings UI start the standalone environment/download UI
// (tools/downloader_ui.py on port 17990). Anchored, exactly-once substitutions, gated by
// `node --check` — same discipline as the packaging retrofit.
// 带 BEGIN/END 哨兵：重复执行时先摘掉旧块再按锚点重新插入，
// 否则改了补丁内容也会因为「已打过」而被跳过（踩过一次）。
function patchOnce(filePath, anchor, body, label) {
  const BEGIN = `/* [moss:${label}] begin */`;
  const END = `/* [moss:${label}] end */`;
  let text = fs.readFileSync(filePath, 'utf8');
  // 兼容早期实现：那版插在「启动后端」路径里、没有哨兵，按已知边界整段摘除
  const legacyStart = text.indexOf('// [moss] 环境准备入口');
  if (legacyStart >= 0) {
    const legacyEnd = text.indexOf('console.log("backend:"', legacyStart);
    if (legacyEnd > legacyStart) text = text.slice(0, legacyStart) + text.slice(legacyEnd);
  }
  const re = new RegExp(`${BEGIN.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[\\s\\S]*?${END.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\n?`, 'g');
  const had = re.test(text);
  text = text.replace(re, '');
  const hits = text.split(anchor).length - 1;
  if (hits !== 1) throw new Error(`${label}: anchor must match exactly once, matched ${hits}`);
  fs.writeFileSync(filePath, text.replace(anchor, `${BEGIN}\n${body}\n${END}\n${anchor}`), 'utf8');
  console.log(`[settings-tabs] ${label}: ${had ? 'replaced' : 'patched'}`);
}

const mainPath = path.join(extracted, 'out', 'main', 'index.js');
patchOnce(
  mainPath,
  'electron.ipcMain.handle("check-port", async (_event) => {',
  `// [moss] 环境准备入口：设置页「环境准备」页签用它拉起独立的 17990 界面（--no-browser，不开外部窗口）。
// 必须注册在模块级：启动后端那条路径只在用户点「启动」时才执行，注册在里面页签就永远拉不起服务。
// 工作台根目录在此自行解析，不依赖外层函数作用域（外层变量在模块级不可见）。
electron.ipcMain.removeHandler("open-env-setup");
electron.ipcMain.handle("open-env-setup", () => {
  try {
    const configured = process.env.MOSS_WORKBENCH_ROOT && process.env.MOSS_WORKBENCH_ROOT.trim();
    const packaged = path$1.join(process.resourcesPath, "workbench");
    const root = configured
      ? configured
      : fs$1.existsSync(path$1.join(packaged, "server", "run.py"))
        ? packaged
        : process.platform === "win32" ? "D:/MossTTSD" : process.cwd();
    const script = path$1.join(root, "tools", "downloader_ui.py");
    if (!fs$1.existsSync(script)) { console.error("[moss] 环境准备入口不存在:", script); return false; }
    const candidates = process.platform === "win32"
      ? [path$1.join(root, "client", "python", "python.exe"), path$1.join(root, "python", "python.exe")]
      : [path$1.join(root, "client", "python", "python3"), path$1.join(root, "python", "python3")];
    const python = candidates.find((p) => fs$1.existsSync(p));
    if (!python) { console.error("[moss] 未找到可用的 Python 解释器"); return false; }
    const child = child_process.spawn(python, [script, "--no-browser"], { cwd: root, detached: true, stdio: "ignore", windowsHide: true });
    child.unref();
    return true;
  } catch (err) {
    console.error("[moss] 环境准备启动失败:", err);
    return false;
  }
});
`,
  'main',
);

const preloadPath = path.join(extracted, 'out', 'preload', 'index.js');
patchOnce(
  preloadPath,
  '  checkPort: () => electron.ipcRenderer.invoke("check-port"),',
  `  // [moss] 拉起并打开「环境准备」独立界面（设置页「环境准备」页签使用）
  openEnvSetup: () => electron.ipcRenderer.invoke("open-env-setup"),
`,
  'preload',
);

for (const file of [mainPath, preloadPath]) {
  const chk = spawnSync('node', ['--check', file], { encoding: 'utf8', shell: true });
  if (chk.status !== 0) {
    process.stderr.write(chk.stdout || '');
    process.stderr.write(chk.stderr || '');
    throw new Error(`node --check failed on ${file}; asar NOT written`);
  }
}
console.log('[settings-tabs] main/preload node --check passed');

run(['pack', extracted, output]);
console.log(`[settings-tabs] wrote ${output}`);

if (apply) {
  const backup = asar + '.bak-settings-tabs';
  fs.copyFileSync(asar, backup);
  fs.copyFileSync(output, asar);
  console.log(`[settings-tabs] applied in place (backup: ${backup})`);
} else {
  console.log('[settings-tabs] re-run with --apply to replace the original asar');
}
