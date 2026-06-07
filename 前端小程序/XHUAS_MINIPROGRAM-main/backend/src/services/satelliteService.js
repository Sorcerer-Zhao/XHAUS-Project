const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync, spawn } = require("child_process");
const historyArchive = require("./historyArchiveService");

const BACKEND_ROOT = path.resolve(__dirname, "..", "..");
const WORKSPACE_ROOT = path.resolve(BACKEND_ROOT, "..", "..");
const XHAUS_ROOT = process.env.XHAUS_ROOT ? path.resolve(process.env.XHAUS_ROOT) : path.join(WORKSPACE_ROOT, "XHAUS");
const SATELLITE_SOURCE = process.env.SATELLITE_ROOT ? path.resolve(process.env.SATELLITE_ROOT) : path.join(WORKSPACE_ROOT, "Satellite");
const SATELLITE_MAIN = path.join(SATELLITE_SOURCE, "meta_skill", "main_satellite.py");
const RUNTIME_ROOT = path.join(XHAUS_ROOT, "runtime", "satellite");
const STATE_FILE = path.join(RUNTIME_ROOT, "state.json");
const STAGING_DIR = path.join(RUNTIME_ROOT, "staging");
const SELF_COGNITION_DIR = path.join(XHAUS_ROOT, "runtime", "self_cognition");
const REPORT_FILE = path.join(SELF_COGNITION_DIR, "Satellite-自动进化报告.md");
const IDENTITY_TARGET = path.join(SELF_COGNITION_DIR, "Satellite-identity.md");
const PYTHON_BIN = process.env.XHAUS_PYTHON || process.env.PYTHON || "python";
const TWO_WEEKS_HOURS = 14 * 24;
const DEFAULT_INTERVAL_MS = Number(process.env.XHAUS_SATELLITE_INTERVAL_MS || 6 * 60 * 60 * 1000);
const MIN_RECENT_TURNS = Number(process.env.XHAUS_SATELLITE_MIN_TURNS || 3);
const WINDOWS_ENV_NAMES = [
  "DEEPSEEK_API_KEY",
  "SATELLITE_LLM_API_KEY",
  "SATELLITE_LLM_PROVIDER",
  "SATELLITE_LLM_MODEL",
  "SATELLITE_LLM_BASE_URL",
  "OPENAI_API_KEY",
  "OPENCLAW_GATEWAY_TOKEN",
];

let running = false;
let schedulerStarted = false;

function homeDir() {
  return process.env.USERPROFILE || process.env.HOME || os.homedir();
}

function userSkillsRoot() {
  return process.env.XHAUS_SKILLS_DIR || path.join(homeDir(), ".xhaus", "skills");
}

function satelliteInstallDir() {
  return path.join(userSkillsRoot(), "Satellite");
}

function readWindowsEnvironmentValue(name) {
  if (process.platform !== "win32") {
    return "";
  }
  try {
    const script = `[Environment]::GetEnvironmentVariable('${name}', 'User'); [Environment]::GetEnvironmentVariable('${name}', 'Machine')`;
    const output = execFileSync(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-Command", script],
      {
        encoding: "utf8",
        windowsHide: true,
        timeout: 5000,
      },
    );
    return output
      .split(/\r?\n/)
      .map((line) => line.trim())
      .find(Boolean) || "";
  } catch (err) {
    return "";
  }
}

function mergePersistedWindowsEnvironment(env) {
  if (process.platform !== "win32") {
    return env;
  }
  for (const name of WINDOWS_ENV_NAMES) {
    if (!env[name]) {
      const value = readWindowsEnvironmentValue(name);
      if (value) {
        env[name] = value;
      }
    }
  }
  return env;
}

function pythonEnv(extra = {}) {
  const env = Object.assign({}, process.env, extra, {
    PYTHONIOENCODING: "utf-8",
    PYTHONUTF8: "1",
  });
  mergePersistedWindowsEnvironment(env);
  if (!env.SATELLITE_LLM_PROVIDER && env.OPENCLAW_GATEWAY_TOKEN && !env.DEEPSEEK_API_KEY) {
    env.SATELLITE_LLM_PROVIDER = "openclaw";
  }
  return env;
}

function readState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
  } catch (err) {
    return {
      status: "idle",
      last_run_at: null,
      last_success_at: null,
      last_message: "Satellite 尚未自动运行",
      report_path: REPORT_FILE,
      installed: fs.existsSync(path.join(satelliteInstallDir(), "SKILL.md")),
      interval_ms: DEFAULT_INTERVAL_MS,
      retention_days: historyArchive.RETENTION_DAYS,
    };
  }
}

function writeState(patch) {
  fs.mkdirSync(RUNTIME_ROOT, { recursive: true });
  const next = Object.assign({}, readState(), patch, {
    installed: fs.existsSync(path.join(satelliteInstallDir(), "SKILL.md")),
    running,
    interval_ms: DEFAULT_INTERVAL_MS,
    retention_days: historyArchive.RETENTION_DAYS,
    updated_at: new Date().toISOString(),
  });
  fs.writeFileSync(STATE_FILE, JSON.stringify(next, null, 2), "utf8");
  return next;
}

function listSkillNames() {
  const root = userSkillsRoot();
  if (!fs.existsSync(root)) {
    return [];
  }
  return fs
    .readdirSync(root)
    .filter((name) => {
      const dir = path.join(root, name);
      return fs.existsSync(path.join(dir, "SKILL.md"));
    })
    .sort((a, b) => a.localeCompare(b));
}

function runProcess(command, args, options = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: options.cwd || XHAUS_ROOT,
      env: pythonEnv(options.env || {}),
      shell: false,
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";
    let closed = false;
    const timer = setTimeout(() => {
      if (!closed) {
        child.kill();
        stderr += `\nCommand timed out after ${options.timeoutMs || 600000}ms`;
      }
    }, options.timeoutMs || 600000);

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", (err) => {
      closed = true;
      clearTimeout(timer);
      resolve({ ok: false, code: -1, stdout, stderr: stderr || err.message });
    });
    child.on("close", (code) => {
      closed = true;
      clearTimeout(timer);
      resolve({ ok: code === 0, code, stdout, stderr });
    });
    child.stdin.on("error", () => {
      // The child may exit before it needs stdin; this is harmless for auto-confirm.
    });

    if (options.input) {
      child.stdin.write(options.input, "utf8");
    }
    child.stdin.end();
  });
}

async function ensureSatelliteInstalled() {
  if (!fs.existsSync(path.join(SATELLITE_SOURCE, "SKILL.md"))) {
    const state = writeState({
      status: "install_failed",
      last_message: `未找到 Satellite 源目录: ${SATELLITE_SOURCE}`,
    });
    return { ok: false, skipped: false, state };
  }

  if (fs.existsSync(path.join(satelliteInstallDir(), "SKILL.md"))) {
    return { ok: true, skipped: true, state: writeState({ status: readState().status || "idle" }) };
  }

  const result = await runProcess(
    PYTHON_BIN,
    ["install_skill.py", SATELLITE_SOURCE, "--no-restart"],
    { cwd: XHAUS_ROOT, timeoutMs: 180000 },
  );

  const state = writeState({
    status: result.ok ? "installed" : "install_failed",
    last_message: result.ok ? "Satellite 已自动安装到可加载 Skill 目录" : "Satellite 自动安装失败",
    last_install_stdout: result.stdout.slice(-4000),
    last_install_stderr: result.stderr.slice(-4000),
  });
  return { ok: result.ok, skipped: false, result, state };
}

async function relinkAgentSkills() {
  const code = [
    "from xhaus.core.openclaw_agent import list_openclaw_agents",
    "from xhaus.skills.workspace_link import link_skills_into_workspace",
    "for agent in list_openclaw_agents():",
    "    result = link_skills_into_workspace(agent.workspace)",
    "    print(f'{agent.id}: linked={len(result.linked)} warnings={len(result.warnings)} errors={len(result.errors)}')",
  ].join("\n");
  return runProcess(PYTHON_BIN, ["-c", code], { cwd: XHAUS_ROOT, timeoutMs: 120000 });
}

function summarizeOutput(stdout, stderr) {
  const text = `${stdout || ""}\n${stderr || ""}`;
  if (/已挂载并生效/.test(text)) {
    return "Satellite 已运行并挂载生成结果";
  }
  if (/Both skill_generation and identity_update are 'ignore'|nothing actionable|ignored/i.test(text)) {
    return "Satellite 已运行，本轮没有需要沉淀的新模式";
  }
  if (/No valid logs|No log|empty window|no_logs/i.test(text)) {
    return "Satellite 已运行，但近两周暂无足够历史数据";
  }
  return "Satellite 已完成运行";
}

function appendReport({ result, beforeSkills, afterSkills }) {
  const newSkills = afterSkills.filter((name) => !beforeSkills.includes(name));
  const now = new Date().toISOString().replace("T", " ").replace(/\.\d{3}Z$/, " UTC");
  const lines = [
    `\n\n## ${now}`,
    "",
    `状态：${result.ok ? "完成" : "失败"}`,
    `说明：${summarizeOutput(result.stdout, result.stderr)}`,
    `历史窗口：最近 14 天`,
    `记忆目录：${historyArchive.MEMORY_ROOT}`,
    `Skill 目录：${userSkillsRoot()}`,
    "",
  ];

  if (newSkills.length) {
    lines.push("### 新生成的 Skill", "");
    for (const name of newSkills) {
      lines.push(`- ${name}: ${path.join(userSkillsRoot(), name)}`);
    }
    lines.push("");
  } else {
    lines.push("### 新生成的 Skill", "", "- 本次没有新增 Skill；可能只是更新/忽略，或需要更多历史样本。", "");
  }

  lines.push(
    "### 你可以怎么处理",
    "",
    "- 如果满意：无需操作，下次激活 XHAUS 时会继续加载可用 Skill。",
    "- 如果不满意：直接修改上面的 Skill 目录，或修改本文件夹里的 Satellite 认知建议文档。",
    "",
    "### 运行输出摘要",
    "",
    "```text",
    `${(result.stdout || "").slice(-6000)}${result.stderr ? `\n[stderr]\n${result.stderr.slice(-3000)}` : ""}`.trim(),
    "```",
    "",
  );

  fs.mkdirSync(SELF_COGNITION_DIR, { recursive: true });
  if (!fs.existsSync(REPORT_FILE)) {
    fs.writeFileSync(REPORT_FILE, "# Satellite 自动进化报告\n", "utf8");
  }
  fs.appendFileSync(REPORT_FILE, lines.join("\n"), "utf8");
  return { report_path: REPORT_FILE, new_skills: newSkills };
}

function shouldSkipForInterval(force) {
  if (force) {
    return false;
  }
  const state = readState();
  if (!state.last_run_at) {
    return false;
  }
  return Date.now() - new Date(state.last_run_at).getTime() < DEFAULT_INTERVAL_MS;
}

async function runNow({ force = false, reason = "manual" } = {}) {
  if (running) {
    return writeState({ status: "running", last_message: "Satellite 正在运行中" });
  }

  await ensureSatelliteInstalled();
  historyArchive.cleanupOldHistory();

  const recentTurns = historyArchive.countRecentTurns();
  if (!force && recentTurns < MIN_RECENT_TURNS) {
    return writeState({
      status: "waiting_for_history",
      last_message: `已保留近两周历史；当前样本 ${recentTurns} 条，达到 ${MIN_RECENT_TURNS} 条后自动运行 Satellite`,
      recent_turns: recentTurns,
    });
  }

  if (shouldSkipForInterval(force)) {
    return writeState({
      status: "scheduled",
      last_message: "Satellite 未到下一次自动运行时间",
      recent_turns: recentTurns,
    });
  }

  if (!fs.existsSync(SATELLITE_MAIN)) {
    return writeState({
      status: "error",
      last_message: `未找到 Satellite 入口: ${SATELLITE_MAIN}`,
      recent_turns: recentTurns,
    });
  }

  running = true;
  writeState({
    status: "running",
    last_run_at: new Date().toISOString(),
    last_reason: reason,
    last_message: "Satellite 正在读取近两周历史并自动生成建议",
    recent_turns: recentTurns,
  });

  const beforeSkills = listSkillNames();
  const result = await runProcess(
    PYTHON_BIN,
    [
      SATELLITE_MAIN,
      "--hours",
      String(TWO_WEEKS_HOURS),
      "--memory",
      historyArchive.MEMORY_ROOT,
      "--staging",
      STAGING_DIR,
      "--skills-dir",
      userSkillsRoot(),
      "--identity",
      IDENTITY_TARGET,
      "-v",
    ],
    {
      cwd: path.dirname(SATELLITE_MAIN),
      timeoutMs: Number(process.env.XHAUS_SATELLITE_TIMEOUT_MS || 10 * 60 * 1000),
      input: "Y\n",
    },
  );
  const afterSkills = listSkillNames();
  const relink = result.ok ? await relinkAgentSkills() : null;
  const report = result.ok ? appendReport({ result, beforeSkills, afterSkills }) : null;
  running = false;

  return writeState({
    status: result.ok ? "completed" : "error",
    last_success_at: result.ok ? new Date().toISOString() : readState().last_success_at,
    last_message: result.ok ? summarizeOutput(result.stdout, result.stderr) : "Satellite 运行失败，请检查 LLM Key 或 OpenClaw Gateway",
    last_stdout: result.stdout.slice(-4000),
    last_stderr: `${result.stderr || ""}${relink && !relink.ok ? `\n[relink]\n${relink.stderr}` : ""}`.slice(-4000),
    last_relink_stdout: relink ? relink.stdout.slice(-2000) : "",
    last_code: result.code,
    recent_turns: recentTurns,
    report_path: report ? report.report_path : REPORT_FILE,
    new_skills: report ? report.new_skills : [],
  });
}

function maybeRun(reason) {
  setTimeout(() => {
    runNow({ force: false, reason }).catch((err) => {
      running = false;
      writeState({
        status: "error",
        last_message: err && err.message ? err.message : "Satellite 自动运行失败",
      });
    });
  }, 0);
}

function startScheduler() {
  if (schedulerStarted) {
    return;
  }
  schedulerStarted = true;
  ensureSatelliteInstalled().catch((err) => {
    writeState({
      status: "install_failed",
      last_message: err && err.message ? err.message : "Satellite 自动安装失败",
    });
  });
  const first = setTimeout(() => maybeRun("startup"), 30 * 1000);
  if (typeof first.unref === "function") {
    first.unref();
  }
  const timer = setInterval(() => maybeRun("timer"), DEFAULT_INTERVAL_MS);
  if (typeof timer.unref === "function") {
    timer.unref();
  }
}

function getStatus() {
  const state = readState();
  return Object.assign({}, state, {
    running,
    installed: fs.existsSync(path.join(satelliteInstallDir(), "SKILL.md")),
    source: SATELLITE_SOURCE,
    memory_root: historyArchive.MEMORY_ROOT,
    skills_root: userSkillsRoot(),
    report_path: REPORT_FILE,
    recent_turns: historyArchive.countRecentTurns(),
  });
}

module.exports = {
  ensureSatelliteInstalled,
  maybeRun,
  runNow,
  startScheduler,
  getStatus,
};
