#!/usr/bin/env node
/** 兼容别名 → mobility-plan.js */
const { spawnSync } = require('child_process');
const path = require('path');
const r = spawnSync(process.execPath, [path.join(__dirname, 'mobility-plan.js'), ...process.argv.slice(2)], {
  stdio: 'inherit',
  env: process.env,
});
process.exit(r.status ?? 1);
