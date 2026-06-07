#!/usr/bin/env node
/**
 * 真实路线规划脚本：高德地图 Web Service API
 * 用法：node crawl-route.js --from "中关村" --to "三里屯" --time "18:30" [--mode all|subway|taxi|walk|bike]
 *
 * 输出结构与 plan-route.js 的成功结果保持兼容：
 * { success, from, to, distance, departureTime, recommended, plans, dataSource }
 */

const fs = require('fs');
const path = require('path');
const https = require('https');

const AREAS_PATH = path.join(__dirname, '..', 'assets', 'mock-areas.json');
const KEY_PATH = path.join(__dirname, '..', 'assets', 'amap-key.txt');
const CITY = '北京';
const CITY_CODE = '010';

function parseArgs(args) {
  const params = {};
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    const v = args[i + 1];
    if (a === '--from' && v) { params.from = v; i++; }
    else if (a === '--to' && v) { params.to = v; i++; }
    else if (a === '--time' && v) { params.time = v; i++; }
    else if (a === '--mode' && v) { params.mode = v; i++; }
  }
  return params;
}

function loadKey() {
  try {
    const key = fs.readFileSync(KEY_PATH, 'utf-8').trim();
    if (!key || key === 'YOUR_AMAP_API_KEY_HERE') return null;
    return key;
  } catch {
    return null;
  }
}

function loadData() {
  return JSON.parse(fs.readFileSync(AREAS_PATH, 'utf-8'));
}

function resolveArea(input, areas) {
  if (!input) return null;
  if (areas[input]) return { key: input, data: areas[input] };
  // 最长匹配优先，避免「大」这种单字误匹配
  const candidates = [];
  for (const [key, data] of Object.entries(areas)) {
    if (input.includes(key)) candidates.push({ key, data, score: key.length });
    else if (input.length >= 2 && key.includes(input)) candidates.push({ key, data, score: input.length });
  }
  if (candidates.length === 0) return null;
  candidates.sort((a, b) => b.score - a.score);
  return { key: candidates[0].key, data: candidates[0].data };
}

function getAmapCoord(areaData) {
  return `${areaData.lon},${areaData.lat}`;
}

function parseTime(timeStr) {
  if (!timeStr) return new Date();
  const match = timeStr.match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return new Date();
  const date = new Date();
  date.setHours(Number(match[1]), Number(match[2]), 0, 0);
  return date;
}

function formatTime(date) {
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function addMinutes(date, minutes) {
  return new Date(date.getTime() + minutes * 60000);
}

function metersToKm(distance) {
  const meters = Number(distance || 0);
  return meters / 1000;
}

function formatDistance(distance) {
  return `${metersToKm(distance).toFixed(1)} km`;
}

function amapRequest(endpoint, params, version = 'v3') {
  return new Promise((resolve, reject) => {
    const key = loadKey();
    if (!key) {
      reject(new Error('缺少高德 API Key'));
      return;
    }

    const query = new URLSearchParams({ ...params, key, output: 'json' });
    const url = `https://restapi.amap.com/${version}/${endpoint}?${query}`;
    const req = https.get(url, { timeout: 12000 }, (res) => {
      let data = '';
      res.on('data', chunk => { data += chunk; });
      res.on('end', () => {
        try {
          const parsed = JSON.parse(data);
          if (parsed.status && parsed.status !== '1') {
            reject(new Error(parsed.info || parsed.infocode || '高德 API 请求失败'));
            return;
          }
          resolve(parsed);
        } catch (error) {
          reject(error);
        }
      });
    });
    req.on('timeout', () => req.destroy(new Error('高德 API 请求超时')));
    req.on('error', reject);
  });
}

function transitRoute(fromLonLat, toLonLat) {
  return amapRequest('direction/transit/integrated', {
    origin: fromLonLat,
    destination: toLonLat,
    city: CITY,
    strategy: 0,
  });
}

function drivingRoute(fromLonLat, toLonLat) {
  return amapRequest('direction/driving', {
    origin: fromLonLat,
    destination: toLonLat,
    strategy: 10,
    extensions: 'base',
  });
}

function walkingRoute(fromLonLat, toLonLat) {
  return amapRequest('direction/walking', {
    origin: fromLonLat,
    destination: toLonLat,
  });
}

async function bicyclingRoute(fromLonLat, toLonLat) {
  try {
    return await amapRequest('direction/bicycling', {
      origin: fromLonLat,
      destination: toLonLat,
    }, 'v4');
  } catch {
    return null;
  }
}

function extractBusLineName(segment) {
  const lines = segment?.bus?.buslines || [];
  if (!lines.length) return null;
  const line = lines[0];
  const name = line.name || '';
  const dep = line.departure_stop?.name || '';
  const arr = line.arrival_stop?.name || '';
  if (dep && arr) return `${name}（${dep} → ${arr}）`;
  return name || null;
}

function formatTransitDetail(transit) {
  const parts = [];
  for (const segment of transit.segments || []) {
    const walkingDistance = Number(segment.walking?.distance || 0);
    if (walkingDistance > 0 && parts.length === 0) {
      parts.push(`步行${walkingDistance}米`);
    }
    const bus = extractBusLineName(segment);
    if (bus) parts.push(bus);
  }
  return parts.length ? parts.join(' → ') : '高德公交/地铁推荐路线';
}

function buildTransitPlans(response, departure) {
  const transits = response?.route?.transits || [];
  return transits.slice(0, 3).map((transit, index) => {
    const durationMinutes = Math.max(1, Math.round(Number(transit.duration || 0) / 60));
    const costValue = Math.round(Number(transit.cost || 0));
    const arrival = addMinutes(departure, durationMinutes);
    return {
      mode: '🚇 地铁',
      duration: `${durationMinutes}分钟`,
      durationMinutes,
      cost: costValue > 0 ? `¥${costValue}` : '以高德为准',
      costValue,
      route: formatTransitDetail(transit),
      transfers: Math.max(0, (transit.segments || []).filter(s => extractBusLineName(s)).length - 1),
      arrivalTime: formatTime(arrival),
      dataSource: 'amap',
      pros: index === 0 ? ['高德实时公交/地铁路线', '含真实换乘信息'] : ['高德备选路线'],
      cons: [],
    };
  });
}

function buildTaxiPlan(response, transitResponse, departure) {
  const path0 = response?.route?.paths?.[0];
  if (!path0) return null;
  const distanceMeters = Number(path0.distance || 0);
  const durationMinutes = Math.max(1, Math.round(Number(path0.duration || 0) / 60));
  const amapTaxiCost = Number(transitResponse?.route?.taxi_cost || 0);
  const costValue = amapTaxiCost > 0
    ? Math.round(amapTaxiCost)
    : estimateTaxiCost(distanceMeters / 1000);
  return {
    mode: '🚕 打车',
    duration: `${durationMinutes}分钟`,
    durationMinutes,
    cost: `¥${costValue}`,
    costValue,
    distance: formatDistance(distanceMeters),
    route: path0.strategy || '高德驾车路线',
    arrivalTime: formatTime(addMinutes(departure, durationMinutes)),
    dataSource: 'amap',
    pros: ['高德实时路网估时', '门到门，最省力'],
    cons: [],
  };
}

function buildWalkPlan(response, departure) {
  const path0 = response?.route?.paths?.[0];
  if (!path0) return null;
  const durationMinutes = Math.max(1, Math.round(Number(path0.duration || 0) / 60));
  return {
    mode: '🚶 步行',
    duration: `${durationMinutes}分钟`,
    durationMinutes,
    cost: '免费',
    costValue: 0,
    distance: formatDistance(path0.distance),
    route: '高德步行路线',
    arrivalTime: formatTime(addMinutes(departure, durationMinutes)),
    dataSource: 'amap',
    pros: ['零花费'],
    cons: durationMinutes > 30 ? ['步行时间较长'] : [],
  };
}

function buildBikePlan(response, departure) {
  const data = response?.data || response?.route;
  const paths = data?.paths || [];
  const path0 = paths[0];
  if (!path0) return null;
  const durationMinutes = Math.max(1, Math.round(Number(path0.duration || 0) / 60));
  return {
    mode: '🚲 骑行',
    duration: `${durationMinutes}分钟`,
    durationMinutes,
    cost: '¥1.5-3（共享单车）',
    costValue: 2,
    distance: formatDistance(path0.distance),
    route: '高德骑行路线',
    arrivalTime: formatTime(addMinutes(departure, durationMinutes)),
    dataSource: 'amap',
    pros: ['灵活不堵车', '费用极低'],
    cons: [],
  };
}

function estimateTaxiCost(km) {
  if (km <= 3) return 13;
  return Math.round(13 + (km - 3) * 2.3);
}

function recommendScore(plan, distKm) {
  const mode = plan.mode || '';
  let penalty = 0;
  if (mode.includes('步行')) {
    if (distKm > 3) penalty += 9999;            // 步行超 3km 不作推荐
    else if (plan.durationMinutes > 30) penalty += 60;
  }
  if (mode.includes('骑行')) {
    if (distKm > 6) penalty += 9999;            // 骑行超 6km 不作首选
    else if (distKm > 4) penalty += 20;
  }
  // 时间为主、费用为辅
  return plan.durationMinutes + (plan.costValue || 0) * 0.3 + penalty;
}

function sortAndMarkRecommendation(plans, distKm) {
  plans.sort((a, b) => recommendScore(a, distKm) - recommendScore(b, distKm));
  plans.forEach(p => { p.recommendation = false; });
  if (plans[0]) plans[0].recommendation = true;
  return plans;
}

async function plan(params) {
  if (!params.from || !params.to) {
    return { success: false, error: '缺少参数：需要 --from <出发地> --to <目的地>' };
  }
  if (!loadKey()) {
    return { success: false, error: '缺少高德 API Key' };
  }

  const config = loadData();
  const fromArea = resolveArea(params.from, config.areas);
  const toArea = resolveArea(params.to, config.areas);
  if (!fromArea) {
    return { success: false, error: `无法识别出发地「${params.from}」` };
  }
  if (!toArea) {
    return { success: false, error: `无法识别目的地「${params.to}」` };
  }
  if (fromArea.key === toArea.key) {
    return {
      success: true,
      from: fromArea.key,
      to: toArea.key,
      sameArea: true,
      message: `出发地和目的地都在${fromArea.key}，步行即可到达，约 5-10 分钟。`,
      dataSource: 'amap',
    };
  }

  const departure = parseTime(params.time);
  const fromCoord = getAmapCoord(fromArea.data);
  const toCoord = getAmapCoord(toArea.data);
  const modeFilter = params.mode || 'all';
  const wants = mode => modeFilter === 'all' || modeFilter === mode;

  const [transit, driving, walking, bicycling] = await Promise.all([
    wants('subway') || wants('all') ? transitRoute(fromCoord, toCoord).catch(() => null) : null,
    wants('taxi') || wants('all') ? drivingRoute(fromCoord, toCoord).catch(() => null) : null,
    wants('walk') || wants('all') ? walkingRoute(fromCoord, toCoord).catch(() => null) : null,
    wants('bike') || wants('all') ? bicyclingRoute(fromCoord, toCoord) : null,
  ]);

  const plans = [];
  if (transit && (wants('subway') || wants('all'))) {
    plans.push(...buildTransitPlans(transit, departure));
  }
  if (driving && (wants('taxi') || wants('all'))) {
    const taxiPlan = buildTaxiPlan(driving, transit, departure);
    if (taxiPlan) plans.push(taxiPlan);
  }
  if (walking && (wants('walk') || wants('all'))) {
    const walkPlan = buildWalkPlan(walking, departure);
    if (walkPlan) plans.push(walkPlan);
  }
  if (bicycling && (wants('bike') || wants('all'))) {
    const bikePlan = buildBikePlan(bicycling, departure);
    if (bikePlan) plans.push(bikePlan);
  }

  const distance = transit?.route?.distance
    || driving?.route?.paths?.[0]?.distance
    || walking?.route?.paths?.[0]?.distance
    || 0;
  let distKm = metersToKm(distance);
  if (!distKm) {
    for (const p of plans) {
      const m = (p.distance || '').match(/([\d.]+)/);
      if (m) distKm = Math.max(distKm, Number(m[1]));
    }
  }

  sortAndMarkRecommendation(plans, distKm);
  if (plans.length === 0) {
    return { success: false, error: '高德未返回可用路线' };
  }

  return {
    success: true,
    from: fromArea.key,
    to: toArea.key,
    distance: distance ? formatDistance(distance) : undefined,
    departureTime: formatTime(departure),
    recommended: plans[0]?.mode || null,
    plans,
    query: { from: params.from, to: params.to, time: params.time || formatTime(departure), mode: params.mode || 'all' },
    dataSource: 'amap',
  };
}

(async () => {
  const result = await plan(parseArgs(process.argv.slice(2))).catch(error => ({
    success: false,
    error: error.message,
  }));
  console.log(JSON.stringify(result, null, 2));
})();
