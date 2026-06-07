const api = require("../../services/apiService");

Page({
  data: {
    safeTop: 80,
    title: "我的偏好与节奏",
    content: "",
    saving: false,
    docs: [],
    satelliteStatus: "状态读取中",
    satelliteRunning: false,
  },

  onLoad() {
    this.satelliteTimer = null;
    this.updateSafeTop();
    this.loadDocs();
    this.loadSatelliteStatus();
  },

  onUnload() {
    this.stopSatellitePolling();
  },

  updateSafeTop() {
    if (typeof wx.getMenuButtonBoundingClientRect !== "function") {
      return;
    }
    const rect = wx.getMenuButtonBoundingClientRect();
    if (rect && rect.bottom) {
      this.setData({ safeTop: rect.bottom + 10 });
    }
  },

  onTitleInput(e) {
    this.setData({ title: e.detail.value });
  },

  onContentInput(e) {
    this.setData({ content: e.detail.value });
  },

  saveCognition() {
    const title = String(this.data.title || "").trim();
    const content = String(this.data.content || "").trim();
    if (!content) {
      wx.showToast({ title: "请输入内容", icon: "none" });
      return;
    }
    this.setData({ saving: true });
    api.request({
      url: "/api/xhaus/self-cognition",
      method: "POST",
      data: { title, content },
    })
      .then(() => {
        this.setData({
          saving: false,
          content: "",
        });
        wx.showToast({ title: "已保存", icon: "none" });
        this.loadDocs();
      })
      .catch(() => {
        this.setData({ saving: false });
        wx.showToast({ title: "保存失败", icon: "none" });
      });
  },

  loadDocs() {
    api.request({ url: "/api/xhaus/self-cognition" })
      .then((response) => {
        this.setData({
          docs: ((response && response.data && response.data.documents) || []).slice(0, 20),
        });
      })
      .catch(() => this.setData({ docs: [] }));
  },

  formatSatelliteStatus(data) {
    const turns = typeof data.recent_turns === "number" ? `近两周 ${data.recent_turns} 条` : "近两周统计中";
    const status = data.running ? "运行中" : data.last_message || data.status || "待运行";
    return `${status} · ${turns}`;
  },

  loadSatelliteStatus() {
    return api.request({ url: "/api/xhaus/satellite/status" })
      .then((response) => {
        const data = (response && response.data) || {};
        this.setData({
          satelliteStatus: this.formatSatelliteStatus(data),
          satelliteRunning: !!data.running,
        });
        if (data.status === "completed") {
          this.stopSatellitePolling();
          this.loadDocs();
        }
        if (data.status === "error") {
          this.stopSatellitePolling();
        }
        return data;
      })
      .catch(() => this.setData({ satelliteStatus: "Satellite 不可用" }));
  },

  startSatellitePolling() {
    this.stopSatellitePolling();
    this.satelliteTimer = setInterval(() => this.loadSatelliteStatus(), 3000);
  },

  stopSatellitePolling() {
    if (this.satelliteTimer) {
      clearInterval(this.satelliteTimer);
      this.satelliteTimer = null;
    }
  },

  runSatelliteNow() {
    if (this.data.satelliteRunning) {
      return;
    }
    this.setData({
      satelliteRunning: true,
      satelliteStatus: "Satellite 正在整理近两周历史",
    });
    api.request({
      url: "/api/xhaus/satellite/run",
      method: "POST",
      data: { force: true, async: true },
    })
      .then((response) => {
        const data = (response && response.data) || {};
        this.setData({
          satelliteRunning: true,
          satelliteStatus: data.running ? this.formatSatelliteStatus(data) : "Satellite 已提交后台运行",
        });
        wx.showToast({ title: "Satellite 已开始运行", icon: "none" });
        this.startSatellitePolling();
      })
      .catch(() => {
        this.setData({ satelliteStatus: "正在确认后台状态..." });
        this.startSatellitePolling();
        wx.showToast({ title: "正在确认状态", icon: "none" });
      });
  },

  openDocument(e) {
    const name = e.currentTarget.dataset.name;
    if (!name) {
      return;
    }
    wx.navigateTo({
      url: `/pages/document/index?name=${encodeURIComponent(name)}`,
    });
  },

  deleteDocument(e) {
    const name = e.currentTarget.dataset.name;
    if (!name) {
      return;
    }
    wx.showModal({
      title: "删除文档",
      content: `确定删除 ${name} 吗？`,
      confirmText: "删除",
      confirmColor: "#9b5227",
      success: (modal) => {
        if (!modal.confirm) {
          return;
        }
        api.request({
          url: `/api/xhaus/self-cognition/${encodeURIComponent(name)}`,
          method: "DELETE",
        })
          .then(() => {
            wx.showToast({ title: "已删除", icon: "none" });
            this.loadDocs();
          })
          .catch((err) => {
            wx.showToast({
              title: (err && err.message) || "删除失败",
              icon: "none",
            });
          });
      },
    });
  },
});
