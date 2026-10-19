/**
 * pages/card/card.js —— 做成一张图页（卡片出图通道）
 *
 * 派单：小鲸鱼《@小龙虾_做成一张图出图通道已就绪请接前端+实测_20261018》
 * 后端：backend/card_render.py（2 条路由）
 *   ① GET  /api/echoes/card/render?kind=story|book&target_id=&actor_id=  → PNG 二进制
 *   ② POST /api/echoes/card/preview  → 只量不出图（宽高/字节/底部留白/越界/字是否真的画上）
 *
 * 铁律（后端已守，前端不重复判定、但也不假装成功）：
 *   · 只画公开素材：整篇全私有 → not_shareable，**不许出一张含私有内容的图**
 *   · 缺 actor_id → 后端直接拒（权限判定的根，绝不退化放行）
 *   · 前端只认 ok；失败必带中文 error 直接弹给老人
 *
 * 流程：进页面 → 先 preview 体检（决定能不能出图 + 画布多大）→ 点「做出来」→ downloadFile 拿 PNG
 *       → wx.saveImageToPhotosAlbum 存相册（保存失败不说"成功"）。
 *
 * ⚠️ 本页不在大字版首页露出；本页仍遵守大字版禁词（不出现「设置/权限/分享」）。
 */
const app = getApp();
const api = require('../../utils/api.js');

Page({
  data: {
    uiMode: 'standard',
    kind: 'story',          // 'story' 一篇 | 'book' 一本书
    targetId: '',
    actorId: '',
    title: '',              // 这张图做的是哪篇/哪本

    checking: false,
    checkError: '',         // 体检失败的人话（如：这篇没有能公开的内容）
    checked: false,
    width: 0,
    height: 0,
    bytes: 0,
    bottomGap: 0,
    overflow: false,
    lineFound: {},          // { '某句话': true }

    making: false,
    imgPath: '',            // 出好的本地临时图
    saved: false
  },

  onLoad(options) {
    const o = options || {};
    const g = app.globalData || {};
    const kind = o.kind === 'book' ? 'book' : 'story';
    const targetId = o.target_id || o.story_id || '';
    this.setData({
      uiMode: app.getUiMode(),
      kind: kind,
      targetId: targetId,
      actorId: g.userId || '',
      title: o.title ? decodeURIComponent(o.title) : ''
    });
    app.ensureLogin()
      .then(() => this._boot())
      .catch(() => this._boot());
  },

  onShow() {
    this.setData({ uiMode: app.getUiMode() });
  },

  _boot() {
    const g = app.globalData || {};
    const actorId = g.userId || api.getSession().userId || '';
    this.setData({ actorId: actorId });
    if (!actorId) {
      this.setData({ checkError: '还没登录呢，登录一下就能做了' });
      return;
    }
    if (!this.data.targetId) {
      // kind=book 且没带 target_id → 用自己（后端同样缺省为本人）
      if (this.data.kind === 'book') {
        this.setData({ targetId: actorId });
      } else {
        this.setData({ checkError: '这张图要做哪一篇呢？先回去点开那一篇' });
        return;
      }
    }
    this.onCheck();
  },

  /** 切换：这一篇 / 整本书 */
  onSwitchKind(e) {
    const kind = (e && e.currentTarget && e.currentTarget.dataset.kind) || 'story';
    if (kind === this.data.kind) return;
    const g = app.globalData || {};
    this.setData({
      kind: kind,
      targetId: kind === 'book' ? (g.userId || '') : (this._storyId || this.data.targetId),
      checked: false,
      imgPath: '',
      saved: false,
      checkError: ''
    });
    this.onCheck();
  },

  // ===================== ① 体检（先量，不盲信） =====================

  onCheck() {
    const d = this.data;
    if (d.checking || !d.actorId) return;
    this.setData({ checking: true, checkError: '' });
    api.cardPreview({ actorId: d.actorId, kind: d.kind, targetId: d.targetId })
      .then((data) => {
        const dd = data || {};
        this.setData({
          checking: false,
          checked: true,
          width: Number(dd.width || 0),
          height: Number(dd.height || 0),
          bytes: Number(dd.bytes || 0),
          bottomGap: Number(dd.ink_bottom_gap_px || dd.bottom_padding || 0),
          overflow: !!dd.overflow,
          lineFound: dd.line_found || {}
        });
      })
      .catch((err) => {
        // not_shareable / not_found / render_unavailable 都由后端给中文人话
        this.setData({
          checking: false,
          checked: false,
          checkError: (err && err.message) || '这张图现在做不了，请稍后再试'
        });
      });
  },

  // ===================== ② 出图 =====================

  onMake() {
    const d = this.data;
    if (d.making || !d.actorId) return;
    if (!d.checked) {
      wx.showToast({ title: '先看看能不能做', icon: 'none' });
      return;
    }
    this.setData({ making: true, imgPath: '', saved: false });
    const url = api.cardRenderUrl(d.kind, d.targetId, d.actorId);
    wx.downloadFile({
      url: url,
      success: (res) => {
        // 后端出错时回的是 JSON（带 ok:false + 中文 error），不是图 —— 如实报，不假装成功
        if (res.statusCode !== 200) {
          this.setData({ making: false });
          wx.showModal({
            title: '这张图没做出来',
            content: this._errorFromFile(res.tempFilePath) || '这张图现在做不了，请稍后再试',
            showCancel: false
          });
          return;
        }
        this.setData({ making: false, imgPath: res.tempFilePath });
        wx.previewImage({ urls: [res.tempFilePath] });
      },
      fail: () => {
        this.setData({ making: false });
        wx.showModal({
          title: '没做出来',
          content: '网络不太好，请稍后再试',
          showCancel: false
        });
      }
    });
  },

  /** 出错时读一下回包里的中文 error（失败也不假装成功） */
  _errorFromFile(path) {
    if (!path) return '';
    try {
      const raw = wx.getFileSystemManager().readFileSync(path, 'utf8');
      const body = JSON.parse(raw);
      return (body && body.error) || '';
    } catch (e) {
      return '';
    }
  },

  /** 存到相册 */
  onSave() {
    const p = this.data.imgPath;
    if (!p) return;
    wx.saveImageToPhotosAlbum({
      filePath: p,
      success: () => {
        this.setData({ saved: true });
        wx.showToast({ title: '存到相册了', icon: 'success' });
      },
      fail: (err) => {
        // 用户自己拒绝授权时不说"成功"，给一句人话
        const msg = (err && err.errMsg) || '';
        const denied = msg.indexOf('auth') >= 0 || msg.indexOf('deny') >= 0;
        wx.showModal({
          title: '没存上',
          content: denied ? '没让存到相册，去手机里允许一下就能存了' : '没存上，请再试一次',
          showCancel: false
        });
      }
    });
  },

  /** 返回：不要图了 */
  onBack() {
    wx.navigateBack({ fail: () => wx.reLaunch({ url: '/pages/index/index' }) });
  }
});
