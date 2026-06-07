const express = require("express");
const path = require("path");
const { PORT } = require("./config/env");
const loginRoutes = require("./routes/login");
const chatRoutes = require("./routes/chat");
const sessionRoutes = require("./routes/session");
const statusRoutes = require("./routes/status");
const xhausRoutes = require("./routes/xhaus");
const satelliteService = require("./services/satelliteService");

const app = express();

app.use(express.json({ limit: "2mb" }));
app.use(express.static(path.join(__dirname, "..", "public")));
app.use(
  "/assets",
  express.static(path.join(__dirname, "..", "..", "miniprogram", "images"))
);
app.use((req, res, next) => {
  console.log(`[${new Date().toISOString()}] ${req.method} ${req.url}`);
  next();
});

app.get("/health", (req, res) => {
  res.json({ status: "ok" });
});

app.use("/api", loginRoutes);
app.use("/api", chatRoutes);
app.use("/api", sessionRoutes);
app.use("/api", statusRoutes);
app.use("/api", xhausRoutes);

app.use((err, req, res, next) => {
  console.error("server_error", err);
  res.status(500).json({
    code: 50000,
    message: "internal_server_error",
    data: null,
  });
});

const server = app.listen(PORT, '0.0.0.0', () => {
  console.log(`server_listening_on_${PORT}`);
  satelliteService.startScheduler();
});

module.exports = {
  app,
  server,
};
