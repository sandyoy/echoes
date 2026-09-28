/**
 * pages/capture/capture.js — 采集页（第1期：文字/照片/语音/原声/视频 全部已接后端形状）
 * 依据 v2.4 §四：老人按住说话 / 打字 / 传照片 / 传视频 / 留个声
 * 交互铁律（sandy 拍板）：合格线 =「摁一下，哒哒就说」——
 *   照微信「按住说话」，不发明新交互，老人学不会＝不合格。
 *
 * 权限可见性口径（小鲸鱼 09-26 单《权限可见性口径+采集页对齐》，permissions.py 20/20 实测）：
 *   - 首页显示几篇由后端按关系算；前端**不给任何权限勾选框**（v2.4 铁律）
 *   - 能看就能添 → 能进本页即视为有添素材权限
 *
 * 接口路径（小鲸鱼 09-26 纠偏单 + 09-28《接口定义_采集v1.1》，全部冻结）：
 *   - 文字   POST /api/echoes/clip/text
 *   - 照片   POST /api/echoes/clip/photo      （先取上传址 → 上传 → 再登记）
 *   - 语音   POST /api/echoes/clip/audio       （保留原声 + 尽量转文字）
 *   - 原声   POST /api/echoes/clip/original    （刻意不转写，保方言/语气）
 *   - 视频   POST /api/echoes/clip/video
 *   - 补转写 POST /api/echoes/clip/transcribe  （幂等）
 *   - 取筐   GET  /api/echoes/clip/list?story_id=&viewer_id=
 *   - 上传址 POST /api/echoes/upload/url
 *
 * 信封 {ok,data,error,code}；**前端只看 ok**，ok=false 时把 error（中文人话）原样显示。
 * 三个铁律（v2.4 §六）：
 *   1) keep_original_voice 恒 true → 前端**不传**该字段（传了后端强制改回）
 *   2) transcribe_failed 不算失败 → 原声已存，用灰/黄提示，**不弹红叉、不提示重录**
 *   3) audio_path 是本机路径 → 前端**不传**
 */
const app = getApp();
const api = require('../../utils/api.js');

// 5 个入口（小鲸鱼：说话 与 留个声 是两件事，不合并）
const TYPES = ['text', 'voice', 'original', 'photo', 'video'];

// 校验上限（与小鲸鱼《接口定义_采集v1.1》第四节一致，本地先拦少跑一趟网络）
const MAX_AUDIO_MB = 20;
const MAX_VIDEO_MB = 200;
const MIN_AUDIO_SEC = 0.5;

/** 统一请求：只看 ok，error 直显；code 留给调用方分支（实现在 utils/api.js） */
const callApi = api.request;

Page({
  data: {
    uiMode: 'standard',
    type: 'voice',
    storyId: null,
    actorId: 'u_me',   // v1：登录态未接，先固定；后端 owner_id 暂取 actor_id（TODO 登录态注入）
    text: '',
    recording: false,
    mediaList: [],     // 本地已选/已录素材（仅展示用）
    clips: [],         // 后端素材筐（已排序，直接渲染）
    notice: ''         // 上一次操作的软提示（灰/黄，不吓人）
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
    this.setData({ type: e.currentTarget.dataset.type, notice: '' });
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

  // ==================== 语音 / 原声：按住说话 ====================

  /** 按住说话：开始录音（语音=要转文字；原声=只留声音） */
  onHoldStart() {
    if (this.data.type !== 'voice' && this.data.type !== 'original') return;
    this._recStart = Date.now();
    this.setData({ recording: true });
    wx.vibrateShort && wx.vibrateShort();
    const rm = wx.getRecorderManager && wx.getRecorderManager();
    if (!rm) { this._recSupported = false; return; }
    this._recSupported = true;
    this._onStop = (res) => this._handleRecordStop(res);
    rm.onStop(this._onStop);
    rm.start({
      duration: 15 * 60 * 1000,          // 15 分钟上限（超了后端给分段 notice）
      sampleRate: 16000, numberOfChannels: 1,
      encodeBitRate: 48000, format: 'mp3'
    });
  },

  /** 松开：停止录音（原声文件必须一起上传，绝不能只传转写文本） */
  onHoldEnd() {
    if (!this.data.recording) return;
    this.setData({ recording: false });
    const rm = wx.getRecorderManager && wx.getRecorderManager();
    if (rm && this._recSupported) rm.stop();
    else wx.showToast({ title: '这台设备不支持录音', icon: 'none' });
  },

  /** 录音结束 → 本地校验 → 取上传址 → 上传 → 登记 */
  _handleRecordStop(res) {
    const { type, storyId, actorId } = this.data;
    const isOriginal = type === 'original';
    const path = (res && res.tempFilePath) || '';
    const size = (res && res.fileSize) || 0;
    const duration = (res && res.duration ? res.duration / 1000 : 0) || 0;

    // ① 本地校验：过短（误碰）
    if (duration && duration < MIN_AUDIO_SEC) {
      wx.showToast({ title: '像误碰了一下，再按住说话', icon: 'none' });
      return;
    }
    // ② 本地校验：超 20MB
    if (size > MAX_AUDIO_MB * 1024 * 1024) {
      wx.showToast({ title: '这段太长（超20MB）', icon: 'none' });
      return;
    }
    if (!path) { wx.showToast({ title: '没录上，再试一次', icon: 'none' }); return; }
    if (!storyId) { wx.showToast({ title: '还没有故事', icon: 'none' }); return; }

    const name = (path.split('/').pop()) || (isOriginal ? 'voice.m4a' : 'voice.mp3');
    const mime = /\.(m4a)$/i.test(name) ? 'audio/m4a'
      : /\.(wav)$/i.test(name) ? 'audio/wav'
      : /\.(amr)$/i.test(name) ? 'audio/amr' : 'audio/mpeg';

    wx.showLoading({ title: '保存中' });
    // 三步：取上传地址 → 上传字节拿 media_url → 调登记接口
    this._uploadBytes(path, name, size, mime)
      .then((mediaUrl) => {
        const media = {
          mediaUrl: mediaUrl, fileName: name, fileSize: size,
          mime: mime, duration: duration, caption: '', doTranscribe: !isOriginal
        };
        return isOriginal
          ? api.clipOriginal(storyId, actorId, media)
          : api.clipAudio(storyId, actorId, media);
      })
      .then((data) => {
        wx.hideLoading();
        // ★ 语音：如果 transcribed=false 属预期（转写稍后），用灰/黄，不弹红叉
        if (data && data.transcribed === false && !isOriginal) {
          this.setData({ notice: '原声已留下，文字稍后补' });
        } else {
          this.setData({ notice: '' });
          wx.showToast({ title: isOriginal ? '声音留下了' : '记下了', icon: 'success' });
        }
        this.refreshClips();
      })
      .catch((e) => {
        wx.hideLoading();
        if (e.code === 'upload_not_configured') { this.setData({ notice: '上传通道还没开，原声先存本地' }); return; }
        if (e.code === 'transcribe_failed') { this.setData({ notice: e.message || '文字没转上，原声已经留住了' }); return; } // 不算失败
        this.setData({ notice: '' });
        wx.showModal({ title: '没存上', content: e.message, showCancel: false });
      });
  },

  /** 取上传地址 → 上传字节 → 返回 media_url（三段式，对象存储接入后前端一行不改） */
  _uploadBytes(filePath, fileName, fileSize, mime) {
    return api.uploadUrl(fileName, fileSize, mime).then((up) =>
      new Promise((resolve, reject) => {
        wx.uploadFile({
          url: up.upload_url, filePath: filePath, name: 'file',
          success: (r) => {
            let body = r.data;
            try { body = typeof body === 'string' ? JSON.parse(body) : body; } catch (err) {}
            const url = (body && (body.file_url || body.media_url)) || up.file_url || '';
            url ? resolve(url) : reject(new Error('上传没返回地址'));
          },
          fail: () => reject(new Error('上传失败，稍后再试'))
        });
      })
    );
  },

  // ==================== 文字 ====================

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

  // ==================== 照片 / 视频 ====================

  /** 加号：直接跳系统图库/相机，不发明中间页（sandy 拍板：当场录 + 相册传） */
  onPlusPick(e) {
    const kind = (e.currentTarget.dataset.kind) || this.data.type;
    if (kind !== 'photo' && kind !== 'video') {
      wx.showToast({ title: '请直接在下方输入', icon: 'none' });
      return;
    }
    wx.chooseMedia({
      count: kind === 'photo' ? 9 : 1,
      mediaType: [kind],
      sourceType: ['album', 'camera'],   // 相册传 + 当场录
      maxDuration: kind === 'video' ? 600 : 60,   // 视频 10 分钟上限
      success: (res) => {
        (res.tempFiles || []).forEach((f) => {
          const size = f.size || 0;
          // 视频本地拦 200MB
          if (kind === 'video' && size > MAX_VIDEO_MB * 1024 * 1024) {
            wx.showToast({ title: '视频太大（超200MB）', icon: 'none' });
            return;
          }
          const item = { kind, path: f.tempFilePath, size };
          this.setData({ mediaList: this.data.mediaList.concat([item]) });
          if (kind === 'photo') this._uploadPhoto(item);
          else this._uploadVideo(item, f);
        });
      },
      fail: () => {}
    });
  },

  /** 照片三步：取上传地址 → 上传字节 → 用 file_url 登记 */
  _uploadPhoto(item) {
    const { storyId, actorId } = this.data;
    if (!storyId) return;
    const name = (item.path || '').split('/').pop() || '';
    const mime = /\.(png)$/i.test(name) ? 'image/png'
      : /\.(heic)$/i.test(name) ? 'image/heic'
      : /\.(webp)$/i.test(name) ? 'image/webp' : 'image/jpeg';
    this._uploadBytes(item.path, name, item.size || 0, mime)
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

  /** 视频三步：取上传地址 → 上传字节 → 用 file_url 登记（缩略图作 cover） */
  _uploadVideo(item, file) {
    const { storyId, actorId } = this.data;
    if (!storyId) return;
    const name = (item.path || '').split('/').pop() || '';
    const mime = /\.(mov)$/i.test(name) ? 'video/quicktime'
      : /\.(m4v)$/i.test(name) ? 'video/x-m4v' : 'video/mp4';
    wx.showLoading({ title: '上传中' });
    this._uploadBytes(item.path, name, item.size || 0, mime)
      .then((fileUrl) => api.clipVideo(storyId, actorId, {
        mediaUrl: fileUrl, coverUrl: (file && file.thumbTempFilePath) || '',
        fileName: name, fileSize: item.size || 0, mime: mime,
        duration: (file && file.duration) || 0, caption: ''
      }))
      .then((data) => {
        wx.hideLoading();
        if (data && data.notice) this.setData({ notice: data.notice });
        else wx.showToast({ title: '视频存下了', icon: 'success' });
        this.refreshClips();
      })
      .catch((e) => {
        wx.hideLoading();
        if (e.code === 'upload_not_configured') { this.setData({ notice: '上传通道还没开' }); return; }
        wx.showModal({ title: '视频没存上', content: e.message, showCancel: false });
      });
  },

  // ==================== 保存 ====================

  /** 保存：文字走文字接口；照片/视频在选择时已上传登记；语音/原声在松手时已完成 */
  onSave() {
    if (this.data.type === 'text') { this.saveText(); return; }
    if (this.data.type === 'voice' || this.data.type === 'original') {
      wx.showToast({ title: '按住说话就存下来了', icon: 'none' });
      return;
    }
    wx.showToast({ title: '已保存', icon: 'success' });
  }
});
