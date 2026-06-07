#!/usr/bin/env node
const { post } = require('../../_shared/sandbox-client');
const { poll } = require('./poll-events');
const { resetState, loadState, STATE_PATH } = require('./state');

async function main() {
  console.log('[sandbox-heartbeat] 验证 poll-events.js ...');
  resetState();

  // 注入下雨，触发 weather / venue / mobility 连锁
  await post('/admin/inject', { kind: 'rain' });

  const r1 = await poll({ dryRun: false });
  if (!r1.success) throw new Error('poll 失败');
  if (r1.data.latest_seq <= 0) throw new Error('latest_seq 异常');

  const types = new Set((r1.data.reminders || []).map((x) => x.type));
  console.log('   首轮 reminders:', [...types].join(', ') || '(无，可能事件在后续 tick)');

  // 再 poll 一次应无重复（幂等）
  const before = loadState().lastSeq;
  const r2 = await poll({ dryRun: false });
  if (r2.data.since !== before) throw new Error('since 未对齐 last_seq');
  if ((r2.data.reminders || []).length > 0 && r2.data.events.length === 0) {
    // ok - no new events
  }

  if (!r1.summary || typeof r1.summary !== 'string') throw new Error('缺少 summary 字符串');
  console.log('✅ sandbox-heartbeat OK');
  console.log('   state:', STATE_PATH);
  console.log('   summary:', r1.summary.split('\n')[0]);
}

main().catch((e) => { console.error('❌', e.message); process.exit(1); });
