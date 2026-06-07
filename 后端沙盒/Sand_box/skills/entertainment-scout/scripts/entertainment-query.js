#!/usr/bin/env node
/**
 * 娱乐活动查询 — GET /entertainment
 * 用法: node entertainment-query.js --area 三里屯 --type bar --time 21:00 --people 2 --budget 200 --mood lively
 */

const { get, checkHealth } = require('../../_shared/sandbox-client');
const { parseFlags, ok, run } = require('../../_shared/skill-runner');
const { summarizeEntertainment } = require('../../_shared/summaries');

async function query(flags) {
  await checkHealth();

  if (flags.id) {
    const venue = await get(`/entertainment/${flags.id}`);
    const data = { query: { id: flags.id }, count: 1, sim_now: venue.sim_now, venues: [venue] };
    return ok('entertainment_query', summarizeEntertainment(data), data);
  }

  const queryParams = {
    area: flags.area,
    type: flags.type,
    time: flags.time,
    people: flags.people,
    budget: flags.budget,
    mood: flags.mood,
    limit: flags.limit || 6,
  };

  const raw = await get('/entertainment', queryParams);
  const data = {
    query: raw.query || queryParams,
    count: raw.count,
    total: raw.total ?? raw.count,
    hint: raw.hint ?? null,
    sim_now: raw.sim_now,
    weatherNote: raw.weatherNote,
    venues: raw.venues || [],
  };
  return ok('entertainment_query', summarizeEntertainment(data), data);
}

async function main() {
  const flags = parseFlags(process.argv.slice(2), {
    area: 'string', type: 'string', time: 'string',
    people: 'number', budget: 'number', mood: 'string', limit: 'number', id: 'string',
  });
  if (flags.help) {
    console.log('用法: node entertainment-query.js [--area 三里屯] [--type movie|bar|ktv|...] [--time 21:00] [--budget 200] [--mood lively]');
    return;
  }
  return query(flags);
}

if (require.main === module) {
  run(main);
}

module.exports = { query };
