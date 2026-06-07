const api = require("../../services/apiService");
const conversationStore = require("../../services/conversationService");
const markdown = require("../../services/markdownService");

const POLL_INTERVAL_MS = 300;
const WS_URL_KEY = "xhaus_miniprogram_websocket_url";
const WS_URL_HISTORY_KEY = "xhaus_miniprogram_websocket_history";

function makeId() {
  return `${Date.now()}_${Math.floor(Math.random() * 100000)}`;
}

function makeMessage(role, text) {
  return decorateMessage({
    id: makeId(),
    role,
    text: text || "",
  });
}

function decorateMessage(message) {
  const next = Object.assign({}, message);
  next.blocks = next.role === "assistant" ? markdown.parseMarkdown(next.text || "") : [];
  return next;
}

function prepareMessages(messages) {
  return (messages || []).map(decorateMessage);
}

function titleFromMessages(messages) {
  const user = (messages || []).find((item) => item.role === "user" && item.text);
  return user ? String(user.text).slice(0, 28) : "新的对话";
}

function normalizeAgentForChat(value) {
  const id = String(value || "main").replace(/^custom:/, "").toLowerCase();
  const map = {
    default_butler: "main",
    emma: "emma",
    franziska: "franziska",
    elegant_maid: "elegant_maid",
  };
  return map[id] || id || "main";
}

function personaErrorMessage(err) {
  const message = err && err.message ? err.message : "";
  if (/request|fail|timeout|ERR|Network/i.test(message)) {
    return "后端不可用，请检查 apiBase 和本机 backend";
  }
  if (message === "xhaus_persona_not_found") {
    return "未找到管家预设，请检查 XHAUS_ROOT";
  }
  if (message === "xhaus_main_not_found") {
    return "未找到 XHAUS/main.py";
  }
  if (message === "custom_profile_agent_sync_failed") {
    return "自定义管家同步失败";
  }
  if (message === "persona_switch_failed") {
    return "管家切换失败";
  }
  return "切换失败";
}

Page({
  data: {
    hasStarted: false,
    safeTop: 80,
    apiBase: "",
    openclawStatus: "连接中",
    xhausStatus: "idle",
    activeAgentId: "main",
    activeAgentLabel: "默认管家",
    websocketUrl: "",
    activeConversationId: "",
    conversationTitle: "新的对话",
    messages: [],
    inputValue: "",
    isSending: false,
    isSwitchingPersona: false,
    currentTaskId: "",
    lastSeq: 0,
    scrollTarget: "",
    session: null,
    quickPrompts: [
      {
        label: "餐饮",
        prompt: "帮我规划今晚吃饭，按我的口味选餐厅并安排路线。",
      },
      {
        label: "娱乐",
        prompt: "给我安排一个放松的周末娱乐计划。",
      },
      {
        label: "出行",
        prompt: "帮我规划去目的地的最优出行方案。",
      },
      {
        label: "日程",
        prompt: "帮我把今天剩下的事情排成一个详细日程。",
      },
    ],
  },

  onLoad() {
    this.pollTimer = null;
    this.statusTimer = null;
    this.currentAssistantId = "";
    this.conversation = null;
    this.updateSafeTop();
    this.setData({
      apiBase: api.getApiBase(),
      websocketUrl: this.loadWebSocketUrl(),
    });
  },

  onShow() {
    if (this.data.hasStarted) {
      this.restoreActiveConversation();
    }
  },

  onUnload() {
    this.stopPolling();
    if (this.statusTimer) {
      clearInterval(this.statusTimer);
      this.statusTimer = null;
    }
  },

  updateSafeTop() {
    if (typeof wx.getMenuButtonBoundingClientRect !== "function") {
      return;
    }
    const rect = wx.getMenuButtonBoundingClientRect();
    if (rect && rect.bottom) {
      this.setData({ safeTop: rect.bottom + 10 });
    }
  },

  startExperience() {
    if (this.data.hasStarted) {
      return;
    }
    this.setData({ hasStarted: true });
    this.restoreActiveConversation()
      .then(() => this.ensureWebSocketUrl())
      .then(() => this.switchPersona({ random: false, silent: true }))
      .catch(() => {
        // The chat view can still open; the user will see status feedback.
      });
    this.checkOpenClawStatus();
    this.statusTimer = setInterval(() => this.checkOpenClawStatus(), 9000);
  },

  loadWebSocketUrl() {
    try {
      return String(wx.getStorageSync(WS_URL_KEY) || "").trim();
    } catch (err) {
      return "";
    }
  },

  loadWebSocketHistory() {
    try {
      const history = wx.getStorageSync(WS_URL_HISTORY_KEY);
      return Array.isArray(history)
        ? Array.from(new Set(history.map((item) => String(item || "").trim()).filter(Boolean))).slice(0, 8)
        : [];
    } catch (err) {
      return [];
    }
  },

  saveWebSocketUrl(url) {
    const value = String(url || "").trim();
    if (!/^wss?:\/\//i.test(value)) {
      return false;
    }
    const nextHistory = [value].concat(this.loadWebSocketHistory().filter((item) => item !== value)).slice(0, 8);
    try {
      wx.setStorageSync(WS_URL_KEY, value);
      wx.setStorageSync(WS_URL_HISTORY_KEY, nextHistory);
    } catch (err) {
      // Ignore storage failures; the current request can still use the value.
    }
    this.setData({ websocketUrl: value });
    return true;
  },

  promptWebSocketUrl({ title = "填写 WebSocket", required = true } = {}) {
    return new Promise((resolve, reject) => {
      const current = this.data.websocketUrl || this.loadWebSocketUrl();
      wx.showModal({
        title,
        content: current
          ? `当前：${current}\n请输入新的 OpenClaw Gateway WebSocket 地址`
          : "请输入运行 OpenClaw Gateway 的 WebSocket 地址",
        editable: true,
        placeholderText: "例如 ws://127.0.0.1:18789",
        confirmText: "保存",
        cancelText: required ? "稍后" : "取消",
        success: (result) => {
          if (!result.confirm) {
            if (required) {
              reject(new Error("websocket_required"));
            } else {
              resolve("");
            }
            return;
          }
          const value = String(result.content || current || "").trim();
          if (!/^wss?:\/\//i.test(value)) {
            wx.showToast({ title: "请填写 ws:// 或 wss://", icon: "none" });
            reject(new Error("invalid_websocket"));
            return;
          }
          this.saveWebSocketUrl(value);
          resolve(value);
        },
        fail: reject,
      });
    });
  },

  ensureWebSocketUrl() {
    const existing = this.data.websocketUrl || this.loadWebSocketUrl();
    if (/^wss?:\/\//i.test(existing)) {
      this.saveWebSocketUrl(existing);
      return Promise.resolve(existing);
    }
    return this.promptWebSocketUrl({ title: "首次填写 WebSocket", required: true });
  },

  changeWebSocketUrl() {
    const history = this.loadWebSocketHistory().slice(0, 5);
    const items = history.concat(["输入新的 WebSocket"]);
    wx.showActionSheet({
      itemList: items,
      success: (result) => {
        if (result.tapIndex < history.length) {
          this.saveWebSocketUrl(history[result.tapIndex]);
          wx.showToast({ title: "WebSocket 已切换", icon: "none" });
          return;
        }
        this.promptWebSocketUrl({ title: "切换 WebSocket", required: false })
          .then((value) => {
            if (value) {
              wx.showToast({ title: "WebSocket 已保存", icon: "none" });
            }
          })
          .catch(() => {});
      },
    });
  },

  createBackendSession() {
    return api.request({
      url: "/api/xhaus/web-session",
      method: "POST",
      data: {},
    }).then((response) => {
      if (!response || response.code !== 0) {
        throw new Error((response && response.message) || "session_failed");
      }
      const payload = response.data || {};
      return {
        user_id: payload.user_id,
        session_id: payload.session_id,
        token: payload.token,
        expiresAt: Date.now() + (payload.expires_in || 7200) * 1000,
      };
    });
  },

  restoreActiveConversation() {
    const activeId = conversationStore.getActiveId();
    const existing = activeId ? conversationStore.getConversation(activeId) : null;
    if (existing) {
      if (existing.session && existing.session.expiresAt > Date.now()) {
        this.conversation = existing;
        this.setConversationData(existing);
        return Promise.resolve(existing);
      }
      return this.createBackendSession().then((session) => {
        const refreshed = conversationStore.saveConversation(Object.assign({}, existing, { session }));
        this.conversation = refreshed;
        this.setConversationData(refreshed);
        return refreshed;
      });
    }
    return this.createNewConversation();
  },

  createNewConversation() {
    return this.createBackendSession().then((session) => {
      const conversation = conversationStore.createConversation({
        session,
        agentId: this.data.activeAgentId,
        agentLabel: this.data.activeAgentLabel,
      });
      this.conversation = conversation;
      this.setConversationData(conversation);
      return conversation;
    });
  },

  setConversationData(conversation) {
    const messages = prepareMessages(conversation.messages || []);
    this.setData({
      activeConversationId: conversation.id,
      conversationTitle: conversation.title || titleFromMessages(messages),
      session: conversation.session || null,
      messages,
      scrollTarget: messages.length ? `msg-${messages[messages.length - 1].id}` : "",
    });
  },

  persistConversation() {
    if (!this.conversation) {
      return;
    }
    const messages = this.data.messages.map((item) => ({
      id: item.id,
      role: item.role,
      text: item.text || "",
    }));
    const autoTitle = titleFromMessages(messages);
    const useCustomTitle = !!this.conversation.customTitle;
    this.conversation = conversationStore.saveConversation(Object.assign({}, this.conversation, {
      title: useCustomTitle ? (this.data.conversationTitle || autoTitle) : autoTitle,
      customTitle: useCustomTitle,
      agentId: this.data.activeAgentId,
      agentLabel: this.data.activeAgentLabel,
      session: this.data.session,
      messages,
    }));
    this.setData({
      conversationTitle: this.conversation.title,
      activeConversationId: this.conversation.id,
    });
  },

  checkOpenClawStatus() {
    api.request({ url: "/api/openclaw/status" })
      .then((response) => {
        const payload = (response && response.data) || {};
        const status = payload.ok ? (payload.writable === false ? "待授权" : "在线") : "离线";
        this.setData({ openclawStatus: status });
      })
      .catch(() => this.setData({ openclawStatus: "离线" }));
  },

  switchPersona(options = {}) {
    const random = options.random !== false;
    if (this.data.isSwitchingPersona) {
      return Promise.resolve();
    }
    this.setData({ isSwitchingPersona: true, xhausStatus: "切换中" });
    return this.ensureWebSocketUrl().then((websocketUrl) => {
    const payload = Object.assign(options.personaIndex
      ? { persona_index: options.personaIndex }
      : random
        ? {}
        : { persona_index: 1 }, { websocket_url: websocketUrl });
    return api.request({
      url: "/api/xhaus/switch-persona",
      method: "POST",
      data: payload,
    })
      .then((response) => {
        if (!response || response.code !== 0) {
          throw new Error((response && response.message) || "persona_switch_failed");
        }
        const selected = response.data && response.data.selected;
        const runtime = response.data && response.data.runtime;
        const active = runtime && runtime.active_agent;
        const label = (active && active.label) || (selected && selected.label) || this.data.activeAgentLabel;
        const id = (selected && selected.agent_id) || (active && active.id) || (selected && selected.value) || this.data.activeAgentId;
        this.setData({
          activeAgentId: normalizeAgentForChat(id),
          activeAgentLabel: label,
          xhausStatus: runtime && runtime.status ? runtime.status : "已切换",
          isSwitchingPersona: false,
        });
        this.persistConversation();
        if (!options.silent) {
          wx.showToast({ title: `已切换到 ${label}`, icon: "none" });
        }
      })
      .catch((err) => {
        console.error("persona_switch_failed", err);
        const message = personaErrorMessage(err);
        this.setData({ isSwitchingPersona: false, xhausStatus: message });
        if (!options.silent) {
          wx.showToast({ title: message, icon: "none" });
        }
      });
    }).catch((err) => {
      this.setData({ isSwitchingPersona: false, xhausStatus: "等待 WebSocket" });
      if (!options.silent) {
        wx.showToast({ title: err.message === "websocket_required" ? "需要先填写 WebSocket" : "WebSocket 无效", icon: "none" });
      }
    });
  },

  randomPersona() {
    if (this.data.isSwitchingPersona) {
      return;
    }
    wx.navigateTo({
      url: "/pages/persona/index",
      events: {
        personaSelected: (choice) => {
          if (choice && choice.index) {
            this.switchPersona({ random: false, personaIndex: choice.index });
          }
        },
      },
    });
  },

  newConversation() {
    this.stopPolling();
    this.currentAssistantId = "";
    this.createNewConversation().then(() => {
      wx.showToast({ title: "已新建对话", icon: "none" });
    });
  },

  openSkillPage() {
    wx.navigateTo({ url: "/pages/skill/index" });
  },

  openMemoryPage() {
    wx.navigateTo({ url: "/pages/memory/index" });
  },

  openHistoryPage() {
    this.persistConversation();
    wx.navigateTo({ url: "/pages/history/index" });
  },

  editConversationTitle() {
    const current = this.data.conversationTitle || "新的对话";
    wx.showModal({
      title: "编辑对话名称",
      editable: true,
      content: current,
      placeholderText: "输入新的对话名称",
      confirmText: "保存",
      success: (result) => {
        if (!result.confirm) {
          return;
        }
        const title = String(result.content || current).trim() || current;
        this.setData({ conversationTitle: title });
        if (this.conversation) {
          this.conversation = conversationStore.saveConversation(Object.assign({}, this.conversation, {
            title,
            customTitle: true,
          }));
        }
      },
    });
  },

  onInputChange(e) {
    this.setData({ inputValue: e.detail.value });
  },

  fillPrompt(e) {
    this.setData({ inputValue: e.currentTarget.dataset.prompt || "" });
  },

  sendMessage() {
    const text = String(this.data.inputValue || "").trim();
    if (!text || this.data.isSending) {
      return;
    }
    if (!this.data.session || this.data.session.expiresAt <= Date.now()) {
      this.createNewConversation().then(() => this.sendMessage());
      return;
    }

    const userMessage = makeMessage("user", text);
    const assistantMessage = makeMessage("assistant", "");
    this.currentAssistantId = assistantMessage.id;
    this.setData({
      messages: this.data.messages.concat([userMessage, assistantMessage]),
      inputValue: "",
      isSending: true,
      currentTaskId: "",
      lastSeq: 0,
      scrollTarget: `msg-${assistantMessage.id}`,
    });
    this.persistConversation();

    const session = this.data.session;
    const sendChatRequest = (currentSession) => api.request({
      url: "/api/chat",
      method: "POST",
      data: {
        user_id: currentSession.user_id,
        session_id: currentSession.session_id,
        token: currentSession.token,
        message: text,
        agent: normalizeAgentForChat(this.data.activeAgentId),
        use_active_agent: true,
        client: "wechat_miniprogram",
      },
    });

    sendChatRequest(session)
      .catch((err) => {
        if (err && err.message === "session_not_found") {
          return this.createBackendSession().then((freshSession) => {
            this.setData({ session: freshSession });
            if (this.conversation) {
              this.conversation = conversationStore.saveConversation(Object.assign({}, this.conversation, {
                session: freshSession,
              }));
            }
            return sendChatRequest(freshSession);
          });
        }
        throw err;
      })
      .then((response) => {
        if (!response || response.code !== 0) {
          throw new Error((response && response.message) || "chat_failed");
        }
        const taskId = response.data && response.data.task_id;
        if (!taskId) {
          throw new Error("missing_task_id");
        }
        this.setData({ currentTaskId: taskId, lastSeq: 0 });
        this.startPolling(taskId);
      })
      .catch((err) => this.handleChatError(err));
  },

  startPolling(taskId) {
    this.stopPolling();
    const poll = () => {
      const session = this.data.session;
      if (!session || this.data.currentTaskId !== taskId) {
        return;
      }
      api.request({
        url: `/api/chat/${taskId}?since=${this.data.lastSeq}`,
        headers: {
          Authorization: `Bearer ${session.token}`,
          "x-user-id": session.user_id,
          "x-session-id": session.session_id,
        },
      })
        .then((response) => {
          if (!response || response.code !== 0) {
            throw new Error((response && response.message) || "poll_failed");
          }
          const payload = response.data || {};
          const deltas = payload.deltas || [];
          deltas.forEach((delta) => this.appendAssistantDelta(delta.content || ""));
          this.setData({ lastSeq: payload.seq || this.data.lastSeq });

          if (payload.status === "done") {
            this.finishTask();
            return;
          }
          if (payload.status === "error" || payload.status === "cancelled") {
            this.handleChatError(new Error(payload.error || "task_error"));
            return;
          }
          this.pollTimer = setTimeout(poll, POLL_INTERVAL_MS);
        })
        .catch((err) => this.handleChatError(err));
    };
    poll();
  },

  appendAssistantDelta(content) {
    const messages = this.data.messages.map((item) => {
      if (item.id !== this.currentAssistantId) return item;
      return decorateMessage(Object.assign({}, item, { text: `${item.text || ""}${content}` }));
    });
    this.setData({
      messages,
      scrollTarget: `msg-${this.currentAssistantId}`,
    });
  },

  finishTask() {
    this.stopPolling();
    this.currentAssistantId = "";
    this.setData({
      isSending: false,
      currentTaskId: "",
    });
    this.persistConversation();
  },

  handleChatError(err) {
    console.error("chat_error", err);
    this.stopPolling();
    const raw = err && err.message ? err.message : "";
    const detail = /request|fail|timeout|Network/i.test(raw)
      ? "后端不可用：请确认本机 backend 正在运行，并且 envList.js 的 apiBase 指向这台电脑。"
      : /Unknown agent id|404/i.test(raw)
        ? "当前管家还没有在 OpenClaw 注册完成，请先换管家并等待 XHAUS 完成初始化。"
        : raw || "OpenClaw 暂时没有返回，请检查网关与模型服务。";
    const messages = this.data.messages.map((item) => {
      if (item.id !== this.currentAssistantId) return item;
      return decorateMessage(Object.assign({}, item, {
        text: item.text || detail,
      }));
    });
    this.currentAssistantId = "";
    this.setData({
      messages,
      isSending: false,
      currentTaskId: "",
    });
    this.persistConversation();
    wx.showToast({ title: "对话失败", icon: "none" });
  },

  stopPolling() {
    if (this.pollTimer) {
      clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
  },
});
