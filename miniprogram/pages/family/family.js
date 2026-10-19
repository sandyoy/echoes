/**
 * pages/family/family.js —— 加家人页（v3.0 §2.2/§2.3）
 *
 * 派单：小鲸鱼《@小龙虾_加家人4路由已就绪请接前端+实测_20261016》
 * 后端：backend/family_api.py（4 条路由，HTTP 实测 36/36 全绿）
 *   ① GET  /api/echoes/family/list    —— 我的家人（已认领 / 待认领两栏）
 *   ② GET  /api/echoes/family/search   —— 按名字找人（对方已在小程序）
 *   ③ POST /api/echoes/family/add      —— 加家人 → 看整本（幂等，不许加自己）
 *   ④ POST /api/echoes/family/remove   —— 移出名单 → 不再能看整本
 *
 * 三条铁律（前端必须守）：
 *   1) owner_id 必传 —— 权限判定的根，缺了后端直接拒，绝不退化放行
 *   2) 手机号只回显 phone_masked（138****8000），前端不拿手机号做匹配
 *   3) 移除只动「家人名单」，不动单篇关系（后端保证，前端话术也要说清）
 *
 * 加家人的两条路（同一页，不建两个页面）：
 *   路 A：对方已经在小程序 → 输名字搜出来 → 点名字加（§2.3）
 *   路 B：对方还没上过 → 输手机号 + 称呼 → 直接加（§2.2），等他上来自动认领
 *
 * ⚠️ 本页不在大字版首页露出；但本页仍遵守大字版禁词（不出现「设置/权限/分享」）。
 */
const app = getApp();
const api = require('../../utils/api.js');

Page({
  data: {
    uiMode: 'standard',
    ownerId: '',              // 书的主人（= 当前登录人）
    loading: true,
    error: '',                // 中文人话，可直接显示

    // 名单（两栏）
    family: [],               // 已认领：能看整本
    pending: [],              // 待认领：等他上来自动接上
    familyCount: 0,
    pendingCount: 0,

    // 搜索（路 A）
    searchName: '',
    searching: false,
    searched: false,          // 搜过一次才显示"没找到"（避免一进来就说没找到）
    candidates: [],
    candidateCount: 0,

    // 直接加（路 B）
    addName: '',              // 对方怎么称呼（显示名，必填）
    addPhone: '',             // 手机号（11 位）
    addRelation: '',          // 关系（可空：儿子/女儿/老伴…）
    adding: false,

    removing: ''              // 正在移除的 member_id（防连点）
  },

  onLoad() {
    this.setData({ uiMode: app.getUiMode() });
    app.ensureLogin()
      .then(() => this._boot())
      .catch(() => this._boot());
  },

  onShow() {
    this.setData({ uiMode: app.getUiMode() });
  },

  onPullDownRefresh() {
    this.loadList().then(() => wx.stopPullDownRefresh());
  },

  _userId() {
    return (app.globalData && app.globalData.userId) || api.getSession().userId || '';
  },

  /** 登录落定后起步：owner_id = 我自己（本页只看自己的家人名单） */
  _boot() {
    const uid = this._userId();
    if (!uid) {
      this.setData({
        loading: false,
        error: '还没登录呢，登录一下就能加家人了'
      });
      return;
    }
    this.setData({ ownerId: uid });
    this.loadList();
  },

  // ===================== ① 名单 =====================

  loadList() {
    const ownerId = this.data.ownerId;
    if (!ownerId) return Promise.resolve();
    this.setData({ loading: true, error: '' });
    return api.familyList(ownerId)
      .then((d) => {
        const dd = d || {};
        this.setData({
          loading: false,
          family: dd.family || [],
          pending: dd.pending || [],
          familyCount: Number(dd.family_count || 0),
          pendingCount: Number(dd.pending_count || 0)
        });
      })
      .catch((err) => {
        this.setData({
          loading: false,
          error: (err && err.message) || '没取到家里人的名单，请稍后再试'
        });
      });
  },

  // ===================== ② 按名字找人（路 A） =====================

  onSearchInput(e) {
    this.setData({ searchName: (e.detail && e.detail.value) || '' });
  },

  onSearch() {
    const d = this.data;
    const name = (d.searchName || '').trim();
    if (!name) {
      wx.showToast({ title: '先写上他的名字', icon: 'none' });
      return;
    }
    if (d.searching) return;
    this.setData({ searching: true });
    api.familySearch(d.ownerId, name)
      .then((data) => {
        const dd = data || {};
        this.setData({
          searching: false,
          searched: true,
          candidates: dd.candidates || [],
          candidateCount: Number(dd.count || 0)
        });
      })
      .catch((err) => {
        this.setData({ searching: false, searched: true, candidates: [], candidateCount: 0 });
        wx.showModal({
          title: '没查成',
          content: (err && err.message) || '网络不太好，请稍后再试',
          showCancel: false
        });
      });
  },

  /** 点候选里的名字 → 加为家人（路 A 落点） */
  onPickCandidate(e) {
    const item = (e && e.currentTarget && e.currentTarget.dataset.item) || {};
    if (!item.user_id) return;
    if (item.already_family) {
      wx.showToast({ title: '他已经在你的家人里了', icon: 'none' });
      return;
    }
    this._add({
      userId: item.user_id,
      displayName: item.display_name || ''
    }, item.display_name || '这位家人');
  },

  // ===================== ③ 按手机号直接加（路 B） =====================

  onAddNameInput(e) {
    this.setData({ addName: (e.detail && e.detail.value) || '' });
  },

  onAddPhoneInput(e) {
    this.setData({ addPhone: (e.detail && e.detail.value) || '' });
  },

  onAddRelationInput(e) {
    this.setData({ addRelation: (e.detail && e.detail.value) || '' });
  },

  onAddByPhone() {
    const d = this.data;
    const name = (d.addName || '').trim();
    const phone = (d.addPhone || '').replace(/\s/g, '');
    if (!name) {
      wx.showToast({ title: '先写上他怎么称呼', icon: 'none' });
      return;
    }
    if (!/^\d{11}$/.test(phone)) {
      wx.showToast({ title: '手机号要 11 位数字', icon: 'none' });
      return;
    }
    this._add({
      phone: phone,
      displayName: name,
      relation: (d.addRelation || '').trim()
    }, name);
  },

  /** 加家人共用出口：成功 → 清表单 + 刷新名单（加完能立刻看见） */
  _add(payload, who) {
    const d = this.data;
    if (d.adding || !d.ownerId) return;
    this.setData({ adding: true });
    api.familyAdd(d.ownerId, payload)
      .then((res) => {
        const r = res || {};
        this.setData({
          adding: false,
          searchName: '',
          searched: false,
          candidates: [],
          candidateCount: 0,
          addName: '',
          addPhone: '',
          addRelation: ''
        });
        wx.showToast({
          title: r.already_family ? '他已经在里面了' : '加进来了',
          icon: 'success'
        });
        if (!r.already_family) {
          wx.showModal({
            title: '加好了',
            content: `${who}现在能看你这本书的全部 ${r.book_story_count || 0} 篇。`,
            showCancel: false
          });
        }
        this.loadList();
      })
      .catch((err) => {
        this.setData({ adding: false });
        // 后端已给中文人话（不许加自己 / 没找到这个人 / 要先登录…），直接弹给老人
        wx.showModal({
          title: '没加成',
          content: (err && err.message) || '网络不太好，请稍后再试',
          showCancel: false
        });
      });
  },

  // ===================== ④ 移出名单 =====================

  onRemove(e) {
    const item = (e && e.currentTarget && e.currentTarget.dataset.item) || {};
    const memberId = item.member_id;
    if (!memberId || this.data.removing) return;
    const name = item.display_name || '这位家人';
    wx.showModal({
      title: '把' + name + '移出去？',
      content: '移出去以后，他就看不到你这本书了。你单独给他看过的某一篇不受影响。',
      confirmText: '移出去',
      confirmColor: '#c0392b',
      success: (r) => {
        if (!r.confirm) return;
        this.setData({ removing: memberId });
        api.familyRemove(this.data.ownerId, memberId)
          .then(() => {
            this.setData({ removing: '' });
            wx.showToast({ title: '已经移出去了', icon: 'success' });
            this.loadList();
          })
          .catch((err) => {
            this.setData({ removing: '' });
            wx.showModal({
              title: '没移成',
              content: (err && err.message) || '网络不太好，请稍后再试',
              showCancel: false
            });
          });
      }
    });
  }
});
