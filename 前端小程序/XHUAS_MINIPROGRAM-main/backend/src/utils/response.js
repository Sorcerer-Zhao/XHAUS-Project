function sendOk(res, data, message = "ok") {
  res.json({
    code: 0,
    message,
    data,
  });
}

function sendError(res, code, message, status = 400, data = null) {
  res.status(status).json({
    code,
    message,
    data,
  });
}

module.exports = {
  sendOk,
  sendError,
};
