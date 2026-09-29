/**
 * 往事可追忆 v2.4 · 另起炉灶版
 * app.js — 全局状态：界面模式（标准/大字）+ 主题注入 + 登录态引导
 *
 * 设计依据：docs/需求书_往事可追忆_另起炉灶版_v2.4_20260923.md 第三节
 * 登录态依据：小鲸鱼《接口定义_登录态v1_20260929》（backend/login_api.py，自测 37/37）
 *   —— 进小程序第一件事：wx.login() → POST /api/echoes/login → 拿 user_id
 *      后续采集 6 类 + 认领 7 个接口**统一用它**，前端**不许再写死假 id**。
 * 铁律：大字版里凡出现「设置/权限/分享」字样，即为失败。
 */
const api = require('./utils/api.js');

App({
  globalData: {
    // 'standard' | 'large'  —— 全局界面模式，随时可切（v2.4 §3.2）
    uiMode: 'standard',
    // 故事 = 数据主体（v2.4 §2.1）
    currentStoryId: null,
    // 登录态（09-29 接真登录后由 login() 填）
    userId: '',
    isNewUser: false,
    sessionFrom: '',        // 'stub' | 'wechat' —— 后端不静默假装，前端可据此提示
    loginReady: false,
    // 后端基址。小龙虾 09-26 实测：本机已装 fastapi/uvicorn/sqlalchemy，
    //   后端适配器可在本地真跑（自测全过 + /docs 200 + 接口信封实测），
    //   本地联调：cd backend && python3 -m uvicorn api_adapter_fastapi:app --port 8012
    //   微信开发者工具需在「详情→本地设置」勾「不校验合法域名」才能连 127.0.0.1。
    apiBase: 'http://127.0.0.1:8012'
  },

  onLaunch() {
    // 记忆上次选择，打开即恢复（默认标准版）
    const saved = wx.getStorageSync('uiMode');
    if (saved === 'standard' || saved === 'large') {
      this.globalData.uiMode = saved;
    }
    // 登录态引导（异步，不阻塞启动；失败静默，各页按「未登录」渲染）
    this.ensureLogin();
  },

  /**
   * 登录（进小程序第一件事）
   * 联调期本机无微信 appid/secret → forceStub:true 走桩；生产环境自动走真 code2session。
   * 返回值 session_from 写明走的是 stub 还是 wechat，**不静默假装**。
   * @returns {Promise<object|null>} 登录 data；失败返回 null（不抛，老人不被打扰）
   */
  ensureLogin() {
    const g = this.globalData;
    // 已有登录态 → 只刷资料（含 ui_mode），不重复登录
    if (g.userId && g.loginReady) {
      return api.loginProfile(g.userId)
        .then((p) => { this.applyProfile(p); return p; })
        .catch(() => null);
    }
    return api.wxLoginCode()
      .then((code) => api.login({ code: code, forceStub: this.isDevEnv() }))
      .then((data) => {
        g.userId = data.user_id || '';
        g.isNewUser = !!data.is_new_user;
        g.sessionFrom = data.session_from || '';
        g.loginReady = !!g.userId;
        this.applyProfile(data.profile);
        // 后端算好的「有 N 篇提到了你」已由 api.login 存进 mentionedCache
        return data;
      })
      .catch(() => null);   // 后端未起/网络差 → 静默，各页按未登录渲染
  },

  /** profile.ui_mode 是 User 级持久设置，登录即应用（前端不自己存业务态） */
  applyProfile(profile) {
    const p = profile || {};
    if (p.ui_mode === 'standard' || p.ui_mode === 'large') {
      this.globalData.uiMode = p.ui_mode;
      wx.setStorageSync('uiMode', p.ui_mode);
    }
  },

  /** 联调环境判定：非正式版即本地联调（走 force_stub，稳拿伪 openid） */
  isDevEnv() {
    try {
      const info = wx.getAccountInfoSync && wx.getAccountInfoSync();
      return !info || !info.miniProgram || info.miniProgram.envVersion !== 'release';
    } catch (e) {
      return true;
    }
  },

  /** 切换界面模式（v2.4 §3.2：全局切换，不是注册时选一次） */
  setUiMode(mode) {
    if (mode !== 'standard' && mode !== 'large') return;
    this.globalData.uiMode = mode;
    wx.setStorageSync('uiMode', mode);
    // 已登录 → 同步到后端（User 级持久，下次进来 profile 就是它）
    const uid = this.globalData.userId;
    if (uid) api.loginSetUiMode(uid, mode).catch(() => null);
  },

  getUiMode() {
    return this.globalData.uiMode;
  }
});
