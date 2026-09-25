/**
 * pages/capture/capture.js — 采集页（第1期：四类素材）
 * 依据 v2.4 §四：老人按住说话 / 打字 / 传照片 / 传视频
 * 交互铁律（sandy 拍板）：合格线 =「摁一下，哒哒就说」——
 *   照微信「按住说话」，不发明新交互，老人学不会＝不合格。
 *   故事里的加号 = 只可见这一篇；家人加号 = 可见整本书（本页只做「这个故事」的加号）。
 */
const app = getApp();
const TYPES = ['voice', 'text', 'photo', 'video'];

Page({
  data: {
    uiMode: 'standard',
    type: 'voice',
    storyId: null,
    text: '',
    recording: false,
    mediaList: []   // 已选/已录的素材占位
  },

  onLoad(query) {
    const type = TYPES.indexOf(query.type) >= 0 ? query.type : 'voice';
    this.setData({
      uiMode: app.getUiMode(),
      type,
      storyId: query.storyId || app.globalData.currentStoryId || null
    });
  },

  onTypeChange(e) {
    this.setData({ type: e.currentTarget.dataset.type });
  },

  /** 按住说话：进入录音（样式照微信，不发明新交互） */
  onHoldStart() {
    if (this.data.type !== 'voice') return;
    // TODO(接口): 调用后端 B 线语音上传接口（小鲸鱼 09-30 交定义）
    this.setData({ recording: true });
    wx.vibrateShort && wx.vibrateShort();
  },

  onHoldEnd() {
    if (!this.data.recording) return;
    this.setData({ recording: false });
    // TODO(接口): 停止录音 → 上传 → 追加到 mediaList
  },

  onTextInput(e) {
    this.setData({ text: e.detail.value });
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
          // TODO(接口): 上传（后端 B 线）
        },
        fail: () => {}
      });
    } else {
      // 文字/语音的加号暂不涉及系统选择器
      wx.showToast({ title: '请直接在下方输入', icon: 'none' });
    }
  },

  /** 保存：素材挂到「同一件事」（v2.4 核心：一条故事 = 一个素材筐） */
  onSave() {
    // TODO(接口): 调后端「素材挂故事」接口；storyId 为空时先建故事
    wx.showToast({ title: '待接口对接', icon: 'none' });
  }
});
