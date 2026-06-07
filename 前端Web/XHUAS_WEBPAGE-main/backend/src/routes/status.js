const express = require("express");
const openclawClient = require("../services/openclawClient");
const { sendOk } = require("../utils/response");

const router = express.Router();

router.get("/openclaw/status", async (req, res) => {
  const status = await openclawClient.ping();
  if (typeof status === "boolean") {
    return sendOk(res, { ok: status });
  }
  return sendOk(res, status);
});

module.exports = router;
