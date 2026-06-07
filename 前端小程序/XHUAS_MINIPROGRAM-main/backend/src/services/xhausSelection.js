const DEFAULT_AGENT = {
  id: "main",
  label: "默认管家",
  value: "main",
  source: "default",
};

const PRESET_AGENT_IDS = {
  default_butler: "main",
  elegant_maid: "elegant_maid",
  Emma: "emma",
  emma: "emma",
  Franziska: "franziska",
  franziska: "franziska",
};

let activeAgent = Object.assign({}, DEFAULT_AGENT);

function normalizeAgentId(value) {
  const trimmed = String(value || "").trim().toLowerCase();
  if (!trimmed) {
    return "main";
  }
  if (/^[a-z0-9_-]+$/.test(trimmed)) {
    return trimmed.slice(0, 64);
  }
  const slug = trimmed.replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
  return slug || "main";
}

function cleanLabel(label, fallback) {
  return String(label || fallback || "")
    .replace(/（我的管家）$/, "")
    .trim();
}

function agentFromChoice(choice) {
  if (!choice || choice.kind === "custom") {
    return null;
  }

  const rawValue = String(choice.value || "").replace(/^custom:/, "");
  const agentId = PRESET_AGENT_IDS[rawValue] || rawValue || choice.label;
  return {
    id: normalizeAgentId(agentId),
    label: cleanLabel(choice.label, rawValue || "当前管家"),
    value: choice.value || rawValue,
    source: "xhaus_wizard",
  };
}

function setActiveAgent(agent) {
  if (!agent || !agent.id) {
    return activeAgent;
  }
  activeAgent = {
    id: normalizeAgentId(agent.id),
    label: cleanLabel(agent.label, agent.id),
    value: agent.value || agent.id,
    source: agent.source || "manual",
  };
  return activeAgent;
}

function setActiveAgentFromChoice(choice) {
  const agent = agentFromChoice(choice);
  if (!agent) {
    return activeAgent;
  }
  return setActiveAgent(agent);
}

function getActiveAgent() {
  return Object.assign({}, activeAgent);
}

module.exports = {
  DEFAULT_AGENT,
  agentFromChoice,
  getActiveAgent,
  normalizeAgentId,
  setActiveAgent,
  setActiveAgentFromChoice,
};
