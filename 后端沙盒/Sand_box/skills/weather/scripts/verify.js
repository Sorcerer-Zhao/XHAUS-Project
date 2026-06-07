#!/usr/bin/env node
const { query } = require('./weather-query');

async function main() {
  console.log('[weather] 验证 weather-query.js ...');
  const r = await query({ area: '望京' });
  if (!r.success || r.data?.current?.temperature_2m == null) throw new Error('天气数据异常');
  if (!r.summary) throw new Error('缺少 summary');
  console.log('✅ weather OK');
  console.log('   summary:', r.summary.split('\n')[0]);
}

main().catch((e) => { console.error('❌', e.message); process.exit(1); });
