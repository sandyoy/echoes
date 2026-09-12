// app.js —— 苏格拉底学伴 · 独立小程序
// 知识库存储架构（2026-08-01 拆分时设计）：
//   - 当前阶段：知识库存本地（wx.getStorageSync），孩子自己设备上用
//   - 未来阶段：预留 BACKEND_SYNC 开关，开启后走后端服务器共享
//     （跨设备同步、家长查看孩子知识库）—— 后端未做时保持 false
const CONFIG = {
  // 未来后端共享开关：true 时启用服务器同步（需实现存储 API）
  BACKEND_SYNC: false,
  // 未来后端地址（BACKEND_SYNC 为 true 时生效）
  API_BASE: ''
}

App({
  globalData: {
    CONFIG,
    // 当前孩子用户信息（本地）
    currentLearner: null
  },

  onLaunch() {
    // 加载本地孩子档案
    const learner = wx.getStorageSync('learnerProfile')
    if (learner) {
      this.globalData.currentLearner = learner
    }
  },

  // ============ 知识库存储统一接口 ============
  // 所有读写走这里，未来切后端只需改这两个函数

  // 读取某个知识库片段
  getKB(key) {
    if (CONFIG.BACKEND_SYNC) {
      // TODO: 接后端共享存储 API
      return Promise.reject('后端共享未启用')
    }
    return Promise.resolve(wx.getStorageSync(key) || null)
  },

  // 保存某个知识库片段
  setKB(key, value) {
    if (CONFIG.BACKEND_SYNC) {
      // TODO: 接后端共享存储 API
      return Promise.reject('后端共享未启用')
    }
    wx.setStorageSync(key, value)
    return Promise.resolve(true)
  }
})
