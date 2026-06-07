const api = require("../../services/apiService");

Page({
  data: {
    safeTop: 80,
    name: "",
    content: "",
    updatedAt: "",
    loading: true,
    saving: false,
    deleting: false,
    error: "",
  },

  onLoad(options) {
    this.updateSafeTop();
    const name = decodeURIComponent(options.name || "");
    this.setData({ name });
    this.loadSkill(name);
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

  loadSkill(name) {
    if (!name) {
      this.setData({
        loading: false,
        error: "Skill 名称为空",
      });
      return;
    }
    api.request({
      url: `/api/xhaus/skills/${encodeURIComponent(name)}`,
    })
      .then((response) => {
        const skill = (response && response.data) || {};
        this.setData({
          loading: false,
          name: skill.name || name,
          content: skill.content || "",
          updatedAt: skill.updated_at || "",
          error: "",
        });
      })
      .catch((err) => {
        this.setData({
          loading: false,
          error: (err && err.message) || "Skill 读取失败",
        });
      });
  },

  onContentInput(e) {
    this.setData({ content: e.detail.value });
  },

  saveSkill() {
    const name = this.data.name;
    const content = String(this.data.content || "");
    if (!content.trim()) {
      wx.showToast({ title: "内容不能为空", icon: "none" });
      return;
    }
    this.setData({ saving: true });
    api.request({
      url: `/api/xhaus/skills/${encodeURIComponent(name)}`,
      method: "PUT",
      data: { content },
    })
      .then((response) => {
        const data = (response && response.data) || {};
        this.setData({
          saving: false,
          updatedAt: data.skill ? data.skill.updated_at : this.data.updatedAt,
        });
        wx.showToast({ title: "已保存", icon: "none" });
      })
      .catch((err) => {
        this.setData({ saving: false });
        wx.showToast({
          title: (err && err.message) || "保存失败",
          icon: "none",
        });
      });
  },

  deleteSkill() {
    const name = this.data.name;
    if (!name) {
      return;
    }
    wx.showModal({
      title: "删除 Skill",
      content: `确定删除 ${name} 吗？这个操作会清理共享目录和 OpenClaw workspace 副本。`,
      confirmText: "删除",
      confirmColor: "#9b5227",
      success: (modal) => {
        if (!modal.confirm) {
          return;
        }
        this.setData({ deleting: true });
        api.request({
          url: `/api/xhaus/skills/${encodeURIComponent(name)}`,
          method: "DELETE",
        })
          .then(() => {
            wx.showToast({ title: "已删除", icon: "none" });
            wx.navigateBack();
          })
          .catch((err) => {
            this.setData({ deleting: false });
            wx.showToast({
              title: (err && err.message) || "删除失败",
              icon: "none",
            });
          });
      },
    });
  },
});
