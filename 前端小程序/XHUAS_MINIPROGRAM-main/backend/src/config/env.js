const dotenv = require("dotenv");

dotenv.config();

const required = ["JWT_SECRET"];

const missing = required.filter((key) => !process.env[key]);
if (missing.length) {
  throw new Error(`Missing required env: ${missing.join(", ")}`);
}

const SESSION_TTL_DAYS = parseInt(process.env.SESSION_TTL_DAYS || "30", 10);
const PORT = parseInt(process.env.PORT || "3000", 10);

module.exports = {
  PORT,
  WECHAT_APPID: process.env.WECHAT_APPID || "",
  WECHAT_APP_SECRET: process.env.WECHAT_APP_SECRET || "",
  OPENCLAW_AUTHORIZATION: process.env.OPENCLAW_AUTHORIZATION || "",
  OPENCLAW_CHAT_COMPLETIONS_URL: process.env.OPENCLAW_CHAT_COMPLETIONS_URL || "",
  OPENCLAW_GATEWAY_URL: process.env.OPENCLAW_GATEWAY_URL || "",
  OPENCLAW_GATEWAY_TOKEN: process.env.OPENCLAW_GATEWAY_TOKEN || "",
  OPENCLAW_CONFIG_PATH: process.env.OPENCLAW_CONFIG_PATH || "",
  OPENCLAW_STATE_DIR: process.env.OPENCLAW_STATE_DIR || "",
  OPENCLAW_SESSION_KEY: process.env.OPENCLAW_SESSION_KEY || "",
  XHAUS_DEFAULT_WEBSOCKET: process.env.XHAUS_DEFAULT_WEBSOCKET || "ws://127.0.0.1:18789",
  JWT_SECRET: process.env.JWT_SECRET,
  SESSION_TTL_DAYS,
};
