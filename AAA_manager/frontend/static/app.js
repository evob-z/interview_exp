// ===== 面试助手 - 前端交互逻辑 =====

(function () {
    'use strict';

    // --- State ---
    let currentMode = 'interview';
    let isStreaming = false;
    let currentSessionId = '';  // 当前会话ID

    // --- DOM Elements ---
    const chatMessages = document.getElementById('chatMessages');
    const chatInput = document.getElementById('chatInput');
    const sendBtn = document.getElementById('sendBtn');
    const modeBtns = document.querySelectorAll('.mode-btn');
    const mobileNavBtns = document.querySelectorAll('.mobile-nav-btn');

    // --- Initialize Marked ---
    if (window.marked) {
        marked.setOptions({
            highlight: function (code, lang) {
                if (window.hljs && lang && hljs.getLanguage(lang)) {
                    return hljs.highlight(code, { language: lang }).value;
                }
                return code;
            },
            breaks: true,
            gfm: true
        });
    }

    // --- API Helpers ---
    async function apiGet(url) {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`请求失败: ${res.status}`);
        return res.json();
    }

    async function apiPost(url, data) {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!res.ok) throw new Error(`请求失败: ${res.status}`);
        return res.json();
    }

    // --- Error Handling ---
    function showError(message) {
        const toast = document.createElement('div');
        toast.className = 'error-toast';
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    }

    // --- Chat Messages ---
    function clearWelcome() {
        const welcome = chatMessages.querySelector('.welcome-message');
        if (welcome) welcome.remove();
    }

    function addMessage(type, content, extras = {}) {
        clearWelcome();
        const msgEl = document.createElement('div');
        msgEl.className = `message ${type}`;

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';

        if (type === 'user') {
            bubble.textContent = content;
        } else if (type === 'assistant') {
            bubble.innerHTML = renderMarkdown(content);
        } else if (type === 'system') {
            bubble.innerHTML = renderMarkdown(content);
        }

        msgEl.appendChild(bubble);

        // Sources
        if (extras.sources && extras.sources.length > 0) {
            const sourcesEl = document.createElement('div');
            sourcesEl.className = 'message-sources';
            extras.sources.forEach(src => {
                const tag = document.createElement('span');
                tag.className = 'source-tag';
                tag.textContent = typeof src === 'string' ? src : `📄 ${src.category || ''} ${src.question_id || ''}`;
                tag.title = typeof src === 'string' ? src : (src.text || '');
                sourcesEl.appendChild(tag);
            });
            msgEl.appendChild(sourcesEl);
        }

        chatMessages.appendChild(msgEl);
        scrollToBottom();
        return msgEl;
    }

    function addStreamingMessage() {
        clearWelcome();
        const msgEl = document.createElement('div');
        msgEl.className = 'message assistant';
        msgEl.id = 'streamingMsg';

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';
        bubble.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';

        msgEl.appendChild(bubble);
        chatMessages.appendChild(msgEl);
        scrollToBottom();
        return msgEl;
    }

    function updateStreamingMessage(content) {
        const msgEl = document.getElementById('streamingMsg');
        if (!msgEl) return;
        const bubble = msgEl.querySelector('.message-bubble');
        bubble.innerHTML = renderMarkdown(content);
        scrollToBottom();
    }

    function finalizeStreamingMessage(extras = {}) {
        const msgEl = document.getElementById('streamingMsg');
        if (!msgEl) return;
        msgEl.removeAttribute('id');

        // Add sources
        if (extras.sources && extras.sources.length > 0) {
            const sourcesEl = document.createElement('div');
            sourcesEl.className = 'message-sources';
            extras.sources.forEach(src => {
                const tag = document.createElement('span');
                tag.className = 'source-tag';
                tag.textContent = typeof src === 'string' ? src : `📄 ${src.category || ''} ${src.question_id || ''}`;
                tag.title = typeof src === 'string' ? src : (src.text || '');
                sourcesEl.appendChild(tag);
            });
            msgEl.appendChild(sourcesEl);
        }

        scrollToBottom();
    }

    function renderMarkdown(text) {
        if (!text) return '';
        if (window.marked) {
            return marked.parse(text);
        }
        return text.replace(/\n/g, '<br>');
    }

    function scrollToBottom() {
        requestAnimationFrame(() => {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        });
    }

    // --- Send Question ---
    async function sendQuestion(question) {
        if (!question.trim() || isStreaming) return;

        // 如果没有当前会话，先自动创建
        if (!currentSessionId) {
            try {
                const data = await apiPost('/api/history/sessions', {});
                currentSessionId = data.session.id;
            } catch (e) {
                console.warn('创建会话失败:', e);
            }
        }

        addMessage('user', question);
        chatInput.value = '';
        autoResizeInput();
        setInputEnabled(false);

        try {
            await streamQuestion(question);
        } catch (err) {
            // Fallback to non-stream
            try {
                await fallbackQuestion(question);
            } catch (fallbackErr) {
                showError('网络错误，请稍后重试');
                removeStreamingMessage();
            }
        }

        setInputEnabled(true);
        // 刷新历史记录列表
        loadHistory();
    }

    async function streamQuestion(question) {
        isStreaming = true;
        addStreamingMessage();

        const response = await fetch('/api/qa/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, mode: currentMode, session_id: currentSessionId })
        });

        if (!response.ok) {
            throw new Error('Stream not available');
        }

        const contentType = response.headers.get('content-type') || '';

        if (contentType.includes('text/event-stream')) {
            // SSE stream
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let fullContent = '';
            let extras = {};

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split('\n');

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = line.slice(6);
                        if (data === '[DONE]') continue;
                        try {
                            const parsed = JSON.parse(data);
                            if (parsed.type === 'content') {
                                fullContent += parsed.data || '';
                                updateStreamingMessage(fullContent);
                            } else if (parsed.type === 'sources') {
                                extras.sources = parsed.data;
                            } else if (parsed.type === 'done') {
                                // done 事件，忽略（轮询在流结束后统一触发）
                            } else if (parsed.content) {
                                // fallback: old format
                                fullContent += parsed.content;
                                updateStreamingMessage(fullContent);
                            }
                        } catch (e) {
                            // plain text chunk
                            fullContent += data;
                            updateStreamingMessage(fullContent);
                        }
                    }
                }
            }

            finalizeStreamingMessage(extras);
        } else {
            // JSON response (non-stream fallback)
            const data = await response.json();
            updateStreamingMessage(data.answer || data.content || '');
            finalizeStreamingMessage({
                sources: data.sources
            });
        }

        isStreaming = false;

        // 流式完成后触发追问轮询
        if (currentSessionId) {
            setTimeout(() => pollFollowups(currentSessionId), 2000);
        }
    }

    async function fallbackQuestion(question) {
        addStreamingMessage();
        const data = await apiPost('/api/qa', { question, mode: currentMode, session_id: currentSessionId });
        updateStreamingMessage(data.answer || '');
        finalizeStreamingMessage({
            sources: data.sources
        });
        isStreaming = false;

        // 触发追问轮询
        if (currentSessionId) {
            setTimeout(() => pollFollowups(currentSessionId), 2000);
        }
    }

    // --- Followup Prediction ---
    async function pollFollowups(sessionId) {
        for (let i = 0; i < 5; i++) {
            try {
                const data = await apiGet(`/api/followup/${sessionId}`);
                if (data.ready && data.followups.length > 0) {
                    showFollowups(data.followups);
                    return;
                }
            } catch (e) { /* ignore */ }
            await new Promise(r => setTimeout(r, 2000));
        }
    }

    function showFollowups(followups) {
        const container = document.getElementById('chatMessages');
        const div = document.createElement('div');
        div.className = 'followup-suggestions';
        div.innerHTML = `
            <div class="followup-header">💡 深入追问 & 相关问题：</div>
            ${followups.map((f, i) => `
                <div class="followup-item" data-question="${(f.question || '').replace(/"/g, '&quot;')}">
                    <span class="followup-num">${i + 1}.</span>
                    <span class="followup-text">${f.question || ''}</span>
                </div>
            `).join('')}
        `;
        // 绑定点击事件
        div.querySelectorAll('.followup-item').forEach(item => {
            item.addEventListener('click', () => {
                const q = item.dataset.question;
                if (q) {
                    chatInput.value = q;
                    sendQuestion(q);
                }
            });
        });
        container.appendChild(div);
        scrollToBottom();
    }

    function removeStreamingMessage() {
        const el = document.getElementById('streamingMsg');
        if (el) el.remove();
        isStreaming = false;
    }

    function setInputEnabled(enabled) {
        chatInput.disabled = !enabled;
        sendBtn.disabled = !enabled;
        if (enabled) chatInput.focus();
    }

    // --- Input Handling ---
    function autoResizeInput() {
        chatInput.style.height = 'auto';
        chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
    }

    chatInput.addEventListener('input', autoResizeInput);

    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendQuestion(chatInput.value);
        }
    });

    sendBtn.addEventListener('click', () => {
        sendQuestion(chatInput.value);
    });

    // --- Mode Switch ---
    modeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            modeBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentMode = btn.dataset.mode;
        });
    });

    // --- Card Toggle ---
    document.querySelectorAll('.card-header').forEach(header => {
        header.addEventListener('click', () => {
            const targetId = header.dataset.toggle;
            if (!targetId) return;
            const body = document.getElementById(targetId);
            const toggle = header.querySelector('.card-toggle');
            if (body) body.classList.toggle('collapsed');
            if (toggle) toggle.classList.toggle('collapsed');
        });
    });

    // --- Welcome Tips ---
    document.querySelectorAll('.welcome-tips .tip').forEach(tip => {
        tip.addEventListener('click', () => {
            const q = tip.dataset.question;
            if (q) sendQuestion(q);
        });
    });

    // --- Mobile Navigation ---
    mobileNavBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            mobileNavBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const panel = btn.dataset.panel;
            const chatPanel = document.querySelector('.chat-panel');
            const infoPanel = document.querySelector('.info-panel');

            if (panel === 'chat') {
                chatPanel.classList.remove('hidden');
                infoPanel.classList.remove('active');
            } else {
                chatPanel.classList.add('hidden');
                infoPanel.classList.add('active');
            }
        });
    });

    // --- Load Stats ---
    async function loadStats() {
        try {
            const data = await apiGet('/api/stats');
            const qb = data.question_bank || {};

            document.getElementById('statTotal').textContent = qb.total_questions || qb.total || 0;
            document.getElementById('statInterviews').textContent = (data.interviews && data.interviews.total_count) || 0;
            document.getElementById('statApplications').textContent = (data.applications && data.applications.total) || 0;

            // Categories
            const catContainer = document.getElementById('statCategories');
            catContainer.innerHTML = '';
            if (qb.categories) {
                Object.entries(qb.categories).forEach(([name, count]) => {
                    const item = document.createElement('div');
                    item.className = 'category-item';
                    item.innerHTML = `<span class="cat-name">${name}</span><span class="cat-count">${count}</span>`;
                    catContainer.appendChild(item);
                });
            }
        } catch (err) {
            console.warn('加载统计信息失败:', err);
        }
    }

    // --- Load Profile Summary ---
    async function loadProfile() {
        const profileContent = document.getElementById('profileContent');
        const profileLoading = document.getElementById('profileLoading');
        const profileBrief = document.getElementById('profileBrief');

        try {
            const data = await apiGet('/api/profile/summary');
            const brief = data.brief || data.summary || '暂无画像数据';
            profileBrief.textContent = brief;
            profileLoading.style.display = 'none';
            profileContent.style.display = 'block';
        } catch (err) {
            profileLoading.textContent = '暂无画像数据';
            console.warn('加载画像失败:', err);
        }
    }

    // --- Action Buttons ---
    document.getElementById('btnSync').addEventListener('click', async function () {
        const btn = this;
        const statusEl = document.getElementById('syncStatus');
        btn.disabled = true;
        statusEl.textContent = '同步中...';

        try {
            const data = await apiPost('/api/sync/run?dry_run=false', {});
            statusEl.textContent = `同步完成：${data.message || '成功'}`;
            // Reload stats after sync
            setTimeout(loadStats, 1000);
        } catch (err) {
            statusEl.textContent = '同步失败，请稍后重试';
            showError('同步失败');
        }
        btn.disabled = false;
    });

    document.getElementById('btnAdvice').addEventListener('click', async function () {
        const btn = this;
        btn.disabled = true;

        try {
            const data = await apiGet('/api/profile/advice');
            const advice = data.advice || data.content || JSON.stringify(data);
            addMessage('system', '💡 **改进建议**\n\n' + advice);
        } catch (err) {
            showError('获取建议失败');
        }
        btn.disabled = false;
    });

    document.getElementById('btnEncourage').addEventListener('click', async function () {
        const btn = this;
        btn.disabled = true;

        try {
            const data = await apiGet('/api/profile/encouragement');
            const text = data.encouragement || data.content || data.message || JSON.stringify(data);
            addMessage('system', '🎉 ' + text);
        } catch (err) {
            showError('获取鼓励失败');
        }
        btn.disabled = false;
    });

    // --- Load History (Sessions) ---
    async function loadHistory() {
        const historyList = document.getElementById('historyList');
        if (!historyList) return;
        try {
            const data = await apiGet('/api/history/sessions?limit=20');
            const sessions = data.sessions || [];
            if (sessions.length === 0) {
                historyList.innerHTML = '<div class="loading-placeholder">暂无记录</div>';
                return;
            }
            historyList.innerHTML = '';
            sessions.forEach(s => {
                const item = document.createElement('div');
                item.className = 'history-item' + (s.id === currentSessionId ? ' active' : '');
                item.innerHTML = `
                    <div class="history-question">${s.title}</div>
                    <div class="history-meta">${s.updated_at.slice(5, 16).replace('T', ' ')} · ${s.message_count}条</div>
                `;
                item.addEventListener('click', () => loadSession(s.id));
                historyList.appendChild(item);
            });
        } catch (err) {
            historyList.innerHTML = '<div class="loading-placeholder">加载失败</div>';
        }
    }

    // --- Load Session ---
    async function loadSession(sessionId) {
        try {
            const data = await apiGet(`/api/history/sessions/${sessionId}`);
            const session = data.session;
            currentSessionId = session.id;

            // 清空聊天区域并还原消息
            chatMessages.innerHTML = '';
            session.messages.forEach(msg => {
                if (msg.role === 'user') {
                    addMessage('user', msg.content);
                } else {
                    addMessage('assistant', msg.content);
                }
            });

            loadHistory(); // 刷新列表高亮
        } catch (err) {
            showError('加载会话失败');
        }
    }

    // --- Create New Session ---
    async function createNewSession() {
        try {
            const data = await apiPost('/api/history/sessions', {});
            currentSessionId = data.session.id;
            // 清空聊天区域
            chatMessages.innerHTML = `
                <div class="welcome-message">
                    <div class="welcome-icon">💬</div>
                    <h2>新对话</h2>
                    <p>输入面试相关问题开始。</p>
                    <div class="welcome-tips">
                        <span class="tip" data-question="什么是 ReAct？">什么是 ReAct？</span>
                        <span class="tip" data-question="解释一下 RAG 的原理">RAG 的原理</span>
                        <span class="tip" data-question="Python GIL 是什么？">Python GIL</span>
                    </div>
                </div>`;
            // 重新绑定 tips 点击事件
            chatMessages.querySelectorAll('.welcome-tips .tip').forEach(tip => {
                tip.addEventListener('click', () => {
                    const q = tip.dataset.question;
                    if (q) sendQuestion(q);
                });
            });
            loadHistory();
        } catch (err) {
            showError('创建会话失败');
        }
    }

    // --- New Chat Button ---
    document.getElementById('btnNewChat').addEventListener('click', createNewSession);

    // --- Voice Input Module ---
    let voiceWs = null;
    let isRecording = false;
    let voiceAudioContext = null;
    let voiceMediaRefs = null;  // {stream, source, processor}

    document.getElementById('btnVoice').addEventListener('click', toggleVoice);

    function toggleVoice() {
        if (isRecording) {
            stopVoice();
        } else {
            startVoice();
        }
    }

    async function startVoice() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: 16000,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                }
            });

            // 连接后端 WebSocket
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${location.host}/api/asr/ws`;
            voiceWs = new WebSocket(wsUrl);

            voiceWs.onopen = () => {
                voiceWs.send('START');
                isRecording = true;
                document.getElementById('btnVoice').classList.add('recording');
            };

            voiceWs.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    // data.type = "partial" | "final"
                    // data.text = 识别的文字
                    const input = document.getElementById('chatInput');
                    if (data.text) {
                        input.value = data.text;
                        autoResizeInput();
                    }
                } catch (e) {
                    console.warn('解析语音结果失败:', e);
                }
            };

            voiceWs.onerror = () => {
                stopVoice();
                showError('语音连接失败');
            };

            voiceWs.onclose = () => {
                // 连接关闭时确保状态重置
                if (isRecording) {
                    stopVoice();
                }
            };

            // 使用 AudioContext + ScriptProcessorNode 获取 PCM 数据
            voiceAudioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
            const source = voiceAudioContext.createMediaStreamSource(stream);
            const processor = voiceAudioContext.createScriptProcessor(4096, 1, 1);

            processor.onaudioprocess = (e) => {
                if (!isRecording || !voiceWs || voiceWs.readyState !== WebSocket.OPEN) return;
                const inputData = e.inputBuffer.getChannelData(0);
                // 转为 16bit PCM
                const pcm = new Int16Array(inputData.length);
                for (let i = 0; i < inputData.length; i++) {
                    pcm[i] = Math.max(-32768, Math.min(32767, inputData[i] * 32768));
                }
                voiceWs.send(pcm.buffer);
            };

            source.connect(processor);
            processor.connect(voiceAudioContext.destination);

            // 保存引用以便停止
            voiceMediaRefs = { stream, source, processor };
        } catch (err) {
            showError('无法访问麦克风: ' + err.message);
        }
    }

    function stopVoice() {
        isRecording = false;
        document.getElementById('btnVoice').classList.remove('recording');

        if (voiceWs && voiceWs.readyState === WebSocket.OPEN) {
            voiceWs.send('STOP');
            // 等一下收最终结果再关闭
            setTimeout(() => {
                if (voiceWs) {
                    voiceWs.close();
                    voiceWs = null;
                }
            }, 2000);
        } else {
            voiceWs = null;
        }

        if (voiceMediaRefs) {
            voiceMediaRefs.processor.disconnect();
            voiceMediaRefs.source.disconnect();
            voiceMediaRefs.stream.getTracks().forEach(t => t.stop());
            voiceMediaRefs = null;
        }

        if (voiceAudioContext) {
            voiceAudioContext.close();
            voiceAudioContext = null;
        }
    }

    // --- Initialize ---
    async function init() {
        loadStats();
        loadProfile();
        await createNewSession();  // 自动创建会话
        chatInput.focus();
    }

    // Start
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
