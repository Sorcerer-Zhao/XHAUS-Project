const state = {
  started: false,
  session: null,
  messages: [],
  currentConversationId: "",
  conversations: [],
  conversationTitle: "管家对话",
  currentTaskId: "",
  lastSeq: 0,
  assistantIndex: -1,
  polling: null,
  runtimeTimer: null,
  statusTimer: null,
  satelliteTimer: null,
  satelliteLastSuccess: "",
  personaChoices: [],
  personaChoicesSignature: "",
  personaRefreshInFlight: false,
  activeAgent: {
    id: "main",
    label: "默认管家",
  },
  currentPrompt: {
    type: "idle",
    allow_empty: true,
  },
  editor: null,
};

const SESSION_KEY = "xhaus_web_session";
const WS_HISTORY_KEY = "xhaus_ws_history";
const CONVERSATIONS_KEY = "xhaus_web_conversations";
const CURRENT_CONVERSATION_KEY = "xhaus_web_current_conversation";
const INITIAL_MESSAGE =
  "XHAUS 已接入前端控制台。我可以帮你安排出行、餐饮、娱乐和日程，也可以继续沉淀你的偏好与自我认知。";
const $ = (selector) => document.querySelector(selector);

function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.add("is-show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("is-show"), 3000);
}

function readableError(err, fallback = "请求失败") {
  if (!err) {
    return fallback;
  }
  if (typeof err === "string") {
    return err;
  }
  if (err.message) {
    return err.message;
  }
  if (err.data && err.data.message) {
    return err.data.message;
  }
  return fallback;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: Object.assign({ "Content-Type": "application/json" }, options.headers || {}),
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.code !== 0) {
    throw data;
  }
  return data.data;
}

function setStatus(id, label, kind) {
  const el = $(id);
  if (!el) {
    return;
  }
  el.classList.toggle("is-ok", kind === "ok");
  el.classList.toggle("is-bad", kind === "bad");
  el.classList.toggle("is-warn", kind === "warn");
  el.querySelector("span:last-child").textContent = label;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function initialMessages() {
  return [{ role: "assistant", text: INITIAL_MESSAGE }];
}

function newConversation(title = "管家对话") {
  const now = Date.now();
  return {
    id: `conv_${crypto.randomUUID ? crypto.randomUUID() : `${now}_${Math.random().toString(16).slice(2)}`}`,
    title,
    customTitle: false,
    messages: initialMessages(),
    session: null,
    createdAt: now,
    updatedAt: now,
  };
}

function loadConversationStore() {
  try {
    const raw = JSON.parse(localStorage.getItem(CONVERSATIONS_KEY) || "[]");
    return Array.isArray(raw) ? raw : [];
  } catch (err) {
    return [];
  }
}

function saveConversationStore() {
  localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(state.conversations.slice(0, 30)));
  if (state.currentConversationId) {
    localStorage.setItem(CURRENT_CONVERSATION_KEY, state.currentConversationId);
  }
}

function currentConversation() {
  return state.conversations.find((item) => item.id === state.currentConversationId) || null;
}

function hydrateConversation(conversation) {
  state.currentConversationId = conversation.id;
  state.conversationTitle = conversation.title || "管家对话";
  state.messages = Array.isArray(conversation.messages) && conversation.messages.length
    ? conversation.messages
    : initialMessages();
  state.session = conversation.session || null;
  localStorage.setItem(CURRENT_CONVERSATION_KEY, conversation.id);
  localStorage.setItem(SESSION_KEY, JSON.stringify(state.session || null));
  updateConversationTitle();
  renderMessages();
  renderConversationHistory();
}

function initConversations() {
  state.conversations = loadConversationStore();
  if (!state.conversations.length) {
    state.conversations = [newConversation()];
  }
  const currentId = localStorage.getItem(CURRENT_CONVERSATION_KEY);
  const selected = state.conversations.find((item) => item.id === currentId) || state.conversations[0];
  hydrateConversation(selected);
  saveConversationStore();
}

function persistConversation() {
  const conversation = currentConversation();
  if (!conversation) {
    return;
  }
  conversation.messages = state.messages;
  conversation.session = state.session;
  conversation.title = state.conversationTitle || conversation.title || "管家对话";
  conversation.updatedAt = Date.now();
  state.conversations = [
    conversation,
    ...state.conversations.filter((item) => item.id !== conversation.id),
  ];
  saveConversationStore();
  renderConversationHistory();
}

function updateConversationTitle() {
  const el = $("#conversationTitle");
  if (el) {
    el.textContent = state.conversationTitle || "管家对话";
  }
}

function maybeAutoTitle(text) {
  const conversation = currentConversation();
  if (!conversation || conversation.customTitle) {
    return;
  }
  const title = String(text || "").trim().slice(0, 24);
  if (!title) {
    return;
  }
  conversation.title = title;
  state.conversationTitle = title;
  updateConversationTitle();
}

function renderConversationHistory() {
  const root = $("#conversationHistory");
  if (!root) {
    return;
  }
  const list = state.conversations.slice().sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
  root.innerHTML = list.length
    ? list
        .map((item) => {
          const active = item.id === state.currentConversationId ? " · 当前" : "";
          const time = item.updatedAt ? new Date(item.updatedAt).toLocaleString() : "";
          return `<div class="history-item">
            <div class="history-main" data-id="${escapeHtml(item.id)}">
              <span class="history-title">${escapeHtml(item.title || "管家对话")}${active}</span>
              <span class="history-meta">${escapeHtml(time)} · ${(item.messages || []).length} 条消息</span>
            </div>
          </div>`;
        })
        .join("")
    : '<div class="doc-item is-empty">暂无历史对话</div>';
  root.querySelectorAll(".history-main").forEach((item) => {
    item.addEventListener("click", () => switchConversation(item.dataset.id));
  });
}

function renderMessages() {
  const root = $("#messages");
  if (!root) {
    return;
  }
  root.innerHTML = state.messages
    .map((message) => {
      const userClass = message.role === "user" ? " is-user" : "";
      const markdownClass = message.role === "assistant" ? " markdown" : "";
      const content =
        message.role === "assistant"
          ? renderMarkdown(message.text || "")
          : escapeHtml(message.text || "");
      return `<div class="message${userClass}"><div class="bubble${markdownClass}">${content}</div></div>`;
    })
    .join("");
  root.scrollTop = root.scrollHeight;
}

function renderInlineMarkdown(value) {
  return String(value || "")
    .split(/(`[^`\n]+?`)/g)
    .map((part) => {
      if (/^`[^`\n]+?`$/.test(part)) {
        return `<code>${escapeHtml(part.slice(1, -1))}</code>`;
      }
      return escapeHtml(part)
        .replace(/\*\*([\s\S]+?)\*\*/g, "<strong>$1</strong>")
        .replace(/(^|[^\*])\*([^*\n]+?)\*(?!\*)/g, '$1<em>$2</em>');
    })
    .join("");
}

function tableCells(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isTableSeparator(line) {
  const cells = tableCells(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, "")));
}

function isTableStart(lines, index) {
  return (
    index + 1 < lines.length &&
    lines[index].includes("|") &&
    lines[index + 1].includes("|") &&
    isTableSeparator(lines[index + 1])
  );
}

function renderMarkdown(text) {
  const lines = String(text || "").split(/\r?\n/);
  const html = [];
  let index = 0;
  let inList = false;

  const closeList = () => {
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
  };

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      closeList();
      html.push("<br>");
      index += 1;
      continue;
    }

    const codeFence = trimmed.match(/^```(\S*)\s*$/);
    if (codeFence) {
      closeList();
      const language = codeFence[1] || "";
      index += 1;
      const codeLines = [];
      while (index < lines.length && !/^```\s*$/.test(lines[index].trim())) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      html.push(
        `<div class="md-code-wrap">${language ? `<div class="md-code-lang">${escapeHtml(language)}</div>` : ""}<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre></div>`,
      );
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      closeList();
      html.push("<hr>");
      index += 1;
      continue;
    }

    if (isTableStart(lines, index)) {
      closeList();
      const headers = tableCells(lines[index]);
      index += 2;
      const rows = [];
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        rows.push(tableCells(lines[index]));
        index += 1;
      }
      html.push(
        `<div class="md-table-wrap"><table><thead><tr>${headers
          .map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`)
          .join("")}</tr></thead><tbody>${rows
          .map(
            (row) =>
              `<tr>${headers
                .map((_, cellIndex) => `<td>${renderInlineMarkdown(row[cellIndex] || "")}</td>`)
                .join("")}</tr>`,
          )
          .join("")}</tbody></table></div>`,
      );
      continue;
    }

    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = heading[1].length + 2;
      html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }

    const listItem = trimmed.match(/^[-*]\s+(.+)$/);
    if (listItem) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${renderInlineMarkdown(listItem[1])}</li>`);
      index += 1;
      continue;
    }

    closeList();
    html.push(`<p>${renderInlineMarkdown(trimmed)}</p>`);
    index += 1;
  }

  closeList();
  return html.join("");
}

function sourceText(selector) {
  const el = $(selector);
  if (!el) {
    return "暂无内容";
  }
  const text = (el.innerText || el.textContent || "").trim();
  return text || "暂无内容";
}

function openDetail(title, sourceSelector) {
  const overlay = $("#detailOverlay");
  $("#detailTitle").textContent = title || "详情";
  $("#detailContent").textContent = sourceText(sourceSelector);
  overlay.hidden = false;
  document.body.classList.add("detail-open");
  $("#closeDetailBtn").focus();
}

function closeDetail() {
  const overlay = $("#detailOverlay");
  if (!overlay || overlay.hidden) {
    return;
  }
  overlay.hidden = true;
  document.body.classList.remove("detail-open");
}

function updateActiveAgent(agent, pendingAgent) {
  if (agent && agent.id) {
    state.activeAgent = {
      id: agent.id,
      label: agent.label || agent.name || agent.id,
    };
  }
  const el = $("#activeAgentName");
  if (el) {
    if (pendingAgent && pendingAgent.id) {
      el.textContent = `正在创建 ${pendingAgent.label || pendingAgent.id}`;
    } else {
      el.textContent = state.activeAgent.label || state.activeAgent.id || "默认管家";
    }
  }
}

function loadWsHistory() {
  try {
    const raw = JSON.parse(localStorage.getItem(WS_HISTORY_KEY) || "[]");
    if (!Array.isArray(raw)) {
      return [];
    }
    return Array.from(new Set(raw.map((item) => String(item || "").trim()).filter(Boolean))).slice(0, 8);
  } catch (err) {
    return [];
  }
}

function saveWsHistory(url) {
  const value = String(url || "").trim();
  if (!/^wss?:\/\//i.test(value)) {
    return;
  }
  const next = [value, ...loadWsHistory().filter((item) => item !== value)].slice(0, 8);
  localStorage.setItem(WS_HISTORY_KEY, JSON.stringify(next));
}

function renderWsHistory() {
  const root = $("#wsHistory");
  if (!root) {
    return;
  }
  const isWsPrompt = state.currentPrompt && state.currentPrompt.type === "websocket";
  const list = loadWsHistory();
  root.hidden = !isWsPrompt || list.length === 0;
  root.innerHTML = root.hidden
    ? ""
    : list
        .map((url) => `<button class="ws-choice" type="button" title="${escapeHtml(url)}">${escapeHtml(url)}</button>`)
        .join("");
  root.querySelectorAll(".ws-choice").forEach((button) => {
    button.addEventListener("click", () => {
      $("#wizardInput").value = button.textContent || "";
      $("#wizardInput").focus();
    });
  });
}

async function ensureSession(forceNew = false) {
  if (forceNew) {
    state.session = null;
    const conversation = currentConversation();
    if (conversation) {
      conversation.session = null;
    }
  }
  const conversation = currentConversation();
  const cached = conversation && conversation.session
    ? conversation.session
    : JSON.parse(localStorage.getItem(SESSION_KEY) || "null");
  if (cached && cached.expiresAt && cached.expiresAt > Date.now()) {
    state.session = cached;
    return cached;
  }

  const data = await api("/api/xhaus/web-session", { method: "POST", body: "{}" });
  const session = {
    user_id: data.user_id,
    session_id: data.session_id,
    token: data.token,
    expiresAt: Date.now() + (data.expires_in || 7200) * 1000,
  };
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  state.session = session;
  if (conversation) {
    conversation.session = session;
    persistConversation();
  }
  return session;
}

function isSessionExpiredError(err) {
  return err && ["session_not_found", "invalid_token", "token_mismatch"].includes(err.message);
}

function startNewConversation() {
  if (state.currentTaskId) {
    toast("当前回复还没结束，稍后再新建对话");
    return;
  }
  persistConversation();
  const conversation = newConversation();
  state.conversations.unshift(conversation);
  hydrateConversation(conversation);
  saveConversationStore();
  $("#messageInput").focus();
}

function switchConversation(id) {
  if (state.currentTaskId) {
    toast("当前回复还没结束，稍后再切换对话");
    return;
  }
  const conversation = state.conversations.find((item) => item.id === id);
  if (!conversation) {
    return;
  }
  persistConversation();
  hydrateConversation(conversation);
  $("#conversationHistory").hidden = true;
}

function renameConversation() {
  const conversation = currentConversation();
  if (!conversation) {
    return;
  }
  const title = window.prompt("输入新的对话名称", state.conversationTitle || conversation.title || "管家对话");
  if (title === null) {
    return;
  }
  const next = title.trim();
  if (!next) {
    toast("对话名称不能为空");
    return;
  }
  conversation.title = next;
  conversation.customTitle = true;
  state.conversationTitle = next;
  updateConversationTitle();
  persistConversation();
}

function toggleConversationHistory() {
  const panel = $("#conversationHistory");
  panel.hidden = !panel.hidden;
  if (!panel.hidden) {
    renderConversationHistory();
  }
}

async function activateXhaus() {
  try {
    const runtime = await api("/api/xhaus/activate", { method: "POST", body: "{}" });
    updateRuntime(runtime);
    setStatus("#xhausStatus", "XHAUS 已激活", "ok");
  } catch (err) {
    setStatus("#xhausStatus", "XHAUS 激活失败", "bad");
    toast(readableError(err, "XHAUS 激活失败"));
  }
}

async function refreshRuntime() {
  try {
    const runtime = await api("/api/xhaus/runtime");
    updateRuntime(runtime);
    refreshPersonaChoicesIfChanged();
  } catch (err) {
    setStatus("#xhausStatus", "XHAUS 状态不可用", "bad");
  }
}

async function stopXhaus() {
  try {
    const runtime = await api("/api/xhaus/stop", { method: "POST", body: "{}" });
    updateRuntime(runtime);
    toast("XHAUS 正在停止");
  } catch (err) {
    toast(readableError(err, "XHAUS 停止失败"));
  }
}

function updateRuntime(runtime) {
  const running = runtime.status === "running";
  const activated = runtime.status === "activated";
  $("#runtimePid").textContent = running && runtime.pid ? `PID ${runtime.pid}` : activated ? "DONE" : "PID --";
  const label = running
    ? "XHAUS main.py 运行中"
    : activated
      ? "XHAUS 已激活"
      : `XHAUS ${runtime.status}`;
  setStatus("#xhausStatus", label, running || activated ? "ok" : "bad");
  const prompt = runtime.prompt || {};
  state.currentPrompt = prompt;
  $("#xhausPrompt").textContent = prompt.label || "等待 XHAUS 输出下一步";
  $("#wizardInput").placeholder = prompt.placeholder || "输入编号、y/n、Agent ID 等";
  renderWsHistory();
  updateActiveAgent(runtime.active_agent, runtime.pending_agent);
  const lines = (runtime.logs || []).map((entry) => `[${entry.source}] ${entry.line}`);
  $("#runtimeLog").textContent = lines.length ? lines.join("\n") : "main.py 已启动，等待控制台输出...";
}

async function checkOpenClaw(showToast = false) {
  try {
    const data = await api("/api/openclaw/status");
    const transport = data.transport ? ` · ${data.transport}` : "";
    if (data.ok && data.writable === false) {
      setStatus("#openclawStatus", "OpenClaw 待设备授权", "warn");
      if (showToast) {
        toast(data.detail || "Gateway 在线，但当前设备缺少对话权限。");
      }
      return data;
    }
    setStatus("#openclawStatus", data.ok ? `OpenClaw 在线${transport}` : "OpenClaw 未连接", data.ok ? "ok" : "bad");
    if (showToast) {
      toast(data.detail || (data.ok ? "OpenClaw 已连接" : "OpenClaw 未连接"));
    }
    return data;
  } catch (err) {
    setStatus("#openclawStatus", "OpenClaw 未连接", "bad");
    if (showToast) {
      toast(readableError(err, "OpenClaw 未连接"));
    }
    return { ok: false };
  }
}

async function fetchPresetChoices() {
  try {
    const data = await api("/api/xhaus/presets");
    state.personaChoices = data.choices || [];
    state.personaChoicesSignature = personaChoicesSignature(state.personaChoices);
    renderPersonaChoices();
  } catch (err) {
    state.personaChoices = [
      { index: 1, label: "默认管家", value: "default_butler" },
      { index: 2, label: "优雅女仆", value: "elegant_maid" },
    ];
    state.personaChoicesSignature = personaChoicesSignature(state.personaChoices);
    renderPersonaChoices();
  }
}

function personaChoicesSignature(choices) {
  return (choices || [])
    .map((choice) => `${choice.index}:${choice.kind || ""}:${choice.value || ""}:${choice.label || ""}`)
    .join("|");
}

async function refreshPersonaChoicesIfChanged() {
  if (state.personaRefreshInFlight) {
    return;
  }
  state.personaRefreshInFlight = true;
  try {
    const data = await api("/api/xhaus/presets");
    const choices = data.choices || [];
    const signature = personaChoicesSignature(choices);
    if (signature !== state.personaChoicesSignature) {
      state.personaChoices = choices;
      state.personaChoicesSignature = signature;
      renderPersonaChoices();
    }
  } catch (err) {
    // Keep the current list if the runtime is still booting.
  } finally {
    state.personaRefreshInFlight = false;
  }
}

function renderPersonaChoices() {
  const root = $("#personaChoices");
  if (!root) {
    return;
  }
  root.innerHTML = state.personaChoices
    .map((choice) => {
      const profileId = String(choice.value || "").replace(/^custom:/, "");
      const canDelete = choice.kind === "custom_profile";
      return [
        `<span class="persona-choice-wrap${canDelete ? " deletable" : ""}">`,
        `<button class="persona-choice" type="button" data-index="${choice.index}">${choice.index}. ${escapeHtml(choice.label)}</button>`,
        canDelete
          ? `<button class="persona-delete" type="button" data-id="${escapeHtml(profileId)}" data-label="${escapeHtml(choice.label)}" aria-label="删除 ${escapeHtml(choice.label)}">删</button>`
          : "",
        `</span>`,
      ].join("");
    })
    .join("");
  root.querySelectorAll(".persona-choice").forEach((button) => {
    button.addEventListener("click", () => sendXhausInput(button.dataset.index, "人设编号已发送"));
  });
  root.querySelectorAll(".persona-delete").forEach((button) => {
    button.addEventListener("click", () => deleteCustomPersona(button.dataset.id, button.dataset.label));
  });
}

async function deleteCustomPersona(profileId, label) {
  const id = String(profileId || "").trim();
  if (!id) {
    toast("没有找到要删除的人设 ID");
    return;
  }
  const name = label || id;
  if (!window.confirm(`确定删除「${name}」吗？这会删除它的自定义人设文件和对应 OpenClaw workspace，不会影响系统预设。`)) {
    return;
  }

  try {
    const result = await api(`/api/xhaus/custom-profiles/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    state.personaChoices = result.choices || [];
    renderPersonaChoices();
    if (result.runtime) {
      updateRuntime(result.runtime);
    }
    toast("自定义人设已删除");
  } catch (err) {
    toast(readableError(err, "删除人设失败"));
  }
}

async function sendMessage(text) {
  if (!text || state.currentTaskId) {
    return;
  }

  const session = await ensureSession();
  state.messages.push({ role: "user", text });
  state.messages.push({ role: "assistant", text: "" });
  state.assistantIndex = state.messages.length - 1;
  state.lastSeq = 0;
  maybeAutoTitle(text);
  renderMessages();
  persistConversation();

  const startTask = async (session) =>
    api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        user_id: session.user_id,
        session_id: session.session_id,
        token: session.token,
        message: text,
        agent: state.activeAgent.id || "main",
        use_active_agent: true,
        client: "xhaus_web",
      }),
    });

  try {
    let data = null;
    try {
      data = await startTask(session);
    } catch (err) {
      if (!isSessionExpiredError(err)) {
        throw err;
      }
      const freshSession = await ensureSession(true);
      data = await startTask(freshSession);
    }
    state.currentTaskId = data.task_id;
    pollTask();
  } catch (err) {
    failAssistant(readableError(err, "OpenClaw 请求失败"));
  }
}

async function pollTask() {
  if (!state.currentTaskId || !state.session) {
    return;
  }

  try {
    const data = await api(`/api/chat/${state.currentTaskId}?since=${state.lastSeq}`, {
      headers: {
        Authorization: `Bearer ${state.session.token}`,
        "x-user-id": state.session.user_id,
        "x-session-id": state.session.session_id,
      },
    });
    for (const delta of data.deltas || []) {
      state.messages[state.assistantIndex].text += delta.content || "";
    }
    state.lastSeq = data.seq || state.lastSeq;
    renderMessages();
    persistConversation();

    if (data.status === "done") {
      state.currentTaskId = "";
      state.assistantIndex = -1;
      persistConversation();
      checkOpenClaw();
      return;
    }
    if (data.status === "error" || data.status === "cancelled") {
      failAssistant(data.error || "任务中断");
      return;
    }
    state.polling = setTimeout(pollTask, 250);
  } catch (err) {
    if (isSessionExpiredError(err)) {
      await ensureSession(true).catch(() => null);
    }
    failAssistant(readableError(err, "轮询失败"));
  }
}

function failAssistant(message) {
  if (state.assistantIndex >= 0) {
    state.messages[state.assistantIndex].text =
      state.messages[state.assistantIndex].text || message;
  }
  state.currentTaskId = "";
  state.assistantIndex = -1;
  renderMessages();
  persistConversation();
  toast(message);
}

async function installSkill() {
  const sourcePath = $("#skillPath").value.trim();
  if (!sourcePath) {
    toast("请输入本地 Skill 目录");
    return;
  }

  $("#skillResult").textContent = "正在执行 install_skill.py...";
  try {
    const result = await api("/api/xhaus/skills/install", {
      method: "POST",
      body: JSON.stringify({
        source_path: sourcePath,
        force: $("#forceSkill").checked,
      }),
    });
    $("#skillResult").textContent = (result.stdout || "Skill 已安装").trim();
    toast("Skill 已添加");
    loadSkillList();
  } catch (err) {
    const detail = err.data && (err.data.stderr || err.data.stdout);
    $("#skillResult").textContent = detail || readableError(err, "安装失败");
    toast("Skill 安装失败");
  }
}

function renderManagedList(root, items, type) {
  if (!root) {
    return;
  }
  root.innerHTML = items.length
    ? items
        .map((item) => {
          const name = item.name || "";
          const meta = [
            item.updated_at ? new Date(item.updated_at).toLocaleString() : "",
            item.size ? `${item.size} bytes` : "",
          ]
            .filter(Boolean)
            .join(" · ");
          return `<div class="managed-item">
            <div class="managed-main" data-type="${type}" data-name="${escapeHtml(name)}">
              <span class="managed-title">${escapeHtml(name)}</span>
              <span class="managed-meta">${escapeHtml(meta || item.path || "")}</span>
            </div>
            <div class="item-actions">
              <button class="small-button subtle managed-edit" type="button" data-type="${type}" data-name="${escapeHtml(name)}">编辑</button>
              <button class="small-button danger managed-delete" type="button" data-type="${type}" data-name="${escapeHtml(name)}">删除</button>
            </div>
          </div>`;
        })
        .join("")
    : '<div class="doc-item is-empty">暂无内容</div>';
  root.querySelectorAll(".managed-main,.managed-edit").forEach((el) => {
    el.addEventListener("click", () => openManagedEditor(el.dataset.type, el.dataset.name));
  });
  root.querySelectorAll(".managed-delete").forEach((el) => {
    el.addEventListener("click", () => deleteManagedItem(el.dataset.type, el.dataset.name));
  });
}

async function loadSkillList() {
  const root = $("#skillList");
  if (!root) {
    return;
  }
  try {
    const data = await api("/api/xhaus/skills");
    renderManagedList(root, data.skills || [], "skill");
  } catch (err) {
    root.innerHTML = '<div class="doc-item is-empty">Skill 列表不可用</div>';
  }
}

async function sendXhausInput(value, successMessage = "已发送到 XHAUS", options = {}) {
  const text = String(value || "").trim();
  const sendEmpty = options.sendEmpty === true;
  if (!text && !sendEmpty) {
    toast("请输入要发送给 XHAUS 的内容");
    return;
  }

  try {
    const runtime = await api("/api/xhaus/input", {
      method: "POST",
      body: JSON.stringify({ value: text, send_empty: sendEmpty }),
    });
    if (state.currentPrompt && state.currentPrompt.type === "websocket" && text) {
      saveWsHistory(text);
      renderWsHistory();
    }
    updateRuntime(runtime);
    setTimeout(refreshPersonaChoicesIfChanged, 900);
    setTimeout(refreshPersonaChoicesIfChanged, 2500);
    toast(successMessage);
  } catch (err) {
    const runtime = err && err.data;
    if (runtime && runtime.logs) {
      updateRuntime(runtime);
    }
    toast(readableError(err, "XHAUS 输入发送失败"));
  }
}

function sendWizardInput() {
  const input = $("#wizardInput");
  const value = input.value.trim();
  input.value = "";
  sendXhausInput(value);
}

function sendEmptyInput() {
  $("#wizardInput").value = "";
  sendXhausInput("", "已发送回车", { sendEmpty: true });
}

async function saveCognition() {
  const title = $("#cogTitle").value.trim();
  const content = $("#cogContent").value.trim();
  if (!content) {
    toast("请输入自我认知内容");
    return;
  }

  try {
    await api("/api/xhaus/self-cognition", {
      method: "POST",
      body: JSON.stringify({ title, content }),
    });
    $("#cogContent").value = "";
    toast("自我认知文档已保存");
    loadCognitionDocs();
  } catch (err) {
    toast(readableError(err, "保存失败"));
  }
}

async function loadCognitionDocs() {
  try {
    const data = await api("/api/xhaus/self-cognition");
    const docs = data.documents || [];
    renderManagedList($("#cogList"), docs, "memory");
  } catch (err) {
    $("#cogList").innerHTML = '<div class="doc-item is-empty">文档列表不可用</div>';
  }
}

async function openManagedEditor(type, name) {
  if (!type || !name) {
    return;
  }
  const isSkill = type === "skill";
  const url = isSkill
    ? `/api/xhaus/skills/${encodeURIComponent(name)}`
    : `/api/xhaus/self-cognition/${encodeURIComponent(name)}`;
  try {
    const data = await api(url);
    state.editor = { type, name };
    $("#editorKind").textContent = isSkill ? "SKILL" : "MEMORY";
    $("#editorTitle").textContent = name;
    $("#editorContent").value = data.content || "";
    $("#editorOverlay").hidden = false;
    document.body.classList.add("detail-open");
    $("#editorContent").focus();
  } catch (err) {
    toast(readableError(err, "打开失败"));
  }
}

function closeEditor() {
  $("#editorOverlay").hidden = true;
  document.body.classList.remove("detail-open");
  state.editor = null;
}

async function saveManagedEditor() {
  if (!state.editor) {
    return;
  }
  const { type, name } = state.editor;
  const isSkill = type === "skill";
  const url = isSkill
    ? `/api/xhaus/skills/${encodeURIComponent(name)}`
    : `/api/xhaus/self-cognition/${encodeURIComponent(name)}`;
  const content = $("#editorContent").value;
  try {
    await api(url, {
      method: "PUT",
      body: JSON.stringify({ content }),
    });
    toast("已保存");
    closeEditor();
    if (isSkill) {
      loadSkillList();
    } else {
      loadCognitionDocs();
    }
  } catch (err) {
    toast(readableError(err, "保存失败"));
  }
}

async function deleteManagedItem(type, name) {
  if (!type || !name) {
    return;
  }
  const isSkill = type === "skill";
  const label = isSkill ? "Skill" : "自我认知文档";
  if (!window.confirm(`确定删除 ${label}「${name}」吗？`)) {
    return;
  }
  const url = isSkill
    ? `/api/xhaus/skills/${encodeURIComponent(name)}`
    : `/api/xhaus/self-cognition/${encodeURIComponent(name)}`;
  try {
    await api(url, { method: "DELETE" });
    toast("已删除");
    if (state.editor && state.editor.type === type && state.editor.name === name) {
      closeEditor();
    }
    if (isSkill) {
      loadSkillList();
    } else {
      loadCognitionDocs();
    }
  } catch (err) {
    toast(readableError(err, "删除失败"));
  }
}

function deleteManagedFromEditor() {
  if (!state.editor) {
    return;
  }
  deleteManagedItem(state.editor.type, state.editor.name);
}

function formatSatelliteStatus(data) {
  if (!data) {
    return "状态不可用";
  }
  const turns = typeof data.recent_turns === "number" ? `近两周历史 ${data.recent_turns} 条` : "近两周历史统计中";
  const status = data.running ? "运行中" : data.last_message || data.status || "待运行";
  const report = data.report_path ? `报告：${data.report_path}` : "";
  return [status, turns, report].filter(Boolean).join(" · ");
}

function isSatelliteFailure(data) {
  return !!data && (
    data.status === "error" ||
    data.status === "install_failed" ||
    (typeof data.last_code === "number" && data.last_code !== 0)
  );
}

async function loadSatelliteStatus(showNotice = false) {
  const el = $("#satelliteStatus");
  if (!el) {
    return;
  }
  try {
    const data = await api("/api/xhaus/satellite/status");
    el.textContent = formatSatelliteStatus(data);
    if (showNotice && data.status === "completed" && data.last_success_at && data.last_success_at !== state.satelliteLastSuccess) {
      state.satelliteLastSuccess = data.last_success_at;
      toast("Satellite 已更新报告，请查看自我认知文档");
      loadCognitionDocs();
    }
  } catch (err) {
    el.textContent = "Satellite 状态不可用";
  }
}

async function runSatelliteNow() {
  const el = $("#satelliteStatus");
  if (el) {
    el.textContent = "Satellite 正在读取近两周历史...";
  }
  try {
    const data = await api("/api/xhaus/satellite/run", {
      method: "POST",
      body: JSON.stringify({ force: true }),
    });
    if (el) {
      el.textContent = formatSatelliteStatus(data);
    }
    if (isSatelliteFailure(data)) {
      toast(data.last_message || "Satellite 运行失败");
      return;
    }
    if (data.status === "completed") {
      toast("Satellite 已运行，请查看自我认知文档");
      loadCognitionDocs();
      return;
    }
    toast(data.last_message || "Satellite 已提交运行，请稍后查看状态");
  } catch (err) {
    if (el) {
      el.textContent = readableError(err, "Satellite 运行失败");
    }
    toast(readableError(err, "Satellite 运行失败"));
  }
}

async function launchApp() {
  if (state.started) {
    return;
  }
  state.started = true;
  $("#landing").hidden = true;
  $("#appShell").hidden = false;
  initConversations();
  renderMessages();

  await Promise.allSettled([ensureSession(), fetchPresetChoices(), loadSkillList(), loadCognitionDocs(), loadSatelliteStatus()]);
  await Promise.allSettled([activateXhaus(), checkOpenClaw()]);

  state.runtimeTimer = setInterval(refreshRuntime, 2500);
  state.statusTimer = setInterval(checkOpenClaw, 9000);
  state.satelliteTimer = setInterval(() => loadSatelliteStatus(true), 12000);
  $("#messageInput").focus();
}

function bindEvents() {
  $("#startBtn").addEventListener("click", launchApp);
  $("#startBtnTop").addEventListener("click", launchApp);
  $("#storyPingBtn").addEventListener("click", () => checkOpenClaw(true));
  $("#chatForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = $("#messageInput");
    const text = input.value.trim();
    input.value = "";
    sendMessage(text);
  });
  $("#activateBtn").addEventListener("click", activateXhaus);
  $("#stopXhausBtn").addEventListener("click", stopXhaus);
  $("#sendWizardBtn").addEventListener("click", sendWizardInput);
  $("#sendEmptyBtn").addEventListener("click", sendEmptyInput);
  $("#wizardInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      if ($("#wizardInput").value.trim() || !state.currentPrompt.allow_empty) {
        sendWizardInput();
      } else {
        sendEmptyInput();
      }
    }
  });
  $("#installSkillBtn").addEventListener("click", installSkill);
  $("#saveCogBtn").addEventListener("click", saveCognition);
  $("#runSatelliteBtn").addEventListener("click", runSatelliteNow);
  $("#newConversationBtn").addEventListener("click", startNewConversation);
  $("#historyToggleBtn").addEventListener("click", toggleConversationHistory);
  $("#renameConversationBtn").addEventListener("click", renameConversation);
  $("#saveEditorBtn").addEventListener("click", saveManagedEditor);
  $("#deleteEditorBtn").addEventListener("click", deleteManagedFromEditor);
  $("#closeEditorBtn").addEventListener("click", closeEditor);
  document.querySelectorAll("[data-close-editor]").forEach((el) => {
    el.addEventListener("click", closeEditor);
  });
  document.querySelectorAll("[data-expand-source]").forEach((button) => {
    button.addEventListener("click", () => {
      openDetail(button.dataset.expandTitle || "详情", button.dataset.expandSource);
    });
  });
  $("#closeDetailBtn").addEventListener("click", closeDetail);
  document.querySelectorAll("[data-close-detail]").forEach((el) => {
    el.addEventListener("click", closeDetail);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeDetail();
      closeEditor();
    }
  });
  document.querySelectorAll(".quick-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      if (!state.started) {
        launchApp().then(() => {
          $("#messageInput").value = chip.dataset.prompt || "";
          $("#messageInput").focus();
        });
        return;
      }
      $("#messageInput").value = chip.dataset.prompt || "";
      $("#messageInput").focus();
    });
  });
}

function boot() {
  bindEvents();
}

boot();
