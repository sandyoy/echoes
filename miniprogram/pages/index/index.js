/**
 * pages/index/index.js — 首页（双界面）
 * 标准版：定稿图「首页定稿_候选A_柔和版.png」形态 —— 顶部标题+副标+头像，主区三块平级卡
 *         （橙「自己说」/ 青「有人问我」/ 时间轴+我的书两小卡），下面「我的故事」列表
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
    stories: [],            // 故事列表（当前本地占位；P0-2 接 /story/list 后换真数据）
    mentionedCount: 0,      // 有 N 篇故事提到了你（后端算，前端只显示）
    loginReady: false,      // 登录是否已成功（真登录态）
    loginError: '',         // 登录失败原因（2026-10-27：不再静默，显式提示 + 可重试）
    showDiag: false,        // 自测面板是否展开
    diagLines: [],          // 自测日志行（app.diag 转成字符串）
    isNewUser: false,       // 首次进来（按此决定引导，v2.4）
    avatarText: '我',       // 右上角头像里的字（有昵称取首字）
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
      // 2026-10-27：登录失败不再静默 —— 把原因带到页面上，用户能看到"为什么点了没反应"
      if (!g.loginReady) {
        this.setData({
          loginReady: false,
          loginError: g.loginError || (g.loginPending ? '正在登录，稍等' : '登录没成功')
        });
        return;
      }
      const c = api.getMentionedCache();
      this.setData({
        mentionedCount: Number(c.count || 0),
        loginReady: true,
        loginError: '',
        isNewUser: !!g.isNewUser,
        uiMode: app.getUiMode()          // 登录会应用 profile.ui_mode
      });
    }).catch(() => null);
  },

  /** 展开/收起自测面板（2026-10-27） */
  onToggleDiag() {
    const next = !this.data.showDiag;
    const lines = (app.diag || []).map((l) => l.t + ' ' + l.step + ' ' + JSON.stringify(l.extra || {}));
    this.setData({ showDiag: next, diagLines: lines });
  },

  /** 复制自测日志（发给技术看，或自己留着对比） */
  onCopyDiag() {
    const text = (app.diag || []).map((l) => l.t + ' ' + l.step + ' ' + JSON.stringify(l.extra || {})).join('\n');
    wx.setClipboardData({
      data: text || '（还没有自测记录）',
      success: () => wx.showToast({ title: '已复制', icon: 'success' })
    });
  },

  /** 登录失败条点一下 → 重试登录（2026-10-27） */
  onRetryLogin() {
    const g = app.globalData;
    if (g.loginPending) { wx.showToast({ title: '正在登录', icon: 'none' }); return; }
    g.loginError = '';
    g.userId = '';
    g.loginReady = false;
    this.setData({ loginError: '' });
    wx.showLoading({ title: '正在登录' });
    app.ensureLogin().then(() => {
      wx.hideLoading();
      if (app.globalData.userId) {
        this.setData({ loginReady: true, loginError: '' });
        wx.showToast({ title: '登录好了', icon: 'success' });
      } else {
        this.setData({ loginError: app.globalData.loginError || '还是没成功' });
      }
    });
  },

  /** 点「有 N 篇故事提到了你」→ 进入待认领页（列出提到自己的故事） */
  onOpenMentioned() {
    if (this.data.mentionedCount <= 0) return;
    wx.navigateTo({ url: '/pages/claim/claim' });
  },

  /** 右上角头像：暂进「家里人」页（个人资料页尚未设计，不新造空页） */
  onOpenAvatar() {
    wx.navigateTo({
      url: '/pages/family/family',
      fail: () => { /* 家人页未就绪时静默，不打断 */ }
    });
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

  /** 卡1「现在就说」→ 进采集页（语音）。进门默认语音，其余录法在采集页里选 */
  onCaptureVoice() {
    wx.navigateTo({ url: '/pages/capture/capture?type=voice' });
  },

  /** 标准版：进入采集页（文字/语音/照片/视频 四类） */
  onCapture(e) {
    const type = (e && e.currentTarget && e.currentTarget.dataset.type) || 'text';
    wx.navigateTo({ url: `/pages/capture/capture?type=${type}` });
  },

  /** 卡2「开始聊」= 采访（v3.0 §6.0/§7.1：独立入口、与自述平级，直接进对话框） */
  onOpenInterview() {
    wx.navigateTo({
      url: '/pages/interview/interview',
      fail: () => { /* 采访页未就绪时静默，不打断 */ }
    });
  },

  /** 卡3「时间轴」（灵魂功能，v3.0 §五：时间轴是目录、故事是章节） */
  onOpenTimeline() {
    wx.navigateTo({
      url: '/pages/timeline/timeline',
      fail: () => { /* 时间轴页未就绪时静默 */ }
    });
  },

  /** 点故事卡 → 看故事详情（P0-2 新建 pages/story） */
  onTapStory(e) {
    const sid = (e && e.currentTarget && e.currentTarget.dataset.storyId) || '';
    if (!sid) return;
    wx.navigateTo({
      url: '/pages/story/story?story_id=' + encodeURIComponent(sid),
      fail: () => { /* 详情页未就绪时静默 */ }
    });
  },

  /** 卡3「我的书」→ 成书页 */
  onOpenBook() {
    wx.navigateTo({ url: '/pages/book/book' });
  },

  /** 家人页（v3.0 §2.2/§2.3）：现由底部 tabBar「家里人」承担，此方法保留给头像入口 */
  onOpenFamily() {
    wx.navigateTo({
      url: '/pages/family/family',
      fail: () => { /* 家人页未就绪时静默 */ }
    });
  }
});
