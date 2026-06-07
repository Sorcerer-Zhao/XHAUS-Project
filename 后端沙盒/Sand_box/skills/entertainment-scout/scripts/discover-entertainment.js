#!/usr/bin/env node
/** 兼容别名 → entertainment-query.js */
const { spawnSync } = require('child_process');
const path = require('path');
const r = spawnSync(process.execPath, [path.join(__dirname, 'entertainment-query.js'), ...process.argv.slice(2)], {
  stdio: 'inherit',
  env: process.env,
});
process.exit(r.status ?? 1);
