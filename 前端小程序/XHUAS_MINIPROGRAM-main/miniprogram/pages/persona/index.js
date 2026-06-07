const api = require("../../services/apiService");

const FALLBACK_CHOICES = [
  { index: 1, value: "default_butler", label: "默认管家", kind: "preset" },
  { index: 2, value: "elegant_maid", label: "优雅女仆", kind: "preset" },
  { index: 3, value: "Emma", label: "Emma", kind: "preset" },
  { index: 4, value: "Franziska", label: "Franziska", kind: "preset" },
];

function decorateChoice(item) {
  return Object.assign({}, item, {
    kindLabel: item.kind === "custom_profile" ? "我的自定义管家" : "系统预设管家",
    canDelete: item.kind === "custom_profile",
    profileId: String(item.value || "").replace(/^custom:/, ""),
  });
}

Page({
  data: {
    safeTop: 80,
    loading: true,
    choices: [],
  },

  onLoad() {
    this.updateSafeTop();
    this.loadChoices();
  },

  onShow() {
    if (!this.data.loading) {
      this.loadChoices();
    }
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

  loadChoices() {
    this.setData({ loading: true });
    api.request({ url: "/api/xhaus/presets" })
      .then((response) => {
        const choices = ((response && response.data && response.data.choices) || [])
          .filter((item) => item.kind !== "custom")
          .map(decorateChoice);
        this.setData({
          loading: false,
          choices: choices.length ? choices : FALLBACK_CHOICES.map(decorateChoice),
        });
      })
      .catch(() => {
        this.setData({ loading: false, choices: FALLBACK_CHOICES.map(decorateChoice) });
        wx.showToast({ title: "请检查本机 backend 地址", icon: "none" });
      });
  },

  selectPersona(e) {
    const index = Number(e.currentTarget.dataset.index || 0);
    const choice = this.data.choices.find((item) => item.index === index);
    if (!choice) {
      return;
    }
    const channel = this.getOpenerEventChannel && this.getOpenerEventChannel();
    if (channel && channel.emit) {
      channel.emit("personaSelected", choice);
    }
    wx.navigateBack();
  },

  createProfile() {
    wx.navigateTo({ url: "/pages/customProfile/index?fresh=1" });
  },

  deletePersona(e) {
    const profileId = e.currentTarget.dataset.id;
    const label = e.currentTarget.dataset.label || "这个管家";
    if (!profileId) {
      return;
    }
    wx.showModal({
      title: "删除管家",
      content: `确定删除「${label}」吗？这会删除它的自定义人设文件和对应 workspace，不会影响系统预设。`,
      confirmText: "删除",
      confirmColor: "#9b5227",
      success: (result) => {
        if (!result.confirm) {
          return;
        }
        wx.showLoading({ title: "删除中" });
        api.request({
          url: `/api/xhaus/custom-profiles/${encodeURIComponent(profileId)}`,
          method: "DELETE",
        })
          .then(() => {
            wx.hideLoading();
            wx.showToast({ title: "已删除", icon: "success" });
            this.loadChoices();
          })
          .catch((err) => {
            wx.hideLoading();
            wx.showToast({
              title: (err && err.message) || "删除失败",
              icon: "none",
            });
          });
      },
    });
  },
});
