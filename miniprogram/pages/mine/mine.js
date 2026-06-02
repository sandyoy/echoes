// 个人中心
const app = getApp()

Page({
  data: {
    userInfo: {},
    stats: {
      totalStories: 0,
      thisYear: 0,
      audioCount: 0
    }
  },

  onShow() {
    this.loadUserInfo()
    this.loadStats()
  },

  loadUserInfo() {
    const userInfo = app.globalData.userInfo || {}
    this.setData({ userInfo })
  },

  loadStats() {
    const stories = wx.getStorageSync('localStories') || []
    const thisYear = new Date().getFullYear()
    
    this.setData({
      stats: {
        totalStories: stories.length,
        thisYear: stories.filter(s => s.date && s.date.startsWith(String(thisYear))).length,
        audioCount: stories.filter(s => s.type === 'audio').length
      }
    })
  },

  login() {
    app.login().then(user => {
      this.setData({ userInfo: user })
      wx.showToast({ title: '登录成功', icon: 'success' })
    }).catch(err => {
      wx.showToast({ title: '登录失败', icon: 'none' })
    })
  },

  goTimeline() {
    wx.switchTab({ url: '/pages/timeline/timeline' })
  },

  exportData() {
    const stories = wx.getStorageSync('localStories') || []
    if (stories.length === 0) {
      wx.showToast({ title: '暂无回忆可导出', icon: 'none' })
      return
    }
    
    // 生成文本摘要
    let text = '【往事可追忆】回忆导出
'
    text += `导出时间：${new Date().toLocaleString()}
`
    text += `共 ${stories.length} 条回忆

---

`
    
    stories.forEach(s => {
      text += `📅 ${s.date || '未知日期'}`
      if (s.era) text += `  🏷️ ${s.era}`
      text += `
${s.content}

---

`
    })

    wx.setClipboardData({
      data: text,
      success: () => {
        wx.showToast({ title: '已复制到剪贴板', icon: 'success' })
      }
    })
  },

  about() {
    wx.showModal({
      title: '关于「往事可追忆」',
      content: '「往事可追忆」是一个温暖的回忆记录工具。

用文字或声音记录你的人生故事，AI帮你一起回忆，自动整理成时光轴。

回忆是最好的礼物。',
      showCancel: false
    })
  }
})
