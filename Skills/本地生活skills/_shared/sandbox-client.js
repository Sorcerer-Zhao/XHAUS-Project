#!/usr/bin/env node
/**
 * dynamic-sandbox 统一 HTTP 适配层（Phase 2）
 *
 * 默认 Base: http://127.0.0.1:8787
 * 环境变量:
 *   SANDBOX_URL          覆盖 Base URL
 *   SANDBOX_TIMEOUT_MS   请求超时（默认 10000）
 */

const SANDBOX_BASE = (process.env.SANDBOX_URL || 'http://127.0.0.1:8787').replace(/\/$/, '');
const DEFAULT_TIMEOUT_MS = Number(process.env.SANDBOX_TIMEOUT_MS || 10000);

class SandboxError extends Error {
  constructor(message, { code, httpStatus, details } = {}) {
    super(message);
    this.name = 'SandboxError';
    this.code = code || 'SANDBOX_ERROR';
    this.httpStatus = httpStatus;
    this.details = details;
  }
}

function buildUrl(path, params) {
  const url = new URL(path.startsWith('http') ? path : `${SANDBOX_BASE}${path}`);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url;
}

async function request(method, path, { params, body, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  const url = buildUrl(path, params);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let res;
  let text = '';

  try {
    res = await fetch(url, {
      method,
      headers: body
        ? { 'Content-Type': 'application/json', Accept: 'application/json' }
        : { Accept: 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    text = await res.text();
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new SandboxError(`沙箱请求超时（${timeoutMs}ms）: ${url}`, { code: 'TIMEOUT' });
    }
    const refused =
      err.cause?.code === 'ECONNREFUSED' ||
      err.message?.includes('fetch failed') ||
      err.code === 'ECONNREFUSED';
    if (refused) {
      throw new SandboxError(
        `无法连接沙箱 ${SANDBOX_BASE}。请先启动: cd dynamic-sandbox && ./run.sh`,
        { code: 'UNAVAILABLE' }
      );
    }
    throw new SandboxError(err.message || String(err), { code: 'NETWORK_ERROR' });
  } finally {
    clearTimeout(timer);
  }

  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new SandboxError('沙箱返回非 JSON 响应', {
      code: 'INVALID_JSON',
      httpStatus: res.status,
      details: text.slice(0, 500),
    });
  }

  if (!res.ok) {
    const msg = data.detail || data.error || `HTTP ${res.status} ${res.statusText}`;
    throw new SandboxError(msg, { code: 'HTTP_ERROR', httpStatus: res.status, details: data });
  }

  return data;
}

async function get(path, params) {
  return request('GET', path, { params });
}

async function post(path, body) {
  return request('POST', path, { body });
}

async function checkHealth() {
  const data = await get('/health');
  if (!data || data.status !== 'ok') {
    throw new SandboxError('沙箱 health 检查失败', { code: 'UNHEALTHY', details: data });
  }
  return data;
}

function withSource(data) {
  if (!data || typeof data !== 'object') return data;
  return { source: 'sandbox', sandbox: SANDBOX_BASE, ...data };
}

function fail(error) {
  if (error instanceof SandboxError) {
    return {
      success: false,
      error: error.message,
      code: error.code,
      httpStatus: error.httpStatus,
      details: error.details,
    };
  }
  return { success: false, error: error.message || String(error), code: 'UNKNOWN' };
}

module.exports = {
  SANDBOX_BASE,
  SandboxError,
  buildUrl,
  get,
  post,
  checkHealth,
  withSource,
  fail,
};
