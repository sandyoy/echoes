/**
 * pages/choose/choose.js — 付完 9.9 之后的二选一（2026-10-31）
 *
 * === 这一页为什么存在 ===
 * 9.9 卖的不是"半本书"，是**一条路的入口权**。钱一付，用户必须立刻在
 * 「转给爸妈」和「我自己先说」之间选一个 —— 这一屏就是那个岔路口。
 * 没有这一屏，9.9 就只是一次孤立的收款；有了它，钱才变成内容。
 *
 * === 三条不许破的规矩 ===
 * 1. **文案全部来自后端**（buttons[].label）：各端措辞必须一致，
 *    尤其"转给爸妈"这句，老人看到时不能有被推销感。
 * 2. **钱没到账不许放行**：bought=false 时不给按钮，只给"先去说两句"，
 *    因为免费层永远不拦人。**绝不假成功**。
 * 3. **一人一本**：sameBook=true 时不给新书，只让他接着这本说。
 *
 * === 进来时带什么 ===
 *   options.from  可选：'after_pay'（付完跳来）/ 'card'（从卡片点开）
 *   options.token 可选：gift 卡片凭据（老人点开卡片时走这条）
 */
const api = require('../../utils/api.js');

Page({
  data: {
    loading: true,
    bought: false,
    sameBook: false,
    question: '',
    buttons: [],
    card: null,
    userId: ''
  },

  onLoad(options) {
    this.opts = options || {};
    const session = api.getSession ? api.getSession() : {};
    const userId = (session && session.userId) || wx.getStorageSync('user_id') || '';
    this.setData({ userId });

    if (!userId) {
      // 没登录态：不猜身份，直接引导去说（免费层）
      this.setData({ loading: false, bought: false });
      return;
    }

    // 从卡片点开（老人侧）：先接受，再进说话；这条走 accept_gift
    if (this.opts.token) {
      this.acceptThenCapture(this.opts.token, userId);
      return;
    }

    this.loadChoices(userId);
  },

  /** 拉两个按钮 */
  loadChoices(userId) {
    api.payChoices(userId).then((d) => {
      this.setData({
        loading: false,
        bought: !!d.bought,
        sameBook: !!d.same_book,
        question: d.question || '这一页，给谁说？',
        buttons: d.buttons || [],
        card: null
      });
    }).catch((e) => {
      this.setData({ loading: false, bought: false });
      wx.showToast({ title: e.message || '没打开，稍后再试', icon: 'none' });
    });
  },

  /** 点了其中一个按钮 */
  onPick(e) {
    const key = e.currentTarget.dataset.key;
    const userId = this.data.userId;
    if (!key || !userId) return;

    // 已经有册子的"接着说" → 直接去说，不必再调 choose
    if (key === 'continue_self') {
      this.goCapture();
      return;
    }

    wx.showLoading({ title: '正在准备', mask: true });
    // 后端只认 self_first / gift_to_elder，前端 key 与之一致
    api.payChoose(userId, key).then((d) => {
      wx.hideLoading();
      if (d.path === 'gift' && d.card) {
        this.giftToken = (d.card && d.card.token) || '';
        this.setData({ card: d.card });
        return;
      }
      // self_first：当场开书 → 进说话
      this.goCapture(d.book_id);
    }).catch((e) => {
      wx.hideLoading();
      wx.showToast({ title: e.message || '没准备好，再点一次', icon: 'none' });
    });
  },

  /** 老人/家人点开卡片 → 接受 → 书归他 */
  acceptThenCapture(token, userId) {
    api.payAcceptGift(token, userId).then((d) => {
      this.setData({ loading: false });
      // 接受的人就是书主人，直接进说话界面，**不给他看"谁付的钱"**
      this.goCapture(d.book_id);
    }).catch((e) => {
      this.setData({ loading: false, bought: false });
      // 过期/失效：说人话，且给出口（先去说，说了不丢）
      wx.showModal({
        title: '这张卡打不开了',
        content: e.message || '让发给你的人重新发一张。你也可以先自己说两句。',
        confirmText: '先去说',
        showCancel: false,
        success: () => this.goCapture()
      });
    });
  },

  /** 去说话（免费层，永远放行） */
  goCapture(bookId) {
    let url = '/pages/capture/capture';
    const qs = [];
    if (bookId) qs.push('book_id=' + encodeURIComponent(bookId));
    if (qs.length) url += '?' + qs.join('&');
    wx.navigateTo({
      url,
      fail: () => wx.switchTab({ url: '/pages/index/index' })
    });
  },

  goBook() {
    wx.switchTab({ url: '/pages/book/book' });
  },

  closeCard() {
    this.setData({ card: null });
  },

  noop() {},

  copyLink() {
    const token = this.giftToken || (this.data.card && this.data.card.token) || '';
    if (!token) return;
    // 卡片链接走小程序页面（不进 web 分享页，避免老人点开还要装东西）
    const path = '/pages/choose/choose?token=' + encodeURIComponent(token);
    wx.setClipboardData({
      data: path,
      success: () => wx.showToast({ title: '已复制，粘贴给家里人', icon: 'none' })
    });
  },

  /** 微信右上角转发：卡片就是这张卡 */
  onShareAppMessage() {
    const token = this.giftToken || (this.data.card && this.data.card.token) || '';
    return {
      title: '给爸妈留一页，点开就能说',
      path: '/pages/choose/choose?token=' + encodeURIComponent(token),
      imageUrl: ''
    };
  }
});
