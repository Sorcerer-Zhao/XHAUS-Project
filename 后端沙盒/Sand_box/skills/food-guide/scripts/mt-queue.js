#!/usr/bin/env node
/**
 * 美团排队通用 CLI — 零外部依赖，支持任意美团/点评门店
 *
 * 鉴权：通过 mt-passport CLI 获取 token（美团 passport OAuth）
 * API： 美团点评排队接口（m.dianping.com/queue/mdp/ajax/）
 *
 * 用法：
 *   node mt-queue.js index <shop_id>              查询桌型和排队状态
 *   node mt-queue.js take <shop_id> --people <N> --table <ID> [--force]  取号
 *   node mt-queue.js status <shop_id>             查排队进度
 *   node mt-queue.js cancel <shop_id>             取消排队
 *   node mt-queue.js search <关键词> [--city 北京]   搜索门店
 *
 * 环境变量：
 *   MT_QUEUE_TOKEN    手动传入 token（优先级最高，跳过 mt-passport）
 *   MT_PASSPORT_CLIENT_ID  美团 passport client_id
 */

const https = require('https');
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// ── 配置 ──────────────────────────────────────────────────────
const BASE_URL = 'https://m.dianping.com/queue/mdp/ajax/';
const CLIENT_ID = process.env.MT_PASSPORT_CLIENT_ID || '170f5f2dbbde4048bd4a5e4ed28209cc';
const TIMEOUT = 30000;

const STATUS_MAP = { 1: '取号中', 2: '排队中', 4: '已取消', 5: '已就餐', 6: '已过号', 7: '取号失败' };

// ── Token 获取 ────────────────────────────────────────────────
function getToken() {
  // 1. 环境变量优先
  if (process.env.MT_QUEUE_TOKEN) return process.env.MT_QUEUE_TOKEN;

  // 2. 尝试 mt-passport gettoken
  try {
    const result = execSync('mt-passport gettoken --client_id ' + CLIENT_ID, {
      encoding: 'utf-8', timeout: 10000, stdio: ['pipe', 'pipe', 'pipe']
    }).trim();
    if (result) return result;
  } catch (e) {
    // 无缓存或命令失败
  }

  // 3. 需要授权
  console.error('需要美团授权。运行: mt-passport auth --client_id ' + CLIENT_ID);
  console.error('或设置环境变量: export MT_QUEUE_TOKEN=<token>');
  process.exit(1);
}

// ── HTTP 请求 ─────────────────────────────────────────────────
function apiGet(endpoint, params, token) {
  return new Promise((resolve, reject) => {
    const query = new URLSearchParams(params).toString();
    const url = BASE_URL + endpoint + (query ? '?' + query : '');
    const req = https.get(url, {
      headers: {
        'User-Agent': 'MeituanQueue-OpenClaw/1.0',
        'Accept': 'application/json',
        'enterchannel': '2',
        'token': token,
      },
      timeout: TIMEOUT,
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const body = JSON.parse(data);
          if (body.code && body.code !== 200 && [302, 401, 403].includes(body.code)) {
            reject(new Error('登录已过期，请重新授权：mt-passport auth --client_id ' + CLIENT_ID + ' --force'));
            return;
          }
          resolve(body);
        } catch { reject(new Error('服务端返回异常响应')); }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('请求超时')); });
  });
}

function apiPost(endpoint, data, token) {
  return new Promise((resolve, reject) => {
    const postData = new URLSearchParams(data).toString();
    const url = BASE_URL + endpoint;
    const req = https.request(url, {
      method: 'POST',
      headers: {
        'User-Agent': 'MeituanQueue-OpenClaw/1.0',
        'Accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Content-Length': Buffer.byteLength(postData),
        'enterchannel': '2',
        'token': token,
      },
      timeout: TIMEOUT,
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch { reject(new Error('服务端返回异常响应')); }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('请求超时')); });
    req.write(postData);
    req.end();
  });
}

// ── 辅助函数 ──────────────────────────────────────────────────
function parseCapacity(desc) {
  const m = desc.match(/(\d+)-(\d+)/);
  if (m) return { min: parseInt(m[1]), max: parseInt(m[2]) };
  const s = desc.match(/(\d+)/);
  if (s) { const n = parseInt(s[1]); return { min: n, max: n }; }
  return { min: null, max: null };
}

function formatOrderDetail(d, shopId) {
  const shopName = d.shopName || ('门店' + shopId);
  const num = d.tableNumDesc || '—';
  const tableName = d.tableTypeName || '未知';
  const people = d.peopleCount || '?';
  const statusCode = d.queueOrderStatus || 0;
  const status = STATUS_MAP[statusCode] || ('未知(' + statusCode + ')');
  const waitTables = d.queueWaitTableNum || 0;
  const waitTime = d.willWaitTimeDesc || '';

  const lines = [
    '【' + shopName + '】排队订单',
    '排队号：' + num,
    '桌型：' + tableName + '（' + people + '人）',
    '状态：' + status,
    '前方等待：' + waitTables + '桌',
  ];
  if (waitTime) lines.push('预计等待：约' + waitTime + '分钟');
  return lines.join('\n');
}

// ── 命令实现 ──────────────────────────────────────────────────

async function cmdIndex(shopId, token) {
  const resp = await apiGet('queueIndexV2', { dpShopId: shopId }, token);
  if (resp.code && resp.code !== 200) {
    return '查询排队状态失败：' + (resp.errMsg || ('code=' + resp.code));
  }

  const data = resp.data || {};
  const shop = data.queueIndexShopVO || {};
  const shopName = shop.shopName || ('门店' + shopId);
  const support = shop.supportQueue || false;
  const tableInfos = shop.queueTableInfos || [];
  const orders = data.userQueueOrders || [];

  const lines = ['【' + shopName + '】'];

  // 已有订单
  if (orders.length > 0) {
    const latest = orders[0];
    const num = latest.tableNumDesc || '';
    lines.push('你已有排队订单（' + num + '），无需重复取号。可用 status 查看详情。');
    return lines.join('\n');
  }

  if (!support) {
    lines.push('该门店暂不支持在线排队。');
    return lines.join('\n');
  }

  // 桌型列表
  if (tableInfos.length > 0) {
    lines.push('');
    lines.push('可选桌型：');
    tableInfos.forEach(function(t) {
      const tid = t.tableTypeId || '?';
      const name = t.tableTypeName || '未知';
      const cap = t.tableCapacityDesc || '';
      const wait = t.waitCount || 0;
      const waitDesc = wait > 0 ? '排' + wait + '桌' : '无需等待';
      lines.push('  [' + tid + '] ' + name + '(' + cap + ') — ' + waitDesc);
    });
  } else {
    lines.push('当前无可用桌型。');
    return lines.join('\n');
  }

  lines.push('');
  lines.push('请选择桌型编号（方括号中的数字）和就餐人数进行取号。');
  return lines.join('\n');
}

async function cmdTake(shopId, peopleCount, tableTypeId, force, token) {
  // Step 1: 获取 index 以校验
  const indexResp = await apiGet('queueIndexV2', { dpShopId: shopId }, token);
  if (indexResp.code && indexResp.code !== 200) {
    return '取号失败：' + (indexResp.errMsg || ('code=' + indexResp.code));
  }

  const data = indexResp.data || {};

  // 检查已有订单
  const orders = data.userQueueOrders || [];
  if (orders.length > 0) {
    const latest = orders[0];
    const num = latest.tableNumDesc || '';
    return '你已有排队订单（' + num + '），无需重复取号。可用 status 查看详情，或 cancel 取消后重新取号。';
  }

  const queueState = data.queueIndexShopVO || {};
  const tableInfos = queueState.queueTableInfos || [];

  // 找到目标桌型
  let matchedInfo = null;
  for (let i = 0; i < tableInfos.length; i++) {
    if (tableInfos[i].tableTypeId === tableTypeId) {
      matchedInfo = tableInfos[i];
      break;
    }
  }

  if (!matchedInfo) {
    const available = tableInfos.map(function(t) {
      return '[' + t.tableTypeId + ']' + (t.tableTypeName || '');
    }).join(', ');
    return '取号失败：桌型 ' + tableTypeId + ' 不存在。可用桌型：' + (available || '无');
  }

  const tableTypeName = matchedInfo.tableTypeName || '';

  // 校验人数
  const capDesc = matchedInfo.tableCapacityDesc || '';
  const cap = parseCapacity(capDesc);
  if (cap.min !== null && cap.max !== null) {
    if (peopleCount < cap.min || peopleCount > cap.max) {
      return '就餐人数 ' + peopleCount + ' 与桌型 ' + tableTypeName + '(' + capDesc + ') 不匹配。该桌型适合 ' + cap.min + '-' + cap.max + ' 人，请调整人数或选择其他桌型。';
    }
  }

  // 空队确认
  const waitCount = matchedInfo.waitCount || 0;
  if (waitCount === 0 && !force) {
    const shopName = queueState.shopName || ('门店' + shopId);
    return '【' + shopName + '】' + tableTypeName + '(' + capDesc + ') 当前无人排队，但排队情况可能随时变化。如需确保位置，建议仍然取号。请用 --force 参数确认取号。';
  }

  // Step 2: 取号
  const orderData = {
    dpShopId: shopId,
    peopleCount: peopleCount,
    tableTypeId: tableTypeId,
    tableTypeName: tableTypeName,
  };
  // 尝试获取手机号
  const phone = data.phone || '';
  if (phone) orderData.phone = phone;

  const resp = await apiPost('queue', orderData, token);
  if (resp.code !== 200 || !resp.data) {
    return '取号失败：' + (resp.errMsg || '未知错误');
  }

  const orderId = resp.data.queueOrderViewId || '';
  if (!orderId) return '取号失败：未获取到订单号。';

  // Step 3: 轮询获取详情
  let detail = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt > 0) await sleep(1000);
    try {
      const detailResp = await apiGet('queueOrderDetail', { queueOrderViewId: orderId }, token);
      if (detailResp.code === 200 && detailResp.data) {
        const d = detailResp.data;
        if (d.queueOrderStatus !== 1) { detail = d; break; }
        detail = d;
      }
    } catch (e) { break; }
  }

  if (detail) {
    return '取号成功！\n\n' + formatOrderDetail(detail, shopId);
  }
  return '取号成功！\n桌型：' + tableTypeName + '（' + peopleCount + '人）\n订单号：' + orderId + '\n排队详情正在生成中，稍后可用 status 查看。';
}

async function cmdStatus(shopId, token) {
  const indexResp = await apiGet('queueIndexV2', { dpShopId: shopId }, token);
  if (indexResp.code && indexResp.code !== 200) {
    return '查询订单失败：' + (indexResp.errMsg || ('code=' + indexResp.code));
  }

  const orders = (indexResp.data || {}).userQueueOrders || [];
  if (orders.length === 0) return '当前无排队订单。';

  const latest = orders[0];
  const orderId = latest.queueOrderViewId || '';
  if (!orderId) return '当前无排队订单。';

  const resp = await apiGet('queueOrderDetail', { queueOrderViewId: orderId }, token);
  if (resp.code && resp.code !== 200) {
    return '查询订单详情失败：' + (resp.errMsg || ('code=' + resp.code));
  }

  const d = resp.data || {};
  if (!d || Object.keys(d).length === 0) return '查询订单详情失败。';
  return formatOrderDetail(d, shopId);
}

async function cmdCancel(shopId, token) {
  const indexResp = await apiGet('queueIndexV2', { dpShopId: shopId }, token);
  if (indexResp.code && indexResp.code !== 200) {
    return '查询订单失败：' + (indexResp.errMsg || ('code=' + indexResp.code));
  }

  const orders = (indexResp.data || {}).userQueueOrders || [];
  if (orders.length === 0) return '当前无排队订单，无需取消。';

  const orderId = orders[0].queueOrderViewId || '';
  if (!orderId) return '当前无排队订单。';

  const resp = await apiPost('cancelQueue', { queueOrderViewId: orderId }, token);
  if (resp.code === 200) return '排队已取消。';
  return '取消失败：' + (resp.errMsg || '未知错误');
}

// ── 门店搜索 ──────────────────────────────────────────────────
async function cmdSearch(keyword, city) {
  city = city || '北京';
  // 使用美团/点评内部搜索接口
  const token = getToken();

  return new Promise((resolve) => {
    const query = new URLSearchParams({
      keyword: keyword,
      cityName: city,
      start: '0',
      limit: '10',
    }).toString();

    const url = 'https://m.dianping.com/search/searchshop?' + query;
    const req = https.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)',
        'Accept': 'application/json',
        'token': token,
      },
      timeout: TIMEOUT,
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const body = JSON.parse(data);
          const shops = (body.searchShopList || body.shopList || []).slice(0, 10);
          if (shops.length === 0) {
            resolve('未找到匹配的门店。');
            return;
          }
          const lines = ['搜索「' + keyword + '」结果：', ''];
          shops.forEach(function(s, i) {
            const id = s.shopId || s.shopUuid || '?';
            const name = s.shopName || s.name || '未知';
            const addr = s.address || s.shopAddress || '';
            const stars = s.shopPower || s.avgScore || '';
            lines.push('  [' + (i + 1) + '] ' + name + '  shop_id=' + id);
            if (stars) lines.push('      评分：' + stars);
            if (addr) lines.push('      地址：' + addr);
          });
          resolve(lines.join('\n'));
        } catch {
          resolve('搜索失败：返回数据格式异常。');
        }
      });
    });
    req.on('error', () => resolve('搜索失败：网络异常。'));
    req.on('timeout', () => { req.destroy(); resolve('搜索超时。'); });
  });
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── 主入口 ────────────────────────────────────────────────────
async function main() {
  const args = process.argv.slice(2);
  const action = args[0];
  const shopId = args[1];

  if (!action || action === 'help' || action === '--help') {
    console.log([
      '美团排队通用 CLI — OpenClaw',
      '',
      '用法: node mt-queue.js <命令> [参数]',
      '',
      '命令:',
      '  index <shop_id>              查询桌型和排队状态',
      '  take <shop_id> --people <N> --table <ID> [--force]  取号排队',
      '  status <shop_id>             查询当前排队进度',
      '  cancel <shop_id>             取消排队',
      '  search <关键词> [--city <城市>]  搜索门店获取 shop_id',
      '',
      '环境变量:',
      '  MT_QUEUE_TOKEN       手动传入 token（跳过 mt-passport）',
      '  MT_PASSPORT_CLIENT_ID 美团 passport client_id',
      '',
      '示例:',
      '  node mt-queue.js search 海底捞',
      '  node mt-queue.js index 4211342',
      '  node mt-queue.js take 4211342 --people 2 --table 1',
      '  node mt-queue.js status 4211342',
      '  node mt-queue.js cancel 4211342',
    ].join('\n'));
    return;
  }

  if (action === 'search') {
    const keyword = shopId;
    if (!keyword) { console.log('请提供搜索关键词。'); return; }
    let city = '北京';
    const cityIdx = args.indexOf('--city');
    if (cityIdx !== -1 && args[cityIdx + 1]) city = args[cityIdx + 1];
    const result = await cmdSearch(keyword, city);
    console.log(result);
    return;
  }

  if (!shopId) {
    console.log('请提供门店 shop_id。先用 search 命令查找。');
    return;
  }

  const sid = parseInt(shopId);
  if (isNaN(sid)) { console.log('shop_id 必须是数字。'); return; }

  const token = getToken();

  try {
    let result;
    switch (action) {
      case 'index':
        result = await cmdIndex(sid, token);
        break;
      case 'take': {
        const peopleIdx = args.indexOf('--people');
        const tableIdx = args.indexOf('--table');
        const force = args.includes('--force');
        if (peopleIdx === -1 || tableIdx === -1) {
          console.log('take 需要 --people <人数> 和 --table <桌型ID> 参数。');
          return;
        }
        result = await cmdTake(sid, parseInt(args[peopleIdx + 1]), parseInt(args[tableIdx + 1]), force, token);
        break;
      }
      case 'status':
        result = await cmdStatus(sid, token);
        break;
      case 'cancel':
        result = await cmdCancel(sid, token);
        break;
      default:
        console.log('未知命令: ' + action + '。可用: index, take, status, cancel, search');
        return;
    }
    console.log(result);
  } catch (e) {
    console.log('错误：' + e.message);
  }
}

main();
