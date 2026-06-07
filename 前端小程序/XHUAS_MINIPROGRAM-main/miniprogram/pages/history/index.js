const conversationStore = require("../../services/conversationService");

Page({
  data: {
    safeTop: 80,
    conversations: [],
  },

  onLoad() {
    this.updateSafeTop();
  },

  onShow() {
    this.loadList();
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

  loadList() {
    this.setData({ conversations: conversationStore.listConversations() });
  },

  openConversation(e) {
    const id = e.currentTarget.dataset.id;
    conversationStore.setActiveId(id);
    wx.navigateBack();
  },

  newConversation() {
    conversationStore.setActiveId("");
    wx.navigateBack();
  },

  deleteConversation(e) {
    const id = e.currentTarget.dataset.id;
    conversationStore.deleteConversation(id);
    this.loadList();
  },
});
