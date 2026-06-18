'use strict';

const $ = id => document.getElementById(id);

const state = {
    view: 'idle',
    jobId: null,
    ws: null,
    selectedFile: null,
    jobStatus: null,
};

const STAGES = {
    parsing:   '解析 PDF',
    scripting: '生成脚本',
    animating: '制作动画',
    tts:       '合成语音',
    syncing:   '音画同步',
    recording: '录制画面',
    composing: '合成视频',
};

/* ── State switching ── */
function show(id) {
    ['idle','processing','done'].forEach(s => $(`state-${s}`).classList.remove('active'));
    $(`state-${id}`).classList.add('active');
    state.view = id;
}

/* ── Upload ── */
function initUpload() {
    const zone = $('upload-zone');
    const input = $('file-input');
    const btn = $('btn-submit');

    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', e => {
        e.preventDefault();
        zone.classList.remove('drag-over');
        if (e.dataTransfer?.files[0]) onFile(e.dataTransfer.files[0]);
    });

    input.addEventListener('change', () => { if (input.files[0]) onFile(input.files[0]); });

    function onFile(f) {
        if (!f.name.toLowerCase().endsWith('.pdf')) return toast('仅支持 PDF 文件');
        if (f.size > 50 * 1024 * 1024) return toast('文件超过 50MB');
        state.selectedFile = f;
        $('file-name').textContent = `${f.name} (${(f.size/1024/1024).toFixed(1)}MB)`;
        zone.classList.add('has-file');
        btn.disabled = false;
    }

    $('btn-reset').addEventListener('click', e => {
        e.stopPropagation();
        state.selectedFile = null;
        zone.classList.remove('has-file');
        input.value = '';
        btn.disabled = true;
    });

    btn.addEventListener('click', submit);
}

async function submit() {
    if (!state.selectedFile) return;
    const btn = $('btn-submit');
    btn.disabled = true;
    btn.textContent = '上传中...';

    const fd = new FormData();
    fd.append('file', state.selectedFile);

    try {
        const dur = $('target-duration').value;
        const rate = $('speech-rate').value;
        const res = await fetch(`/api/jobs?target_duration=${dur}&speech_rate=${rate}`, { method: 'POST', body: fd });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '请求失败'); }
        const data = await res.json();
        state.jobId = data.job_id;
        startProcessing(data.job_id);
    } catch (e) {
        toast(e.message);
        btn.disabled = false;
        btn.textContent = '生成视频';
    }
}

/* ── Processing ── */
function startProcessing(jobId) {
    show('processing');
    $('proc-title').textContent = '正在生成...';
    $('proc-stage').textContent = '准备中';
    $('proc-error').classList.remove('visible');
    updateProgress(0);
    connectWS(jobId);
}

function connectWS(jobId) {
    if (state.ws) { state.ws.close(); state.ws = null; }

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/api/ws/${jobId}`);
    state.ws = ws;

    ws.onmessage = ({ data }) => {
        try { handleMessage(JSON.parse(data)); } catch (_) {}
    };

    ws.onclose = () => {
        if (state.jobId === jobId && state.jobStatus !== 'done' && state.jobStatus !== 'failed') {
            setTimeout(() => connectWS(jobId), 3000);
        }
    };

    ws.onerror = () => {};
}

function handleMessage(msg) {
    switch (msg.type) {
        case 'progress':
            updateProgress(msg.progress);
            $('proc-stage').textContent = STAGES[msg.stage] || msg.stage || '处理中...';
            $('proc-title').textContent = `正在生成 (${msg.progress}%)`;
            state.jobStatus = msg.stage;
            break;
        case 'done':
            state.jobStatus = 'done';
            updateProgress(100);
            state.ws?.close();
            setTimeout(() => showResult(msg), 500);
            break;
        case 'error':
            state.jobStatus = 'failed';
            state.ws?.close();
            $('proc-error').textContent = msg.message || '处理失败';
            $('proc-error').classList.add('visible');
            $('proc-title').textContent = '生成失败';
            $('proc-stage').textContent = '';
            break;
    }
}

function updateProgress(pct) {
    $('progress-fill').style.width = pct + '%';
    $('progress-pct').textContent = pct + '%';
}

/* ── Done ── */
function showResult(data) {
    show('done');

    const url = data.video_url || `/api/jobs/${state.jobId}/video`;
    $('result-video').src = url;

    $('meta-duration').textContent = fmtDuration(data.duration || 0);
    $('meta-size').textContent = fmtSize(data.file_size || 0);
}

/* ── Cancel / Restart ── */
$('btn-cancel').addEventListener('click', () => {
    state.ws?.close();
    state.jobId = null;
    state.jobStatus = null;
    show('idle');
    $('btn-submit').disabled = !state.selectedFile;
    $('btn-submit').textContent = '生成视频';
});

$('btn-restart').addEventListener('click', () => {
    state.jobId = null;
    state.jobStatus = null;
    state.selectedFile = null;
    $('file-input').value = '';
    $('upload-zone').classList.remove('has-file');
    $('btn-submit').disabled = true;
    show('idle');
});

$('btn-download').addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = $('result-video').src;
    a.download = 'podcast.mp4';
    a.click();
});

/* ── Speech rate ── */
$('speech-rate').addEventListener('input', () => {
    const v = $('speech-rate').value;
    $('speech-rate-val').textContent = v > 0 ? ` +${v}` : v;
});

/* ── Toast ── */
let toastT;
function toast(msg) {
    let el = document.querySelector('.toast');
    if (!el) {
        el = document.createElement('div');
        el.className = 'toast';
        document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastT);
    toastT = setTimeout(() => el.classList.remove('show'), 3000);
}

/* ── Utils ── */
function fmtDuration(s) {
    const m = Math.floor(s/60), sec = Math.floor(s%60);
    return m ? `${m}:${String(sec).padStart(2,'0')}` : `${sec}s`;
}
function fmtSize(b) {
    if (b > 1024*1024) return (b/1024/1024).toFixed(1)+' MB';
    if (b > 1024) return (b/1024).toFixed(0)+' KB';
    return b+' B';
}

/* ── Init ── */
document.addEventListener('DOMContentLoaded', () => {
    initUpload();
    show('idle');
});
