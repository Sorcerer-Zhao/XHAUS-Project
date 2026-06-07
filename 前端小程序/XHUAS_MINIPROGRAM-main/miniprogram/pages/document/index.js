const api = require("../../services/apiService");
const markdown = require("../../services/markdownService");

Page({
  data: {
    safeTop: 80,
    name: "",
    updatedAt: "",
    content: "",
    blocks: [],
    loading: true,
    editing: false,
    saving: false,
    deleting: false,
    error: "",
  },

  onLoad(options) {
    this.updateSafeTop();
    const name = decodeURIComponent(options.name || "");
    this.setData({ name });
    this.loadDocument(name);
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

  loadDocument(name) {
    if (!name) {
      this.setData({
        loading: false,
        error: "文档名为空",
      });
      return;
    }
    api.request({
      url: `/api/xhaus/self-cognition/${encodeURIComponent(name)}`,
    })
      .then((response) => {
        const doc = (response && response.data) || {};
        this.setData({
          loading: false,
          name: doc.name || name,
          updatedAt: doc.updated_at || "",
          content: doc.content || "",
          blocks: markdown.parseMarkdown(doc.content || ""),
          error: "",
        });
      })
      .catch((err) => {
        this.setData({
          loading: false,
          error: (err && err.message) || "文档读取失败",
        });
      });
  },

  toggleEdit() {
    this.setData({ editing: !this.data.editing });
  },

  onContentInput(e) {
    this.setData({ content: e.detail.value });
  },

  saveDocument() {
    const name = this.data.name;
    const content = String(this.data.content || "");
    if (!content.trim()) {
      wx.showToast({ title: "内容不能为空", icon: "none" });
      return;
    }
    this.setData({ saving: true });
    api.request({
      url: `/api/xhaus/self-cognition/${encodeURIComponent(name)}`,
      method: "PUT",
      data: { content },
    })
      .then((response) => {
        const data = (response && response.data) || {};
        this.setData({
          saving: false,
          editing: false,
          updatedAt: data.updated_at || this.data.updatedAt,
          blocks: markdown.parseMarkdown(content),
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

  deleteDocument() {
    const name = this.data.name;
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
        this.setData({ deleting: true });
        api.request({
          url: `/api/xhaus/self-cognition/${encodeURIComponent(name)}`,
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
