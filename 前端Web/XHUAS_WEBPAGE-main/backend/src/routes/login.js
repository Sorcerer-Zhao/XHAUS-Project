const express = require("express");
const { WECHAT_APPID, WECHAT_APP_SECRET } = require("../config/env");
const sessionService = require("../services/sessionService");
const { signToken, TOKEN_TTL_SECONDS } = require("../utils/token");
const { sendOk, sendError } = require("../utils/response");

const router = express.Router();

router.post("/wechat/login", async (req, res) => {
  if (!WECHAT_APPID || !WECHAT_APP_SECRET) {
    return sendError(res, 50002, "wechat_credentials_missing", 500);
  }

  const code = req.body && req.body.code;
  if (!code) {
    return sendError(res, 40001, "missing_code", 400);
  }

  const url = new URL("https://api.weixin.qq.com/sns/jscode2session");
  url.searchParams.set("appid", WECHAT_APPID);
  url.searchParams.set("secret", WECHAT_APP_SECRET);
  url.searchParams.set("js_code", code);
  url.searchParams.set("grant_type", "authorization_code");

  try {
    const response = await fetch(url.toString());
    const data = await response.json();
    if (data.errcode) {
      return sendError(res, 40002, data.errmsg || "wechat_login_failed", 400);
    }

    const openid = data.openid;
    if (!openid) {
      return sendError(res, 40003, "missing_openid", 400);
    }

    const userId = await sessionService.getOrCreateUserId(openid);
    const session = await sessionService.createSession({ userId, openid });
    const token = signToken({ userId, sessionId: session.sessionId });

    return sendOk(res, {
      user_id: userId,
      session_id: session.sessionId,
      token,
      expires_in: TOKEN_TTL_SECONDS,
    });
  } catch (err) {
    console.error("wechat_login_error", err);
    return sendError(res, 50001, "wechat_login_error", 500);
  }
});

module.exports = router;
