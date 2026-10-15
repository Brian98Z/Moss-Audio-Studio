'use strict';
(() => {
  const $ = (s) => document.querySelector(s);
  const t = (key, vars) => window.MossI18n.t(key, vars);
  const selected = new Set();
  const need = new URLSearchParams(location.search).get('need');
  let items = [];
  let timer = null;
  const esc = (s) => String(s || '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // 被工作台设置页以内嵌 iframe 打开时切到紧凑样式（去掉重复页头/返回链接与外层留白）。
  if (window.self !== window.top) {
    document.documentElement.classList.add('embedded');
    document.body.classList.add('embedded');
  }
  const bytes = (n) => { if (!Number.isFinite(n)) return '—'; const units = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0; while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; } return `${n.toFixed(i ? 2 : 0)} ${units[i]}`; };
  const relativeTarget = (target, root) => {
    const absolute = String(target || '').replace(/\\/g, '/');
    const base = String(root || '').replace(/\\/g, '/').replace(/\/+$/, '');
    const foldedAbsolute = absolute.toLowerCase();
    const foldedBase = base.toLowerCase();
    if (foldedAbsolute === foldedBase) return '.';
    if (foldedAbsolute.startsWith(foldedBase + '/')) return absolute.slice(base.length + 1);
    return null;
  };
  const targetDisplay = (target, root) => {
    const relative = relativeTarget(target, root);
    return relative == null
      ? `<code class="download-path" title="${esc(target || '')}">${esc(t('downloadsOutsideRoot'))}: ${esc(target || '')}</code>`
      : `<code class="download-path" title="${esc(target || '')}">${esc(relative)}</code>`;
  };
  async function request(path, options) {
    const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
    const data = await res.json();
    if (!res.ok) {
      // 工作台的缺件错误是结构化 detail 对象（{code, asset, message}），别直接 String() 成 [object Object]
      const d = data.detail;
      const msg = d && typeof d === 'object' ? (d.message || d.code || JSON.stringify(d)) : (d || data.error || `${res.status} ${res.statusText}`);
      throw new Error(msg);
    }
    return data;
  }
  function render() {
    for (const group of ['required', 'optional']) {
      const host = $(`#${group === 'required' ? 'requiredItems' : 'optionalItems'}`);
      host.innerHTML = '';
      items.filter((item) => item.group === group).forEach((item) => {
        const card = document.createElement('article');
        card.className = `download-card${item.id === need ? ' preselected' : ''}`;
        const label = window.MossI18n.language === 'english' ? (item.label_en || item.label) : item.label;
        const fraction = item.bytes ? Math.min(100, Math.floor((item.done_bytes || 0) * 100 / item.bytes)) : 0;
        const speedEta = item.status === 'running' ? `${bytes(item.speed_bps || 0)}/s · ${item.eta_s == null ? '—' : `${item.eta_s}s`}` : '';
        // 成功标识：下载完成即已逐文件校验过；已存在但未校验的给「未校对 + 校对按钮」
        const badge = item.status === 'verifying'
          ? `<span class="badge verifying">${esc(t('downloadsVerifying'))} ${fraction}%</span>`
          : item.verified === false
            ? `<span class="badge bad">${esc(t('downloadsVerifyFailed'))}</span>`
            : item.present
              ? (item.verified ? `<span class="badge ok">✓ ${esc(t('downloadsVerified'))}</span>` : `<span class="badge warn">${esc(t('downloadsUnverified'))}</span>`)
              : `<span class="badge">${esc(item.status)}</span>`;
        const actions = item.status === 'error'
          ? `<button type="button" data-retry="${esc(item.id)}">${esc(t('downloadsRetry'))}</button>`
          : (item.present && item.status !== 'verifying' ? `<button type="button" data-verify="${esc(item.id)}">${esc(t('downloadsVerify'))}</button>` : '');
        // 已落盘的条目不显示"上次失败下载"的残留进度；体积与下载包不同时同时给出两个数。
        const busy = item.status === 'running' || item.status === 'queued' || item.status === 'verifying';
        const presentLine = item.present
          ? ' · ' + (item.shared_only
            ? esc(t('downloadsPresentShared'))
            : esc(t('downloadsPresent', { size: bytes(item.present_bytes) })))
          : '';
        const activity = item.present && !busy
          ? (item.error ? `<div class="download-meta"><span class="error">${esc(item.error)}</span></div>` : '')
          : `<progress max="100" value="${fraction}"></progress><div class="download-meta"><span>${bytes(item.done_bytes || 0)} / ${bytes(item.bytes)}</span><span class="error">${esc(item.error || '')}</span></div>`;
        card.innerHTML = `<header><label><input type="checkbox" data-select="${esc(item.id)}" ${selected.has(item.id) ? 'checked' : ''} ${item.present ? 'disabled' : ''}><strong>${esc(label)}</strong></label><span class="download-figures"><span>${esc(t('downloadsPackageSize', { size: bytes(item.bytes) }))}</span>${targetDisplay(item.target, window.downloadRoot)}</span></header><p class="download-notes">${esc(item.notes || '')}</p><div class="download-meta"><span>${badge}${presentLine}</span><span>${esc(speedEta)}</span></div>${activity}${actions}`;
        host.appendChild(card);
      });
    }
    const total = items.filter((item) => selected.has(item.id) && !item.present).reduce((sum, item) => sum + (item.bytes || 0), 0);
    $('#selectedTotal').textContent = bytes(total);
    $('#diskFree').textContent = window.diskFree == null ? '' : ` · ${t('downloadsDiskFree', { size: bytes(window.diskFree) })}`;
    const target = items.find((item) => item.id === need);
    const notice = $('#needNotice');
    if (target) { notice.classList.remove('hidden'); notice.innerHTML = esc(t('downloadsNeed', { label: window.MossI18n.language === 'english' ? target.label_en || target.label : target.label, cause: target.enables && target.enables.join(', ') })); }
  }
  async function refresh() {
    try {
      const data = await request('/api/downloads');
      window.downloadRoot = (data.disk && data.disk.root) || '';
      window.diskFree = data.disk && data.disk.free_bytes;
      $('#downloadRoot').textContent = window.downloadRoot || '—';
      items = (data.items || []).map((item) => ({ ...item, relative_target: relativeTarget(item.target, window.downloadRoot) }));
      if (need && items.some((item) => item.id === need && !item.present)) selected.add(need);
      render();
    } catch (err) { $('#downloadMessage').textContent = err.message; }
  }
  function schedule() { if (document.hidden) { clearInterval(timer); timer = null; return; } if (!timer) { refresh(); timer = setInterval(refresh, 1000); } }
  document.addEventListener('visibilitychange', schedule);
  $('#selectAll').addEventListener('click', () => { items.filter((x) => !x.present).forEach((x) => selected.add(x.id)); render(); });
  $('#selectNone').addEventListener('click', () => { selected.clear(); render(); });
  document.addEventListener('change', (ev) => { if (ev.target.matches('[data-select]')) { const id = ev.target.dataset.select; ev.target.checked ? selected.add(id) : selected.delete(id); render(); } });
  document.addEventListener('click', async (ev) => {
    const retry = ev.target.closest('[data-retry]');
    const verify = ev.target.closest('[data-verify]');
    if (!retry && !verify) return;
    const id = (retry || verify).dataset[retry ? 'retry' : 'verify'];
    try {
      if (retry) {
        selected.add(id);
        await request('/api/downloads/start', { method: 'POST', body: JSON.stringify({ ids: [id] }) });
        $('#downloadMessage').textContent = t('downloadsStarted');
      } else {
        await request('/api/downloads/verify', { method: 'POST', body: JSON.stringify({ ids: [id] }) });
        $('#downloadMessage').textContent = t('downloadsVerifying');
      }
      await refresh();
    } catch (err) { $('#downloadMessage').textContent = err.message; }
  });
  $('#startDownloads').addEventListener('click', async () => { try { const result = await request('/api/downloads/start', { method: 'POST', body: JSON.stringify({ ids: [...selected] }) }); $('#downloadMessage').textContent = `${t('downloadsStarted')}: ${(result.started || []).join(', ')}`; await refresh(); } catch (err) { $('#downloadMessage').textContent = err.message; } });
  $('#cancelDownloads').addEventListener('click', async () => { try { await request('/api/downloads/cancel', { method: 'POST', body: JSON.stringify({ ids: [...selected] }) }); await refresh(); } catch (err) { $('#downloadMessage').textContent = err.message; } });
  $('#verifyDownloads').addEventListener('click', async () => {
    const ids = items.filter((item) => item.present).map((item) => item.id);
    if (!ids.length) { $('#downloadMessage').textContent = t('downloadsNothingToVerify'); return; }
    try {
      await request('/api/downloads/verify', { method: 'POST', body: JSON.stringify({ ids }) });
      $('#downloadMessage').textContent = t('downloadsVerifying');
      await refresh();
    } catch (err) { $('#downloadMessage').textContent = err.message; }
  });
  window.MossI18n.onLanguageChange(render);
  schedule();
})();
