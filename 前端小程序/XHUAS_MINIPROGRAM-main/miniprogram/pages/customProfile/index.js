const api = require("../../services/apiService");

const DRAFT_KEY = "xhaus_custom_profile_draft";

function emptyDraft() {
  return {
    name: "",
    documents: [],
  };
}

function readDraft() {
  try {
    return wx.getStorageSync(DRAFT_KEY) || emptyDraft();
  } catch (err) {
    return emptyDraft();
  }
}

function writeDraft(draft) {
  try {
    wx.setStorageSync(DRAFT_KEY, draft);
  } catch (err) {
    // Keep the in-page copy if storage fails.
  }
}

Page({
  data: {
    safeTop: 80,
    loading: true,
    saving: false,
    name: "",
    documents: [],
  },

  onLoad(options = {}) {
    if (options.fresh === "1") {
      try {
        wx.removeStorageSync(DRAFT_KEY);
      } catch (err) {}
    }
    this.updateSafeTop();
    this.loadDraft();
  },

  onShow() {
    const draft = readDraft();
    if (draft.documents && draft.documents.length) {
      this.setData({
        name: draft.name || this.data.name,
        documents: draft.documents,
      });
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

  loadDraft() {
    const cached = readDraft();
    if (cached.documents && cached.documents.length) {
      this.setData({
        loading: false,
        name: cached.name || "",
        documents: cached.documents,
      });
      return;
    }

    api.request({ url: "/api/xhaus/custom-profiles/template" })
      .then((response) => {
        const documents = ((response && response.data && response.data.documents) || []);
        const draft = { name: "", documents };
        writeDraft(draft);
        this.setData({
          loading: false,
          documents,
        });
      })
      .catch(() => {
        this.setData({ loading: false });
        wx.showToast({ title: "模板读取失败", icon: "none" });
      });
  },

  onNameInput(e) {
    const name = e.detail.value;
    const draft = readDraft();
    const next = Object.assign({}, draft, {
      name,
      documents: this.data.documents,
    });
    writeDraft(next);
    this.setData({ name });
  },

  openDocument(e) {
    const file = e.currentTarget.dataset.file;
    if (!file) {
      return;
    }
    writeDraft({
      name: this.data.name,
      documents: this.data.documents,
    });
    wx.navigateTo({
      url: `/pages/customProfileEditor/index?file=${encodeURIComponent(file)}`,
    });
  },

  resetDraft() {
    wx.showModal({
      title: "重新开始",
      content: "会清空当前自定义管家的草稿。",
      confirmText: "清空",
      confirmColor: "#9b5227",
      success: (result) => {
        if (!result.confirm) {
          return;
        }
        try {
          wx.removeStorageSync(DRAFT_KEY);
        } catch (err) {}
        this.setData({
          loading: true,
          name: "",
          documents: [],
        });
        this.loadDraft();
      },
    });
  },

  saveProfile() {
    const name = String(this.data.name || "").trim();
    if (!name) {
      wx.showToast({ title: "请先给管家取名", icon: "none" });
      return;
    }
    if (!this.data.documents.length) {
      wx.showToast({ title: "文档还没准备好", icon: "none" });
      return;
    }

    this.setData({ saving: true });
    api.request({
      url: "/api/xhaus/custom-profiles",
      method: "POST",
      data: {
        label: name,
        documents: this.data.documents,
      },
      })
      .then((response) => {
        const data = response && response.data ? response.data : {};
        const provision = data.provision || {};
        try {
          wx.removeStorageSync(DRAFT_KEY);
        } catch (err) {}
        this.setData({ saving: false });
        wx.showModal({
          title: "已加入管家列表",
          content: provision.ok === false
            ? "人设文件已保存，但 OpenClaw Agent 同步失败。返回后再次选择这个管家会自动重试同步。"
            : "返回主界面后，再点“换管家”就能选用这个新人设。",
          showCancel: false,
          confirmText: "知道了",
          success: () => wx.navigateBack(),
        });
      })
      .catch((err) => {
        this.setData({ saving: false });
        wx.showToast({
          title: (err && err.message) || "保存失败",
          icon: "none",
        });
      });
  },
});
