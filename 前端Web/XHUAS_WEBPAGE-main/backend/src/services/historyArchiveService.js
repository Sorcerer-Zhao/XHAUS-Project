const fs = require("fs");
const path = require("path");
const { XHAUS_ROOT } = require("./projectPaths");

const MEMORY_ROOT = path.join(XHAUS_ROOT, "runtime", "satellite_memory");
const DREAMING_ROOT = path.join(MEMORY_ROOT, "dreaming", "frontend");
const RETENTION_DAYS = Number(process.env.XHAUS_HISTORY_RETENTION_DAYS || 14);

function todayKey(date = new Date()) {
  return date.toISOString().slice(0, 10);
}

function oneLine(value, limit = 1800) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit);
}

function appendFile(file, content) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.appendFileSync(file, content, "utf8");
}

function ensureDailyHeader(file, title) {
  if (!fs.existsSync(file)) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, `# ${title}\n`, "utf8");
  }
}

function cutoffTime() {
  return Date.now() - RETENTION_DAYS * 24 * 60 * 60 * 1000;
}

function isOldMarkdown(file) {
  if (!file.endsWith(".md")) {
    return false;
  }
  const nameMatch = path.basename(file).match(/^(\d{4}-\d{2}-\d{2})\.md$/);
  if (nameMatch) {
    return new Date(`${nameMatch[1]}T23:59:59.999Z`).getTime() < cutoffTime();
  }
  try {
    return fs.statSync(file).mtimeMs < cutoffTime();
  } catch (err) {
    return false;
  }
}

function walkFiles(root) {
  if (!fs.existsSync(root)) {
    return [];
  }
  const result = [];
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const file = path.join(root, entry.name);
    if (entry.isDirectory()) {
      result.push(...walkFiles(file));
    } else {
      result.push(file);
    }
  }
  return result;
}

function pruneEmptyDirs(root) {
  if (!fs.existsSync(root)) {
    return;
  }
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      pruneEmptyDirs(path.join(root, entry.name));
    }
  }
  if (root !== MEMORY_ROOT && fs.readdirSync(root).length === 0) {
    fs.rmdirSync(root);
  }
}

function cleanupOldHistory() {
  let removed = 0;
  for (const file of walkFiles(MEMORY_ROOT)) {
    if (isOldMarkdown(file)) {
      fs.unlinkSync(file);
      removed += 1;
    }
  }
  pruneEmptyDirs(MEMORY_ROOT);
  return removed;
}

function appendConversation({ userId, sessionId, agent, userMessage, assistantMessage }) {
  const now = new Date();
  const day = todayKey(now);
  const time = now.toISOString().replace(/\.\d{3}Z$/, "Z");
  const user = oneLine(userMessage);
  const assistant = oneLine(assistantMessage);
  if (!user && !assistant) {
    return null;
  }

  const dailyFile = path.join(MEMORY_ROOT, `${day}.md`);
  ensureDailyHeader(dailyFile, `XHAUS conversation memory ${day}`);
  appendFile(
    dailyFile,
    [
      "",
      `## ${time} · ${agent || "main"}`,
      "",
      `User: ${user}`,
      "",
      `Assistant: ${assistant}`,
      "",
    ].join("\n"),
  );

  const dreamingFile = path.join(DREAMING_ROOT, `${day}.md`);
  ensureDailyHeader(dreamingFile, `Frontend candidates ${day}`);
  appendFile(
    dreamingFile,
    [
      "",
      `- Candidate: User: ${user}`,
      "  - confidence: 0.9",
      `  - agent: ${agent || "main"}`,
      `  - session: ${sessionId || ""}`,
      `  - user: ${userId || ""}`,
      `- Candidate: Assistant: ${assistant}`,
      "  - confidence: 0.9",
      "",
    ].join("\n"),
  );

  cleanupOldHistory();
  return { memory_root: MEMORY_ROOT, daily_file: dailyFile, dreaming_file: dreamingFile };
}

function countRecentTurns() {
  let count = 0;
  for (const file of walkFiles(MEMORY_ROOT)) {
    if (!file.endsWith(".md") || isOldMarkdown(file)) {
      continue;
    }
    try {
      const text = fs.readFileSync(file, "utf8");
      count += (text.match(/^- Candidate: User:/gm) || []).length;
      count += (text.match(/^## /gm) || []).length;
    } catch (err) {
      // Ignore unreadable history files.
    }
  }
  return count;
}

module.exports = {
  MEMORY_ROOT,
  RETENTION_DAYS,
  appendConversation,
  cleanupOldHistory,
  countRecentTurns,
};
