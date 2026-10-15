// Add persisted English UI localization to the packaged renderer bundle.
// Usage: node integration/enable_english_ui.js [path-to-app.asar]
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const asar = path.resolve(process.argv[2] || 'D:/MossTTSD/client/resources/app.asar');
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'moss-english-ui-'));
const extracted = path.join(work, 'app');
const output = asar + '.new';
const asarCli = ['--yes', '@electron/asar@4'];

function run(args) {
  const result = spawnSync('npx', [...asarCli, ...args], { encoding: 'utf8', shell: true });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.status !== 0) throw new Error(`asar command failed (${result.status}): ${args.join(' ')}`);
}

const translations = {
  '首页': 'Home',
  '工具': 'Tools',
  '控制台': 'Console',
  '设置': 'Settings',
  '关于': 'About',
  '界面语言': 'Language',
  '中文': 'Chinese',
  '英文': 'English',
  '保存': 'Save',
  '重置': 'Reset',
  '文件目录': 'Folders',
  '根目录': 'Root folder',
  '资产目录': 'Assets folder',
  '模型目录': 'Models folder',
  '输出目录': 'Output folder',
  '上传目录': 'Uploads folder',
  '加载配置失败': 'Failed to load settings',
  '已保存': 'Settings saved',
  'MOSS 语音工作台': 'MOSS Voice Workbench',
  '版本 v1.0.0': 'Version v1.0.0',
  '本地 MOSS 语音工作台：单人配音 / 音色克隆 / 音色设计 / 多人对话 / 音效生成，全部在本地 GPU 推理，数据不出机器。': 'MOSS Voice Workbench runs locally: single-speaker TTS and voice cloning, voice design, multi-speaker dialogue, and sound effects are generated on your local GPU. Your data stays on your device.',
  '更多干货，请访问 =>': 'More resources:',
  ' 用户协议与免责声明': ' User Agreement and Disclaimer',
  '使用前必读': 'Please read before use',
  '本工作台是纯本地运行的开源模型前端：单人配音 / 音色克隆、音色设计、多人对话、音效生成全部在本机 GPU 推理，您输入的文本、参考音频与生成结果都不会上传到任何服务器。继续使用即表示您已阅读并同意下列条款；因使用本软件产生的全部结果与责任由您自行承担。': 'This workbench is a local frontend for open-source models. TTS, voice cloning, voice design, dialogue, and sound effects run on your GPU. Text, reference audio, and generated results are not uploaded. By continuing, you accept the terms below and responsibility for your use of this software.',
  '声音克隆必须获得授权': 'Voice cloning requires authorization',
  '只能克隆您本人、或已获得明确授权的说话人的声音；不得用于伪造他人声音、冒充他人身份、诈骗、诽谤或制作虚假信息，也不得把生成内容对外说成真实人物本人的发言。': 'Clone only your own voice or a speaker’s voice with their explicit authorization. Do not impersonate others, commit fraud or defamation, create deceptive content, or present generated speech as a real person’s statement.',
  '生成内容由模型自动产生，可能存在错误或不准确，不代表开发者立场；对外发布前请自行核对（语音内容可用内置的「识别逐字稿」复核）。模型的代码与权重遵循各自的开源许可（如 Apache-2.0）。本软件按“现状”提供，不对生成内容的准确性、合法性或适用性作任何担保；因使用或无法使用本软件造成的损失，开发者不承担责任。': 'Model-generated output may be inaccurate and does not represent the developer’s views. Verify content before publishing; use “Transcribe” to check speech. Model code and weights have their own licenses (for example, Apache-2.0). This software is provided “as is,” without warranties. The developer is not liable for losses arising from use or inability to use it.',
  '您不得利用本软件实施包括但不限于以下行为，也不得为下列行为提供便利：': 'You must not use this software to engage in, or facilitate, any of the following:',
  '反对宪法所确定的基本原则。': 'Oppose the fundamental principles established by the Constitution.',
  '危害国家安全、泄露国家秘密、颠覆国家政权、破坏国家统一，以及损害国家荣誉和利益。': 'Endanger national security, disclose state secrets, subvert state power, undermine national unity, or harm national honor and interests.',
  '煽动民族仇恨、民族歧视，破坏民族团结；破坏国家宗教政策，宣扬邪教和封建迷信。': 'Incite ethnic hatred or discrimination, undermine ethnic unity, violate religious policy, or promote cults or superstition.',
  '散布谣言，扰乱社会秩序、破坏社会稳定；散布淫秽、色情、赌博、暴力、凶杀、恐怖或教唆犯罪的信息。': 'Spread rumors or disrupt public order and stability; distribute obscene, pornographic, gambling, violent, murderous, terroristic, or crime-inciting content.',
  '侮辱、诽谤他人，侵害他人合法权益；冒用他人身份，或伪造他人声音、肖像。': 'Insult or defame others, infringe their lawful rights, impersonate them, or falsify their voice or likeness.',
  '制作、传播法律、行政法规禁止的其他内容。': 'Create or distribute other content prohibited by law or administrative regulation.',
  '模型与上游项目（MOSS-TTS Family · Apache-2.0）': 'Models and upstream projects (MOSS-TTS Family · Apache-2.0)',
  '本工作台只是本机前端：单人配音 / 音色克隆、音色设计、多人对话、音效生成，全部由 OpenMOSS 开源的 MOSS 模型在本机 GPU 推理完成；代码与权重均为 Apache-2.0 许可，可商用。': 'This workbench is a local frontend. OpenMOSS MOSS models run on your GPU for TTS, voice cloning, voice design, dialogue, and sound effects. Code and weights use the Apache-2.0 license and may be used commercially.',
  '用到的模型：MOSS-TTS-v1.5（单人配音 / 零样本声音克隆）、MOSS-VoiceGenerator（音色设计）、MOSS-TTSD-v1.0（多人对话）、MOSS-SoundEffect（音效）、MOSS-Audio-Tokenizer（音频编解码）。': 'Models: MOSS-TTS-v1.5 (single-speaker TTS / zero-shot voice cloning), MOSS-VoiceGenerator (voice design), MOSS-TTSD-v1.0 (multi-speaker dialogue), MOSS-SoundEffect (sound effects), and MOSS-Audio-Tokenizer (audio codec).',
  '官方资源：': 'Official resources:',
  '官方主页 openmoss.ai': 'Official site · openmoss.ai',
  'GitHub · OpenMOSS/MOSS-TTS': 'GitHub · OpenMOSS/MOSS-TTS',
  'HuggingFace · OpenMOSS-Team': 'Hugging Face · OpenMOSS-Team',
  'ModelScope · openmoss': 'ModelScope · openmoss',
  'MOSS 语音工作台 · 本地部署': 'MOSS Voice Workbench · Local deployment',
  '  欢迎使用 MOSS 语音工作台': '  Welcome to MOSS Voice Workbench',
  '一键启动': 'Start',
  '刷新': 'Refresh',
  '停止': 'Stop',
  '服务已停止……': 'Service stopped…',
  '正在启动服务……': 'Starting service…',
  '正在进入界面...': 'Loading interface…',
  '尝试次数: ': 'Attempt: ',
  '打开网页版': 'Open in browser',
  '等待服务启动...': 'Waiting for the service to start...',
  '外观': 'Appearance',
  '界面会立即应用所选主题。': 'The interface applies the theme immediately.',
  '主题模式': 'Theme mode',
  '浅色': 'Light',
  '暗黑': 'Dark',
  '跟随系统': 'Follow system',
  '主配色': 'Primary color',
  '自定义': 'Custom',
  '恢复默认': 'Reset to default',
  '下载中心': 'Download Center',
  '必要组件未下载': 'Required components are missing',
  '打开下载中心': 'Open Download Center',
  '检查必要组件…': 'Checking required components…'
};

const localeRuntime = `
;(() => {
  const translations = ${JSON.stringify(translations)};
  const entries = Object.entries(translations).map(([zh, en]) => [zh.trim(), en.trim()]);
  const forward = { ...Object.fromEntries(entries), '保 存': 'Save', '重 置': 'Reset', '刷 新': 'Refresh', '停 止': 'Stop' };
  const reverse = Object.fromEntries(entries.map(([zh, en]) => [en, zh]));
  let current = 'chinese';
  const observer = new MutationObserver(() => apply(current));
  const apply = (language) => {
    current = language === 'english' ? 'english' : 'chinese';
    const root = document.body;
    if (!root) return;
    observer.disconnect();
    const map = current === 'english' ? forward : reverse;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) => node.parentElement?.closest('script, style, textarea, pre, [contenteditable]')
        ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const value = node.nodeValue;
      const trimmed = value.trim();
      if (!trimmed || !Object.prototype.hasOwnProperty.call(map, trimmed)) continue;
      const start = value.indexOf(trimmed);
      const translated = value.slice(0, start) + map[trimmed] + value.slice(start + trimmed.length);
      if (translated !== value) node.nodeValue = translated;
    }
    window.mossUiLanguage = current;
    // 只投递给本机后端页面（127.0.0.1:<port>）：既覆盖 Tools iframe，也覆盖工作台 iframe。
    document.querySelectorAll('iframe').forEach(frame => {
      const origin = frameOrigin(frame);
      if (origin) frame.contentWindow?.postMessage({ type: 'moss-language', language: current }, origin);
    });
    observer.observe(root, { childList: true, characterData: true, subtree: true });
  };
  const frameOrigin = (frame) => {
    if (!frame.src) return null;
    try {
      const url = new URL(frame.src);
      return url.hostname === '127.0.0.1' || url.hostname === 'localhost' ? url.origin : null;
    } catch (_) { return null; }
  };
  const localOrigin = (value) => {
    try {
      const url = new URL(value);
      return url.hostname === '127.0.0.1' || url.hostname === 'localhost' ? url.origin : null;
    } catch (_) { return null; }
  };

  // ================== 主题：浅色 / 暗黑 / 跟随系统 + 自定义主色 ==================
  // 包里 antd 被 tree-shaking（只有 defaultAlgorithm，没有 darkAlgorithm），
  // 所以暗色不换算法，改为一组暗色 token 覆盖（写完与 light 视觉对拍过）。
  const MOSS_DARK_TOKENS = {
    colorBgBase: '#0f1219',
    colorTextBase: '#e7ebf5',
    colorBgLayout: '#0f1219',
    colorBgContainer: '#1a1f2b',
    colorBgElevated: '#202634',
    colorBgSpotlight: '#202634',
    colorBgHeader: '#1a1f2b',
    colorBorder: '#2a3140',
    colorBorderSecondary: '#232936',
    colorFillSecondary: 'rgba(255,255,255,0.10)',
    colorFillTertiary: 'rgba(255,255,255,0.07)',
    colorFillQuaternary: 'rgba(255,255,255,0.05)',
    colorText: 'rgba(231,235,245,0.92)',
    colorTextSecondary: 'rgba(231,235,245,0.68)',
    colorTextTertiary: 'rgba(231,235,245,0.45)',
    colorTextQuaternary: 'rgba(231,235,245,0.28)',
    colorTextPlaceholder: 'rgba(231,235,245,0.32)',
    colorTextDescription: 'rgba(231,235,245,0.55)',
    colorIcon: 'rgba(231,235,245,0.55)',
    colorIconHover: 'rgba(231,235,245,0.85)',
    colorSplit: 'rgba(255,255,255,0.08)',
    colorBgMask: 'rgba(0,0,0,0.55)',
    // 状态类“淡底”（Alert / Tag / Result 等）：亮色算法给的是近白淡色
    // （colorWarningBg=#fffbe6、colorErrorBg=#fff2f0 实测），暗色下配浅色文字看不清。
    // 这里按各自 seed 混入暗色底面，等价于 antd 暗色算法的做法。
    colorErrorBg: '#351b22',
    colorErrorBgHover: '#492026',
    colorErrorBorder: '#7b2d31',
    colorWarningBg: '#352b18',
    colorWarningBgHover: '#473718',
    colorWarningBorder: '#795817',
    colorSuccessBg: '#1a2e19',
    colorSuccessBgHover: '#1f3d19',
    colorSuccessBorder: '#2d6219',
    colorInfoBg: '#10223e',
    colorInfoBgHover: '#112a50',
    colorInfoBorder: '#123f80',
    colorFillAlter: 'rgba(255,255,255,0.04)',
    colorBgTextHover: 'rgba(255,255,255,0.06)',
    colorBgTextActive: 'rgba(255,255,255,0.10)'
  };
  window.__mossThemeDarkTokens = MOSS_DARK_TOKENS;
  const THEME_MODES = ['light', 'dark', 'system'];
  const THEME_HEX = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i;
  const themeMedia = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  let themeMode = 'light';
  let themePrimary = '';
  const normalizeMode = (value) => THEME_MODES.indexOf(value) >= 0 ? value : null;
  const normalizePrimary = (value) => {
    if (typeof value !== 'string') return null;
    const raw = value.trim();
    if (!THEME_HEX.test(raw)) return null;
    let hex = raw.replace('#', '').toLowerCase();
    if (hex.length === 3) hex = hex.split('').map((c) => c + c).join('');
    return '#' + hex;
  };
  const isDarkTheme = () => themeMode === 'system' ? !!(themeMedia && themeMedia.matches) : themeMode === 'dark';
  const broadcastTheme = () => {
    document.querySelectorAll('iframe').forEach(frame => {
      const origin = frameOrigin(frame);
      if (origin) frame.contentWindow?.postMessage({ type: 'moss-theme', mode: themeMode, primary: themePrimary }, origin);
    });
  };
  const applyTheme = (patch, options) => {
    const opts = options || {};
    const mode = normalizeMode(patch && patch.mode);
    const primary = patch && Object.prototype.hasOwnProperty.call(patch, 'primary') ? normalizePrimary(patch.primary) : null;
    let changed = false;
    if (mode && mode !== themeMode) { themeMode = mode; changed = true; }
    if (primary && primary !== themePrimary) { themePrimary = primary; changed = true; }
    else if (patch && (patch.primary === '' || patch.primary === null) && themePrimary) { themePrimary = ''; changed = true; }
    if (opts.persist) window.api.onSaveConfig({ theme: { mode: themeMode, primary: themePrimary } });
    if (!changed && opts.force !== true) return false;
    const dark = isDarkTheme();
    // 主色的“淡底”系列：antd 默认（亮色）算法给的是接近白色的淡色底（colorPrimaryBg），
    // 在暗色下配浅色文字会看不清（Select 选中项、侧栏菜单选中态）。这里按当前主色算出暗色淡底
    // 覆盖该系列 token；主色一变就重算，随用户选色走。
    const themeBase = themePrimary || '#f77612';
    const toRgb = (hex) => {
      const h = String(hex).replace('#', '');
      const f = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
      return [parseInt(f.slice(0, 2), 16), parseInt(f.slice(2, 4), 16), parseInt(f.slice(4, 6), 16)];
    };
    const mixHex = (hex, target, ratio) => '#' + toRgb(hex).map((v, i) => {
      const t = toRgb(target)[i];
      return Math.max(0, Math.min(255, Math.round(v + (t - v) * ratio))).toString(16).padStart(2, '0');
    }).join('');
    MOSS_DARK_TOKENS.colorPrimaryBg = mixHex(themeBase, '#0f1219', 0.78);
    MOSS_DARK_TOKENS.colorPrimaryBgHover = mixHex(themeBase, '#0f1219', 0.68);
    MOSS_DARK_TOKENS.controlItemBgActive = MOSS_DARK_TOKENS.colorPrimaryBg;
    MOSS_DARK_TOKENS.controlItemBgActiveHover = MOSS_DARK_TOKENS.colorPrimaryBgHover;
    MOSS_DARK_TOKENS.controlItemBgHover = 'rgba(255,255,255,0.08)';
    MOSS_DARK_TOKENS.colorPrimaryBorder = mixHex(themeBase, '#0f1219', 0.5);
    MOSS_DARK_TOKENS.colorPrimaryBorderHover = mixHex(themeBase, '#0f1219', 0.4);
    document.documentElement.style.setProperty('--moss-primary-rgb', toRgb(themeBase).join(', '));
    window.__mossTheme = { mode: themeMode, primary: themePrimary, dark: dark };
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    document.documentElement.dataset.themeMode = themeMode;
    // 给注入的 CSS 用（设置页色块/链接跟随主色）
    document.documentElement.style.setProperty('--moss-primary', themePrimary || '#f77612');
    if (typeof window.__mossRerenderTheme === 'function') window.__mossRerenderTheme();
    broadcastTheme();
    return true;
  };
  window.setMossUiTheme = (patch) => applyTheme(patch, { persist: true });
  window.getMossUiTheme = () => ({ mode: themeMode, primary: themePrimary, dark: isDarkTheme() });
  // 外壳 → 工作台/Tools iframe 的初始参数（避免暗色下先白闪）
  window.__mossThemeQuery = () => '?theme=' + encodeURIComponent(themeMode) + (themePrimary ? '&primary=' + themePrimary.slice(1) : '');
  window.__mossThemeParams = () => '&theme=' + encodeURIComponent(themeMode) + (themePrimary ? '&primary=' + themePrimary.slice(1) : '');

  window.addEventListener('message', (event) => {
    const type = event.data && event.data.type;
    if (type !== 'moss-language-request' && type !== 'moss-theme-request') return;
    // 只应答本机后端的页面请求，避免向无关窗口泄露界面语言 / 主题
    const origin = localOrigin(event.origin);
    if (!origin) return;
    const reply = type === 'moss-language-request'
      ? { type: 'moss-language', language: current }
      : { type: 'moss-theme', mode: themeMode, primary: themePrimary };
    try { event.source?.postMessage(reply, origin); } catch (_) {}
  });
  window.setMossUiLanguage = apply;
  window.api.getConfig().then((config) => {
    apply(config.language);
    const theme = config.theme || {};
    applyTheme({ mode: theme.mode, primary: typeof theme.primary === 'string' ? theme.primary : '' }, { force: true });
  }).catch(() => {
    apply('chinese');
    applyTheme({ mode: 'light' }, { force: true });
  });
  if (themeMedia) {
    const onSystemThemeChange = () => {
      if (themeMode === 'system') applyTheme({}, { force: true });
    };
    if (themeMedia.addEventListener) themeMedia.addEventListener('change', onSystemThemeChange);
    else if (themeMedia.addListener) themeMedia.addListener(onSystemThemeChange);
  }
  if (document.body) observer.observe(document.body, { childList: true, characterData: true, subtree: true });
})();
`;

const cssBegin = '/* ---- moss-theme:begin ---- */';
const cssEnd = '/* ---- moss-theme:end ---- */';
const themeCss = `
${cssBegin}
/* ---- 主题设置区与暗色基础（由 integration/enable_english_ui.js 注入）---- */
:root {
  --moss-line: #e8e8e8;
  --moss-seg-bg: #f2f4f8;
  --moss-active-bg: #ffffff;
  --moss-active-ring: #1f2534;
  --moss-primary: #f77612;
  --moss-primary-rgb: 247, 118, 18;
  --moss-page-bg: #ffffff;
  --moss-menu-bg: #f5f5f0;
  --moss-soft: #f5f5f5;
  --moss-stop-bg: #f6ece4;
  --moss-stop-fg: #937965;
  --moss-link: #1677ff;
}
.settings-theme-section .moss-hint { margin: 0 0 14px; font-size: 13px; opacity: 0.65; }
.moss-theme-row { display: flex; align-items: center; gap: 14px; margin-bottom: 12px; }
.moss-theme-label { width: 84px; font-size: 13px; opacity: 0.85; }
.moss-segmented { display: inline-flex; gap: 3px; padding: 3px; border-radius: 10px; background: var(--moss-seg-bg); }
.moss-seg { border: 0; background: transparent; color: inherit; font: inherit; font-size: 13px; padding: 5px 14px; border-radius: 8px; cursor: pointer; }
.moss-seg.is-active { background: var(--moss-active-bg); box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12); font-weight: 600; }
.moss-swatches { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.moss-swatch { width: 24px; height: 24px; padding: 0; border-radius: 7px; border: 2px solid transparent; box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.12); cursor: pointer; }
.moss-swatch.is-active { border-color: var(--moss-active-ring); }
.moss-swatch-custom { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; }
.moss-swatch-custom input { width: 34px; height: 26px; padding: 0; border: 1px solid var(--moss-line); border-radius: 7px; background: transparent; cursor: pointer; }
.moss-link { border: 0; background: transparent; color: var(--moss-primary); font: inherit; font-size: 13px; padding: 0; cursor: pointer; }
/* 顶栏服务链接：显示后端地址，点击用系统浏览器打开 */
.moss-service-link {
  display: inline-flex; align-items: center; gap: 8px; margin: 0 12px; padding: 3px 10px;
  border: 1px solid var(--moss-line, #e8e8e8); border-radius: 8px; text-decoration: none;
  color: var(--moss-link, #1677ff); font-size: 12px; white-space: nowrap; line-height: 20px;
}
.moss-service-link:hover { border-color: var(--moss-primary); color: var(--moss-primary); }
.moss-service-link code { font-family: ui-monospace, Consolas, monospace; font-size: 11.5px; opacity: 0.9; color: inherit; }
html[data-theme="dark"] {
  color-scheme: dark;
  --moss-line: #2a3140;
  --moss-seg-bg: #212736;
  --moss-active-bg: #2b3344;
  --moss-active-ring: #e7ebf5;
  --moss-page-bg: #0f1219;
  --moss-menu-bg: #1a1f2b;
  --moss-soft: #1a1f2b;
  --moss-stop-bg: #14161d;
  --moss-stop-fg: #a9b4cc;
  --moss-link: #7b80ff;
}
html[data-theme="dark"] body { background: #0f1219; color: #e7ebf5; }
html[data-theme="dark"] .headBanner { background: linear-gradient(120deg, #1b2130, #202634, #1b2130); }
html[data-theme="dark"] .stopPage { color: var(--moss-stop-fg); background: var(--moss-stop-bg); }
/* 侧栏容器：antd 的 -dark 变体会把 aside 涂成 #001529，菜单常覆盖它，这里兜住露出的边 */
html[data-theme="dark"] .ant-layout-sider,
html[data-theme="dark"] .ant-layout-sider-dark { background: #1a1f2b !important; }
html[data-theme="dark"] .ant-layout-sider-children { background: transparent; }
${cssEnd}
`;

try {
  run(['extract', asar, extracted]);
  const assets = path.join(extracted, 'out', 'renderer', 'assets');
  const bundles = fs.readdirSync(assets).filter((name) => /^index-.*\.js$/.test(name));
  if (bundles.length !== 1) throw new Error(`expected one renderer bundle, found ${bundles.length}`);
  const bundlePath = path.join(assets, bundles[0]);
  let source = fs.readFileSync(bundlePath, 'utf8');
  const alreadyLocalized = source.includes('window.setMossUiLanguage');

  const optionAnchor = '{ value: "chinese", label: "汉语" }';
  if (!alreadyLocalized) {
    if (source.split(optionAnchor).length !== 2) throw new Error('language option anchor mismatch');
    source = source.replace(optionAnchor, `${optionAnchor}, { value: "english", label: "English" }`);
  }

  // 语言选项名统一为通用叫法：汉语 / 英语 → 中文 / 英文
  // （英文界面里由上面的词条表译成 Chinese / English；配置值仍是 chinese / english，不动。）
  if (!source.includes('label: "中文"')) {
    const cnLabels = source.split('label: "汉语"').length - 1;
    if (cnLabels !== 1) throw new Error(`language label anchor expected 1, found ${cnLabels}`);
    source = source.replace('label: "汉语"', 'label: "中文"');
  }
  if (!source.includes('label: "英文"') && source.includes('label: "英语"')) {
    const enLabels = source.split('label: "英语"').length - 1;
    if (enLabels !== 1) throw new Error(`language label anchor expected 1, found ${enLabels}`);
    source = source.replace('label: "英语"', 'label: "英文"');
  }

  if (!alreadyLocalized) {
    const saveAnchor = /const handleSave = \(values\) => \{\s*window\.api\.onSaveConfig\(values\);\s*\};/;
    if ((source.match(saveAnchor) || []).length !== 1) throw new Error('settings save anchor mismatch');
    source = source.replace(saveAnchor, 'const handleSave = (values) => { window.api.onSaveConfig(values); window.setMossUiLanguage?.(values.language); };');
  }

  // Remove the ineffective layering workaround; the freeze was an observer loop.
  const siderAnchor = '/* @__PURE__ */ jsxRuntimeExports.jsx(Sider, { width: 130, children:';
  const elevatedSiderAnchor = '/* @__PURE__ */ jsxRuntimeExports.jsx(Sider, { width: 130, style: { position: "relative", zIndex: 10 }, children:';
  source = source.replace(elevatedSiderAnchor, siderAnchor);

  if (source.includes('const CommonTools = () => {')) {
    source = source.replace('const CommonTools = () => {', 'const SettingsFolders = () => {');
    const start = source.indexOf('const ConfigSettings = () => {');
    const end = source.indexOf('const FolderItem =', start);
    let settings = source.slice(start, end);
    const opener = 'jsxRuntimeExports.jsx("div", { style: { padding: 50 }, children: /* @__PURE__ */ jsxRuntimeExports.jsxs(Form$1,';
    if (!settings.includes(opener)) throw new Error('settings container anchor mismatch');
    settings = settings.replace(opener, 'jsxRuntimeExports.jsxs("div", { style: { padding: 50 }, children: [/* @__PURE__ */ jsxRuntimeExports.jsxs(Form$1,');
    settings = settings.replace(/\]\s*\}\)\s*\}\);\s*\};\s*$/, '] }), jsxRuntimeExports.jsx(SettingsFolders, {})] });\n};\n');
    source = source.slice(0, start) + settings + source.slice(end);
    source = source.replace(/const SettingsFolders = \(\) => \{[\s\S]*?const \{ Title/, block => block.replace('padding: 30', 'padding: "24px 0 0"'));
    source = source.replace(/\s*\{\s*label:[^\n]*\n\s*key: "\/tools",\s*\n\s*icon:[^\n]*\n\s*\},/, '');
    source = source.replace(/\s*\/\* @__PURE__ \*\/ jsxRuntimeExports\.jsx\(Route, \{ path: "\/tools",[^\n]*\n/, '\n');
  }
  const settingsStart = source.indexOf('const ConfigSettings = () => {');
  const settingsEnd = source.indexOf('const FolderItem =', settingsStart);
  if (settingsStart < 0 || settingsEnd < 0) throw new Error('settings block anchors mismatch');
  const settingsSource = source.slice(settingsStart, settingsEnd).replace('labelCol: { span: 4 }, form,', 'labelCol: { flex: "none" }, labelAlign: "left", form,');
  source = source.slice(0, settingsStart) + settingsSource + source.slice(settingsEnd);

  const foldersSlot = 'jsxRuntimeExports.jsx(SettingsFolders, {})';
  if (!source.includes('"settings-folders-section"')) {
    if (source.split(foldersSlot).length !== 2) throw new Error('folders slot anchor mismatch');
    source = source.replace(foldersSlot, 'jsxRuntimeExports.jsxs("section", { className: "settings-folders-section", style: { borderTop: "1px solid #e8e8e8", marginTop: 24, paddingTop: 20 }, children: [jsxRuntimeExports.jsx("h2", { style: { fontSize: 16, fontWeight: 600, margin: "0 0 16px" }, children: "文件目录" }), jsxRuntimeExports.jsx(SettingsFolders, {})] })');
    source = source.replace('padding: "24px 0 0"', 'padding: 0');
  }
  if (!source.includes('key: "/tools"')) {
    const consoleItem = /\{\s*label:[^\n]*\n\s*key: "\/console",/;
    if (!consoleItem.test(source)) throw new Error('console menu anchor mismatch');
    source = source.replace(consoleItem, '{ label: jsxRuntimeExports.jsx("span", { children: "工具" }), key: "/tools", icon: jsxRuntimeExports.jsx(RefIcon$b, {}) },\n  $&');
    const settingsRoute = 'jsxRuntimeExports.jsx(Route, { path: "/settings",';
    if (!source.includes(settingsRoute)) throw new Error('settings route anchor mismatch');
    source = source.replace(settingsRoute, 'jsxRuntimeExports.jsx(Route, { path: "/tools", element: jsxRuntimeExports.jsx("div", {}) }),\n        ' + settingsRoute);
  }
  const toolsShell = 'jsxRuntimeExports.jsx(Route, { path: "/tools", element: jsxRuntimeExports.jsx(StemsTools, {}) })';
  if (source.includes(toolsShell)) {
    source = source.replace(toolsShell, 'jsxRuntimeExports.jsx(Route, { path: "/tools", element: jsxRuntimeExports.jsx(StemsTools, {}) })');
  }
  const menuStart = source.indexOf('const items = [');
  const menuEnd = source.indexOf('const HeadLink =', menuStart);
  if (menuStart < 0 || menuEnd < 0) throw new Error('sidebar menu anchors missing');
  const menu = source.slice(menuStart, menuEnd).replace(/children: "[\s\u00a0]+/g, 'children: "');
  source = source.slice(0, menuStart) + menu + source.slice(menuEnd);
  const toolsRoute = 'jsxRuntimeExports.jsx(Route, { path: "/tools", element: jsxRuntimeExports.jsx("div", {}) })';
  const hasToolsRoute = source.includes(toolsRoute);
  if (hasToolsRoute || source.includes('function StemsTools() {')) {
    const component = `
function StemsTools() {
  const toolsLocation = useLocation();
  reactExports.useEffect(() => {
    const syncRoute = () => {
      const frame = window.__mossToolsFrame;
      if (!frame) return;
      const visible = window.location.hash === "#/tools";
      frame.style.visibility = visible ? "visible" : "hidden";
      frame.style.pointerEvents = visible ? "auto" : "none";
      document.body.style.overflow = visible ? "hidden" : (window.__mossToolsPreviousOverflow || "");
    };
    if (!window.__mossToolsFrame) {
      window.__mossToolsPreviousOverflow = document.body.style.overflow;
      const frame = document.createElement("iframe");
      frame.dataset.mossTools = "true";
      frame.title = "Stems";
      Object.assign(frame.style, { position: "fixed", top: "0", left: "130px", width: "calc(100% - 130px)", height: "100vh", border: "0", zIndex: "10", background: "white" });
      frame.addEventListener("load", () => frame.contentWindow?.postMessage({ type: "moss-language", language: window.mossUiLanguage || "chinese" }, new URL(frame.src).origin));
      window.__mossToolsFrame = frame;
      const connect = async () => {
        const base = await window.api.checkPort();
        if (base) {
          const themeParams = window.__mossThemeParams ? window.__mossThemeParams() : "";
          frame.src = base + "tools?language=" + (window.mossUiLanguage || "chinese") + themeParams;
          document.body.append(frame);
          syncRoute();
        } else window.setTimeout(connect, 1000);
      };
      connect();
    }
    if (!window.__mossToolsRouteHooked) {
      window.__mossToolsRouteHooked = true;
      const notify = () => window.dispatchEvent(new Event("moss-route-change"));
      for (const method of ["pushState", "replaceState"]) {
        const original = history[method];
        history[method] = function(...args) { const result = original.apply(this, args); notify(); return result; };
      }
      window.addEventListener("moss-route-change", syncRoute);
      window.addEventListener("popstate", syncRoute);
    }
    syncRoute();
  }, [toolsLocation.pathname]);
  return null;
}
`;
    const oldStart = source.indexOf('function StemsTools() {');
    const existingLinkStart = source.indexOf('function MossServiceLink() {', oldStart);
    const appStart = source.indexOf('function App() {', oldStart);
    if (oldStart >= 0 && appStart < 0) throw new Error('App() anchor mismatch');
    if (oldStart >= 0) source = source.slice(0, oldStart) + source.slice(existingLinkStart >= 0 ? existingLinkStart : appStart);
    const launcherComponent = `
function MossServiceLink() {
  const linkState = reactExports.useState("");
  const url = linkState[0];
  const setUrl = linkState[1];
  const missingState = reactExports.useState(null);
  const missing = missingState[0];
  const setMissing = missingState[1];
  const openDownloader = () => window.api.startDownloader();
  reactExports.useEffect(() => {
    let alive = true;
    let timer = null;
    const tick = async () => {
      try { const base = await window.api.checkPort(); if (alive && base) { setUrl(base); return true; } } catch (_) {}
      return false;
    };
    tick().then((done) => { if (done || !alive) return; timer = setInterval(() => { tick().then((finished) => { if (finished) { clearInterval(timer); timer = null; } }); }, 2000); });
    const checkRequired = async () => {
      try {
        window.api.startDownloader(true);
        for (let attempt = 0; attempt < 40 && alive; attempt++) {
          try {
            const response = await fetch("http://127.0.0.1:17990/api/downloads");
            if (response.ok) { const state = await response.json(); if (alive) setMissing(Array.isArray(state.required_missing) ? state.required_missing : []); return; }
          } catch (_) {}
          await new Promise((resolve) => setTimeout(resolve, 250));
        }
        if (alive) setMissing([]);
      } catch (_) { if (alive) setMissing([]); }
    };
    checkRequired();
    return () => { alive = false; clearInterval(timer); };
  }, []);
  return jsxRuntimeExports.jsxs("div", { className: "moss-service-link", children: [
    jsxRuntimeExports.jsx("button", { type: "button", onClick: openDownloader, children: "下载中心" }),
    url ? jsxRuntimeExports.jsxs("a", { href: url, target: "_blank", rel: "noreferrer", title: url, children: [jsxRuntimeExports.jsx("span", { children: "打开网页版" }), jsxRuntimeExports.jsx("code", { children: url })] }) : null,
    missing && missing.length ? jsxRuntimeExports.jsxs("div", { role: "alert", style: { marginTop: 8, padding: 8, background: "#fff7e6", color: "#8c5a00", borderRadius: 6 }, children: [
      jsxRuntimeExports.jsx("strong", { children: "必要组件未下载" }), jsxRuntimeExports.jsx("span", { children: "（" + missing.length + "）" }),
      jsxRuntimeExports.jsx("button", { type: "button", onClick: openDownloader, children: "打开下载中心" })
    ] }) : null
  ] });
}
`;
    if (!source.includes('function MossServiceLink() {')) throw new Error('MossServiceLink anchor mismatch');
    const linkStart = source.indexOf('function MossServiceLink() {');
    const linkAppStart = source.indexOf('function App() {', linkStart);
    if (linkAppStart < 0) throw new Error('MossServiceLink end anchor mismatch');
    source = source.slice(0, linkStart) + launcherComponent + '\n' + source.slice(linkAppStart);
  }
  const downloaderMarker = 'window.api.startDownloader';
  if (!source.includes(downloaderMarker) || !source.includes('必要组件未下载') || !source.includes('打开下载中心')) throw new Error('downloader UI marker validation failed');
  source = source.replace('jsxRuntimeExports.jsx(Route, { path: "/tools", element: jsxRuntimeExports.jsx(StemsTools, {}) })', 'jsxRuntimeExports.jsx(Route, { path: "/tools", element: null })');
  if (!source.includes('jsxRuntimeExports.jsx(StemsTools, {}), /* persistent tools */')) {
    const layoutAnchor = 'jsxRuntimeExports.jsxs(Layout, { children: [';
    source = source.replace(layoutAnchor, layoutAnchor + 'jsxRuntimeExports.jsx(StemsTools, {}), /* persistent tools */');
  }

  // ---------------- 主题设置区：浅色 / 暗黑 / 跟随系统 + 自定义主色 ----------------
  // 与 SettingsFolders 同一手法：注入一个纯 DOM 组件（antd 的 Switch/Segmented/ColorPicker
  // 都被 tree-shaking 了，用原生元素 + 注入的 CSS 反而更可控），再挂进设置页容器。
  if (!source.includes('function SettingsTheme() {')) {
    const themeComponent = `
function SettingsTheme() {
  const initialTheme = window.getMossUiTheme ? window.getMossUiTheme() : { mode: "light", primary: "" };
  const themeState = reactExports.useState({ mode: initialTheme.mode, primary: initialTheme.primary || "" });
  const theme = themeState[0];
  const setTheme = themeState[1];
  const modes = [{ value: "light", label: "浅色" }, { value: "dark", label: "暗黑" }, { value: "system", label: "跟随系统" }];
  const swatches = ["#6a6ef6", "#1677ff", "#13c2c2", "#52c41a", "#fa8c16", "#eb2f96", "#722ed1", "#f5222d"];
  const commit = (patch) => {
    setTheme(Object.assign({}, theme, patch));
    if (window.setMossUiTheme) window.setMossUiTheme(patch);
  };
  const picked = (theme.primary || "").toLowerCase();
  return jsxRuntimeExports.jsxs("section", {
    className: "settings-theme-section",
    style: { borderTop: "1px solid var(--moss-line, #e8e8e8)", marginTop: 24, paddingTop: 20 },
    children: [
      jsxRuntimeExports.jsx("h2", { style: { fontSize: 16, fontWeight: 600, margin: "0 0 4px" }, children: "外观" }),
      jsxRuntimeExports.jsx("p", { className: "moss-hint", children: "界面会立即应用所选主题。" }),
      jsxRuntimeExports.jsxs("div", { className: "moss-theme-row", children: [
        jsxRuntimeExports.jsx("span", { className: "moss-theme-label", children: "主题模式" }),
        jsxRuntimeExports.jsx("div", { className: "moss-segmented", children: modes.map((item) => jsxRuntimeExports.jsx("button", {
          type: "button",
          className: theme.mode === item.value ? "moss-seg is-active" : "moss-seg",
          onClick: () => commit({ mode: item.value }),
          children: item.label
        }, item.value)) })
      ] }),
      jsxRuntimeExports.jsxs("div", { className: "moss-theme-row", children: [
        jsxRuntimeExports.jsx("span", { className: "moss-theme-label", children: "主配色" }),
        jsxRuntimeExports.jsxs("div", { className: "moss-swatches", children: [
          swatches.map((color) => jsxRuntimeExports.jsx("button", {
            type: "button",
            title: color,
            className: picked === color ? "moss-swatch is-active" : "moss-swatch",
            style: { background: color },
            onClick: () => commit({ primary: color })
          }, color)),
          jsxRuntimeExports.jsxs("label", { className: "moss-swatch-custom", children: [
            jsxRuntimeExports.jsx("input", { type: "color", value: theme.primary || "#6a6ef6", onChange: (event) => commit({ primary: event.target.value }) }),
            jsxRuntimeExports.jsx("span", { children: "自定义" })
          ] }),
          jsxRuntimeExports.jsx("button", { type: "button", className: "moss-link", onClick: () => commit({ primary: "" }), children: "恢复默认" })
        ] })
      ] })
    ]
  });
}
`;
    if (!source.includes('function App() {')) throw new Error('App() anchor missing for SettingsTheme');
    source = source.replace('function App() {', themeComponent + '\nfunction App() {');
  }
  const themeSectionRef = 'jsxRuntimeExports.jsx(SettingsTheme, {})';
  // 外观区放设置页最上方（在语言之前）：先清掉旧版注入在容器末尾的引用，再插到容器开头
  source = source.replace(', ' + themeSectionRef + '] });', '] });');
  if (!source.includes(themeSectionRef)) {
    const containerOpen = 'jsxRuntimeExports.jsxs("div", { style: { padding: 50 }, children: [';
    if (source.split(containerOpen).length !== 2) throw new Error('settings container open anchor mismatch (theme section)');
    source = source.replace(containerOpen, containerOpen + themeSectionRef + ', ');
  }

  // ---------------- 顶栏服务链接：显示后端地址，点击用系统浏览器打开 ----------------
  // 端口是动态的（checkPort 返回 http://127.0.0.1:<port>/），所以组件挂载后自己探测；
  // 后端还没起来时先不渲染，起来后（每 2s 重试）再出现。
  if (!source.includes('function MossServiceLink() {')) {
    const serviceComponent = `
function MossServiceLink() {
  const linkState = reactExports.useState("");
  const url = linkState[0];
  const setUrl = linkState[1];
  reactExports.useEffect(() => {
    let alive = true;
    let timer = null;
    const tick = async () => {
      try {
        const base = await window.api.checkPort();
        if (alive && base) { setUrl(base); return true; }
      } catch (_) {}
      return false;
    };
    tick().then((done) => {
      if (done || !alive) return;
      timer = setInterval(() => {
        tick().then((finished) => { if (finished && timer) { clearInterval(timer); timer = null; } });
      }, 2000);
    });
    return () => { alive = false; if (timer) clearInterval(timer); };
  }, []);
  if (!url) return null;
  // target="_blank" → 主进程 setWindowOpenHandler → shell.openExternal 用系统默认浏览器打开
  return jsxRuntimeExports.jsxs("a", {
    className: "moss-service-link",
    href: url,
    target: "_blank",
    rel: "noreferrer",
    title: url,
    children: [
      jsxRuntimeExports.jsx("span", { children: "打开网页版" }),
      jsxRuntimeExports.jsx("code", { children: url })
    ]
  });
}
`;
    if (!source.includes('function App() {')) throw new Error('App() anchor missing for MossServiceLink');
    source = source.replace('function App() {', serviceComponent + '\nfunction App() {');
  }
  if (!source.includes('jsxRuntimeExports.jsx(MossServiceLink, {})')) {
    const headLink = 'jsxRuntimeExports.jsx(HeadLink, {})';
    if (source.split(headLink).length !== 2) throw new Error('headBanner HeadLink anchor mismatch');
    source = source.replace(headLink, headLink + ',\n              jsxRuntimeExports.jsx(MossServiceLink, {})');
  }

  // Replace ALL previously injected runtimes, including duplicate copies.
  // 连同其后的换行一起吃掉，否则每次重建都会多留一个空行（字节不稳定的漂移）。
  const legacyRuntime = /;\(\(\) => \{\r?\n  const translations = [\s\S]*?\r?\n\}\)\(\);\r?\n?/g;
  const copies = [...source.matchAll(legacyRuntime)].length;
  if (alreadyLocalized && copies === 0) throw new Error('localization runtime anchor mismatch');
  source = source.replace(legacyRuntime, '');
  const renderAnchor = 'clientExports.createRoot(document.getElementById("root")).render(';
  const treeFnAnchor = 'window.__mossRenderTree = function () {';
  if (source.split(renderAnchor).length === 2) {
    source = source.replace(renderAnchor, localeRuntime + '\n' + renderAnchor);
  } else if (source.split(treeFnAnchor).length === 2) {
    // 已打过主题补丁的包：入口语句已被改写成树函数形式，锚点跟着换（重建必须幂等）
    source = source.replace(treeFnAnchor, localeRuntime + '\n' + treeFnAnchor);
  } else {
    throw new Error('renderer entry anchor mismatch');
  }

  // ---- 主题 1/3：写死的 antd token 改成运行时可变（ConfigProvider 仍在原处）----
  const tokenMarker = 'colorPrimary: (window.__mossTheme && window.__mossTheme.primary) || "#f77612"';
  if (!source.includes(tokenMarker)) {
    const tokenRe = /token: \{\s*colorPrimary: "#f77612"\s*\}/;
    if ((source.match(tokenRe) || []).length !== 1) throw new Error('ConfigProvider token anchor mismatch');
    source = source.replace(tokenRe,
      'token: Object.assign({ colorPrimary: (window.__mossTheme && window.__mossTheme.primary) || "#f77612" }, ' +
      '(window.__mossTheme && window.__mossTheme.dark) ? window.__mossThemeDarkTokens || {} : {})');
  }

  // ---- 主题 2/3：工作台 iframe 的 src 带上主题参数（暗色下不先白闪）----
  const srcMarker = 'window.__mossThemeQuery ? window.__mossThemeQuery() : ""';
  if (!source.includes(srcMarker)) {
    if ((source.match(/setSrc\(srcUrl\);/g) || []).length !== 1) throw new Error('workbench iframe src anchor mismatch');
    source = source.replace('setSrc(srcUrl);', 'setSrc(srcUrl + (' + srcMarker + '));');
  }

  // ---- 主题 3/3：根节点改成可重渲染的树函数，切换主题时让 ConfigProvider 重新求值 ----
  if (!source.includes(treeFnAnchor)) {
    const rootRe = /clientExports\.createRoot\(document\.getElementById\("root"\)\)\.render\(([\s\S]*?)\n\);/;
    const rootMatch = source.match(rootRe);
    if (!rootMatch) throw new Error('root render statement mismatch');
    source = source.replace(rootRe,
      'const __mossRoot = clientExports.createRoot(document.getElementById("root"));\n' +
      treeFnAnchor + '\n' +
      '  return (' + rootMatch[1] + ');\n' +
      '};\n' +
      'window.__mossRerenderTheme = function () { __mossRoot.render(__mossRenderTree()); };\n' +
      '__mossRoot.render(__mossRenderTree());');
  }

  // 设置页分隔线跟随主题（原是写死的浅色 #e8e8e8）
  const foldersBorder = 'style: { borderTop: "1px solid #e8e8e8", marginTop: 24, paddingTop: 20 }';
  if (source.includes(foldersBorder)) {
    source = source.replace(foldersBorder, 'style: { borderTop: "1px solid var(--moss-line, #e8e8e8)", marginTop: 24, paddingTop: 20 }');
  }

  // ---- 主题：外壳自带视图里的写死颜色 → 主题变量 ----
  // 不改这些的话，暗色下设置页/首页的画布与左侧菜单仍是白的（文字已变浅 ⇒ 直接看不见）。
  const shellColorPatches = [
    ['backgroundColor: "white"', 'backgroundColor: "var(--moss-page-bg, white)"', 2],
    ['background: "white"', 'background: "var(--moss-page-bg, white)"', 1],
    ['backgroundColor: "#f5f5f0"', 'backgroundColor: "var(--moss-menu-bg, #f5f5f0)"', 1],
    ['background: "#f5f5f5"', 'background: "var(--moss-soft, #f5f5f5)"', 2],
    ['background: "#f6ece4"', 'background: "var(--moss-stop-bg, #f6ece4)"', 2],
    ['color: "#937965"', 'color: "var(--moss-stop-fg, #937965)"', 1],
    ['border: "2px solid #937965"', 'border: "2px solid var(--moss-stop-fg, #937965)"', 1],
    ['color: "#1677ff"', 'color: "var(--moss-link, #1677ff)"', 9],
    ['? "#f77612" : ""', '? "var(--moss-primary, #f77612)" : ""', 1],
    ['color: "#f77612"', 'color: "var(--moss-primary, #f77612)"', 3]
  ];
  for (const [from, to, expected] of shellColorPatches) {
    if (source.includes(to)) continue;                                    // 已打过
    const found = source.split(from).length - 1;
    if (found === 0) continue;   // 锚点已被更早的补丁改写（例如变量名不同）：跳过，产物自检会兜底
    if (found !== expected) throw new Error(`shell color anchor "${from}" expected ${expected}, found ${found}`);
    source = source.split(from).join(to);
  }

  // 外壳样式表：主题块用哨兵包住 ⇒ 每次重建都整块替换（否则新增变量在旧包上不会生效）
  const stylesheets = fs.readdirSync(assets).filter((name) => /^index-.*\.css$/.test(name));
  if (stylesheets.length !== 1) throw new Error(`expected one renderer stylesheet, found ${stylesheets.length}`);
  const stylePath = path.join(assets, stylesheets[0]);
  let styleSource = fs.readFileSync(stylePath, 'utf8');
  styleSource = styleSource.replace(new RegExp('\\s*' + cssBegin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '[\\s\\S]*?' + cssEnd.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g'), '');
  styleSource = styleSource.replace(/\n\/\* ---- 主题设置区与暗色基础[\s\S]*$/, '');   // 旧版无哨兵的追加块
  fs.writeFileSync(stylePath, styleSource.replace(/\s+$/, '') + '\n' + themeCss, 'utf8');
  // 注入点前导空行归一化：组件与运行时的注入都会留一个换行，重复重建会累积成
  // 空行漂移（每次 +1~3 字节）。折叠后重建结果字节稳定。
  source = source.replace(/\n{3,}(function StemsTools\(\) \{)/g, '\n\n$1');
  source = source.replace(/\n{2,}(;\(\(\) => \{\n  const translations = )/g, '\n\n$1');
  // 产物自检：注入后的包必须仍包含外壳的关键组件，避免锚点漂移时静默打出坏包。
  for (const marker of ['function App() {', 'const ConfigSettings = () => {', 'window.setMossUiLanguage', 'moss-language-request', 'StemsTools',
    'window.setMossUiTheme', 'window.__mossRenderTree', 'window.__mossThemeDarkTokens', 'function SettingsTheme() {', 'settings-theme-section', 'moss-theme-request',
    'function MossServiceLink() {', 'jsxRuntimeExports.jsx(MossServiceLink, {})', 'moss-service-link', 'window.api.startDownloader',
    '必要组件未下载', '打开下载中心', '127.0.0.1:17990/api/downloads']) {
    if (!source.includes(marker)) throw new Error(`patched bundle lost "${marker}"`);
  }
  console.log(`Replaced ${copies} localization runtime(s) with one guarded observer; theme settings section + runtime theme tokens applied`);
  fs.writeFileSync(bundlePath, source, 'utf8');
  run(['pack', extracted, output]);
  console.log(`English UI option + translations packaged: ${output}`);
} finally {
  fs.rmSync(work, { recursive: true, force: true });
}
