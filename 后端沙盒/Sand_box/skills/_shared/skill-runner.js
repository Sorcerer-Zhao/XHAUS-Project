#!/usr/bin/env node
/**
 * OpenClaw Skill 脚本统一运行器（Phase 3）
 *
 * 输出格式（Agent 友好）:
 * {
 *   "success": true,
 *   "action": "search_restaurants",
 *   "summary": "自然语言摘要，可直接复述给用户",
 *   "data": { ...结构化字段... },
 *   "source": "sandbox",
 *   "sandbox": "http://127.0.0.1:8787"
 * }
 */

const { fail, SANDBOX_BASE } = require('./sandbox-client');

/**
 * 解析 --key value 风格命令行参数。
 * schema 示例: { area: 'string', budget: 'number', people: 'number', id: 'string' }
 */
function parseFlags(argv, schema = {}) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i];
    if (token === '--help' || token === '-h') {
      out.help = true;
      continue;
    }
    if (!token.startsWith('--')) {
      out._.push(token);
      continue;
    }
    const rawKey = token.slice(2);
    const key = rawKey.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) {
      const type = schema[key] || schema[rawKey] || 'string';
      out[key] = type === 'number' ? Number(next) : next;
      i++;
    } else {
      out[key] = true;
    }
  }
  return out;
}

function ok(action, summary, data = {}) {
  return {
    success: true,
    action,
    data,
    source: 'sandbox',
    sandbox: SANDBOX_BASE,
    // 常用字段展开到顶层；summary 放最后，避免被 data 内同名字段覆盖
    ...data,
    summary,
  };
}

function emit(result) {
  console.log(JSON.stringify(result, null, 2));
}

async function run(handler) {
  try {
    const result = await handler();
    emit(result);
    if (result && result.success === false) process.exit(1);
  } catch (err) {
    const failed = fail(err);
    emit({ ...failed, action: 'error', summary: failed.error });
    process.exit(1);
  }
}

module.exports = { parseFlags, ok, emit, run };
