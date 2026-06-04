(() => {
  const config = window.STUDIO_CONFIG || {};
  const state = {
    sessions: [],
    session: null,
    ws: null,
    streaming: false,
    health: null,
    activePanel: 'schema',
    activeStreamId: null,
    reconnectTimer: null,
    importingGraph: false,
    importResult: null,
    importError: '',
    selectedGraphFileName: '',
    selectedGraphId: localStorage.getItem('kbqa_graph_scope_id') || '',
    graphSummary: null,
    summaryLoading: false,
    summaryError: '',
    deletingGraphId: '',
    deletingSessionId: '',
    confirmingDeleteSessionId: '',
    creatingSession: false,
    isComposing: false,
    compositionEndedAt: 0,
    suppressNextEnter: false,
    compositionGuardTimer: null,
    liveToolKey: '',
    activeModelDeltaKey: '',
    suppressModelOutputSync: false,
    resetModelOutputOnNextDelta: false,
  };

  const $ = (selector) => document.querySelector(selector);
  const els = {
    brandHome: $('#brand-home'),
    status: $('#status-pill'),
    model: $('#model-chip'),
    historyBtn: $('#history-btn'),
    themeToggle: $('#theme-toggle'),
    newChat: $('#new-chat'),
    hero: $('#hero'),
    heroUpload: $('#hero-upload-graph'),
    capabilitySection: $('#capability-section'),
    exampleSection: $('#example-section'),
    promptGrid: $('#prompt-grid'),
    messages: $('#messages'),
    input: $('#message-input'),
    send: $('#send-button'),
    runIndicator: $('#run-indicator'),
    runDetail: $('#run-detail'),
    resetRun: $('#reset-run'),
    graphScopeSelect: $('#graph-scope-select'),
    graphScopeHint: $('#graph-scope-hint'),
    fabContainer: $('#fab-container'),
    fabMain: $('#fab-main'),
    fabSchema: $('#fab-schema'),
    fabImport: $('#fab-import'),
    panel: $('#activities-panel'),
    closePanel: $('#close-panel'),
    tabs: document.querySelectorAll('.panel-tab'),
    schemaContent: $('#schema-content'),
    importContent: $('#import-content'),
    skillCount: $('#skill-count'),
    toolCount: $('#tool-count'),
    historyOverlay: $('#history-overlay'),
    historyModal: $('#history-modal'),
    closeHistory: $('#close-history'),
    historyNewChat: $('#history-new-chat'),
    sessionCount: $('#session-count'),
    sessions: $('#session-list'),
    scrollTop: null,
  };

  document.addEventListener('DOMContentLoaded', init);

  async function init() {
    if ('scrollRestoration' in window.history) {
      window.history.scrollRestoration = 'manual';
    }
    applySavedTheme();
    bindEvents();
    await loadHealth();
    await loadSessions();
    showLandingPage({ scrollTop: true });
    document.body.style.opacity = '1';
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    return response.json();
  }

  async function loadHealth() {
    try {
      state.health = await api('/api/health');
      normalizeSelectedGraph();
      const model = state.health.model || 'Model';
      els.model.textContent = shortenModel(model);
      els.status.classList.toggle('ready', Boolean(state.health.api_key_present));
      els.status.classList.toggle('warn', !state.health.api_key_present);
      els.status.querySelector('span:last-child').textContent = state.health.api_key_present
        ? 'Runtime ready'
        : 'Missing API key';
      renderHeroMetrics();
    } catch (error) {
      state.health = null;
      els.status.classList.add('warn');
      els.status.querySelector('span:last-child').textContent = 'Runtime unavailable';
    }
    await loadGraphSummary(state.selectedGraphId || '', { silent: true });
    renderSchemaPanel();
    renderImportPanel();
    renderGraphScopeSelector();
  }

  async function loadGraphSummary(graphId = state.selectedGraphId || '', options = {}) {
    state.summaryLoading = true;
    state.summaryError = '';
    if (!options.silent) renderSchemaPanel();
    try {
      const query = graphId ? `?graph_id=${encodeURIComponent(graphId)}` : '';
      state.graphSummary = await api(`/api/graphs/summary${query}`);
    } catch (error) {
      state.graphSummary = null;
      state.summaryError = String(error.message || error);
    } finally {
      state.summaryLoading = false;
      if (!options.silent) renderSchemaPanel();
    }
  }

  async function loadSessions() {
    const data = await api('/api/sessions');
    state.sessions = data.sessions || [];
    renderSessionList();
  }

  function graphCatalog() {
    const health = state.health || {};
    if (Array.isArray(health.graph_catalog)) return health.graph_catalog;
    if (Array.isArray(health.custom_graph_imports)) return health.custom_graph_imports;
    return [];
  }

  function renderHeroMetrics() {
    const project = (state.health && state.health.project) || {};
    const skillCount = (project.skills || []).length || 3;
    const toolCount = (project.tools || []).length || 6;
    if (els.skillCount) els.skillCount.textContent = `${skillCount} reasoning skills`;
    if (els.toolCount) els.toolCount.textContent = `${toolCount} graph tools`;
  }

  function selectedGraph() {
    return graphCatalog().find((item) => item.id === state.selectedGraphId) || null;
  }

  function normalizeSelectedGraph() {
    if (!state.selectedGraphId) return;
    if (!selectedGraph()) {
      state.selectedGraphId = '';
      localStorage.setItem('kbqa_graph_scope_id', '');
    }
  }

  function renderGraphScopeSelector() {
    if (!els.graphScopeSelect) return;
    const graphs = graphCatalog();
    const current = selectedGraph();
    const options = [
      '<option value="">All graphs · complete ledger</option>',
      ...graphs.map((graph) => {
        const stats = graph.stats || {};
        const label = `${graph.name || graph.id || 'Graph'} · ${stats.triple_count || 0} triples`;
        return `<option value="${escapeHtml(graph.id || '')}">${escapeHtml(label)}</option>`;
      }),
    ];
    els.graphScopeSelect.innerHTML = options.join('');
    els.graphScopeSelect.value = current ? current.id : '';
    if (els.graphScopeHint) {
      els.graphScopeHint.textContent = current
        ? `Chat is scoped to ${current.name || current.id}`
        : `Chat uses the complete graph ledger (${graphs.length} graphs)`;
    }
  }

  async function createSession() {
    const data = await api('/api/sessions', { method: 'POST' });
    await loadSessions();
    await openSession(data.session.id);
    closeHistory();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async function ensureActiveSession() {
    if (!state.session) {
      state.creatingSession = true;
      updateSendState();
      try {
        const data = await api('/api/sessions', { method: 'POST' });
        await loadSessions();
        await openSession(data.session.id);
      } finally {
        state.creatingSession = false;
        updateSendState();
      }
    }
    if (!isSocketReady()) {
      await waitForSocketReady();
    }
  }

  function showLandingPage(options = {}) {
    disconnectSocket();
    state.session = null;
    state.activeStreamId = null;
    state.liveToolKey = '';
    state.activeModelDeltaKey = '';
    state.suppressModelOutputSync = false;
    state.resetModelOutputOnNextDelta = false;
    resetRunUi();
    renderAll();
    if (options.scrollTop) {
      requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: 'auto' }));
    }
  }

  async function openSession(sessionId) {
    const data = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
    state.session = data.session;
    state.activeStreamId = null;
    state.liveToolKey = '';
    resetRunUi();
    connect(sessionId);
    renderAll();
  }

  function connect(sessionId) {
    disconnectSocket();
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/${sessionId}`);
    ws.onopen = updateSendState;
    ws.onmessage = (event) => handleSocketMessage(JSON.parse(event.data));
    ws.onclose = () => {
      if (state.ws !== ws) return;
      state.ws = null;
      updateSendState();
      if (state.session && state.session.id === sessionId) {
        resetRunUi();
        state.reconnectTimer = window.setTimeout(() => {
          if (!state.ws && state.session && state.session.id === sessionId) {
            connect(sessionId);
          }
        }, 1600);
      }
    };
    ws.onerror = updateSendState;
    state.ws = ws;
  }

  function disconnectSocket() {
    clearReconnectTimer();
    if (!state.ws) return;
    const oldSocket = state.ws;
    state.ws = null;
    oldSocket.close();
  }

  function handleSocketMessage(message) {
    if (message.type === 'history') {
      state.session = message.session;
      state.activeStreamId = null;
      state.activeModelDeltaKey = '';
      state.suppressModelOutputSync = false;
      resetRunUi();
      renderAll();
      return;
    }

    if (message.type === 'message') {
      upsertMessage(message.message);
      return;
    }

    if (message.type === 'run_start') {
      state.streaming = true;
      state.activeStreamId = message.stream_id || `stream-${message.run_id}`;
      state.liveToolKey = '';
      state.activeModelDeltaKey = '';
      state.suppressModelOutputSync = false;
      state.resetModelOutputOnNextDelta = false;
      els.runIndicator.classList.add('active');
      els.runDetail.textContent = `run ${message.run_id}`;
      updateSendState();
      renderMessages();
      renderSchemaPanel();
      return;
    }

    if (message.type === 'assistant_delta') {
      appendAssistantDelta(message);
      return;
    }

    if (message.type === 'event') {
      if (message.message && message.message.kind === 'model_output') {
        if (!state.suppressModelOutputSync) {
          syncActiveModelOutput(message.message);
        }
      } else {
        // Tool-only model turns should not blank the last text the model streamed.
        // The next assistant_delta/model_output will replace this preserved text.
        state.resetModelOutputOnNextDelta = true;
      }
      upsertMessage(message.message);
      renderSchemaPanel();
      return;
    }

    if (message.type === 'assistant_final') {
      const finalMessage = { ...message.message, streaming: false };
      state.activeStreamId = null;
      state.liveToolKey = '';
      state.activeModelDeltaKey = '';
      state.suppressModelOutputSync = false;
      state.resetModelOutputOnNextDelta = false;
      appendFinalAssistantMessage(finalMessage);
      return;
    }

    if (message.type === 'error') {
      upsertMessage(message.message);
      state.streaming = false;
      state.activeStreamId = null;
      state.activeModelDeltaKey = '';
      state.suppressModelOutputSync = false;
      state.resetModelOutputOnNextDelta = false;
      els.runIndicator.classList.remove('active');
      updateSendState();
      renderSchemaPanel();
      return;
    }

    if (message.type === 'run_done') {
      state.streaming = false;
      state.activeStreamId = null;
      state.liveToolKey = '';
      state.activeModelDeltaKey = '';
      state.suppressModelOutputSync = false;
      state.resetModelOutputOnNextDelta = false;
      els.runIndicator.classList.remove('active');
      updateSendState();
      loadSessions();
      loadHealth();
      renderSchemaPanel();
    }
  }

  function appendAssistantDelta(message) {
    if (!state.session || !message.delta) return;
    state.suppressModelOutputSync = false;
    const id = message.id || state.activeStreamId || 'stream-current';
    const modelDeltaKey = message.model_message_id || message.message_id || '';
    if (message.replace) {
      state.activeModelDeltaKey = modelDeltaKey;
      state.resetModelOutputOnNextDelta = true;
    } else if (modelDeltaKey && modelDeltaKey !== state.activeModelDeltaKey) {
      state.activeModelDeltaKey = modelDeltaKey;
      state.resetModelOutputOnNextDelta = true;
    }
    const existing = state.session.messages.find((item) => item.id === id);
    if (existing) {
      existing.content = state.resetModelOutputOnNextDelta
        ? message.delta
        : `${existing.content || ''}${message.delta}`;
      existing.streaming = true;
      existing.agent = message.agent || existing.agent || config.agentId;
      existing.timestamp = new Date().toISOString();
    } else {
      state.session.messages.push({
        id,
        role: 'assistant',
        content: message.delta,
        timestamp: new Date().toISOString(),
        streaming: true,
        agent: message.agent || config.agentId,
      });
    }
    state.resetModelOutputOnNextDelta = false;
    renderMessages();
    scrollToBottom();
  }

  function syncActiveModelOutput(message) {
    if (!state.session || !state.activeStreamId || !message || !message.content) return;
    const modelDeltaKey = message.model_message_id || message.message_id || '';
    if (modelDeltaKey) state.activeModelDeltaKey = modelDeltaKey;
    const existing = state.session.messages.find((item) => item.id === state.activeStreamId);
    if (existing) {
      existing.content = message.content;
      existing.streaming = true;
      existing.agent = message.agent || existing.agent || config.agentId;
      existing.timestamp = message.timestamp || new Date().toISOString();
    } else {
      state.session.messages.push({
        id: state.activeStreamId,
        role: 'assistant',
        content: message.content,
        timestamp: message.timestamp || new Date().toISOString(),
        streaming: true,
        agent: message.agent || config.agentId,
      });
    }
    // A complete model output just landed — any subsequent assistant_delta
    // belongs to a NEW model generation and must replace, not append.
    state.resetModelOutputOnNextDelta = true;
  }

  function clearActiveModelDraft() {
    if (!state.session || !state.activeStreamId) return;
    const existing = state.session.messages.find((item) => item.id === state.activeStreamId && item.role === 'assistant');
    if (existing) {
      existing.content = '';
      existing.streaming = true;
      existing.timestamp = new Date().toISOString();
      return;
    }
    state.session.messages.push({
      id: state.activeStreamId,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      streaming: true,
      agent: config.agentId,
    });
  }

  function upsertMessage(message, forceReplace = false) {
    if (!state.session || !message) return;
    const index = state.session.messages.findIndex((item) => item.id === message.id);
    if (index >= 0) {
      if (forceReplace || state.session.messages[index].content !== message.content) {
        state.session.messages[index] = { ...state.session.messages[index], ...message };
      }
    } else {
      state.session.messages.push(message);
    }
    renderMessages();
    renderTitleVisibility();
    scrollToBottom();
  }

  function appendFinalAssistantMessage(message) {
    if (!state.session || !message) return;
    state.session.messages = (state.session.messages || []).filter((item) => item.id !== message.id);
    state.session.messages.push(message);
    renderMessages();
    renderTitleVisibility();
    scrollToBottom();
  }

  function bindEvents() {
    els.brandHome.addEventListener('click', () => {
      showLandingPage({ scrollTop: true });
    });
    els.newChat.addEventListener('click', createSession);
    els.historyBtn.addEventListener('click', openHistory);
    els.closeHistory.addEventListener('click', closeHistory);
    els.historyOverlay.addEventListener('click', closeHistory);
    if (els.historyNewChat) {
      els.historyNewChat.addEventListener('click', createSession);
    }
    els.themeToggle.addEventListener('click', toggleTheme);
    els.send.addEventListener('click', sendCurrentMessage);
    els.resetRun.addEventListener('click', reconnectCurrentSession);
    if (els.heroUpload) {
      els.heroUpload.addEventListener('click', () => openPanel('import'));
    }
    document.querySelectorAll('.capability-card').forEach((button) => {
      button.addEventListener('click', () => {
        const panel = button.dataset.panel || '';
        if (panel) {
          openPanel(panel);
          return;
        }
        els.input.focus();
        window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
      });
    });
    if (els.graphScopeSelect) {
      els.graphScopeSelect.addEventListener('change', async () => {
        state.selectedGraphId = els.graphScopeSelect.value || '';
        localStorage.setItem('kbqa_graph_scope_id', state.selectedGraphId);
        renderGraphScopeSelector();
        await loadGraphSummary(state.selectedGraphId || '');
        renderImportPanel();
      });
    }
    els.input.addEventListener('input', () => {
      autoResize();
      updateSendState();
    });
    els.input.addEventListener('compositionstart', () => {
      state.isComposing = true;
      clearCompositionGuard();
    });
    els.input.addEventListener('compositionend', () => {
      state.isComposing = false;
      state.compositionEndedAt = Date.now();
      state.suppressNextEnter = true;
      if (state.compositionGuardTimer) window.clearTimeout(state.compositionGuardTimer);
      state.compositionGuardTimer = window.setTimeout(clearCompositionGuard, 180);
      autoResize();
      updateSendState();
    });
    els.input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        if (isComposingInput(event)) {
          if (state.suppressNextEnter && !state.isComposing && !event.isComposing && event.keyCode !== 229) {
            event.preventDefault();
            clearCompositionGuard();
          }
          return;
        }
        event.preventDefault();
        sendCurrentMessage();
      }
    });
    els.promptGrid.querySelectorAll('.question-card').forEach((button) => {
      button.addEventListener('click', () => {
        els.input.value = button.dataset.prompt || '';
        autoResize();
        updateSendState();
        sendCurrentMessage();
      });
    });
    setFabOpen(false);
    els.fabMain.addEventListener('click', () => {
      setFabOpen(!els.fabContainer.classList.contains('open'));
    });
    if (els.fabSchema) {
      els.fabSchema.addEventListener('click', () => openPanel('schema'));
    }
    if (els.fabImport) {
      els.fabImport.addEventListener('click', () => openPanel('import'));
    }
    els.closePanel.addEventListener('click', closePanel);
    els.tabs.forEach((tab) => {
      tab.addEventListener('click', () => openPanel(tab.dataset.tab || 'schema'));
    });

    document.addEventListener('keydown', (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n') {
        event.preventDefault();
        createSession();
      }
      if (event.key === 'Escape') {
        closeHistory();
        closePanel();
        setFabOpen(false, true);
      }
    });
  }

  async function sendCurrentMessage() {
    const content = els.input.value.trim();
    if (!content || state.streaming || state.creatingSession) return;
    try {
      await ensureActiveSession();
      if (!isSocketReady()) {
        throw new Error('Conversation channel is not ready yet.');
      }
      state.ws.send(JSON.stringify({ type: 'chat', content, graph_id: state.selectedGraphId || '' }));
      els.input.value = '';
      autoResize();
      updateSendState();
    } catch (error) {
      window.alert(`Unable to start the conversation: ${String(error.message || error)}`);
      updateSendState();
    }
  }

  function renderAll() {
    renderHeroMetrics();
    renderTitleVisibility();
    renderSessionList();
    renderMessages();
    renderSchemaPanel();
    renderImportPanel();
    renderGraphScopeSelector();
    updateSendState();
  }

  function renderTitleVisibility() {
    const messages = state.session ? state.session.messages || [] : [];
    const hasMessages = messages.length > 0;
    els.hero.classList.toggle('hidden', hasMessages);
    if (els.capabilitySection) els.capabilitySection.classList.toggle('hidden', hasMessages);
    els.exampleSection.classList.toggle('hidden', hasMessages);
    els.messages.classList.toggle('active', hasMessages);
  }

  function renderSessionList() {
    if (els.sessionCount) {
      els.sessionCount.textContent = `${state.sessions.length} saved`;
    }
    els.sessions.innerHTML = '';
    if (!state.sessions.length) {
      els.sessions.innerHTML = `
        <div class="history-empty">
          <span class="history-empty-icon">○</span>
          <strong>No saved conversations yet</strong>
          <p>Start from the homepage and your graph questions will appear here.</p>
          <button class="history-empty-action" type="button">Start a new chat</button>
        </div>
      `;
      const action = els.sessions.querySelector('.history-empty-action');
      if (action) action.addEventListener('click', createSession);
      return;
    }
    for (const session of state.sessions) {
      const card = document.createElement('div');
      const isOpen = Boolean(state.session && session.id === state.session.id);
      const isDeleting = state.deletingSessionId === session.id;
      const isConfirmingDelete = state.confirmingDeleteSessionId === session.id;
      const messageCount = Number(session.message_count || 0);
      card.className = `history-card${isOpen ? ' active' : ''}`;
      card.innerHTML = `
        <button class="history-load" type="button" data-session-open="${escapeHtml(session.id)}">
          <span class="history-orb"><span class="history-dot"></span></span>
          <span class="history-copy">
            <span class="history-name">${escapeHtml(session.title || 'New conversation')}</span>
            <span class="history-meta">
              <span>${formatMessageCount(messageCount)}</span>
              <span>${formatDate(session.updated_at)}</span>
            </span>
          </span>
          <span class="history-status">${isOpen ? 'Current' : 'Open'}</span>
        </button>
        <button class="history-delete${isConfirmingDelete ? ' confirming' : ''}" type="button" data-session-delete="${escapeHtml(session.id)}" aria-label="${isConfirmingDelete ? 'Confirm delete conversation' : 'Delete conversation'}" title="${isConfirmingDelete ? 'Click again to delete' : 'Delete conversation'}" ${isDeleting ? 'disabled' : ''}>
          ${isDeleting ? '<span class="delete-spinner"></span><span>Deleting</span>' : isConfirmingDelete ? '<span class="delete-icon">!</span><span>Confirm</span>' : '<span class="delete-icon">×</span><span>Delete</span>'}
        </button>
      `;
      card.querySelector('[data-session-open]').addEventListener('click', async () => {
        state.confirmingDeleteSessionId = '';
        await openSession(session.id);
        closeHistory();
      });
      card.querySelector('[data-session-delete]').addEventListener('click', async (event) => {
        event.stopPropagation();
        if (state.confirmingDeleteSessionId !== session.id) {
          state.confirmingDeleteSessionId = session.id;
          renderSessionList();
          return;
        }
        await deleteSession(session.id);
      });
      els.sessions.appendChild(card);
    }
  }

  async function deleteSession(sessionId) {
    if (!sessionId || state.deletingSessionId) return;
    state.deletingSessionId = sessionId;
    state.confirmingDeleteSessionId = '';
    renderSessionList();
    try {
      const deletingCurrent = Boolean(state.session && state.session.id === sessionId);
      await api(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
      await loadSessions();
      if (deletingCurrent) {
        showLandingPage({ scrollTop: true });
      } else {
        renderSessionList();
      }
    } catch (error) {
      window.alert(`Failed to delete conversation: ${String(error.message || error)}`);
    } finally {
      state.deletingSessionId = '';
      state.confirmingDeleteSessionId = '';
      renderSessionList();
    }
  }

  function renderMessages() {
    if (!state.session) {
      els.messages.innerHTML = '';
      renderTitleVisibility();
      return;
    }
    const messages = state.session.messages || [];
    const visibleMessages = buildTimelineItems(messages);
    renderTitleVisibility();
    els.messages.innerHTML = visibleMessages.map(renderMessage).join('');
    els.messages.querySelectorAll('.event-head').forEach((head) => {
      head.addEventListener('click', () => head.closest('.event-card').classList.toggle('open'));
    });
  }

  function isRenderableMessage(message) {
    return message.role !== 'event' && !isActiveAssistantDraft(message);
  }

  function isVisibleEvent(message) {
    return message.role === 'event' && message.kind !== 'model_output';
  }

  function buildTimelineItems(messages) {
    const liveRun = buildLiveRun(messages);
    const items = [];
    let insertedLiveRun = false;
    messages.forEach((message, index) => {
      if (isRenderableMessage(message)) {
        items.push(message);
      }
      if (liveRun && index === liveRun.afterIndex) {
        items.push(liveRun);
        insertedLiveRun = true;
      }
    });
    if (liveRun && !insertedLiveRun) {
      items.push(liveRun);
    }
    return items;
  }

  function buildLiveRun(messages) {
    if (!state.activeStreamId) return null;
    const assistantIndex = messages.findIndex((item) => item.id === state.activeStreamId);
    const afterIndex = findLastUserIndex(messages, assistantIndex >= 0 ? assistantIndex : messages.length);
    const runItems = messages.slice(afterIndex + 1);
    const draft = messages.find((item) => item.id === state.activeStreamId && item.role === 'assistant') || null;
    const latestModelOutput = findLast(runItems, (item) => item.role === 'event' && item.kind === 'model_output');
    const events = runItems.filter(isVisibleEvent);
    const currentTool = findLast(events, (item) => item.role === 'event');
    const toolKey = currentTool ? `${currentTool.id || ''}:${currentTool.kind || ''}:${currentTool.title || ''}` : '';
    const toolSwapped = Boolean(toolKey && toolKey !== state.liveToolKey);
    if (toolKey) state.liveToolKey = toolKey;
    return {
      id: `${state.activeStreamId}-live`,
      role: 'run_progress',
      agent: (draft && draft.agent) || (currentTool && currentTool.agent) || config.agentId,
      content: draft ? (draft.content || '') : ((latestModelOutput && latestModelOutput.content) || ''),
      currentTool,
      eventCount: events.length,
      toolSwapped,
      afterIndex,
    };
  }

  function isActiveAssistantDraft(message) {
    return Boolean(state.activeStreamId && message.role === 'assistant' && message.id === state.activeStreamId);
  }

  function findLastUserIndex(messages, beforeIndex) {
    for (let index = Math.min(beforeIndex - 1, messages.length - 1); index >= 0; index -= 1) {
      if (messages[index].role === 'user') return index;
    }
    return -1;
  }

  function findLast(items, predicate) {
    for (let index = items.length - 1; index >= 0; index -= 1) {
      if (predicate(items[index])) return items[index];
    }
    return null;
  }

  function isComposingInput(event) {
    return state.isComposing || event.isComposing || event.keyCode === 229 || state.suppressNextEnter;
  }

  function clearCompositionGuard() {
    state.suppressNextEnter = false;
    if (state.compositionGuardTimer) {
      window.clearTimeout(state.compositionGuardTimer);
      state.compositionGuardTimer = null;
    }
  }

  function renderMessage(message) {
    const streamingClass = message.streaming ? ' streaming' : '';
    if (message.role === 'user') {
      return `<article class="message user"><div class="bubble">${escapeHtml(message.content)}</div></article>`;
    }
    if (message.role === 'run_progress') {
      return renderLiveRun(message);
    }
    if (message.role === 'assistant') {
      return renderAssistantResult(message, streamingClass);
    }
    if (message.role === 'event') {
      const kind = message.kind || 'event';
      return `
        <article class="message event">
          <div class="event-card ${escapeHtml(kind)}">
            <div class="event-head">
              <div class="event-title"><span class="event-dot"></span><span>${escapeHtml(message.title || kind)}</span></div>
              <span class="event-agent">${escapeHtml(message.agent || '')}</span>
            </div>
            <div class="event-body"><pre>${escapeHtml(message.content || '')}</pre></div>
          </div>
        </article>
      `;
    }
    return `<article class="message system"><div class="bubble">${escapeHtml(message.content || '')}</div></article>`;
  }

  function renderLiveRun(run) {
    const modelOutput = run.content
      ? formatMarkdown(run.content)
      : '<span class="live-placeholder">Waiting for the model to stream text...</span>';
    return `
      <article class="message run-progress">
        <div class="avatar">${avatarLetter(run.agent)}</div>
        <div class="run-card">
          <div class="run-card-head">
            <div class="run-title"><span class="run-pulse"></span><span>Agent is working</span></div>
            <span class="run-count">${run.eventCount} tool updates</span>
          </div>
          <div class="run-tool-pane">
            <span class="run-section-label">Tool activity</span>
            ${renderCurrentTool(run.currentTool, run.toolSwapped)}
          </div>
          <div class="run-model-pane">
            <span class="run-section-label">Model output</span>
            <div class="run-model-output">${modelOutput}</div>
          </div>
        </div>
      </article>
    `;
  }

  function renderAssistantResult(message, streamingClass = '') {
    const output = message.content
      ? formatMarkdown(message.content)
      : '<span class="live-placeholder">No final answer was returned.</span>';
    return `
      <article class="message assistant run-result${streamingClass}">
        <div class="avatar">${avatarLetter(message.agent)}</div>
        <div class="run-card final-card">
          <div class="run-card-head">
            <div class="run-title"><span class="run-check">✓</span><span>Task complete</span></div>
            <span class="run-count">final answer</span>
          </div>
          <div class="run-tool-pane">
            <span class="run-section-label">Tool activity</span>
            <div class="current-tool-card complete">
              <div class="current-tool-topline">
                <span class="current-tool-status">Completed</span>
                <span class="current-tool-agent">${escapeHtml(message.agent || config.agentId || '')}</span>
              </div>
              <div class="current-tool-main">
                <strong>Model finished the task</strong>
                <span>Tool calls have settled; the final answer is ready below.</span>
              </div>
            </div>
          </div>
          <div class="run-model-pane final-answer">
            <span class="run-section-label">Final answer</span>
            <div class="run-model-output">${output}</div>
          </div>
        </div>
      </article>
    `;
  }

  function renderCurrentTool(tool, swapped) {
    if (!tool) {
      return `
        <div class="current-tool-card empty">
          <div class="current-tool-main">
            <strong>Preparing next action</strong>
            <span>The current tool call will appear here as soon as the agent starts one.</span>
          </div>
        </div>
      `;
    }
    const status = tool.kind === 'tool_call' ? 'Calling' : tool.kind === 'tool_end' ? 'Completed' : 'Update';
    const statusClass = tool.kind === 'tool_end' ? 'done' : tool.kind === 'tool_call' ? 'calling' : 'context';
    const preview = tool.content ? `<pre>${escapeHtml(truncate(tool.content, 900))}</pre>` : '';
    return `
      <div class="current-tool-card ${escapeHtml(statusClass)}${swapped ? ' tool-swapping' : ''}">
        <div class="current-tool-topline">
          <span class="current-tool-status">${escapeHtml(status)}</span>
          <span class="current-tool-agent">${escapeHtml(tool.agent || '')}</span>
        </div>
        <div class="current-tool-main">
          <strong>${escapeHtml(tool.title || tool.tool || tool.kind || 'Tool update')}</strong>
          <span>${escapeHtml(tool.tool || tool.kind || 'runtime')}</span>
        </div>
        ${preview ? `<div class="current-tool-preview">${preview}</div>` : ''}
      </div>
    `;
  }

  function renderSchemaPanel() {
    if (!els.schemaContent) return;
    const health = state.health || {};
    const project = health.project || {};
    els.schemaContent.innerHTML = renderKbqaSchema(project, health.graph_runtime || {});
    const explorerSelect = $('#graph-explorer-select');
    if (explorerSelect) {
      explorerSelect.addEventListener('change', async () => {
        state.selectedGraphId = explorerSelect.value || '';
        localStorage.setItem('kbqa_graph_scope_id', state.selectedGraphId);
        renderGraphScopeSelector();
        renderImportPanel();
        await loadGraphSummary(state.selectedGraphId || '');
      });
    }
    const refresh = $('#graph-explorer-refresh');
    if (refresh) refresh.addEventListener('click', () => loadGraphSummary(state.selectedGraphId || ''));
    const manage = $('#graph-explorer-manage');
    if (manage) manage.addEventListener('click', () => openPanel('import'));
  }

  function renderImportPanel() {
    if (!els.importContent) return;
    const imports = graphCatalog();
    const result = state.importResult && state.importResult.import ? state.importResult.import : null;
    const latest = result ? [result, ...imports.filter((item) => item.id !== result.id)] : imports;
    const fileName = state.selectedGraphFileName || '';
    const needsFile = Boolean(state.importError && state.importError.includes('choose a graph file') && !fileName && !state.importingGraph);
    els.importContent.innerHTML = `
      <div class="schema-hero kbqa-hero import-hero refined-import-hero management-hero">
        <div>
          <span class="schema-kicker">Graph Management</span>
          <h2>Add, select, and remove graph datasets.</h2>
          <p>Upload a named triple file, inspect the graph catalog, choose the scope used by chat, or delete datasets you no longer need.</p>
        </div>
        <div class="import-steps" aria-label="Graph import steps">
          <span><strong>1</strong>Upload triples</span>
          <span><strong>2</strong>Select chat scope</span>
          <span><strong>3</strong>Explore or delete</span>
        </div>
      </div>
      <form class="import-card refined-import-card" id="graph-import-form">
        <div class="import-field graph-name-field">
          <label class="field-label" for="graph-name">
            <span>Graph name</span>
            <small>A short display name used in the scope selector and graph catalog.</small>
          </label>
          <div class="graph-name-input-wrap">
            <span class="graph-name-icon">KG</span>
            <input id="graph-name" name="dataset_name" type="text" placeholder="qa-test-products">
          </div>
        </div>
        <div class="import-field">
          <div class="field-label">
            <span>Graph file</span>
            <small>TXT/TSV/CSV, JSON/JSONL, or Excel with subject, relation, object triples.</small>
          </div>
          <label class="file-dropzone ${fileName ? 'has-file' : ''}" for="graph-file">
            <input id="graph-file" class="file-picker-input" name="file" type="file" accept=".txt,.tsv,.csv,.json,.jsonl,.ndjson,.xlsx,.xlsm,text/plain,application/json">
            <span class="file-dropzone-icon">S-R-O</span>
            <span class="file-dropzone-copy">
              <strong id="graph-file-name">${escapeHtml(fileName || (state.importingGraph ? 'Uploading selected file...' : 'Drop or choose a graph file'))}</strong>
              <small id="graph-file-hint">${escapeHtml(fileName ? 'Ready to append to the graph ledger.' : 'Click to browse. Expected columns or fields: subject, relation, object.')}</small>
            </span>
            <span id="graph-file-action" class="file-dropzone-action">${fileName ? 'Change file' : 'Browse file'}</span>
          </label>
        </div>
        <div class="format-example compact-format">
          <div>
            <strong>TXT / CSV</strong>
            <pre>Alice|works_at|Acme
Acme|located_in|Paris</pre>
          </div>
          <div>
            <strong>JSON</strong>
            <pre>{
  "triples": [
    {
      "subject": "Alice",
      "relation": "works_at",
      "object": "Acme"
    }
  ]
}</pre>
          </div>
          <div>
            <strong>Excel</strong>
            <pre>Columns: subject | relation | object</pre>
          </div>
        </div>
        <button class="import-submit primary-import-submit ${state.importingGraph ? 'loading' : ''} ${needsFile ? 'needs-file' : ''}" type="submit" ${state.importingGraph ? 'disabled' : ''}>
          <span class="submit-icon">${state.importingGraph ? '…' : needsFile ? '!' : '↑'}</span>
          <span class="submit-copy">
            <strong>${state.importingGraph ? 'Uploading and indexing...' : needsFile ? 'Choose a file first' : 'Upload graph'}</strong>
            <small>${state.importingGraph ? escapeHtml(fileName || 'Processing file') : needsFile ? 'Select TXT, JSON, or Excel above before uploading' : 'Append to ledger and select it for chat'}</small>
          </span>
        </button>
        ${state.importError ? `<div class="import-message error">${escapeHtml(state.importError)}</div>` : ''}
        ${result ? `<div class="import-message success">Added ${escapeHtml(result.name || result.id)} (${formatDatasetStats(result.stats)}) and selected it for the next chat run.</div>` : ''}
      </form>
      <div class="schema-section-title"><h3>Managed Graphs</h3><small>${latest.length} uploaded graphs</small></div>
      <div class="import-list">
        ${latest.length ? latest.map(renderImportItem).join('') : '<div class="empty-state">No uploaded graphs yet. Upload a TXT, JSON, or Excel triple file to start.</div>'}
      </div>
    `;
    const form = $('#graph-import-form');
    if (form) form.addEventListener('submit', handleGraphImport);
    const fileInput = $('#graph-file');
    if (fileInput) fileInput.addEventListener('change', handleGraphFileChange);
    els.importContent.querySelectorAll('[data-graph-select]').forEach((button) => {
      button.addEventListener('click', async () => {
        state.selectedGraphId = button.dataset.graphSelect || '';
        localStorage.setItem('kbqa_graph_scope_id', state.selectedGraphId);
        renderGraphScopeSelector();
        renderImportPanel();
        await loadGraphSummary(state.selectedGraphId || '');
      });
    });
    els.importContent.querySelectorAll('[data-graph-explore]').forEach((button) => {
      button.addEventListener('click', async () => {
        state.selectedGraphId = button.dataset.graphExplore || '';
        localStorage.setItem('kbqa_graph_scope_id', state.selectedGraphId);
        renderGraphScopeSelector();
        await loadGraphSummary(state.selectedGraphId || '', { silent: true });
        openPanel('schema');
      });
    });
    els.importContent.querySelectorAll('[data-graph-delete]').forEach((button) => {
      button.addEventListener('click', () => handleGraphDelete(button.dataset.graphDelete || '', button.dataset.graphName || 'this graph'));
    });
  }

  function renderImportItem(item) {
    const stats = item.stats || {};
    const files = item.files || [];
    const active = item.id && item.id === state.selectedGraphId;
    const deleting = item.id && item.id === state.deletingGraphId;
    return `
      <div class="import-item graph-management-item ${active ? 'active' : ''}">
        <div class="graph-management-main">
          <div>
            <div class="graph-management-title-row">
              <strong>${escapeHtml(item.name || item.id || 'custom graph')}</strong>
              ${active ? '<span class="active-graph-badge">Active scope</span>' : ''}
            </div>
            <p>${formatDatasetStats(stats)}</p>
            <code>${escapeHtml(item.id || '')}</code>
          </div>
          <span class="graph-management-date">${escapeHtml(formatDate(item.created_at))}</span>
        </div>
        <div class="graph-management-actions">
          <button class="report-action graph-action" type="button" data-graph-select="${escapeHtml(item.id || '')}" ${active ? 'disabled' : ''}>${active ? 'Selected' : 'Use in chat'}</button>
          <button class="report-action graph-action" type="button" data-graph-explore="${escapeHtml(item.id || '')}">Explore</button>
          <button class="report-action graph-action danger" type="button" data-graph-delete="${escapeHtml(item.id || '')}" data-graph-name="${escapeHtml(item.name || item.id || 'this graph')}" ${deleting ? 'disabled' : ''}>${deleting ? 'Removing...' : 'Delete'}</button>
        </div>
        <details>
          <summary>Source and generated metadata</summary>
          <pre>${escapeHtml([
            `raw_path: ${item.raw_path || ''}`,
            `processed_dir: ${item.processed_dir || ''}`,
            ...(files.length ? files.slice(0, 24) : ['No file list available']),
          ].join('\n'))}</pre>
        </details>
      </div>
    `;
  }

  function handleGraphFileChange(event) {
    const input = event.currentTarget;
    const file = input && input.files ? input.files[0] : null;
    state.selectedGraphFileName = file ? file.name : '';
    updateFilePickerLabel('graph-file-name', 'graph-file-hint', input.closest('.file-dropzone'), state.selectedGraphFileName);
  }

  async function handleGraphImport(event) {
    event.preventDefault();
    if (state.importingGraph) return;
    const fileInput = $('#graph-file');
    const nameInput = $('#graph-name');
    const file = fileInput && fileInput.files ? fileInput.files[0] : null;
    if (!file) {
      state.importError = 'Please choose a graph file before uploading.';
      renderImportPanel();
      return;
    }
    state.selectedGraphFileName = file.name;
    const form = new FormData();
    form.append('file', file);
    form.append('dataset_name', nameInput ? nameInput.value : '');
    state.importingGraph = true;
    state.importError = '';
    state.importResult = null;
    renderImportPanel();
    try {
      const response = await fetch('/api/graphs/imports', { method: 'POST', body: form });
      if (!response.ok) throw new Error(await response.text());
      state.importResult = await response.json();
      state.health = await api('/api/health');
      const imported = state.importResult && state.importResult.import ? state.importResult.import : null;
      if (imported && imported.id) {
        state.selectedGraphId = imported.id;
        localStorage.setItem('kbqa_graph_scope_id', state.selectedGraphId);
      }
      normalizeSelectedGraph();
      await loadGraphSummary(state.selectedGraphId || '', { silent: true });
      state.selectedGraphFileName = '';
      state.importError = '';
    } catch (error) {
      state.selectedGraphFileName = '';
      state.importError = String(error.message || error);
    } finally {
      state.importingGraph = false;
      renderGraphScopeSelector();
      renderImportPanel();
      renderSchemaPanel();
    }
  }

  async function handleGraphDelete(graphId, graphName) {
    if (!graphId || state.deletingGraphId) return;
    const confirmed = window.confirm(`Delete "${graphName}"? This removes the uploaded graph and rebuilds the graph ledger.`);
    if (!confirmed) return;

    state.deletingGraphId = graphId;
    state.importError = '';
    state.importResult = null;
    renderImportPanel();
    try {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 90000);
      let response;
      try {
        response = await fetch(`/api/graphs/imports/${encodeURIComponent(graphId)}`, {
          method: 'DELETE',
          signal: controller.signal,
        });
      } finally {
        window.clearTimeout(timeout);
      }
      if (!response.ok && response.status !== 404) throw new Error(await response.text());
      state.health = await api('/api/health');
      if (state.selectedGraphId === graphId) {
        state.selectedGraphId = '';
        localStorage.setItem('kbqa_graph_scope_id', '');
      }
      normalizeSelectedGraph();
      await loadGraphSummary(state.selectedGraphId || '', { silent: true });
      state.importError = response.status === 404 ? 'That graph was already removed; the catalog has been refreshed.' : '';
    } catch (error) {
      state.importError = error && error.name === 'AbortError'
        ? 'Delete is still taking too long. The UI was unlocked; refresh the graph catalog in a moment.'
        : String(error.message || error);
    } finally {
      state.deletingGraphId = '';
      renderGraphScopeSelector();
      renderImportPanel();
      renderSchemaPanel();
    }
  }

  function renderKbqaSchema(project, graphRuntime) {
    const graphs = graphCatalog();
    const summary = state.graphSummary || {};
    const stats = summary.stats || graphRuntime || project.dataset || {};
    const current = selectedGraph();
    const scopeName = current ? current.name || current.id : 'All graphs';
    const options = [
      '<option value="">All graphs · complete ledger</option>',
      ...graphs.map((graph) => {
        const graphStats = graph.stats || {};
        const label = `${graph.name || graph.id || 'Graph'} · ${graphStats.triple_count || 0} triples`;
        return `<option value="${escapeHtml(graph.id || '')}" ${graph.id === state.selectedGraphId ? 'selected' : ''}>${escapeHtml(label)}</option>`;
      }),
    ].join('');
    const loading = state.summaryLoading ? '<div class="empty-state">Loading graph summary...</div>' : '';
    const error = state.summaryError ? `<div class="import-message error">${escapeHtml(state.summaryError)}</div>` : '';
    const explorerBody = !state.summaryLoading ? `
      <div class="graph-overview-grid">
        ${graphStatCard('Entities', stats.entity_count || 0, 'Unique subjects and objects')}
        ${graphStatCard('Relations', stats.relation_count || 0, 'Distinct predicates')}
        ${graphStatCard('Triples', stats.triple_count || 0, 'Evidence statements')}
        ${graphStatCard('Graphs', stats.graph_count || (current ? 1 : graphs.length), current ? 'Selected dataset' : 'In complete ledger')}
      </div>

      ${renderDenseGraphMap(summary.dense_subgraph || {})}

      <div class="schema-section-title"><h3>Graph Samples</h3><small>raw examples from the selected scope</small></div>
      <div class="explorer-sample-grid">
        <div class="explorer-card">
          <div class="explorer-card-head"><strong>Sample Nodes</strong><span>${(summary.sample_nodes || []).length}</span></div>
          ${renderSampleNodes(summary.sample_nodes || [])}
        </div>
        <div class="explorer-card">
          <div class="explorer-card-head"><strong>Sample Relations</strong><span>${(summary.sample_relations || []).length}</span></div>
          ${renderSampleRelations(summary.sample_relations || [])}
        </div>
        <div class="explorer-card wide">
          <div class="explorer-card-head"><strong>Sample Triples</strong><span>${(summary.sample_triples || []).length}</span></div>
          ${renderSampleTriples(summary.sample_triples || [])}
        </div>
      </div>

      <div class="schema-section-title"><h3>Frequent Items</h3><small>top 10 by occurrence</small></div>
      <div class="frequency-grid">
        <div class="explorer-card">
          <div class="explorer-card-head"><strong>Top Nodes</strong><span>10 max</span></div>
          ${renderFrequencyList(summary.top_nodes || [], 'node')}
        </div>
        <div class="explorer-card">
          <div class="explorer-card-head"><strong>Top Relations</strong><span>10 max</span></div>
          ${renderFrequencyList(summary.top_relations || [], 'relation')}
        </div>
      </div>
    ` : '';
    return `
      <div class="graph-explorer-hero">
        <div>
          <span class="schema-kicker">Graph Explorer</span>
          <h2>${escapeHtml(scopeName)}</h2>
          <p>Choose a graph, inspect representative nodes and triples, then use the same scope in chat for grounded code reasoning.</p>
        </div>
        <div class="graph-explorer-controls">
          <label for="graph-explorer-select">Graph to view</label>
          <select id="graph-explorer-select">${options}</select>
          <div class="graph-explorer-actions">
            <button class="report-action" id="graph-explorer-refresh" type="button">Refresh</button>
            <button class="report-action" id="graph-explorer-manage" type="button">Manage graphs</button>
          </div>
        </div>
      </div>
      ${error || loading}
      ${explorerBody}
    `;
  }

  function graphStatCard(label, value, body) {
    return `<div class="status-card explorer-stat"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><p>${escapeHtml(body)}</p></div>`;
  }

  function renderDenseGraphMap(graph) {
    const nodes = (graph.nodes || []).slice(0, 15);
    const edges = graph.edges || [];
    const info = graph.summary || {};
    if (!nodes.length) {
      return `
        <div class="graph-map-card empty-graph-map">
          <div class="graph-map-topline">
            <div>
              <span class="graph-map-kicker">Dense Graph Map</span>
              <h3>Top 15 Connected Nodes</h3>
              <p>No connected nodes were found in this graph scope yet.</p>
            </div>
          </div>
        </div>
      `;
    }

    const width = 980;
    const height = 560;
    const placedNodes = layoutDenseGraph(nodes, width, height);
    const nodeById = new Map(placedNodes.map((node) => [node.id, node]));
    const maxWeight = Math.max(1, ...placedNodes.map((node) => Number(node.weight || 1)));
    const visibleEdges = edges
      .filter((edge) => nodeById.has(edge.source) && nodeById.has(edge.target))
      .slice(0, 34);
    const edgeMarkup = visibleEdges.map((edge, index) => renderGraphEdge(edge, index, nodeById)).join('');
    const nodeMarkup = placedNodes.map((node, index) => renderGraphNode(node, index, maxWeight)).join('');
    const focus = info.focus_node || nodes[0].label || nodes[0].id || 'selected graph';
    const title = `Top 15 dense map around ${focus}`;

    return `
      <div class="graph-map-card">
        <div class="graph-map-topline">
          <div>
            <span class="graph-map-kicker">Dense Graph Map</span>
            <h3>Top 15 Connected Nodes</h3>
            <p>A real topology slice ranked by node degree and internal edge density. Larger circles mean more graph connections.</p>
          </div>
          <div class="graph-map-metrics" aria-label="Dense graph metrics">
            <span><strong>${escapeHtml(info.node_count || nodes.length)}</strong> nodes</span>
            <span><strong>${escapeHtml(info.edge_count || visibleEdges.length)}</strong> edges</span>
            <span><strong>${escapeHtml(info.density || 0)}</strong> density</span>
          </div>
        </div>
        <div class="graph-map-canvas">
          <svg class="kg-map-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeAttr(title)}">
            <defs>
              <radialGradient id="kg-node-focus" cx="36%" cy="28%" r="72%">
                <stop offset="0%" stop-color="#fef3c7"></stop>
                <stop offset="48%" stop-color="#38bdf8"></stop>
                <stop offset="100%" stop-color="#1d4ed8"></stop>
              </radialGradient>
              <radialGradient id="kg-node-core" cx="34%" cy="26%" r="76%">
                <stop offset="0%" stop-color="#ffffff"></stop>
                <stop offset="54%" stop-color="#93c5fd"></stop>
                <stop offset="100%" stop-color="#2563eb"></stop>
              </radialGradient>
              <radialGradient id="kg-node-neighbor" cx="34%" cy="26%" r="76%">
                <stop offset="0%" stop-color="#ecfeff"></stop>
                <stop offset="56%" stop-color="#67e8f9"></stop>
                <stop offset="100%" stop-color="#0f766e"></stop>
              </radialGradient>
              <linearGradient id="kg-edge-gradient" x1="0%" x2="100%" y1="0%" y2="0%">
                <stop offset="0%" stop-color="#0f172a" stop-opacity=".18"></stop>
                <stop offset="48%" stop-color="#2563eb" stop-opacity=".72"></stop>
                <stop offset="100%" stop-color="#06b6d4" stop-opacity=".52"></stop>
              </linearGradient>
              <marker id="kg-arrow" markerWidth="9" markerHeight="9" refX="7.5" refY="4.5" orient="auto" markerUnits="strokeWidth">
                <path d="M1,1 L8,4.5 L1,8 Z" fill="#2563eb" opacity=".72"></path>
              </marker>
              <filter id="kg-soft-glow" x="-40%" y="-40%" width="180%" height="180%">
                <feGaussianBlur stdDeviation="5" result="blur"></feGaussianBlur>
                <feMerge>
                  <feMergeNode in="blur"></feMergeNode>
                  <feMergeNode in="SourceGraphic"></feMergeNode>
                </feMerge>
              </filter>
            </defs>
            <rect class="kg-map-bg" x="18" y="18" width="944" height="524" rx="34"></rect>
            <circle class="kg-map-orbit orbit-one" cx="${width / 2}" cy="${height / 2}" r="178"></circle>
            <ellipse class="kg-map-orbit orbit-two" cx="${width / 2}" cy="${height / 2}" rx="386" ry="218"></ellipse>
            <g class="kg-map-edges">${edgeMarkup}</g>
            <g class="kg-map-nodes">${nodeMarkup}</g>
          </svg>
        </div>
      </div>
    `;
  }

  function layoutDenseGraph(nodes, width, height) {
    const centerX = width / 2;
    const centerY = height / 2;
    const focusIndex = Math.max(0, nodes.findIndex((node) => node.role === 'focus'));
    const ordered = focusIndex === 0 ? nodes : [nodes[focusIndex], ...nodes.filter((_, index) => index !== focusIndex)];
    const innerCount = Math.min(6, Math.max(0, ordered.length - 1));
    const outerCount = Math.max(0, ordered.length - 1 - innerCount);
    return ordered.map((node, index) => {
      if (index === 0) {
        return { ...node, x: centerX, y: centerY, layoutRole: 'focus' };
      }
      if (index <= innerCount) {
        const angle = -Math.PI / 2 + ((index - 1) / Math.max(1, innerCount)) * Math.PI * 2;
        return {
          ...node,
          x: centerX + Math.cos(angle) * 246,
          y: centerY + Math.sin(angle) * 144,
          layoutRole: 'core',
        };
      }
      const outerIndex = index - innerCount - 1;
      const angle = -Math.PI / 2 + (outerIndex / Math.max(1, outerCount)) * Math.PI * 2 + Math.PI / Math.max(5, outerCount);
      const ripple = outerIndex % 2 === 0 ? 1 : -1;
      return {
        ...node,
        x: centerX + Math.cos(angle) * (384 + ripple * 12),
        y: centerY + Math.sin(angle) * (214 - ripple * 8),
        layoutRole: 'neighbor',
      };
    });
  }

  function renderGraphEdge(edge, index, nodeById) {
    const source = nodeById.get(edge.source);
    const target = nodeById.get(edge.target);
    if (!source || !target) return '';
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const length = Math.max(1, Math.hypot(dx, dy));
    const curve = ((index % 2 === 0 ? 1 : -1) * Math.min(72, 22 + length * 0.08));
    const cx = (source.x + target.x) / 2 + (-dy / length) * curve;
    const cy = (source.y + target.y) / 2 + (dx / length) * curve;
    const label = shortGraphLabel(edge.label || edge.relation || 'relation', 22);
    const labelWidth = Math.max(64, Math.min(168, label.length * 7 + 22));
    let angle = Math.atan2(dy, dx) * 180 / Math.PI;
    if (angle > 92 || angle < -92) angle += 180;
    const strokeWidth = Math.min(5.2, 1.35 + Math.sqrt(Number(edge.weight || 1)) * 0.72);
    const path = `M ${source.x.toFixed(1)} ${source.y.toFixed(1)} Q ${cx.toFixed(1)} ${cy.toFixed(1)} ${target.x.toFixed(1)} ${target.y.toFixed(1)}`;
    return `
      <g class="kg-edge-group">
        <path class="kg-edge-shadow" d="${path}" stroke-width="${(strokeWidth + 7).toFixed(2)}"></path>
        <path class="kg-edge" d="${path}" stroke-width="${strokeWidth.toFixed(2)}" marker-end="url(#kg-arrow)"></path>
        <g class="kg-edge-label" transform="translate(${cx.toFixed(1)} ${cy.toFixed(1)}) rotate(${angle.toFixed(1)})">
          <rect x="${(-labelWidth / 2).toFixed(1)}" y="-13" width="${labelWidth}" height="26" rx="13"></rect>
          <text text-anchor="middle" dominant-baseline="central">${escapeHtml(label)}</text>
        </g>
      </g>
    `;
  }

  function renderGraphNode(node, index, maxWeight) {
    const weight = Number(node.weight || 1);
    const normalized = Math.sqrt(weight / Math.max(1, maxWeight));
    const radius = Math.round(20 + normalized * 18 + (index === 0 ? 7 : 0));
    const tone = index === 0 ? 'focus' : index < 7 ? 'core' : 'neighbor';
    const label = shortGraphLabel(node.label || node.id || 'node', tone === 'neighbor' ? 16 : 18);
    return `
      <g class="kg-node ${tone}" transform="translate(${node.x.toFixed(1)} ${node.y.toFixed(1)})">
        <circle class="kg-node-halo" r="${radius + 13}"></circle>
        <circle class="kg-node-ring" r="${radius + 5}"></circle>
        <circle class="kg-node-body" r="${radius}" filter="url(#kg-soft-glow)"></circle>
        <text class="kg-node-label" text-anchor="middle" dominant-baseline="central">${escapeHtml(label)}</text>
        <text class="kg-node-meta" y="${radius + 22}" text-anchor="middle">${escapeHtml(formatCompactNumber(weight))} links</text>
      </g>
    `;
  }

  function shortGraphLabel(value, limit) {
    return truncate(String(value || ''), limit || 18);
  }

  function formatCompactNumber(value) {
    const number = Number(value || 0);
    if (number >= 1000000) return `${(number / 1000000).toFixed(1)}m`;
    if (number >= 1000) return `${(number / 1000).toFixed(number >= 10000 ? 0 : 1)}k`;
    return String(number);
  }

  function renderSampleNodes(nodes) {
    if (!nodes.length) return '<div class="empty-state compact">No nodes found in this scope.</div>';
    return `<div class="node-chip-list">${nodes.map((node) => `<span>${escapeHtml(node.name || node)}</span>`).join('')}</div>`;
  }

  function renderSampleRelations(relations) {
    if (!relations.length) return '<div class="empty-state compact">No relations found in this scope.</div>';
    return `<div class="relation-sample-list">${relations.map((relation) => `
      <div class="relation-sample-row">
        <strong>${escapeHtml(relation.name || '')}</strong>
        <span>${escapeHtml(relation.count || 0)} triples</span>
        <small>${escapeHtml(formatRelationExample(relation.example))}</small>
      </div>
    `).join('')}</div>`;
  }

  function renderSampleTriples(triples) {
    if (!triples.length) return '<div class="empty-state compact">No triples found in this scope.</div>';
    return `<div class="triple-list refined-triples">${triples.map((triple) => `
      <div class="triple-row refined-triple-row">
        <span class="triple-entity subject">${escapeHtml(triple.subject || '')}</span>
        <span class="triple-connector">
          <i></i>
          <strong>${escapeHtml(triple.relation || '')}</strong>
        </span>
        <span class="triple-entity object">${escapeHtml(triple.object || '')}</span>
      </div>
    `).join('')}</div>`;
  }

  function renderFrequencyList(items, type) {
    if (!items.length) return `<div class="empty-state compact">No frequent ${type}s yet.</div>`;
    return `<div class="frequency-list">${items.slice(0, 10).map((item, index) => {
      const meta = type === 'node'
        ? `${item.count || 0} hits · out ${item.out || 0} · in ${item.in || 0}`
        : `${item.count || 0} triples · ${formatRelationExample(item.example)}`;
      return `
        <div class="frequency-row">
          <span>${index + 1}</span>
          <strong>${escapeHtml(item.name || '')}</strong>
          <small>${escapeHtml(meta)}</small>
        </div>
      `;
    }).join('')}</div>`;
  }

  function formatRelationExample(example) {
    if (!example || (!example.subject && !example.object)) return 'No example triple available';
    return `${example.subject || '?'} -> ${example.object || '?'}`;
  }

  function card(label, value, body) {
    return `<div class="status-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><p>${escapeHtml(body || '')}</p></div>`;
  }

  function openPanel(tab = 'schema') {
    if (!['schema', 'import'].includes(tab)) tab = 'schema';
    state.activePanel = tab;
    els.panel.classList.add('active');
    setFabOpen(false);
    els.tabs.forEach((item) => item.classList.toggle('active', item.dataset.tab === tab));
    const schemaSection = $('#schema-content');
    if (schemaSection) {
      schemaSection.classList.toggle('active', tab === 'schema');
    }
    const importSection = $('#import-content');
    if (importSection) {
      importSection.classList.toggle('active', tab === 'import');
    }
    if (tab === 'schema') renderSchemaPanel();
    if (tab === 'import') renderImportPanel();
  }

  function setFabOpen(open, restoreFocus = false) {
    if (!els.fabContainer || !els.fabMain) return;
    const actions = [els.fabSchema, els.fabImport].filter(Boolean);
    els.fabContainer.classList.toggle('open', open);
    els.fabMain.setAttribute('aria-expanded', open ? 'true' : 'false');
    actions.forEach((action) => {
      action.setAttribute('aria-hidden', open ? 'false' : 'true');
      action.tabIndex = open ? 0 : -1;
    });
    if (!open && restoreFocus && actions.includes(document.activeElement)) {
      els.fabMain.focus({ preventScroll: true });
    }
  }

  function closePanel() {
    els.panel.classList.remove('active');
  }

  function openHistory() {
    renderSessionList();
    els.historyOverlay.classList.add('active');
    els.historyModal.classList.add('active');
  }

  function closeHistory() {
    state.confirmingDeleteSessionId = '';
    els.historyOverlay.classList.remove('active');
    els.historyModal.classList.remove('active');
  }

  function updateSendState() {
    const waitingForSocket = Boolean(state.session && !isSocketReady());
    els.send.disabled = state.streaming || state.creatingSession || waitingForSocket || !els.input.value.trim();
  }

  function resetRunUi() {
    state.streaming = false;
    state.activeStreamId = null;
    state.liveToolKey = '';
    state.activeModelDeltaKey = '';
    state.suppressModelOutputSync = false;
    state.resetModelOutputOnNextDelta = false;
    els.runIndicator.classList.remove('active');
    els.runDetail.textContent = 'waiting for events';
    updateSendState();
  }

  function reconnectCurrentSession() {
    resetRunUi();
    if (!state.session) return;
    connect(state.session.id);
  }

  function isSocketReady() {
    return state.ws && state.ws.readyState === WebSocket.OPEN;
  }

  function waitForSocketReady(timeout = 2500) {
    if (isSocketReady()) return Promise.resolve(true);
    return new Promise((resolve) => {
      const started = Date.now();
      const timer = window.setInterval(() => {
        if (isSocketReady()) {
          window.clearInterval(timer);
          resolve(true);
          return;
        }
        if (Date.now() - started > timeout) {
          window.clearInterval(timer);
          resolve(false);
        }
      }, 50);
    });
  }

  function clearReconnectTimer() {
    if (state.reconnectTimer) {
      window.clearTimeout(state.reconnectTimer);
      state.reconnectTimer = null;
    }
  }

  function autoResize() {
    els.input.style.height = 'auto';
    els.input.style.height = `${Math.min(150, els.input.scrollHeight)}px`;
  }

  function scrollToBottom() {
    requestAnimationFrame(() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' }));
  }



  function applySavedTheme() {
    const theme = localStorage.getItem(`${config.agentId || 'studio'}-theme`) || 'light';
    document.body.classList.toggle('dark-theme', theme === 'dark');
    document.body.classList.toggle('light-theme', theme !== 'dark');
  }

  function toggleTheme() {
    const dark = !document.body.classList.contains('dark-theme');
    document.body.classList.toggle('dark-theme', dark);
    document.body.classList.toggle('light-theme', !dark);
    localStorage.setItem(`${config.agentId || 'studio'}-theme`, dark ? 'dark' : 'light');
  }

  function formatDatasetStats(stats) {
    if (!stats) return 'No dataset stats available.';
    const parts = [];
    if (stats.entity_count) parts.push(`${stats.entity_count} entities`);
    if (stats.relation_count) parts.push(`${stats.relation_count} relations`);
    if (stats.triple_count) parts.push(`${stats.triple_count} triples`);
    return parts.length ? parts.join(' · ') : 'File artifacts are present.';
  }

  function shortenModel(model) {
    const parts = String(model || '').split('/');
    return parts[parts.length - 1] || model;
  }

  function formatDate(value) {
    if (!value) return 'just now';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'just now';
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  function formatMessageCount(count) {
    return `${count} ${count === 1 ? 'message' : 'messages'}`;
  }

  function avatarLetter(agent) {
    const source = agent || config.brand || 'A';
    return escapeHtml(String(source).trim().charAt(0).toUpperCase() || 'A');
  }

  function truncate(value, limit) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
  }

  function unique(values) {
    return [...new Set(values)];
  }

  function updateFilePickerLabel(nameId, hintId, dropzone, fileName) {
    const name = $(`#${nameId}`);
    const hint = $(`#${hintId}`);
    const action = $('#graph-file-action');
    if (name) name.textContent = fileName || 'Drop or choose a graph file';
    if (hint) hint.textContent = fileName ? 'Ready to append to the graph ledger.' : 'Click to browse. Expected columns or fields: subject, relation, object.';
    if (action) action.textContent = fileName ? 'Change file' : 'Browse file';
    if (dropzone) dropzone.classList.toggle('has-file', Boolean(fileName));
  }

  function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function formatMarkdown(value) {
    const lines = String(value || '').replace(/\r\n/g, '\n').split('\n');
    const blocks = [];
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      const trimmed = line.trim();
      if (!trimmed) {
        index += 1;
        continue;
      }
      const boxedAnswer = parseBoxedAnswer(trimmed);
      if (boxedAnswer) {
        blocks.push(renderBoxedAnswer(boxedAnswer));
        index += 1;
        continue;
      }
      if (trimmed.startsWith('```')) {
        const codeLines = [];
        index += 1;
        while (index < lines.length && !lines[index].trim().startsWith('```')) {
          codeLines.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        blocks.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`);
        continue;
      }
      if (isMarkdownTableStart(lines, index)) {
        const header = parseMarkdownRow(lines[index]);
        index += 2;
        const rows = [];
        while (index < lines.length && isMarkdownRow(lines[index])) {
          rows.push(parseMarkdownRow(lines[index]));
          index += 1;
        }
        blocks.push(renderMarkdownTable(header, rows));
        continue;
      }
      const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
      if (heading) {
        const level = heading[1].length;
        blocks.push(`<h${level}>${formatInlineMarkdown(heading[2])}</h${level}>`);
        index += 1;
        continue;
      }
      const listType = /^[-*]\s+/.test(trimmed) ? 'ul' : (/^\d+\.\s+/.test(trimmed) ? 'ol' : '');
      if (listType) {
        const items = [];
        while (index < lines.length) {
          const item = lines[index].trim();
          const match = listType === 'ul' ? item.match(/^[-*]\s+(.+)$/) : item.match(/^\d+\.\s+(.+)$/);
          if (!match) break;
          items.push(`<li>${formatInlineMarkdown(match[1])}</li>`);
          index += 1;
        }
        blocks.push(`<${listType}>${items.join('')}</${listType}>`);
        continue;
      }
      const paragraph = [];
      while (
        index < lines.length &&
        lines[index].trim() &&
        !lines[index].trim().startsWith('```') &&
        !isMarkdownTableStart(lines, index) &&
        !parseBoxedAnswer(lines[index].trim()) &&
        !/^(#{1,3})\s+/.test(lines[index].trim()) &&
        !/^[-*]\s+/.test(lines[index].trim()) &&
        !/^\d+\.\s+/.test(lines[index].trim())
      ) {
        paragraph.push(lines[index]);
        index += 1;
      }
      blocks.push(`<p>${paragraph.map((item) => formatInlineMarkdown(item)).join('<br>')}</p>`);
    }
    return blocks.join('');
  }

  function parseBoxedAnswer(value) {
    const text = String(value || '').trim();
    const prefixMatch = text.match(/^\\{1,2}boxed\s*\{/);
    if (!prefixMatch) return null;
    let depth = 0;
    let body = '';
    let foundOpen = false;
    for (let index = prefixMatch[0].length - 1; index < text.length; index += 1) {
      const char = text[index];
      if (char === '{') {
        if (foundOpen) body += char;
        depth += 1;
        foundOpen = true;
        continue;
      }
      if (char === '}') {
        depth -= 1;
        if (depth === 0) {
          const trailing = text.slice(index + 1).trim();
          return trailing ? null : normalizeBoxedAnswer(body);
        }
        body += char;
        continue;
      }
      if (foundOpen) body += char;
    }
    return null;
  }

  function normalizeBoxedAnswer(rawValue) {
    const raw = String(rawValue || '').trim();
    if (!raw) return { raw: '', values: [] };
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return { raw, values: parsed.map((item) => String(item)) };
      }
      return { raw, values: [String(parsed)] };
    } catch (error) {
      const quoted = [...raw.matchAll(/"([^"]+)"|'([^']+)'/g)].map((match) => match[1] || match[2]);
      if (quoted.length) return { raw, values: quoted };
      const cleaned = raw.replace(/^\[|\]$/g, '').trim();
      const values = cleaned
        ? cleaned.split(/\s*,\s*/).map((item) => item.replace(/^["']|["']$/g, '').trim()).filter(Boolean)
        : [];
      return { raw, values: values.length ? values : [raw] };
    }
  }

  function renderBoxedAnswer(answer) {
    const values = answer.values && answer.values.length ? answer.values : [answer.raw || ''];
    const chips = values.map((item) => `<strong>${formatInlineMarkdown(item)}</strong>`).join('');
    return `
      <div class="boxed-answer-card">
        <span class="boxed-answer-kicker">Final Answer</span>
        <div class="boxed-answer-values">${chips}</div>
      </div>
    `;
  }

  function formatInlineMarkdown(value) {
    let html = escapeHtml(value || '');
    html = html.replace(/\\{1,2}boxed\s*\{([^{}]+)\}/g, (_, answer) => renderBoxedAnswer(normalizeBoxedAnswer(answer)));
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    return html;
  }

  function isMarkdownRow(line) {
    const trimmed = String(line || '').trim();
    return trimmed.startsWith('|') && trimmed.endsWith('|') && parseMarkdownRow(trimmed).length > 1;
  }

  function isMarkdownTableStart(lines, index) {
    return index + 1 < lines.length && isMarkdownRow(lines[index]) && isMarkdownDivider(lines[index + 1]);
  }

  function isMarkdownDivider(line) {
    const cells = parseMarkdownRow(line);
    return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, '')));
  }

  function parseMarkdownRow(line) {
    return String(line || '').trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim());
  }

  function renderMarkdownTable(header, rows) {
    const head = header.map((cell) => `<th>${formatInlineMarkdown(cell)}</th>`).join('');
    const body = rows.map((row) => `
      <tr>${header.map((_, index) => `<td>${formatInlineMarkdown(row[index] || '')}</td>`).join('')}</tr>
    `).join('');
    return `<div class="markdown-table-wrap"><table class="markdown-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function downloadText(filename, content) {
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }
})();
