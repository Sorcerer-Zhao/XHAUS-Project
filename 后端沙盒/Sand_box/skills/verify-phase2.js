#!/usr/bin/env node
/**
 * Phase 2 全量验证 — 各 Skill 独立调用沙箱 HTTP API
 *
 * 用法: node verify-phase2.js
 * 前置: dynamic-sandbox 已在 http://127.0.0.1:8787 启动
 */

const { execFileSync } = require('child_process');
const path = require('path');

const SKILLS = [
  'food-guide',
  'weather',
  'mobility-planner',
  'entertainment-scout',
  'sandbox-heartbeat',
];

let failed = 0;

for (const skill of SKILLS) {
  const script = path.join(__dirname, skill, 'scripts', 'verify.js');
  process.stdout.write(`\n── ${skill} ──\n`);
  try {
    execFileSync(process.execPath, [script], { stdio: 'inherit', timeout: 30000 });
  } catch {
    failed++;
  }
}

console.log(failed ? `\n❌ Phase 2 失败 (${failed}/${SKILLS.length})` : '\n✅ Phase 2 全部通过');
process.exit(failed ? 1 : 0);
