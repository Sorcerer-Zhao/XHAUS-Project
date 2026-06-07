#!/usr/bin/env node
/**
 * 餐厅数据获取（高德 POI 搜索 API）
 *
 * 用法：node crawl-restaurants.js [--area <区域>] [--force]
 * 输出：assets/real-restaurants.json
 *
 * 替代大众点评 Playwright 方案：无需浏览器，无反爬，数据来自高德地图。
 * 可获取：店名、评分、人均、地址、电话、营业时间、菜系标签
 * 不可获取：排队信息（由排号系统模拟）、推荐菜细节（用标签代替）
 */

const https = require('https');
const fs = require('fs');
const path = require('path');

const OUTPUT_PATH = path.join(__dirname, '..', 'assets', 'real-restaurants.json');
const STATE_PATH = path.join(__dirname, '..', 'assets', 'crawl-state.json');
const KEY_PATH = path.join(__dirname, '..', '..', 'mobility-planner', 'assets', 'amap-key.txt');
const CACHE_TTL_MS = 2 * 60 * 60 * 1000;
const TARGET_AREAS = ['望京', '三里屯', '朝阳大悦城', '国贸', '中关村', '五道口'];
const RESTAURANT_SEARCHES = [
  { suffix: '美食', limit: 8 },
  // 补足“日料/日本料理”类意图；单搜“美食”时高德第一页经常不覆盖日料。
  { suffix: '日料', limit: 4 },
];

// ── 高德 API 调用 ────────────────────────────────────────────
function getApiKey() {
  return fs.readFileSync(KEY_PATH, 'utf-8').trim();
}

function amapGet(endpoint, params) {
  return new Promise((resolve, reject) => {
    const query = new URLSearchParams({ ...params, key: getApiKey(), output: 'json' });
    const url = `https://restapi.amap.com/v3/${endpoint}?${query}`;
    const req = https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch { reject(new Error('JSON 解析失败')); }
      });
    });
    req.setTimeout(12000, () => req.destroy(new Error('高德 API 请求超时')));
    req.on('error', reject);
  });
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── 搜索某区域餐厅 ──────────────────────────────────────────
async function searchKeyword(area, config) {
  const resp = await amapGet('place/text', {
    keywords: `${area}${config.suffix}`,
    types: '050000',       // 餐饮服务
    city: '北京',
    citylimit: 'true',
    offset: String(config.limit),
    page: '1',
    extensions: 'all',
  });

  if (resp.status !== '1' || !resp.pois) {
    await sleep(1500);
    const retry = await amapGet('place/text', {
      keywords: `${area}${config.suffix}`, types: '050000', city: '北京',
      citylimit: 'true', offset: String(config.limit), page: '1', extensions: 'all',
    });
    if (retry.status !== '1' || !retry.pois) return [];
    return retry.pois;
  }
  return resp.pois;
}

async function searchArea(area) {
  const pois = [];
  for (const config of RESTAURANT_SEARCHES) {
    pois.push(...await searchKeyword(area, config));
    await sleep(300);
  }
  return pois;
}

// ── POI → 餐厅 JSON 映射 ────────────────────────────────────
function extractCuisine(poi) {
  // keytag: "火锅" / type: "餐饮服务;中餐厅;火锅店"
  const keytag = (typeof poi.keytag === 'string') ? poi.keytag : '';
  const typeText = poi.type || '';
  if (/日本料理|寿司|日式|日料/.test(`${keytag};${typeText}`)) return '日料';
  if (keytag) return keytag;

  const typeParts = typeText.split(';');
  if (typeParts.length >= 3) return typeParts[2].replace(/店|馆|厅|餐厅/g, '');
  if (typeParts.length >= 2) return typeParts[1].replace(/店|馆|厅|餐厅/g, '');
  return '美食';
}

function cleanString(value) {
  if (typeof value === 'string') return value.trim();
  return '';
}

function extractPhone(poi) {
  if (typeof poi.tel === 'string') return poi.tel;
  return '';
}

function extractTags(poi) {
  const tags = [];
  if (poi.keytag && typeof poi.keytag === 'string') tags.push(poi.keytag);
  if (poi.atag && typeof poi.atag === 'string') {
    poi.atag.split(',').forEach(t => {
      t = t.trim();
      if (t && t.length >= 2 && t.length <= 8) tags.push(t);
    });
  }
  // 从 type 中提取
  const typeParts = (poi.type || '').split(';');
  typeParts.forEach(p => {
    p = p.replace(/服务|店|馆/g, '').trim();
    if (p && p.length >= 2 && p.length <= 6 && !tags.includes(p)) tags.push(p);
  });
  if (/日本料理|寿司|日式|日料/.test(`${poi.keytag || ''};${poi.type || ''}`)) tags.unshift('日料');
  return [...new Set(tags)].slice(0, 5);
}

function extractHighlights(poi) {
  // atag 通常包含推荐菜/特色："炒饭,双人餐,素食,蘑菇"
  if (poi.atag && typeof poi.atag === 'string') {
    return poi.atag.split(',')
      .map(s => s.trim())
      .filter(s => s.length >= 2)
      .slice(0, 3);
  }
  return [];
}

function estimateWaitInfo(poi) {
  // 高德无排队数据，基于评分和价格估算一个合理的等位预期
  const rating = parseFloat(poi.biz_ext?.rating) || 0;
  const cost = parseFloat(poi.biz_ext?.cost) || 0;
  const hour = new Date().getHours();
  const isPeak = (hour >= 11 && hour <= 13) || (hour >= 17 && hour <= 20);

  // 高评分 + 高峰期 → 更多等位
  let baseWait = 0;
  if (rating >= 4.5 && isPeak) baseWait = 3 + Math.floor((rating - 4.5) * 10);
  else if (rating >= 4.0 && isPeak) baseWait = 1 + Math.floor((rating - 4.0) * 4);

  // 用餐厅名做确定性种子，避免每次结果不同
  const seed = (poi.name || '').split('').reduce((s, c) => s + c.charCodeAt(0), 0);
  const jitter = (seed % 5) - 2; // -2 ~ +2
  const currentWait = Math.max(0, baseWait + jitter);

  return {
    currentWait,
    avgWaitMinutes: currentWait > 0 ? currentWait * (7 + seed % 4) : 0,
  };
}

function poiToRestaurant(poi, area, index) {
  const biz = poi.biz_ext || {};
  const rating = parseFloat(biz.rating) || 0;
  const cost = parseFloat(biz.cost) || 0;

  // 营业时间：高德格式 "11:00-21:30 11:00-21:30"，取第一段
  let openHours = biz.open_time;
  if (!openHours || typeof openHours !== 'string') openHours = '';
  else if (openHours.includes(' ')) openHours = openHours.split(' ')[0];

  return {
    id: `r${String(index).padStart(3, '0')}`,
    name: cleanString(poi.name),
    cuisine: extractCuisine(poi),
    area,
    address: cleanString(poi.address),
    rating: rating || 4.0,
    pricePerPerson: cost || 80,
    tags: extractTags(poi),
    openHours,
    phone: extractPhone(poi),
    waitInfo: estimateWaitInfo(poi),
    highlights: extractHighlights(poi),
  };
}

// ── 缓存逻辑 ────────────────────────────────────────────────
function isCacheValid() {
  try {
    if (!fs.existsSync(OUTPUT_PATH)) return false;
    const state = JSON.parse(fs.readFileSync(STATE_PATH, 'utf-8'));
    const lastCrawl = state.restaurants?.lastCrawlTime;
    if (!lastCrawl) return false;
    return (Date.now() - new Date(lastCrawl).getTime()) < CACHE_TTL_MS;
  } catch { return false; }
}

function updateCrawlState(extra) {
  let state = {};
  try { state = JSON.parse(fs.readFileSync(STATE_PATH, 'utf-8')); } catch {}
  state.restaurants = { lastCrawlTime: new Date().toISOString(), ...extra };
  fs.writeFileSync(STATE_PATH, JSON.stringify(state, null, 2));
}

// ── 参数解析 ────────────────────────────────────────────────
function parseArgs(args) {
  const params = { areas: TARGET_AREAS, force: false };
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--area' && args[i + 1]) { params.areas = [args[++i]]; }
    else if (args[i] === '--force') { params.force = true; }
  }
  return params;
}

// ── 主逻辑 ──────────────────────────────────────────────────
async function main() {
  const options = parseArgs(process.argv.slice(2));

  if (!options.force && isCacheValid()) {
    const cached = JSON.parse(fs.readFileSync(OUTPUT_PATH, 'utf-8'));
    if (cached.restaurants && cached.restaurants.length > 0) {
      console.log(JSON.stringify(cached, null, 2));
      return;
    }
  }

  // 检查 API key
  if (!fs.existsSync(KEY_PATH)) {
    const result = { error: '未找到高德 API key', fallback: true, restaurants: [] };
    fs.writeFileSync(OUTPUT_PATH, JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
    return;
  }

  const allRestaurants = [];
  const seen = new Set();

  for (const area of options.areas) {
    try {
      const pois = await searchArea(area);
      for (const poi of pois) {
        const key = poi.name;
        if (seen.has(key)) continue;
        seen.add(key);
        allRestaurants.push(poiToRestaurant(poi, area, allRestaurants.length + 1));
      }
    } catch (e) {
      // 单个区域失败不影响其他区域
    }
    await sleep(300); // 避免 API 限速
  }

  const result = allRestaurants.length > 0
    ? { restaurants: allRestaurants, dataSource: 'amap', crawledAt: new Date().toISOString() }
    : { error: '高德 API 未返回数据', fallback: true, restaurants: [] };

  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(result, null, 2));
  updateCrawlState({ areas: options.areas.join(','), count: allRestaurants.length, dataSource: 'amap' });
  console.log(JSON.stringify(result, null, 2));
}

main().catch(e => {
  const result = { error: e.message, fallback: true, restaurants: [] };
  try { fs.writeFileSync(OUTPUT_PATH, JSON.stringify(result, null, 2)); } catch {}
  console.log(JSON.stringify(result, null, 2));
});
