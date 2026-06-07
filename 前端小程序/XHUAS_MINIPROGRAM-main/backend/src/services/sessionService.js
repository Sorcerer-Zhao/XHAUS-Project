const crypto = require("crypto");
const redis = require("../utils/redis");

const SESSION_TTL_SECONDS = 60 * 60 * 2;
const MAX_HISTORY = 40;

function sessionKey(sessionId) {
  return `session:${sessionId}`;
}

function userKey(openid) {
  return `user_by_openid:${openid}`;
}

class SessionService {
  async getOrCreateUserId(openid) {
    const existing = await redis.get(userKey(openid));
    if (existing) {
      return existing;
    }
    const userId = `u_${crypto.randomUUID()}`;
    await redis.set(userKey(openid), userId);
    return userId;
  }

  async createSession({ userId, openid }) {
    const sessionId = `s_${crypto.randomUUID()}`;
    const session = this.buildSession({ sessionId, userId, openid });
    await this.saveSession(session);
    return session;
  }

  async createSessionWithId({ sessionId, userId, openid }) {
    const session = this.buildSession({ sessionId, userId, openid });
    await this.saveSession(session);
    return session;
  }

  async getSession(sessionId) {
    const raw = await redis.get(sessionKey(sessionId));
    if (!raw) {
      return null;
    }
    try {
      return JSON.parse(raw);
    } catch (err) {
      console.error("session_parse_failed", err);
      return null;
    }
  }

  async touchSession(sessionId) {
    const session = await this.getSession(sessionId);
    if (!session) {
      return null;
    }
    session.updatedAt = Date.now();
    await this.saveSession(session);
    return session;
  }

  async updateAgent(sessionId, agentId) {
    const session = await this.getSession(sessionId);
    if (!session) {
      return null;
    }
    session.agent = agentId;
    await this.saveSession(session);
    return session;
  }

  async appendMessages(sessionId, messages) {
    const session = await this.getSession(sessionId);
    if (!session) {
      return null;
    }
    session.messages = session.messages.concat(messages).slice(-MAX_HISTORY);
    await this.saveSession(session);
    return session;
  }

  async getHistory(sessionId) {
    const session = await this.getSession(sessionId);
    if (!session) {
      return null;
    }
    return session.messages.slice();
  }

  async deleteSession(sessionId) {
    await redis.del(sessionKey(sessionId));
  }

  async resetSession(oldSessionId, newSessionId) {
    const session = await this.getSession(oldSessionId);
    if (!session) {
      return null;
    }
    await this.deleteSession(oldSessionId);
    const sessionId = newSessionId || `s_${crypto.randomUUID()}`;
    const nextSession = this.buildSession({
      sessionId,
      userId: session.userId,
      openid: session.openid,
    });
    await this.saveSession(nextSession);
    return nextSession;
  }

  buildSession({ sessionId, userId, openid }) {
    const now = Date.now();
    return {
      sessionId,
      userId,
      openid,
      messages: [],
      createdAt: now,
      updatedAt: now,
      expiresAt: now + SESSION_TTL_SECONDS * 1000,
    };
  }

  async saveSession(session) {
    await redis.set(
      sessionKey(session.sessionId),
      JSON.stringify(session),
      "EX",
      SESSION_TTL_SECONDS
    );
  }
}

module.exports = new SessionService();
