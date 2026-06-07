const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");
const {
  OPENCLAW_AUTHORIZATION,
  OPENCLAW_CHAT_COMPLETIONS_URL,
  OPENCLAW_CONFIG_PATH,
  OPENCLAW_GATEWAY_TOKEN,
  OPENCLAW_GATEWAY_URL,
  OPENCLAW_SESSION_KEY,
  OPENCLAW_STATE_DIR,
} = require("../config/env");
const { XHAUS_ROOT } = require("./projectPaths");
const { SSEParser } = require("../utils/sseParser");
const { pythonCandidates } = require("../utils/python");

const DEFAULT_MODEL = "openclaw/default";
const RETRY_LIMIT = 1;
const RETRY_BASE_MS = 400;
const PING_TIMEOUT_MS = 5000;
const CHAT_TIMEOUT_MS = 300000;
const BRIDGE_SCRIPT = path.join(XHAUS_ROOT, "frontend_chat_bridge.py");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function emitTextIncrementally(text, onDelta, meta) {
  const source = String(text || "");
  if (!source || !onDelta) {
    return;
  }
  const chunkSize = 18;
  for (let index = 0; index < source.length; index += chunkSize) {
    onDelta(source.slice(index, index + chunkSize), meta);
    if (index + chunkSize < source.length) {
      await sleep(35);
    }
  }
}

function stripBearer(value) {
  return String(value || "").replace(/^Bearer\s+/i, "").trim();
}

function buildHeaders() {
  const headers = {
    "Content-Type": "application/json",
  };

  const token = stripBearer(OPENCLAW_AUTHORIZATION);
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  return headers;
}

function readJson(filePath) {
  try {
    if (!filePath || !fs.existsSync(filePath)) {
      return {};
    }
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (err) {
    return {};
  }
}

function openclawConfigPath() {
  if (OPENCLAW_CONFIG_PATH) {
    return path.resolve(OPENCLAW_CONFIG_PATH);
  }
  const stateDir = OPENCLAW_STATE_DIR || path.join(os.homedir(), ".openclaw");
  return path.join(stateDir, "openclaw.json");
}

function loadOpenClawConfig() {
  return readJson(openclawConfigPath());
}

function normalizeWsUrl(value) {
  const url = String(value || "").trim();
  if (url.startsWith("http://")) {
    return `ws://${url.slice("http://".length)}`;
  }
  if (url.startsWith("https://")) {
    return `wss://${url.slice("https://".length)}`;
  }
  return url;
}

function resolveGateway() {
  const config = loadOpenClawConfig();
  const gateway = config.gateway && typeof config.gateway === "object" ? config.gateway : {};
  const configuredUrl = OPENCLAW_GATEWAY_URL || gateway.url || "";
  let url = normalizeWsUrl(configuredUrl);

  if (!url) {
    const rawPort = Number.parseInt(gateway.port || "18789", 10);
    const port = Number.isFinite(rawPort) ? rawPort : 18789;
    const rawHost = String(gateway.host || gateway.hostname || "127.0.0.1").trim();
    const host = !rawHost || rawHost === "0.0.0.0" || rawHost === "::" ? "127.0.0.1" : rawHost;
    url = `ws://${host}:${port}`;
  }

  const configToken = gateway.auth && gateway.auth.token ? String(gateway.auth.token).trim() : "";
  const token = OPENCLAW_GATEWAY_TOKEN || configToken || stripBearer(OPENCLAW_AUTHORIZATION);

  return {
    url,
    token,
    configPath: openclawConfigPath(),
  };
}

function deriveModelsUrl() {
  const endpoint = String(OPENCLAW_CHAT_COMPLETIONS_URL || "").trim();
  if (!endpoint) {
    return "";
  }
  return endpoint.replace(/\/v1\/chat\/completions.*$/i, "/v1/models");
}

function isLikelyJson(response, text) {
  const contentType = response.headers.get("content-type") || "";
  const trimmed = String(text || "").trim();
  return contentType.includes("application/json") || trimmed.startsWith("{") || trimmed.startsWith("[");
}

async function consumeStream(response, { onDelta, onDone }) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  const parser = new SSEParser();

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    const text = decoder.decode(value, { stream: true });
    const events = parser.feed(text);
    for (const event of events) {
      if (event === "[DONE]") {
        if (onDone) {
          onDone();
        }
        return;
      }
      try {
        const payload = JSON.parse(event);
        const choice = payload.choices && payload.choices[0];
        const delta = choice && choice.delta && choice.delta.content;
        if (delta && onDelta) {
          onDelta(delta, payload);
        }
      } catch (err) {
        // Ignore malformed chunks from streaming transports.
      }
    }
  }

  const remaining = parser.flush();
  for (const event of remaining) {
    if (event === "[DONE]") {
      if (onDone) {
        onDone();
      }
      return;
    }
  }

  if (onDone) {
    onDone();
  }
}

async function chatViaHttp({
  messages,
  metadata,
  stream,
  signal,
  onDelta,
  onDone,
  model,
}) {
  const endpoint = String(OPENCLAW_CHAT_COMPLETIONS_URL || "").trim();
  if (!endpoint) {
    throw new Error("OPENCLAW_CHAT_COMPLETIONS_URL 未配置");
  }

  const payload = {
    model: model || DEFAULT_MODEL,
    messages,
    stream,
    metadata,
  };

  const response = await fetch(endpoint, {
    method: "POST",
    headers: buildHeaders(),
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`OpenClaw HTTP ${response.status}: ${text.slice(0, 360)}`);
  }

  if (!stream) {
    return await response.json();
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const json = await response.json();
    const content =
      json.choices &&
      json.choices[0] &&
      json.choices[0].message &&
      json.choices[0].message.content;
    if (content) {
      await emitTextIncrementally(content, onDelta, json);
    }
    if (onDone) {
      onDone();
    }
    return json;
  }
  if (!contentType.includes("text/event-stream")) {
    const text = await response.text();
    throw new Error(`OpenClaw HTTP 返回的不是兼容对话流: ${text.slice(0, 160)}`);
  }

  await consumeStream(response, { onDelta, onDone });
  return null;
}

function latestUserMessage(messages) {
  const list = Array.isArray(messages) ? messages : [];
  for (let index = list.length - 1; index >= 0; index -= 1) {
    const message = list[index];
    if (message && message.role === "user" && message.content) {
      return String(message.content);
    }
  }
  return "";
}

function messageContent(message) {
  if (!message || typeof message !== "object") {
    return "";
  }
  const content = message.content;
  if (typeof content === "string") {
    return content;
  }
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (!part || typeof part !== "object") {
          return "";
        }
        return typeof part.text === "string" ? part.text : "";
      })
      .join("");
  }
  return "";
}

function buildBridgeMessage(messages) {
  const list = Array.isArray(messages) ? messages : [];
  let lastUserIndex = -1;
  for (let index = list.length - 1; index >= 0; index -= 1) {
    if (list[index] && list[index].role === "user") {
      lastUserIndex = index;
      break;
    }
  }
  const latest = lastUserIndex >= 0 ? messageContent(list[lastUserIndex]) : latestUserMessage(list);
  const systemText = list
    .filter((message) => message && message.role === "system")
    .map(messageContent)
    .filter(Boolean)
    .join("\n\n");
  const history = list
    .slice(Math.max(0, lastUserIndex - 8), Math.max(0, lastUserIndex))
    .filter((message) => message && (message.role === "user" || message.role === "assistant"))
    .map((message) => `${message.role === "assistant" ? "管家" : "用户"}：${messageContent(message)}`)
    .filter((line) => !/：$/.test(line))
    .join("\n");

  const parts = [];
  if (systemText) {
    parts.push(`【系统说明与长期记忆】\n${systemText}`);
  }
  if (history) {
    parts.push(`【近期对话】\n${history}`);
  }
  parts.push(`【用户当前请求】\n${latest}`);
  return parts.join("\n\n").slice(-16000);
}

function parseBridgeLine(line, state, onEvent) {
  const trimmed = line.trim();
  if (!trimmed) {
    return;
  }
  try {
    const event = JSON.parse(trimmed);
    state.events.push(event);
    if (event.event === "error") {
      state.error = event.message || "OpenClaw Gateway error";
    }
    if (event.event === "done") {
      state.done = event;
    }
    if (event.event === "status") {
      state.status = event;
    }
    if (onEvent) {
      onEvent(event);
    }
  } catch (err) {
    state.stdout.push(trimmed);
  }
}

function runBridge(payload, { signal, timeoutMs = CHAT_TIMEOUT_MS, onEvent } = {}) {
  if (!fs.existsSync(BRIDGE_SCRIPT)) {
    return Promise.reject(new Error(`XHAUS bridge not found: ${BRIDGE_SCRIPT}`));
  }

  const candidates = pythonCandidates();
  let candidateIndex = 0;

  return new Promise((resolve, reject) => {
    let child = null;
    let settled = false;

    const trySpawn = () => {
      if (candidateIndex >= candidates.length) {
        reject(new Error("未找到可用 Python。请设置 XHAUS_PYTHON 或 PYTHON 指向 Python 解释器。"));
        return;
      }

      const command = candidates[candidateIndex];
      candidateIndex += 1;
      const state = {
        events: [],
        stdout: [],
        stderr: "",
        error: "",
        done: null,
        status: null,
      };
      let stdoutBuffer = "";
      let spawnFailed = false;

      child = spawn(command, [BRIDGE_SCRIPT], {
        cwd: XHAUS_ROOT,
        env: Object.assign({}, process.env, {
          OPENCLAW_GATEWAY_TOKEN: OPENCLAW_GATEWAY_TOKEN || process.env.OPENCLAW_GATEWAY_TOKEN || "",
          OPENCLAW_GATEWAY_URL: OPENCLAW_GATEWAY_URL || process.env.OPENCLAW_GATEWAY_URL || "",
          OPENCLAW_SESSION_KEY: OPENCLAW_SESSION_KEY || process.env.OPENCLAW_SESSION_KEY || "",
          XHAUS_SESSION_KEY: OPENCLAW_SESSION_KEY || process.env.XHAUS_SESSION_KEY || "",
          PYTHONIOENCODING: "utf-8",
          PYTHONUTF8: "1",
        }),
        shell: false,
        windowsHide: true,
        stdio: ["pipe", "pipe", "pipe"],
      });

      const timer = setTimeout(() => {
        if (child && !child.killed) {
          child.kill();
        }
        state.error = state.error || `OpenClaw bridge timed out after ${timeoutMs}ms`;
      }, timeoutMs);

      const abort = () => {
        if (child && !child.killed) {
          child.kill();
        }
      };
      if (signal) {
        if (signal.aborted) {
          abort();
        } else {
          signal.addEventListener("abort", abort, { once: true });
        }
      }

      child.stdout.on("data", (chunk) => {
        stdoutBuffer += chunk.toString("utf8");
        const lines = stdoutBuffer.split(/\r?\n/);
        stdoutBuffer = lines.pop() || "";
        for (const line of lines) {
          parseBridgeLine(line, state, onEvent);
        }
      });

      child.stderr.on("data", (chunk) => {
        state.stderr += chunk.toString("utf8");
      });

      child.stdin.end(JSON.stringify(payload));

      child.on("error", (err) => {
        clearTimeout(timer);
        spawnFailed = true;
        if (signal) {
          signal.removeEventListener("abort", abort);
        }
        if (err.code === "ENOENT") {
          trySpawn();
          return;
        }
        if (!settled) {
          settled = true;
          reject(err);
        }
      });

      child.on("close", (code) => {
        if (spawnFailed) {
          return;
        }
        clearTimeout(timer);
        if (signal) {
          signal.removeEventListener("abort", abort);
        }
        if (stdoutBuffer.trim()) {
          parseBridgeLine(stdoutBuffer, state, onEvent);
        }
        if (signal && signal.aborted) {
          if (!settled) {
            settled = true;
            reject(new Error("OpenClaw request aborted"));
          }
          return;
        }
        if (code === 0) {
          if (!settled) {
            settled = true;
            resolve(state);
          }
          return;
        }
        if (state.status) {
          if (!settled) {
            settled = true;
            resolve(state);
          }
          return;
        }
        const detail = state.error || state.stderr.trim() || state.stdout.join("\n") || `OpenClaw bridge exited with ${code}`;
        if (!settled) {
          settled = true;
          reject(new Error(detail));
        }
      });
    };

    trySpawn();
  });
}

async function chatViaBridge({ messages, metadata, signal, onDelta, onDone }) {
  const agent = metadata && metadata.agent ? String(metadata.agent) : "main";
  const message = buildBridgeMessage(messages);
  const gateway = resolveGateway();
  let emitted = "";

  const state = await runBridge(
    {
      mode: "chat",
      message,
      agent_id: agent,
      gateway_url: gateway.url,
      timeout: Math.floor(CHAT_TIMEOUT_MS / 1000),
    },
    {
      signal,
      timeoutMs: CHAT_TIMEOUT_MS + 5000,
      onEvent(event) {
        if (event.event === "delta" && event.text) {
          emitted += event.text;
          if (onDelta) {
            onDelta(event.text, event);
          }
        }
      },
    },
  );

  const finalText = state.done && state.done.text ? String(state.done.text) : "";
  if (finalText && finalText !== emitted && onDelta) {
    const rest = finalText.startsWith(emitted) ? finalText.slice(emitted.length) : finalText;
    if (rest) {
      await emitTextIncrementally(rest, onDelta, state.done);
    }
  }
  if (onDone) {
    onDone();
  }
  return null;
}

async function chatCompletions(options) {
  let lastHttpError = null;

  if (OPENCLAW_CHAT_COMPLETIONS_URL) {
    for (let attempt = 0; attempt <= RETRY_LIMIT; attempt += 1) {
      try {
        return await chatViaHttp(options);
      } catch (err) {
        if (options.signal && options.signal.aborted) {
          throw err;
        }
        lastHttpError = err;
        if (attempt < RETRY_LIMIT) {
          await sleep(RETRY_BASE_MS * (attempt + 1));
        }
      }
    }
  }

  try {
    return await chatViaBridge(options);
  } catch (err) {
    if (!lastHttpError) {
      throw err;
    }
    throw new Error(`${err.message}（HTTP 兼容接口也不可用：${lastHttpError.message}）`);
  }
}

async function pingHttp() {
  const modelsUrl = deriveModelsUrl();
  if (!modelsUrl) {
    return {
      ok: false,
      transport: "http",
      detail: "OPENCLAW_CHAT_COMPLETIONS_URL 未配置",
    };
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PING_TIMEOUT_MS);
  try {
    const response = await fetch(modelsUrl, {
      method: "GET",
      headers: buildHeaders(),
      signal: controller.signal,
    });
    const text = await response.text();
    if ((response.ok || response.status === 401 || response.status === 403) && isLikelyJson(response, text)) {
      return {
        ok: true,
        writable: true,
        transport: "http",
        detail: `HTTP ${response.status}`,
      };
    }
    return {
      ok: false,
      transport: "http",
      detail: `HTTP ${response.status} 返回的不是兼容 JSON API`,
    };
  } catch (err) {
    return {
      ok: false,
      transport: "http",
      detail: err.message,
    };
  } finally {
    clearTimeout(timer);
  }
}

async function pingBridge() {
  const gateway = resolveGateway();
  try {
    const state = await runBridge(
      {
        mode: "ping",
        gateway_url: gateway.url,
      },
      {
        timeoutMs: PING_TIMEOUT_MS + 5000,
      },
    );
    return state.status || {
      ok: true,
      writable: false,
      transport: "gateway",
      detail: "Gateway reachable",
    };
  } catch (err) {
    return {
      ok: false,
      writable: false,
      transport: "gateway",
      detail: err.message,
      url: gateway.url,
      configPath: gateway.configPath,
    };
  }
}

async function ping() {
  if (OPENCLAW_CHAT_COMPLETIONS_URL) {
    const httpStatus = await pingHttp();
    if (httpStatus.ok) {
      return httpStatus;
    }
  }
  return await pingBridge();
}

module.exports = {
  chatCompletions,
  ping,
  resolveGateway,
};
