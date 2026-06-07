#!/usr/bin/env node
/**
 * last_seq 持久化 — 默认 ~/.openclaw/sandbox-heartbeat/state.json
 * 可用 SANDBOX_HEARTBEAT_STATE 覆盖路径
 */

const fs = require('fs');
const path = require('path');

const STATE_DIR = process.env.SANDBOX_HEARTBEAT_STATE
  ? path.dirname(process.env.SANDBOX_HEARTBEAT_STATE)
  : path.join(process.env.HOME || '', '.openclaw', 'sandbox-heartbeat');

const STATE_PATH = process.env.SANDBOX_HEARTBEAT_STATE
  || path.join(STATE_DIR, 'state.json');

const DEFAULT_STATE = {
  lastSeq: 0,
  lastPollAt: null,
  lastLatestSeq: 0,
  totalProcessed: 0,
};

function ensureDir() {
  fs.mkdirSync(STATE_DIR, { recursive: true });
}

function loadState() {
  try {
    const raw = JSON.parse(fs.readFileSync(STATE_PATH, 'utf-8'));
    return { ...DEFAULT_STATE, ...raw };
  } catch {
    return { ...DEFAULT_STATE };
  }
}

function saveState(patch) {
  ensureDir();
  const next = { ...loadState(), ...patch, updatedAt: new Date().toISOString() };
  fs.writeFileSync(STATE_PATH, JSON.stringify(next, null, 2), 'utf-8');
  return next;
}

function resetState() {
  ensureDir();
  const fresh = { ...DEFAULT_STATE, updatedAt: new Date().toISOString() };
  fs.writeFileSync(STATE_PATH, JSON.stringify(fresh, null, 2), 'utf-8');
  return fresh;
}

module.exports = { STATE_PATH, loadState, saveState, resetState };
