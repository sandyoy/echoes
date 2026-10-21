/**
 * pages/story/story.js — 故事详情页（P0-2 · B 组 STORY.DETAIL）
 *
 * 依据：docs/双Hermes/任务总表_活地图.md P0-2「首页故事列表点了只传 id，没有详情页，老人点自己录的故事打不开」
 * 接口：GET /api/echoes/story/detail?story_id&owner_id&viewer_id（后端已就绪，本次前端接）
 *
 * 三条铁律（沿用时间轴/接口定义）：
 *   1) 权限判定只在后端 —— 前端只传 owner_id/viewer_id，不自己算谁能看
 *   2) 后端说不能看就显示后端那句中文人话，不自己编文案、不当报错炸给老人
 *   3) 不自己加工时间 —— time_raw 原样显示老人说法
 */
const api = require('../../utils/api.js');
const app = getApp();

Page({
  data: {
    uiMode: 'standard',
    loading: true,
    error: '',            // 中文人话，可直接显示
    storyId: '',
    ownerId: '',
    story: null,          // {story_id,title,raw_content,polished_content,time_raw,clips[],people_mentioned[]}
    clips: [],            // 这条故事下的素材
    canEdit: false,       // 是不是主人本人（只影响「设可见性」按钮露不露，真正的判定在后端）
    busy: false
  },

  onLoad(query) {
    const q = query || {};
    const storyId = q.story_id || '';
    const userId = (app.globalData && app.globalData.userId) || '';
    this.setData({
      uiMode: app.getUiMode(),
      storyId: storyId,
      ownerId: q.owner_id || userId
    });
    if (!storyId) {
      this.setData({ loading: false, error: '没找到这条故事' });
      return;
    }
    this.load();
  },

  onPullDownRefresh() {
    this.load().then(() => wx.stopPullDownRefresh()).catch(() => wx.stopPullDownRefresh());
  },

  /** 拉详情：先确保登录态（owner_id/viewer_id 都来自登录） */
  load() {
    this.setData({ loading: true, error: '' });
    return app.ensureLogin().then(() => {
      const g = app.globalData || {};
      const ownerId = this.data.ownerId || g.userId || '';
      const viewerId = g.userId || '';
      this.setData({ ownerId: ownerId, uiMode: app.getUiMode() });
      return api.storyDetail(this.data.storyId, ownerId, viewerId).then((d) => {
        const story = (d && (d.story || d)) || null;
        this.setData({
          loading: false,
          story: story,
          canEdit: !!viewerId && viewerId === ownerId
        });
        // story/detail 不带素材（后端 _story_summary 不含 clips）→ 单独拉 clip/list
        // 素材拉不到不算打开失败：正文照常给老人看，素材区留空不报错
        return api.clipList(this.data.storyId, viewerId, ownerId).then((cd) => {
          const list = (cd && (cd.clips || cd.list)) || [];
          this.setData({ clips: list });
        }).catch(() => { this.setData({ clips: [] }); });
      });
    }).catch((err) => {
      this.setData({
        loading: false,
        error: (err && err.message) || '这条故事一时打不开，稍后再试'
      });
    });
  },

  /** 正文：优先显示采访理顺后的成品，没有再显示原始内容 */
  getDisplayText() {
    const s = this.data.story || {};
    return s.polished_content || s.raw_content || '';
  },

  /** 素材「给家里人看 / 只给自己看」开关（C 组 CLIP.VISIBILITY，默认私有） */
  onToggleVisibility(e) {
    const clipId = (e && e.currentTarget && e.currentTarget.dataset.clipId) || '';
    const cur = (e && e.currentTarget && e.currentTarget.dataset.visibility) || 'private';
    if (!clipId || this.data.busy) return;
    const next = cur === 'public' ? 'private' : 'public';
    const actorId = (app.globalData && app.globalData.userId) || this.data.ownerId;
    this.setData({ busy: true });
    api.clipSetVisibility(clipId, actorId, next).then(() => {
      const clips = (this.data.clips || []).map((c) => (
        c.clip_id === clipId ? Object.assign({}, c, { visibility: next }) : c
      ));
      this.setData({ clips: clips, busy: false });
      wx.showToast({ title: next === 'public' ? '家里人能看了' : '已收回，只自己看', icon: 'none' });
    }).catch((err) => {
      this.setData({ busy: false });
      wx.showToast({ title: (err && err.message) || '没改成，稍后再试', icon: 'none' });
    });
  },

  /** 删这条故事 —— 二次确认，真删在后端，前端不自己从列表里偷删 */
  onDelete() {
    const story = this.data.story || {};
    const ownerId = this.data.ownerId;
    const actorId = (app.globalData && app.globalData.userId) || ownerId;
    wx.showModal({
      title: '删掉这条故事？',
      content: '删了就找不回来了',
      confirmText: '删掉',
      cancelText: '留着',
      success: (r) => {
        if (!r.confirm) return;
        this.setData({ busy: true });
        api.storyDelete(this.data.storyId, ownerId, actorId).then(() => {
          this.setData({ busy: false });
          wx.showToast({ title: '已删掉', icon: 'none' });
          setTimeout(() => {
            const pages = getCurrentPages();
            if (pages.length > 1) wx.navigateBack(); else wx.switchTab({ url: '/pages/index/index' });
          }, 600);
        }).catch((err) => {
          this.setData({ busy: false });
          wx.showToast({ title: (err && err.message) || '没删成，稍后再试', icon: 'none' });
        });
      }
    });
  },

  onBack() {
    const pages = getCurrentPages();
    if (pages.length > 1) wx.navigateBack();
    else wx.switchTab({ url: '/pages/index/index' });
  }
});
