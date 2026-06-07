#!/usr/bin/env node
const { query } = require('./entertainment-query');

async function main() {
  console.log('[entertainment-scout] 验证 entertainment-query.js ...');
  const r = await query({ area: '三里屯', limit: 3 });
  if (!r.success || !r.data?.venues?.length) throw new Error('venues 为空');
  if (!r.summary) throw new Error('缺少 summary');
  console.log('✅ entertainment-scout OK');
  console.log('   summary:', r.summary.split('\n')[0]);
}

main().catch((e) => { console.error('❌', e.message); process.exit(1); });
