const DRAFT_KEY = "xhaus_custom_profile_draft";

function readDraft() {
  try {
    return wx.getStorageSync(DRAFT_KEY) || { name: "", documents: [] };
  } catch (err) {
    return { name: "", documents: [] };
  }
}

function writeDraft(draft) {
  try {
    wx.setStorageSync(DRAFT_KEY, draft);
  } catch (err) {
    // Ignore storage failures.
  }
}

Page({
  data: {
    safeTop: 80,
    file: "",
    title: "",
    tip: "",
    content: "",
    error: "",
  },

  onLoad(options) {
    this.updateSafeTop();
    const file = decodeURIComponent(options.file || "");
    this.loadDocument(file);
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

  loadDocument(file) {
    const draft = readDraft();
    const doc = (draft.documents || []).find((item) => item.file === file);
    if (!doc) {
      this.setData({
        file,
        error: "没有找到这个人设文件，请返回重新进入。",
      });
      return;
    }
    this.setData({
      file,
      title: doc.title || file,
      tip: doc.tip || "",
      content: doc.content || "",
      error: "",
    });
  },

  onContentInput(e) {
    this.setData({ content: e.detail.value });
  },

  saveDocument() {
    const draft = readDraft();
    const documents = (draft.documents || []).map((doc) => {
      if (doc.file !== this.data.file) {
        return doc;
      }
      return Object.assign({}, doc, {
        content: this.data.content,
      });
    });
    writeDraft(Object.assign({}, draft, { documents }));
    wx.showToast({ title: "已保存草稿", icon: "none" });
    wx.navigateBack();
  },
});
