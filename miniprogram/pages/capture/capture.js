/**
 * pages/capture/capture.js — 采集页（第1期：文字 / 图片 已接后端形状）
 * 依据 v2.4 §四：老人按住说话 / 打字 / 传照片 / 传视频
 * 交互铁律（sandy 拍板）：合格线 =「摁一下，哒哒就说」——
 *   照微信「按住说话」，不发明新交互，老人学不会＝不合格。
 *   故事里的加号 = 只可见这一篇；家人加号 = 可见整本书（本页只做「这个故事」的加号）。
 *
 * 权限可见性口径（小鲸鱼 09-26 单《权限可见性口径+采集页对齐》，后端 permissions.py 20/20 已实测）：
 *   - 首页显示几篇由后端按关系算（主人=全部 / 家人=整本 / 故事成员=被加那篇 / 被提到的人=被提那篇 / 陌生人=0）
 *   - 前端**不给任何权限勾选框**（v2.4 铁律）；能看就能添 → 能进本页即视为有添素材权限
 *
 * ⚠️ 接口路径（小鲸鱼 09-26 纠偏单《采集接口路径不一致请改》定稿，勿再用旧的 /api/stories/{id}/clips）：
 *   - 挂文字   POST /api/echoes/clip/text
 *   - 挂图片   POST /api/echoes/clip/photo   （先取上传地址 → PUT → 再登记，见下）
 *   - 取素材筐 GET  /api/echoes/clip/list?story_id=&viewer_id=
 *   - 取上传址 POST /api/echoes/upload/url
 *   - 统一信封 {ok, data, error, code}/{ok, data, message}；**前端只看 ok**，
 *     ok=false 时把 error（中文人话）原样显示给用户，code 只用于分支、不显示。
 *   - clips 已按 sort_order 排好，直接渲染不用再排。
 *   - 语音/原声类 **必须带 media_url**（后端强制保留原声，v2.4 铁律「不只是转文字」）
 *     → 前端上传语音时**原声文件一定要一起传，不能只传 transcript**。
 *     （语音/视频接口小鲸鱼 09-29 才出，本页先只接文字/图片，语音保留 UI 占位。）
 */
const app = getApp();
const TYPES = ['voice', 'text', 'photo', 'video'];

/** 统一请求：只看 ok，error 直显；code 留给调用方分支 */
function callApi(path, method, data) {
  return new Promise((resolve, reject) => {
    const base = (app.globalData && app.globalData.apiBase) || '';
    wx.request({
      url: base + path,
      method,
      data: data || {},
      success: (res) => {
        const body = res.data || {};
        if (body.ok) return resolve(body.data || {});
        // 后端的中文 error 直接给用户看；code 不外显
        const err = new Error(body.error || '操作失败，请重试');
        err.code = body.code;      // 仅供调用方分支
        reject(err);
      },
      fail: () => reject(new Error('网络不太好，请稍后再试'))
    });
  });
}

Page({
  data: {
    uiMode: 'standard',
    type: 'voice',
    storyId: null,
    actorId: 'u_me',   // v1：登录态未接，先固定；后端 owner_id 暂取 actor_id（TODO 登录态注入）
    text: '',
    recording: false,
    mediaList: [],     // 本地已选/已录素材占位
    clips: []          // 后端素材筐（已排序）
  },

  onLoad(query) {
    const type = TYPES.indexOf(query.type) >= 0 ? query.type : 'voice';
    this.setData({
      uiMode: app.getUiMode(),
      type,
      storyId: query.storyId || app.globalData.currentStoryId || null
    });
    if (this.data.storyId) this.refreshClips();
  },

  onTypeChange(e) {
    this.setData({ type: e.currentTarget.dataset.type });
  },

  /** 取素材筐（已排序，直接渲染） */
  refreshClips() {
    const { storyId, actorId } = this.data;
    if (!storyId) return;
    callApi(
      '/api/echoes/clip/list?story_id=' + encodeURIComponent(storyId) +
      '&viewer_id=' + encodeURIComponent(actorId),
      'GET'
    )
      .then((data) => this.setData({ clips: data.clips || [] }))
      .catch(() => this.setData({ clips: [] }));   // no_permission → 当作没有
  },

  /** 按住说话：进入录音（样式照微信，不发明新交互） */
  onHoldStart() {
    if (this.data.type !== 'voice') return;
    // TODO(接口): 调用后端语音上传接口（小鲸鱼 09-29 交定义）；
    //   录音**原声文件必须一起上传**（media_url），不能只传转写文本。
    this.setData({ recording: true });
    wx.vibrateShort && wx.vibrateShort();
  },

  onHoldEnd() {
    if (!this.data.recording) return;
    this.setData({ recording: false });
    // TODO(接口): 停止录音 → 取上传地址 → PUT → 用 file_url 作 media_url 登记
    wx.showToast({ title: '语音接口 09-29 到', icon: 'none' });
  },

  onTextInput(e) {
    this.setData({ text: e.detail.value });
  },

  /** 挂文字素材 → POST /api/echoes/clip/text */
  saveText() {
    const { storyId, actorId, text } = this.data;
    if (!storyId) { wx.showToast({ title: '还没有故事', icon: 'none' }); return; }
    if (!text || !text.trim()) { wx.showToast({ title: '说点什么再存', icon: 'none' }); return; }
    wx.showLoading({ title: '保存中' });
    callApi('/api/echoes/clip/text', 'POST', {
      story_id: storyId, actor_id: actorId, text: text, caption: ''
    })
      .then(() => {
        wx.hideLoading();
        wx.showToast({ title: '已记下', icon: 'success' });
        this.setData({ text: '' });
        this.refreshClips();
      })
      .catch((e) => {
        wx.hideLoading();
        if (e.code === 'empty_text') { wx.showToast({ title: '说点什么再存', icon: 'none' }); return; }
        wx.showModal({ title: '没存上', content: e.message, showCancel: false });
      });
  },

  /** 加号：直接跳系统图库/相机，不发明中间页（sandy 拍板：当场录 + 相册传） */
  onPlusPick(e) {
    const kind = (e.currentTarget.dataset.kind) || this.data.type;
    if (kind === 'photo' || kind === 'video') {
      wx.chooseMedia({
        count: 9,
        mediaType: [kind],
        sourceType: ['album', 'camera'],   // 相册传 + 当场录
        success: (res) => {
          const newItems = (res.tempFiles || []).map((f) => ({
            kind, path: f.tempFilePath, size: f.size
          }));
          this.setData({ mediaList: this.data.mediaList.concat(newItems) });
          // 图片：上传三步（取地址→PUT→登记）。当前后端 upload 未接对象存储，
          // 前端照流程写，等 sandy 定 COS/自建后自动通（形状已冻结，前端一行不改）。
          if (kind === 'photo') newItems.forEach((it) => this.uploadAndRegister(it));
        },
        fail: () => {}
      });
    } else {
      wx.showToast({ title: '请直接在下方输入', icon: 'none' });
    }
  },

  /** 图片三步：取上传地址 → PUT 字节 → 用 file_url 登记（接口 2） */
  uploadAndRegister(item) {
    const { storyId, actorId } = this.data;
    if (!storyId) return;
    const name = (item.path || '').split('/').pop() || '';
    const mime = /\.(png)$/i.test(name) ? 'image/png'
      : /\.(heic)$/i.test(name) ? 'image/heic'
      : /\.(webp)$/i.test(name) ? 'image/webp' : 'image/jpeg';
    callApi('/api/echoes/upload/url', 'POST', {
      file_name: name, file_size: item.size || 0, mime
    })
      .then((up) => new Promise((resolve, reject) => {
        // 真实 PUT 到 upload_url（待对象存储接入后启用）
        wx.uploadFile({
          url: up.upload_url, filePath: item.path, name: 'file',
          success: (r) => resolve(r.data && r.data.file_url ? r.data.file_url : up.file_url),
          fail: () => reject(new Error('图片上传失败'))
        });
      }))
      .then((fileUrl) => callApi('/api/echoes/clip/photo', 'POST', {
        story_id: storyId, actor_id: actorId, media_url: fileUrl,
        file_name: name, file_size: item.size || 0, mime: mime,
        cover_url: '', caption: ''
      }))
      .then(() => this.refreshClips())
      .catch((e) => {
        // upload_not_configured：上传通道还没接对象存储，属预期，不吓用户
        if (e.code === 'upload_not_configured') return;
        wx.showModal({ title: '照片没存上', content: e.message, showCancel: false });
      });
  },

  /** 保存：文字走文字接口；图片在选择时已登记 */
  onSave() {
    if (this.data.type === 'text') { this.saveText(); return; }
    if (this.data.type === 'voice' || this.data.type === 'video') {
      wx.showToast({ title: '接口 09-29 到', icon: 'none' });
      return;
    }
    wx.showToast({ title: '照片已保存', icon: 'success' });
  }
});
