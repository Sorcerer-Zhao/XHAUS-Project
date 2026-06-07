#!/usr/bin/env node
/**
 * 用户取号后的「盯号列表」— 心跳除 /events 外再轮询 /queue/status，避免漏叫号提醒
 */

const fs = require('fs');
const path = require('path');
const { get } = require('../../_shared/sandbox-client');

const STATE_DIR = process.env.SANDBOX_HEARTBEAT_STATE
  ? path.dirname(process.env.SANDBOX_HEARTBEAT_STATE)
  : path.join(process.env.HOME || '', '.openclaw', 'sandbox-heartbeat');

const WATCH_PATH = path.join(STATE_DIR, 'watch-queue.json');

function ensureDir() {
  fs.mkdirSync(STATE_DIR, { recursive: true });
}

function loadWatch() {
  try {
    return JSON.parse(fs.readFileSync(WATCH_PATH, 'utf-8'));
  } catch {
    return { tickets: {} };
  }
}

function saveWatch(data) {
  ensureDir();
  fs.writeFileSync(WATCH_PATH, JSON.stringify(data, null, 2), 'utf-8');
}

function registerTicket({ queueCode, restaurant, restaurantId, ahead = 0 }) {
  if (!queueCode) return loadWatch();
  const data = loadWatch();
  data.tickets[queueCode] = {
    queueCode,
    restaurant: restaurant || '',
    restaurantId: restaurantId || '',
    lastStatus: 'waiting',
    lastAhead: ahead,
    thresholdNotified: ahead <= 5,
    registeredAt: new Date().toISOString(),
  };
  saveWatch(data);
  return data;
}

function unregisterTicket(queueCode) {
  const data = loadWatch();
  delete data.tickets[queueCode];
  saveWatch(data);
  return data;
}

function listWatched() {
  return Object.values(loadWatch().tickets || {});
}

/**
 * 轮询所有盯号中的票，状态变化时生成 reminders（补 /events 遗漏）
 */
async function pollWatchedQueues() {
  const data = loadWatch();
  const tickets = data.tickets || {};
  const reminders = [];
  const codes = Object.keys(tickets);

  for (const code of codes) {
    const meta = tickets[code];
    let st;
    try {
      st = await get('/queue/status', { queue_code: code });
    } catch {
      continue;
    }
    if (st.success === false) {
      delete tickets[code];
      continue;
    }

    const status = st.status;
    const ahead = st.ahead ?? 0;
    const restaurant = st.restaurant || meta.restaurant || '餐厅';

    if (meta.lastStatus === 'waiting' && status === 'called') {
      reminders.push({
        type: 'queue.called',
        text: `🔔 排队号 ${code} 已叫号，请尽快前往「${restaurant}」就座！`,
        suggestedAction: '立即用 message 通知用户就座，语气简短紧迫。',
        urgency: 'critical',
        queue_code: code,
        source: 'watch_poll',
      });
    }

    if (status === 'waiting' && !meta.thresholdNotified && meta.lastAhead > 5 && ahead <= 5 && ahead > 0) {
      meta.thresholdNotified = true;
      reminders.push({
        type: 'queue.threshold',
        text: `⏳ 排队号 ${code} 前面只剩 ${ahead} 桌，预计 ${st.eta_min ?? '?'} 分钟，可以准备出发了。`,
        suggestedAction: '主动提醒用户；可询问是否规划出行（mobility-plan）。',
        urgency: 'high',
        queue_code: code,
        source: 'watch_poll',
      });
    }

    meta.lastStatus = status;
    meta.lastAhead = ahead;

    if (status === 'seated' || status === 'cancelled') {
      delete tickets[code];
    }
  }

  saveWatch(data);
  return reminders;
}

module.exports = {
  WATCH_PATH,
  loadWatch,
  registerTicket,
  unregisterTicket,
  listWatched,
  pollWatchedQueues,
};
