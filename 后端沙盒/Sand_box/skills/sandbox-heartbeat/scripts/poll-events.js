#!/usr/bin/env node
/**
 * 管家心跳 — 单次轮询 GET /events?since=<lastSeq>
 *
 * 用法:
 *   node poll-events.js              # 拉增量事件，更新 last_seq，输出 reminders
 *   node poll-events.js --dry-run    # 不写入 state
 *   node poll-events.js --reset      # 重置 last_seq 为 0
 *   node poll-events.js --status     # 查看 state
 */

const { get, checkHealth } = require('../../_shared/sandbox-client');
const { parseFlags, ok, run } = require('../../_shared/skill-runner');
const { loadState, saveState, resetState, STATE_PATH } = require('./state');
const { remindersFromEvents, summarizePoll, WATCHED_TYPES } = require('./event-messages');
const { pollWatchedQueues, listWatched } = require('./watch-queue');

function mergeReminders(eventReminders, watchReminders) {
  const seen = new Set();
  const out = [];
  for (const r of [...eventReminders, ...watchReminders]) {
    const key = `${r.type}:${r.queue_code || r.payload?.queue_code || r.text}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(r);
  }
  return out;
}

async function poll({ dryRun = false, sinceOverride, typeFilter, limit = 100 } = {}) {
  await checkHealth();

  const state = loadState();
  const since = sinceOverride != null ? sinceOverride : state.lastSeq;

  const params = { since, limit };
  if (typeFilter) params.type = typeFilter;

  const resp = await get('/events', params);
  const events = resp.events || [];
  const latestSeq = resp.latest_seq ?? since;
  const eventReminders = remindersFromEvents(events);
  const watchReminders = await pollWatchedQueues();
  const reminders = mergeReminders(eventReminders, watchReminders);

  if (!dryRun) {
    saveState({
      lastSeq: latestSeq,
      lastLatestSeq: latestSeq,
      lastPollAt: new Date().toISOString(),
      totalProcessed: (state.totalProcessed || 0) + events.length,
    });
  }

  const data = {
    since,
    latest_seq: latestSeq,
    sim_now: resp.sim_now,
    newCount: events.length,
    watchedTypes: [...WATCHED_TYPES],
    watchedQueues: listWatched(),
    events,
    reminders,
    statePath: STATE_PATH,
    dryRun,
  };

  const summary = summarizePoll({
    newCount: events.length,
    reminders,
    latestSeq,
    since,
  });

  return ok('heartbeat_poll', summary, data);
}

async function main() {
  const flags = parseFlags(process.argv.slice(2), {
    dryRun: 'boolean',
    reset: 'boolean',
    status: 'boolean',
    since: 'number',
    limit: 'number',
    type: 'string',
  });

  if (flags.help) {
    console.log(`用法: node poll-events.js [--dry-run] [--reset] [--status] [--since N] [--type queue.threshold,...]

状态文件: ${STATE_PATH}
环境变量: SANDBOX_URL, SANDBOX_HEARTBEAT_STATE`);
    return;
  }

  if (flags.reset) {
    const s = resetState();
    return ok('heartbeat_reset', `已重置 last_seq=0（${STATE_PATH}）`, s);
  }

  if (flags.status) {
    const s = loadState();
    return ok('heartbeat_status', `last_seq=${s.lastSeq}，上次轮询 ${s.lastPollAt || '从未'}`, s);
  }

  return poll({
    dryRun: Boolean(flags.dryRun),
    sinceOverride: flags.since,
    typeFilter: flags.type,
    limit: flags.limit || 100,
  });
}

if (require.main === module) {
  run(main);
}

module.exports = { poll };
