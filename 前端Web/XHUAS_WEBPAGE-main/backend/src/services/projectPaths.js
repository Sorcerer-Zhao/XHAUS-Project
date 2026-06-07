const fs = require("fs");
const path = require("path");

function findProjectRoot() {
  const explicit = process.env.XHUAS_PROJECT_ROOT || process.env.XHAUS_PROJECT_ROOT;
  if (explicit) {
    return path.resolve(explicit);
  }

  let current = path.resolve(__dirname);
  for (let i = 0; i < 8; i += 1) {
    if (fs.existsSync(path.join(current, "XHAUS", "main.py"))) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      break;
    }
    current = parent;
  }

  return path.resolve(__dirname, "..", "..", "..");
}

const PROJECT_ROOT = findProjectRoot();
const BACKEND_ROOT = path.join(PROJECT_ROOT, "backend");
const XHAUS_ROOT = path.join(PROJECT_ROOT, "XHAUS");
const SATELLITE_ROOT = path.join(PROJECT_ROOT, "Satellite");

module.exports = {
  PROJECT_ROOT,
  BACKEND_ROOT,
  XHAUS_ROOT,
  SATELLITE_ROOT,
};
