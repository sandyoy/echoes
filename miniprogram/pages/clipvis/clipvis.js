/**
 * pages/clipvis/clipvis.js —— 哪段能给别人看（公开/私有开关）
 * 铁律（v3.0 §1.2）：默认私有；公开必须是老人**主动点一下**，且随时能收回。
 * 后端单一真相源：POST /api/echoes/clip/visibility（share_api.can_share_story 判它）
 * 本页只在「做一张图 / 分享」走不通时把人接过来——不让人卡在一句"做不了"上。
 */
const api = require('../../utils/api.js');

Page({
  data: {
    uiMode: 'standard',
    storyId: '',
    storyTitle: '',
    actorId: '',
    clips: [],          // [{clip_id, preview, visibility, is_public, kind_label, can_toggle}]
    loading: true,
    err: '',
    publicCount: 0,
    backTo: ''          // 从哪来的（'card' 回卡片页 / '' 回上一页）
  },

  onLoad(options) {
    const app = getApp();
    const o = options || {};
    const g = app.globalData || {};
    this.setData({
      uiMode: app.getUiMode ? app.getUiMode() : 'standard',
      storyId: o.story_id || '',
      storyTitle: o.title ? decodeURIComponent(o.title) : '',
      backTo: o.from || '',
      actorId: g.userId || ''
    });
    const self = this;
    (app.ensureLogin ? app.ensureLogin() : Promise.resolve())
      .catch(function () {})
      .then(function () {
        const actorId = (getApp().globalData || {}).userId || api.getSession().userId || '';
        self.setData({ actorId: actorId });
        self.loadClips();
      });
  },

  loadClips() {
    const d = this.data;
    if (!d.storyId || !d.actorId) {
      this.setData({ loading: false, err: '还没登录呢，登录一下就能看了' });
      return;
    }
    this.setData({ loading: true, err: '' });
    api.storyDetail(d.storyId, d.actorId, d.actorId)
      .then((data) => {
        const dd = data || {};
        const raw = dd.clips || [];
        const clips = raw.map((c) => {
          const text = (c.text || c.caption || '').trim();
          const kind = c.kind || c.type || '';
          let label = '一段话';
          if (kind === 'photo' || kind === 'image') label = '一张照片';
          else if (kind === 'audio') label = '一段录音';
          else if (kind === 'video') label = '一段视频';
          const preview = text ? (text.length > 28 ? text.slice(0, 28) + '…' : text) : ('（' + label + '）');
          const isPub = c.visibility === 'public';
          return {
            clip_id: c.clip_id || c.id || '',
            preview: preview,
            kind_label: label,
            is_public: isPub,
            visibility: c.visibility || 'private',
            can_toggle: !!c.is_mine || !!c.can_toggle
          };
        });
        const pubCount = clips.filter(function (x) { return x.is_public; }).length;
        this.setData({
          loading: false,
          clips: clips,
          publicCount: pubCount,
          storyTitle: this.data.storyTitle || dd.title || ''
        });
      })
      .catch((err) => {
        this.setData({ loading: false, err: (err && err.message) || '没能打开这段内容，请稍后再试' });
      });
  },

  /** 点一下这一段：私有→公开 / 公开→私有 */
  onToggle(e) {
    const clipId = e.currentTarget.dataset.id;
    if (!clipId) return;
    const clips = this.data.clips || [];
    let target = null;
    for (let i = 0; i < clips.length; i++) {
      if (clips[i].clip_id === clipId) { target = clips[i]; break; }
    }
    if (!target) return;
    if (!target.can_toggle) {
      wx.showToast({ title: '这段是别人放的，你改不了', icon: 'none' });
      return;
    }
    const next = target.is_public ? 'private' : 'public';
    wx.showLoading({ title: '正在改…', mask: true });
    api.clipSetVisibility(clipId, this.data.actorId, next)
      .then(() => {
        wx.hideLoading();
        const updated = clips.map(function (c) {
          if (c.clip_id !== clipId) return c;
          return Object.assign({}, c, { is_public: next === 'public', visibility: next });
        });
        const pubCount = updated.filter(function (x) { return x.is_public; }).length;
        this.setData({ clips: updated, publicCount: pubCount });
        wx.showToast({ title: next === 'public' ? '这段能给别人看了' : '这段收回来了', icon: 'none' });
      })
      .catch((err) => {
        wx.hideLoading();
        wx.showModal({
          title: '没改成',
          content: (err && err.message) || '网络不太好，请再点一次',
          showCancel: false
        });
      });
  },

  /** 改完回去接着做图 */
  onBackToCard() {
    const d = this.data;
    if (d.publicCount === 0) {
      wx.showToast({ title: '至少让一段能给别人看，才做得成图', icon: 'none' });
      return;
    }
    if (d.backTo === 'card' && d.storyId) {
      wx.redirectTo({
        url: '/pages/card/card?kind=story&target_id=' + encodeURIComponent(d.storyId) +
             '&title=' + encodeURIComponent(d.storyTitle || ''),
        fail: () => {
          wx.navigateBack({ delta: 1 });
        }
      });
      return;
    }
    wx.navigateBack({ delta: 1 });
  }
});
