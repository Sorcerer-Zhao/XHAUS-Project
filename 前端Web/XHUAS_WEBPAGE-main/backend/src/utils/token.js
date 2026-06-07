const jwt = require("jsonwebtoken");
const { JWT_SECRET, SESSION_TTL_DAYS } = require("../config/env");

const TOKEN_TTL_SECONDS = SESSION_TTL_DAYS * 24 * 60 * 60;

function signToken(payload) {
  return jwt.sign(payload, JWT_SECRET, { expiresIn: TOKEN_TTL_SECONDS });
}

function verifyToken(token) {
  return jwt.verify(token, JWT_SECRET);
}

module.exports = {
  signToken,
  verifyToken,
  TOKEN_TTL_SECONDS,
};
