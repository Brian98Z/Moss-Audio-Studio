'use strict';

(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const elements = {
    input: $('#file-input'), drop: $('#drop-zone'), browse: $('#browse-button'), summary: $('#file-summary'),
    filename: $('#file-name'), filesize: $('#file-size'), remove: $('#remove-file'), start: $('#denoise-button'),
    slider: $('#mix-slider'), mixValue: $('#mix-value'), progress: $('#progress-panel'), progressTitle: $('#progress-title'),
    progressFill: $('#progress-fill'), progressPercent: $('#progress-percent'), progressMessage: $('#progress-message'),
    error: $('#error-box'), errorMessage: $('#error-message'), retry: $('#retry-button'), results: $('#results-panel'),
    summaryResult: $('#result-summary'), originalAudio: $('#original-audio'), originalDownload: $('#original-download'),
    denoisedAudio: $('#denoised-audio'), denoisedDownload: $('#denoised-download'), newTask: $('#new-task'),
  };
  const translations = {
    chinese: {
      local:'本地处理', stepUpload:'选择音频', uploadTitle:'导入人声录音', formatNote:'WAV · MP3 · FLAC · M4A', dropTitle:'拖放音频到这里', dropOr:'或', browse:'浏览文件', dropHint:'支持常见音频格式 · 建议使用 WAV 获得最佳效果', removeFile:'移除文件', reduction:'降噪强度', mixHint:'降低强度可混回部分原始声音。', engineLabel:'处理引擎', privacy:'音频仅在本机处理', apply:'开始降噪', stepProcess:'正在降噪', working:'正在清理背景噪声', preparing:'正在准备降噪…', retry:'重试', stepResults:'试听结果', resultsTitle:'降噪结果已准备好。', original:'原始音频', denoised:'降噪后', downloadOriginal:'下载原始音频', downloadResult:'下载降噪音频', newTask:'处理另一段音频', guideLabel:'人声降噪', guideText:'在本机处理录音，降低背景噪声并保留人声。', takesTime:'处理需要一些时间', timeNote:'较长的音频可能需要几分钟，请保持此页面开启。', footerLeft:'MOSS · 本地人声降噪', footerRight:'你的音频不会离开这台设备。', invalidFile:'请选择有效的音频文件。', uploadError:'上传失败', requestError:'无法开始降噪', jobError:'降噪失败', jobUnavailable:'任务状态暂时无法获取，请检查连接后重试。', statusPending:'任务正在排队…', statusRunning:'正在降低背景噪声…', statusDone:'降噪已完成', duration:'时长', sampleRate:'采样率', elapsed:'处理用时', noOutputs:'降噪已完成，但没有返回音频文件。',
    },
    english: {
      local:'LOCAL PROCESSING', stepUpload:'SELECT AUDIO', uploadTitle:'Bring in a voice recording', formatNote:'WAV · MP3 · FLAC · M4A', dropTitle:'Drop an audio file here', dropOr:'or', browse:'browse files', dropHint:'Common audio formats supported · WAV recommended for best results', removeFile:'Remove file', reduction:'Reduction', mixHint:'Lower values blend some of the original audio back in.', engineLabel:'Engine', privacy:'Audio stays on this device', apply:'Denoise audio', stepProcess:'DENOISING', working:'Cleaning up background noise', preparing:'Preparing denoise…', retry:'Retry', stepResults:'A/B AUDITION', resultsTitle:'Your denoised audio is ready.', original:'Original audio', denoised:'Denoised', downloadOriginal:'Download original', downloadResult:'Download denoised audio', newTask:'Process another recording', guideLabel:'Vocal denoise', guideText:'Process recordings locally to reduce background noise while preserving voice.', takesTime:'Processing takes a little time', timeNote:'Longer recordings may take a few minutes; please keep this page open.', footerLeft:'MOSS · LOCAL VOCAL DENOISE', footerRight:'Your audio never leaves this device.', invalidFile:'Choose a valid audio file.', uploadError:'Upload failed', requestError:'Could not start denoising', jobError:'Denoising failed', jobUnavailable:'The job status is temporarily unavailable. Check your connection and retry.', statusPending:'Job queued…', statusRunning:'Reducing background noise…', statusDone:'Denoising complete', duration:'Duration', sampleRate:'Sample rate', elapsed:'Elapsed', noOutputs:'Denoising finished, but no audio file was returned.',
    },
  };
  let language = new URLSearchParams(location.search).get('language') === 'english' ? 'english' : 'chinese';
  let selectedFile = null;
  let uploadedPath = null;
  let originalUrl = null;
  let active = false;
  let pollTimer = 0;
  let progress = 0;
  let currentJobId = '';

  function t(key) { return translations[language][key] ?? key; }
  function themeQuery() {
    if (!window.MossTheme) return '';
    const theme = MossTheme.get();
    if (!theme || !theme.mode) return '';
    return '?theme=' + encodeURIComponent(theme.mode) + (theme.primary ? '&primary=' + encodeURIComponent(theme.primary.slice(1)) : '');
  }
  function setLanguage(next) {
    language = next === 'english' ? 'english' : 'chinese';
    document.documentElement.lang = language === 'english' ? 'en' : 'zh-CN';
    const query = new URLSearchParams({ language });
    const theme = themeQuery();
    if (theme) new URLSearchParams(theme.replace(/^\?/, '')).forEach((value, key) => query.set(key, value));
    $('.brand').href = `/tools?${query}`;
    $('#back-tools').href = `/tools?${query}`;
    $('#back-tools').textContent = language === 'english' ? '← Back to Tools' : '← 返回工具';
    document.querySelectorAll('[data-i18n]').forEach((node) => { node.textContent = t(node.dataset.i18n); });
    document.querySelectorAll('[data-i18n-aria]').forEach((node) => node.setAttribute('aria-label', t(node.dataset.i18nAria)));
    elements.mixValue.textContent = `${elements.slider.value}%`;
    if (selectedFile) elements.start.querySelector('span').textContent = active ? t('working') : currentJobId ? t('retry') : t('apply');
    if (!elements.results.hidden) renderSummary(window.__mossDenoiseResult || {});
  }
  window.addEventListener('message', (event) => {
    if (event.source === parent && event.data?.type === 'moss-language') setLanguage(event.data.language);
  });
  function formatSize(bytes) { return bytes < 1_000_000 ? `${(bytes / 1024).toFixed(0)} KB` : `${(bytes / 1_000_000).toFixed(1)} MB`; }
  function setFile(file) {
    if (!file || active) return;
    if (!file.type.startsWith('audio/') && !/\.(wav|mp3|flac|m4a|ogg|aac|aiff?)$/i.test(file.name)) { elements.progress.hidden = true; showError(t('invalidFile')); return; }
    selectedFile = file; uploadedPath = null; currentJobId = '';
    elements.filename.textContent = file.name; elements.filesize.textContent = formatSize(file.size);
    elements.summary.hidden = false; elements.drop.hidden = true; elements.start.disabled = false;
    elements.start.querySelector('span').textContent = t('apply'); elements.progress.hidden = true; elements.error.hidden = true; elements.results.hidden = true;
    if (originalUrl) URL.revokeObjectURL(originalUrl);
    originalUrl = URL.createObjectURL(file); elements.originalAudio.src = originalUrl;
    elements.originalDownload.href = originalUrl; elements.originalDownload.download = file.name;
  }
  function clearFile() {
    if (active) return;
    selectedFile = null; uploadedPath = null; currentJobId = ''; elements.input.value = '';
    elements.summary.hidden = true; elements.drop.hidden = false; elements.start.disabled = true;
    elements.results.hidden = true; elements.progress.hidden = true; elements.error.hidden = true;
    if (originalUrl) URL.revokeObjectURL(originalUrl); originalUrl = null;
    elements.originalAudio.removeAttribute('src'); elements.originalDownload.removeAttribute('href');
  }
  function showError(message) { elements.errorMessage.textContent = message; elements.error.hidden = false; }
  function updateProgress(value, message) {
    progress = Math.max(progress, Math.min(95, value)); elements.progressFill.style.width = `${progress}%`;
    elements.progressPercent.textContent = `${Math.round(progress)}%`; if (message) elements.progressMessage.textContent = message;
  }
  async function parseResponse(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || data.error || `${response.status} ${response.statusText}`);
    return data;
  }
  async function uploadFile() {
    const form = new FormData(); form.append('files', selectedFile);
    const data = await parseResponse(await fetch('/api/upload', { method:'POST', body:form }));
    if (!data.files?.[0]?.path) throw new Error(t('uploadError'));
    return data.files[0].path;
  }
  async function startDenoise() {
    if ((!selectedFile && !currentJobId) || active) return;
    active = true; elements.start.disabled = true; elements.start.classList.add('is-loading');
    elements.start.querySelector('span').textContent = t('working'); elements.progress.hidden = false;
    elements.progressTitle.textContent = t('working'); elements.error.hidden = true; elements.results.hidden = true;
    progress = 0; updateProgress(3, t('preparing'));
    try {
      if (currentJobId) { await pollJob(currentJobId); return; }
      if (!uploadedPath) { updateProgress(8, t('preparing')); uploadedPath = await uploadFile(); }
      updateProgress(12, t('statusPending'));
      const data = await parseResponse(await fetch('/api/denoise/apply', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ path:uploadedPath, mix:Number(elements.slider.value) / 100 }) }));
      if (!data.job_id) throw new Error(t('requestError'));
      currentJobId = data.job_id; await pollJob(currentJobId);
    } catch (error) { fail(error.message || t('requestError'), Boolean(currentJobId)); }
  }
  async function pollJob(jobId) {
    let attempts = 0;
    while (active) {
      await new Promise((resolve) => { pollTimer = window.setTimeout(resolve, attempts < 5 ? 700 : 1200); });
      if (!active) return;
      try {
        const job = await parseResponse(await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { cache:'no-store' })); attempts++;
        if (job.status === 'pending') updateProgress(Math.min(22, 12 + attempts * 2), t('statusPending'));
        else if (job.status === 'running') updateProgress(Math.round(100 * (job.params?.progress || 0)), t('statusRunning'));
        if (job.status === 'failed') { fail(job.error || t('jobError')); return; }
        if (job.status === 'done') { updateProgress(100, t('statusDone')); finish(job.result || {}); return; }
        if (!['pending', 'running'].includes(job.status)) { fail(job.error || t('jobUnavailable')); return; }
      } catch (error) { fail(error.message || t('jobUnavailable'), true); return; }
    }
  }
  function fail(message, preserveJob = false) {
    active = false; window.clearTimeout(pollTimer); if (!preserveJob) currentJobId = '';
    elements.start.disabled = false; elements.start.classList.remove('is-loading');
    elements.start.querySelector('span').textContent = currentJobId ? t('retry') : t('apply');
    elements.progressTitle.textContent = t('jobError'); showError(message);
  }
  function finish(result) {
    active = false; elements.start.classList.remove('is-loading'); elements.progressTitle.textContent = t('statusDone'); elements.start.disabled = false;
    elements.start.querySelector('span').textContent = t('apply');
    if (!Array.isArray(result.outputs) || result.outputs.length === 0) { showError(t('noOutputs')); return; }
    window.__mossDenoiseResult = result; elements.progress.hidden = true; elements.results.hidden = false; renderResults(result);
    elements.results.scrollIntoView({ behavior:'smooth', block:'start' });
  }
  function safeUrl(url) {
    try { const parsed = new URL(url, location.origin); return parsed.origin === location.origin ? parsed.href : '#'; }
    catch (_) { return '#'; }
  }
  function renderSummary(result) {
    const details = []; const duration = Number(result.seconds); const rate = Number(result.sample_rate); const elapsed = Number(result.elapsed);
    if (Number.isFinite(duration) && duration >= 0) details.push(`${t('duration')} · ${Math.floor(duration / 60)}:${String(Math.floor(duration % 60)).padStart(2, '0')}`);
    if (Number.isFinite(rate) && rate > 0) details.push(`${t('sampleRate')} · ${(rate / 1000).toLocaleString(language === 'english' ? 'en' : 'zh-CN')} kHz`);
    if (Number.isFinite(elapsed) && elapsed >= 0) details.push(`${t('elapsed')} · ${elapsed.toFixed(1)} s`);
    elements.summaryResult.textContent = details.join('  /  ');
  }
  function renderResults(result) {
    if (!Array.isArray(result.outputs) || !result.outputs[0]) return;
    renderSummary(result);
    const output = result.outputs[0]; const url = safeUrl(output.url);
    elements.denoisedAudio.src = url; elements.denoisedDownload.href = url;
    elements.denoisedDownload.download = output.name || 'denoised.wav';
  }
  elements.drop.addEventListener('click', (event) => { if (event.target !== elements.browse) elements.input.click(); });
  elements.drop.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); elements.input.click(); } });
  elements.browse.addEventListener('click', (event) => { event.stopPropagation(); elements.input.click(); });
  elements.input.addEventListener('change', () => setFile(elements.input.files?.[0]));
  elements.remove.addEventListener('click', clearFile); elements.start.addEventListener('click', startDenoise); elements.retry.addEventListener('click', startDenoise);
  elements.slider.addEventListener('input', () => { elements.mixValue.textContent = `${elements.slider.value}%`; });
  elements.newTask.addEventListener('click', clearFile);
  ['dragenter', 'dragover'].forEach((type) => elements.drop.addEventListener(type, (event) => { event.preventDefault(); elements.drop.classList.add('is-dragging'); }));
  ['dragleave', 'drop'].forEach((type) => elements.drop.addEventListener(type, (event) => { event.preventDefault(); elements.drop.classList.remove('is-dragging'); }));
  elements.drop.addEventListener('drop', (event) => setFile(event.dataTransfer?.files?.[0]));
  setLanguage(language);
})();
