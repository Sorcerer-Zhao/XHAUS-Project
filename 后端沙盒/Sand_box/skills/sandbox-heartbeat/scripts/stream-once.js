#!/usr/bin/env node
/**
 * SSE 消费演示 — GET /events/stream?since=<seq>，监听一段时间后退出
 *
 * 用法: node stream-once.js [--since 0] [--seconds 15]
 */

const { SANDBOX_BASE, fail } = require('../../_shared/sandbox-client');
const { loadState, saveState } = require('./state');
const { remindersFromEvents, summarizePoll } = require('./event-messages');
const { ok, run } = require('../../_shared/skill-runner');

async function streamOnce({ since, seconds = 15 }) {
  const url = new URL(`${SANDBOX_BASE}/events/stream`);
  url.searchParams.set('since', String(since));

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), seconds * 1000);

  const events = [];
  let latestSeq = since;

  try {
    const res = await fetch(url, { headers: { Accept: 'text/event-stream' }, signal: controller.signal });
    if (!res.ok) throw new Error(`SSE HTTP ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';
      for (const block of parts) {
        const dataLine = block.split('\n').find((l) => l.startsWith('data:'));
        if (!dataLine) continue;
        try {
          const evt = JSON.parse(dataLine.slice(5).trim());
          events.push(evt);
          latestSeq = Math.max(latestSeq, evt.seq || latestSeq);
        } catch { /* keep-alive comments */ }
      }
    }
  } catch (err) {
    if (err.name !== 'AbortError') throw err;
  } finally {
    clearTimeout(timer);
  }

  const reminders = remindersFromEvents(events);
  saveState({ lastSeq: latestSeq, lastPollAt: new Date().toISOString() });

  const data = { since, latest_seq: latestSeq, newCount: events.length, events, reminders, mode: 'sse' };
  return ok('heartbeat_stream', summarizePoll({ newCount: events.length, reminders, latestSeq, since }), data);
}

async function main() {
  const argv = process.argv.slice(2);
  let since = loadState().lastSeq;
  let seconds = 15;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--since' && argv[i + 1]) since = Number(argv[++i]);
    if (argv[i] === '--seconds' && argv[i + 1]) seconds = Number(argv[++i]);
  }
  return streamOnce({ since, seconds });
}

if (require.main === module) {
  run(main);
}

module.exports = { streamOnce };
