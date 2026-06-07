#!/usr/bin/env node
const { plan, areas } = require('./mobility-plan');

async function main() {
  console.log('[mobility-planner] 验证 mobility-plan.js ...');
  const a = await areas();
  if (!a.data?.areas) throw new Error('areas 为空');
  const p = await plan({ from: '望京', to: '三里屯', mode: 'all' });
  if (!p.success || !p.summary) throw new Error('plan 失败');
  console.log('✅ mobility-planner OK');
  console.log('   summary:', p.summary.slice(0, 80) + '...');
}

main().catch((e) => { console.error('❌', e.message); process.exit(1); });
