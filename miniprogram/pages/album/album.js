// 翻页画册页面 - 像翻一本真正的画册
const app = getApp()

Page({
  data: {
    pages: [],           // 画册页数据（每页一屏）
    current: 0,          // 当前页索引
    total: 0,
    hasData: false,
    loading: true
  },

  onLoad(options) {
    // 支持从外部传入指定年份高亮，这里先忽略
    this.buildPages()
  },

  onShow() {
    // 每次显示都可能新增了内容，重建画册
    this.buildPages()
  },

  // 从本地回忆构建画册页
  buildPages() {
    const stories = wx.getStorageSync('localStories') || []
    
    if (!stories || stories.length === 0) {
      this.setData({ hasData: false, loading: false })
      return
    }

    // 按年分组，升序（人生从早到晚）
    const groups = {}
    stories.forEach(s => {
      const year = s.year || (s.date ? s.date.substring(0, 4) : '未知')
      if (!groups[year]) groups[year] = []
      groups[year].push(s)
    })

    const years = Object.keys(groups).sort((a, b) => {
      if (a === '未知') return 1
      if (b === '未知') return -1
      return a.localeCompare(b)
    })

    // 生成封面页 + 每一年一页（或多年合并）
    const pages = []
    
    // 封面
    pages.push({
      type: 'cover',
      title: '往事可追忆',
      subtitle: '我的人生记忆本',
      totalYears: years.filter(y => y !== '未知').length
    })

    // 年份页
    years.forEach((year, idx) => {
      const yearStories = groups[year].sort((a, b) => {
        const da = a.date || (a.year ? `${a.year}-01-01` : '')
        const db = b.date || (b.year ? `${b.year}-01-01` : '')
        return da.localeCompare(db)
      })
      pages.push({
        type: 'year',
        year,
        stories: yearStories,
        photoCount: yearStories.filter(s => s.type === 'photo').length,
        textCount: yearStories.filter(s => s.type !== 'photo').length
      })
    })

    // 尾页
    pages.push({
      type: 'end',
      title: '— 未完待续 —',
      subtitle: '更多回忆，正在讲述'
    })

    this.setData({ pages, total: pages.length, current: 0, hasData: true, loading: false })
  },

  // 翻页回调
  onPageChange(e) {
    this.setData({ current: e.detail.current })
  },

  // 回到首页记录（加回忆）
  goRecord() {
    wx.switchTab({ url: '/pages/index/index' })
  }
})
