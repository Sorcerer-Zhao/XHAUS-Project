#!/usr/bin/env node
/**
 * 天气查询 — GET /weather（仿 open-meteo 字段）
 * 用法: node weather-query.js --area 望京
 */

const { get, checkHealth } = require('../../_shared/sandbox-client');
const { parseFlags, ok, run } = require('../../_shared/skill-runner');
const { summarizeWeather } = require('../../_shared/summaries');

const WEATHER_LABELS = {
  0: '晴', 1: '少云', 2: '多云', 3: '阴', 45: '雾', 48: '霜雾',
  51: '毛毛雨', 53: '毛毛雨', 55: '毛毛雨', 61: '小雨', 63: '中雨', 65: '大雨',
  71: '小雪', 73: '中雪', 75: '大雪', 80: '阵雨', 95: '雷暴',
};

function label(code) {
  return WEATHER_LABELS[code] || `天气码 ${code}`;
}

async function query(flags) {
  await checkHealth();
  const raw = await get('/weather', { area: flags.area, lat: flags.lat, lon: flags.lon });
  const cur = raw.current || {};
  const daily = raw.daily || {};
  const data = {
    area: raw.area || flags.area || '全城',
    sim_now: raw.sim_now,
    is_raining: raw.is_raining,
    current: cur,
    daily,
    forecast3d: (daily.time || []).map((day, i) => ({
      date: day,
      max: daily.temperature_2m_max?.[i],
      min: daily.temperature_2m_min?.[i],
      code: daily.weather_code?.[i],
      label: label(daily.weather_code?.[i]),
    })),
    metrics: {
      temperature: cur.temperature_2m,
      apparent: cur.apparent_temperature,
      humidity: cur.relative_humidity_2m,
      wind: cur.wind_speed_10m,
      weather_code: cur.weather_code,
      weather_label: label(cur.weather_code),
    },
  };
  return ok('weather_query', summarizeWeather({ ...data, summary: data.metrics }), data);
}

async function main() {
  const flags = parseFlags(process.argv.slice(2), { area: 'string', lat: 'string', lon: 'string' });
  if (flags.help) {
    console.log('用法: node weather-query.js [--area 望京]');
    return;
  }
  return query(flags);
}

if (require.main === module) {
  run(main);
}

module.exports = { query, label };
