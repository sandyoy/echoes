/**
 * pages/index/index.js — 首页（双界面）
 * 标准版：故事列表 + 成书 + 全部功能（v2.4 §3.3）
 * 大字版：就一个大按钮「按住说话」，其余收起（v2.4 §3.3）
 *
 * 待认领/认领线（小鲸鱼 09-27 接口 v1，形状已冻结）：
 *   登录成功后调 POST /api/echoes/claim/login → 拿 mentioned_count → 首页红点
 *   「有 N 篇故事提到了你」（N>0 才显示，整块可点进待认领页）
 *   被提到的人看「提到自己的那篇」永远不需要授权（v2.4 铁律）
 *
 * ⚠️ 大字版禁词（v2.4 §3.3）：凡出现「设置/权限/分享」字样即为失败。
 *    提到数那行在**大字版不显示**（首页大字版只有「按住说话」+「更多」），
 *    避免任何复杂元素；红点只在标准版露出。
 */
const app = getApp();
const api = require('../../utils/api.js');

Page({
  data: {
    uiMode: 'standard',
    stories: [],            // TODO(接口): 故事列表接口，等小鲸鱼后续交定义；当前为本地占位
    mentionedCount: 0,      // 有 N 篇故事提到了你（后端算，前端只显示）
    loginReady: false,      // claim/login 是否已成功过（本机登录态未接前的过渡）
    busy: false
  },

  onShow() {
    this.setData({ uiMode: app.getUiMode() });
    this.refreshMentioned();
  },

  /**
   * 登录态接入点（本机登录态未接前的过渡实现）
   * 真登录落定后，把 userId/phone 换成真实登录返回值即可，此处一行不改。
   * 登录成功后调一次 claim/login（幂等，重复登录不翻倍），把 N 存下 → 首页红点。
   */
  ensureClaimLogin() {
    const s = api.getSession();
    if (!s.userId) return Promise.resolve(null);   // 还没有真实登录态 → 跳过，不报案
    return api.claimLogin(s.userId, s.phone)
      .then((data) => {
        this.setData({
          mentionedCount: Number(data.mentioned_count || 0),
          loginReady: true
        });
        return data;
      })
      .catch(() => null);   // 后端未起/网络差 → 静默，不打扰老人
  },

  /** 拉「有 N 篇故事提到了你」。无登录态时用缓存值，不发请求（省一次往返、不报案） */
  refreshMentioned() {
    const cache = api.getMentionedCache();
    this.setData({ mentionedCount: Number(cache.count || 0) });
    this.ensureClaimLogin();
  },

  /** 点「有 N 篇故事提到了你」→ 进入待认领页（列出提到自己的故事） */
  onOpenMentioned() {
    if (this.data.mentionedCount <= 0) return;
    wx.navigateTo({ url: '/pages/claim/claim' });
  },

  /** 切换标准版 / 大字版（v2.4 §3.2：随时可切） */
  onToggleMode() {
    const next = app.getUiMode() === 'large' ? 'standard' : 'large';
    app.setUiMode(next);
    this.setData({ uiMode: next });
  },

  /** 大字版主入口：按住说话 → 采集页 */
  onHoldStart() {
    // TODO(接口): 录音 + ASR（后端 B/C 线，小鲸鱼负责）
    // 第1期先跳采集页，录音能力等接口定义
    wx.navigateTo({ url: '/pages/capture/capture?type=voice' });
  },

  onHoldEnd() {
    // 按住结束占位；真实录音 stop 由 ASR 接口接入后实现
  },

  /** 标准版：进入采集页（文字/语音/照片/视频 四类） */
  onCapture(e) {
    const type = (e && e.currentTarget && e.currentTarget.dataset.type) || 'text';
    wx.navigateTo({ url: `/pages/capture/capture?type=${type}` });
  },

  /** 进入成书页 */
  onOpenBook() {
    wx.navigateTo({ url: '/pages/book/book' });
  }
});
