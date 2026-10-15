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
  var PORTS = [17980, 17990];   // backend default, then the standalone downloader UI

  function labels() {
    var head = (document.body && document.body.innerText || '').slice(0, 3000);
    var zh = /设置|首页|关于|外观/.test(head);
    return zh ? ['通用设置', '模型下载'] : ['General', 'Model downloads'];
  }

  // 外壳当前明暗：读宿主自身的底色亮度，用于给嵌套 iframe 兜底主题（外层广播到不了它）。
  function shellMode() {
    var nodes = [document.body, document.documentElement];
    for (var i = 0; i < nodes.length; i++) {
      if (!nodes[i]) continue;
      var bg = getComputedStyle(nodes[i]).backgroundColor || '';
      if (!bg || bg === 'transparent' || /rgba\\(\\s*0\\s*,\\s*0\\s*,\\s*0\\s*,\\s*0\\s*\\)/.test(bg)) continue;
      var m = /rgba?\\(\\s*(\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)/.exec(bg);
      if (!m) continue;
      var luma = 0.2126 * +m[1] + 0.7152 * +m[2] + 0.0722 * +m[3];
      return luma < 128 ? 'dark' : 'light';
    }
    return 'dark';
  }

  // 内嵌页会向父窗口要主题；这里代为应答，保证页签内的页面与外壳同色。
  window.addEventListener('message', function (event) {
    var data = event.data || {};
    if (data.type === 'moss-theme-request' && event.source) {
      try { event.source.postMessage({ type: 'moss-theme', mode: shellMode(), primary: '' }, '*'); } catch (e) {}
    }
  });

  function pickBase() {
    // Probe the known ports; fall back to the backend default.
    var i = 0;
    function tryNext() {
      if (i >= PORTS.length) return Promise.resolve('http://127.0.0.1:' + PORTS[0]);
      var base = 'http://127.0.0.1:' + PORTS[i++];
      return fetch(base + '/api/health', { cache: 'no-store' })
        .then(function (r) { return r.ok ? base : tryNext(); })
        .catch(tryNext);
    }
    return tryNext();
  }

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
    var panel = document.createElement('div');
    panel.setAttribute(PANEL, '1');
    panel.style.cssText = 'display:none';
    var frame = document.createElement('iframe');
    frame.style.cssText = 'width:100%;height:100%;border:0;background:transparent';
    panel.appendChild(frame);
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
        if (el === bar || el === panel) continue;
        el.style.display = active === 0 ? '' : 'none';
      }
      panel.style.display = active === 1 ? '' : 'none';
      if (active === 1) {
        try { fit(); } catch (e) {}   // 撑满页签下方空间，且不把外层容器顶出滚动条
        pickBase().then(function (base) {
          var url = base + '/downloads';
          // 每次切回该页签都重新加载一次：上一次加载失败（例如后端还没起）时也能自愈。
          var same = frame.getAttribute('src') === url;
          if (same) frame.removeAttribute('src');
          setTimeout(function () { frame.setAttribute('src', url); }, same ? 30 : 0);
        });
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
    root.appendChild(panel);
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
    var host = document.querySelector('[' + PANEL + ']');
    if (!host || host.style.display === 'none') return;
    var parent = host.parentElement;
    var padBottom = parent ? (parseFloat(getComputedStyle(parent).paddingBottom) || 0) : 0;
    var viewport = document.documentElement.clientHeight;   // 视口内高（已扣掉滚动条）
    var top = host.getBoundingClientRect().top;
    host.style.height = Math.max(240, Math.round(viewport - top - padBottom - 6)) + 'px';
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
