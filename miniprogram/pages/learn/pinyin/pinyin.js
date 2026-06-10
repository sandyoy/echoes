// 拼音首页
Page({
  data: {
    todayCount: 0,
    todayDone: false,
    progressPercent: 0
  },

  onShow() {
    this.loadProgress()
  },

  loadProgress() {
    const stat = wx.getStorageSync('pinyinStat') || {}
    const today = getTodayDateStr()
    
    if (stat.date === today) {
      const minutes = stat.minutes || 0
      this.setData({
        todayCount: minutes,
        todayDone: minutes >= 10,
        progressPercent: Math.min(100, (minutes / 10) * 100)
      })
    } else {
      this.setData({
        todayCount: 0,
        todayDone: false,
        progressPercent: 0
      })
    }
  },

  goFlashcard(e) {
    const type = e.currentTarget.dataset.type
    wx.navigateTo({ url: `/pages/learn/pinyin/flashcard/flashcard?type=${type}` })
  },

  goLookup() {
    wx.navigateTo({ url: '/pages/learn/pinyin/lookup/lookup' })
  },

  doCheckin() {
    if (this.data.todayDone) return
    
    wx.showToast({ title: '去闪卡页面学习吧！', icon: 'none' })
    // 用户去闪卡页面学习，完成后自动记录
  }
})

function getTodayDateStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
}
