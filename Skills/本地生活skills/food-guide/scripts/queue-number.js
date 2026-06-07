#!/usr/bin/env node
/**
 * 排队取号 — POST/GET /queue/*
 * 用法:
 *   node queue-number.js take --restaurant-id r004 --people 2 --name 宋先生
 *   node queue-number.js status --queue-code 海01
 *   node queue-number.js cancel --queue-code 海01
 */

const { get, post, checkHealth } = require('../../_shared/sandbox-client');
const { parseFlags, ok, run } = require('../../_shared/skill-runner');
const {
  summarizeQueueTake,
  summarizeQueueStatus,
  summarizeQueueCancel,
} = require('../../_shared/summaries');

function parseQueueArgs(argv) {
  const action = argv[0] || 'take';
  const flags = parseFlags(argv.slice(1), {
    restaurantId: 'string',
    people: 'number',
    name: 'string',
    queueCode: 'string',
  });
  return { action, flags };
}

function normalizeTake(data) {
  const ticket = {
    queueCode: data.queue_code,
    restaurant: data.restaurant,
    address: data.address,
    tableType: data.table_type_label || data.table_type,
    people: data.people,
    customerName: data.customer_name,
    aheadCount: data.ahead,
    estimatedMinutes: data.eta_min,
    estimatedCallTime: data.estimated_call_time,
    tips: data.tips || [],
  };
  return { ticket, raw: data };
}

function normalizeStatus(data) {
  const ticket = {
    queueCode: data.queue_code,
    restaurant: data.restaurant,
    address: data.address,
    tableType: data.table_type,
    people: data.people,
    statusText: data.status_text,
    aheadCount: data.ahead,
    estimatedMinutes: data.eta_min,
    estimatedCallTime: data.estimated_call_time,
    progress: data.progress,
    status: data.status,
  };
  return { ticket, raw: data };
}

async function take(flags) {
  if (!flags.restaurantId) return { success: false, summary: '缺少 --restaurant-id', error: '缺少 --restaurant-id' };
  const raw = await post('/queue/take', {
    restaurant_id: flags.restaurantId,
    people: flags.people || 2,
    customer_name: flags.name || '顾客',
  });
  if (raw.success === false) return { success: false, summary: raw.error, ...raw };
  const { ticket, raw: data } = normalizeTake(raw);
  try {
    const { registerTicket } = require('../../sandbox-heartbeat/scripts/watch-queue');
    registerTicket({
      queueCode: ticket.queueCode || data.queue_code,
      restaurant: ticket.restaurant || data.restaurant,
      restaurantId: flags.restaurantId,
      ahead: ticket.aheadCount ?? data.ahead ?? 0,
    });
  } catch { /* 盯号注册失败不阻断取号 */ }
  const summary = summarizeQueueTake(ticket, data)
    + '\n已加入管家盯号列表，叫号或快到号时我会主动提醒你（需已开启 sandbox-heartbeat Cron）。';
  return ok('queue_take', summary, { ticket, ...data, watchRegistered: true });
}

async function status(flags) {
  if (!flags.queueCode) return { success: false, summary: '缺少 --queue-code', error: '缺少 --queue-code' };
  const raw = await get('/queue/status', { queue_code: flags.queueCode });
  if (raw.success === false) return { success: false, summary: raw.error, ...raw };
  const { ticket, raw: data } = normalizeStatus(raw);
  return ok('queue_status', summarizeQueueStatus(ticket, data), { ticket, ...data });
}

async function cancel(flags) {
  if (!flags.queueCode) return { success: false, summary: '缺少 --queue-code', error: '缺少 --queue-code' };
  const raw = await post('/queue/cancel', { queue_code: flags.queueCode });
  if (raw.success === false) return { success: false, summary: raw.error, ...raw };
  return ok('queue_cancel', summarizeQueueCancel(raw), raw);
}

async function reset() {
  const raw = await post('/admin/reset', { seed: 42 });
  return ok('queue_reset', `沙箱世界已重置（seed=42），当前世界时间 ${raw.sim_now || ''}`, raw);
}

async function advance(flags) {
  if (!flags.queueCode) {
    return {
      success: false,
      summary: '演示叫号需 --queue-code；平时请轮询 status 等待沙箱自动叫号',
      error: '缺少 --queue-code',
    };
  }
  const raw = await post('/admin/inject', { kind: 'queue_called', queue_code: flags.queueCode });
  return ok('queue_advance', raw.message || `已触发叫号 ${flags.queueCode}`, raw);
}

async function main() {
  const { action, flags } = parseQueueArgs(process.argv.slice(2));
  if (flags.help) {
    console.log(`用法: node queue-number.js <take|status|cancel|reset|advance> [选项]`);
    return;
  }
  await checkHealth();
  switch (action) {
    case 'take': return take(flags);
    case 'status': return status(flags);
    case 'cancel': return cancel(flags);
    case 'reset': return reset();
    case 'advance': return advance(flags);
    default:
      return { success: false, summary: `未知操作: ${action}`, error: `未知操作: ${action}` };
  }
}

if (require.main === module) {
  run(main);
}

module.exports = { take, status, cancel, parseQueueArgs };
