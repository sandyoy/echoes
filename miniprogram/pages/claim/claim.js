/**
 * pages/claim/claim.js — 待认领页 + 「我也加进来」（加入链路）
 *
 * 数据来源（对应小鲸鱼接口）：
 *   ①「提到了我」 GET /api/echoes/claim/mentioned?user_id=
 *      —— 有 N 篇故事提到了你（被提到的人看那篇永远不需要授权）
 *   ②「等写故事的人确认」 GET /api/echoes/claim/search?display_name=
 *      —— 手机号对不上时按名字找候选，候选 ≠ 生效，必须等登记人确认
 *   ③「我加入的」 GET /api/echoes/join/mine?user_id=
 *      —— 我主动加进来的书/篇（加入链路落点，否则加完就丢）
 *
 * ★ 加入链路「我也加进来」（小鲸鱼 10-15，路由 61~63；需求书 v3.0 §8之二.5）
 *   路径 A（分享卡片进来）：onLoad({share_token}) → joinTarget → 篇末块「这是<X>的故事，里面提到了你」
 *   路径 B（点「提到了我」列表某篇）：onOpenStory(story_id) → 该篇篇末块
 *   两种路径都渲染同一个 joinBlock；点【我也加进来】→ 未登录先 wx 登录（参与才登录）→ joinByShare
 *   三条铁律（前端必须守）：只加这一篇 / 先有可见关系才能加 / 登录态才调
 *
 * 铁律（小鲸鱼 09-27 两个必守点）：
 *   1. 手机号一律脱敏回显（138****8000），前端**不拿回显手机号做匹配**，匹配在后端
 *   2. 候选 ≠ 生效：必须等写故事的人点确认（防重名冒领）
 *
 * ⚠️ 本页不在大字版首页露出，但本页仍遵守大字版禁词（不出现「设置/权限/分享」）。
 */
const app = getApp();
const api = require('../../utils/api.js');

Page({
  data: {
    uiMode: 'standard',
    mode: 'mentioned',        // 'mentioned' | 'search' | 'joined'
    name: '',                 // 按名字搜索输入
    mentioned: { count: 0, stories: [] },
    candidates: { count: 0, hint: '', candidates: [] },
    joined: { families: [], story_memberships: [], family_count: 0, story_count: 0 },
    loadingMentioned: false,
    loadingSearch: false,
    loadingJoined: false,

    // ★ 篇末「我也加进来」块（分享卡片进来 or 点开某篇时填充）
    joinBlock: {
      ready: false,           // 是否已拿到 target（未拿到不渲染块）
      shareToken: '',
      headline: '',           // 「这是李桂芳的故事，里面提到了你」
      ownerName: '',
      title: '',
      needLogin: false,       // 无 user_id
      alreadyJoined: false,   // 加过了 → 显示「你已经加进来了」
      canJoin: false,         // 能加 → 显示「我也加进来」
      reason: '',             // 不能加时的人话原因
      joining: false          // 按钮防连点
    }
  },

  onLoad(options) {
    this.setData({ uiMode: app.getUiMode() });
    const token = (options && options.share_token) || '';
    if (token) {
      // 路径 A：从分享卡片点开 → 直接进「篇末块」，其余列表照常拉
      this._openJoin({ shareToken: token });
    }
    this.refreshMentioned();
    this.refreshJoined();
  },

  onNameInput(e) {
    this.setData({ name: e.detail.value });
  },

  onSwitchMode(e) {
    const mode = e.currentTarget.dataset.mode;
    this.setData({ mode: mode });
    if (mode === 'mentioned') this.refreshMentioned();
    if (mode === 'joined') this.refreshJoined();
  },

  _userId() {
    return (app.globalData && app.globalData.userId) || api.getSession().userId || '';
  },

  /** ① 有 N 篇故事提到了你（拉列表）。user_id 由 app.ensureLogin() 落定（微信 openid） */
  refreshMentioned() {
    const uid = this._userId();
    if (!uid) {
      // 登录可能还在路上 —— 落定后重试一次
      this.setData({ mentioned: { count: 0, stories: [] } });
      app.ensureLogin().then(() => {
        if (this._userId()) this.refreshMentioned();
      }).catch(() => null);
      return;
    }
    this.setData({ loadingMentioned: true });
    api.claimMentioned(uid)
      .then((data) => this.setData({
        mentioned: { count: Number(data.count || 0), stories: data.stories || [] }
      }))
      .catch((e) => wx.showModal({ title: '没打开', content: e.message, showCancel: false }))
      .then(() => this.setData({ loadingMentioned: false }));
  },

  /** ③ 我加入的（书 + 篇）——加入链路的落点 */
  refreshJoined() {
    const uid = this._userId();
    if (!uid) {
      this.setData({ joined: { families: [], story_memberships: [], family_count: 0, story_count: 0 } });
      app.ensureLogin().then(() => {
        if (this._userId()) this.refreshJoined();
      }).catch(() => null);
      return;
    }
    this.setData({ loadingJoined: true });
    api.joinMine(uid)
      .then((d) => this.setData({
        joined: {
          families: (d && d.families) || [],
          story_memberships: (d && d.story_memberships) || [],
          family_count: Number((d && d.family_count) || 0),
          story_count: Number((d && d.story_count) || 0)
        }
      }))
      .catch(() => this.setData({ joined: { families: [], story_memberships: [], family_count: 0, story_count: 0 } }))
      .then(() => this.setData({ loadingJoined: false }));
  },

  /** ② 按名字搜索候选（手机号对不上时走这里）——结果只是候选 */
  onSearch() {
    const name = (this.data.name || '').trim();
    if (!name) { wx.showToast({ title: '先写上名字', icon: 'none' }); return; }
    this.setData({ loadingSearch: true });
    api.claimSearch(name)
      .then((data) => this.setData({
        candidates: {
          count: Number(data.count || 0),
          hint: data.hint || '须写故事的人确认后才会生效',
          candidates: data.candidates || []
        }
      }))
      .catch((e) => wx.showModal({ title: '没查成', content: e.message, showCancel: false }))
      .then(() => this.setData({ loadingSearch: false }));
  },

  /**
   * ★ 打开某篇的「篇末块」。
   * 若只给了 story_id（路径 B，从「提到了我」列表点进来），用的是后端该篇的分享令牌 ——
   * 这里按接口口径走 share_token；没有令牌时退化为提示（保持不假装成功）。
   */
  _openJoin(opts) {
    const o = opts || {};
    const token = o.shareToken || '';
    if (!token) {
      wx.showToast({ title: '这篇先不用加，你本来就能看', icon: 'none' });
      return;
    }
    const uid = this._userId();
    api.joinTarget(token, uid)
      .then((t) => {
        this.setData({
          joinBlock: {
            ready: true,
            shareToken: token,
            headline: t.headline || '',
            ownerName: t.owner_display_name || '',
            title: t.title || '',
            needLogin: !!t.need_login,
            alreadyJoined: !!t.already_joined,
            canJoin: !!t.can_join,
            reason: t.reason || '',
            joining: false
          }
        });
      })
      .catch((e) => wx.showModal({ title: '这个分享打不开了', content: e.message, showCancel: false }));
  },

  /** 点开「提到了我」列表某一篇 → 弹出该篇篇末块（分享令牌由后端分享接口给；此页无令牌时提示） */
  onOpenStory(e) {
    const sid = (e && e.currentTarget && e.currentTarget.dataset.storyId) || '';
    const token = (e && e.currentTarget && e.currentTarget.dataset.shareToken) || '';
    // 列表若带回 share_token 则直接开篇末块；否则按「你已可看这一篇」处理（被提及者本就无需授权）
    this._openJoin({ shareToken: token, storyId: sid });
  },

  /**
   * ★ 点【我也加进来】：先确保登录（参与才登录），再 joinByShare（默认加入这一篇）。
   * 铁律 3：无 user_id → 后端 login_required；前端这里主动先登录，不让老人看到英文码。
   */
  onJoinTap() {
    const b = this.data.joinBlock;
    if (!b || !b.ready || b.joining) return;
    if (b.alreadyJoined) return;
    if (!b.canJoin && !b.needLogin) {
      wx.showModal({ title: '这次加不了', content: b.reason || '你还没有加入这篇的资格', showCancel: false });
      return;
    }
    this.setData({ 'joinBlock.joining': true });

    const doJoin = (uid) => {
      if (!uid) {
        this.setData({ 'joinBlock.joining': false });
        wx.showModal({ title: '要先登录', content: '登录一下就能加进来啦', showCancel: false });
        return;
      }
      api.joinByShare(b.shareToken, uid)
        .then((d) => {
          this.setData({
            'joinBlock.alreadyJoined': true,
            'joinBlock.canJoin': false,
            'joinBlock.joining': false
          });
          wx.showToast({ title: d && d.already_joined ? '你已经在里面了' : '加进来啦', icon: 'success' });
          // 落地：刷新「提到了我」和「我加入的」，加完不丢
          this.refreshJoined();
          this.refreshMentioned();
        })
        .catch((err) => {
          this.setData({ 'joinBlock.joining': false });
          wx.showModal({ title: '没加成', content: err.message, showCancel: false });
        });
    };

    const uid = this._userId();
    if (uid) { doJoin(uid); return; }
    // 未登录 → 先走微信一键登录
    app.ensureLogin().then(() => doJoin(this._userId())).catch(() => doJoin(''));
  },

  /** 候选条目的说明：候选 ≠ 生效 */
  onCandidateTap() {
    wx.showModal({
      title: '等写故事的人确认',
      content: '找到的是候选。要等你家里人那边点一下确认，这篇才会挂到你名下。',
      showCancel: false
    });
  }
});
