#!/usr/bin/env node
/**
 * 端到端用户体验演示（Phase 5）
 * 用法: node demo/e2e-story.js [--no-reset]
 */

const { execFileSync } = require('child_process');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SKILLS = path.join(ROOT, 'skills');
const { post } = require(path.join(SKILLS, '_shared/sandbox-client'));

const C = {
  title: (s) => `\x1b[1;36m${s}\x1b[0m`,
  user: (s) => `\x1b[33m👤 用户：${s}\x1b[0m`,
  agent: (s) => `\x1b[32m🤖 管家：${s}\x1b[0m`,
  dim: (s) => `\x1b[2m${s}\x1b[0m`,
};

function runScript(rel, args = []) {
  const script = path.join(SKILLS, rel);
  const out = execFileSync(process.execPath, [script, ...args], {
    encoding: 'utf-8',
    env: { ...process.env, SANDBOX_URL: process.env.SANDBOX_URL || 'http://127.0.0.1:8787' },
  });
  return JSON.parse(out);
}

function section(n, title) {
  console.log('\n' + C.title(`━━━ 故事 ${n}：${title} ━━━`));
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function prepareWorld(reset) {
  if (reset) {
    await post('/admin/reset', { seed: 42 });
    await post('/admin/clock', { time_scale: 30 });
  }
  try {
    execFileSync(process.execPath, [
      path.join(SKILLS, 'sandbox-heartbeat/scripts/poll-events.js'), '--reset',
    ], { encoding: 'utf-8', env: process.env });
  } catch { /* ignore */ }
}

async function storySearchJapanese() {
  section(1, '搜附近日料');
  console.log(C.user('望京附近有什么日料？两个人，预算 300。'));
  console.log(C.dim('  → exec: search-restaurants.js'));

  const res = runScript('food-guide/scripts/search-restaurants.js', [
    '--area', '望京', '--cuisine', '日料', '--people', '2', '--budget', '300', '--sort', 'wait',
  ]);
  if (!res.success) throw new Error(res.error || '搜索失败');
  console.log(C.agent(res.summary));

  const pick = res.restaurants?.find((r) => !r.isFull) || res.restaurants?.[0];
  if (!pick) throw new Error('无推荐餐厅');
  console.log(C.dim(`  （restaurant_id=${pick.id}）`));
  return pick;
}

async function storyQueue(restaurant) {
  section(2, '取号排队 → 叫号提醒');
  console.log(C.user(`帮我在「${restaurant.name}」排个号，2 个人。`));

  const take = runScript('food-guide/scripts/queue-number.js', [
    'take', '--restaurant-id', restaurant.id, '--people', '2', '--name', '演示用户',
  ]);
  if (!take.success) throw new Error(take.error || '取号失败');

  const code = take.queue_code || take.ticket?.queueCode;
  console.log(C.agent(take.summary));

  await post('/admin/inject', { kind: 'queue_threshold', queue_code: code });
  await sleep(400);
  await post('/admin/inject', { kind: 'queue_called', queue_code: code });

  const hb = runScript('sandbox-heartbeat/scripts/poll-events.js');
  const reminders = hb.reminders || hb.data?.reminders || [];
  const called = reminders.find((r) => r.type === 'queue.called');
  if (called) console.log(C.agent(`【主动提醒】${called.text}`));

  const st = runScript('food-guide/scripts/queue-number.js', ['status', '--queue-code', code]);
  console.log(C.agent(st.summary));
}

async function storyWeatherMobility(restaurant) {
  section(3, '天气变化联动出行与娱乐');
  console.log(C.user('下雨了，去三里屯怎么走？有什么室内活动？'));

  await post('/admin/inject', { kind: 'rain' });
  await sleep(600);

  const hb = runScript('sandbox-heartbeat/scripts/poll-events.js');
  for (const r of hb.reminders || hb.data?.reminders || []) {
    if (['weather.changed', 'mobility.surge', 'venue.closed'].includes(r.type)) {
      console.log(C.agent(`【主动提醒】${r.text}`));
    }
  }

  const wx = runScript('weather/scripts/weather-query.js', ['--area', restaurant.area || '望京']);
  console.log(C.agent(wx.summary));

  const plan = runScript('mobility-planner/scripts/mobility-plan.js', [
    '--from', restaurant.area || '望京', '--to', '三里屯',
  ]);
  console.log(C.agent(plan.summary));

  const ent = runScript('entertainment-scout/scripts/entertainment-query.js', [
    '--area', '三里屯', '--type', 'movie', '--time', '21:00',
  ]);
  console.log(C.agent(ent.summary));
}

async function main() {
  console.log(C.title('\n╔══════════════════════════════════════════════════╗'));
  console.log(C.title('║   端到端用户体验演示 · 三条完整故事链             ║'));
  console.log(C.title('╚══════════════════════════════════════════════════╝'));

  await prepareWorld(!process.argv.includes('--no-reset'));
  const restaurant = await storySearchJapanese();
  await storyQueue(restaurant);
  await storyWeatherMobility(restaurant);

  console.log(C.title('\n✅ 三条故事链演示完成。\n'));
}

main().catch((err) => {
  console.error('\n❌ 演示失败:', err.message);
  console.error('请先运行: ./scripts/start-all.sh');
  process.exit(1);
});
