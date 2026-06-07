const api = require("../../services/apiService");

Page({
  data: {
    safeTop: 80,
    skillPath: "",
    forceSkill: false,
    installing: false,
    loadingSkills: false,
    skills: [],
    result: "等待选择 Skill。",
  },

  onLoad() {
    this.updateSafeTop();
    this.loadSkills();
  },

  onShow() {
    this.loadSkills();
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

  onSkillPathInput(e) {
    this.setData({ skillPath: e.detail.value });
  },

  onForceSkillChange(e) {
    this.setData({ forceSkill: e.detail.value });
  },

  useExampleSkill() {
    this.setData({
      skillPath: "test-skill-plain",
    });
  },

  loadSkills() {
    this.setData({ loadingSkills: true });
    api.request({
      url: "/api/xhaus/skills",
    })
      .then((response) => {
        const data = (response && response.data) || {};
        this.setData({
          loadingSkills: false,
          skills: data.skills || [],
        });
      })
      .catch(() => {
        this.setData({ loadingSkills: false });
      });
  },

  openSkill(e) {
    const name = e.currentTarget.dataset.name;
    if (!name) {
      return;
    }
    wx.navigateTo({
      url: `/pages/skillDetail/index?name=${encodeURIComponent(name)}`,
    });
  },

  deleteSkill(e) {
    const name = e.currentTarget.dataset.name;
    if (!name) {
      return;
    }
    wx.showModal({
      title: "删除 Skill",
      content: `确定删除 ${name} 吗？OpenClaw workspace 里的副本也会一起清理。`,
      confirmText: "删除",
      confirmColor: "#9b5227",
      success: (modal) => {
        if (!modal.confirm) {
          return;
        }
        api.request({
          url: `/api/xhaus/skills/${encodeURIComponent(name)}`,
          method: "DELETE",
        })
          .then(() => {
            wx.showToast({ title: "已删除", icon: "none" });
            this.loadSkills();
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

  installSkill() {
    const sourcePath = String(this.data.skillPath || "").trim();
    if (!sourcePath) {
      wx.showToast({ title: "请输入 Skill 目录", icon: "none" });
      return;
    }
    this.setData({
      installing: true,
      result: "正在装载...",
    });
    api.request({
      url: "/api/xhaus/skills/install",
      method: "POST",
      data: {
        source_path: sourcePath,
        force: this.data.forceSkill,
      },
    })
      .then((response) => {
        const data = (response && response.data) || {};
        const output = data.stdout || data.stderr || "Skill 已装载。";
        this.setData({
          installing: false,
          result: output.slice(0, 900),
        });
        this.loadSkills();
        wx.showToast({ title: "Skill 已装载", icon: "none" });
      })
      .catch((err) => {
        const data = (err && err.data) || {};
        this.setData({
          installing: false,
          result: (data.stderr || data.stdout || err.message || "Skill 装载失败").slice(0, 900),
        });
        wx.showToast({ title: "装载失败", icon: "none" });
      });
  },
});
