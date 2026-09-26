/**
 * 往事可追忆 v2.4 · 另起炉灶版
 * app.js — 全局状态：界面模式（标准/大字）+ 主题注入
 *
 * 设计依据：docs/需求书_往事可追忆_另起炉灶版_v2.4_20260923.md 第三节
 * 铁律：大字版里凡出现「设置/权限/分享」字样，即为失败。
 */
App({
  globalData: {
    // 'standard' | 'large'  —— 全局界面模式，随时可切（v2.4 §3.2）
    uiMode: 'standard',
    // 故事 = 数据主体（v2.4 §2.1）
    currentStoryId: null,
    // 后端基址。小龙虾 09-26 实测：本机已装 fastapi/uvicorn/sqlalchemy，
    //   后端适配器可在本地真跑（34/34 自测过 + /docs 200 + 4 接口信封实测），
    //   本地联调：cd backend && python3 -m uvicorn api_adapter_fastapi:app --port 8012
    //   微信开发者工具需在「详情→本地设置」勾「不校验合法域名」才能连 127.0.0.1。
    apiBase: 'http://127.0.0.1:8012'
  },

  onLaunch() {
    // 记忆上次选择，打开即恢复（默认标准版）
    const saved = wx.getStorageSync('uiMode');
    if (saved === 'standard' || saved === 'large') {
      this.globalData.uiMode = saved;
    }
  },

  /** 切换界面模式（v2.4 §3.2：全局切换，不是注册时选一次） */
  setUiMode(mode) {
    if (mode !== 'standard' && mode !== 'large') return;
    this.globalData.uiMode = mode;
    wx.setStorageSync('uiMode', mode);
  },

  getUiMode() {
    return this.globalData.uiMode;
  }
});
