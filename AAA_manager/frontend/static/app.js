// ===== 面试助手 - 前端交互逻辑 =====

(function () {
    'use strict';

    // --- State ---
    let currentMode = 'interview';
    let isStreaming = false;
    let currentSessionId = '';  // 当前会话ID
    let currentTurnEl = null;  // 当前轮次容器

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

    function showToast(message) {
        const toast = document.createElement('div');
        toast.className = 'success-toast';
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

        if (type === 'user') {
            // 新问题：创建新轮次容器，插入到顶部
            currentTurnEl = document.createElement('div');
            currentTurnEl.className = 'chat-turn';
            chatMessages.prepend(currentTurnEl);
            currentTurnEl.appendChild(msgEl);
        } else {
            // 回答：追加到当前轮次（问题下方）
            if (!currentTurnEl) {
                currentTurnEl = document.createElement('div');
                currentTurnEl.className = 'chat-turn';
                chatMessages.prepend(currentTurnEl);
            }
            currentTurnEl.appendChild(msgEl);
        }

        scrollToTop();
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

        // 追加到当前轮次（用户问题下方）
        if (!currentTurnEl) {
            currentTurnEl = document.createElement('div');
            currentTurnEl.className = 'chat-turn';
            chatMessages.prepend(currentTurnEl);
        }
        currentTurnEl.appendChild(msgEl);
        scrollToTop();
        return msgEl;
    }

    function updateStreamingMessage(content) {
        const msgEl = document.getElementById('streamingMsg');
        if (!msgEl) return;
        const bubble = msgEl.querySelector('.message-bubble');
        bubble.innerHTML = renderMarkdown(content);
        // 不强制滚动，让用户可以自由查看
    }

    /**
     * 将搜索结果区域折叠为可展开/收起的块
     */
    function collapseSearchResults(searchContent) {
        const msgEl = document.getElementById('streamingMsg');
        if (!msgEl || !searchContent.trim()) return;
        const bubble = msgEl.querySelector('.message-bubble');

        // 构建折叠容器
        const wrapper = document.createElement('div');
        wrapper.className = 'search-results-collapsible collapsed';

        const toggle = document.createElement('div');
        toggle.className = 'search-results-toggle';
        toggle.innerHTML = '<span class="search-toggle-icon">📎</span> <span class="search-toggle-text">相关资料</span> <span class="search-toggle-hint">(点击展开)</span>';
        toggle.addEventListener('click', () => {
            wrapper.classList.toggle('collapsed');
            const hint = toggle.querySelector('.search-toggle-hint');
            if (wrapper.classList.contains('collapsed')) {
                hint.textContent = '(点击展开)';
            } else {
                hint.textContent = '(点击收起)';
            }
        });

        const body = document.createElement('div');
        body.className = 'search-results-body';
        body.innerHTML = renderMarkdown(searchContent);

        wrapper.appendChild(toggle);
        wrapper.appendChild(body);

        // 替换 bubble 内容为折叠块 + LLM 内容区
        bubble.innerHTML = '';
        bubble.appendChild(wrapper);

        // 创建 LLM 输出区域
        const llmArea = document.createElement('div');
        llmArea.className = 'llm-answer-area';
        bubble.appendChild(llmArea);
    }

    /**
     * 更新流式消息（折叠模式下仅更新 LLM 输出区域）
     */
    function updateStreamingMessageWithCollapsed(content) {
        const msgEl = document.getElementById('streamingMsg');
        if (!msgEl) return;
        const bubble = msgEl.querySelector('.message-bubble');
        const llmArea = bubble.querySelector('.llm-answer-area');
        if (llmArea) {
            llmArea.innerHTML = renderMarkdown(content);
        } else {
            // fallback: 没有折叠结构就直接更新
            bubble.innerHTML = renderMarkdown(content);
        }
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

        scrollToTop();
    }

    function renderMarkdown(text) {
        if (!text) return '';
        if (window.marked) {
            return marked.parse(text);
        }
        return text.replace(/\n/g, '<br>');
    }

    function scrollToTop() {
        requestAnimationFrame(() => {
            chatMessages.scrollTop = 0;
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
            let preSearchContent = '';  // 搜索阶段的内容
            let llmStarted = false;    // LLM 是否已开始输出
            let sourcesReceived = false; // 是否已收到 sources 事件

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
                                if (!sourcesReceived) {
                                    // sources 之前的内容属于搜索阶段
                                    preSearchContent += parsed.data || '';
                                    fullContent += parsed.data || '';
                                    updateStreamingMessage(fullContent);
                                } else {
                                    // sources 之后第一个 content 到来 → LLM 正式开始
                                    if (!llmStarted) {
                                        llmStarted = true;
                                        collapseSearchResults(preSearchContent);
                                        // 重置 fullContent 为仅 LLM 内容（折叠区域独立展示）
                                        fullContent = '';
                                    }
                                    fullContent += parsed.data || '';
                                    updateStreamingMessageWithCollapsed(fullContent);
                                }
                            } else if (parsed.type === 'sources') {
                                extras.sources = parsed.data;
                                sourcesReceived = true;
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
            setTimeout(() => pollFollowups(currentSessionId), 4000);
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
            setTimeout(() => pollFollowups(currentSessionId), 4000);
        }
    }

    // --- Followup Prediction ---
    async function pollFollowups(sessionId) {
        // 最多轮询 5 次，间隔 5 秒（之前 2s 太频、会刷屏 app.log）
        for (let i = 0; i < 5; i++) {
            try {
                const data = await apiGet(`/api/followup/${sessionId}`);
                if (data.ready && data.followups.length > 0) {
                    showFollowups(data.followups);
                    return;
                }
            } catch (e) { /* ignore */ }
            await new Promise(r => setTimeout(r, 5000));
        }
    }

    function showFollowups(followups) {
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
        // 追加到当前轮次容器
        if (currentTurnEl) {
            currentTurnEl.appendChild(div);
        } else {
            chatMessages.prepend(div);
        }
        scrollToTop();
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
            const navPanel = document.getElementById('navPanel');

            // 隐藏所有面板
            chatPanel.classList.add('hidden');
            infoPanel.classList.remove('active');
            if (navPanel) navPanel.classList.remove('active');

            if (panel === 'chat') {
                chatPanel.classList.remove('hidden');
            } else if (panel === 'info') {
                infoPanel.classList.add('active');
            } else if (panel === 'nav') {
                chatPanel.classList.remove('hidden');
                if (navPanel) navPanel.classList.add('active');
            }
        });
    });

    // --- Nav Panel Toggle (hamburger for mobile) ---
    const btnNavToggle = document.getElementById('btnNavToggle');
    if (btnNavToggle) {
        btnNavToggle.addEventListener('click', () => {
            const navPanel = document.getElementById('navPanel');
            if (navPanel) {
                navPanel.classList.toggle('active');
            }
        });
    }

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

    // --- 岗位备战弹窗 ---
    const prepareModal = document.getElementById('prepareModal');
    const prepareResult = document.getElementById('prepareResult');

    function openPrepareModal() {
        if (!prepareModal) return;
        prepareModal.style.display = 'flex';
        if (prepareResult) prepareResult.innerHTML = '';
    }
    function closePrepareModal() {
        if (!prepareModal) return;
        prepareModal.style.display = 'none';
    }

    const btnPrepare = document.getElementById('btnPrepare');
    if (btnPrepare) btnPrepare.addEventListener('click', openPrepareModal);
    const btnPrepareClose = document.getElementById('btnPrepareClose');
    if (btnPrepareClose) btnPrepareClose.addEventListener('click', closePrepareModal);
    if (prepareModal) {
        prepareModal.addEventListener('click', (e) => {
            if (e.target === prepareModal) closePrepareModal();
        });
    }

    const btnPrepareRun = document.getElementById('btnPrepareRun');
    if (btnPrepareRun) {
        btnPrepareRun.addEventListener('click', async function () {
            const company = (document.getElementById('prepCompany').value || '').trim();
            const position = (document.getElementById('prepPosition').value || '').trim();
            const date = (document.getElementById('prepDate').value || '').trim() || null;
            const countRaw = document.getElementById('prepCount').value;
            const count = countRaw ? parseInt(countRaw, 10) : null;

            if (!company || !position) {
                showError('请填写公司和岗位');
                return;
            }
            this.disabled = true;
            if (prepareResult) prepareResult.innerHTML = '⚙️ 正在搜索 JD 并生成预测题…大约耗时 20-60s';

            try {
                const data = await apiPost('/api/prepare/run', { company, position, date, count });
                const msg = `✅ 生成完成：<b>${data.question_count}</b> 题`
                    + `<br>📄 文件：<code>${data.output_filename}</code>`
                    + `<br>🔍 JD 片段 ${data.jd_snippet_count} 条，来源 URL ${data.jd_source_count} 个，耗时 ${data.elapsed_sec}s`
                    + `<br>💡 现在可在左侧模拟面试直接搜索这些预测题复习`;
                if (prepareResult) prepareResult.innerHTML = msg;
                addMessage('system', `🎯 **岗位备战完成**\n\n- 公司：${data.company}\n- 岗位：${data.position}\n- 题库文件：\`${data.output_filename}\`\n- 生成题数：${data.question_count}\n- JD 片段：${data.jd_snippet_count}\n\n${data.hint || ''}`);
                setTimeout(loadStats, 600);
            } catch (err) {
                if (prepareResult) prepareResult.innerHTML = '❌ 生成失败，请检查后端日志';
                showError('岗位备战生成失败');
            }
            this.disabled = false;
        });
    }

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
                    <div class="history-actions">
                        <button class="history-action-btn process-btn" title="问题提取">⚡</button>
                        <button class="history-action-btn delete-btn" title="删除会话">🗑️</button>
                    </div>
                `;
                item.addEventListener('click', (e) => {
                    if (e.target.closest('.history-actions')) return;
                    loadSession(s.id);
                });
                item.querySelector('.process-btn').addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (s.message_count === 0) {
                        showError('空会话无法处理');
                        return;
                    }
                    openPipelineModal(s.id, s.title, s.updated_at);
                });
                item.querySelector('.delete-btn').addEventListener('click', async (e) => {
                    e.stopPropagation();
                    if (!confirm(`确定删除会话「${s.title}」？`)) return;
                    try {
                        await fetch(`/api/history/sessions/${s.id}`, { method: 'DELETE' });
                        if (s.id === currentSessionId) {
                            await createNewSession();
                        }
                        loadHistory();
                        showToast('会话已删除');
                    } catch (err) {
                        showError('删除失败');
                    }
                });
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
            currentTurnEl = null;
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
            currentTurnEl = null;
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

    // --- Export Modal ---
    let exportModalEl = null;

    function createExportModal() {
        const mask = document.createElement('div');
        mask.className = 'modal-mask';
        mask.id = 'exportModal';
        mask.style.display = 'none';
        mask.innerHTML = `
            <div class="modal-panel">
                <div class="modal-header">
                    <h3>📤 导出面试问题</h3>
                    <button class="modal-close" id="exportModalClose">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="modal-hint">将会话中的面试问题导出到「面试原始问题」目录</div>
                    <div class="form-field">
                        <label>文件名（不含 .md）</label>
                        <input type="text" id="exportFilename" placeholder="留空则自动命名" />
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="action-btn" id="exportCancel" style="max-width:80px;text-align:center;margin-right:8px;">取消</button>
                    <button class="action-btn" id="exportConfirm" style="max-width:80px;text-align:center;background:var(--primary);color:white;border-color:var(--primary);">确认</button>
                </div>
            </div>
        `;
        document.body.appendChild(mask);
        exportModalEl = mask;

        // 绑定事件
        mask.querySelector('#exportModalClose').addEventListener('click', closeExportModal);
        mask.querySelector('#exportCancel').addEventListener('click', closeExportModal);
        mask.addEventListener('click', (e) => {
            if (e.target === mask) closeExportModal();
        });
    }

    function openExportModal(sessionId, sessionTitle) {
        if (!exportModalEl) createExportModal();
        exportModalEl.style.display = 'flex';
        const input = exportModalEl.querySelector('#exportFilename');
        input.value = sessionTitle || '';
        input.focus();
        input.select();

        // 重新绑定确认按钮（避免闭包残留）
        const confirmBtn = exportModalEl.querySelector('#exportConfirm');
        const newConfirm = confirmBtn.cloneNode(true);
        confirmBtn.parentNode.replaceChild(newConfirm, confirmBtn);
        newConfirm.addEventListener('click', () => doExport(sessionId));

        // Enter 键确认
        input.onkeydown = (e) => {
            if (e.key === 'Enter') doExport(sessionId);
        };
    }

    function closeExportModal() {
        if (exportModalEl) exportModalEl.style.display = 'none';
    }

    async function doExport(sessionId) {
        const input = exportModalEl.querySelector('#exportFilename');
        const filename = input.value.trim() || null;
        const confirmBtn = exportModalEl.querySelector('#exportConfirm');
        confirmBtn.disabled = true;
        confirmBtn.textContent = '导出中…';

        try {
            const data = await apiPost(`/api/history/sessions/${sessionId}/export`, { filename });
            closeExportModal();
            showToast(`导出成功：${data.count} 个问题 → ${data.file}`);
        } catch (err) {
            showError('导出失败：' + err.message);
        } finally {
            confirmBtn.disabled = false;
            confirmBtn.textContent = '确认';
        }
    }

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

    // --- Pipeline Modal ---
    function openPipelineModal(sessionId, title, updatedAt) {
        const modal = document.getElementById('pipelineModal');
        const input = document.getElementById('pipelineFilename');

        // 预填默认文件名：模拟面试_{日期}
        const dateStr = updatedAt ? updatedAt.slice(2, 10).replace(/-/g, '').slice(0, 6) : new Date().toISOString().slice(2, 10).replace(/-/g, '').slice(0, 6);
        input.value = `模拟面试_${dateStr}`;
        input.placeholder = `如：字节跳动_大厂_${dateStr}_技术一面`;

        modal.style.display = 'flex';
        input.focus();
        input.select();

        // 存储当前处理的 session 信息
        modal._sessionId = sessionId;
        modal._title = title;
    }

    // 取消按钮
    document.getElementById('btnPipelineCancel').addEventListener('click', () => {
        document.getElementById('pipelineModal').style.display = 'none';
    });

    // 开始处理按钮
    document.getElementById('btnPipelineRun').addEventListener('click', async () => {
        const modal = document.getElementById('pipelineModal');
        const filename = document.getElementById('pipelineFilename').value.trim();
        const sessionId = modal._sessionId;

        if (!filename) {
            showError('请输入文件名');
            return;
        }

        modal.style.display = 'none';
        showToast('开始提取问题...');

        try {
            const res = await fetch(`/api/sync/session-pipeline/${sessionId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename: filename })
            });
            if (!res.ok) throw new Error(`请求失败: ${res.status}`);
            const data = await res.json();

            // 构建结果消息
            let msg = '⚡ **问题提取完成**\n\n';
            data.steps.forEach(step => {
                const icon = step.status === 'ok' ? '✅' : step.status === 'skipped' ? '⏭️' : '❌';
                const stepName = {extract: '问题抽取', review: '面试复盘', archive: '问题入库'}[step.step];
                msg += `${icon} ${stepName}`;
                if (step.count) msg += ` (${step.count}题)`;
                if (step.archived_count !== undefined) msg += ` (入库${step.archived_count}题, 跳过${step.skipped_count}题)`;
                if (step.file) msg += ` → ${step.file}`;
                if (step.error) msg += ` - ${step.error}`;
                if (step.reason) msg += ` - ${step.reason}`;
                msg += '\n';
            });

            addMessage('system', msg);
            showToast('问题提取完成');
            loadStats();
        } catch (err) {
            showError('处理失败: ' + err.message);
        }
    });

    // 点击遮罩关闭
    document.getElementById('pipelineModal').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) {
            e.currentTarget.style.display = 'none';
        }
    });

    // ESC 键关闭弹窗
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const pipelineModal = document.getElementById('pipelineModal');
            if (pipelineModal && pipelineModal.style.display !== 'none') {
                pipelineModal.style.display = 'none';
            }
        }
    });

    // --- Initialize ---
    async function init() {
        loadStats();
        loadProfile();
        await createNewSession();  // 自动创建会话
        // 清理空会话（排除当前刚创建的会话）
        try {
            await fetch('/api/history/sessions/cleanup-empty', { method: 'DELETE' });
        } catch (e) { /* ignore */ }
        loadHistory();  // 刷新列表
        chatInput.focus();
    }

    // Start
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
