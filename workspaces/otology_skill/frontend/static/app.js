(() => {
  const MAX_EVENT_MESSAGES = 90;
  const config = window.STUDIO_CONFIG || {};
  const state = {
    sessions: [],
    session: null,
    ws: null,
    streaming: false,
    health: null,
    activePanel: 'sankey',
    activeStreamId: null,
    reconnectTimer: null,
    importingCase: false,
    importResult: null,
    importError: '',
    caseDetails: {},
    caseDetailLoading: false,
    caseRefreshTimer: null,
    caseRefreshInFlight: false,
    deletingCaseId: '',
    deletingSessionId: '',
    confirmingDeleteSessionId: '',
    creatingSession: false,
    sankeyActiveNodeId: '',
    sankeyFileCache: {},
    sankeyPreviewLoading: '',
    sankeyPreviewError: '',
    selectedCaseFileNames: '',
    mainSelectedCaseFileNames: '',
    mainQuestionMode: 'single',
    selectedCaseId: localStorage.getItem('otology_case_scope_id') || '',
    isComposing: false,
    compositionEndedAt: 0,
    suppressNextEnter: false,
    compositionGuardTimer: null,
    liveToolKey: '',
    activeModelDeltaKey: '',
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
    caseLaunchpad: $('#case-launchpad'),
    mainCaseForm: $('#main-case-form'),
    mainCaseFiles: $('#main-case-files'),
    mainCaseFileName: $('#main-case-file-name'),
    mainCaseFileHint: $('#main-case-file-hint'),
    mainCaseFileAction: $('#main-case-file-action'),
    mainImportMessage: $('#main-import-message'),
    mainCaseQuestion: $('#main-case-question'),
    mainMultiQuestions: $('#main-multi-questions'),
    mainAddQuestion: $('#main-add-question'),
    capabilitySection: $('#capability-section'),
    heroUploadCase: $('#hero-upload-case'),
    skillCount: $('#skill-count'),
    toolCount: $('#tool-count'),
    exampleSection: $('#example-section'),
    promptGrid: $('#prompt-grid'),
    messages: $('#messages'),
    input: $('#message-input'),
    send: $('#send-button'),
    runIndicator: $('#run-indicator'),
    runDetail: $('#run-detail'),
    resetRun: $('#reset-run'),
    caseScopeSelect: $('#case-scope-select'),
    caseScopeHint: $('#case-scope-hint'),
    fabContainer: $('#fab-container'),
    fabMain: $('#fab-main'),
    fabSankey: $('#fab-sankey'),
    fabImport: $('#fab-import'),
    panel: $('#activities-panel'),
    closePanel: $('#close-panel'),
    tabs: document.querySelectorAll('.panel-tab'),
    sankeyContent: $('#sankey-content'),
    importContent: $('#import-content'),
    historyOverlay: $('#history-overlay'),
    historyModal: $('#history-modal'),
    closeHistory: $('#close-history'),
    historyNewChat: $('#history-new-chat'),
    sessionCount: $('#session-count'),
    sessions: $('#session-list'),
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
      normalizeSelectedCase();
      await loadSelectedCaseDetail();
      const model = state.health.model || 'Model';
      els.model.textContent = shortenModel(model);
      els.status.classList.toggle('ready', Boolean(state.health.api_key_present));
      els.status.classList.toggle('warn', !state.health.api_key_present);
      els.status.querySelector('span:last-child').textContent = state.health.api_key_present
        ? 'Runtime ready'
        : 'Missing API key';
    } catch (error) {
      state.health = null;
      els.status.classList.add('warn');
      els.status.querySelector('span:last-child').textContent = 'Runtime unavailable';
    }
    updateHeroMetrics();
    renderSankeyPanel();
    renderImportPanel();
    renderCaseScopeSelector();
  }

  async function loadSessions() {
    const data = await api('/api/sessions');
    state.sessions = data.sessions || [];
    renderSessionList();
  }

  function caseCatalog() {
    const health = state.health || {};
    if (Array.isArray(health.case_catalog)) return health.case_catalog;
    const project = health.project || {};
    if (Array.isArray(project.case_catalog)) return project.case_catalog;
    return [];
  }

  function selectedCase() {
    if (state.selectedCaseId && state.caseDetails[state.selectedCaseId]) {
      return state.caseDetails[state.selectedCaseId];
    }
    return caseCatalog().find((item) => item.id === state.selectedCaseId) || null;
  }

  async function loadSelectedCaseDetail(force = false) {
    const caseId = state.selectedCaseId;
    if (!caseId) return null;
    if (!force && state.caseDetails[caseId] && state.caseDetails[caseId].process) {
      return state.caseDetails[caseId];
    }
    state.caseDetailLoading = true;
    try {
      const data = await api(`/api/cases/${encodeURIComponent(caseId)}`);
      if (data.case && data.case.id) {
        state.caseDetails[data.case.id] = data.case;
        return data.case;
      }
    } catch (error) {
      delete state.caseDetails[caseId];
    } finally {
      state.caseDetailLoading = false;
    }
    return null;
  }

  function scheduleCaseProcessRefresh(delay = 500) {
    if (!state.selectedCaseId) return;
    if (state.caseRefreshTimer) window.clearTimeout(state.caseRefreshTimer);
    state.caseRefreshTimer = window.setTimeout(refreshSelectedCaseProcess, delay);
  }

  async function refreshSelectedCaseProcess() {
    if (!state.selectedCaseId) return;
    if (state.caseRefreshInFlight) {
      scheduleCaseProcessRefresh(500);
      return;
    }
    state.caseRefreshTimer = null;
    state.caseRefreshInFlight = true;
    try {
      await loadSelectedCaseDetail(true);
      state.health = await api('/api/health');
      normalizeSelectedCase();
      renderCaseScopeSelector();
      renderActivePanel();
    } catch (error) {
      // Live process refresh is best-effort; chat streaming should keep going.
    } finally {
      state.caseRefreshInFlight = false;
    }
  }

  function normalizeSelectedCase() {
    if (!state.selectedCaseId) return;
    if (!selectedCase()) {
      state.selectedCaseId = '';
      localStorage.setItem('otology_case_scope_id', '');
    }
  }

  function renderCaseScopeSelector() {
    if (!els.caseScopeSelect) return;
    const cases = caseCatalog();
    const current = selectedCase();
    const options = [
      '<option value="">No uploaded case selected</option>',
      ...cases.map((item) => {
        const stats = item.stats || {};
        const label = `${item.name || item.id || 'Case'} · ${stats.workbook_count || 0} files · ${stats.table_count || 0} tables`;
        return `<option value="${escapeHtml(item.id || '')}">${escapeHtml(label)}</option>`;
      }),
    ];
    els.caseScopeSelect.innerHTML = options.join('');
    els.caseScopeSelect.value = current ? current.id : '';
    if (els.caseScopeHint) {
      els.caseScopeHint.textContent = current
        ? `Active case for the next answer: ${current.name || current.id}`
        : 'No case selected. Upload Excel files from Data & Inputs.';
    }
  }

  function updateHeroMetrics() {
    const project = state.health && state.health.project ? state.health.project : {};
    const skills = Array.isArray(project.skills) ? project.skills.length : 3;
    const tools = Array.isArray(project.tools) ? project.tools.length : 6;
    if (els.skillCount) {
      els.skillCount.textContent = `${skills} modeling skill${skills === 1 ? '' : 's'}`;
    }
    if (els.toolCount) {
      els.toolCount.textContent = `${tools} ontology tool${tools === 1 ? '' : 's'}`;
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
      state.resetModelOutputOnNextDelta = false;
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
      state.resetModelOutputOnNextDelta = false;
      els.runIndicator.classList.add('active');
      els.runDetail.textContent = `run ${message.run_id}`;
      updateSendState();
      renderMessages();
      renderActivePanel();
      scheduleCaseProcessRefresh(250);
      return;
    }

    if (message.type === 'assistant_delta') {
      appendAssistantDelta(message);
      return;
    }

    if (message.type === 'event') {
      if (message.message && message.message.kind !== 'model_output') {
        state.resetModelOutputOnNextDelta = true;
      } else if (message.message && message.message.kind === 'model_output') {
        syncActiveModelOutput(message.message);
      }
      upsertMessage(message.message);
      renderActivePanel();
      scheduleCaseProcessRefresh(650);
      return;
    }

    if (message.type === 'assistant_final') {
      const finalMessage = { ...message.message, streaming: false };
      state.activeStreamId = null;
      state.liveToolKey = '';
      state.activeModelDeltaKey = '';
      state.resetModelOutputOnNextDelta = false;
      appendFinalAssistantMessage(finalMessage);
      scheduleCaseProcessRefresh(250);
      return;
    }

    if (message.type === 'error') {
      upsertMessage(message.message);
      state.streaming = false;
      state.activeStreamId = null;
      state.activeModelDeltaKey = '';
      state.resetModelOutputOnNextDelta = false;
      els.runIndicator.classList.remove('active');
      updateSendState();
      renderActivePanel();
      scheduleCaseProcessRefresh(250);
      return;
    }

    if (message.type === 'run_done') {
      state.streaming = false;
      state.activeStreamId = null;
      state.liveToolKey = '';
      state.activeModelDeltaKey = '';
      state.resetModelOutputOnNextDelta = false;
      els.runIndicator.classList.remove('active');
      updateSendState();
      loadSessions();
      if (state.selectedCaseId) delete state.caseDetails[state.selectedCaseId];
      loadHealth();
      renderActivePanel();
      scheduleCaseProcessRefresh(150);
    }
  }

  function appendAssistantDelta(message) {
    if (!state.session || !message.delta) return;
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
    state.resetModelOutputOnNextDelta = true;
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
    pruneSessionEvents();
    renderMessages();
    renderTitleVisibility();
    scrollToBottom();
  }

  function appendFinalAssistantMessage(message) {
    if (!state.session || !message) return;
    state.session.messages = (state.session.messages || []).filter((item) => item.id !== message.id);
    state.session.messages.push(message);
    pruneSessionEvents();
    renderMessages();
    renderTitleVisibility();
    scrollToBottom();
  }

  function pruneSessionEvents() {
    if (!state.session || !Array.isArray(state.session.messages)) return;
    const eventIndexes = state.session.messages
      .map((message, index) => (message.role === 'event' ? index : -1))
      .filter((index) => index >= 0);
    if (eventIndexes.length <= MAX_EVENT_MESSAGES) return;
    const keep = new Set(eventIndexes.slice(-MAX_EVENT_MESSAGES));
    state.session.messages = state.session.messages.filter((message, index) => message.role !== 'event' || keep.has(index));
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
    if (els.heroUploadCase) {
      els.heroUploadCase.addEventListener('click', focusLaunchpad);
    }
    if (els.mainCaseForm) {
      els.mainCaseForm.addEventListener('submit', handleMainCaseImport);
    }
    if (els.mainCaseFiles) {
      els.mainCaseFiles.addEventListener('change', handleMainCaseFileChange);
    }
    document.querySelectorAll('[data-main-question-mode]').forEach((button) => {
      button.addEventListener('click', () => setMainQuestionMode(button.dataset.mainQuestionMode || 'single'));
    });
    if (els.mainAddQuestion) {
      els.mainAddQuestion.addEventListener('click', () => addMainQuestionRow());
    }
    document.querySelectorAll('.capability-card').forEach((button) => {
      button.addEventListener('click', () => {
        if (button.dataset.focusLaunchpad) {
          focusLaunchpad();
          return;
        }
        const panel = button.dataset.panel || '';
        if (panel) {
          openPanel(panel);
          return;
        }
        els.input.focus();
        window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
      });
    });
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
    if (els.fabSankey) {
      els.fabSankey.addEventListener('click', () => openPanel('sankey'));
    }
    if (els.fabImport) {
      els.fabImport.addEventListener('click', () => openPanel('import'));
    }
    if (els.caseScopeSelect) {
      els.caseScopeSelect.addEventListener('change', async () => {
        state.selectedCaseId = els.caseScopeSelect.value || '';
        localStorage.setItem('otology_case_scope_id', state.selectedCaseId);
        await loadSelectedCaseDetail();
        renderCaseScopeSelector();
        renderSankeyPanel();
        renderImportPanel();
      });
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
        closeSankeyModal();
        closeHistory();
        closePanel();
        setFabOpen(false, true);
      }
    });
  }

  function focusLaunchpad() {
    if (els.caseLaunchpad) {
      els.caseLaunchpad.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    window.setTimeout(() => {
      if (els.mainCaseFiles) els.mainCaseFiles.focus();
    }, 320);
  }

  function handleMainCaseFileChange(event) {
    const input = event.currentTarget;
    const files = input && input.files ? Array.from(input.files) : [];
    state.mainSelectedCaseFileNames = files.length ? files.map((file) => file.name).join(', ') : '';
    updateMainCaseFileLabel(Boolean(files.length));
  }

  function updateMainCaseFileLabel(hasFiles = Boolean(state.mainSelectedCaseFileNames)) {
    if (els.mainCaseFileName) {
      els.mainCaseFileName.textContent = hasFiles ? state.mainSelectedCaseFileNames : 'Choose Excel workbooks';
    }
    if (els.mainCaseFileHint) {
      els.mainCaseFileHint.textContent = hasFiles
        ? 'Ready to prepare as one multi-workbook case.'
        : 'No files selected yet. Click here to browse.';
    }
    if (els.mainCaseFileAction) {
      els.mainCaseFileAction.textContent = hasFiles ? 'Change files' : 'Browse';
    }
    const dropzone = els.mainCaseFiles ? els.mainCaseFiles.closest('.main-file-dropzone') : null;
    if (dropzone) dropzone.classList.toggle('has-file', hasFiles);
  }

  function setMainQuestionMode(mode) {
    state.mainQuestionMode = mode === 'multi' ? 'multi' : 'single';
    document.querySelectorAll('[data-main-question-mode]').forEach((button) => {
      button.classList.toggle('active', button.dataset.mainQuestionMode === state.mainQuestionMode);
    });
    if (els.mainCaseQuestion) {
      els.mainCaseQuestion.classList.toggle('hidden', state.mainQuestionMode === 'multi');
    }
    if (els.mainMultiQuestions) {
      els.mainMultiQuestions.classList.toggle('hidden', state.mainQuestionMode !== 'multi');
    }
  }

  function addMainQuestionRow(value = '') {
    if (!els.mainMultiQuestions || !els.mainAddQuestion) return;
    const count = els.mainMultiQuestions.querySelectorAll('.main-question-input').length + 1;
    const row = document.createElement('div');
    row.className = 'main-question-row';
    row.innerHTML = `
      <span>Q${count}</span>
      <textarea class="main-question-input" rows="2" placeholder="Question ${count}: Add another related ontology goal.">${escapeHtml(value)}</textarea>
      <button class="remove-question-btn" type="button" aria-label="Remove question">×</button>
    `;
    const remove = row.querySelector('.remove-question-btn');
    if (remove) {
      remove.addEventListener('click', () => {
        row.remove();
        refreshMainQuestionNumbers();
      });
    }
    els.mainMultiQuestions.insertBefore(row, els.mainAddQuestion);
    refreshMainQuestionNumbers();
  }

  function refreshMainQuestionNumbers() {
    if (!els.mainMultiQuestions) return;
    els.mainMultiQuestions.querySelectorAll('.main-question-row').forEach((row, index) => {
      const label = row.querySelector('span');
      if (label) label.textContent = `Q${index + 1}`;
    });
  }

  function getMainQuestions() {
    if (state.mainQuestionMode === 'multi') {
      return Array.from(document.querySelectorAll('.main-question-input'))
        .map((item) => item.value.trim())
        .filter(Boolean);
    }
    const question = els.mainCaseQuestion ? els.mainCaseQuestion.value.trim() : '';
    return question ? [question] : [];
  }

  function setMainImportMessage(kind, message) {
    if (!els.mainImportMessage) return;
    els.mainImportMessage.textContent = message || '';
    els.mainImportMessage.className = `launchpad-message ${kind || ''}${message ? ' visible' : ''}`;
  }

  function setMainImportLoading(loading, action = 'ask') {
    if (!els.mainCaseForm) return;
    els.mainCaseForm.classList.toggle('loading', loading);
    els.mainCaseForm.querySelectorAll('button, input, textarea, select').forEach((item) => {
      if (item.id === 'main-add-question' || item.classList.contains('remove-question-btn')) {
        item.disabled = loading;
        return;
      }
      item.disabled = loading;
    });
    const primary = els.mainCaseForm.querySelector('[data-main-action="ask"] span');
    if (primary) primary.textContent = loading && action === 'ask' ? 'Preparing and sending...' : 'Prepare case and ask';
    const secondary = els.mainCaseForm.querySelector('[data-main-action="prepare"] span');
    if (secondary) secondary.textContent = loading && action === 'prepare' ? 'Preparing case...' : 'Only prepare case';
  }

  async function handleMainCaseImport(event) {
    event.preventDefault();
    if (state.importingCase) return;
    const action = event.submitter && event.submitter.dataset ? event.submitter.dataset.mainAction || 'ask' : 'ask';
    const fileInput = els.mainCaseFiles;
    const files = fileInput && fileInput.files ? Array.from(fileInput.files) : [];
    if (!files.length) {
      setMainImportMessage('error', 'Please choose at least one .xlsx or .xlsm workbook.');
      focusLaunchpad();
      return;
    }
    const questions = getMainQuestions();
    if (action === 'ask' && !questions.length) {
      setMainImportMessage('error', 'Add at least one business question before asking the agent.');
      return;
    }
    state.mainSelectedCaseFileNames = files.map((file) => file.name).join(', ');
    updateMainCaseFileLabel(true);
    const form = new FormData();
    files.forEach((file) => form.append('files', file));
    form.append('case_name', $('#main-case-name') ? $('#main-case-name').value : '');
    form.append('question', formatQuestionsForCase(questions));
    form.append('questions_json', JSON.stringify(questions));
    state.importingCase = true;
    state.importError = '';
    state.importResult = null;
    setMainImportLoading(true, action);
    setMainImportMessage('info', files.length > 1 ? `Preparing ${files.length} workbooks as one case...` : 'Preparing workbook case...');
    try {
      const response = await fetch('/api/cases/imports', { method: 'POST', body: form });
      if (!response.ok) throw new Error(await response.text());
      state.importResult = await response.json();
      state.health = await api('/api/health');
      const imported = state.importResult && state.importResult.import ? state.importResult.import : null;
      if (imported && imported.id) {
        state.selectedCaseId = imported.id;
        state.caseDetails[imported.id] = imported;
        localStorage.setItem('otology_case_scope_id', state.selectedCaseId);
      }
      normalizeSelectedCase();
      state.mainSelectedCaseFileNames = '';
      if (fileInput) fileInput.value = '';
      updateMainCaseFileLabel(false);
      renderSankeyPanel();
      renderCaseScopeSelector();
      renderImportPanel();
      const questionText = questions.length === 1 ? '1 question' : `${questions.length} questions`;
      setMainImportMessage('success', `Case prepared and selected (${files.length} file${files.length === 1 ? '' : 's'}, ${questionText}).`);
      if (action === 'ask' && questions.length) {
        const prompt = composeOntologyPrompt(imported, questions);
        els.input.value = prompt;
        autoResize();
        updateSendState();
        if (isSocketReady() && !state.streaming) {
          sendCurrentMessage();
        } else {
          setMainImportMessage('success', 'Case prepared. The prompt is in the chat box; send it when the runtime is ready.');
        }
      }
    } catch (error) {
      setMainImportMessage('error', String(error.message || error));
    } finally {
      state.importingCase = false;
      setMainImportLoading(false, action);
    }
  }

  function formatQuestionsForCase(questions) {
    if (!questions.length) return '';
    if (questions.length === 1) return questions[0];
    return questions.map((question, index) => `${index + 1}. ${question}`).join('\n');
  }

  function composeOntologyPrompt(caseItem, questions) {
    const intro = questions.length > 1
      ? 'Using the selected Excel case, build one consolidated business ontology schema that covers all related questions below.'
      : 'Using the selected Excel case, design a business ontology for the question below.';
    const questionBlock = questions.length > 1
      ? questions.map((question, index) => `${index + 1}. ${question}`).join('\n')
      : questions[0];
    const caseName = caseItem && (caseItem.name || caseItem.id) ? `\nCase: ${caseItem.name || caseItem.id}` : '';
    return `${intro}${caseName}

Questions:
${questionBlock}

Please generate ontology code, reports, validation artifacts, and Markdown download links under the case business_ontology directory. Finish with 产出总结, 业务本体设计, 输出文件, 核心关系, and 验证结果与假设.${questions.length > 1 ? '\nAlso include a per-question coverage summary mapping each question to entities, relationships, interfaces, operations, and output files.' : ''}`;
  }

  async function sendCurrentMessage() {
    const content = els.input.value.trim();
    if (!content || state.streaming || state.creatingSession) return;
    try {
      await ensureActiveSession();
      if (!isSocketReady()) {
        throw new Error('Conversation channel is not ready yet.');
      }
      state.ws.send(JSON.stringify({ type: 'chat', content, case_id: state.selectedCaseId || '' }));
      els.input.value = '';
      autoResize();
      updateSendState();
    } catch (error) {
      window.alert(`Unable to start the conversation: ${String(error.message || error)}`);
      updateSendState();
    }
  }

  function renderAll() {
    updateHeroMetrics();
    renderTitleVisibility();
    renderSessionList();
    renderMessages();
    renderSankeyPanel();
    renderImportPanel();
    renderCaseScopeSelector();
    updateSendState();
  }

  function renderTitleVisibility() {
    const messages = state.session ? state.session.messages || [] : [];
    const hasMessages = messages.length > 0;
    els.hero.classList.toggle('hidden', hasMessages);
    if (els.caseLaunchpad) {
      els.caseLaunchpad.classList.toggle('hidden', hasMessages);
    }
    if (els.capabilitySection) {
      els.capabilitySection.classList.toggle('hidden', hasMessages);
    }
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
          <p>Start from the homepage and your ontology modeling runs will appear here.</p>
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
      content: (draft && draft.content) || (latestModelOutput && latestModelOutput.content) || '',
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
      ? formatMarkdown(sanitizeUserVisibleModelText(run.content))
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
    const visibleContent = sanitizeUserVisibleModelText(message.content || '');
    const artifactPaths = extractArtifactPaths(visibleContent);
    const output = visibleContent
      ? formatMarkdown(visibleContent)
      : '<span class="live-placeholder">No final answer was returned.</span>';
    const artifactBanner = artifactPaths.length
      ? `
        <div class="ontology-result-banner">
          <span class="ontology-result-icon">ONT</span>
          <div>
            <strong>Business ontology artifacts are ready</strong>
            <span>${artifactPaths.length} downloadable file${artifactPaths.length === 1 ? '' : 's'} detected in the final answer.</span>
          </div>
        </div>
      `
      : '';
    const artifactDock = artifactPaths.length ? renderArtifactDock(artifactPaths) : '';
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
          <div class="run-model-pane final-answer${artifactPaths.length ? ' ontology-result' : ''}">
            <span class="run-section-label">Final answer</span>
            ${artifactBanner}
            <div class="run-model-output">${output}</div>
            ${artifactDock}
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
    els.schemaContent.innerHTML = renderOtologySchema(project);
    bindSchemaPanelActions();
  }

  function renderSankeyPanel() {
    if (!els.sankeyContent) return;
    const currentCase = selectedCase();
    if (!currentCase) {
      els.sankeyContent.innerHTML = `
        <div class="schema-hero ontology-hero case-workspace-hero sankey-hero">
          <div>
            <span class="schema-kicker">Sankey Map</span>
            <h2>Select a table group to explore its flow.</h2>
            <p>After a case is selected, this page maps Excel workbooks into raw schemas, merged ontology classes, and the final schema file.</p>
          </div>
          <button class="report-action primary-import-submit" id="sankey-open-data" type="button">
            <span>Open Data & Inputs</span>
            <small>Select or upload case</small>
          </button>
        </div>
      `;
      const openData = $('#sankey-open-data');
      if (openData) openData.addEventListener('click', () => openPanel('import'));
      return;
    }

    const graph = currentCase.process && currentCase.process.sankey ? currentCase.process.sankey : { nodes: [], links: [] };
    const stats = graph.stats || {};
    els.sankeyContent.innerHTML = `
      <div class="schema-hero ontology-hero case-workspace-hero sankey-hero">
        <div>
          <span class="schema-kicker">Sankey Map</span>
          <h2>${escapeHtml(currentCase.name || 'Selected case')} data lineage</h2>
          <p>Click any node to open a readable file preview. The map keeps only the user-facing flow: Excel workbook, raw schema, merged ontology, and final schema file.</p>
        </div>
        <div class="schema-stat-stack">
          <strong>${escapeHtml(stats.node_count || graph.nodes.length || 0)}</strong><span>nodes</span>
          <strong>${escapeHtml(stats.link_count || graph.links.length || 0)}</strong><span>links</span>
          <strong>${escapeHtml(stats.artifact_count || 0)}</strong><span>artifacts</span>
        </div>
      </div>
      ${renderSankeyCaseSnapshot(currentCase)}
      <div class="sankey-layout">
        <section class="sankey-card">
          <div class="sankey-card-head">
            <div class="sankey-card-copy">
              <span class="sankey-card-kicker">Interactive lineage</span>
              <h3>Business data lineage</h3>
              <p>Follow each workbook into its raw schema, merged ontology, and final schema file.</p>
            </div>
            <div class="sankey-card-actions">
              <button class="sankey-expand-button" id="sankey-expand-map" type="button">
                <span class="sankey-expand-icon">⤢</span>
                <span class="sankey-expand-copy">
                  <strong>Expand Map</strong>
                  <small>Open large canvas</small>
                </span>
              </button>
            </div>
            <div class="sankey-flow-rail" aria-label="Sankey flow stages">
              <span class="workbook">Workbook</span>
              <em></em>
              <span class="raw_schema">Raw Schema</span>
              <em></em>
              <span class="merged_class">Merged Ontology</span>
              <em></em>
              <span class="final_schema_file">Final Schema File</span>
            </div>
          </div>
          ${renderSankeySvg(graph)}
        </section>
      </div>
      ${renderSankeyCaseFooter(currentCase)}
    `;
    bindSankeyActions(graph);
  }

  function renderActivePanel() {
    if (state.activePanel === 'sankey') {
      renderSankeyPanel();
      return;
    }
    if (state.activePanel === 'import') {
      return;
    }
    renderSankeyPanel();
  }

  function renderSankeyCaseSnapshot(currentCase) {
    const stats = currentCase.stats || {};
    const process = currentCase.process || {};
    const extraction = Array.isArray(process.extraction_map) ? process.extraction_map : [];
    const mergeEvents = Array.isArray(process.merge_events) ? process.merge_events : [];
    const files = Array.isArray(currentCase.files) ? currentCase.files : [];
    const fileNames = files.map((file) => file.source_filename).filter(Boolean).slice(0, 3);
    const statItems = [
      ['Files', stats.workbook_count || files.length || 0],
      ['Sheets', stats.sheet_count || 0],
      ['Tables', stats.table_count || extraction.length || 0],
      ['Fields', stats.field_count || 0],
    ];
    return `
      <section class="sankey-case-snapshot">
        <div>
          <span class="case-badge active">Selected table group</span>
          <h3>${escapeHtml(currentCase.name || currentCase.id || 'Excel case')}</h3>
          <p>${fileNames.length ? escapeHtml(fileNames.join(' · ')) : 'No workbook names available.'}</p>
        </div>
        <div class="sankey-case-stat-row">
          ${statItems.map(([label, value]) => `<div><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`).join('')}
          <div><strong>${escapeHtml(mergeEvents.length)}</strong><span>Merges</span></div>
        </div>
      </section>
    `;
  }

  function renderSankeyCaseFooter(currentCase) {
    const process = currentCase.process || {};
    const artifacts = Array.isArray(process.artifacts) ? process.artifacts.filter((item) => !isHiddenUserFile(item.path || item.name || '')) : [];
    const stats = currentCase.stats || {};
    const questions = Array.isArray(currentCase.questions) ? currentCase.questions : [];
    const lastQuestion = questions[0] || currentCase.question || '';
    return `
      <section class="sankey-case-footer">
        <div>
          <span>Business question</span>
          <p>${lastQuestion ? escapeHtml(truncate(lastQuestion, 150)) : 'No upload-time business question was provided.'}</p>
        </div>
        <div>
          <span>Prepared models</span>
          <p>${escapeHtml(stats.generated_file_count || 0)} Python artifact${Number(stats.generated_file_count || 0) === 1 ? '' : 's'} prepared.</p>
        </div>
        <div>
          <span>Final files</span>
          <p>${escapeHtml(artifacts.length)} generated artifact${artifacts.length === 1 ? '' : 's'} available.</p>
        </div>
      </section>
    `;
  }

  function renderSankeySvg(graph, options = {}) {
    const allNodes = Array.isArray(graph.nodes) ? graph.nodes.filter((node) => !isHiddenUserFile(sankeyNodePreviewPath(node))) : [];
    const visibleNodeIds = new Set(allNodes.map((node) => node.id));
    const nodes = allNodes;
    const links = Array.isArray(graph.links)
      ? graph.links.filter((link) => visibleNodeIds.has(link.source) && visibleNodeIds.has(link.target))
      : [];
    if (!nodes.length) {
      return '<div class="empty-state compact-empty">No Sankey data is available yet. Re-import the case or run the model to capture merge trace data.</div>';
    }
    const stageOrder = ['workbook', 'schema', 'merged', 'final'];
    const stageLabels = {
      workbook: 'Excel Workbooks',
      schema: 'Raw Schema',
      merged: 'Merged Ontology',
      final: 'Final Schema File',
    };
    const visibleStages = stageOrder.filter((stage) => nodes.some((node) => node.stage === stage));
    const large = Boolean(options.large);
    const nodeWidth = large ? 260 : 230;
    const nodeHeight = large ? 50 : 46;
    const columnGap = large ? 460 : 390;
    const horizontalPadding = large ? 58 : 42;
    const width = Math.max(
      large ? 1880 : 1540,
      horizontalPadding * 2 + nodeWidth + Math.max(visibleStages.length - 1, 0) * columnGap,
    );
    const byStage = visibleStages.reduce((acc, stage) => ({ ...acc, [stage]: nodes.filter((node) => node.stage === stage) }), {});
    const maxRows = Math.max(...Object.values(byStage).map((items) => items.length), 1);
    const rowPitch = large ? 88 : 76;
    const top = large ? 104 : 96;
    const bottom = large ? 72 : 64;
    const height = Math.max(large ? 780 : 620, top + bottom + nodeHeight + Math.max(maxRows - 1, 0) * rowPitch);
    const positioned = {};
    visibleStages.forEach((stage, stageIndex) => {
      const items = byStage[stage] || [];
      const x = horizontalPadding + stageIndex * ((width - horizontalPadding * 2 - nodeWidth) / Math.max(visibleStages.length - 1, 1));
      const usable = height - top - bottom;
      const gap = items.length > 1 ? usable / (items.length - 1) : 0;
      items.forEach((node, index) => {
        positioned[node.id] = {
          ...node,
          x,
          y: items.length === 1 ? top + usable / 2 : top + index * gap,
          width: nodeWidth,
          height: nodeHeight,
        };
      });
    });
    const maxValue = Math.max(...links.map((link) => Number(link.value) || 1), 1);
    const linkMarkup = links.map((link) => {
      const source = positioned[link.source];
      const target = positioned[link.target];
      if (!source || !target) return '';
      const sx = source.x + source.width;
      const sy = source.y + source.height / 2;
      const tx = target.x;
      const ty = target.y + target.height / 2;
      const curve = Math.max(80, (tx - sx) * .52);
      const widthValue = Math.max(2.5, Math.min(16, 2.5 + ((Number(link.value) || 1) / maxValue) * 13));
      return `
        <path class="sankey-link ${escapeAttr(source.kind || 'node')}-to-${escapeAttr(target.kind || 'node')}" d="M ${sx} ${sy} C ${sx + curve} ${sy}, ${tx - curve} ${ty}, ${tx} ${ty}" stroke-width="${widthValue}">
          <title>${escapeHtml(`${source.label} → ${target.label} · ${link.value || 1} ${link.label || ''}`)}</title>
        </path>
      `;
    }).join('');
    const headerMarkup = visibleStages.map((stage, index) => {
      const x = horizontalPadding + index * ((width - horizontalPadding * 2 - nodeWidth) / Math.max(visibleStages.length - 1, 1));
      return `
        <g class="sankey-stage-chip">
          <rect x="${x}" y="22" width="${nodeWidth}" height="30" rx="15"></rect>
          <text class="sankey-stage-label" x="${x + 12}" y="41">${escapeHtml(stageLabels[stage] || stage)}</text>
        </g>
      `;
    }).join('');
    const nodeMarkup = Object.values(positioned).map((node) => {
      const active = node.id === state.sankeyActiveNodeId;
      const label = truncateSankeyText(node.label || node.id, large ? 36 : 28);
      const meta = node.meta || {};
      const sub = meta.field_count != null ? `${meta.field_count} fields` : (meta.path ? artifactBasename(meta.path) : node.kind);
      return `
        <g class="sankey-node kind-${escapeAttr(node.kind || 'node')} ${active ? 'active' : ''}" data-node-id="${escapeAttr(node.id)}" tabindex="0" role="button" aria-label="${escapeAttr(node.label || node.id)}">
          <rect class="sankey-node-shadow" x="${node.x - 2}" y="${node.y + 5}" width="${node.width + 4}" height="${node.height}" rx="14"></rect>
          <rect x="${node.x}" y="${node.y}" width="${node.width}" height="${node.height}" rx="10"></rect>
          <text class="sankey-node-label" x="${node.x + 12}" y="${node.y + 17}">${escapeHtml(label)}</text>
          <text class="sankey-node-sub" x="${node.x + 12}" y="${node.y + 36}">${escapeHtml(truncateSankeyText(sub, large ? 40 : 34))}</text>
          <title>${escapeHtml(node.label || node.id)}</title>
        </g>
      `;
    }).join('');
    return `
      <div class="sankey-scroll ${large ? 'large' : ''}" aria-label="Interactive Sankey map">
        <svg class="sankey-svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="Case data Sankey map">
          ${headerMarkup}
          <g class="sankey-links">${linkMarkup}</g>
          <g class="sankey-nodes">${nodeMarkup}</g>
        </svg>
      </div>
    `;
  }

  function sankeyNodeSubtitle(node) {
    const meta = node.meta || {};
    if (node.kind === 'workbook') return `${(meta.sheets || []).length || 0} raw schema sheet${((meta.sheets || []).length || 0) === 1 ? '' : 's'}`;
    if (node.kind === 'raw_schema' || node.kind === 'raw_table') return `${meta.source_filename || 'Workbook'} · ${meta.field_count || 0} fields`;
    if (node.kind === 'merged_class') return meta.decision ? `Merged ontology class · ${meta.decision}` : 'Merged ontology class from model trace';
    if (node.kind === 'final_schema_file' || node.kind === 'python_artifact') return meta.path || 'Final schema Python file';
    return node.stage || 'Sankey node';
  }

  function sankeyNodePreviewPath(node) {
    const meta = node && node.meta ? node.meta : {};
    if (meta.path && !isHiddenUserFile(meta.path)) return meta.path;
    if (meta.generated_file && !isHiddenUserFile(meta.generated_file)) return meta.generated_file;
    if (Array.isArray(meta.output_paths)) {
      return meta.output_paths.find((path) => !isHiddenUserFile(path)) || '';
    }
    return '';
  }

  function sankeyNodeKindLabel(node) {
    const kind = node && node.kind ? node.kind : '';
    if (kind === 'workbook') return 'Excel Workbook';
    if (kind === 'raw_schema' || kind === 'raw_table') return 'Raw Schema';
    if (kind === 'merged_class') return 'Merged Ontology';
    if (kind === 'final_schema_file' || kind === 'python_artifact') return 'Final Schema File';
    return 'Preview';
  }

  function renderSankeyTablePreview(meta) {
    const preview = meta.preview || {};
    const headers = Array.isArray(preview.headers) ? preview.headers : [];
    const rows = Array.isArray(preview.sample_rows) ? preview.sample_rows : [];
    const fields = Array.isArray(meta.fields) ? meta.fields : [];
    const tableRows = rows.length ? rows : [headers];
    return `
      <div class="sankey-preview-section">
        <div class="sankey-preview-title">
          <strong>Original Excel table sample</strong>
          <small>${escapeHtml(meta.table_name || meta.sheet_name || '')}</small>
        </div>
        ${tableRows.length ? `
          <div class="sankey-table-wrap">
            <table class="sankey-preview-table">
              <tbody>
                ${tableRows.map((row, rowIndex) => `
                  <tr class="${rowIndex === (preview.header_row_index || 2) - 1 ? 'header-row' : ''}">
                    ${(Array.isArray(row) ? row : [row]).map((cell) => `<td>${escapeHtml(cell)}</td>`).join('')}
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        ` : '<div class="empty-state compact-empty">No sample rows were persisted for this sheet.</div>'}
        <div class="process-field-list sankey-field-list">
          ${fields.slice(0, 16).map((field) => `
            <span title="${escapeAttr(field.comment || '')}">${escapeHtml(field.original_name || field.field_name || '')} <em>${escapeHtml(field.field_name || '')}:${escapeHtml(field.python_type || '')}</em></span>
          `).join('')}
        </div>
      </div>
    `;
  }

  function renderSankeyCodePreview(path, preview, loading, error) {
    if (loading) {
      return '<div class="sankey-code-preview loading">Loading schema preview...</div>';
    }
    if (error) {
      return `<div class="import-message error">${escapeHtml(error)}</div>`;
    }
    if (!preview) {
      return '<div class="sankey-code-preview loading">Click again if the preview does not load automatically.</div>';
    }
    if (isPythonArtifact(path, preview)) {
      return renderSankeyPythonSchemaPreview(path, preview);
    }
    return `
      <div class="sankey-preview-section">
        <div class="sankey-preview-title">
          <strong>${escapeHtml(preview.name || artifactBasename(path))}</strong>
          ${renderSankeyDownloadAction(path)}
        </div>
        <div class="sankey-code-preview">
          <pre><code>${escapeHtml(preview.content || '')}${preview.truncated ? '\n... [truncated]' : ''}</code></pre>
        </div>
      </div>
    `;
  }

  function isPythonArtifact(path, preview) {
    return /\.py$/i.test(preview && preview.name ? preview.name : artifactBasename(path));
  }

  function renderSankeyDownloadAction(path) {
    return `
      <a class="sankey-download-action" href="${artifactDownloadHref(path)}" download title="${escapeAttr(displayArtifactPath(path))}">
        <span class="sankey-download-icon">↓</span>
        <span class="sankey-download-copy">
          <strong>Download schema file</strong>
          <small>${escapeHtml(artifactBasename(path))}</small>
        </span>
      </a>
    `;
  }

  function renderSankeyPythonSchemaPreview(path, preview) {
    const schema = parsePythonSchema(preview.content || '');
    const classes = schema.classes;
    const entities = classes.filter((item) => item.kind === 'Entity');
    const fieldCount = entities.reduce((total, item) => total + item.fields.length, 0);
    const operationCount = entities.reduce((total, item) => total + item.operations.length, 0);
    const intro = schema.summary || 'This file defines the business-facing ontology schema generated from the selected Excel case.';
    return `
      <div class="sankey-schema-preview">
        <div class="sankey-schema-hero">
          <div>
            <span class="case-badge active">Business schema</span>
            <h4>${escapeHtml(preview.name || artifactBasename(path))}</h4>
            <p>${escapeHtml(intro)}</p>
          </div>
          ${renderSankeyDownloadAction(path)}
        </div>
        <div class="sankey-schema-stats">
          <div><strong>${escapeHtml(entities.length)}</strong><span>Entities</span></div>
          <div><strong>${escapeHtml(fieldCount)}</strong><span>Fields</span></div>
          <div><strong>${escapeHtml(operationCount)}</strong><span>Operations</span></div>
          <div><strong>${escapeHtml(classes.length - entities.length)}</strong><span>Hidden support types</span></div>
        </div>
        ${entities.length ? `
          <div class="sankey-schema-class-grid">
            ${entities.map(renderPythonSchemaClassCard).join('')}
          </div>
        ` : '<div class="empty-state compact-empty">No entity classes could be detected in this Python file.</div>'}
      </div>
    `;
  }

  function renderPythonSchemaClassCard(item) {
    const fields = item.fields.slice(0, 12);
    const hiddenFields = Math.max(item.fields.length - fields.length, 0);
    const operations = item.operations.slice(0, 6);
    const values = item.values.slice(0, 12);
    return `
      <article class="sankey-schema-class-card kind-${escapeAttr(item.kind.toLowerCase().replace(/\s+/g, '-'))}">
        <div class="sankey-schema-class-head">
          <span>${escapeHtml(item.kind)}</span>
          <h5>${escapeHtml(humanizeIdentifier(item.name))}</h5>
          <small>${escapeHtml(item.name)}</small>
        </div>
        ${item.description ? `<p class="sankey-schema-description">${escapeHtml(item.description)}</p>` : ''}
        ${item.sources.length ? `
          <div class="sankey-schema-chip-row">
            <strong>Sources</strong>
            ${item.sources.slice(0, 6).map((source) => `<span>${escapeHtml(humanizeIdentifier(source))}</span>`).join('')}
          </div>
        ` : ''}
        ${fields.length ? `
          <div class="sankey-schema-field-list">
            ${fields.map((field) => `
              <div>
                <strong>${escapeHtml(humanizeIdentifier(field.name))}</strong>
                <span>${escapeHtml(friendlyPythonType(field.type))}</span>
              </div>
            `).join('')}
            ${hiddenFields ? `<div class="more"><strong>+${hiddenFields}</strong><span>more fields</span></div>` : ''}
          </div>
        ` : ''}
        ${values.length ? `
          <div class="sankey-schema-chip-row value-row">
            <strong>Allowed values</strong>
            ${values.map((value) => `<span>${escapeHtml(value)}</span>`).join('')}
          </div>
        ` : ''}
        ${operations.length ? `
          <div class="sankey-schema-chip-row operation-row">
            <strong>Operations</strong>
            ${operations.map((operation) => `<span>${escapeHtml(humanizeIdentifier(operation))}</span>`).join('')}
          </div>
        ` : ''}
      </article>
    `;
  }

  function parsePythonSchema(content) {
    const lines = String(content || '').replace(/\r\n/g, '\n').split('\n');
    const firstClassIndex = lines.findIndex((line) => /^class\s+\w+/.test(line) || /^\s*@(?:dataclass|runtime_checkable)/.test(line));
    const headerText = lines.slice(0, firstClassIndex >= 0 ? firstClassIndex : Math.min(lines.length, 40)).join('\n');
    const summary = cleanPythonDoc(extractTripleQuotedText(headerText)).split('\n').find((line) => line.trim()) || '';
    const classes = [];
    for (let index = 0; index < lines.length; index += 1) {
      const classMatch = lines[index].match(/^class\s+([A-Za-z_]\w*)\s*(?:\(([^)]*)\))?:/);
      if (!classMatch) continue;
      const decorators = [];
      let prev = index - 1;
      while (prev >= 0 && /^\s*@/.test(lines[prev])) {
        decorators.unshift(lines[prev].trim());
        prev -= 1;
      }
      const block = [];
      for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
        if (/^(?:@|class\s+|def\s+|async\s+def\s+)/.test(lines[cursor]) && lines[cursor].trim()) break;
        block.push(lines[cursor]);
      }
      classes.push(parsePythonClassBlock(classMatch[1], classMatch[2] || '', decorators, block));
    }
    return { summary, classes };
  }

  function parsePythonClassBlock(name, bases, decorators, block) {
    const baseList = bases.split(',').map((item) => item.trim()).filter(Boolean);
    const doc = cleanPythonDoc(extractTripleQuotedText(block.join('\n')));
    const kind = classDisplayKind(doc, baseList, decorators, block);
    const description = cleanPythonDescription(doc, kind);
    const sources = extractDocList(doc, 'Source class');
    const fields = [];
    const operations = [];
    const values = [];
    block.forEach((line, index) => {
      const fieldMatch = line.match(/^    ([A-Za-z_]\w*)\s*:\s*([^=#]+?)(?:\s*=\s*[^#]+)?(?:\s*#.*)?$/);
      if (fieldMatch && !fieldMatch[1].startsWith('_')) {
        fields.push({ name: fieldMatch[1], type: fieldMatch[2].trim() });
      }
      const methodMatch = line.match(/^    def\s+([A-Za-z_]\w*)\s*\(/);
      if (methodMatch && !methodMatch[1].startsWith('_')) {
        const methodDoc = extractTripleQuotedText(block.slice(index + 1, index + 5).join('\n'));
        const operationMatch = methodDoc.match(/Operation:\s*([A-Za-z_]\w*)/);
        operations.push(operationMatch ? operationMatch[1] : methodMatch[1]);
      }
      const valueMatch = line.match(/^    ([A-Z][A-Z0-9_]*)\s*=\s*["']([^"']+)["']/);
      if (valueMatch) values.push(valueMatch[2]);
    });
    return { name, kind, description, sources, fields, operations, values };
  }

  function classDisplayKind(doc, bases, decorators, block) {
    const baseText = bases.join(' ');
    if (/Enum\b/.test(baseText)) return 'Value Set';
    if (/Protocol\b/.test(baseText) || decorators.some((item) => item.includes('runtime_checkable')) || /Ontology Interface/i.test(doc)) return 'Interface';
    if (decorators.some((item) => item.includes('dataclass')) || block.some((line) => /^    [A-Za-z_]\w*\s*:/.test(line))) return 'Entity';
    return 'Class';
  }

  function extractTripleQuotedText(value) {
    const match = String(value || '').match(/(?:\"\"\"|''')([\s\S]*?)(?:\"\"\"|''')/);
    return match ? match[1] : '';
  }

  function cleanPythonDoc(value) {
    return String(value || '')
      .split('\n')
      .map((line) => line.replace(/^\s+/, '').trimEnd())
      .join('\n')
      .trim();
  }

  function cleanPythonDescription(doc, kind) {
    const first = String(doc || '').split('\n').map((line) => line.trim()).find((line) => line && !/^(Source class|External links)/i.test(line)) || '';
    return first
      .replace(/^Ontology\s+(Entity|Interface)\s*:\s*/i, '')
      .replace(/^Operation\s*:\s*/i, '')
      .replace(new RegExp(`^${kind}\\s*:\\s*`, 'i'), '');
  }

  function extractDocList(doc, label) {
    const lines = String(doc || '').split('\n');
    const items = [];
    let active = false;
    lines.forEach((line) => {
      const text = line.trim();
      if (new RegExp(`^${label}:?`, 'i').test(text)) {
        active = true;
        return;
      }
      if (active && /^[A-Za-z].*:/.test(text)) {
        active = false;
      }
      if (active) {
        const match = text.match(/^-\s*(.+)$/);
        if (match) items.push(match[1].trim());
      }
    });
    return items;
  }

  function humanizeIdentifier(value) {
    const withSpaces = String(value || '')
      .replace(/_/g, ' ')
      .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
      .replace(/\s+/g, ' ')
      .trim();
    return withSpaces.replace(/\b\w/g, (char) => char.toUpperCase()).replace(/\bRid\b/g, 'RID');
  }

  function friendlyPythonType(value) {
    let text = String(value || '').trim().replace(/['"]/g, '');
    text = text.replace(/^Optional\[(.*)\]$/, '$1');
    text = text.replace(/^list\[(.*)\]$/, 'List of $1');
    text = text.replace(/^List\[(.*)\]$/, 'List of $1');
    const lower = text.toLowerCase();
    if (lower === 'str') return 'Text';
    if (lower === 'int') return 'Integer';
    if (lower === 'float') return 'Decimal';
    if (lower === 'bool') return 'Yes / No';
    if (lower === 'dict') return 'Structured object';
    if (lower.startsWith('list of ')) return `List of ${humanizeIdentifier(text.slice(8))}`;
    return humanizeIdentifier(text);
  }

  function renderSankeyMetadata(meta) {
    const items = Object.entries(meta || {}).filter(([, value]) => value != null && value !== '' && !Array.isArray(value) && typeof value !== 'object');
    const arrays = Object.entries(meta || {}).filter(([, value]) => Array.isArray(value) && value.length);
    return `
      <div class="sankey-preview-section">
        <div class="sankey-preview-title"><strong>Persisted model trace</strong><small>metadata</small></div>
        <div class="sankey-meta-grid">
          ${items.map(([key, value]) => `<div><span>${escapeHtml(key)}</span><strong>${escapeHtml(value)}</strong></div>`).join('')}
        </div>
        ${arrays.map(([key, values]) => `
          <div class="process-field-list sankey-field-list">
            <strong>${escapeHtml(key)}</strong>
            ${values.slice(0, 16).map((value) => `<span>${escapeHtml(typeof value === 'string' ? value : JSON.stringify(value))}</span>`).join('')}
          </div>
        `).join('')}
      </div>
    `;
  }

  function renderSankeyWorkbookPreview(meta) {
    const sheets = Array.isArray(meta.sheets) ? meta.sheets : [];
    if (!sheets.length) {
      return '<div class="empty-state compact-empty">No workbook preview rows were persisted for this file.</div>';
    }
    return sheets.map((sheet) => renderSankeyTablePreview({
      ...sheet,
      source_filename: meta.source_filename,
      raw_path: meta.raw_path,
    })).join('');
  }

  function renderSankeyNodeModal(node) {
    if (!node) return '<div class="empty-state compact-empty">This Sankey node is no longer available.</div>';
    const meta = node.meta || {};
    const path = sankeyNodePreviewPath(node);
    const preview = path ? state.sankeyFileCache[path] : null;
    const loading = path && state.sankeyPreviewLoading === path;
    const error = state.sankeyPreviewError && state.sankeyActiveNodeId === node.id ? state.sankeyPreviewError : '';
    if (node.kind === 'workbook') return renderSankeyWorkbookPreview(meta);
    if (node.kind === 'raw_schema' || node.kind === 'raw_table') return renderSankeyTablePreview(meta);
    if (path) return renderSankeyCodePreview(path, preview, loading, error);
    return renderSankeyMetadata(meta);
  }

  function openSankeyModal(title, subtitle, bodyHtml, options = {}) {
    closeSankeyModal();
    const overlay = document.createElement('div');
    overlay.className = `sankey-modal-overlay active${options.map ? ' map-modal' : ''}`;
    overlay.innerHTML = `
      <div class="sankey-modal ${options.map ? 'sankey-map-modal' : ''}" role="dialog" aria-modal="true" aria-label="${escapeAttr(title)}">
        <div class="sankey-modal-head">
          <div>
            <span class="case-badge active">${escapeHtml(options.badge || 'Preview')}</span>
            <h3>${escapeHtml(title)}</h3>
            ${subtitle ? `<p>${escapeHtml(subtitle)}</p>` : ''}
          </div>
          <button class="modal-close sankey-modal-close" type="button" aria-label="Close">×</button>
        </div>
        <div class="sankey-modal-body">${bodyHtml}</div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) closeSankeyModal();
    });
    const closeButton = overlay.querySelector('.sankey-modal-close');
    if (closeButton) closeButton.addEventListener('click', closeSankeyModal);
    if (options.map && options.graph) bindSankeyActions(options.graph, overlay);
  }

  function closeSankeyModal() {
    document.querySelectorAll('.sankey-modal-overlay').forEach((item) => item.remove());
  }

  function openSankeyMapModal(graph) {
    openSankeyModal(
      'Expanded Sankey Map',
      'Click any node in the enlarged map to open its Excel or Python preview.',
      renderSankeySvg(graph, { large: true }),
      { map: true, graph, badge: 'Expanded lineage' },
    );
  }

  function bindSankeyActions(graph, root = els.sankeyContent) {
    if (!root) return;
    const expandButton = root.querySelector('#sankey-expand-map');
    if (expandButton) {
      expandButton.addEventListener('click', () => openSankeyMapModal(graph));
    }
    root.querySelectorAll('[data-node-id]').forEach((nodeEl) => {
      const handler = () => selectSankeyNode(graph, nodeEl.dataset.nodeId || '');
      nodeEl.addEventListener('click', handler);
      nodeEl.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          handler();
        }
      });
    });
  }

  async function selectSankeyNode(graph, nodeId) {
    const node = (graph.nodes || []).find((item) => item.id === nodeId);
    if (!node) return;
    state.sankeyActiveNodeId = nodeId;
    state.sankeyPreviewError = '';
    openSankeyModal(node.label || node.id, sankeyNodeSubtitle(node), renderSankeyNodeModal(node), { badge: sankeyNodeKindLabel(node) });
    const path = sankeyNodePreviewPath(node);
    if (!path || state.sankeyFileCache[path]) return;
    state.sankeyPreviewLoading = path;
    openSankeyModal(node.label || node.id, sankeyNodeSubtitle(node), renderSankeyNodeModal(node), { badge: sankeyNodeKindLabel(node) });
    try {
      state.sankeyFileCache[path] = await api(`/api/files/preview?path=${encodeURIComponent(path)}`);
    } catch (error) {
      state.sankeyPreviewError = String(error.message || error);
    } finally {
      state.sankeyPreviewLoading = '';
      openSankeyModal(node.label || node.id, sankeyNodeSubtitle(node), renderSankeyNodeModal(node), { badge: sankeyNodeKindLabel(node) });
    }
  }

  function renderImportPanel() {
    if (!els.importContent) return;
    const imports = caseCatalog();
    const currentCase = selectedCase();
    const result = state.importResult && state.importResult.import ? state.importResult.import : null;
    const latest = result ? [result, ...imports.filter((item) => item.id !== result.id)] : imports;
    const fileNames = state.selectedCaseFileNames || '';
    els.importContent.innerHTML = `
      <div class="schema-hero ontology-hero import-hero refined-import-hero data-studio-hero">
        <div>
          <span class="schema-kicker">Data & Inputs</span>
          <h2>Curate the source material before the agent reasons.</h2>
          <p>Upload Excel workbooks, select the active case, and inspect generated Python models before ontology generation.</p>
        </div>
        <div class="import-steps" aria-label="Excel import steps">
          <span><strong>1</strong>Upload Excel</span>
          <span><strong>2</strong>Select case</span>
          <span><strong>3</strong>Trace the process</span>
        </div>
      </div>
      <form class="import-card refined-import-card" id="case-import-form">
        <div class="form-section-title">
          <span>Excel source</span>
          <small>Raw workbooks stay immutable; generated models are stored as case artifacts.</small>
        </div>
        <div class="import-field">
          <label class="field-label" for="case-name">
            <span>Case name</span>
            <small>A readable name for the uploaded workbook set.</small>
          </label>
          <input id="case-name" name="case_name" type="text" placeholder="customer retention analysis">
        </div>
        <div class="import-field">
          <div class="field-label">
            <span>Excel files</span>
            <small>Select .xlsx or .xlsm workbooks. Multiple files are imported as one case.</small>
          </div>
          <label class="file-dropzone ${fileNames ? 'has-file' : ''}" for="case-files">
            <input id="case-files" class="file-picker-input" name="files" type="file" multiple accept=".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet">
            <span class="file-dropzone-icon">XLS</span>
            <span class="file-dropzone-copy">
              <strong id="case-file-name">${escapeHtml(fileNames || (state.importingCase ? 'Uploading selected workbooks...' : 'Choose Excel workbooks'))}</strong>
              <small id="case-file-hint">${escapeHtml(fileNames ? 'Ready to prepare as a case.' : 'No files selected yet. Click here to browse.')}</small>
            </span>
            <span id="case-file-action" class="file-dropzone-action">${fileNames ? 'Change files' : 'Browse'}</span>
          </label>
        </div>
        <div class="import-field">
          <label class="field-label">
            <span>Prepared model style</span>
            <small>The first-pass artifact is always generated as Python classes.</small>
          </label>
          <div class="fixed-model-style wide" aria-label="Fixed prepared model style">
            <strong>Python class</strong>
            <small>Not configurable in this workflow</small>
          </div>
        </div>
        <div class="format-example compact-format">
          <div>
            <strong>Metadata sheets</strong>
            <pre>field_name / data_type / unit / notes</pre>
          </div>
          <div>
            <strong>Raw tables</strong>
            <pre>Detected header row + sample rows</pre>
          </div>
          <div>
            <strong>Multiple files</strong>
            <pre>Imported together as one named case</pre>
          </div>
        </div>
        <button class="report-action import-submit primary-import-submit ${state.importingCase ? 'loading' : ''}" type="submit" ${state.importingCase ? 'disabled' : ''}>
          <span>${state.importingCase ? 'Uploading and preparing...' : 'Prepare and select case'}</span>
          <small>${state.importingCase ? escapeHtml(fileNames || 'Processing workbooks') : 'Generate models and make this case active'}</small>
        </button>
        ${state.importError ? `<div class="import-message error">${escapeHtml(state.importError)}</div>` : ''}
        ${result ? `<div class="import-message success">Prepared ${escapeHtml(result.name || result.id)} (${formatCaseStats(result.stats || {})}) and selected it for the next chat run.</div>` : ''}
      </form>
      <div class="schema-section-title"><h3>Case Catalog</h3><small>${latest.length} selectable cases</small></div>
      <div class="import-list">
        ${latest.length ? latest.map(renderCaseImportItem).join('') : '<div class="empty-state">No uploaded Excel cases yet.</div>'}
      </div>
    `;
    const form = $('#case-import-form');
    if (form) form.addEventListener('submit', handleCaseImport);
    const fileInput = $('#case-files');
    if (fileInput) fileInput.addEventListener('change', handleCaseFileChange);
    bindCaseSelectionButtons(els.importContent);
  }

  function renderCaseImportItem(item) {
    const stats = item.stats || {};
    const files = item.files || [];
    const processCounts = item.process_counts || {};
    const active = item.id && item.id === state.selectedCaseId;
    const deleting = item.id && item.id === state.deletingCaseId;
    return `
      <div class="import-item ${active ? 'active-case' : ''}">
        <div class="import-item-main">
          <div>
            <span class="case-badge ${active ? 'active' : ''}">${active ? 'Active case' : 'Selectable case'}</span>
            <strong>${escapeHtml(item.name || item.id || 'Excel case')}</strong>
            <p>${formatCaseStats(stats)} · ${escapeHtml(processCounts.merge_event_count || 0)} merge events${item.question ? ` · ${escapeHtml(truncate(item.question, 90))}` : ''}</p>
            <code>${escapeHtml(item.id || '')}</code>
          </div>
          <div class="case-catalog-actions">
            <button class="case-select-button" type="button" data-select-case="${escapeHtml(item.id || '')}" ${active ? 'disabled' : ''}>
              ${active ? 'Selected' : 'Use this case'}
            </button>
            <button class="report-action secondary danger-action case-delete-button" type="button" data-delete-case="${escapeHtml(item.id || '')}" data-case-name="${escapeHtml(item.name || item.id || 'this case')}" ${deleting ? 'disabled' : ''}>
              ${deleting ? 'Deleting...' : 'Delete'}
            </button>
          </div>
        </div>
        <small>${escapeHtml(formatDate(item.created_at))}</small>
        <details>
          <summary>Excel files and prepared metadata</summary>
          <pre>${escapeHtml([
            `raw_dir: ${item.raw_dir || ''}`,
            `output_dir: ${item.output_dir || ''}`,
            ...(files.length ? files.map((file) => `${file.source_filename || ''} -> ${file.prepared_dir || ''}`) : ['No file list available']),
          ].join('\n'))}</pre>
        </details>
      </div>
    `;
  }

  function bindCaseSelectionButtons(root) {
    if (!root) return;
    root.querySelectorAll('[data-select-case]').forEach((button) => {
      button.addEventListener('click', async () => {
        state.selectedCaseId = button.dataset.selectCase || '';
        localStorage.setItem('otology_case_scope_id', state.selectedCaseId);
        await loadSelectedCaseDetail();
        renderCaseScopeSelector();
        renderSankeyPanel();
        renderImportPanel();
      });
    });
    root.querySelectorAll('[data-delete-case]').forEach((button) => {
      button.addEventListener('click', () => handleCaseDelete(button.dataset.deleteCase || '', button.dataset.caseName || 'this case'));
    });
  }

  function handleCaseFileChange(event) {
    const input = event.currentTarget;
    const files = input && input.files ? Array.from(input.files) : [];
    state.selectedCaseFileNames = files.length ? files.map((file) => file.name).join(', ') : '';
    updateFilePickerLabel(
      'case-file-name',
      'case-file-hint',
      input.closest('.file-dropzone'),
      state.selectedCaseFileNames,
      'Choose Excel workbooks',
      'Ready to prepare as a case.',
      'No files selected yet. Click here to browse.',
    );
  }

  async function handleCaseImport(event) {
    event.preventDefault();
    if (state.importingCase) return;
    const fileInput = $('#case-files');
    const files = fileInput && fileInput.files ? Array.from(fileInput.files) : [];
    if (!files.length) {
      state.importError = 'Please choose at least one .xlsx or .xlsm workbook.';
      renderImportPanel();
      return;
    }
    state.selectedCaseFileNames = files.map((file) => file.name).join(', ');
    const form = new FormData();
    files.forEach((file) => form.append('files', file));
    form.append('case_name', $('#case-name') ? $('#case-name').value : '');
    state.importingCase = true;
    state.importError = '';
    state.importResult = null;
    renderImportPanel();
    try {
      const response = await fetch('/api/cases/imports', { method: 'POST', body: form });
      if (!response.ok) throw new Error(await response.text());
      state.importResult = await response.json();
      state.health = await api('/api/health');
      const imported = state.importResult && state.importResult.import ? state.importResult.import : null;
      if (imported && imported.id) {
        state.selectedCaseId = imported.id;
        localStorage.setItem('otology_case_scope_id', state.selectedCaseId);
      }
      normalizeSelectedCase();
      state.selectedCaseFileNames = '';
      state.importError = '';
    } catch (error) {
      state.selectedCaseFileNames = '';
      state.importError = String(error.message || error);
    } finally {
      state.importingCase = false;
      renderSankeyPanel();
      renderCaseScopeSelector();
      renderImportPanel();
    }
  }

  async function handleCaseDelete(caseId, caseName) {
    if (!caseId || state.deletingCaseId) return;
    if (!window.confirm(`Delete "${caseName}"? This removes the uploaded Excel files, prepared models, and generated case outputs for this case.`)) return;

    state.deletingCaseId = caseId;
    state.importError = '';
    state.importResult = null;
    renderImportPanel();
    try {
      const response = await fetch(`/api/cases/imports/${encodeURIComponent(caseId)}`, { method: 'DELETE' });
      const responseText = await response.text();
      let responsePayload = null;
      if (responseText) {
        try {
          responsePayload = JSON.parse(responseText);
        } catch (error) {
          responsePayload = null;
        }
      }
      if (!response.ok) {
        try {
          state.health = await api('/api/health');
        } catch (error) {
          // Keep the previous catalog when health is temporarily unavailable.
        }
        const stillListed = caseCatalog().some((item) => item.id === caseId);
        if (response.status === 404 && !stillListed) {
          if (state.selectedCaseId === caseId) {
            state.selectedCaseId = '';
            localStorage.setItem('otology_case_scope_id', '');
          }
          delete state.caseDetails[caseId];
          state.importError = 'That case was already removed; the catalog has been refreshed.';
          return;
        }
        const detail = responsePayload && responsePayload.detail ? String(responsePayload.detail) : responseText;
        if (response.status === 404 && stillListed && detail === 'Not Found') {
          throw new Error('Delete endpoint is not loaded in the running backend. Restart the Otology frontend server, refresh this page, then try Delete again.');
        }
        throw new Error(detail || `Delete failed with HTTP ${response.status}.`);
      }
      if (state.selectedCaseId === caseId) {
        state.selectedCaseId = '';
        localStorage.setItem('otology_case_scope_id', '');
      }
      delete state.caseDetails[caseId];
      state.health = await api('/api/health');
      normalizeSelectedCase();
      state.importError = '';
    } catch (error) {
      state.importError = String(error.message || error);
    } finally {
      state.deletingCaseId = '';
      renderCaseScopeSelector();
      renderSankeyPanel();
      renderImportPanel();
    }
  }

  function defaultOtologySchema() {
    return {
      title: 'Excel To Ontology Workflow',
      subtitle: 'Workbook-first schema for table conversion, semantic refactor, ontology merge, and validation.',
      nodes: [
        { id: 'tables', label: 'Raw Tables', description: 'Excel sheets and original business columns.' },
        { id: 'field_models', label: 'Field Models', description: 'Stable Python fields with source-column comments.' },
        { id: 'entities', label: 'Business Entities', description: 'Domain concepts, interfaces, relations, and operations.' },
        { id: 'merged', label: 'Merged Ontology', description: 'Unified classes with alignment decisions and reports.' },
        { id: 'validation', label: 'Validation', description: 'py_compile, naming checks, and generated artifact review.' },
      ],
      relations: [
        { source: 'Raw Tables', predicate: 'excel_to_python_class', target: 'Field Models', skill: 'excel-to-python-class' },
        { source: 'Field Models', predicate: 'semantic_refactor', target: 'Business Entities', skill: 'business-ontology-refactor' },
        { source: 'Business Entities', predicate: 'align_and_merge', target: 'Merged Ontology', skill: 'ontology-merge' },
        { source: 'Merged Ontology', predicate: 'compile_and_report', target: 'Validation', skill: 'ontology-merge' },
      ],
      artifacts: [
        { name: 'generated_models.py', description: 'Python classes created from tables.' },
        { name: 'merged_ontology.py', description: 'Final unified ontology module.' },
        { name: 'alignment_report.md', description: 'Entity, field, relation, and assumption report.' },
        { name: 'validation.log', description: 'py_compile and naming-rule evidence.' },
      ],
    };
  }

  function renderOtologySchema(project) {
    const skills = project.skills || [];
    const tools = project.tools || [];
    const cases = caseCatalog();
    const currentCase = selectedCase();
    const process = currentCase && currentCase.process ? currentCase.process : null;
    const extractionCount = process && process.extraction_map ? process.extraction_map.length : 0;
    const mergeCount = process && process.merge_events ? process.merge_events.length : 0;
    return `
      <div class="schema-hero ontology-hero case-workspace-hero process-flow-hero">
        <div>
          <span class="schema-kicker">Process Flow</span>
          <h2>${currentCase ? escapeHtml(currentCase.name || 'Selected Excel case') : 'Visualize Excel-to-ontology before and after the run.'}</h2>
          <p>${currentCase ? `${escapeHtml(formatCaseStats(currentCase.stats || {}))} · ${escapeHtml(extractionCount)} sheet-to-class links · ${escapeHtml(mergeCount)} merge events` : 'Select a case to see which sheets produced which Python classes, then watch merge decisions accumulate from tool/model traces.'}</p>
        </div>
        <div class="schema-stat-stack">
          <strong>${cases.length}</strong><span>cases</span>
          <strong>${extractionCount}</strong><span>classes</span>
          <strong>${mergeCount}</strong><span>merges</span>
        </div>
      </div>

      ${currentCase ? renderProcessOverview(currentCase, skills, tools) : renderEmptyProcessWorkspace()}
      ${currentCase ? renderProcessStages(process ? process.stages || [] : []) : ''}
      ${currentCase ? renderExtractionMap(process) : ''}
      ${currentCase ? renderMergeTrace(process) : ''}
      ${currentCase ? renderValidationSummary(currentCase) : ''}
    `;
  }

  function renderEmptyProcessWorkspace() {
    return `
      <div class="active-case-card empty-case-card">
        <div>
          <span class="case-badge">No active case</span>
          <h3>Start by uploading an Excel case.</h3>
          <p>The process view becomes useful after Data & Inputs creates a case: it will show workbook intake, sheet inspection, generated Python classes, merge events, and validation state.</p>
        </div>
        <button class="report-action primary-import-submit" id="schema-manage-case" type="button">
          <span>Open Data & Inputs</span>
          <small>Upload Excel and prepare models</small>
        </button>
      </div>
    `;
  }

  function renderProcessOverview(item, skills, tools) {
    const stats = item.stats || {};
    const statItems = [
      ['Workbooks', stats.workbook_count],
      ['Sheets', stats.sheet_count],
      ['Tables', stats.table_count],
      ['Fields', stats.field_count],
      ['Generated files', stats.generated_file_count],
    ];
    return `
      <div class="active-case-card">
        <div class="active-case-head">
          <div>
            <span class="case-badge active">Active process</span>
            <h3>${escapeHtml(item.name || item.id || 'Excel case')}</h3>
            <p>${item.question ? escapeHtml(item.question) : 'No upload-time business question was provided.'}</p>
          </div>
          <div class="active-case-actions">
            <button class="report-action" id="schema-manage-case" type="button">Edit data inputs</button>
            <button class="report-action secondary" id="schema-clear-case" type="button">Clear selection</button>
          </div>
        </div>
        <div class="case-stat-grid">
          ${statItems.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value == null ? '-' : value)}</strong></div>`).join('')}
        </div>
        <div class="case-path-grid">
          <div><span>Prepared models</span><code>${escapeHtml(item.prepared_root || 'outputs/otology_skill/cases')}</code></div>
          <div><span>Ontology output</span><code>${escapeHtml(item.output_dir || 'outputs/otology_skill/cases')}</code></div>
        </div>
        <div class="toolchain compact-toolchain">
          ${skills.slice(0, 4).map((skill) => `<span>${escapeHtml(skill)}</span>`).join('')}
          ${tools.slice(0, 6).map((tool) => `<span class="tool-pill">${escapeHtml(tool)}</span>`).join('')}
        </div>
      </div>
    `;
  }

  function renderProcessStages(stages) {
    if (!stages.length) return '';
    return `
      <div class="schema-section-title"><h3>Pipeline Timeline</h3><small>${stages.length} tracked stages</small></div>
      <div class="process-stage-grid">
        ${stages.map((stage, index) => `
          <div class="process-stage-card status-${escapeHtml(stage.status || 'waiting')}">
            <span class="process-stage-index">${index + 1}</span>
            <div>
              <strong>${escapeHtml(stage.label || stage.id || 'Stage')}</strong>
              <p>${escapeHtml(stage.description || '')}</p>
              <small>${escapeHtml(stage.status || 'waiting')} · ${escapeHtml(stage.count == null ? 0 : stage.count)}</small>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }

  function renderExtractionMap(process) {
    const rows = process && process.extraction_map ? process.extraction_map : [];
    return `
      <div class="schema-section-title"><h3>Sheet → Python Class</h3><small>${rows.length} extracted classes</small></div>
      <div class="extraction-map-grid">
        ${rows.length ? rows.map((item) => `
          <div class="extraction-card">
            <div class="extraction-route">
              <span>${escapeHtml(item.source_filename || 'Workbook')}</span>
              <strong>${escapeHtml(item.sheet_name || 'Sheet')}</strong>
              <em>→</em>
              <strong>${escapeHtml(item.class_name || 'GeneratedClass')}</strong>
            </div>
            <div class="extraction-meta">
              <code>${escapeHtml(item.table_name || '')}</code>
              <span>${escapeHtml(item.field_count || 0)} fields</span>
            </div>
            <div class="process-field-list">
              ${(item.fields || []).slice(0, 8).map((field) => `
                <span title="${escapeAttr(field.comment || '')}">${escapeHtml(field.original_name || field.field_name || '')} <em>${escapeHtml(field.field_name || '')}:${escapeHtml(field.python_type || '')}</em></span>
              `).join('')}
            </div>
            ${item.generated_file ? `<code class="generated-path">${escapeHtml(item.generated_file)}</code>` : ''}
          </div>
        `).join('') : '<div class="empty-state compact-empty">No extraction map is available yet. Re-import or refresh the selected case.</div>'}
      </div>
    `;
  }

  function renderMergeTrace(process) {
    const events = process && process.merge_events ? process.merge_events : [];
    return `
      <div class="schema-section-title"><h3>Merge Decisions</h3><small>${events.length} captured events</small></div>
      <div class="merge-trace-list">
        ${events.length ? events.map(renderMergeEvent).join('') : `
          <div class="merge-empty-card">
            <span class="case-badge">Waiting for model run</span>
            <h3>No merge events captured yet.</h3>
            <p>Ask a question with this case selected. When the agent calls <code>merge_ontology_classes</code> or returns <code>PROCESS_TRACE_JSON</code>, the sidebar records which classes were merged or kept separate.</p>
          </div>
        `}
      </div>
    `;
  }

  function renderMergeEvent(event) {
    const payload = event.payload || {};
    const trace = payload.trace || payload;
    const classes = Array.isArray(trace) ? trace : trace.merged_classes || trace.classes || [];
    const conflicts = Array.isArray(trace) ? [] : trace.conflicts || [];
    return `
      <div class="merge-event-card">
        <div class="merge-event-head">
          <div>
            <span>${escapeHtml(event.source || event.event_type || 'runtime')}</span>
            <strong>${escapeHtml(formatDate(event.created_at))}</strong>
          </div>
          <small>${escapeHtml(event.run_id || '')}</small>
        </div>
        <div class="merge-class-list">
          ${classes.length ? classes.slice(0, 8).map((item) => `
            <div>
              <strong>${escapeHtml(item.class_name || item.target_class || 'Merged class')}</strong>
              <p>${escapeHtml((item.original_names || item.source_classes || item.merge_tokens || []).join(' + ') || 'No source class list')}</p>
              <small>${escapeHtml(item.field_count == null ? '' : `${item.field_count} fields`)}${item.source_files && item.source_files.length ? ` · ${escapeHtml(item.source_files.join(', '))}` : ''}</small>
            </div>
          `).join('') : '<div class="empty-state compact-empty">Structured merge class details were not provided.</div>'}
        </div>
        ${conflicts.length ? `<div class="import-message error">${escapeHtml(conflicts.length)} field conflicts need review.</div>` : ''}
      </div>
    `;
  }

  function renderValidationSummary(item) {
    const stats = item.stats || {};
    const process = item.process || {};
    const validation = process.validation || {};
    return `
      <div class="schema-section-title"><h3>Validation & Next Step</h3><small>artifact health</small></div>
      <div class="validation-summary-card ${stats.failed_compile_count ? 'has-warning' : ''}">
        <div>
          <span class="case-badge ${stats.failed_compile_count ? '' : 'active'}">${stats.failed_compile_count ? 'Needs attention' : 'Compile clean'}</span>
          <h3>${escapeHtml(validation.generated_file_count || stats.generated_file_count || 0)} generated files · ${escapeHtml(validation.failed_compile_count || stats.failed_compile_count || 0)} compile failures</h3>
          <p>Use Data & Inputs to add missing business rules, then ask the agent to produce or refine the merged business ontology.</p>
        </div>
        <button class="report-action primary-import-submit" id="schema-ask-case" type="button">
          <span>Ask with this case</span>
          <small>Focus the chat composer</small>
        </button>
      </div>
    `;
  }

  function bindSchemaPanelActions() {
    const manage = $('#schema-manage-case');
    if (manage) manage.addEventListener('click', () => openPanel('import'));
    const ask = $('#schema-ask-case');
    if (ask) {
      ask.addEventListener('click', () => {
        closePanel();
        els.input.focus();
        window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
      });
    }
    const clear = $('#schema-clear-case');
    if (clear) {
      clear.addEventListener('click', () => {
        state.selectedCaseId = '';
        localStorage.setItem('otology_case_scope_id', '');
        renderCaseScopeSelector();
        renderSankeyPanel();
        renderImportPanel();
      });
    }
  }

  function openPanel(tab = 'sankey') {
    if (tab === 'schema') tab = 'sankey';
    if (!['sankey', 'import'].includes(tab)) {
      tab = 'sankey';
    }
    state.activePanel = tab;
    els.panel.classList.add('active');
    setFabOpen(false);
    els.tabs.forEach((item) => item.classList.toggle('active', item.dataset.tab === tab));
    const sankeySection = $('#sankey-content');
    if (sankeySection) {
      sankeySection.classList.toggle('active', tab === 'sankey');
    }
    const importSection = $('#import-content');
    if (importSection) {
      importSection.classList.toggle('active', tab === 'import');
    }
    if (tab === 'sankey') renderSankeyPanel();
    if (tab === 'import') renderImportPanel();
  }

  function setFabOpen(open, restoreFocus = false) {
    if (!els.fabContainer || !els.fabMain) return;
    const actions = [els.fabSankey, els.fabImport].filter(Boolean);
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

  function truncateSankeyText(value, limit) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    if (measureSankeyText(text) <= limit) return text;
    const suffix = '...';
    const budget = Math.max(1, limit - measureSankeyText(suffix));
    let used = 0;
    let result = '';
    for (const char of text) {
      const next = sankeyGlyphUnits(char);
      if (used + next > budget) break;
      result += char;
      used += next;
    }
    return `${result.replace(/[._\-\s]+$/, '')}${suffix}`;
  }

  function measureSankeyText(text) {
    let total = 0;
    for (const char of text) {
      total += sankeyGlyphUnits(char);
    }
    return total;
  }

  function sankeyGlyphUnits(char) {
    const code = char.codePointAt(0) || 0;
    if (
      (code >= 0x2e80 && code <= 0x9fff) ||
      (code >= 0xac00 && code <= 0xd7af) ||
      (code >= 0xf900 && code <= 0xfaff) ||
      (code >= 0xff01 && code <= 0xff60) ||
      (code >= 0xffe0 && code <= 0xffe6)
    ) {
      return 2;
    }
    if (/[ilI1|.,'`]/.test(char)) return 0.75;
    if (/[_\-\s]/.test(char)) return 0.9;
    if (/[mwMW@#%&]/.test(char)) return 1.35;
    if (/[A-Z]/.test(char)) return 1.15;
    return 1.08;
  }

  function updateFilePickerLabel(nameId, hintId, dropzone, fileName, emptyLabel, readyHint, emptyHint) {
    const name = $(`#${nameId}`);
    const hint = $(`#${hintId}`);
    const action = $('#case-file-action');
    if (name) name.textContent = fileName || emptyLabel;
    if (hint) hint.textContent = fileName ? readyHint : emptyHint;
    if (action) action.textContent = fileName ? 'Change files' : 'Browse';
    if (dropzone) dropzone.classList.toggle('has-file', Boolean(fileName));
  }

  function formatCaseStats(stats) {
    const parts = [];
    if (stats.workbook_count != null) parts.push(`${stats.workbook_count} files`);
    if (stats.sheet_count != null) parts.push(`${stats.sheet_count} sheets`);
    if (stats.table_count != null) parts.push(`${stats.table_count} tables`);
    if (stats.field_count != null) parts.push(`${stats.field_count} fields`);
    if (stats.failed_compile_count) parts.push(`${stats.failed_compile_count} compile failures`);
    return parts.length ? parts.join(' · ') : 'not prepared yet';
  }

  function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function artifactPathRegex(flags = 'g') {
    return new RegExp(
      "(?:(?:[A-Za-z]:)?/[^\\s<>\"'`)\\]]*?/(?:workspaces/otology_skill/)?outputs/otology_skill|/?(?:workspaces/otology_skill/)?outputs/otology_skill)/[^\\s<>\"'`)\\]]+\\.(?:py|md|json|txt|csv|xlsx|xlsm|log)",
      flags,
    );
  }

  function decodeUriComponentSafe(value) {
    try {
      return decodeURIComponent(value);
    } catch (error) {
      return value;
    }
  }

  function decodeHtmlEntities(value) {
    const textarea = document.createElement('textarea');
    textarea.innerHTML = value == null ? '' : String(value);
    return textarea.value;
  }

  function normalizeArtifactPath(path) {
    let normalized = decodeUriComponentSafe(String(path || ''))
      .trim()
      .replace(/^[`"'(<\[]+/, '')
      .replace(/[.,;:`"')\]>]+$/, '')
      .replace(/\\/g, '/');
    if (normalized.startsWith('file://')) {
      normalized = normalized.slice(7);
    }
    const outputPrefix = 'outputs/otology_skill/';
    const workspacePrefix = 'workspaces/otology_skill/outputs/otology_skill/';
    if (normalized.startsWith(`/${outputPrefix}`)) {
      return outputPrefix + normalized.slice(outputPrefix.length + 1);
    }
    if (normalized.startsWith(outputPrefix)) {
      return normalized;
    }
    if (normalized.startsWith(`/${workspacePrefix}`)) {
      return outputPrefix + normalized.slice(workspacePrefix.length + 1);
    }
    if (normalized.startsWith(workspacePrefix)) {
      return outputPrefix + normalized.slice(workspacePrefix.length);
    }
    const workspaceIndex = normalized.indexOf(`/${workspacePrefix}`);
    if (workspaceIndex >= 0) {
      return outputPrefix + normalized.slice(workspaceIndex + workspacePrefix.length + 1);
    }
    const outputIndex = normalized.indexOf(`/${outputPrefix}`);
    if (outputIndex >= 0) {
      return outputPrefix + normalized.slice(outputIndex + outputPrefix.length + 1);
    }
    return normalized;
  }

  function displayArtifactPath(path) {
    return normalizeArtifactPath(path);
  }

  function artifactBasename(path) {
    const display = displayArtifactPath(path);
    return display.split('/').filter(Boolean).pop() || display;
  }

  function isHiddenUserFile(path) {
    return artifactBasename(path) === '__init__.py';
  }

  function sanitizeUserVisibleModelText(value) {
    return String(value || '')
      .replace(/^#{1,3}\s*(?:口径提示|冲突提示|容易混淆的指标|指标差异提醒)\s*\n[\s\S]*?(?=^#{1,3}\s+|\nPROCESS_TRACE_JSON\b|\s*$)/gim, '')
      .replace(/\[[^\]]*__init__\.py[^\]]*\]\([^)]*\)/g, '')
      .replace(artifactPathRegex('g'), (path) => (isHiddenUserFile(path) ? '' : path))
      .replace(/\b__init__\.py\b/g, '')
      .replace(/\r\n/g, '\n')
      .split('\n')
      .filter((line) => !/^[-*]\s*$/.test(line.trim()))
      .join('\n');
  }

  function isDownloadableArtifactPath(path) {
    return !isHiddenUserFile(path) && artifactPathRegex('').test(normalizeArtifactPath(path));
  }

  function artifactDownloadHref(path) {
    return `/api/files/download?path=${encodeURIComponent(normalizeArtifactPath(path))}`;
  }

  function extractArtifactPaths(value) {
    const found = [];
    const seen = new Set();
    const regex = artifactPathRegex('g');
    let match = regex.exec(String(value || ''));
    while (match) {
      const path = normalizeArtifactPath(match[0]);
      if (path && !isHiddenUserFile(path) && !seen.has(path)) {
        seen.add(path);
        found.push(path);
      }
      match = regex.exec(String(value || ''));
    }
    return found.slice(0, 12);
  }

  function renderDownloadLink(path, label = '', variant = 'inline') {
    const normalized = normalizeArtifactPath(path);
    if (isHiddenUserFile(normalized)) return '';
    const display = displayArtifactPath(normalized);
    const title = label || artifactBasename(normalized);
    return `
      <a class="artifact-download ${escapeHtml(variant)}" href="${artifactDownloadHref(normalized)}" download title="${escapeHtml(display)}">
        <span class="artifact-download-icon">↓</span>
        <span class="artifact-download-copy">
          <strong>${escapeHtml(title)}</strong>
          <small>${escapeHtml(display)}</small>
        </span>
      </a>
    `;
  }

  function renderArtifactDock(paths) {
    if (!paths.length) return '';
    return `
      <div class="artifact-download-dock">
        <div class="artifact-download-head">
          <span>Downloadable outputs</span>
          <small>${paths.length} file${paths.length === 1 ? '' : 's'}</small>
        </div>
        <div class="artifact-download-grid">
          ${paths.map((path) => renderDownloadLink(path, artifactBasename(path), 'card')).join('')}
        </div>
      </div>
    `;
  }

  function renderMarkdownLink(labelHtml, href) {
    const target = normalizeArtifactPath(decodeHtmlEntities(href));
    if (isHiddenUserFile(target)) {
      return '';
    }
    if (isDownloadableArtifactPath(target)) {
      return renderDownloadLink(target, decodeHtmlEntities(labelHtml), 'inline');
    }
    if (/^https?:\/\//i.test(target)) {
      return `<a class="markdown-link" href="${escapeHtml(target)}" target="_blank" rel="noreferrer">${labelHtml}</a>`;
    }
    return `${labelHtml} (${escapeHtml(target)})`;
  }

  function autoLinkArtifactPaths(html) {
    return String(html || '').replace(artifactPathRegex('g'), (path) => (
      isHiddenUserFile(path) ? '' : renderDownloadLink(path, artifactBasename(path), 'inline')
    ));
  }

  function renderCodeToken(codeHtml) {
    const raw = decodeHtmlEntities(codeHtml);
    if (isDownloadableArtifactPath(raw)) {
      return renderDownloadLink(raw, artifactBasename(raw), 'code-chip');
    }
    return `<code>${codeHtml}</code>`;
  }

  function isCodeBlockTitle(value) {
    const text = String(value || '').trim().replace(/:$/, '');
    return text.length > 2 && text.length <= 80 && /^[A-Z0-9][A-Z0-9_ .:/-]*$/.test(text) && /[A-Z_]/.test(text);
  }

  function codeFenceLanguage(fenceLine) {
    const info = String(fenceLine || '').replace(/^```+/, '').trim();
    const language = (info.split(/\s+/)[0] || '').replace(/[^\w.+-]/g, '');
    return language || 'code';
  }

  function renderMarkdownCodeBlock(code, fenceLine = '```', title = '') {
    const language = codeFenceLanguage(fenceLine);
    const cleanTitle = String(title || '').trim().replace(/:$/, '');
    if (/^PROCESS_TRACE_JSON$/i.test(cleanTitle)) {
      const traceCard = renderProcessTraceMarkdownCard(code);
      if (traceCard) return traceCard;
    }
    const lineCount = code ? String(code).split('\n').length : 0;
    const displayTitle = cleanTitle || language.toUpperCase();
    const meta = [
      cleanTitle && language !== 'code' ? language.toUpperCase() : '',
      lineCount ? `${lineCount} line${lineCount === 1 ? '' : 's'}` : '',
    ].filter(Boolean).join(' · ');
    return `
      <figure class="markdown-code-block">
        <figcaption class="markdown-code-header">
          <span class="markdown-code-title">${escapeHtml(displayTitle)}</span>
          ${meta ? `<span class="markdown-code-meta">${escapeHtml(meta)}</span>` : ''}
        </figcaption>
        <pre><code>${escapeHtml(code)}</code></pre>
      </figure>
    `;
  }

  function parseProcessTraceJson(code) {
    let raw = String(code || '').trim();
    raw = raw.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/i, '').trim();
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
    } catch (error) {
      return null;
    }
  }

  function renderTraceStat(value, label, tone = '') {
    return `
      <div class="process-trace-stat ${escapeAttr(tone)}">
        <strong>${escapeHtml(value)}</strong>
        <span>${escapeHtml(label)}</span>
      </div>
    `;
  }

  function renderTraceStep(step) {
    const status = String(step.status || '').toUpperCase();
    const ok = status === 'PASS' || status === 'COMPLETE' || status === 'DONE';
    const rawName = step.action || step.tool || step.step || 'workflow step';
    const name = readableTraceStepName(rawName);
    const detail = step.evidence || step.target || step.description || step.tool || '';
    return `
      <li class="${ok ? 'ok' : ''}">
        <span>${ok ? '✓' : '•'}</span>
        <div>
          <strong>${escapeHtml(name)}</strong>
          ${detail ? `<small>${escapeHtml(truncate(detail, 110))}</small>` : ''}
        </div>
      </li>
    `;
  }

  function readableTraceStepName(value) {
    const key = String(value || '').trim().toLowerCase();
    const labels = {
      parse_ontology_files: '解析原始 Python 类',
      parse_prepared_classes: '解析原始 Python 类',
      inspect_excel_schema: '读取 Excel 字段说明',
      generate_python_models_from_excel: '生成基础 Python 类',
      design_ontology: '设计业务本体',
      write_file: '写入业务本体文件',
      write_business_ontology: '写入业务本体文件',
      validate_python_artifacts: '验证 Python 文件',
      validate_artifacts: '验证 Python 文件',
      render_merged_ontology: '生成合并本体文件',
      merge_ontology_classes: '合并本体类',
    };
    if (labels[key]) return labels[key];
    if (/^\d+$/.test(key)) return `步骤 ${key}`;
    return humanizeIdentifier(value);
  }

  function renderTraceMapping(mapping) {
    const source = mapping.source_sheet || mapping.source_class || mapping.source || 'Source schema';
    const target = mapping.target_class || mapping.target || mapping.target_entity || 'Business ontology';
    const decision = mapping.decision || mapping.reason || '';
    return `
      <li>
        <strong>${escapeHtml(source)}</strong>
        <span>→</span>
        <strong>${escapeHtml(target)}</strong>
        ${decision ? `<small>${escapeHtml(truncate(decision, 86))}</small>` : ''}
      </li>
    `;
  }

  function renderProcessTraceMarkdownCard(code) {
    const trace = parseProcessTraceJson(code);
    if (!trace) return '';
    const steps = Array.isArray(trace.workflow_steps) ? trace.workflow_steps : [];
    const mappings = Array.isArray(trace.source_to_target) ? trace.source_to_target : [];
    const artifacts = Array.isArray(trace.artifact_paths) ? trace.artifact_paths : [];
    const validation = trace.validation && typeof trace.validation === 'object' ? trace.validation : {};
    const validationStatus = validation.status || validation.py_compile || (Object.keys(validation).length ? 'PASS' : 'Recorded');
    const visibleMappings = mappings.slice(0, 5);
    return `
      <section class="process-trace-card" aria-label="Process trace summary">
        <div class="process-trace-head">
          <div>
            <span class="process-trace-kicker">Process Trace</span>
            <h4>流程记录已整理</h4>
            <p>原始 JSON 已隐藏，这里只展示流程、映射和验证结果。</p>
          </div>
          <strong class="process-trace-status">${escapeHtml(validationStatus)}</strong>
        </div>
        <div class="process-trace-stats">
          ${renderTraceStat(steps.length, '执行步骤')}
          ${renderTraceStat(mappings.length, '原始表映射')}
          ${renderTraceStat(artifacts.length, '生成文件')}
          ${renderTraceStat(validationStatus, '代码验证')}
        </div>
        ${steps.length ? `
          <div class="process-trace-section">
            <h5>执行步骤</h5>
            <ol class="process-trace-steps">${steps.slice(0, 5).map(renderTraceStep).join('')}</ol>
          </div>
        ` : ''}
        ${visibleMappings.length ? `
          <div class="process-trace-section">
            <h5>关键映射</h5>
            <ul class="process-trace-mappings">
              ${visibleMappings.map(renderTraceMapping).join('')}
              ${mappings.length > visibleMappings.length ? `<li class="more">+${mappings.length - visibleMappings.length} 条映射已用于 Sankey 图</li>` : ''}
            </ul>
          </div>
        ` : ''}
      </section>
    `;
  }

  function isMarkdownHorizontalRule(value) {
    return /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/.test(String(value || ''));
  }

  function renderMarkdownDivider() {
    return '<div class="markdown-divider" role="separator" aria-hidden="true"><span></span></div>';
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
      if (isMarkdownHorizontalRule(line)) {
        blocks.push(renderMarkdownDivider());
        index += 1;
        continue;
      }
      if (isCodeBlockTitle(trimmed) && index + 1 < lines.length && lines[index + 1].trim().startsWith('```')) {
        const fenceLine = lines[index + 1].trim();
        const codeLines = [];
        index += 2;
        while (index < lines.length && !lines[index].trim().startsWith('```')) {
          codeLines.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        blocks.push(renderMarkdownCodeBlock(codeLines.join('\n'), fenceLine, trimmed));
        continue;
      }
      const boxedAnswer = parseBoxedAnswer(trimmed);
      if (boxedAnswer) {
        blocks.push(renderBoxedAnswer(boxedAnswer));
        index += 1;
        continue;
      }
      if (trimmed.startsWith('```')) {
        const fenceLine = trimmed;
        const codeLines = [];
        index += 1;
        while (index < lines.length && !lines[index].trim().startsWith('```')) {
          codeLines.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        blocks.push(renderMarkdownCodeBlock(codeLines.join('\n'), fenceLine));
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
        !isMarkdownHorizontalRule(lines[index]) &&
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
    const boxedTokens = [];
    const codeTokens = [];
    const linkTokens = [];
    html = html.replace(/\\{1,2}boxed\s*\{([^{}]+)\}/g, (_, answer) => {
      const token = `@@BOXED_${boxedTokens.length}@@`;
      boxedTokens.push(renderBoxedAnswer(normalizeBoxedAnswer(answer)));
      return token;
    });
    html = html.replace(/`([^`]+)`/g, (_, code) => {
      const token = `@@CODE_${codeTokens.length}@@`;
      codeTokens.push(code);
      return token;
    });
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, href) => {
      const token = `@@LINK_${linkTokens.length}@@`;
      linkTokens.push(renderMarkdownLink(label, href));
      return token;
    });
    html = autoLinkArtifactPaths(html);
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    codeTokens.forEach((code, index) => {
      html = html.replace(`@@CODE_${index}@@`, renderCodeToken(code));
    });
    linkTokens.forEach((link, index) => {
      html = html.replace(`@@LINK_${index}@@`, link);
    });
    boxedTokens.forEach((boxed, index) => {
      html = html.replace(`@@BOXED_${index}@@`, boxed);
    });
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
    const headerText = header.join('|').toLowerCase();
    const tableClass = /文件|file|说明|description/.test(headerText) ? ' markdown-output-file-table' : '';
    return `<div class="markdown-table-wrap${tableClass}"><table class="markdown-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

})();
