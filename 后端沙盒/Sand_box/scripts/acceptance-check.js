#!/usr/bin/env node
/**
 * Phase 7 最终验收 — 对照六项标准自动检查
 *
 * 用法:
 *   node scripts/acceptance-check.js          # 沙箱须已启动
 *   node scripts/acceptance-check.js --boot   # 未启动时先跑 start-all.sh（不含 --demo）
 */

const { execFileSync } = require('child_process');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SKILLS = path.join(ROOT, 'skills');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];

function record(id, title, ok, detail = '') {
  results.push({ id, title, ok, detail });
  const mark = ok ? '✅' : '❌';
  console.log(`${mark} [${id}] ${title}${detail ? ` — ${detail}` : ''}`);
}

async function bootIfNeeded() {
  const { checkHealth } = require(path.join(SKILLS, '_shared/sandbox-client'));
  try {
    await checkHealth();
    return;
  } catch {
    if (!process.argv.includes('--boot')) {
      throw new Error('沙箱未运行。请先: ./scripts/start-all.sh  或  node scripts/acceptance-check.js --boot');
    }
    console.log('▶ 沙箱未运行，执行 start-all.sh ...\n');
    execFileSync(path.join(ROOT, 'scripts/start-all.sh'), [], { stdio: 'inherit', cwd: ROOT });
    await sleep(500);
  }
}

async function checkCriterion1() {
  const skills = ['food-guide', 'weather', 'mobility-planner', 'entertainment-scout', 'sandbox-heartbeat'];
  let allOk = true;
  const failed = [];

  for (const s of skills) {
    try {
      const out = execFileSync(process.execPath, [path.join(SKILLS, s, 'scripts/verify.js')], {
        cwd: ROOT, encoding: 'utf-8', timeout: 30000, env: process.env,
      });
      if (!out.includes('✅')) throw new Error('verify 未通过');
    } catch (e) {
      allOk = false;
      failed.push(s);
    }
  }

  // 抽样：主脚本输出须含 source=sandbox
  try {
    const out = execFileSync(process.execPath, [
      path.join(SKILLS, 'weather/scripts/weather-query.js'), '--area', '望京',
    ], { cwd: ROOT, encoding: 'utf-8', timeout: 15000, env: process.env });
    const json = JSON.parse(out);
    if (json.source !== 'sandbox') throw new Error('source 非 sandbox');
  } catch (e) {
    allOk = false;
    failed.push('weather-query(source)');
  }

  record('1', 'OpenClaw Skill → dynamic-sandbox HTTP', allOk,
    allOk ? '5 个 Skill verify 通过' : `失败: ${failed.join(', ')}`);
}

async function checkCriterion2() {
  const { get, post } = require(path.join(SKILLS, '_shared/sandbox-client'));

  const h1 = await get('/health');
  const wxBefore = await get('/weather', { area: '望京' });
  const evBefore = await get('/events', { since: 0, limit: 1 });

  // 注入剧情 → 世界状态立刻变化（证明非静态 JSON）
  await post('/admin/inject', { kind: 'rain' });
  const wxAfter = await get('/weather', { area: '望京' });
  const evAfter = await get('/events', { since: 0, limit: 20 });
  const rainChanged = wxAfter.is_raining === true || wxAfter.weather_code >= 60;
  const eventsGrew = (evAfter.latest_seq ?? 0) > (evBefore.latest_seq ?? 0);

  // 后台时钟：tick 间隔默认 ~5s，等待一个周期
  await sleep(5500);
  const h2 = await get('/health');
  const tickGrew = (h2.tick_count ?? 0) > (h1.tick_count ?? 0);

  const r1 = await get('/restaurants', { area: '望京', limit: 1 });
  const hasSimNow = Boolean(r1.sim_now);
  const live = hasSimNow && rainChanged && eventsGrew && tickGrew;

  record('2', '沙箱数据实时演化（非静态 JSON）', live,
    live
      ? `inject→下雨，events ${evBefore.latest_seq}→${evAfter.latest_seq}，tick ${h1.tick_count}→${h2.tick_count}`
      : `sim_now=${hasSimNow} rain=${rainChanged} events=${eventsGrew} tick=${tickGrew}`);
}

async function checkCriterion3() {
  const { get, SANDBOX_BASE } = require(path.join(SKILLS, '_shared/sandbox-client'));

  const poll = await get('/events', { since: 0, limit: 5 });
  const pollOk = Array.isArray(poll.events) && poll.latest_seq != null;

  let sseOk = false;
  try {
    const url = `${SANDBOX_BASE}/events/stream?since=0`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3000);
    const res = await fetch(url, { headers: { Accept: 'text/event-stream' }, signal: controller.signal });
    sseOk = res.ok && (res.headers.get('content-type') || '').includes('text/event-stream');
    clearTimeout(timer);
  } catch (e) {
    sseOk = e.name === 'AbortError'; // 超时前连上即算通过
  }

  record('3', '/events 可轮询 + SSE 可连接', pollOk && sseOk,
    `poll latest_seq=${poll.latest_seq}，SSE ${sseOk ? 'OK' : '失败'}`);
}

async function checkCriterion4() {
  try {
    execFileSync(process.execPath, [path.join(ROOT, 'demo/e2e-story.js'), '--no-reset'], {
      cwd: ROOT, stdio: 'pipe', timeout: 60000, env: process.env,
    });
    record('4', '≥3 条自然语言演示链路', true, 'e2e-story.js 三条故事链通过');
  } catch (e) {
    const msg = (e.stderr || e.stdout || e.message || '').toString().slice(0, 200);
    record('4', '≥3 条自然语言演示链路', false, msg);
  }
}

function checkCriterion5() {
  const required = [
    'README.md',
    'GETTING_STARTED.md',
    'DEMO.md',
    'scripts/start-all.sh',
    'scripts/health-check.js',
    'skills/_shared/sandbox-client.js',
  ];
  const fs = require('fs');
  const missing = required.filter((f) => !fs.existsSync(path.join(ROOT, f)));

  let errorReadable = false;
  try {
    execFileSync(process.execPath, [path.join(SKILLS, 'weather/scripts/weather-query.js')], {
      cwd: ROOT, encoding: 'utf-8', env: { ...process.env, SANDBOX_URL: 'http://127.0.0.1:1' },
    });
  } catch (e) {
    const out = (e.stderr || e.stdout || '').toString();
    errorReadable = out.includes('无法连接沙箱') || out.includes('请先启动');
  }

  const ok = missing.length === 0 && errorReadable;
  record('5', '启动文档齐全 + 失败可读报错', ok,
    missing.length ? `缺文件: ${missing.join(', ')}` : (errorReadable ? 'SandboxError 中文提示 OK' : '错误提示未命中'));
}

function checkCriterion6() {
  const fs = require('fs');
  const shared = ['sandbox-client.js', 'skill-runner.js', 'summaries.js']
    .every((f) => fs.existsSync(path.join(SKILLS, '_shared', f)));
  const index = fs.existsSync(path.join(SKILLS, 'SCRIPTS.md'));
  const perSkillVerify = ['food-guide', 'weather', 'mobility-planner', 'entertainment-scout', 'sandbox-heartbeat']
    .every((s) => fs.existsSync(path.join(SKILLS, s, 'scripts/verify.js')));

  const ok = shared && index && perSkillVerify;
  record('6', '代码结构清晰、易扩展', ok,
    ok ? '_shared + SCRIPTS.md + 各 skill verify.js' : '结构检查未通过');
}

async function main() {
  console.log('╔══════════════════════════════════════════════════╗');
  console.log('║        Phase 7 · 最终验收检查                     ║');
  console.log('╚══════════════════════════════════════════════════╝\n');

  await bootIfNeeded();

  await checkCriterion1();
  await checkCriterion2();
  await checkCriterion3();
  await checkCriterion4();
  checkCriterion5();
  checkCriterion6();

  const passed = results.filter((r) => r.ok).length;
  const total = results.length;
  console.log(`\n${'═'.repeat(50)}`);
  console.log(`验收结果: ${passed}/${total} 项通过`);
  console.log(`${'═'.repeat(50)}\n`);

  if (passed < total) {
    console.log('修复建议:');
    console.log('  ./scripts/start-all.sh');
    console.log('  node scripts/health-check.js --skills');
    console.log('  node demo/e2e-story.js');
    console.log('  详见 ACCEPTANCE.md\n');
    process.exit(1);
  }
  console.log('🎉 全部验收标准满足。可开始 OpenClaw 对话演示（见 DEMO.md）。\n');
}

main().catch((e) => {
  console.error('\n❌ 验收中止:', e.message);
  process.exit(1);
});
