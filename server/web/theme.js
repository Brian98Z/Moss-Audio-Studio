/* theme.js — 界面主题：浅色 / 暗黑 + 用户自定义主配色
 *
 * 语言只有“切换”，主题还要跟系统偏好走，故与 i18n.js 分开成独立模块。
 *
 * 取值优先级（与 i18n.js 一致：外壳消息 > URL 参数 > 本地缓存 > 默认）：
 *   1. 外壳（Electron）广播的 {type:'moss-theme', mode, primary} —— 客户端内的权威来源；
 *   2. URL 查询参数 ?theme=dark&primary=1677ff —— 独立打开（浏览器/接口调用）时用；
 *   3. localStorage 缓存 —— 同一页面重载后不闪回默认色；
 *   4. 默认：mode=dark，primary 留空（用样式表里的 --accent：蓝紫 #6a6ef6）。
 *
 * 落地方式：在 <html> 上写 data-theme="light|dark"（CSS 变量按此切换），
 * 并把主色及其派生色写到 :root 的 CSS 变量上（见 index.html 的变量定义）。
 */
(() => {
  const STORAGE_KEY = 'moss-theme';
  const MODES = ['light', 'dark', 'system'];
  const DEFAULT_MODE = 'dark';
  // 未设置主色时留空：外壳用 antd 自己的默认主色、页面用样式表里的默认 --accent
  // （即“什么都不改”= 与今天完全一致），用户一旦选了颜色再统一覆盖两边。
  const HEX = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i;

  const normalizeMode = (value) => (MODES.includes(value) ? value : null);

  const normalizePrimary = (value) => {
    if (typeof value !== 'string') return null;
    const raw = value.trim();
    if (!HEX.test(raw)) return null;
    let hex = raw.replace('#', '').toLowerCase();
    if (hex.length === 3) hex = hex.split('').map((c) => c + c).join('');
    return '#' + hex;
  };

  const clamp = (n) => Math.max(0, Math.min(255, Math.round(n)));

  const parseHex = (hex) => ({
    r: parseInt(hex.slice(1, 3), 16),
    g: parseInt(hex.slice(3, 5), 16),
    b: parseInt(hex.slice(5, 7), 16),
  });

  const toHex = ({ r, g, b }) =>
    '#' + [r, g, b].map((v) => clamp(v).toString(16).padStart(2, '0')).join('');

  // 主色的派生：hover/按下更暗、柔和底更浅；文字色按亮度取黑或白。
  const mix = (hex, target, ratio) => {
    const a = parseHex(hex);
    const b = parseHex(target);
    return toHex({
      r: a.r + (b.r - a.r) * ratio,
      g: a.g + (b.g - a.g) * ratio,
      b: a.b + (b.b - a.b) * ratio,
    });
  };

  const luminance = (hex) => {
    const { r, g, b } = parseHex(hex);
    const f = (v) => (v / 255 <= 0.03928 ? v / 255 / 12.92 : Math.pow((v / 255 + 0.055) / 1.055, 2.4));
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };

  const readCache = () => {
    try {
      const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      return { mode: normalizeMode(raw.mode), primary: normalizePrimary(raw.primary) };
    } catch (_) {
      return { mode: null, primary: null };
    }
  };

  const writeCache = (state) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (_) {
      /* 隐私模式下写不进也无所谓 */
    }
  };

  const readUrl = () => {
    try {
      const params = new URLSearchParams(window.location.search);
      return {
        mode: normalizeMode(params.get('theme')),
        primary: normalizePrimary(params.get('primary')),
      };
    } catch (_) {
      return { mode: null, primary: null };
    }
  };

  const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  const cached = readCache();
  const fromUrl = readUrl();
  const state = {
    mode: fromUrl.mode || cached.mode || DEFAULT_MODE,
    primary: fromUrl.primary || cached.primary || null,
  };
  const listeners = new Set();

  /** 把 mode=system 解析成实际明暗 */
  const resolve = () => (state.mode === 'system' ? (media && media.matches ? 'dark' : 'light') : state.mode);

  const ACCENT_VARS = ['--accent', '--accent-rgb', '--accent-strong', '--accent-weak', '--accent-soft', '--accent-fg'];

  const apply = () => {
    const root = document.documentElement;
    root.dataset.theme = resolve();
    root.dataset.themeMode = state.mode;
    if (state.primary) {
      const p = parseHex(state.primary);
      const dark = resolve() === 'dark';
      // 亮底上“更强”= 压暗，暗底上“更强”= 提亮（同一个变量被两套主题复用）
      root.style.setProperty('--accent', state.primary);
      root.style.setProperty('--accent-rgb', `${p.r}, ${p.g}, ${p.b}`);
      root.style.setProperty('--accent-strong', dark ? mix(state.primary, '#ffffff', 0.3) : mix(state.primary, '#000000', 0.18));
      root.style.setProperty('--accent-weak', dark ? mix(state.primary, '#ffffff', 0.55) : mix(state.primary, '#000000', 0.32));
      root.style.setProperty('--accent-soft', `rgba(${p.r}, ${p.g}, ${p.b}, ${dark ? 0.22 : 0.12})`);
      root.style.setProperty('--accent-fg', luminance(state.primary) > 0.55 ? '#111111' : '#ffffff');
    } else {
      // 未自定义主色 ⇒ 交还给样式表的默认值（明暗两套各自写在自己的变量块里）
      ACCENT_VARS.forEach((name) => root.style.removeProperty(name));
    }
    document.dispatchEvent(new CustomEvent('moss-theme-change', { detail: { mode: state.mode, resolved: resolve(), primary: state.primary } }));
    listeners.forEach((fn) => {
      try {
        fn({ mode: state.mode, resolved: resolve(), primary: state.primary });
      } catch (_) {
        /* 订阅者自己出错不影响主题 */
      }
    });
  };

  /** 合并式设置；清空主色请显式传 primary:'' */
  const set = (patch, options = {}) => {
    const mode = normalizeMode(patch && patch.mode);
    let changed = false;
    if (mode && mode !== state.mode) {
      state.mode = mode;
      changed = true;
    }
    if (patch && Object.prototype.hasOwnProperty.call(patch, 'primary')) {
      const primary = normalizePrimary(patch.primary);
      const clearing = primary === null && (patch.primary === '' || patch.primary === null);
      if (primary && primary !== state.primary) {
        state.primary = primary;
        changed = true;
      } else if (clearing && state.primary !== null) {
        state.primary = null;
        changed = true;
      }
    }
    if (!changed) return false;
    writeCache(state);
    apply();
    return true;
  };

  apply();

  // 跟随系统：只在 mode=system 时对系统明暗变化做响应
  if (media) {
    const onSystemChange = () => {
      if (state.mode === 'system') apply();
    };
    if (media.addEventListener) media.addEventListener('change', onSystemChange);
    else if (media.addListener) media.addListener(onSystemChange);
  }

  // 外壳广播（客户端内唯一权威来源）
  window.addEventListener('message', (event) => {
    const data = event.data;
    if (!data || data.type !== 'moss-theme') return;
    set({ mode: data.mode, primary: data.primary });
  });

  // 主动向父窗口（外壳）要一次：URL 参数缺失时也能拿到当前主题
  try {
    if (window.parent && window.parent !== window) window.parent.postMessage({ type: 'moss-theme-request' }, '*');
  } catch (_) {
    /* 跨窗口不可达就算了，URL/缓存兜底 */
  }

  // 独立打开时（无外壳）也把首帧结果缓存下来，避免刷新闪一下默认色
  if (fromUrl.mode || fromUrl.primary) writeCache(state);

  window.MossTheme = {
    get: () => ({ mode: state.mode, resolved: resolve(), primary: state.primary }),
    set: (patch) => set(patch),
    /** 立即刷新（外部改了 CSS 变量后需要） */
    apply,
    /** 订阅变更，返回取消订阅函数 */
    on: (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    MODES: MODES.slice(),
    // 预设色板：外壳设置页与这里共用同一组，避免两边对不上
    SWATCHES: ['#6a6ef6', '#1677ff', '#13c2c2', '#52c41a', '#fa8c16', '#eb2f96', '#722ed1', '#f5222d'],
  };
})();
