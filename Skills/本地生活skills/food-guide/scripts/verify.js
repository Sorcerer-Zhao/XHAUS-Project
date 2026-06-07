#!/usr/bin/env node
const { search } = require('./search-restaurants');
const { take, status } = require('./queue-number');

async function main() {
  console.log('[food-guide] 验证 search-restaurants + queue-number ...');
  const list = await search({ area: '望京', sort: 'wait', limit: 3 });
  if (!list.success || !list.summary) throw new Error('search 缺少 summary');
  const target = list.restaurants?.find((r) => r.id === 'r004') || list.restaurants?.[0];
  if (!target) throw new Error('无餐厅');
  const ticket = await take({ restaurantId: target.id, people: 2, name: '验证' });
  if (!ticket.success) throw new Error('取号失败');
  const code = ticket.queue_code || ticket.ticket?.queueCode;
  const st = await status({ queueCode: code });
  if (!st.success || !st.summary) throw new Error('status 失败');
  console.log('✅ food-guide OK');
  console.log('   search:', list.summary.split('\n')[0]);
  console.log('   queue:', st.summary);
}

main().catch((e) => { console.error('❌', e.message); process.exit(1); });
