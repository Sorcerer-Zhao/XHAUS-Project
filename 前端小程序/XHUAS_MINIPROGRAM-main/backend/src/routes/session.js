const crypto = require("crypto");
const express = require("express");
const sessionService = require("../services/sessionService");
const { signToken, verifyToken, TOKEN_TTL_SECONDS } = require("../utils/token");
const { sendOk, sendError } = require("../utils/response");

const router = express.Router();

function extractAuth(req) {
  const authHeader = req.headers.authorization || "";
  const token = authHeader.replace(/^Bearer\s+/i, "").trim() || req.query?.token || "";
  const userId = req.query?.user_id || req.headers["x-user-id"] || "";
  const sessionId = req.params.session_id || req.query?.session_id || req.headers["x-session-id"] || "";
  return { token, userId, sessionId };
}

router.get("/session/:session_id/history", async (req, res) => {
  const { token, userId, sessionId } = extractAuth(req);
  if (!token) {
    return sendError(res, 40101, "missing_token", 401);
  }

  let payload = null;
  try {
    payload = verifyToken(token);
  } catch (err) {
    return sendError(res, 40102, "invalid_token", 401);
  }

  const authUserId = userId || payload.userId;
  const authSessionId = sessionId || payload.sessionId;
  if (payload.userId !== authUserId || payload.sessionId !== authSessionId) {
    return sendError(res, 40103, "token_mismatch", 401);
  }

  const session = await sessionService.getSession(authSessionId);
  if (!session || session.userId !== authUserId) {
    return sendError(res, 40401, "session_not_found", 404);
  }

  const messages = (await sessionService.getHistory(authSessionId)) || [];
  return sendOk(res, {
    session_id: authSessionId,
    messages,
  });
});

router.post("/session/reset", async (req, res) => {
  const authHeader = req.headers.authorization || "";
  const token = authHeader.replace(/^Bearer\s+/i, "").trim() || req.body?.token || "";
  const sessionId = req.headers["x-session-id"] || req.body?.session_id || "";

  if (!sessionId) {
    return sendError(res, 40010, "missing_session_id", 400);
  }
  if (!token) {
    return sendError(res, 40101, "missing_token", 401);
  }

  let payload = null;
  try {
    payload = verifyToken(token);
  } catch (err) {
    return sendError(res, 40102, "invalid_token", 401);
  }

  if (payload.sessionId !== sessionId) {
    return sendError(res, 40103, "token_mismatch", 401);
  }

  const session = await sessionService.getSession(sessionId);
  if (!session) {
    return sendError(res, 40401, "session_not_found", 404);
  }

  const newSessionId = crypto.randomBytes(16).toString("hex");
  const nextSession = await sessionService.resetSession(sessionId, newSessionId);
  if (!nextSession) {
    return sendError(res, 50010, "session_reset_failed", 500);
  }

  const nextToken = signToken({
    userId: nextSession.userId,
    sessionId: nextSession.sessionId,
  });

  return res.json({
    success: true,
    session_id: nextSession.sessionId,
    user_id: nextSession.userId,
    token: nextToken,
    expires_in: TOKEN_TTL_SECONDS,
    message: "session_reset",
  });
});

module.exports = router;
