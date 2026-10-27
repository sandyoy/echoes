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
    loginPending: false,    // 正在登录（用于区分"稍等"和"失败"）
    loginError: '',         // 登录失败的中文原因；空=没失败。页面据此显式提示（2026-10-27）
    // 后端基址（公网正式环境）。
    //   2026-10-15 修正：真机 request 强制 HTTPS + 已备案域名，本机/局域网地址一律连不上
    //   （原 127.0.0.1:8012 / 192.168.1.86:8012 均废弃）。经小鲸鱼 10-15 回执确认并实测：
    //   https://yuanaikang.cn 为已备案域名 + HTTPS（Let's Encrypt，Nginx 反代后端 127.0.0.1:8971），
    //   /api/health、/api/stories/timeline、/api/memorial-book 公网均 200。
    //   ⚠️ 前置：sandy 需在微信公众平台「开发管理→开发设置→服务器域名→request 合法域名」加入
    //   https://yuanaikang.cn ，否则真机仍被微信拦截（仅 sandy 微信可操作）。
    //   本地联调（可选）：开发者工具「详情→本地设置」勾「不校验合法域名」后临时改回本机地址。
    apiBase: 'https://yuanaikang.cn'
  },

  onLaunch() {
    // 记忆上次选择，打开即恢复（默认标准版）
    const saved = wx.getStorageSync('uiMode');
    if (saved === 'standard' || saved === 'large') {
      this.globalData.uiMode = saved;
    }
    // 2026-10-27 自测埋点：把整个登录过程写进数组，页面可一键查看/复制，
    // 不用连开发者工具也能看到"到底哪一步断了"（sandy 不看模拟器，只看结论）
    this.diag = [];
    this._diag('onLaunch 开始', { apiBase: this.globalData.apiBase, isDevEnv: this.isDevEnv() });
    // 登录态引导（异步，不阻塞启动；失败会写 loginError，页面显式提示）
    this.ensureLogin();
    this.registerDiagHandle();
  },

  /** 记一条自测日志 */
  _diag(step, extra) {
    if (!this.diag) this.diag = [];
    const line = { t: new Date().toISOString().slice(11, 23), step: step, extra: extra };
    this.diag.push(line);
    console.log('[自测]', step, extra || '');
    if (this.diag.length > 100) this.diag.shift();
  },

  /** 把自测日志挂到全局，任何页面都能取 */
  registerDiagHandle() {
    // getApp().diag 本身就是句柄，这里只确保字段存在
    if (!this.diag) this.diag = [];
    this.getDiagText = () => (this.diag || []).map((l) => l.t + ' ' + l.step + ' ' + JSON.stringify(l.extra || {})).join('\n');
  },

  /**
   * 登录（进小程序第一件事）
   * 联调期本机无微信 appid/secret → forceStub:true 走桩；生产环境自动走真 code2session。
   * 返回值 session_from 写明走的是 stub 还是 wechat，**不静默假装**。
   *
   * 2026-10-27 修正（小龙虾）—— 原实现三个坑，导致真机「页面点了没反应」：
   *   ① `.catch(() => null)` 把错误全吞了，页面上看不到任何原因，sandy 只能靠猜；
   *   ② 登录失败后 globalData.loginFailed 从不置位，页面无法区分"还在登录"和"登录已失败"；
   *   ③ 微信 code 是一次性的，一次失败后 code 已作废，重试必须重新 wx.login()。
   *   改法：失败重试（重新取 code，最多 2 次）；失败时记下 lastError 并在页面显式提示。
   * @returns {Promise<object|null>} 成功返回 data；失败返回 null，但 **会** 把原因写进 globalData.loginError
   */
  ensureLogin() {
    const g = this.globalData;
    // 已有登录态 → 只刷资料（含 ui_mode），不重复登录
    if (g.userId && g.loginReady) {
      return api.loginProfile(g.userId)
        .then((p) => { this.applyProfile(p); return p; })
        .catch(() => null);
    }
    return this._loginWithRetry(0);
  },

  /**
   * 带重试的登录（2026-10-27 新增）
   * 为什么重试要重新 wx.login()：微信 code 一次性，第一次失败后旧 code 已作废，
   * 拿旧 code 再请求只会稳定复现 40029 invalid code，重试等于白试。
   * 三次都失败 → 写入 loginError，页面据此显示"登录没成功，点这里重试"，不再静默。
   */
  _loginWithRetry(attempt) {
    const g = this.globalData;
    const MAX_ATTEMPT = 3;          // 1 次 + 2 次重试
    g.loginPending = true;
    if (attempt === 0) { g.loginError = ''; }
    this._diag('登录开始', { attempt: attempt + 1, isDevEnv: this.isDevEnv() });

    return api.wxLoginCode()
      .then((code) => {
        this._diag('拿到 wx.login code', { len: (code || '').length, head: String(code || '').slice(0, 8) });
        return api.login({ code: code, forceStub: this.isDevEnv() });
      })
      .then((data) => {
        g.userId = data.user_id || '';
        g.isNewUser = !!data.is_new_user;
        g.sessionFrom = data.session_from || '';
        g.loginReady = !!g.userId;
        g.loginPending = false;
        g.loginError = g.loginReady ? '' : '没拿到用户身份';
        this.applyProfile(data.profile);
        this._diag('登录成功', {
          userId: g.userId, sessionFrom: g.sessionFrom, isNew: g.isNewUser,
          countStories: data.count_stories, mentioned: data.mentioned_count
        });
        // 后端算好的「有 N 篇提到了你」已由 api.login 存进 mentionedCache
        return data;
      })
      .catch((err) => {
        const msg = (err && err.message) || '登录失败';
        console.error('[ensureLogin] 第' + (attempt + 1) + '次失败：', msg, err && err.code);
        this._diag('登录失败', { attempt: attempt + 1, msg: msg, code: (err && err.code) || '' });
        if (attempt + 1 < MAX_ATTEMPT) {
          // 稍等再重试：短时间内连打微信接口容易连续失败
          return new Promise((resolve) => setTimeout(resolve, 400 * (attempt + 1)))
            .then(() => this._loginWithRetry(attempt + 1));
        }
        g.loginPending = false;
        g.loginReady = false;
        g.loginError = msg;        // 页面读它显示，不再用 catch(() => null) 吞掉
        this._diag('三次都失败，已置 loginError', { msg: msg });
        return null;
      });
  },

  /** profile.ui_mode 是 User 级持久设置，登录即应用（前端不自己存业务态） */
  applyProfile(profile) {
    const p = profile || {};
    if (p.ui_mode === 'standard' || p.ui_mode === 'large') {
      this.globalData.uiMode = p.ui_mode;
      wx.setStorageSync('uiMode', p.ui_mode);
    }
  },

  /**
   * 联调环境判定：**只有开发者工具**才算本地联调（走 force_stub，稳拿伪 openid）。
   *   2026-10-24 修正（小鲸鱼）：原判定 `envVersion !== 'release'` 把「扫码预览版/体验版」
   *   也当成本地调试 → 真机扫码永远走桩、拿不到真实 openid，测试结果全不可信。
   *   （注：v2.4 早期用 envVersion 的原意是"别污染正式数据"，但桩身份带来的污染更严重。）
   *
   *   2026-10-25 修正（小龙虾）：小鲸鱼的改法读错了对象 —— 官方文档里
   *   `wx.getAccountInfoSync().miniProgram` **只有** appId / envVersion / version，
   *   **没有 platform 字段**；`platform` 在 `wx.getDeviceInfo()` 上
   *   （合法值 devtools/android/ios/ohos/ohos_pc/windows/mac）。
   *   照原写法 `info.miniProgram.platform` 在真机上恒为 undefined → 恒判"联调" → 仍走桩，
   *   换了个地方再踩同一个坑。故改读 getDeviceInfo().platform，并按基础库版本兜底：
   *    getDeviceInfo 需 2.20.1；更低版本退回 envVersion（develop=开发者工具预览，trial/release=真机）。
   */
  isDevEnv() {
    try {
      // 首选：getDeviceInfo().platform（2.20.1+），唯一有 platform 的官方来源
      if (typeof wx.getDeviceInfo === 'function') {
        const dev = wx.getDeviceInfo() || {};
        if (dev.platform) return String(dev.platform) === 'devtools';
      }
      // 兜底：老基础库没有 getDeviceInfo，用 envVersion（缺字段时保守当联调）
      const info = wx.getAccountInfoSync && wx.getAccountInfoSync();
      const env = info && info.miniProgram && info.miniProgram.envVersion;
      if (!env) return true;
      return String(env) === 'develop';
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
