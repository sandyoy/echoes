// 时间轴页面
const app = getApp()

Page({
  data: {
    stories: [],
    timelineData: []
  },

  onShow() {
    this.loadTimeline()
  },

  loadTimeline() {
    // 先从本地存储加载
    const localStories = wx.getStorageSync('localStories') || []
    
    // 按年份分组
    const groups = {}
    localStories.forEach(s => {
      const year = s.date ? s.date.substring(0, 4) : '未知'
      if (!groups[year]) groups[year] = []
      groups[year].push(s)
    })

    // 按年份降序排列
    const timelineData = Object.keys(groups)
      .sort((a, b) => b.localeCompare(a))
      .map(year => ({
        year,
        stories: groups[year].sort((a, b) => b.date.localeCompare(a.date))
      }))

    this.setData({ stories: localStories, timelineData })
  },

  goStory(e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({ url: `/pages/story/story?id=${id}` })
  }
})
