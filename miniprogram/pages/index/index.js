/**
 * pages/index/index.js — 首页（双界面）
 * 标准版：故事列表 + 成书 + 全部功能（v2.4 §3.3）
 * 大字版：就一个大按钮「按住说话」，其余收起（v2.4 §3.3）
 */
const app = getApp();

Page({
  data: {
    uiMode: 'standard',
    stories: []   // TODO(接口): 等小鲸鱼 09-30 交接口定义后接后台；当前为本地占位
  },

  onShow() {
    this.setData({ uiMode: app.getUiMode() });
  },

  /** 切换标准版 / 大字版（v2.4 §3.2：随时可切） */
  onToggleMode() {
    const next = app.getUiMode() === 'large' ? 'standard' : 'large';
    app.setUiMode(next);
    this.setData({ uiMode: next });
  },

  /** 大字版主入口：按住说话 → 采集页 */
  onHoldStart() {
    // TODO(接口): 录音 + ASR（后端 B/C 线，小鲸鱼负责）
    // 第1期先跳采集页，录音能力等接口定义
    wx.navigateTo({ url: '/pages/capture/capture?type=voice' });
  },

  onHoldEnd() {
    // 按住结束占位；真实录音 stop 由 ASR 接口接入后实现
  },

  /** 标准版：进入采集页（文字/语音/照片/视频 四类） */
  onCapture(e) {
    const type = (e && e.currentTarget && e.currentTarget.dataset.type) || 'text';
    wx.navigateTo({ url: `/pages/capture/capture?type=${type}` });
  },

  /** 进入成书页 */
  onOpenBook() {
    wx.navigateTo({ url: '/pages/book/book' });
  }
});
