#!/usr/bin/env node
/**
 * 管家心跳 — 本地轮询循环（无需 OpenClaw Cron）
 *
 * 用法: node run-loop.js [--interval 30] [--max 0]
 *   --interval  秒，默认 30
 *   --max       最多轮询次数，0=无限（默认 0）
 */

const { poll } = require('./poll-events');
const { fail } = require('../../_shared/sandbox-client');

function parseArgs(argv) {
  const out = { interval: 30, max: 0 };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--interval' && argv[i + 1]) { out.interval = Number(argv[++i]); continue; }
    if (argv[i] === '--max' && argv[i + 1]) { out.max = Number(argv[++i]); continue; }
  }
  return out;
}

async function tick(n) {
  const result = await poll({ dryRun: false });
  const ts = new Date().toISOString();
  console.error(`[${ts}] tick #${n} seq ${result.data?.since}→${result.data?.latest_seq} reminders=${result.data?.reminders?.length || 0}`);
  console.log(JSON.stringify(result, null, 2));
  if (result.data?.reminders?.length) {
    console.error('--- 需主动提醒 ---');
    for (const r of result.data.reminders) {
      console.error(`[${r.type}] ${r.text}`);
    }
  }
}

async function main() {
  const { interval, max } = parseArgs(process.argv.slice(2));
  let n = 0;
  console.error(`sandbox-heartbeat loop: every ${interval}s (max=${max || '∞'})`);

  while (true) {
    n += 1;
    try {
      await tick(n);
    } catch (err) {
      console.log(JSON.stringify(fail(err), null, 2));
    }
    if (max > 0 && n >= max) break;
    await new Promise((r) => setTimeout(r, interval * 1000));
  }
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
