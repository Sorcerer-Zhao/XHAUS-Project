#!/usr/bin/env node
/**
 * 出行方案 — GET /mobility/plan 或 GET /mobility/areas
 * 用法:
 *   node mobility-plan.js --from 望京 --to 三里屯 [--time 19:00] [--mode all]
 *   node mobility-plan.js areas
 */

const { get, checkHealth } = require('../../_shared/sandbox-client');
const { parseFlags, ok, run } = require('../../_shared/skill-runner');
const { summarizeMobility } = require('../../_shared/summaries');

async function plan(flags) {
  if (!flags.from || !flags.to) {
    return { success: false, summary: '需要 --from 和 --to', error: '缺少 --from / --to' };
  }
  await checkHealth();
  const raw = await get('/mobility/plan', {
    from: flags.from,
    to: flags.to,
    time: flags.time,
    mode: flags.mode || 'all',
  });
  if (raw.success === false) {
    return { success: false, summary: raw.error || '出行规划失败', ...raw };
  }
  return ok('mobility_plan', summarizeMobility(raw), raw);
}

async function areas() {
  await checkHealth();
  const raw = await get('/mobility/areas');
  const names = Object.keys(raw.areas || {}).join('、');
  return ok('mobility_areas', `沙箱支持 ${Object.keys(raw.areas || {}).length} 个区域：${names}`, raw);
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv[0] === 'areas') return areas();

  const flags = parseFlags(argv, { from: 'string', to: 'string', time: 'string', mode: 'string' });
  if (flags.help) {
    console.log('用法: node mobility-plan.js --from 望京 --to 三里屯 [--time 19:00] [--mode all|subway|taxi|walk]');
    console.log('      node mobility-plan.js areas');
    return;
  }
  return plan(flags);
}

if (require.main === module) {
  run(main);
}

module.exports = { plan, areas };
