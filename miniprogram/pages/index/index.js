/**
 * pages/index/index.js — 首页（双界面）
 * 标准版：故事列表 + 成书 + 全部功能（v2.4 §3.3）
 * 大字版：就一个大按钮「按住说话」，其余收起（v2.4 §3.3）
 *
 * 登录态（小鲸鱼 09-29《接口定义_登录态v1》）：进小程序第一件事
 *   wx.login() → POST /api/echoes/login → user_id + profile.ui_mode + count_stories
 *   首页红点的 N 直接取登录返回的 count_stories（后端算，前端只显示），
 *   不再单独调 claim/login（该接口仍在，供按手机号自动认领场景）。
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
    loginReady: false,      // 登录是否已成功（真登录态）
    isNewUser: false,       // 首次进来（按此决定引导，v2.4）
    busy: false
  },

  onShow() {
    this.setData({ uiMode: app.getUiMode() });
    this.refreshMentioned();
  },

  /**
   * 拉「有 N 篇故事提到了你」。
   * 登录（app.ensureLogin，onLaunch 已发起）落定后同步一次；未登录时用缓存值，不发请求。
   */
  refreshMentioned() {
    const cache = api.getMentionedCache();
    this.setData({ mentionedCount: Number(cache.count || 0) });
    app.ensureLogin().then(() => {
      const g = app.globalData;
      if (!g.loginReady) return;
      const c = api.getMentionedCache();
      this.setData({
        mentionedCount: Number(c.count || 0),
        loginReady: true,
        isNewUser: !!g.isNewUser,
        uiMode: app.getUiMode()          // 登录会应用 profile.ui_mode
      });
    }).catch(() => null);
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
