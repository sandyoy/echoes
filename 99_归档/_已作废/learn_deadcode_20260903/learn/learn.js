// 学习首页
const app = getApp()

Page({
  data: {
    todayStats: {
      pinyin: 0,
      math: 0,
      minutes: 0
    }
  },

  onShow() {
    this.loadStats()
  },

  loadStats() {
    const stats = wx.getStorageSync('todayLearnStats') || {
      pinyin: 0,
      math: 0,
      minutes: 0
    }
    
    // 检查日期，如果不是今天则重置
    const today = getTodayDate()
    if (stats.date !== today) {
      stats.date = today
      stats.pinyin = 0
      stats.math = 0
      stats.minutes = 0
      wx.setStorageSync('todayLearnStats', stats)
    }
    
    this.setData({ todayStats: stats })
  },

  goPinyin() {
    wx.navigateTo({ url: '/pages/learn/pinyin/pinyin' })
  },

  goMath() {
    wx.navigateTo({ url: '/pages/learn/math/math' })
  }
})

function getTodayDate() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
}
