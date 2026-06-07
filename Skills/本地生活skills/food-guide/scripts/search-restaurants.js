#!/usr/bin/env node
/**
 * 餐厅搜索 — GET /restaurants
 * 用法: node search-restaurants.js --area 望京 --cuisine 日料 --budget 300 --people 2
 */

const { get, checkHealth } = require('../../_shared/sandbox-client');
const { parseFlags, ok, run } = require('../../_shared/skill-runner');
const { summarizeRestaurants } = require('../../_shared/summaries');

const FLAG_SCHEMA = {
  area: 'string', cuisine: 'string', tag: 'string',
  budget: 'number', people: 'number', sort: 'string', limit: 'number', id: 'string',
};

async function search(flags) {
  await checkHealth();

  if (flags.id) {
    const detail = await get(`/restaurants/${flags.id}`);
    const data = {
      query: { id: flags.id },
      count: 1,
      total: 1,
      sim_now: detail.sim_now,
      restaurants: [detail],
    };
    return ok('search_restaurants', summarizeRestaurants(data), data);
  }

  const query = {
    area: flags.area,
    cuisine: flags.cuisine,
    tag: flags.tag,
    budget: flags.budget,
    people: flags.people || 1,
    sort: flags.sort || 'rating',
    limit: flags.limit || 5,
  };

  const raw = await get('/restaurants', query);
  const data = {
    query: raw.query || query,
    count: raw.count,
    total: raw.total ?? raw.count,
    hint: raw.hint ?? null,
    sim_now: raw.sim_now,
    restaurants: raw.restaurants || [],
  };
  return ok('search_restaurants', summarizeRestaurants(data), data);
}

async function main() {
  const flags = parseFlags(process.argv.slice(2), FLAG_SCHEMA);
  if (flags.help) {
    console.log(`用法: node search-restaurants.js [--area 望京] [--cuisine 日料] [--budget 300] [--people 2] [--sort wait|rating|price] [--limit 5] [--id r004]`);
    return;
  }
  return search(flags);
}

if (require.main === module) {
  run(main);
}

module.exports = { search, parseFlags };
