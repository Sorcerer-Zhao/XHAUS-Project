const express = require("express");
const fs = require("fs");
const path = require("path");
const openclawClient = require("../services/openclawClient");
const historyArchive = require("../services/historyArchiveService");
const sessionService = require("../services/sessionService");
const satelliteService = require("../services/satelliteService");
const taskService = require("../services/taskService");
const { getActiveAgent, normalizeAgentId } = require("../services/xhausSelection");
const { verifyToken } = require("../utils/token");
const { sendOk, sendError } = require("../utils/response");

const BACKEND_ROOT = path.resolve(__dirname, "..", "..");
const WORKSPACE_ROOT = path.resolve(BACKEND_ROOT, "..", "..");
const XHAUS_ROOT = process.env.XHAUS_ROOT ? path.resolve(process.env.XHAUS_ROOT) : path.join(WORKSPACE_ROOT, "XHAUS");
const SELF_COGNITION_DIR = path.join(XHAUS_ROOT, "runtime", "self_cognition");
const MAX_MEMORY_CHARS = 8000;

const AGENTS = {
  main: {
    id: "main",
    name: "默认管家",
    description: "当前未选择独立人设时使用的默认管家。",
    model: "openclaw/main",
    defaultSystemPrompt:
      "你是 OpenClaw XHAUS 的本地私人管家。请理解用户意图，结合长期记忆与当前上下文，给出可靠、贴心、可执行的帮助。",
  },
  default_butler: {
    id: "main",
    name: "默认管家",
    description: "默认管家的兼容入口。",
    model: "openclaw/main",
    defaultSystemPrompt:
      "你是 OpenClaw XHAUS 的本地私人管家。请理解用户意图，结合长期记忆与当前上下文，给出可靠、贴心、可执行的帮助。",
  },
  franziska: {
    id: "franziska",
    name: "Franziska",
    description: "聪明、有锋芒的私人管家，适合生活安排、偏好记忆与任务拆解。",
    model: "openclaw/hausmeister",
    defaultSystemPrompt:
      "你叫 Franziska，是一名聪明、忠诚但不盲从的全天候私人管家。你反应快、会看人，说话直接但有温度。核心信念：真正地帮助，而不是表演式地帮助。先自己想办法，再在必要时提问。",
  },
  hausmeister: {
    id: "hausmeister",
    name: "Franziska",
    description: "Franziska 的兼容入口。",
    model: "openclaw/hausmeister",
    defaultSystemPrompt:
      "你叫 Franziska，是一名聪明、忠诚但不盲从的全天候私人管家。你反应快、会看人，说话直接但有温度。核心信念：真正地帮助，而不是表演式地帮助。先自己想办法，再在必要时提问。",
  },
  emma: {
    id: "emma",
    name: "Emma",
    description: "温柔、细致、注重陪伴与秩序感的私人管家。",
    model: "openclaw/emma",
    defaultSystemPrompt:
      "你叫 Emma，是一位温柔、细致、有秩序感的全天候私人管家。你会主动记住用户偏好，帮助用户把生活、日程和情绪节奏安排得更舒适。",
  },
};

const DEFAULT_AGENT = "main";

const router = express.Router();

function extractAuth(req) {
  const authHeader = req.headers.authorization || "";
  const token = authHeader.replace(/^Bearer\s+/i, "").trim() || req.body?.token || req.query?.token || "";
  const userId = req.body?.user_id || req.query?.user_id || req.headers["x-user-id"] || "";
  const sessionId = req.body?.session_id || req.query?.session_id || req.headers["x-session-id"] || "";
  return { token, userId, sessionId };
}

function requireAuth(req, res) {
  const { token, userId, sessionId } = extractAuth(req);
  if (!token) {
    sendError(res, 40101, "missing_token", 401);
    return null;
  }

  let payload = null;
  try {
    payload = verifyToken(token);
  } catch (err) {
    sendError(res, 40102, "invalid_token", 401);
    return null;
  }

  const authUserId = userId || payload.userId;
  const authSessionId = sessionId || payload.sessionId;
  if (payload.userId !== authUserId || payload.sessionId !== authSessionId) {
    sendError(res, 40103, "token_mismatch", 401);
    return null;
  }

  return { userId: authUserId, sessionId: authSessionId };
}

function dynamicAgent(agentId, label) {
  const id = normalizeAgentId(agentId);
  return {
    id,
    name: label || id,
    description: "由 XHAUS 初始化向导选择的当前管家。",
    model: `openclaw/${id}`,
    defaultSystemPrompt: `你是 ${label || id}，OpenClaw XHAUS 当前选中的本地私人管家。请结合用户长期记忆和当前上下文提供帮助。`,
  };
}

function resolveAgent(req, session) {
  const active = getActiveAgent();
  const requested = req.body.use_active_agent === false
    ? req.body.agent || session.agent || DEFAULT_AGENT
    : active.id || req.body.agent || session.agent || DEFAULT_AGENT;
  const id = normalizeAgentId(requested);
  return AGENTS[id] || dynamicAgent(id, active.label);
}

function loadSelfCognitionContext() {
  if (!fs.existsSync(SELF_COGNITION_DIR)) {
    return "";
  }

  const docs = fs
    .readdirSync(SELF_COGNITION_DIR)
    .filter((name) => name.endsWith(".md") && name !== "Satellite-自动进化报告.md")
    .map((name) => {
      const file = path.join(SELF_COGNITION_DIR, name);
      const stat = fs.statSync(file);
      return { name, file, updated: stat.mtimeMs };
    })
    .sort((a, b) => b.updated - a.updated)
    .slice(0, 8);

  const chunks = [];
  let total = 0;
  for (const doc of docs) {
    try {
      const content = fs.readFileSync(doc.file, "utf8").trim();
      if (!content) {
        continue;
      }
      const block = `【${doc.name}】\n${content}`;
      chunks.push(block);
      total += block.length;
      if (total >= MAX_MEMORY_CHARS) {
        break;
      }
    } catch (err) {
      // Skip unreadable documents.
    }
  }
  return chunks.join("\n\n").slice(0, MAX_MEMORY_CHARS);
}

router.get("/agents", (req, res) => {
  const active = getActiveAgent();
  const list = Object.values(AGENTS).map(({ id, name, description }) => ({
    id,
    name,
    description,
  }));
  return sendOk(res, { agents: list, default: active.id || DEFAULT_AGENT, active });
});

router.get("/agents/:agentId", (req, res) => {
  const agent = AGENTS[req.params.agentId];
  if (!agent) {
    return sendError(res, 40403, "agent_not_found", 404);
  }
  return sendOk(res, { id: agent.id, name: agent.name, description: agent.description });
});

router.post("/chat", async (req, res) => {
  const message = req.body && req.body.message;
  if (!message) {
    return sendError(res, 40001, "missing_message", 400);
  }

  const auth = requireAuth(req, res);
  if (!auth) {
    return null;
  }

  const session = await sessionService.getSession(auth.sessionId);
  if (!session || session.userId !== auth.userId) {
    return sendError(res, 40401, "session_not_found", 404);
  }

  const agent = resolveAgent(req, session);
  const agentId = agent.id;

  const task = taskService.createTask({
    userId: auth.userId,
    sessionId: auth.sessionId,
    agent: agentId,
  });

  sendOk(res, {
    task_id: task.taskId,
    session_id: auth.sessionId,
    agent: agentId,
    status: task.status,
  });

  const controller = new AbortController();
  taskService.attachController(task.taskId, controller);

  const history = session.messages || [];
  const memoryContext = loadSelfCognitionContext();
  const systemPrompt = [
    agent.defaultSystemPrompt,
    memoryContext
      ? `以下是用户在网页端保存的自我认知与偏好文档。它们是长期记忆，回答时必须优先参考：\n${memoryContext}`
      : "",
  ]
    .filter(Boolean)
    .join("\n\n");
  const openclawMessages = [
    {
      role: "system",
      content: systemPrompt,
    },
    ...history,
    {
      role: "user",
      content: message,
    },
  ];

  let assistantText = "";

  openclawClient
    .chatCompletions({
      model: agent.model,
      messages: openclawMessages,
      metadata: {
        session_id: auth.sessionId,
        user_id: auth.userId,
        agent: agentId,
      },
      stream: true,
      signal: controller.signal,
      onDelta(delta) {
        assistantText += delta;
        taskService.appendDelta(task.taskId, delta);
      },
      onDone() {
        taskService.finishTask(task.taskId);
        try {
          historyArchive.appendConversation({
            userId: auth.userId,
            sessionId: auth.sessionId,
            agent: agentId,
            userMessage: message,
            assistantMessage: assistantText || "",
          });
          satelliteService.maybeRun("chat_completed");
        } catch (err) {
          console.error("history_archive_failed", err);
        }
        sessionService
          .updateAgent(auth.sessionId, agentId)
          .catch((err) => console.error("session_agent_update_failed", err));
        sessionService
          .appendMessages(auth.sessionId, [
            { role: "user", content: message },
            { role: "assistant", content: assistantText || "" },
          ])
          .catch((err) => {
            console.error("session_append_failed", err);
          });
      },
    })
    .catch((err) => {
      const detail = err && err.message ? err.message : "OpenClaw 暂时不可用";
      console.error("openclaw_error", detail);
      taskService.failTask(task.taskId, detail);
    });

  return null;
});

router.get("/chat/:taskId", (req, res) => {
  const auth = requireAuth(req, res);
  if (!auth) {
    return null;
  }

  const { taskId } = req.params;
  const since = parseInt(req.query.since || "0", 10);
  const result = taskService.getTaskView(taskId, Number.isNaN(since) ? 0 : since);
  if (!result) {
    return sendError(res, 40402, "task_not_found", 404);
  }

  if (result.task.sessionId !== auth.sessionId) {
    return sendError(res, 40301, "task_forbidden", 403);
  }

  return sendOk(res, {
    task_id: taskId,
    status: result.task.status,
    seq: result.task.seq,
    deltas: result.deltas,
    error: result.task.error,
  });
});

router.post("/chat/cancel", (req, res) => {
  const auth = requireAuth(req, res);
  if (!auth) {
    return null;
  }

  const taskId = req.body && req.body.task_id;
  if (!taskId) {
    return sendError(res, 40002, "missing_task_id", 400);
  }

  const task = taskService.getTask(taskId);
  if (!task) {
    return sendError(res, 40402, "task_not_found", 404);
  }

  if (task.sessionId !== auth.sessionId) {
    return sendError(res, 40301, "task_forbidden", 403);
  }

  taskService.cancelTask(taskId);
  return sendOk(res, null, "cancelled");
});

module.exports = router;
