const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");
const express = require("express");
const sessionService = require("../services/sessionService");
const satelliteService = require("../services/satelliteService");
const {
  getActiveAgent,
  normalizeAgentId,
  setActiveAgent,
  setActiveAgentFromChoice,
} = require("../services/xhausSelection");
const { signToken, TOKEN_TTL_SECONDS } = require("../utils/token");
const { XHAUS_DEFAULT_WEBSOCKET } = require("../config/env");
const { sendOk, sendError } = require("../utils/response");
const { setRuntimeGatewayUrl } = require("../services/openclawClient");

const router = express.Router();

const BACKEND_ROOT = path.resolve(__dirname, "..", "..");
const WORKSPACE_ROOT = path.resolve(BACKEND_ROOT, "..", "..");
const XHAUS_ROOT = process.env.XHAUS_ROOT ? path.resolve(process.env.XHAUS_ROOT) : path.join(WORKSPACE_ROOT, "XHAUS");
const PYTHON_BIN = process.env.XHAUS_PYTHON || process.env.PYTHON || "python";
const LOG_LIMIT = 180;
const PRESETS_ROOT = path.join(XHAUS_ROOT, "xhaus", "templates", "profiles", "presets");
const PRESET_LABELS = {
  default_butler: "默认管家",
  elegant_maid: "优雅女仆",
};
const PRESET_PRIORITY = ["default_butler", "elegant_maid"];
const PROFILE_DOCS = ["IDENTITY.md", "SOUL.md", "AGENTS.md", "USER.md"];
const CUSTOM_GUARD_START = "<!-- XHAUS_CUSTOM_PROFILE_GUARD_START -->";
const CUSTOM_GUARD_END = "<!-- XHAUS_CUSTOM_PROFILE_GUARD_END -->";
const PROFILE_DOC_META = {
  "IDENTITY.md": {
    title: "身份设定",
    tip: "写这个管家是谁、如何称呼你、主要职责和不能越界的地方。",
  },
  "SOUL.md": {
    title: "性格灵魂",
    tip: "写它的语气、情绪风格、陪伴方式，以及你希望它像什么样的人。",
  },
  "AGENTS.md": {
    title: "团队协作",
    tip: "写大管家和领域小管家的分工，例如餐饮、出行、娱乐、日程如何协作。",
  },
  "USER.md": {
    title: "用户认知",
    tip: "写这个人设默认应记住的你的偏好、习惯、称谓和服务节奏。",
  },
};

function pythonEnv(extra = {}) {
  return Object.assign({}, process.env, extra, {
    PYTHONIOENCODING: "utf-8",
    PYTHONUTF8: "1",
    XHAUS_SKIP_CONSOLE_CHAT: process.env.XHAUS_SKIP_CONSOLE_CHAT || "1",
  });
}

let xhausProcess = null;
let xhausStartedAt = null;
let xhausLogs = [];
let xhausLastInput = "";
let xhausExitCode = null;
let xhausExitSignal = null;
let autoWizard = null;
let autoWizardBusy = false;

function presetValueToAgentId(value) {
  const raw = String(value || "").replace(/^custom:/, "");
  const map = {
    default_butler: "main",
    elegant_maid: "elegant_maid",
    Emma: "emma",
    emma: "emma",
    Franziska: "franziska",
    franziska: "franziska",
  };
  return normalizeAgentId(map[raw] || raw || "main");
}

function syncActiveAgentFromLine(line) {
  const match = String(line || "").match(/OpenClaw Agent\s*[:：]\s*([a-zA-Z0-9_-]+)/);
  if (match) {
    setActiveAgent({
      id: match[1],
      label: match[1],
      source: "xhaus_summary",
    });
  }
}

function appendLog(source, chunk) {
  const text = Buffer.isBuffer(chunk) ? chunk.toString("utf8") : String(chunk || "");
  const lines = text.split(/\r?\n/).filter(Boolean);
  for (const line of lines) {
    xhausLogs.push({
      time: new Date().toISOString(),
      source,
      line,
    });
    syncActiveAgentFromLine(line);
  }
  if (xhausLogs.length > LOG_LIMIT) {
    xhausLogs = xhausLogs.slice(-LOG_LIMIT);
  }
  maybeAutoDriveWizard();
}

function isProcessRunning(child) {
  return !!child && child.exitCode === null && child.signalCode === null && !child.killed;
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function inferPrompt(logs) {
  const recent = logs.slice(-24).map((entry) => entry.line);
  for (let index = recent.length - 1; index >= 0; index -= 1) {
    const line = recent[index];
    if (/请输入选项编号|Persona Profile|选择角色|请选择一个 Persona/i.test(line)) {
      return {
        type: "persona",
        label: "XHAUS 正在等待人设编号",
        placeholder: "输入人设编号，例如 1",
      };
    }
    if (/WebSocket\s*地址[:：]?/i.test(line)) {
      return {
        type: "websocket",
        label: "XHAUS 正在等待 WebSocket 地址",
        placeholder: "请填写本机 OpenClaw Gateway，例如 ws://127.0.0.1:18789",
      };
    }
    if (/是否|Y\/n|y\/N|请输入 y|请输入 n/i.test(line)) {
      return {
        type: "confirm",
        label: "XHAUS 正在等待确认",
        placeholder: "输入 y 或 n",
      };
    }
    if (/Agent ID/i.test(line)) {
      return {
        type: "agent_id",
        label: "XHAUS 正在等待 Agent ID",
        placeholder: "输入 OpenClaw Agent ID，例如 emma",
      };
    }
    const agentNameMatch = line.match(/Agent\s*名字\s*(?:\[([^\]]+)\])?\s*[:：]?/i);
    if (agentNameMatch) {
      const defaultValue = agentNameMatch[1] || "";
      return {
        type: "agent_name",
        label: defaultValue
          ? `XHAUS 正在等待 Agent 名字，回车使用默认：${defaultValue}`
          : "XHAUS 正在等待 Agent 名字",
        placeholder: defaultValue ? `留空并点“回车/默认”，或输入自定义 Agent 名字` : "输入 Agent 名字",
        default_value: defaultValue,
        allow_empty: true,
      };
    }
    if (/自定义角色名称|API Key|请输入|地址[:：]?$/i.test(line)) {
      return {
        type: "text",
        label: "XHAUS 正在等待输入",
        placeholder: "输入内容后发送到 main.py",
      };
    }
  }
  return {
    type: "idle",
    label: "等待 XHAUS 输出下一步",
    placeholder: "输入内容后发送到 main.py",
    allow_empty: true,
  };
}

function readPresetLabel(presetDir, name) {
  const metaPath = path.join(presetDir, "preset.meta.json");
  if (fs.existsSync(metaPath)) {
    try {
      const meta = JSON.parse(fs.readFileSync(metaPath, "utf8"));
      if (meta && typeof meta.label === "string" && meta.label.trim()) {
        return meta.label.trim();
      }
    } catch (err) {
      // Fall back to generated label.
    }
  }
  return PRESET_LABELS[name] || name.replace(/_/g, " ");
}

function hasProfileDocument(dir) {
  return PROFILE_DOCS.some((file) => fs.existsSync(path.join(dir, file)));
}

function safeIsDirectory(dir) {
  try {
    return fs.statSync(dir).isDirectory();
  } catch (err) {
    return false;
  }
}

function customProfilesRoot() {
  if (process.env.XHAUS_PROFILES_DIR) {
    return path.resolve(process.env.XHAUS_PROFILES_DIR);
  }
  return path.join(process.env.USERPROFILE || process.env.HOME || "", ".xhaus", "profiles");
}

function normalizeProfileId(value) {
  const raw = String(value || "").trim().toLowerCase();
  const slug = raw
    .replace(/^custom:/, "")
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
  return slug || `butler-${Date.now()}`;
}

function safeCustomProfileDir(profileId) {
  const id = normalizeProfileId(profileId);
  const root = path.resolve(customProfilesRoot());
  const dir = path.resolve(root, id);
  if (!dir.startsWith(root + path.sep)) {
    const error = new Error("invalid_profile_id");
    error.code = "invalid_profile_id";
    throw error;
  }
  return { id, dir };
}

function defaultProfileTemplateDir() {
  return path.join(PRESETS_ROOT, "default_butler");
}

function defaultProfileContent(file) {
  const source = path.join(defaultProfileTemplateDir(), file);
  if (fs.existsSync(source)) {
    return fs.readFileSync(source, "utf8");
  }
  const meta = PROFILE_DOC_META[file] || {};
  return `# ${meta.title || file}\n\n`;
}

function stripCustomProfileGuard(content) {
  return String(content || "")
    .replace(new RegExp(`${CUSTOM_GUARD_START}[\\s\\S]*?${CUSTOM_GUARD_END}\\n*`, "g"), "")
    .trimStart();
}

function customProfileGuard(label, file) {
  const name = String(label || "自定义管家").trim() || "自定义管家";
  if (file === "IDENTITY.md") {
    return `${CUSTOM_GUARD_START}
# 自定义人设身份锚点

当前管家人设名称是「${name}」。你必须以「${name}」作为自己的身份认知与自称来源。
除非用户明确要求角色扮演或切换人设，否则不要自称 Emma、Franziska、默认管家或其他预设人设。
如果下方内容与本身份锚点冲突，以本身份锚点为最高优先级。

${CUSTOM_GUARD_END}

`;
  }
  if (file === "SOUL.md") {
    return `${CUSTOM_GUARD_START}
# 自定义人设风格锚点

你的表达风格、情绪和陪伴方式应服务于「${name}」这个自定义人设。
不要继承 Emma、Franziska 或其他预设角色的固定口吻，除非用户在本文件中明确写入。

${CUSTOM_GUARD_END}

`;
  }
  if (file === "USER.md") {
    return `${CUSTOM_GUARD_START}
# 自定义人设使用约束

当用户选择「${name}」时，你应按这个自定义人设理解用户关系与服务方式。
如果历史记忆或旧 workspace 中出现 Emma 等其他身份，只能把它们视为旧记录，不能当作当前身份。

${CUSTOM_GUARD_END}

`;
  }
  return "";
}

function applyCustomProfileGuard(label, file, content) {
  const guard = customProfileGuard(label, file);
  const body = stripCustomProfileGuard(content).trimEnd();
  return guard ? `${guard}${body}`.trimEnd() : body;
}

function ensureCustomProfileGuard(profileId, label, profileDir) {
  const resolved = safeCustomProfileDir(profileId);
  const dir = profileDir ? path.resolve(profileDir) : resolved.dir;
  if (dir !== resolved.dir) {
    const error = new Error("invalid_profile_dir");
    error.code = "invalid_profile_dir";
    throw error;
  }
  fs.mkdirSync(dir, { recursive: true });
  for (const file of PROFILE_DOCS) {
    const filePath = path.join(dir, file);
    const content = fs.existsSync(filePath) ? fs.readFileSync(filePath, "utf8") : defaultProfileContent(file);
    fs.writeFileSync(filePath, `${applyCustomProfileGuard(label, file, content)}\n`, "utf8");
  }
}

function readProfileDocuments(profileDir) {
  return PROFILE_DOCS.map((file) => {
    const pathName = path.join(profileDir, file);
    const meta = PROFILE_DOC_META[file] || {};
    return {
      file,
      title: meta.title || file,
      tip: meta.tip || "",
      content: fs.existsSync(pathName) ? fs.readFileSync(pathName, "utf8") : defaultProfileContent(file),
    };
  });
}

function writeCustomProfile({ id, label, documents }) {
  const resolved = safeCustomProfileDir(id || label);
  fs.mkdirSync(resolved.dir, { recursive: true });
  const docsByFile = new Map((documents || []).map((doc) => [String(doc.file || ""), String(doc.content || "")]));
  for (const file of PROFILE_DOCS) {
    const content = docsByFile.has(file) ? docsByFile.get(file) : defaultProfileContent(file);
    fs.writeFileSync(path.join(resolved.dir, file), `${applyCustomProfileGuard(label, file, content)}\n`, "utf8");
  }
  fs.writeFileSync(path.join(resolved.dir, "preset.meta.json"), JSON.stringify({
    label: String(label || resolved.id).trim() || resolved.id,
    created_at: new Date().toISOString(),
    source: "wechat_miniprogram",
  }, null, 2), "utf8");
  return { id: resolved.id, dir: resolved.dir };
}

function listPresetChoices() {
  const choices = [];
  if (fs.existsSync(PRESETS_ROOT)) {
    let names = [];
    try {
      names = fs
        .readdirSync(PRESETS_ROOT)
        .filter((name) => {
          const presetDir = path.join(PRESETS_ROOT, name);
          return safeIsDirectory(presetDir) && hasProfileDocument(presetDir);
        })
        .sort((a, b) => {
          const ai = PRESET_PRIORITY.indexOf(a);
          const bi = PRESET_PRIORITY.indexOf(b);
          if (ai !== -1 || bi !== -1) {
            return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
          }
          return a.localeCompare(b);
        });
    } catch (err) {
      names = [];
    }

    for (const name of names) {
      const presetDir = path.join(PRESETS_ROOT, name);
      choices.push({
        index: choices.length + 1,
        value: name,
        label: readPresetLabel(presetDir, name),
        kind: "preset",
      });
    }
  }

  const existingValues = new Set(choices.map((item) => item.value));
  [
    ["default_butler", "默认管家"],
    ["elegant_maid", "优雅女仆"],
    ["Emma", "Emma"],
    ["Franziska", "Franziska"],
  ].forEach(([value, label]) => {
    if (!existingValues.has(value)) {
      choices.push({
        index: choices.length + 1,
        value,
        label,
        kind: "preset",
      });
      existingValues.add(value);
    }
  });

  const customRoot = customProfilesRoot();
  if (customRoot && fs.existsSync(customRoot)) {
    let customNames = [];
    try {
      customNames = fs
        .readdirSync(customRoot)
        .filter((name) => {
          const profileDir = path.join(customRoot, name);
          return safeIsDirectory(profileDir) && hasProfileDocument(profileDir);
        })
        .sort((a, b) => a.localeCompare(b));
    } catch (err) {
      customNames = [];
    }

    for (const name of customNames) {
      const profileDir = path.join(customRoot, name);
      choices.push({
        index: choices.length + 1,
        value: `custom:${name}`,
        label: `${readPresetLabel(profileDir, name)}（我的管家）`,
        kind: "custom_profile",
      });
    }
  }

  choices.push({
    index: choices.length + 1,
    value: "__custom__",
    label: "自定义角色",
    kind: "custom",
  });

  return choices;
}

function runtimeView() {
  const running = isProcessRunning(xhausProcess);
  const activated =
    !running &&
    !!xhausProcess &&
    xhausExitCode === 0 &&
    xhausLogs.some((entry) => /Bridge 已激活|已挂载成功|XHAUS 向导结束/.test(entry.line));
  return {
    status: running ? "running" : activated ? "activated" : xhausProcess ? "exited" : "idle",
    pid: running ? xhausProcess.pid : null,
    exit_code: xhausExitCode,
    exit_signal: xhausExitSignal,
    started_at: xhausStartedAt,
    root: XHAUS_ROOT,
    logs: xhausLogs.slice(-80),
    prompt: inferPrompt(xhausLogs),
    active_agent: getActiveAgent(),
    input_enabled: running && !!xhausProcess.stdin && xhausProcess.stdin.writable,
    last_input: xhausLastInput,
  };
}

function writeXhausInput(value) {
  if (!isProcessRunning(xhausProcess) || !xhausProcess.stdin || !xhausProcess.stdin.writable) {
    return false;
  }
  const text = String(value ?? "").trim();
  xhausLastInput = text || "<ENTER>";
  appendLog("stdin", text ? `> ${text}` : "> <ENTER>");
  xhausProcess.stdin.write(`${text}\n`, "utf8");
  return true;
}

function maybeAutoDriveWizard() {
  if (!autoWizard || autoWizardBusy || !isProcessRunning(xhausProcess)) {
    return;
  }
  autoWizardBusy = true;
  try {
    const prompt = inferPrompt(xhausLogs);
    if (prompt.type === "websocket" && !autoWizard.sent.websocket) {
      autoWizard.sent.websocket = true;
      writeXhausInput(autoWizard.websocketUrl);
      return;
    }
    if (prompt.type === "persona" && !autoWizard.sent.persona) {
      autoWizard.sent.persona = true;
      writeXhausInput(String(autoWizard.choice.index));
      setActiveAgentFromChoice(autoWizard.choice);
      return;
    }
    if ((prompt.type === "agent_name" || prompt.type === "agent_id") && !autoWizard.sent.agentName) {
      autoWizard.sent.agentName = true;
      writeXhausInput(autoWizard.agentId);
      return;
    }
    if (/Bridge 已激活|已挂载成功|XHAUS 向导结束|已连接/.test(xhausLogs.map((entry) => entry.line).slice(-12).join("\n"))) {
      autoWizard.done = true;
    }
  } finally {
    autoWizardBusy = false;
  }
}

function killXhausProcess() {
  return new Promise((resolve) => {
    if (!isProcessRunning(xhausProcess)) {
      resolve();
      return;
    }
    const child = xhausProcess;
    const timer = setTimeout(() => resolve(), 1600);
    child.once("close", () => {
      clearTimeout(timer);
      resolve();
    });
    appendLog("system", "restart requested");
    child.kill();
  });
}

async function spawnXhausProcess(env = {}) {
  if (!fs.existsSync(path.join(XHAUS_ROOT, "main.py"))) {
    const error = new Error("xhaus_main_not_found");
    error.code = "xhaus_main_not_found";
    throw error;
  }

  xhausLogs = [];
  xhausLastInput = "";
  xhausExitCode = null;
  xhausExitSignal = null;

  try {
    const satellite = await satelliteService.ensureSatelliteInstalled();
    appendLog(
      "system",
      satellite.ok
        ? "Satellite auto-load ready"
        : `Satellite auto-load warning: ${satellite.state?.last_message || "install_failed"}`,
    );
  } catch (err) {
    appendLog("system", `Satellite auto-load warning: ${err && err.message ? err.message : err}`);
  }

  setActiveAgent({
    id: "main",
    label: "默认管家",
    source: "default",
  });
  xhausStartedAt = new Date().toISOString();
  xhausProcess = spawn(PYTHON_BIN, ["main.py"], {
    cwd: XHAUS_ROOT,
    env: pythonEnv(env),
    shell: false,
    windowsHide: true,
    stdio: ["pipe", "pipe", "pipe"],
  });

  appendLog("system", `started ${PYTHON_BIN} main.py`);
  xhausProcess.stdout.on("data", (chunk) => appendLog("stdout", chunk));
  xhausProcess.stderr.on("data", (chunk) => appendLog("stderr", chunk));
  xhausProcess.on("error", (err) => appendLog("error", err.message));
  xhausProcess.on("close", (code, signal) => {
    xhausExitCode = code;
    xhausExitSignal = signal || "";
    appendLog("system", `exited code=${code} signal=${signal || ""}`);
  });

  return runtimeView();
}

async function driveXhausWizard({ websocketUrl, personaChoice, timeoutMs = 36000 }) {
  const start = Date.now();

  while (Date.now() - start < timeoutMs) {
    if (!isProcessRunning(xhausProcess)) {
      return runtimeView();
    }
    maybeAutoDriveWizard();
    if (
      autoWizard &&
      autoWizard.sent.websocket &&
      autoWizard.sent.persona &&
      xhausLogs.some((entry) => /Bridge 已激活|已挂载成功|XHAUS 向导结束|已连接/.test(entry.line))
    ) {
      return runtimeView();
    }
    await wait(350);
  }

  return runtimeView();
}

function runCommand(command, args, options = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: options.cwd || XHAUS_ROOT,
      env: pythonEnv(options.env || {}),
      shell: false,
      windowsHide: true,
    });

    let stdout = "";
    let stderr = "";
    let finished = false;
    const timeoutMs = options.timeoutMs || 120000;
    const timer = setTimeout(() => {
      if (!finished) {
        child.kill();
        stderr += `\nCommand timed out after ${timeoutMs}ms`;
      }
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", (err) => {
      finished = true;
      clearTimeout(timer);
      resolve({
        ok: false,
        code: -1,
        stdout,
        stderr: stderr || err.message,
      });
    });
    child.on("close", (code) => {
      finished = true;
      clearTimeout(timer);
      resolve({
        ok: code === 0,
        code,
        stdout,
        stderr,
      });
    });
  });
}

async function restartGatewayForSkillChange() {
  return runCommand(
    PYTHON_BIN,
    [
      "-c",
      "from xhaus.core.openclaw_agent import restart_openclaw_gateway\nok,msg=restart_openclaw_gateway()\nprint(msg)\nraise SystemExit(0 if ok else 1)",
    ],
    { timeoutMs: 140000 },
  );
}

async function provisionCustomProfileAgent(profileId, label, profileDir) {
  const code = [
    "import json, sys",
    "from pathlib import Path",
    "from xhaus.core.openclaw_agent import provision_agent_for_profile",
    "profile_id, label, profile_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])",
    "result = provision_agent_for_profile(profile_name=label, profile_dir=profile_dir, mode='create', agent_id=profile_id, restart_gateway=True)",
    "print(json.dumps({",
    "  'ok': result.ok,",
    "  'agent_id': result.agent_id,",
    "  'workspace': str(result.workspace) if result.workspace else '',",
    "  'created': result.created,",
    "  'message': result.message,",
    "  'errors': result.errors,",
    "  'warnings': result.warnings,",
    "}, ensure_ascii=False))",
    "raise SystemExit(0 if result.ok else 1)",
  ].join("\n");
  const result = await runCommand(PYTHON_BIN, ["-c", code, profileId, label, profileDir], { timeoutMs: 240000 });
  const lines = String(result.stdout || "").trim().split(/\r?\n/).filter(Boolean);
  let summary = null;
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    try {
      summary = JSON.parse(lines[index]);
      break;
    } catch (err) {
      // Keep scanning for the JSON summary line.
    }
  }
  return Object.assign({}, result, {
    summary,
    ok: result.ok && (!summary || summary.ok !== false),
  });
}

function sanitizeTitle(raw) {
  const fallback = "self-cognition";
  const title = String(raw || fallback).trim() || fallback;
  return title
    .replace(/[\\/:*?"<>|]/g, "-")
    .replace(/\s+/g, "-")
    .slice(0, 60);
}

function displayTitle(raw) {
  return String(raw || "self-cognition").trim() || "self-cognition";
}

function selfCognitionDir() {
  return path.join(XHAUS_ROOT, "runtime", "self_cognition");
}

function resolveSelfCognitionFile(rawName) {
  const name = path.basename(String(rawName || ""));
  if (!name || !name.endsWith(".md")) {
    const error = new Error("invalid_document_name");
    error.code = "invalid_document_name";
    throw error;
  }
  const dir = path.resolve(selfCognitionDir());
  const file = path.resolve(dir, name);
  if (!file.startsWith(dir + path.sep)) {
    const error = new Error("invalid_document_name");
    error.code = "invalid_document_name";
    throw error;
  }
  return { name, file };
}

function userHomeDir() {
  return process.env.USERPROFILE || process.env.HOME || os.homedir();
}

function userSkillsRoot() {
  if (process.env.XHAUS_SKILLS_DIR) {
    return path.resolve(process.env.XHAUS_SKILLS_DIR);
  }
  return path.join(userHomeDir(), ".xhaus", "skills");
}

function openClawRoot() {
  return path.join(userHomeDir(), ".openclaw");
}

function resolveOpenClawWorkspaceForAgent(agentId) {
  const id = normalizeAgentId(agentId);
  const root = path.resolve(openClawRoot());
  const workspaceName = id === "main" ? "workspace" : `workspace-${id}`;
  const workspace = path.resolve(root, workspaceName);
  if (!workspace.startsWith(root + path.sep)) {
    const error = new Error("invalid_agent_workspace");
    error.code = "invalid_agent_workspace";
    throw error;
  }
  return workspace;
}

function isSafeSkillName(name) {
  return /^[a-zA-Z0-9._-]+$/.test(name) && name !== "." && name !== "..";
}

function resolveSkillDir(name) {
  const skillName = String(name || "").trim();
  if (!isSafeSkillName(skillName)) {
    const error = new Error("invalid_skill_name");
    error.code = "invalid_skill_name";
    throw error;
  }
  const root = path.resolve(userSkillsRoot());
  const dir = path.resolve(root, skillName);
  if (dir !== root && dir.startsWith(root + path.sep)) {
    return dir;
  }
  const error = new Error("invalid_skill_name");
  error.code = "invalid_skill_name";
  throw error;
}

function listOpenClawWorkspaces() {
  const root = openClawRoot();
  if (!fs.existsSync(root)) {
    return [];
  }
  return fs
    .readdirSync(root)
    .filter((name) => name === "workspace" || name.startsWith("workspace-"))
    .map((name) => path.join(root, name))
    .filter((dir) => {
      try {
        return fs.statSync(dir).isDirectory();
      } catch (err) {
        return false;
      }
    });
}

function copyDirRecursive(source, target) {
  fs.mkdirSync(target, { recursive: true });
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    const sourcePath = path.join(source, entry.name);
    const targetPath = path.join(target, entry.name);
    if (entry.isDirectory()) {
      copyDirRecursive(sourcePath, targetPath);
    } else if (entry.isFile()) {
      fs.copyFileSync(sourcePath, targetPath);
    }
  }
}

function syncSkillToWorkspaces(skillName) {
  const sourceDir = resolveSkillDir(skillName);
  const warnings = [];
  for (const workspace of listOpenClawWorkspaces()) {
    const targetDir = path.join(workspace, "skills", skillName);
    try {
      fs.mkdirSync(path.dirname(targetDir), { recursive: true });
      let stat = null;
      try {
        stat = fs.lstatSync(targetDir);
      } catch (err) {
        stat = null;
      }
      if (stat && stat.isSymbolicLink()) {
        continue;
      }
      copyDirRecursive(sourceDir, targetDir);
    } catch (err) {
      warnings.push(`${workspace}: ${err.message}`);
    }
  }
  return warnings;
}

function removeSkillFromWorkspaces(skillName) {
  const warnings = [];
  for (const workspace of listOpenClawWorkspaces()) {
    const targetDir = path.join(workspace, "skills", skillName);
    try {
      fs.rmSync(targetDir, { recursive: true, force: true });
    } catch (err) {
      warnings.push(`${workspace}: ${err.message}`);
    }
  }
  return warnings;
}

function skillInfo(name) {
  const dir = resolveSkillDir(name);
  const file = path.join(dir, "SKILL.md");
  const stat = fs.statSync(file);
  return {
    name,
    path: dir,
    updated_at: stat.mtime.toISOString(),
    size: stat.size,
  };
}

router.post("/xhaus/activate", async (req, res) => {
  if (isProcessRunning(xhausProcess)) {
    return sendOk(res, runtimeView(), "already_running");
  }

  try {
    await spawnXhausProcess(req.body && req.body.env ? req.body.env : {});
  } catch (err) {
    if (err && err.code === "xhaus_main_not_found") {
      return sendError(res, 50010, "xhaus_main_not_found", 500, { root: XHAUS_ROOT });
    }
    return sendError(res, 50011, "xhaus_activate_failed", 500, { detail: err.message });
  }

  return sendOk(res, runtimeView(), "started");
});

router.post("/xhaus/switch-persona", async (req, res) => {
  const choices = listPresetChoices().filter((item) => item.kind !== "custom");
  if (!choices.length) {
    return sendError(res, 50012, "xhaus_persona_not_found", 500);
  }

  const requested = Number(req.body?.persona_index || req.body?.choice || 0);
  const choice = choices.find((item) => item.index === requested) ||
    choices[Math.floor(Math.random() * choices.length)] ||
    choices[0];
  const websocketUrl = String(req.body?.websocket_url || XHAUS_DEFAULT_WEBSOCKET || "ws://127.0.0.1:18789").trim();
  setRuntimeGatewayUrl(websocketUrl);
  const agentId = presetValueToAgentId(choice.value);

  try {
    let provision = null;
    if (choice.kind === "custom_profile") {
      const profileName = String(choice.value || "").replace(/^custom:/, "");
      const resolved = safeCustomProfileDir(profileName);
      const profileLabel = readPresetLabel(resolved.dir, resolved.id);
      ensureCustomProfileGuard(resolved.id, profileLabel, resolved.dir);
      provision = await provisionCustomProfileAgent(agentId, profileLabel, resolved.dir);
      if (!provision.ok) {
        return sendError(res, 50014, "custom_profile_agent_sync_failed", 500, {
          provision,
          selected: Object.assign({}, choice, { agent_id: agentId }),
        });
      }
    }
    await killXhausProcess();
    autoWizard = {
      websocketUrl,
      choice,
      agentId,
      sent: {
        websocket: false,
        persona: false,
        agentName: false,
      },
      done: false,
      startedAt: Date.now(),
    };
    setActiveAgent({
      id: agentId,
      label: choice.label,
      value: choice.value,
      source: "mini_program_choice",
    });
    await spawnXhausProcess(req.body && req.body.env ? req.body.env : {});
    const view = await driveXhausWizard({
      websocketUrl,
      personaChoice: choice.index,
      timeoutMs: Number(req.body?.wait_ms || 12000),
    });
    return sendOk(res, {
      runtime: view,
      selected: Object.assign({}, choice, { agent_id: agentId }),
      websocket_url: websocketUrl,
      provision,
    }, "persona_switched");
  } catch (err) {
    if (err && err.code === "xhaus_main_not_found") {
      return sendError(res, 50010, "xhaus_main_not_found", 500, { root: XHAUS_ROOT });
    }
    return sendError(res, 50013, "xhaus_persona_switch_failed", 500, { detail: err.message, runtime: runtimeView() });
  }
});

router.get("/xhaus/runtime", (req, res) => {
  return sendOk(res, runtimeView());
});

router.post("/xhaus/stop", (req, res) => {
  if (!isProcessRunning(xhausProcess)) {
    return sendOk(res, runtimeView(), "not_running");
  }
  appendLog("system", "stop requested");
  xhausProcess.kill();
  return sendOk(res, runtimeView(), "stopping");
});

router.get("/xhaus/presets", (req, res) => {
  return sendOk(res, { choices: listPresetChoices() });
});

router.get("/xhaus/custom-profiles/template", (req, res) => {
  return sendOk(res, {
    documents: readProfileDocuments(defaultProfileTemplateDir()),
  });
});

router.get("/xhaus/custom-profiles/:id", (req, res) => {
  let resolved;
  try {
    resolved = safeCustomProfileDir(req.params.id);
  } catch (err) {
    return sendError(res, 40050, "invalid_profile_id", 400);
  }
  if (!fs.existsSync(resolved.dir)) {
    return sendError(res, 40450, "custom_profile_not_found", 404);
  }
  return sendOk(res, {
    id: resolved.id,
    label: readPresetLabel(resolved.dir, resolved.id),
    documents: readProfileDocuments(resolved.dir),
  });
});

router.post("/xhaus/custom-profiles", async (req, res) => {
  const label = String(req.body?.label || req.body?.name || "").trim();
  if (!label) {
    return sendError(res, 40051, "missing_profile_name", 400);
  }

  const existingIds = new Set(
    listPresetChoices().map((choice) => normalizeAgentId(String(choice.value || "").replace(/^custom:/, ""))),
  );
  let id = normalizeProfileId(req.body?.id || label);
  let suffix = 2;
  while (existingIds.has(id) || fs.existsSync(path.join(customProfilesRoot(), id))) {
    id = `${normalizeProfileId(req.body?.id || label)}-${suffix}`;
    suffix += 1;
  }

  const saved = writeCustomProfile({
    id,
    label,
    documents: req.body?.documents || [],
  });
  ensureCustomProfileGuard(saved.id, label, saved.dir);
  const choices = listPresetChoices();
  const choice = choices.find((item) => item.value === `custom:${saved.id}`);
  const provision = await provisionCustomProfileAgent(saved.id, label, saved.dir);
  return sendOk(res, {
    id: saved.id,
    label,
    path: saved.dir,
    choice,
    provision,
  }, "custom_profile_saved");
});

router.delete("/xhaus/custom-profiles/:id", async (req, res) => {
  let resolved;
  try {
    resolved = safeCustomProfileDir(req.params.id);
  } catch (err) {
    return sendError(res, 40050, "invalid_profile_id", 400);
  }

  const existed = fs.existsSync(resolved.dir);
  if (existed) {
    fs.rmSync(resolved.dir, { recursive: true, force: true });
  }

  const workspace = resolveOpenClawWorkspaceForAgent(resolved.id);
  const workspaceExisted = fs.existsSync(workspace);
  if (workspaceExisted) {
    fs.rmSync(workspace, { recursive: true, force: true });
  }

  const active = getActiveAgent();
  if (active && normalizeAgentId(active.id) === resolved.id) {
    setActiveAgent({
      id: "main",
      label: "默认管家",
      value: "default_butler",
      source: "custom_profile_deleted",
    });
  }

  let gateway = null;
  if (req.body?.restart_gateway !== false) {
    gateway = await restartGatewayForSkillChange();
  }

  return sendOk(res, {
    id: resolved.id,
    deleted: existed,
    workspace_deleted: workspaceExisted,
    gateway,
  }, "custom_profile_deleted");
});

router.post("/xhaus/input", (req, res) => {
  if (!isProcessRunning(xhausProcess) || !xhausProcess.stdin || !xhausProcess.stdin.writable) {
    return sendError(res, 40910, "xhaus_process_not_waiting_for_input", 409, runtimeView());
  }

  const prompt = inferPrompt(xhausLogs);
  const value = String(req.body?.value ?? req.body?.input ?? "").trim();
  const sendEmpty = req.body?.send_empty === true || req.body?.allow_empty === true || prompt.allow_empty === true;
  if (!value && !sendEmpty) {
    return sendError(res, 40040, "missing_xhaus_input", 400, runtimeView());
  }

  if (prompt.type === "persona" && /^\d+$/.test(value)) {
    const choice = listPresetChoices().find((item) => item.index === Number(value));
    if (choice) {
      setActiveAgentFromChoice(choice);
    }
  } else if ((prompt.type === "agent_id" || prompt.type === "agent_name") && (value || prompt.default_value)) {
    const agentName = value || prompt.default_value;
    setActiveAgent({
      id: normalizeAgentId(agentName),
      label: agentName,
      source: "xhaus_input",
    });
  }
  writeXhausInput(value);
  return sendOk(res, runtimeView(), "xhaus_input_sent");
});

router.post("/xhaus/web-session", async (req, res) => {
  const userId = `web_${crypto.randomUUID()}`;
  const sessionId = `web_${crypto.randomUUID()}`;
  const session = await sessionService.createSessionWithId({
    userId,
    sessionId,
    openid: `web:${userId}`,
  });
  const token = signToken({ userId: session.userId, sessionId: session.sessionId });

  return sendOk(res, {
    user_id: session.userId,
    session_id: session.sessionId,
    token,
    expires_in: TOKEN_TTL_SECONDS,
  });
});

router.post("/xhaus/skills/install", async (req, res) => {
  const rawSourcePath = String(req.body?.source_path || req.body?.sourcePath || "").trim();
  if (!rawSourcePath) {
    return sendError(res, 40020, "missing_skill_source_path", 400);
  }
  const sourcePath = path.isAbsolute(rawSourcePath)
    ? rawSourcePath
    : path.resolve(WORKSPACE_ROOT, rawSourcePath);

  const args = ["install_skill.py", sourcePath];
  if (req.body?.force) {
    args.push("--force");
  }

  const result = await runCommand(PYTHON_BIN, args, { timeoutMs: 180000 });
  if (!result.ok) {
    return sendError(res, 50020, "skill_install_failed", 500, result);
  }
  return sendOk(res, result, "skill_installed");
});

router.get("/xhaus/skills", (req, res) => {
  const root = userSkillsRoot();
  if (!fs.existsSync(root)) {
    return sendOk(res, { skills: [] });
  }

  const skills = fs
    .readdirSync(root)
    .filter((name) => {
      if (!isSafeSkillName(name)) {
        return false;
      }
      const dir = path.join(root, name);
      const file = path.join(dir, "SKILL.md");
      try {
        return fs.statSync(dir).isDirectory() && fs.statSync(file).isFile();
      } catch (err) {
        return false;
      }
    })
    .map((name) => skillInfo(name))
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));

  return sendOk(res, { skills });
});

router.get("/xhaus/skills/:name", (req, res) => {
  let dir;
  try {
    dir = resolveSkillDir(req.params.name);
  } catch (err) {
    return sendError(res, 40021, "invalid_skill_name", 400);
  }

  const name = String(req.params.name || "").trim();
  const file = path.join(dir, "SKILL.md");
  if (!fs.existsSync(file)) {
    return sendError(res, 40421, "skill_not_found", 404);
  }

  const stat = fs.statSync(file);
  return sendOk(res, {
    name,
    path: dir,
    updated_at: stat.mtime.toISOString(),
    size: stat.size,
    content: fs.readFileSync(file, "utf8"),
  });
});

router.put("/xhaus/skills/:name", async (req, res) => {
  let dir;
  try {
    dir = resolveSkillDir(req.params.name);
  } catch (err) {
    return sendError(res, 40021, "invalid_skill_name", 400);
  }

  const content = String(req.body?.content || "").trimEnd();
  if (!content.trim()) {
    return sendError(res, 40022, "missing_skill_content", 400);
  }

  const name = String(req.params.name || "").trim();
  const file = path.join(dir, "SKILL.md");
  if (!fs.existsSync(file)) {
    return sendError(res, 40421, "skill_not_found", 404);
  }

  fs.writeFileSync(file, `${content}\n`, "utf8");
  const warnings = syncSkillToWorkspaces(name);
  let gateway = null;
  if (req.body?.restart_gateway !== false) {
    gateway = await restartGatewayForSkillChange();
  }

  return sendOk(res, {
    skill: skillInfo(name),
    warnings,
    gateway,
  }, "skill_saved");
});

router.delete("/xhaus/skills/:name", async (req, res) => {
  let dir;
  try {
    dir = resolveSkillDir(req.params.name);
  } catch (err) {
    return sendError(res, 40021, "invalid_skill_name", 400);
  }

  const name = String(req.params.name || "").trim();
  const existed = fs.existsSync(dir);
  if (existed) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
  const warnings = removeSkillFromWorkspaces(name);
  let gateway = null;
  if (req.body?.restart_gateway !== false) {
    gateway = await restartGatewayForSkillChange();
  }

  return sendOk(res, {
    name,
    deleted: existed,
    warnings,
    gateway,
  }, "skill_deleted");
});

router.get("/xhaus/satellite/status", (req, res) => {
  return sendOk(res, satelliteService.getStatus());
});

router.post("/xhaus/satellite/run", async (req, res) => {
  if (req.body?.async === true) {
    satelliteService
      .runNow({
        force: req.body?.force !== false,
        reason: "manual",
      })
      .catch((err) => console.error("satellite_async_run_failed", err));
    return sendOk(res, satelliteService.getStatus(), "satellite_run_started");
  }

  const state = await satelliteService.runNow({
    force: req.body?.force !== false,
    reason: "manual",
  });
  return sendOk(res, state, "satellite_run_finished");
});

router.get("/xhaus/self-cognition", (req, res) => {
  const dir = selfCognitionDir();
  if (!fs.existsSync(dir)) {
    return sendOk(res, { documents: [] });
  }

  const documents = fs
    .readdirSync(dir)
    .filter((name) => name.endsWith(".md"))
    .map((name) => {
      const file = path.join(dir, name);
      const stat = fs.statSync(file);
      return {
        name,
        path: file,
        updated_at: stat.mtime.toISOString(),
        size: stat.size,
      };
    })
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));

  return sendOk(res, { documents });
});

router.get("/xhaus/self-cognition/:name", (req, res) => {
  let resolved;
  try {
    resolved = resolveSelfCognitionFile(req.params.name);
  } catch (err) {
    return sendError(res, 40031, "invalid_document_name", 400);
  }
  if (!fs.existsSync(resolved.file)) {
    return sendError(res, 40431, "document_not_found", 404);
  }
  const stat = fs.statSync(resolved.file);
  return sendOk(res, {
    name: resolved.name,
    updated_at: stat.mtime.toISOString(),
    size: stat.size,
    content: fs.readFileSync(resolved.file, "utf8"),
  });
});

router.put("/xhaus/self-cognition/:name", (req, res) => {
  let resolved;
  try {
    resolved = resolveSelfCognitionFile(req.params.name);
  } catch (err) {
    return sendError(res, 40031, "invalid_document_name", 400);
  }

  const content = String(req.body?.content || "").trimEnd();
  if (!content.trim()) {
    return sendError(res, 40032, "missing_document_content", 400);
  }
  if (!fs.existsSync(resolved.file)) {
    return sendError(res, 40431, "document_not_found", 404);
  }

  fs.writeFileSync(resolved.file, `${content}\n`, "utf8");
  const stat = fs.statSync(resolved.file);
  return sendOk(res, {
    name: resolved.name,
    updated_at: stat.mtime.toISOString(),
    size: stat.size,
  }, "self_cognition_updated");
});

router.delete("/xhaus/self-cognition/:name", (req, res) => {
  let resolved;
  try {
    resolved = resolveSelfCognitionFile(req.params.name);
  } catch (err) {
    return sendError(res, 40031, "invalid_document_name", 400);
  }

  const existed = fs.existsSync(resolved.file);
  if (existed) {
    fs.rmSync(resolved.file, { force: true });
  }
  return sendOk(res, {
    name: resolved.name,
    deleted: existed,
  }, "self_cognition_deleted");
});

router.post("/xhaus/self-cognition", (req, res) => {
  const title = displayTitle(req.body?.title);
  const fileTitle = sanitizeTitle(title);
  const content = String(req.body?.content || "").trim();
  if (!content) {
    return sendError(res, 40030, "missing_document_content", 400);
  }

  const dir = selfCognitionDir();
  fs.mkdirSync(dir, { recursive: true });

  const now = new Date();
  const stamp = now.toISOString().replace("T", " ").replace(/\.\d{3}Z$/, " UTC");
  const fileName = `${fileTitle}.md`;
  const filePath = path.join(dir, fileName);
  const existed = fs.existsSync(filePath);
  const markdown = existed
    ? `\n\n## ${stamp}\n\n${content}\n`
    : `# ${title}\n\n## ${stamp}\n\n${content}\n`;

  if (existed) {
    fs.appendFileSync(filePath, markdown, "utf8");
  } else {
    fs.writeFileSync(filePath, markdown, "utf8");
  }

  return sendOk(res, {
    name: fileName,
    path: filePath,
    mode: existed ? "appended" : "created",
  }, "self_cognition_saved");
});

module.exports = router;
