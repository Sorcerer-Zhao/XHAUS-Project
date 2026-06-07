const { envList } = require("../envList");

const API_BASE_OVERRIDE_KEY = "xhaus_api_base";

function normalizeApiBase(base) {
  return String(base || "").trim().replace(/\/+$/, "");
}

function getApiBase() {
  try {
    const stored = wx.getStorageSync(API_BASE_OVERRIDE_KEY);
    if (stored) {
      return normalizeApiBase(stored);
    }
  } catch (err) {
    // Fall back to env config.
  }

  let envVersion = "develop";
  try {
    const accountInfo = wx.getAccountInfoSync && wx.getAccountInfoSync();
    if (accountInfo && accountInfo.miniProgram && accountInfo.miniProgram.envVersion) {
      envVersion = accountInfo.miniProgram.envVersion;
    }
  } catch (err) {
    // Use develop.
  }

  const matched = envList.find((item) => item.envVersion === envVersion);
  const develop = envList.find((item) => item.envVersion === "develop");
  return normalizeApiBase((matched && matched.apiBase) || (develop && develop.apiBase) || "http://127.0.0.1:3000");
}

function request({ url, method = "GET", data, headers }) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${getApiBase()}${url}`,
      method,
      data,
      header: Object.assign({ "Content-Type": "application/json" }, headers || {}),
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
          return;
        }
        reject(res.data || { message: "request_failed" });
      },
      fail(err) {
        reject(err);
      },
    });
  });
}

module.exports = {
  getApiBase,
  normalizeApiBase,
  request,
};
