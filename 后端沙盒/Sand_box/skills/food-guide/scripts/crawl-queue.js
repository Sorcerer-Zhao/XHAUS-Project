#!/usr/bin/env node
/**
 * 爬虫脚本：餐厅实时排号状态
 * 用法：node crawl-queue.js --restaurant "<餐厅名>" --area "<区域>" [--headed]
 *
 * 输出：当前餐厅公开可见的排队状态。爬取失败或餐厅无线上排号时不抛错，
 * 返回 hasQueue=false，让 queue-number.js fallback 到模拟逻辑。
 */

const fs = require('fs');
const path = require('path');

function requirePlaywright() {
  try {
    return require('playwright');
  } catch (firstError) {
    try {
      return require('/opt/anaconda3/lib/python3.13/site-packages/playwright/driver/package');
    } catch (secondError) {
      const error = new Error(`无法加载 Playwright：${firstError.message}; ${secondError.message}`);
      error.cause = firstError;
      throw error;
    }
  }
}

const { chromium } = requirePlaywright();

const STATE_PATH = path.join(__dirname, '..', 'assets', 'crawl-state.json');
const OPERATION_TIMEOUT_MS = 30 * 1000;
const MOBILE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';

const SELECTORS = {
  shopList: '.shop-list li, .search-result-list .shop-item, [class*="shopItem"], [class*="shop-item"], a[href*="/shop/"], a[href*="/shopdetail/"]',
};

function parseArgs(args) {
  const params = { headed: false };
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    const v = args[i + 1];
    if (a === '--restaurant' && v) {
      params.restaurant = v;
      i++;
    } else if (a === '--area' && v) {
      params.area = v;
      i++;
    } else if (a === '--headed') {
      params.headed = true;
    }
  }
  return params;
}

function updateCrawlState(extra = {}) {
  let state = {};
  try {
    state = JSON.parse(fs.readFileSync(STATE_PATH, 'utf-8'));
  } catch {}
  state.queue = { lastCrawlTime: new Date().toISOString(), ...extra };
  fs.writeFileSync(STATE_PATH, JSON.stringify(state, null, 2));
}

async function politeDelay(page) {
  await page.waitForTimeout(1500 + Math.random() * 1000);
}

function withTimeout(promise, ms, label) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error(`${label} 超时`)), ms)),
  ]);
}

function cleanText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function localIsoString(date = new Date()) {
  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? '+' : '-';
  const abs = Math.abs(offsetMinutes);
  const pad = value => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

function looksBlocked(text) {
  return /验证中心|身份核实|短信登录|验证码|请登录|访问过于频繁|punish-component/.test(text);
}

function extractWaiting(text) {
  const cleaned = cleanText(text);
  const waiting = cleaned.match(/(?:等待|等位|前方|排队)[^\d]{0,8}(\d+)\s*(?:桌|组|位|人)/);
  const minutes = cleaned.match(/(?:预计|约|等待|需)[^\d]{0,8}(\d+)\s*(?:分钟|分)/);
  const looseWaiting = cleaned.match(/(\d+)\s*(?:桌|组|位)\s*(?:等待|等位|排队)?/);
  return {
    waiting: waiting ? Number(waiting[1]) : (looseWaiting ? Number(looseWaiting[1]) : null),
    estimatedMinutes: minutes ? Number(minutes[1]) : null,
  };
}

function parseQueueTexts(texts) {
  const joined = cleanText(texts.join(' '));
  if (!joined || /暂无线上排号|无排队|无需排队|不用等/.test(joined)) {
    return { hasQueue: false, message: '该餐厅暂无线上排号' };
  }

  const rows = texts.map(cleanText).filter(Boolean);
  const findByKeywords = keywords => {
    const row = rows.find(text => keywords.some(keyword => text.includes(keyword))) || joined;
    const parsed = extractWaiting(row);
    if (parsed.waiting === null && parsed.estimatedMinutes === null) return null;
    const waiting = Math.max(0, parsed.waiting || 0);
    const estimatedMinutes = Math.max(0, parsed.estimatedMinutes || waiting * 8);
    return { waiting, estimatedMinutes };
  };

  const small = findByKeywords(['小桌', '1-2', '2人', '两人']);
  const medium = findByKeywords(['中桌', '3-4', '4人']);
  const large = findByKeywords(['大桌', '5人', '6人', '多人']);
  const generic = extractWaiting(joined);

  if (!small && !medium && !large && generic.waiting === null && generic.estimatedMinutes === null) {
    return { hasQueue: false, message: '未发现公开排号信息' };
  }

  const fallbackWaiting = Math.max(0, generic.waiting || 0);
  const fallbackMinutes = Math.max(0, generic.estimatedMinutes || fallbackWaiting * 8);
  return {
    hasQueue: true,
    small: small || { waiting: Math.round(fallbackWaiting * 0.5), estimatedMinutes: Math.round(fallbackMinutes * 0.5) },
    medium: medium || { waiting: fallbackWaiting, estimatedMinutes: fallbackMinutes },
    large: large || { waiting: Math.round(fallbackWaiting * 0.3), estimatedMinutes: Math.round(fallbackMinutes * 0.7) },
  };
}

async function openFirstResult(page, restaurantName) {
  const links = await page.$$eval(SELECTORS.shopList, (nodes, name) => {
    const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
    return nodes.map(node => {
      const anchor = node.matches('a[href]') ? node : node.querySelector('a[href]');
      return {
        href: anchor ? anchor.href : '',
        text: clean(node.innerText || node.textContent),
      };
    }).filter(item => item.href && item.text && (!name || item.text.includes(name.replace(/\(.+\)$/, ''))));
  }, restaurantName).catch(() => []);

  if (!links.length) return false;
  await page.goto(links[0].href, { waitUntil: 'domcontentloaded', timeout: OPERATION_TIMEOUT_MS });
  await politeDelay(page);
  return true;
}

async function extractQueueTexts(page) {
  await page.getByText(/取号|排号|等位/).first().click({ timeout: 3000 }).catch(() => {});
  await politeDelay(page);
  return page.evaluate(() => {
    const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
    const keywords = /取号|排号|等位|等待|前方|小桌|中桌|大桌|预计|分钟|桌/;
    return Array.from(document.querySelectorAll('body *'))
      .map(node => clean(node.innerText || node.textContent))
      .filter(text => text && text.length < 300 && keywords.test(text))
      .slice(0, 80);
  });
}

async function crawlQueueStatus(page, restaurantName, area) {
  const query = `${area || ''} ${restaurantName}`.trim();
  const searchUrl = `https://m.dianping.com/search/keyword/2/10_${encodeURIComponent(query)}`;
  await page.goto(searchUrl, { waitUntil: 'domcontentloaded', timeout: OPERATION_TIMEOUT_MS });
  await politeDelay(page);

  const bodyText = await page.locator('body').innerText({ timeout: 5000 }).catch(() => '');
  if (looksBlocked(bodyText)) {
    return { hasQueue: false, message: '大众点评页面需要登录或验证，已切换到模拟排号' };
  }

  const opened = await openFirstResult(page, restaurantName);
  if (!opened) return { hasQueue: false, message: '未找到该餐厅' };

  const detailText = await page.locator('body').innerText({ timeout: 5000 }).catch(() => '');
  if (looksBlocked(detailText)) {
    return { hasQueue: false, message: '餐厅详情页需要登录或验证，已切换到模拟排号' };
  }

  const queueTexts = await extractQueueTexts(page);
  return parseQueueTexts(queueTexts);
}

async function crawl(options) {
  if (!options.restaurant) {
    return {
      restaurant: '',
      area: options.area || '',
      queueInfo: { hasQueue: false, message: '缺少 --restaurant' },
      crawledAt: localIsoString(),
    };
  }

  const browser = await chromium.launch({ headless: !options.headed });
  const context = await browser.newContext({
    userAgent: MOBILE_UA,
    viewport: { width: 390, height: 844 },
    locale: 'zh-CN',
  });

  try {
    const page = await context.newPage();
    const queueInfo = await withTimeout(
      crawlQueueStatus(page, options.restaurant, options.area || ''),
      OPERATION_TIMEOUT_MS,
      `${options.restaurant}排号爬取`
    ).catch(error => ({ hasQueue: false, message: error.message }));

    return {
      restaurant: options.restaurant,
      area: options.area || '',
      queueInfo,
      crawledAt: localIsoString(),
    };
  } finally {
    await browser.close().catch(() => {});
  }
}

(async () => {
  const options = parseArgs(process.argv.slice(2));
  let result;
  try {
    result = await crawl(options);
  } catch (error) {
    result = {
      restaurant: options.restaurant || '',
      area: options.area || '',
      queueInfo: { hasQueue: false, message: error.message },
      crawledAt: localIsoString(),
    };
  }

  updateCrawlState({
    restaurant: result.restaurant,
    area: result.area,
    hasQueue: Boolean(result.queueInfo && result.queueInfo.hasQueue),
  });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  process.exit(0);
})();
