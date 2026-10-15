'use strict';

(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const elements = {
    input: $('#file-input'), drop: $('#drop-zone'), browse: $('#browse-button'), summary: $('#file-summary'),
    filename: $('#file-name'), filesize: $('#file-size'), remove: $('#remove-file'), separate: $('#separate-button'),
    progress: $('#progress-panel'), progressTitle: $('#progress-title'), progressFill: $('#progress-fill'),
    progressPercent: $('#progress-percent'), progressMessage: $('#progress-message'), error: $('#error-box'),
    errorMessage: $('#error-message'), retry: $('#retry-button'), results: $('#results-panel'),
    summaryResult: $('#result-summary'), originalAudio: $('#original-audio'), originalFilename: $('#original-filename'),
    grid: $('#stem-grid'), zip: $('#zip-button'), newTask: $('#new-task'),
  };

  const translations = {
    chinese: {
      local: '本地处理',
      stepUpload: '选择音频', uploadTitle: '导入一段混音', formatNote: 'WAV · MP3 · FLAC · M4A', dropTitle: '拖放音频到这里', dropOr: '或', browse: '浏览文件', dropHint: '支持常见音频格式 · 建议使用 WAV 获得最佳效果', removeFile: '移除文件', privacy: '音频仅在本机处理', separate: '分离音轨', separateAgain: '重新分离', stepProcess: '正在分离', working: '正在聆听每一层声音', preparing: '正在准备音轨分离…', retry: '重试', stepResults: '你的音轨', resultsTitle: '六条独立音轨，已准备好。', downloadAll: '下载全部 ZIP', original: '原始混音', newTask: '分离另一段音频',
      guideLabel: '六轨分离说明', vocals: '人声', vocalsDesc: '主唱与背景人声', drums: '鼓组', drumsDesc: '鼓、镲片与打击乐', bass: '贝斯', bassDesc: '低音贝斯线', guitar: '吉他', guitarDesc: '吉他声部', piano: '钢琴', pianoDesc: '钢琴与键盘声部', other: '其他伴奏', otherDesc: '除以上声部外的剩余伴奏', guideNote: '“其他伴奏”是剩余混合声部，并非单独旋律轨。', takesTime: '处理需要一些时间', timeNote: '音轨分离在本机运行。较长的音频可能需要几分钟，请保持此页面开启。', footerLeft: 'DEMUCS · 本地六轨音频分离', footerRight: '你的音频不会离开这台设备。',
      invalidFile: '请选择有效的音频文件。', uploadError: '上传失败', requestError: '无法开始音轨分离', jobError: '分离失败', jobUnavailable: '任务状态暂时无法获取，请检查连接后重试。', statusPending: '任务正在排队…', statusRunning: '正在分离六条音轨…', statusDone: '音轨已完成', duration: '时长', sampleRate: '采样率', noOutputs: '分离已完成，但没有返回音轨文件。',
      stemNames: { vocals: '人声', drums: '鼓组', bass: '贝斯', guitar: '吉他', piano: '钢琴', other: '其他伴奏' }, stemDesc: { vocals: '主唱与背景人声', drums: '鼓、镲片与打击乐', bass: '低音贝斯线', guitar: '吉他声部', piano: '钢琴与键盘声部', other: '剩余伴奏混合声部' }, download: '下载 WAV',
    },
    english: {
      local: 'LOCAL PROCESSING',
      stepUpload: 'SELECT AUDIO', uploadTitle: 'Bring in a full mix', formatNote: 'WAV · MP3 · FLAC · M4A', dropTitle: 'Drop an audio file here', dropOr: 'or', browse: 'browse files', dropHint: 'Common audio formats supported · WAV recommended for best results', removeFile: 'Remove file', privacy: 'Audio stays on this device', separate: 'Separate stems', separateAgain: 'Separate again', stepProcess: 'SEPARATING', working: 'Listening to every layer', preparing: 'Preparing stem separation…', retry: 'Retry', stepResults: 'YOUR STEMS', resultsTitle: 'Six individual stems, ready.', downloadAll: 'Download ZIP', original: 'Original mix', newTask: 'Separate another track',
      guideLabel: 'The six stems', vocals: 'Vocals', vocalsDesc: 'Lead and backing vocals', drums: 'Drums', drumsDesc: 'Drums, cymbals and percussion', bass: 'Bass', bassDesc: 'Low-end bass line', guitar: 'Guitar', guitarDesc: 'Guitar parts', piano: 'Piano', pianoDesc: 'Piano and keyboard parts', other: 'Other accompaniment', otherDesc: 'Remaining accompaniment beyond the stems above', guideNote: '“Other accompaniment” is a residual mix, not an isolated melody track.', takesTime: 'Separation takes a little time', timeNote: 'Stems are separated on this device. Longer tracks may take a few minutes; please keep this page open.', footerLeft: 'DEMUCS · LOCAL SIX-STEM SEPARATION', footerRight: 'Your audio never leaves this device.',
      invalidFile: 'Choose a valid audio file.', uploadError: 'Upload failed', requestError: 'Could not start stem separation', jobError: 'Separation failed', jobUnavailable: 'The job status is temporarily unavailable. Check your connection and retry.', statusPending: 'Job queued…', statusRunning: 'Separating six stems…', statusDone: 'Stems are ready', duration: 'Duration', sampleRate: 'Sample rate', noOutputs: 'Separation finished, but no stem files were returned.',
      stemNames: { vocals: 'Vocals', drums: 'Drums', bass: 'Bass', guitar: 'Guitar', piano: 'Piano', other: 'Other accompaniment' }, stemDesc: { vocals: 'Lead and backing vocals', drums: 'Drums, cymbals and percussion', bass: 'Low-end bass line', guitar: 'Guitar parts', piano: 'Piano and keyboard parts', other: 'Residual accompaniment mix' }, download: 'Download WAV',
    },
  };
  const vocalMode = new URLSearchParams(location.search).get('mode') === 'vocals';
  for (const [locale, label] of [['chinese', '伴奏'], ['english', 'Instrumental']]) {
    translations[locale].stemNames.instrumental = label;
    if (vocalMode) Object.assign(translations[locale], locale === 'english'
      ? { guideLabel: 'Vocal separation', resultsTitle: 'Vocals and instrumental', statusRunning: 'Separating vocals and instrumental…', working: 'Separating audio…', footerLeft: 'DEMUCS · VOCAL SEPARATION' }
      : { guideLabel: '人声分离', resultsTitle: '人声与伴奏', statusRunning: '正在分离人声与伴奏…', working: '正在分离音频…', footerLeft: 'DEMUCS · 人声分离' });
  }
  const stemOrder = vocalMode ? ['vocals', 'instrumental'] : ['vocals', 'drums', 'bass', 'guitar', 'piano', 'other'];
  const stemClass = { vocals: 'vocals', instrumental: 'other', drums: 'drums', bass: 'bass', guitar: 'guitar', piano: 'piano', other: 'other' };
  const stemInitial = { vocals: 'V', instrumental: 'I', drums: 'D', bass: 'B', guitar: 'G', piano: 'P', other: 'O' };
  let language = new URLSearchParams(location.search).get('language') === 'english' ? 'english' : 'chinese';
  let selectedFile = null;
  let uploadedPath = null;
  let originalUrl = null;
  let active = false;
  let pollTimer = 0;
  let progress = 0;
  let currentJobId = '';

  function t(key) { return translations[language][key] ?? key; }
  function setLanguage(next) {
    language = next === 'english' ? 'english' : 'chinese';
    document.documentElement.lang = language === 'english' ? 'en' : 'zh-CN';
    document.querySelector('.brand').href = '/tools?language=' + language;
    document.querySelector('#back-tools').href = '/tools?language=' + language;
    document.querySelector('#back-tools').textContent = language === 'english' ? '← Back to Tools' : '← 返回工具';
    document.querySelectorAll('[data-i18n]').forEach((node) => {
      const value = t(node.dataset.i18n);
      if (value.includes('<')) node.innerHTML = value;
      else node.textContent = value;
    });
    if (vocalMode) {
      document.querySelector('.guide-list').hidden = true;
      document.querySelector('.guide-footnote').textContent = language === 'english' ? 'Two outputs: vocals and instrumental accompaniment.' : '输出两轨：人声与伴奏。';
    }
    document.querySelectorAll('[data-i18n-aria]').forEach((node) => node.setAttribute('aria-label', t(node.dataset.i18nAria)));
    if (selectedFile) elements.separate.querySelector('span').textContent = active ? t('working') : currentJobId ? t('separateAgain') : t('separate');
    if (window.__mossStemsResult && elements.results.hidden === false) updateResultLabels(window.__mossStemsResult);
  }
  window.addEventListener('message', (event) => {
    if (event.source === parent && event.data?.type === 'moss-language') setLanguage(event.data.language);
  });

  function formatSize(bytes) {
    if (bytes < 1_000_000) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / 1_000_000).toFixed(1)} MB`;
  }
  function setFile(file) {
    if (!file) return;
    if (active) return;
    if (!file.type.startsWith('audio/') && !/\.(wav|mp3|flac|m4a|ogg|aac|aiff?)$/i.test(file.name)) {
      elements.progress.hidden = true;
      showError(t('invalidFile'));
      return;
    }
    selectedFile = file;
    uploadedPath = null;
    currentJobId = '';
    elements.filename.textContent = file.name;
    elements.filesize.textContent = formatSize(file.size);
    elements.summary.hidden = false;
    elements.drop.hidden = true;
    elements.separate.disabled = false;
    elements.separate.querySelector('span').textContent = t('separate');
    elements.progress.hidden = true;
    elements.error.hidden = true;
    elements.results.hidden = true;
    if (originalUrl) URL.revokeObjectURL(originalUrl);
    originalUrl = URL.createObjectURL(file);
    elements.originalAudio.src = originalUrl;
  }
  function clearFile() {
    if (active) return;
    selectedFile = null;
    uploadedPath = null;
    currentJobId = '';
    elements.input.value = '';
    elements.summary.hidden = true;
    elements.drop.hidden = false;
    elements.separate.disabled = true;
    elements.results.hidden = true;
    elements.progress.hidden = true;
    elements.error.hidden = true;
    if (originalUrl) URL.revokeObjectURL(originalUrl);
    originalUrl = null;
    elements.originalAudio.removeAttribute('src');
  }
  function showError(message) {
    elements.errorMessage.textContent = message;
    elements.error.hidden = false;
  }
  function updateProgress(value, message) {
    progress = Math.max(progress, Math.min(95, value));
    elements.progressFill.style.width = `${progress}%`;
    elements.progressPercent.textContent = `${Math.round(progress)}%`;
    if (message) elements.progressMessage.textContent = message;
  }
  async function parseResponse(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || data.error || `${response.status} ${response.statusText}`);
    return data;
  }
  async function uploadFile() {
    const form = new FormData();
    form.append('files', selectedFile);
    const response = await fetch('/api/upload', { method: 'POST', body: form });
    const data = await parseResponse(response);
    if (!data.files?.[0]?.path) throw new Error(t('uploadError'));
    return data.files[0].path;
  }
  async function startSeparation() {
    if (!selectedFile || active) return;
    active = true;
    elements.separate.disabled = true;
    elements.separate.classList.add('is-loading');
    elements.separate.querySelector('span').textContent = t('working');
    elements.progress.hidden = false;
    elements.progressTitle.textContent = t('working');
    elements.error.hidden = true;
    elements.results.hidden = true;
    progress = 0;
    updateProgress(3, t('preparing'));
    try {
      if (currentJobId) {
        await pollJob(currentJobId);
        return;
      }
      if (!uploadedPath) {
        updateProgress(8, t('preparing'));
        uploadedPath = await uploadFile();
      }
      updateProgress(12, t('statusPending'));
      const response = await fetch('/api/stems/separate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: uploadedPath, mode: vocalMode ? 'vocals' : 'six' }),
      });
      const data = await parseResponse(response);
      if (!data.job_id) throw new Error(t('requestError'));
      currentJobId = data.job_id;
      await pollJob(currentJobId);
    } catch (error) {
      fail(error.message || t('requestError'));
    }
  }
  async function pollJob(jobId) {
    let attempts = 0;
    while (active) {
      await new Promise((resolve) => { pollTimer = window.setTimeout(resolve, attempts < 5 ? 700 : 1200); });
      if (!active) return;
      try {
        const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { cache: 'no-store' });
        const job = await parseResponse(response);
        attempts++;
        if (job.status === 'pending') updateProgress(Math.min(22, 12 + attempts * 2), t('statusPending'));
        else if (job.status === 'running') updateProgress(Math.round(100 * (job.params?.progress || 0)), t('statusRunning'));
        if (job.status === 'failed') {
          currentJobId = '';
          fail(job.error || t('jobError'));
          return;
        }
        if (job.status === 'done') {
          updateProgress(100, t('statusDone'));
          finish(job.result || {});
          return;
        }
        if (!['pending', 'running'].includes(job.status)) {
          currentJobId = '';
          fail(job.error || t('jobUnavailable'));
          return;
        }
      } catch (error) {
        fail(error.message || t('jobUnavailable'), true);
        return;
      }
    }
  }
  function fail(message, preserveJob = false) {
    active = false;
    window.clearTimeout(pollTimer);
    if (!preserveJob) currentJobId = '';
    elements.separate.disabled = false;
    elements.separate.classList.remove('is-loading');
    elements.separate.querySelector('span').textContent = currentJobId ? t('retry') : t('separate');
    elements.progressTitle.textContent = t('jobError');
    showError(message);
  }
  function finish(result) {
    active = false;
    elements.separate.classList.remove('is-loading');
    elements.progressTitle.textContent = t('statusDone');
    elements.separate.disabled = false;
    elements.separate.querySelector('span').textContent = t('separateAgain');
    if (!Array.isArray(result.outputs) || result.outputs.length === 0) {
      showError(t('noOutputs'));
      return;
    }
    window.__mossStemsResult = result;
    elements.originalFilename.textContent = selectedFile?.name || '';
    elements.progress.hidden = true;
    elements.results.hidden = false;
    renderResults(result);
    elements.results.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  function safeUrl(url) {
    try {
      const parsed = new URL(url, location.origin);
      return parsed.origin === location.origin ? parsed.href : '#';
    } catch (_) { return '#'; }
  }
  function updateResultLabels(result) {
    const outputs = result.outputs || [];
    const duration = Number(result.seconds);
    const rate = Number(result.sample_rate);
    const details = [];
    if (Number.isFinite(duration) && duration > 0) details.push(`${t('duration')} · ${Math.floor(duration / 60)}:${String(Math.floor(duration % 60)).padStart(2, '0')}`);
    if (Number.isFinite(rate) && rate > 0) details.push(`${t('sampleRate')} · ${(rate / 1000).toLocaleString(language === 'english' ? 'en' : 'zh-CN')} kHz`);
    elements.summaryResult.textContent = details.join('  /  ');
    for (const card of elements.grid.querySelectorAll('.stem-card')) {
      const stem = card.dataset.stem;
      const output = outputs.find((item) => item.stem === stem);
      if (!output) continue;
      const name = card.querySelector('.stem-card-copy strong');
      name.textContent = t('stemNames')[stem] || output.stem;
      card.querySelector('.stem-download').setAttribute('aria-label', `${t('download')} — ${name.textContent}`);
      card.querySelector('.stem-download').title = t('download');
      card.querySelector('audio').setAttribute('aria-label', `${name.textContent} audio preview`);
    }
  }
  function renderResults(result) {
    if (!result || !Array.isArray(result.outputs)) return;
    const outputs = result.outputs;
    const duration = Number(result.seconds);
    const rate = Number(result.sample_rate);
    const details = [];
    if (Number.isFinite(duration) && duration > 0) details.push(`${t('duration')} · ${Math.floor(duration / 60)}:${String(Math.floor(duration % 60)).padStart(2, '0')}`);
    if (Number.isFinite(rate) && rate > 0) details.push(`${t('sampleRate')} · ${(rate / 1000).toLocaleString(language === 'english' ? 'en' : 'zh-CN')} kHz`);
    elements.summaryResult.textContent = details.join('  /  ');
    const cards = new Map([...elements.grid.querySelectorAll('.stem-card')].map((card) => [card.dataset.stem, card]));
    for (const stem of stemOrder) {
      const output = outputs.find((item) => item.stem === stem);
      if (!output) continue;
      let card = cards.get(stem);
      if (!card) {
        card = document.createElement('article');
        card.className = 'stem-card';
        card.dataset.stem = stem;
        const head = document.createElement('div');
        head.className = 'stem-card-head';
        const mark = document.createElement('span');
        mark.className = `stem-mark mark-${stemClass[stem]}`;
        mark.textContent = stemInitial[stem];
        const copy = document.createElement('div');
        copy.className = 'stem-card-copy';
        const name = document.createElement('strong');
        const filename = document.createElement('span');
        copy.append(name, filename);
        const download = document.createElement('a');
        download.className = 'stem-download';
        download.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 17v3a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3"/></svg>';
        head.append(mark, copy, download);
        const audio = document.createElement('audio');
        audio.controls = true;
        audio.preload = 'none';
        card.append(head, audio);
        elements.grid.append(card);
      }
      const name = card.querySelector('.stem-card-copy strong');
      const filename = card.querySelector('.stem-card-copy span');
      const download = card.querySelector('.stem-download');
      const audio = card.querySelector('audio');
      name.textContent = t('stemNames')[stem] || output.stem;
      filename.textContent = output.name || `${stem}.wav`;
      filename.title = filename.textContent;
      download.href = safeUrl(output.url);
      download.download = output.name || `${stem}.wav`;
      download.setAttribute('aria-label', `${t('download')} — ${name.textContent}`);
      download.title = t('download');
      audio.setAttribute('aria-label', `${name.textContent} audio preview`);
      if (audio.getAttribute('src') !== safeUrl(output.url)) audio.src = safeUrl(output.url);
    }
    for (const [stem, card] of cards) if (!outputs.some((item) => item.stem === stem)) card.remove();
    elements.zip.href = `/api/stems/archive/${encodeURIComponent(currentJobId)}`;
  }

  elements.drop.addEventListener('click', (event) => { if (event.target !== elements.browse) elements.input.click(); });
  elements.drop.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); elements.input.click(); } });
  elements.browse.addEventListener('click', (event) => { event.stopPropagation(); elements.input.click(); });
  elements.input.addEventListener('change', () => setFile(elements.input.files?.[0]));
  elements.remove.addEventListener('click', clearFile);
  elements.separate.addEventListener('click', startSeparation);
  elements.retry.addEventListener('click', startSeparation);
  elements.newTask.addEventListener('click', () => {
    clearFile();
    elements.separate.querySelector('span').textContent = t('separate');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
  ['dragenter', 'dragover'].forEach((type) => elements.drop.addEventListener(type, (event) => {
    event.preventDefault();
    elements.drop.classList.add('is-dragging');
  }));
  ['dragleave', 'drop'].forEach((type) => elements.drop.addEventListener(type, (event) => {
    event.preventDefault();
    elements.drop.classList.remove('is-dragging');
  }));
  elements.drop.addEventListener('drop', (event) => setFile(event.dataTransfer?.files?.[0]));
  elements.zip.addEventListener('click', (event) => {
    if (!currentJobId) { event.preventDefault(); showError(t('jobUnavailable')); }
  });
  setLanguage(language);
})();
