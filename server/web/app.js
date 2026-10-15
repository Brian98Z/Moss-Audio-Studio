'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const t = (key, vars) => window.MossI18n.t(key, vars);

/* 示例文本：按语言填充，但只在用户没动过这个框时才重填 */
const SAMPLE_TEXTAREAS = { ttsdScript: 'ttsdScriptSample', sfxPrompt: 'sfxPromptSample' };
const presetApplied = {};
const presetTouched = {};

function applySampleText(id) {
  const area = $(`#${id}`);
  if (!area) return;
  const sample = t(SAMPLE_TEXTAREAS[id]);
  if (!presetTouched[id] && (!area.value.trim() || area.value === presetApplied[id])) area.value = sample;
  presetApplied[id] = sample;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
    ...options,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_) { data = { raw: text }; }
  if (!res.ok) {
    const detail = data && data.detail;
    if (res.status === 409 && detail && detail.code === 'need_asset' && detail.asset) throw new Error(`${detail.message || detail.asset} · ${t('needAssetLink', { url: `/downloads?need=${encodeURIComponent(detail.asset)}` })}`);
    if (res.status === 409 && detail && detail.error === 'need_env') throw new Error(`${detail.hint || '请在环境准备中安装依赖'} · 请在环境准备中安装依赖`);
    throw new Error((data && (typeof data.detail === 'string' ? data.detail : data.error)) || `${res.status} ${res.statusText}`);
  }
  return data;
}

/* ------------------------------------------------------------------ logging */
const logBox = $('#logs');
let logCount = 0;

function appendLog(entry) {
  const div = document.createElement('div');
  const level = entry.level && entry.level !== 'info' ? ` ${entry.level}` : '';
  div.className = level.trim();
  div.innerHTML = `<span class="t">${entry.time || ''}</span>${escapeHtml(entry.message || '')}`;
  logBox.appendChild(div);
  if (++logCount > 800) { logBox.removeChild(logBox.firstChild); logCount--; }
  logBox.scrollTop = logBox.scrollHeight;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

$('#clearLogs').addEventListener('click', () => { logBox.innerHTML = ''; logCount = 0; });

function connectEvents() {
  const es = new EventSource('/api/events');
  es.onmessage = (ev) => {
    try { appendLog(JSON.parse(ev.data)); } catch (_) { /* ignore */ }
  };
  es.onerror = () => { /* the browser reconnects automatically */ };
}

/* --------------------------------------------------------------------- tabs */
$$('.tab').forEach((btn) => {
  btn.addEventListener('click', () => {
    $$('.tab').forEach((b) => b.classList.toggle('active', b === btn));
    $$('.tabpane').forEach((pane) => pane.classList.toggle('hidden', pane.id !== `tab-${btn.dataset.tab}`));
  });
});

/* ----------------------------------------------------------------- speakers */
let speakers = [
  { tag: '[S1]', refPath: '', refText: '' },
  { tag: '[S2]', refPath: '', refText: '' },
];

/* 说话人卡片的提示文案：状态存在 speaker 对象里，语言切换后重渲染才不会丢。
   返回值会插入 innerHTML，因此这里的动态数据（文件名/错误/识别信息）一律转义。 */
function speakerNoteText(spk) {
  const note = spk.note || {};
  if (note.kind === 'uploading') return t('uploading');
  if (note.kind === 'uploadFailed') return t('uploadFailed', { error: escapeHtml(note.error) });
  if (note.kind === 'transcribing') return t('transcribing');
  if (note.kind === 'transcribed') return t('transcribeDone', { language: escapeHtml(note.language), duration: escapeHtml(note.duration), elapsed: escapeHtml(note.elapsed) });
  if (note.kind === 'transcribeEmpty') return t('transcribeEmpty', { duration: escapeHtml(note.duration) });
  if (note.kind === 'transcribeFailed') return t('transcribeFailed', { error: escapeHtml(note.error) });
  if (note.kind === 'needAudio') return t('uploadFirst');
  if (spk.refName) return t('fileInfo', { name: escapeHtml(spk.refName), size: escapeHtml(spk.refSize) });
  return spk.refPath ? escapeHtml(spk.refPath) : t('notUploaded');
}

function renderSpeakers() {
  const host = $('#speakers');
  host.innerHTML = '';
  speakers.forEach((spk, index) => {
    const wrap = document.createElement('div');
    wrap.className = 'speaker';
    wrap.innerHTML = `
      <div class="head">
        <strong>${t('speakerHead', { index: index + 1, tag: spk.tag })}</strong>
        <button class="small danger" data-remove="${index}">${t('remove')}</button>
      </div>
      <label class="field">
        <span>${t('speakerAudioLabel')}</span>
        <div class="row">
          <input type="file" accept="audio/*" data-file="${index}" />
          <button class="small" data-asr="${index}"${spk.refPath && !(spk.note && spk.note.kind === 'transcribing') ? '' : ' disabled'}>${t('transcribe')}</button>
        </div>
        <small class="status" data-fileinfo="${index}">${speakerNoteText(spk)}</small>
      </label>
      <label class="field">
        <span>${t('speakerTextLabel')}</span>
        <textarea rows="2" data-text="${index}" placeholder="${t('speakerTextPlaceholder', { tag: spk.tag })}">${escapeHtml(spk.refText)}</textarea>
      </label>`;
    host.appendChild(wrap);
  });

  $$('[data-file]', host).forEach((input) => {
    input.addEventListener('change', async (ev) => {
      const spk = speakers[Number(ev.target.dataset.file)];
      const file = ev.target.files[0];
      if (!spk || !file) return;
      spk.note = { kind: 'uploading' };
      renderSpeakers();
      try {
        const fd = new FormData();
        fd.append('files', file);
        const data = await api('/api/upload', { method: 'POST', body: fd });
        if (!speakers.includes(spk)) return;
        spk.refPath = data.files[0].path;
        spk.refName = data.files[0].name;
        spk.refSize = data.files[0].size_mb;
        spk.note = null;
      } catch (err) {
        if (!speakers.includes(spk)) return;
        spk.note = { kind: 'uploadFailed', error: err.message };
      }
      renderSpeakers();
    });
  });

  $$('[data-text]', host).forEach((input) => {
    input.addEventListener('input', (ev) => { speakers[Number(ev.target.dataset.text)].refText = ev.target.value; });
  });

  // 参考音频 → 逐字稿：本地 whisper-small（后端 /api/asr），识别结果直接填进逐字稿框
  $$('[data-asr]', host).forEach((btn) => {
    btn.addEventListener('click', async () => {
      const spk = speakers[Number(btn.dataset.asr)];
      if (!spk) return;
      if (!spk.refPath) { spk.note = { kind: 'needAudio' }; renderSpeakers(); return; }
      spk.note = { kind: 'transcribing' };
      renderSpeakers();
      try {
        const d = await api('/api/asr', { method: 'POST', body: JSON.stringify({ path: spk.refPath }) });
        if (!speakers.includes(spk)) return;
        spk.refText = d.text || '';
        spk.note = d.text
          ? { kind: 'transcribed', language: d.language, duration: d.duration, elapsed: d.elapsed }
          : { kind: 'transcribeEmpty', duration: d.duration };
      } catch (err) {
        if (!speakers.includes(spk)) return;
        spk.note = { kind: 'transcribeFailed', error: err.message };
      }
      renderSpeakers();
    });
  });

  $$('[data-remove]', host).forEach((btn) => {
    btn.addEventListener('click', () => {
      if (speakers.length <= 1) { alert(t('minSpeakerAlert')); return; }
      speakers.splice(Number(btn.dataset.remove), 1);
      speakers.forEach((s, i) => { s.tag = `[S${i + 1}]`; });
      renderSpeakers();
    });
  });

  const tagHost = $('#ttsdTags');
  tagHost.innerHTML = '';
  speakers.forEach((spk) => {
    const chip = document.createElement('button');
    chip.className = 'chip';
    chip.textContent = t('insertTag', { tag: spk.tag });
    chip.addEventListener('click', () => {
      const ta = $('#ttsdScript');
      const pos = ta.selectionStart;
      ta.value = `${ta.value.slice(0, pos)}${spk.tag} ${ta.value.slice(pos)}`;
      ta.focus();
    });
    tagHost.appendChild(chip);
  });
}

$('#addSpeaker').addEventListener('click', () => {
  if (speakers.length >= 5) { alert(t('maxSpeakerAlert')); return; }
  speakers.push({ tag: `[S${speakers.length + 1}]`, refPath: '', refText: '' });
  renderSpeakers();
});

/* --------------------------------------------------------------------- jobs */
async function followJob(jobId, { progress, status, results, modelKey, loadLabel }) {
  progress.classList.remove('hidden');
  let finished = false;
  while (!finished) {
    await new Promise((r) => setTimeout(r, 2000));
    let job;
    try { job = await api(`/api/jobs/${jobId}`); } catch (err) { status.textContent = t('jobQueryFailed', { error: err.message }); break; }
    status.className = 'status';
    status.textContent = t('jobProgress', { load: loadLabel || t('jobLabelGeneric'), status: job.status, elapsed: job.elapsed });
    if (job.status === 'done') {
      finished = true;
      status.className = 'status ok';
      status.textContent = t('jobDone', { elapsed: job.elapsed });
      progress.classList.add('hidden');
      if (job.result && job.result.outputs) renderResults(job.result.outputs, results);
      if (job.result && job.result.loaded === null && modelKey) { /* load job */ }
      refreshState();
    } else if (job.status === 'failed') {
      finished = true;
      status.className = 'status error';
      status.textContent = t('jobFailed', { error: job.error });
      progress.classList.add('hidden');
    }
  }
}

function renderResults(outputs, host) {
  host.innerHTML = '';
  outputs.forEach((out) => {
    const div = document.createElement('div');
    div.className = 'result';
    div.innerHTML = `
      <div class="meta">
        <span><b>${escapeHtml(out.name)}</b> · ${out.seconds}s · ${out.size_mb} MB</span>
        <a class="small" href="${out.path ? `/outputs/${encodeURIComponent(out.name)}` : '#'}" download>${t('download')}</a>
      </div>
      <audio controls preload="none" src="/outputs/${encodeURIComponent(out.name)}"></audio>`;
    host.appendChild(div);
  });
}

/* -------------------------------------------------------------- generation */
$('#ttsdRun').addEventListener('click', async () => {
  const status = $('#ttsdStatus');
  const progress = $('#ttsdProgress');
  const missing = speakers.filter((s) => !s.refPath);
  if (missing.length) { status.className = 'status error'; status.textContent = t('missingRef', { tags: missing.map((s) => s.tag).join(' ') }); return; }
  const emptyText = speakers.filter((s) => !s.refText.trim());
  if (emptyText.length) {
    if (!confirm(t('missingTranscript', { tags: emptyText.map((s) => s.tag).join(' ') }))) return;
  }
  status.className = 'status';
  status.textContent = t('submitting');
  try {
    const { job_id } = await api('/api/ttsd/generate', {
      method: 'POST',
      body: JSON.stringify({
        script: $('#ttsdScript').value,
        speakers: speakers.map((s) => ({ tag: s.tag, ref_text: s.refText, ref_audio: s.refPath })),
        max_minutes: Number($('#ttsdMinutes').value),
        seed: Number($('#ttsdSeed').value),
        temperature: Number($('#ttsdTemp').value),
        top_p: Number($('#ttsdTopP').value),
        top_k: Number($('#ttsdTopK').value),
        repetition_penalty: Number($('#ttsdRp').value),
        num_takes: Number($('#ttsdTakes').value),
      }),
    });
    await followJob(job_id, { progress, status, results: $('#ttsdResults'), loadLabel: t('jobLabelTtsd') });
  } catch (err) {
    status.className = 'status error';
    status.innerHTML = t('jobFailed', { error: err.message });
    progress.classList.add('hidden');
  }
});

$('#sfxRun').addEventListener('click', async () => {
  const status = $('#sfxStatus');
  const progress = $('#sfxProgress');
  status.className = 'status';
  status.textContent = t('submitting');
  try {
    const { job_id } = await api('/api/sfx/generate', {
      method: 'POST',
      body: JSON.stringify({
        prompt: $('#sfxPrompt').value,
        seconds: Number($('#sfxSeconds').value),
        seed: Number($('#sfxSeed').value),
        temperature: Number($('#sfxTemp').value),
        top_p: Number($('#sfxTopP').value),
        top_k: Number($('#sfxTopK').value),
        repetition_penalty: Number($('#sfxRp').value),
        num_takes: Number($('#sfxTakes').value),
      }),
    });
    await followJob(job_id, { progress, status, results: $('#sfxResults'), loadLabel: t('jobLabelSfx') });
  } catch (err) {
    status.className = 'status error';
    status.innerHTML = t('jobFailed', { error: err.message });
    progress.classList.add('hidden');
  }
});

$('#sfxChips').addEventListener('click', (ev) => {
  if (ev.target.classList.contains('chip')) {
    $('#sfxPrompt').value = ev.target.textContent;
    presetTouched.sfxPrompt = true;   // 点示例是用户的明确选择，切语言不得改回默认示例
  }
});

async function loadModel(key, statusEl, progressEl) {
  statusEl.className = 'status';
  statusEl.textContent = t('loadModelProgress', { key });
  const { job_id } = await api('/api/models/load', {
    method: 'POST',
    body: JSON.stringify({ key, quant: null }),
  });
  return followJob(job_id, { progress: progressEl, status: statusEl, results: document.createElement('div'), loadLabel: t('jobLabelModel') });
}

$('#ttsdLoad').addEventListener('click', () => {
  const status = $('#ttsdStatus');
  loadModel('ttsd', status, $('#ttsdProgress')).catch((err) => { status.className = 'status error'; status.textContent = err.message; });
});
$('#sfxLoad').addEventListener('click', () => {
  const status = $('#sfxStatus');
  loadModel('sfx', status, $('#sfxProgress')).catch((err) => { status.className = 'status error'; status.textContent = err.message; });
});

/* --------------------------------------- single speaker (MOSS-TTS clone) */
let cloneVoices = [];
let cloneRefPath = '';
let clonePresetText = '';
let cloneRefCustom = null;                 // 用户自传的参考音频（优先于音色列表）
let cloneRefNote = null;                   // null | {kind:'uploading'} | {kind:'uploadFailed', error}
let voiceListNote = { kind: 'default' };   // default | empty | failed

/* 音色列表/参考音色的状态文案：语言切换时重渲染，避免留下上一语言的提示 */
function renderCloneNotes() {
  const listInfo = $('#ttsVoiceInfo');
  if (voiceListNote.kind === 'failed') listInfo.textContent = t('voicesLoadFailedDetail', { error: voiceListNote.error });
  else if (voiceListNote.kind === 'empty') listInfo.textContent = t('voicesEmptyHint');
  else listInfo.textContent = t('ttsVoiceInfo');
  const refInfo = $('#ttsRefInfo');
  if (cloneRefNote && cloneRefNote.kind === 'uploading') refInfo.textContent = t('uploading');
  else if (cloneRefNote && cloneRefNote.kind === 'uploadFailed') refInfo.textContent = t('uploadFailed', { error: cloneRefNote.error });
  else if (cloneRefCustom) refInfo.textContent = t('refOverridden', { name: cloneRefCustom.name, size: cloneRefCustom.size });
  else if (cloneRefPath) refInfo.textContent = t('usingPresetVoice', { path: cloneRefPath });
  else refInfo.textContent = t('ttsRefInfo');
}

async function loadCloneVoices() {
  const select = $('#ttsVoice');
  try {
    const data = await api('/api/tts/voices');
    cloneVoices = data.voices || [];
  } catch (err) {
    select.innerHTML = `<option value="">${t('voicesLoadFailed')}</option>`;
    voiceListNote = { kind: 'failed', error: err.message };
    renderCloneNotes();
    return;
  }
  select.innerHTML = '';
  if (!cloneVoices.length) {
    select.innerHTML = `<option value="">${t('voicesEmpty')}</option>`;
    voiceListNote = { kind: 'empty' };
    renderCloneNotes();
    return;
  }
  cloneVoices.forEach((voice, index) => {
    const option = document.createElement('option');
    option.value = String(index);
    option.textContent = voice.name;
    select.appendChild(option);
  });
  voiceListNote = { kind: 'default' };
  applyCloneVoice(0);
}

function applyCloneVoice(index) {
  const voice = cloneVoices[index];
  if (!voice) return;
  cloneRefPath = voice.path;
  cloneRefCustom = null;
  cloneRefNote = null;
  const textarea = $('#ttsText');
  if (!textarea.value.trim() || textarea.value === clonePresetText) textarea.value = voice.text;
  clonePresetText = voice.text;
  renderCloneNotes();
  updateClonePreview(`/api/tts/voice-audio/${encodeURIComponent(voice.id)}`);
}

function updateClonePreview(src) {
  const host = $('#ttsVoicePreview');
  host.innerHTML = '';
  if (!src) return;
  const audio = document.createElement('audio');
  audio.controls = true;
  audio.preload = 'none';
  audio.src = src;
  audio.style.width = '100%';
  host.appendChild(audio);
}

$('#ttsVoice').addEventListener('change', (ev) => applyCloneVoice(Number(ev.target.value)));

$('#ttsRefFile').addEventListener('change', async (ev) => {
  const file = ev.target.files[0];
  if (!file) return;
  cloneRefNote = { kind: 'uploading' };
  renderCloneNotes();
  try {
    const fd = new FormData();
    fd.append('files', file);
    const data = await api('/api/upload', { method: 'POST', body: fd });
    cloneRefPath = data.files[0].path;
    cloneRefCustom = { name: data.files[0].name, size: data.files[0].size_mb };
    cloneRefNote = null;
    updateClonePreview('');
  } catch (err) {
    cloneRefNote = { kind: 'uploadFailed', error: err.message };
  }
  renderCloneNotes();
});

$('#ttsRun').addEventListener('click', async () => {
  const status = $('#ttsStatus');
  const progress = $('#ttsProgress');
  if (!cloneRefPath) { status.className = 'status error'; status.textContent = t('needVoiceOrRef'); return; }
  if (!$('#ttsText').value.trim()) { status.className = 'status error'; status.textContent = t('needText'); return; }
  status.className = 'status';
  status.textContent = t('submitting');
  try {
    const { job_id } = await api('/api/tts/generate', {
      method: 'POST',
      body: JSON.stringify({
        text: $('#ttsText').value,
        prompt_audio: cloneRefPath,
        num_takes: Number($('#ttsTakes').value),
        seconds: Number($('#ttsSeconds').value),
        language: $('#ttsLanguage').value,
        seed: Number($('#ttsSeed').value),
        temperature: Number($('#ttsTemp').value),
        top_p: Number($('#ttsTopP').value),
        top_k: Number($('#ttsTopK').value),
        repetition_penalty: Number($('#ttsRp').value),
      }),
    });
    await followJob(job_id, { progress, status, results: $('#ttsResults'), loadLabel: t('jobLabelTts') });
  } catch (err) {
    status.className = 'status error';
    status.innerHTML = t('jobFailed', { error: err.message });
    progress.classList.add('hidden');
  }
});

$('#ttsLoad').addEventListener('click', () => {
  const status = $('#ttsStatus');
  loadModel('tts', status, $('#ttsProgress')).catch((err) => { status.className = 'status error'; status.textContent = err.message; });
});

/* -------------------------------------- 音色设计（MOSS-VoiceGenerator 1.7B） */
$('#vgChips').addEventListener('click', (ev) => {
  if (ev.target.classList.contains('chip')) $('#vgInstruction').value = ev.target.textContent;
});

$('#vgRun').addEventListener('click', async () => {
  const status = $('#vgStatus');
  const progress = $('#vgProgress');
  if (!$('#vgInstruction').value.trim()) { status.className = 'status error'; status.textContent = t('needInstruction'); return; }
  if (!$('#vgText').value.trim()) { status.className = 'status error'; status.textContent = t('needText'); return; }
  status.className = 'status';
  status.textContent = t('submitting');
  try {
    const { job_id } = await api('/api/vg/generate', {
      method: 'POST',
      body: JSON.stringify({
        text: $('#vgText').value,
        instruction: $('#vgInstruction').value,
        num_takes: Number($('#vgTakes').value),
        seconds: Number($('#vgSeconds').value),
        language: $('#vgLanguage').value,
        seed: Number($('#vgSeed').value),
        temperature: Number($('#vgTemp').value),
        top_p: Number($('#vgTopP').value),
        top_k: Number($('#vgTopK').value),
        repetition_penalty: Number($('#vgRp').value),
      }),
    });
    await followJob(job_id, { progress, status, results: $('#vgResults'), loadLabel: t('jobLabelVg') });
  } catch (err) {
    status.className = 'status error';
    status.innerHTML = t('jobFailed', { error: err.message });
  }
});

$('#vgLoad').addEventListener('click', () => {
  const status = $('#vgStatus');
  loadModel('vg', status, $('#vgProgress')).catch((err) => { status.className = 'status error'; status.textContent = err.message; });
});

/* ------------------------------------------------------------------- state */
let lastState = null;

// 模型名（含中文描述）由服务端注册表提供；中文界面直接用注册表原文，
// 英文界面用本页词条，避免改动服务端 config.json 与 /api/state 的既有结构。
const MODEL_LABEL_KEYS = { ttsd: 'modelLabelTtsd', tts: 'modelLabelTts', vg: 'modelLabelVg', sfx: 'modelLabelSfx' };

function modelLabel(model) {
  const key = MODEL_LABEL_KEYS[model && model.key];
  if (!key || window.MossI18n.language !== 'english') return (model && model.label) || (model && model.key) || '';
  return t(key);
}

async function refreshState() {
  let st;
  try { st = await api('/api/state'); } catch (_) { return; }
  lastState = st;

  const badges = $('#badges');
  const loaded = st.loaded;
  const loadedKey = loaded && loaded.key;
  [['#ttsdRun', 'ttsd'], ['#ttsRun', 'tts'], ['#vgRun', 'vg'], ['#sfxRun', 'sfx']].forEach(([selector, key]) => {
    $(selector).style.display = loadedKey === key ? '' : 'none';
  });
  badges.innerHTML = `
    <span class="badge ${loaded ? 'ok' : 'warn'}">${loaded ? t('badgeLoaded', { label: escapeHtml(modelLabel(loaded)), quant: loaded.quant }) : t('badgeNoModel')}</span>
    <span class="badge">${t('badgeVram', { used: st.memory.vram_used_gb ?? '-', total: st.memory.vram_total_gb ?? '-' })}</span>`;

  const rows = $('#modelRows');
  rows.innerHTML = '';
  st.models.forEach((m) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><b>${escapeHtml(modelLabel(m))}</b><div class="mono">${escapeHtml(m.path)}</div></td>
      <td>${m.exists ? (m.loaded ? `<span class="badge ok">${t('modelLoaded')}</span>` : `<span class="badge">${t('modelNotLoaded')}</span>`) : `<span class="badge danger">${t('modelMissing')}</span>`}</td>
      <td>${m.quant ? escapeHtml(m.quant) : (m.quants && m.quants.length ? `${t('quantWillUse', { quant: escapeHtml(m.quants[0]) })}${m.quant_checkpoint ? `<div class="mono">${escapeHtml(String(m.quant_checkpoint).split(/[\\/]/).pop())}</div>` : ''}` : `<span class="badge danger">${t('quantNone')}</span>`)}</td>
      <td>${Number(m.size_gb).toFixed(2)} GB</td>
      <td></td>`;
    const cell = tr.lastElementChild;
    const loadBtn = document.createElement('button');
    loadBtn.className = 'small';
    loadBtn.textContent = m.loaded ? t('reload') : t('load');
    loadBtn.disabled = !m.exists;
    loadBtn.addEventListener('click', async () => {
      const status = $('#modelStatus');
      const quants = m.quants || [];
      if (!quants.length) {
        status.className = 'status error';
        status.textContent = t('noQuantAvailable', { label: modelLabel(m) });
        return;
      }
      // 默认用第一档 = 已优化的落盘产物（int8 + no-head 权重）；只有多档时才弹选择，且默认仍是它。
      const quant = quants.length === 1
        ? quants[0]
        : prompt(t('quantPrompt', { choices: quants.join(' / '), recommended: quants[0] }), quants[0]);
      if (!quant || !quants.includes(quant)) return;
      status.className = 'status';
      status.textContent = t('loadingModel', { label: modelLabel(m), quant });
      const { job_id } = await api('/api/models/load', { method: 'POST', body: JSON.stringify({ key: m.key, quant }) });
      await followJob(job_id, { progress: $('#modelsProgress'), status, results: document.createElement('div'), loadLabel: t('jobLabelModel') });
      refreshState();
    });
    cell.appendChild(loadBtn);
    if (m.loaded) {
      const unBtn = document.createElement('button');
      unBtn.className = 'small danger';
      unBtn.style.marginLeft = '8px';
      unBtn.textContent = t('unload');
      unBtn.addEventListener('click', async () => { await api('/api/models/unload', { method: 'POST', body: JSON.stringify({}) }); refreshState(); });
      cell.appendChild(unBtn);
    }
    rows.appendChild(tr);
  });
  const codecInfo = st.codec && st.codec.size_gb != null ? t('codecInfo', { size: Number(st.codec.size_gb).toFixed(2) }) : '';
  $('#memInfo').textContent = t('memInfo', { used: st.memory.ram_used_gb ?? '-', total: st.memory.ram_total_gb ?? '-', device: st.device, quant: st.default_quant }) + codecInfo;
  $('#outputDir').textContent = t('outputDir', { path: st.output_dir });

  refreshOutputs();
}

async function refreshOutputs() {
  let data;
  try { data = await api('/api/outputs'); } catch (_) { return; }
  const rows = $('#outputRows');
  rows.innerHTML = '';
  if (!data.items.length) {
    rows.innerHTML = `<tr><td colspan="4" class="status">${t('noOutputs')}</td></tr>`;
    return;
  }
  data.items.forEach((item) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="mono">${escapeHtml(item.name)}</td>
      <td>${item.size_mb} MB</td>
      <td class="mono">${new Date(item.mtime * 1000).toLocaleString()}</td>
      <td></td>`;
    const cell = tr.lastElementChild;
    const audio = document.createElement('audio');
    audio.controls = true;
    audio.preload = 'none';
    audio.src = item.url;
    audio.style.width = '210px';
    const del = document.createElement('button');
    del.className = 'small danger';
    del.textContent = t('delete');
    del.addEventListener('click', async () => {
      if (!confirm(t('confirmDeleteOutput', { name: item.name }))) return;
      await api(`/api/outputs/${encodeURIComponent(item.name)}`, { method: 'DELETE' });
      refreshOutputs();
    });
    const actions = document.createElement('div');
    actions.className = 'output-actions';
    actions.appendChild(audio);
    actions.appendChild(del);
    cell.appendChild(actions);
    rows.appendChild(tr);
  });
}
$('#clearOutputs').addEventListener('click', async () => {
  const status = $('#outputStatus');
  if (!$('#outputRows audio')) {
    status.className = 'status';
    status.textContent = t('noOutputs');
    return;
  }
  if (!confirm(t('confirmClearOutputs'))) return;
  try {
    const result = await api('/api/outputs', { method: 'DELETE' });
    await refreshOutputs();
    status.className = 'status ok';
    status.textContent = t('clearedOutputs', { count: result.deleted, size: result.freed_mb });
  } catch (err) {
    status.className = 'status error';
    status.textContent = err.message;
  }
});


/* -------------------------------------------------------------------- init */
Object.keys(SAMPLE_TEXTAREAS).forEach((id) => {
  const area = $(`#${id}`);
  if (area) area.addEventListener('input', () => { presetTouched[id] = area.value !== presetApplied[id]; });
});

function applyLanguage() {
  window.MossI18n.applyStatic();
  Object.keys(SAMPLE_TEXTAREAS).forEach(applySampleText);
}

renderCloneNotes();
applyLanguage();
window.MossI18n.onLanguageChange(() => {
  applyLanguage();
  renderCloneNotes();
  if (speakers.length) renderSpeakers();
  if (lastState) refreshState();
});

renderSpeakers();
loadCloneVoices();
connectEvents();
refreshState();
setInterval(refreshState, 8000);
api('/api/health').catch(() => {});
