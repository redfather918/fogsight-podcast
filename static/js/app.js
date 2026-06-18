/**
 * Fogsight Podcast — 前端 SPA
 */
'use strict';

// ── 状态 ─────────────────────────────────────────────────
const State = {
    view: 'upload',       // upload | processing | result | history
    jobId: null,
    ws: null,
    selectedFile: null,
    jobStatus: null,
    stageElapsed: {},     // stage -> 开始时间
};

// 阶段定义（与后端 Pipeline 对应）
const STAGES = [
    { key: 'parsing',   label: 'PDF 解析',  icon: '📄' },
    { key: 'scripting', label: '脚本生成',  icon: '✍️' },
    { key: 'animating', label: '动画生成',  icon: '🎨' },
    { key: 'tts',       label: '音频生成',  icon: '🔊' },
    { key: 'syncing',   label: '音画同步',  icon: '🔗' },
    { key: 'recording', label: '视频录制',  icon: '🎬' },
    { key: 'composing', label: '视频合成',  icon: '🎞️' },
];


// ── DOM 引用 ──────────────────────────────────────────────
const $ = id => document.getElementById(id);
const Views = {
    upload:     $('view-upload'),
    processing: $('view-processing'),
    result:     $('view-result'),
    history:    $('view-history'),
};


// ── 视图切换 ──────────────────────────────────────────────
function showView(name) {
    Object.values(Views).forEach(v => v.classList.remove('active'));
    Views[name]?.classList.add('active');
    State.view = name;
}


// ── 上传区交互 ────────────────────────────────────────────
function initUpload() {
    const zone = $('upload-zone');
    const fileInput = $('file-input');
    const fileName = $('file-name');
    const submitBtn = $('submit-btn');

    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', e => {
        e.preventDefault();
        zone.classList.remove('drag-over');
        const f = e.dataTransfer?.files[0];
        if (f) handleFileSelect(f);
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files[0]) handleFileSelect(fileInput.files[0]);
    });

    function handleFileSelect(f) {
        if (!f.name.toLowerCase().endsWith('.pdf')) {
            showToast('只支持 PDF 文件', 'error');
            return;
        }
        if (f.size > 50 * 1024 * 1024) {
            showToast('文件大小超过 50MB', 'error');
            return;
        }
        State.selectedFile = f;
        fileName.textContent = `${f.name} (${(f.size / 1024 / 1024).toFixed(1)}MB)`;
        zone.classList.add('has-file');
        submitBtn.disabled = false;
    }

    submitBtn.addEventListener('click', submitJob);
}

async function submitJob() {
    if (!State.selectedFile) return;

    const btn = $('submit-btn');
    btn.disabled = true;
    btn.textContent = '正在上传...';

    const duration = $('target-duration').value;
    const speechRate = $('speech-rate').value;

    const fd = new FormData();
    fd.append('file', State.selectedFile);

    try {
        const res = await fetch(`/api/jobs?target_duration=${duration}&speech_rate=${speechRate}`, {
            method: 'POST', body: fd,
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || '上传失败');
        }
        const data = await res.json();
        State.jobId = data.job_id;
        startProcessing(data.job_id);
    } catch (e) {
        showToast(e.message, 'error');
        btn.disabled = false;
        btn.textContent = '开始生成';
    }
}


// ── Processing 视图 ───────────────────────────────────────
function startProcessing(jobId) {
    showView('processing');
    $('job-id-badge').textContent = `Job #${jobId.substring(0, 8)}`;

    // 初始化阶段列表
    renderStages('pending', 'pending');

    // 重置进度
    updateProgress(0);
    clearLog();

    // 连接 WebSocket
    connectWS(jobId);
}

function connectWS(jobId) {
    if (State.ws) { State.ws.close(); State.ws = null; }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/api/ws/${jobId}`);
    State.ws = ws;

    ws.onopen = () => logLine('WebSocket 已连接，等待处理进度...', 'info');

    ws.onmessage = ({ data }) => {
        try {
            handleWsMessage(JSON.parse(data));
        } catch (e) {
            console.warn('WS 消息解析失败', e);
        }
    };

    ws.onclose = () => {
        logLine('WebSocket 连接关闭', 'info');
        // 若任务未结束，3 秒后重连
        if (State.jobId && State.jobStatus !== 'done' && State.jobStatus !== 'failed') {
            setTimeout(() => connectWS(jobId), 3000);
        }
    };

    ws.onerror = () => logLine('WebSocket 连接错误', 'error');
}

function handleWsMessage(msg) {
    switch (msg.type) {
        case 'progress':
            updateProgress(msg.progress);
            renderStages(msg.stage, 'active');
            if (msg.message) logLine(msg.message, 'info');
            State.jobStatus = msg.stage;
            break;

        case 'log':
            logLine(msg.message, msg.level || 'info');
            break;

        case 'done':
            State.jobStatus = 'done';
            updateProgress(100);
            renderStages('done', 'done');
            logLine('✅ 视频生成完成！', 'info');
            setTimeout(() => showResult(msg), 800);
            break;

        case 'error':
            State.jobStatus = 'failed';
            logLine(`❌ 错误：${msg.message}`, 'error');
            $('error-banner').textContent = `处理失败：${msg.message}`;
            $('error-banner').classList.add('visible');
            break;

        case 'ping':
            break;
    }
}

function renderStages(currentStage, currentStatus) {
    const container = $('stages-list');
    container.innerHTML = '';

    let passedCurrent = false;
    STAGES.forEach(s => {
        const item = document.createElement('div');
        item.className = 'stage-item';

        let stageClass = 'pending';
        if (s.key === currentStage && currentStatus !== 'done') {
            stageClass = 'active';
            passedCurrent = true;
        } else if (!passedCurrent && currentStatus !== 'pending') {
            stageClass = 'done';
        }
        if (currentStatus === 'done') stageClass = 'done';

        item.classList.add(stageClass);

        const iconMap = { pending: '○', active: '', done: '✓', failed: '✗' };
        const statusText = { pending: '等待中', active: '处理中...', done: '完成', failed: '失败' };

        item.innerHTML = `
            <div class="stage-icon">${stageClass !== 'active' ? iconMap[stageClass] : ''}</div>
            <span class="stage-name">${s.icon} ${s.label}</span>
            <span class="stage-status">${statusText[stageClass]}</span>`;
        container.appendChild(item);
    });
}

function updateProgress(pct) {
    $('progress-fill').style.width = pct + '%';
    $('progress-pct').textContent = pct + '%';
}

function clearLog() {
    $('log-box').innerHTML = '';
}

function logLine(msg, level = 'info') {
    const box = $('log-box');
    const line = document.createElement('div');
    line.className = `log-line ${level}`;
    const ts = new Date().toLocaleTimeString();
    line.innerHTML = `<span class="ts">[${ts}]</span>${escapeHtml(msg)}`;
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
}


// ── Result 视图 ───────────────────────────────────────────
function showResult(data) {
    showView('result');
    State.ws?.close();

    const video = $('result-video');
    video.src = data.video_url || `/api/jobs/${State.jobId}/video`;

    $('result-title').textContent = data.title || '生成的视频';
    $('result-duration').textContent = formatDuration(data.duration || 0);
    $('result-size').textContent = formatSize(data.file_size || 0);
    $('result-resolution').textContent = '1920×1080';

    $('download-btn').onclick = () => {
        const a = document.createElement('a');
        a.href = video.src;
        a.download = (data.title || 'podcast') + '.mp4';
        a.click();
    };

    $('regenerate-btn').onclick = () => {
        State.jobId = null;
        State.selectedFile = null;
        $('file-input').value = '';
        $('upload-zone').classList.remove('has-file');
        $('submit-btn').disabled = true;
        showView('upload');
    };
}

// 轮询兜底（WS 断连时）
async function pollJobStatus(jobId) {
    while (State.jobId === jobId && !['done','failed'].includes(State.jobStatus)) {
        await sleep(3000);
        try {
            const res = await fetch(`/api/jobs/${jobId}`);
            const job = await res.json();
            updateProgress(job.progress || 0);
            if (job.status === 'done' && job.result) {
                State.jobStatus = 'done';
                showResult(job.result);
                return;
            }
            if (job.status === 'failed') {
                State.jobStatus = 'failed';
                logLine(`处理失败：${job.error}`, 'error');
                return;
            }
        } catch (e) {}
    }
}


// ── History 视图 ──────────────────────────────────────────
async function loadHistory() {
    showView('history');
    const container = $('history-list');
    container.innerHTML = '<p style="color:var(--gray-400);text-align:center;padding:2rem;">加载中...</p>';

    try {
        const res = await fetch('/api/jobs?page=1&limit=20');
        const data = await res.json();

        if (!data.jobs.length) {
            container.innerHTML = '<p style="color:var(--gray-400);text-align:center;padding:3rem;">暂无历史记录</p>';
            return;
        }

        container.innerHTML = '';
        data.jobs.forEach(j => {
            const card = document.createElement('div');
            card.className = 'history-card';
            card.innerHTML = `
                <div class="status-dot ${j.status}"></div>
                <div style="flex:1">
                    <div class="h-title">${escapeHtml(j.title || j.pdf_filename || '未命名')}</div>
                    <div class="h-meta">${j.status === 'done' ? '已完成' : j.status} · ${formatDate(j.created_at)}</div>
                </div>
                <div class="h-meta">${j.progress}%</div>`;

            card.addEventListener('click', () => {
                State.jobId = j.job_id;
                if (j.status === 'done') {
                    fetch(`/api/jobs/${j.job_id}`)
                        .then(r => r.json())
                        .then(job => {
                            if (job.result) showResult(job.result);
                        });
                } else {
                    startProcessing(j.job_id);
                }
            });

            container.appendChild(card);
        });
    } catch (e) {
        container.innerHTML = `<p style="color:var(--danger);text-align:center;padding:2rem;">加载失败：${e.message}</p>`;
    }
}


// ── 工具函数 ──────────────────────────────────────────────
function formatDuration(s) {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return m ? `${m}:${String(sec).padStart(2,'0')}` : `${sec}s`;
}

function formatSize(bytes) {
    if (bytes > 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    if (bytes > 1024) return (bytes / 1024).toFixed(0) + ' KB';
    return bytes + ' B';
}

function formatDate(iso) {
    const d = new Date(iso);
    return d.toLocaleDateString('zh-CN') + ' ' + d.toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' });
}

function escapeHtml(str) {
    return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

let toastTimer;
function showToast(msg, type = 'info') {
    const toast = $('toast');
    toast.textContent = msg;
    toast.style.background = type === 'error' ? 'var(--danger)' : 'var(--gray-900)';
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 3000);
}


// ── 初始化 ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initUpload();

    $('nav-history').addEventListener('click', loadHistory);
    $('nav-home').addEventListener('click', () => showView('upload'));
    $('back-from-processing').addEventListener('click', () => {
        State.ws?.close();
        showView('upload');
    });
    $('back-from-result').addEventListener('click', () => showView('history'));

    // 语速显示
    const speechRate = $('speech-rate');
    const speechRateLabel = $('speech-rate-label');
    speechRate.addEventListener('input', () => {
        const v = speechRate.value;
        speechRateLabel.textContent = v > 0 ? `+${v}` : v;
    });

    showView('upload');
});
