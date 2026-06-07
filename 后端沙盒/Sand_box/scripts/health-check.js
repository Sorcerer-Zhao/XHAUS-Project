#!/usr/bin/env node
/**
 * 沙箱 + Skill 链路健康检查（Phase 6）
 * 用法: node scripts/health-check.js [--skills]
 */

const { execFileSync } = require('child_process');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SKILLS = path.join(ROOT, 'skills');

async function checkSandbox() {
  const { checkHealth, get, SANDBOX_BASE } = require(path.join(SKILLS, '_shared/sandbox-client'));
  const results = [];

  const push = (name, ok, detail = '') => results.push({ name, ok, detail });

  try {
    const h = await checkHealth();
    push('sandbox:8787 /health', true, `tick_count=${h.tick_count}`);
  } catch (e) {
    push('sandbox:8787 /health', false, e.message);
    return { ok: false, base: SANDBOX_BASE, results };
  }

  const endpoints = [
    ['GET /restaurants', () => get('/restaurants', { area: '望京', limit: 1 })],
    ['GET /weather', () => get('/weather', { area: '望京' })],
    ['GET /events', () => get('/events', { since: 0, limit: 1 })],
    ['GET /events/stream (SSE)', async () => {
      const url = `${SANDBOX_BASE}/events/stream?since=0`;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 2500);
      const res = await fetch(url, { headers: { Accept: 'text/event-stream' }, signal: controller.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const ct = res.headers.get('content-type') || '';
      if (!ct.includes('text/event-stream')) throw new Error(`content-type=${ct}`);
      clearTimeout(timer);
      return { sse: true };
    }],
    ['GET /mobility/plan', () => get('/mobility/plan', { from: '望京', to: '三里屯' })],
    ['GET /entertainment', () => get('/entertainment', { area: '三里屯', limit: 1 })],
  ];

  for (const [name, fn] of endpoints) {
    try {
      const data = await fn();
      push(`sandbox:${name}`, true, `keys=${Object.keys(data).slice(0, 4).join(',')}`);
    } catch (e) {
      push(`sandbox:${name}`, false, e.message);
    }
  }

  // queue take + status smoke
  try {
    const list = await get('/restaurants', { area: '望京', limit: 5 });
    const r = (list.restaurants || []).find((x) => x.id === 'r003') || list.restaurants?.[0];
    if (!r) throw new Error('无餐厅可测');
    const { post } = require(path.join(SKILLS, '_shared/sandbox-client'));
    const take = await post('/queue/take', { restaurant_id: r.id, people: 2, customer_name: '健康检查' });
    if (!take.queue_code) throw new Error('取号失败');
    const st = await get('/queue/status', { queue_code: take.queue_code });
    push('POST/GET /queue', true, `code=${take.queue_code} ahead=${st.ahead}`);
  } catch (e) {
    push('POST/GET /queue', false, e.message);
  }

  const ok = results.every((r) => r.ok);
  return { ok, results };
}

function checkSkills() {
  const results = [];
  const skills = ['food-guide', 'weather', 'mobility-planner', 'entertainment-scout', 'sandbox-heartbeat'];
  for (const s of skills) {
    const verify = path.join(SKILLS, s, 'scripts', 'verify.js');
    try {
      execFileSync(process.execPath, [verify], { cwd: ROOT, stdio: 'pipe', timeout: 20000, env: process.env });
      results.push({ name: `skill:${s}`, ok: true });
    } catch (e) {
      const err = (e.stderr || e.stdout || '').toString().split('\n').find((l) => l.includes('❌')) || e.message;
      results.push({ name: `skill:${s}`, ok: false, detail: err.slice(0, 120) });
    }
  }
  return { ok: results.every((r) => r.ok), results };
}

async function main() {
  const withSkills = process.argv.includes('--skills');
  console.log('=== dynamic-sandbox 健康检查 ===\n');

  const sandbox = await checkSandbox();
  for (const r of sandbox.results) {
    console.log(`${r.ok ? '✅' : '❌'} ${r.name}${r.detail ? ` — ${r.detail}` : ''}`);
  }

  let allOk = sandbox.ok;
  if (withSkills) {
    console.log('\n=== OpenClaw Skills 验证 ===\n');
    const skills = checkSkills();
    for (const r of skills.results) {
      console.log(`${r.ok ? '✅' : '❌'} ${r.name}${r.detail ? ` — ${r.detail}` : ''}`);
    }
    allOk = allOk && skills.ok;
  }

  console.log(allOk ? '\n✅ 全部检查通过' : '\n❌ 存在失败项');
  process.exit(allOk ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
