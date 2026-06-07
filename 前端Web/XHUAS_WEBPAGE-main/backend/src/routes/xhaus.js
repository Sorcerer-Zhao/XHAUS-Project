const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const express = require("express");
const sessionService = require("../services/sessionService");
const satelliteService = require("../services/satelliteService");
const { XHAUS_ROOT } = require("../services/projectPaths");
const {
  agentFromChoice,
  getActiveAgent,
  normalizeAgentId,
  setActiveAgent,
  setActiveAgentFromChoice,
} = require("../services/xhausSelection");
const { signToken, TOKEN_TTL_SECONDS } = require("../utils/token");
const { sendOk, sendError } = require("../utils/response");
const { resolvePythonBin } = require("../utils/python");

const router = express.Router();

const PYTHON_BIN = resolvePythonBin();
const LOG_LIMIT = 180;
const PRESETS_ROOT = path.join(XHAUS_ROOT, "xhaus", "templates", "profiles", "presets");
const PRESET_LABELS = {
  default_butler: "默认管家",
  elegant_maid: "优雅女仆",
};
const PRESET_PRIORITY = ["default_butler", "elegant_maid"];
const PROFILE_DOCS = ["IDENTITY.md", "SOUL.md", "AGENTS.md", "USER.md"];

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
let pendingActiveAgent = null;

function syncActiveAgentFromLine(line) {
  const text = String(line || "");
  const match =
    text.match(/OpenClaw\s+Agent\s*[:：]\s*([a-zA-Z0-9_-]+)/) ||
    text.match(/^\s*Agent\s*[:：]\s*([a-zA-Z0-9_-]+)/) ||
    text.match(/session:\s*agent:([a-zA-Z0-9_-]+)/);
  if (match) {
    setActiveAgent({
      id: match[1],
      label: pendingActiveAgent && normalizeAgentId(pendingActiveAgent.id) === normalizeAgentId(match[1])
        ? pendingActiveAgent.label
        : match[1],
      source: "xhaus_summary",
    });
    pendingActiveAgent = null;
    return;
  }

  if (pendingActiveAgent && /Bridge 已激活|已挂载成功|XHAUS 向导结束|已连接/.test(text)) {
    setActiveAgent(pendingActiveAgent);
    pendingActiveAgent = null;
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
}

function isProcessRunning(child) {
  return !!child && child.exitCode === null && child.signalCode === null && !child.killed;
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
    if (/自定义角色名称/i.test(line)) {
      return {
        type: "custom_profile_name",
        label: "XHAUS 正在等待自定义角色名称",
        placeholder: "只能输入字母、数字、下划线或连字符，例如 wang-tianmu",
      };
    }
    if (/API Key|请输入|地址[:：]?$/i.test(line)) {
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

function customProfilesRoot() {
  if (process.env.XHAUS_PROFILES_DIR) {
    return path.resolve(process.env.XHAUS_PROFILES_DIR);
  }
  return path.join(process.env.USERPROFILE || process.env.HOME || "", ".xhaus", "profiles");
}

function safeCustomProfileDir(profileId) {
  const id = normalizeAgentId(profileId);
  const root = path.resolve(customProfilesRoot());
  const dir = path.resolve(root, id);
  if (!id || dir === root || !dir.startsWith(root + path.sep)) {
    const error = new Error("invalid_profile_id");
    error.code = "invalid_profile_id";
    throw error;
  }
  return { id, dir };
}

function openClawRoot() {
  return path.join(process.env.USERPROFILE || process.env.HOME || "", ".openclaw");
}

function safeOpenClawWorkspace(agentId) {
  const id = normalizeAgentId(agentId);
  const root = path.resolve(openClawRoot());
  const workspace = path.resolve(root, id === "main" ? "workspace" : `workspace-${id}`);
  if (!id || workspace === root || !workspace.startsWith(root + path.sep)) {
    const error = new Error("invalid_agent_workspace");
    error.code = "invalid_agent_workspace";
    throw error;
  }
  return workspace;
}

function listPresetChoices() {
  const choices = [];
  if (fs.existsSync(PRESETS_ROOT)) {
    const names = fs
      .readdirSync(PRESETS_ROOT)
      .filter((name) => {
        const presetDir = path.join(PRESETS_ROOT, name);
        return fs.statSync(presetDir).isDirectory() && hasProfileDocument(presetDir);
      })
      .sort((a, b) => {
        const ai = PRESET_PRIORITY.indexOf(a);
        const bi = PRESET_PRIORITY.indexOf(b);
        if (ai !== -1 || bi !== -1) {
          return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
        }
        return a.localeCompare(b);
      });

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

  const customRoot = customProfilesRoot();
  if (customRoot && fs.existsSync(customRoot)) {
    const customNames = fs
      .readdirSync(customRoot)
      .filter((name) => {
        const profileDir = path.join(customRoot, name);
        return fs.statSync(profileDir).isDirectory() && hasProfileDocument(profileDir);
      })
      .sort((a, b) => a.localeCompare(b));

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
    pending_agent: pendingActiveAgent,
    input_enabled: running && !!xhausProcess.stdin && xhausProcess.stdin.writable,
    last_input: xhausLastInput,
  };
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
  return process.env.USERPROFILE || process.env.HOME || "";
}

function userSkillsRoot() {
  if (process.env.XHAUS_SKILLS_DIR) {
    return path.resolve(process.env.XHAUS_SKILLS_DIR);
  }
  return path.join(userHomeDir(), ".xhaus", "skills");
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
  if (!fs.existsSync(path.join(XHAUS_ROOT, "main.py"))) {
    return sendError(res, 50010, "xhaus_main_not_found", 500, { root: XHAUS_ROOT });
  }

  if (isProcessRunning(xhausProcess)) {
    return sendOk(res, runtimeView(), "already_running");
  }

  xhausLogs = [];
  xhausLastInput = "";
  xhausExitCode = null;
  xhausExitSignal = null;
  pendingActiveAgent = null;

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
    env: pythonEnv(req.body && req.body.env ? req.body.env : {}),
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

  return sendOk(res, runtimeView(), "started");
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

router.delete("/xhaus/custom-profiles/:id", (req, res) => {
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

  let workspaceDeleted = false;
  let workspaceWarning = "";
  try {
    const workspace = safeOpenClawWorkspace(resolved.id);
    workspaceDeleted = fs.existsSync(workspace);
    if (workspaceDeleted) {
      fs.rmSync(workspace, { recursive: true, force: true });
    }
  } catch (err) {
    workspaceWarning = err && err.message ? err.message : String(err);
  }

  const active = getActiveAgent();
  if (active && normalizeAgentId(active.id) === resolved.id) {
    setActiveAgent({
      id: "main",
      label: "默认管家",
      value: "default_butler",
      source: "custom_profile_deleted",
    });
    pendingActiveAgent = null;
  }

  return sendOk(res, {
    id: resolved.id,
    deleted: existed,
    workspace_deleted: workspaceDeleted,
    workspace_warning: workspaceWarning,
    choices: listPresetChoices(),
    runtime: runtimeView(),
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

  xhausLastInput = value || "<ENTER>";
  if (prompt.type === "persona" && /^\d+$/.test(value)) {
    const choice = listPresetChoices().find((item) => item.index === Number(value));
    if (choice) {
      if (choice.kind === "custom_profile") {
        pendingActiveAgent = agentFromChoice(choice);
      } else {
        setActiveAgentFromChoice(choice);
        pendingActiveAgent = null;
      }
    }
  } else if ((prompt.type === "agent_id" || prompt.type === "agent_name") && (value || prompt.default_value)) {
    const agentName = value || prompt.default_value;
    pendingActiveAgent = {
      id: normalizeAgentId(agentName),
      label: agentName,
      source: "xhaus_input",
    };
  }
  appendLog("stdin", value ? `> ${value}` : "> <ENTER>");
  xhausProcess.stdin.write(`${value}\n`, "utf8");
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
  const sourcePath = String(req.body?.source_path || req.body?.sourcePath || "").trim();
  if (!sourcePath) {
    return sendError(res, 40020, "missing_skill_source_path", 400);
  }

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

router.put("/xhaus/skills/:name", (req, res) => {
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

  return sendOk(res, {
    skill: skillInfo(name),
    warnings,
  }, "skill_saved");
});

router.delete("/xhaus/skills/:name", (req, res) => {
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

  return sendOk(res, {
    name,
    deleted: existed,
    warnings,
  }, "skill_deleted");
});

router.get("/xhaus/satellite/status", (req, res) => {
  return sendOk(res, satelliteService.getStatus());
});

router.post("/xhaus/satellite/run", async (req, res) => {
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
