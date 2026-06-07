const CONVERSATIONS_KEY = "xhaus_conversations_v2";
const ACTIVE_CONVERSATION_KEY = "xhaus_active_conversation_id";
const MAX_CONVERSATIONS = 80;

function nowIso() {
  return new Date().toISOString();
}

function makeId() {
  return `conv_${Date.now()}_${Math.floor(Math.random() * 100000)}`;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function readAll() {
  try {
    const list = wx.getStorageSync(CONVERSATIONS_KEY);
    return Array.isArray(list) ? list : [];
  } catch (err) {
    return [];
  }
}

function writeAll(list) {
  const normalized = (list || [])
    .filter((item) => item && item.id)
    .sort((a, b) => String(b.updatedAt || "").localeCompare(String(a.updatedAt || "")))
    .slice(0, MAX_CONVERSATIONS);
  try {
    wx.setStorageSync(CONVERSATIONS_KEY, normalized);
  } catch (err) {
    console.error("conversation_save_failed", err);
  }
  return normalized;
}

function summarize(messages) {
  const user = (messages || []).find((item) => item.role === "user" && item.text);
  return user ? String(user.text).slice(0, 28) : "新的对话";
}

function createConversation({ session, agentId, agentLabel } = {}) {
  const id = makeId();
  const time = nowIso();
  const conversation = {
    id,
    title: "新的对话",
    agentId: agentId || "main",
    agentLabel: agentLabel || "默认管家",
    session: session || null,
    messages: [],
    createdAt: time,
    updatedAt: time,
  };
  writeAll([conversation].concat(readAll()));
  setActiveId(id);
  return clone(conversation);
}

function getConversation(id) {
  const item = readAll().find((conversation) => conversation.id === id);
  return item ? clone(item) : null;
}

function listConversations() {
  return readAll().map((item) => ({
    id: item.id,
    title: item.title || summarize(item.messages),
    agentId: item.agentId || "main",
    agentLabel: item.agentLabel || item.agentId || "默认管家",
    messageCount: (item.messages || []).length,
    updatedAt: item.updatedAt || item.createdAt || "",
    preview: summarize(item.messages),
  }));
}

function saveConversation(conversation) {
  if (!conversation || !conversation.id) {
    return null;
  }
  const list = readAll();
  const next = Object.assign({}, conversation, {
    title: conversation.title || summarize(conversation.messages),
    updatedAt: nowIso(),
  });
  const index = list.findIndex((item) => item.id === next.id);
  if (index >= 0) {
    list[index] = next;
  } else {
    list.unshift(next);
  }
  writeAll(list);
  setActiveId(next.id);
  return clone(next);
}

function deleteConversation(id) {
  writeAll(readAll().filter((item) => item.id !== id));
  if (getActiveId() === id) {
    setActiveId("");
  }
}

function clearAll() {
  writeAll([]);
  setActiveId("");
}

function setActiveId(id) {
  try {
    wx.setStorageSync(ACTIVE_CONVERSATION_KEY, id || "");
  } catch (err) {
    // Ignore storage failures.
  }
}

function getActiveId() {
  try {
    return wx.getStorageSync(ACTIVE_CONVERSATION_KEY) || "";
  } catch (err) {
    return "";
  }
}

module.exports = {
  clearAll,
  createConversation,
  deleteConversation,
  getActiveId,
  getConversation,
  listConversations,
  saveConversation,
  setActiveId,
};
