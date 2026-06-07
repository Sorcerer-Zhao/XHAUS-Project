#!/usr/bin/env node
/**
 * 娱乐场所数据获取（高德 POI 搜索 API）
 *
 * 用法：node crawl-entertainment.js [--area <区域>] [--type movie|bar|ktv|spa|massage|all] [--force]
 * 输出：assets/real-entertainment.json
 *
 * 替代大众点评 Playwright 方案：无需浏览器，无反爬，数据来自高德地图。
 * 可获取：店名、评分、人均、地址、电话、营业时间、类型标签
 * 不可获取：电影场次、KTV 具体套餐、密室主题（用合理估算代替）
 */

const https = require('https');
const fs = require('fs');
const path = require('path');

const OUTPUT_PATH = path.join(__dirname, '..', 'assets', 'real-entertainment.json');
const STATE_PATH = path.join(__dirname, '..', 'assets', 'crawl-state.json');
const KEY_PATH = path.join(__dirname, '..', '..', 'mobility-planner', 'assets', 'amap-key.txt');
const CACHE_TTL_MS = 2 * 60 * 60 * 1000;
const TARGET_AREAS = ['望京', '三里屯', '朝阳大悦城', '国贸', '中关村', '五道口'];

// ── 娱乐类型搜索配置 ────────────────────────────────────────
const VENUE_TYPES = [
  { keyword: '电影院',     type: 'movie',           typeLabel: '🎬 电影',     amapType: '080600', limit: 3 },
  { keyword: '酒吧',       type: 'bar',             typeLabel: '🍸 酒吧',     amapType: '',       limit: 3 },
  { keyword: 'KTV',        type: 'ktv',             typeLabel: '🎤 KTV',      amapType: '080302', limit: 3 },
  { keyword: '密室逃脱',   type: 'escape_room',     typeLabel: '🔐 密室逃脱', amapType: '',       limit: 2 },
  { keyword: '剧本杀',     type: 'board_game',      typeLabel: '🎲 剧本杀',   amapType: '',       limit: 2 },
  { keyword: '公园',       type: 'park',            typeLabel: '🌿 公园',     amapType: '110101', limit: 2 },
  { keyword: '健身房',     type: 'fitness',         typeLabel: '💪 健身',     amapType: '',       limit: 2 },
  { keyword: '汤泉洗浴',   type: 'spa',             typeLabel: '♨️ 汤泉',    amapType: '',       limit: 3 },
  { keyword: '足疗按摩',   type: 'massage',         typeLabel: '💆 足疗',     amapType: '',       limit: 3 },
  { keyword: '台球',       type: 'billiards',       typeLabel: '🎱 台球',     amapType: '',       limit: 2 },
  { keyword: '商场购物',   type: 'shopping',        typeLabel: '🛍️ 逛街',    amapType: '',       limit: 2 },
  { keyword: '桌游',       type: 'board_game_cafe', typeLabel: '🎲 桌游吧',   amapType: '',       limit: 2 },
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

async function searchPOI(area, venueConfig) {
  const params = {
    keywords: `${area}${venueConfig.keyword}`,
    city: '北京',
    citylimit: 'true',
    offset: String(venueConfig.limit),
    page: '1',
    extensions: 'all',
  };
  if (venueConfig.amapType) params.types = venueConfig.amapType;

  const resp = await amapGet('place/text', params);
  if (resp.status !== '1' || !resp.pois) {
    // 可能被限速，等待后重试一次
    await sleep(1500);
    const retry = await amapGet('place/text', params);
    if (retry.status !== '1' || !retry.pois) return [];
    return retry.pois;
  }
  return resp.pois;
}

// ── POI → 娱乐场所 JSON 映射 ────────────────────────────────
function extractOpenHours(poi) {
  const biz = poi.biz_ext || {};
  let hours = biz.open_time;
  if (!hours || typeof hours !== 'string') return '';
  if (hours.includes(' ')) hours = hours.split(' ')[0];
  return hours;
}

function extractTags(poi) {
  const tags = [];
  if (poi.keytag && typeof poi.keytag === 'string') tags.push(poi.keytag);
  if (poi.atag && typeof poi.atag === 'string') poi.atag.split(',').forEach(t => { if (t.trim()) tags.push(t.trim()); });
  const typeParts = (poi.type || '').split(';');
  if (typeParts.length >= 3) {
    const last = typeParts[2].replace(/店|馆|厅|中心/g, '').trim();
    if (last && !tags.includes(last)) tags.push(last);
  }
  return [...new Set(tags)].filter(t => t.length >= 2 && t.length <= 8).slice(0, 5);
}

function estimatePriceRange(poi, venueType) {
  const cost = parseFloat(poi.biz_ext?.cost);
  if (!cost || cost <= 0) {
    // 无价格时按类型给默认
    const defaults = {
      movie: '45-120', bar: '100-300', ktv: '60-200/人', escape_room: '100-180/人',
      board_game: '80-150/人', park: '免费', fitness: '50-100/次', spa: '128-298/人',
      massage: '128-368/人', billiards: '40-80/小时', shopping: '免费（逛街）',
      board_game_cafe: '50-100/人',
    };
    return defaults[venueType] || '50-200';
  }
  // 用人均价格估算区间
  const low = Math.round(cost * 0.6);
  const high = Math.round(cost * 1.5);
  const suffix = ['ktv', 'escape_room', 'board_game', 'spa', 'massage', 'fitness', 'board_game_cafe']
    .includes(venueType) ? '/人' : '';
  return `${low}-${high}${suffix}`;
}

function generateKtvPackages(poi) {
  const cost = parseFloat(poi.biz_ext?.cost) || 80;
  return [
    { name: '欢唱2小时（小包）', capacity: '2-4人', price: Math.round(cost * 2.2), period: '18:00-23:00' },
    { name: '欢唱2小时（中包）', capacity: '4-8人', price: Math.round(cost * 3.5), period: '18:00-23:00' },
    { name: '夜场通宵（小包）', capacity: '2-4人', price: Math.round(cost * 3.8), period: '23:00-06:00' },
  ];
}

function generateSpaPackages(poi) {
  const cost = parseFloat(poi.biz_ext?.cost) || 150;
  return [
    { name: '单人泡汤', price: Math.round(cost * 0.8), duration: '不限时' },
    { name: '泡汤+汗蒸', price: Math.round(cost), duration: '不限时' },
    { name: '泡汤+汗蒸+自助', price: Math.round(cost * 1.5), duration: '不限时' },
  ];
}

function generateMassagePackages(poi) {
  const cost = parseFloat(poi.biz_ext?.cost) || 200;
  return [
    { name: '足底按摩 60min', price: Math.round(cost * 0.7) },
    { name: '全身推拿 90min', price: Math.round(cost) },
    { name: '精油SPA 120min', price: Math.round(cost * 1.5) },
  ];
}

function poiToVenue(poi, area, venueConfig, index) {
  const biz = poi.biz_ext || {};
  const rating = parseFloat(biz.rating) || 4.0;

  const venue = {
    id: `e${String(index).padStart(3, '0')}`,
    name: poi.name || '',
    type: venueConfig.type,
    typeLabel: venueConfig.typeLabel,
    area,
    address: poi.address || '',
    rating,
    priceRange: estimatePriceRange(poi, venueConfig.type),
    openHours: extractOpenHours(poi),
    tags: extractTags(poi),
  };

  // 按类型添加附加字段
  switch (venueConfig.type) {
    case 'ktv':
      venue.packages = generateKtvPackages(poi);
      venue.highlights = ['适合聚会', '可订包间', '晚间可玩'];
      break;
    case 'spa':
      venue.packages = generateSpaPackages(poi);
      venue.highlights = ['多种温泉/汗蒸', '休息区舒适', '适合放松'];
      break;
    case 'massage':
      venue.packages = generateMassagePackages(poi);
      venue.highlights = ['专业技师', '环境舒适', '可加钟'];
      break;
    case 'bar':
      venue.highlights = extractTags(poi).length > 0
        ? extractTags(poi).slice(0, 3)
        : ['氛围好', '适合小聚'];
      break;
    case 'park':
      venue.highlights = ['散步休闲', '免费开放', '适合饭后'];
      break;
    case 'shopping':
      venue.highlights = ['逛街购物', '网红打卡', '夜景好'];
      break;
    case 'billiards':
      venue.highlights = ['桌台新', '环境好', '适合朋友'];
      break;
    case 'board_game_cafe':
      venue.highlights = ['桌游丰富', '适合聚会'];
      break;
    case 'fitness': {
      // 生成几节常见课程
      const price = parseFloat(biz.cost) || 80;
      venue.classes = [
        { name: '搏击操', time: '19:30', duration: '50分钟', price: Math.round(price), spotsLeft: 5 },
        { name: '瑜伽', time: '20:30', duration: '60分钟', price: Math.round(price * 0.8), spotsLeft: 8 },
      ];
      venue.highlights = ['运动放松', '课程可选', '适合轻社交'];
      break;
    }
    case 'movie':
      venue.highlights = ['近期热映', '适合饭后', '可选晚场'];
      break;
    case 'escape_room':
      venue.highlights = ['沉浸体验', '适合多人', '需要预约'];
      break;
    case 'board_game':
      venue.highlights = ['剧情互动', '适合聚会', '多人参与'];
      break;
    // 电影场次/密室主题需要猫眼等专业源
  }

  return venue;
}

// ── 缓存逻辑 ────────────────────────────────────────────────
function isCacheValid() {
  try {
    if (!fs.existsSync(OUTPUT_PATH)) return false;
    const state = JSON.parse(fs.readFileSync(STATE_PATH, 'utf-8'));
    const lastCrawl = state.entertainment?.lastCrawlTime;
    if (!lastCrawl) return false;
    return (Date.now() - new Date(lastCrawl).getTime()) < CACHE_TTL_MS;
  } catch { return false; }
}

function updateCrawlState(extra) {
  let state = {};
  try { state = JSON.parse(fs.readFileSync(STATE_PATH, 'utf-8')); } catch {}
  state.entertainment = { lastCrawlTime: new Date().toISOString(), ...extra };
  fs.writeFileSync(STATE_PATH, JSON.stringify(state, null, 2));
}

// ── 参数解析 ────────────────────────────────────────────────
function parseArgs(args) {
  const params = { areas: TARGET_AREAS, type: 'all', force: false };
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--area' && args[i + 1]) { params.areas = [args[++i]]; }
    else if (args[i] === '--type' && args[i + 1]) { params.type = args[++i]; }
    else if (args[i] === '--force') { params.force = true; }
  }
  return params;
}

// ── 主逻辑 ──────────────────────────────────────────────────
async function main() {
  const options = parseArgs(process.argv.slice(2));

  if (!options.force && isCacheValid()) {
    const cached = JSON.parse(fs.readFileSync(OUTPUT_PATH, 'utf-8'));
    if (cached.venues && cached.venues.length > 0) {
      console.log(JSON.stringify(cached, null, 2));
      return;
    }
  }

  if (!fs.existsSync(KEY_PATH)) {
    const result = { error: '未找到高德 API key', fallback: true, venues: [] };
    fs.writeFileSync(OUTPUT_PATH, JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
    return;
  }

  // 按类型过滤
  const searchTypes = options.type === 'all'
    ? VENUE_TYPES
    : VENUE_TYPES.filter(v => v.type === options.type);

  const allVenues = [];
  const seen = new Set();

  for (const area of options.areas) {
    for (const vt of searchTypes) {
      try {
        const pois = await searchPOI(area, vt);
        for (const poi of pois) {
          const key = `${poi.name}`;
          if (seen.has(key)) continue;
          seen.add(key);
          allVenues.push(poiToVenue(poi, area, vt, allVenues.length + 1));
        }
      } catch {
        // 单个类型/区域失败不影响其他
      }
      await sleep(300); // 避免 API 限速
    }
  }

  const result = allVenues.length > 0
    ? { venues: allVenues, dataSource: 'amap', crawledAt: new Date().toISOString() }
    : { error: '高德 API 未返回数据', fallback: true, venues: [] };

  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(result, null, 2));
  updateCrawlState({
    areas: options.areas.join(','),
    type: searchTypes.map(v => v.type).join(','),
    count: allVenues.length,
    dataSource: 'amap',
  });
  console.log(JSON.stringify(result, null, 2));
}

main().catch(e => {
  const result = { error: e.message, fallback: true, venues: [] };
  try { fs.writeFileSync(OUTPUT_PATH, JSON.stringify(result, null, 2)); } catch {}
  console.log(JSON.stringify(result, null, 2));
});
