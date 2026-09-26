/**
 * pages/capture/capture.js — 采集页（第1期：四类素材）
 * 依据 v2.4 §四：老人按住说话 / 打字 / 传照片 / 传视频
 * 交互铁律（sandy 拍板）：合格线 =「摁一下，哒哒就说」——
 *   照微信「按住说话」，不发明新交互，老人学不会＝不合格。
 *   故事里的加号 = 只可见这一篇；家人加号 = 可见整本书（本页只做「这个故事」的加号）。
 *
 * 权限可见性口径（小鲸鱼 09-26 单《权限可见性口径+采集页对齐》对齐，后端 permissions.py 20/20 已实测）：
 *   - 首页显示几篇由后端按关系算（主人=全部 / 家人=整本 / 故事成员=被加那篇 / 被提到的人=被提那篇 / 陌生人=0）
 *   - 前端**不给任何权限勾选框**（v2.4 铁律）；能看就能添 → 能进本页即视为有添素材权限
 *   - ⚠️ 素材接后端时 `POST /api/stories/{story_id}/clips`：
 *       · 语音/原声类 **必须带 media_url**（后端强制保留原声，v2.4 铁律「不只是转文字」）
 *         → 前端上传语音时**原声文件一定要一起传，不能只传 transcript**
 *       · 返回 clip 带 sort_order（后端自动续号），前端按序展示
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
