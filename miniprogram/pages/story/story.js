// 故事详情页
Page({
  data: {
    story: {},
    relatedStories: [],
    isPlaying: false,
    audioContext: null
  },

  onLoad(options) {
    const id = options.id
    const localStories = wx.getStorageSync('localStories') || []
    const story = localStories.find(s => s.id === id)
    
    if (story) {
      this.setData({ story })
      
      // 找同年代的相关回忆
      const related = localStories.filter(s => 
        s.id !== id && s.era === story.era
      ).slice(0, 3)
      this.setData({ relatedStories: related })
    } else {
      wx.navigateBack()
    }
  },

  playAudio() {
    if (this.data.isPlaying && this.data.audioContext) {
      this.data.audioContext.pause()
      this.setData({ isPlaying: false })
      return
    }

    const story = this.data.story
    if (!story.audioPath) return

    const innerAudioContext = wx.createInnerAudioContext()
    innerAudioContext.src = story.audioPath
    innerAudioContext.play()
    
    innerAudioContext.onPlay(() => {
      this.setData({ isPlaying: true, audioContext: innerAudioContext })
    })
    innerAudioContext.onEnded(() => {
      this.setData({ isPlaying: false })
    })
    innerAudioContext.onError(() => {
      wx.showToast({ title: '播放失败', icon: 'none' })
      this.setData({ isPlaying: false })
    })
  },

  deleteStory() {
    wx.showModal({
      title: '确认删除',
      content: '确定要删除这条回忆吗？',
      success: (res) => {
        if (res.confirm) {
          const id = this.data.story.id
          const localStories = wx.getStorageSync('localStories') || []
          const updated = localStories.filter(s => s.id !== id)
          wx.setStorageSync('localStories', updated)
          wx.showToast({ title: '已删除', icon: 'success' })
          wx.navigateBack()
        }
      }
    })
  },

  goStory(e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({ url: `/pages/story/story?id=${id}` })
  }
})
