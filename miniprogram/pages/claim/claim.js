/**
 * pages/claim/claim.js — 待认领页
 *
 * 两条数据来源（对应小鲸鱼接口 v1 的两个点）：
 *   ①「提到了我」 GET /api/echoes/claim/mentioned?user_id=
 *      —— 有 N 篇故事提到了你（被提到的人看那篇永远不需要授权）
 *   ②「等写故事的人确认」 GET /api/echoes/claim/search?display_name=
 *      —— 手机号对不上时按名字找候选，候选 ≠ 生效，必须等登记人确认
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
    mode: 'mentioned',        // 'mentioned' | 'search'
    name: '',                 // 按名字搜索输入
    mentioned: { count: 0, stories: [] },
    candidates: { count: 0, hint: '', candidates: [] },
    loadingMentioned: false,
    loadingSearch: false
  },

  onLoad() {
    this.setData({ uiMode: app.getUiMode() });
    this.refreshMentioned();
  },

  onNameInput(e) {
    this.setData({ name: e.detail.value });
  },

  onSwitchMode(e) {
    this.setData({ mode: e.currentTarget.dataset.mode });
    if (this.data.mode === 'mentioned') this.refreshMentioned();
  },

  /** ① 有 N 篇故事提到了你（拉列表）。user_id 由 app.ensureLogin() 落定（微信 openid） */
  refreshMentioned() {
    const uid = (app.globalData && app.globalData.userId) || api.getSession().userId;
    if (!uid) {
      // 登录可能还在路上 —— 落定后重试一次
      this.setData({ mentioned: { count: 0, stories: [] } });
      app.ensureLogin().then(() => {
        if (app.globalData.userId) this.refreshMentioned();
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

  /** 点开某一篇提到我的故事（第1期：故事详情页未建，先提示） */
  onOpenStory() {
    // TODO(接口): 故事详情页（第2期）；被提到的人看「提到自己的那篇」永远不需要授权
    wx.showToast({ title: '故事详情页第2期上线', icon: 'none' });
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
