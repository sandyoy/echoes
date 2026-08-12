// 首页 - 记录回忆
const app = getApp()

Page({
  data: {
    isRecording: false,
    currentMode: 'self',    // self | interview | type
    typeContent: '',
    stories: [],
    showRecordingToast: false,
    recorderManager: null
  },

  onLoad() {
    this.loadStories()
    
    // 初始化录音管理器
    this.recorderManager = wx.getRecorderManager()
    this.recorderManager.onStart(() => {
      this.setData({ isRecording: true, showRecordingToast: true })
    })
    this.recorderManager.onStop((res) => {
      this.setData({ isRecording: false, showRecordingToast: false })
      if (res.duration > 1000) { // 超过1秒才保存
        this.saveAudioStory(res)
      }
    })
    this.recorderManager.onError(() => {
      wx.showToast({ title: '录音失败', icon: 'none' })
      this.setData({ isRecording: false, showRecordingToast: false })
    })
  },

  onShow() {
    this.loadStories()
  },

  // 加载故事列表
  loadStories() {
    const stories = app.globalData.stories
    if (stories && stories.length > 0) {
      this.setData({ stories: stories.slice(0, 5) })
    } else {
      app.getStories().then(list => {
        this.setData({ stories: list.slice(0, 5) })
      }).catch(() => {
        // 加载失败，用本地存储的数据
        const local = wx.getStorageSync('localStories') || []
        this.setData({ stories: local.slice(0, 5) })
      })
    }
  },

  // 开始录音
  startRecording() {
    if (this.data.currentMode !== 'self') return
    
    // 检查录音权限
    wx.authorize({
      scope: 'scope.record',
      success: () => {
        const options = {
          duration: 600000,     // 最长10分钟
          sampleRate: 16000,
          numberOfChannels: 1,
          encodeBitRate: 48000,
          format: 'mp3'
        }
        this.recorderManager.start(options)
      },
      fail: () => {
        wx.showModal({
          title: '需要录音权限',
          content: '请在设置中开启录音权限，才能记录您的声音回忆',
          showCancel: false
        })
      }
    })
  },

  // 停止录音
  stopRecording() {
    if (this.data.isRecording) {
      this.recorderManager.stop()
    }
  },

  // 保存录音故事
  saveAudioStory(res) {
    const { tempFilePath, duration, fileSize } = res
    
    wx.showLoading({ title: '正在保存...' })
    
    // 上传音频文件
    wx.uploadFile({
      url: `${app.globalData.apiBase}/stories/audio`,
      filePath: tempFilePath,
      name: 'audio',
      formData: {
        type: 'audio',
        era: getEraFromDate(new Date()),
        duration: Math.floor(duration / 1000)
      },
      success: (resp) => {
        wx.hideLoading()
        if (resp.statusCode === 201 || resp.statusCode === 200) {
          wx.showToast({ title: '回忆已保存', icon: 'success' })
          this.loadStories()
        } else {
          // 后端暂不支持音频上传，本地保存
          this.saveLocalStory(res)
        }
      },
      fail: () => {
        wx.hideLoading()
        // 离线保存
        this.saveLocalStory(res)
      }
    })
  },

  // 本地保存（后端不支持时的降级方案）
  saveLocalStory(res) {
    const stories = wx.getStorageSync('localStories') || []
    const newStory = {
      id: Date.now().toString(),
      date: getTodayDate(),
      era: getEraFromDate(new Date()),
      content: `[语音回忆 ${Math.floor(res.duration / 1000)}秒]`,
      type: 'audio',
      audioPath: res.tempFilePath,
      createdAt: new Date().toISOString()
    }
    stories.unshift(newStory)
    wx.setStorageSync('localStories', stories.slice(0, 100))
    app.globalData.stories = stories
    
    wx.hideLoading()
    wx.showToast({ title: '回忆已保存（本地）', icon: 'success' })
    this.loadStories()
  },

  // 切换模式
  switchMode(e) {
    const mode = e.currentTarget.dataset.mode
    this.setData({ currentMode: mode })
  },

  // 打字输入
  onTypeInput(e) {
    this.setData({ typeContent: e.detail.value })
  },

  // 提交文字回忆
  submitType() {
    const content = this.data.typeContent.trim()
    if (!content) return

    wx.showLoading({ title: '正在保存...' })

    wx.request({
      url: `${app.globalData.apiBase}/stories`,
      method: 'POST',
      data: {
        content,
        date: getTodayDate(),
        era: getEraFromContent(content),
        type: 'text',
        tags: []
      },
      success: (res) => {
        wx.hideLoading()
        if (res.statusCode === 201) {
          wx.showToast({ title: '回忆已保存', icon: 'success' })
          this.setData({ typeContent: '' })
          this.loadStories()
        }
      },
      fail: () => {
        wx.hideLoading()
        // 离线保存
        const stories = wx.getStorageSync('localStories') || []
        stories.unshift({
          id: Date.now().toString(),
          date: getTodayDate(),
          era: getEraFromContent(content),
          content,
          type: 'text',
          createdAt: new Date().toISOString()
        })
        wx.setStorageSync('localStories', stories.slice(0, 100))
        wx.showToast({ title: '回忆已保存', icon: 'success' })
        this.setData({ typeContent: '' })
        this.loadStories()
      }
    })
  },

  // 进入AI采访
  goInterview() {
    wx.navigateTo({ url: '/pages/interview/interview' })
  },

  // 进入时间轴
  goTimeline() {
    wx.switchTab({ url: '/pages/timeline/timeline' })
  },

  // 进入故事详情
  goStory(e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({ url: `/pages/story/story?id=${id}` })
  }
})

// 工具函数
function getTodayDate() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
}

function getEraFromDate(date) {
  const year = date.getFullYear()
  if (year >= 2020) return '近年'
  if (year >= 2010) return '2010年代'
  if (year >= 2000) return '2000年代'
  if (year >= 1990) return '1990年代'
  if (year >= 1980) return '1980年代'
  if (year >= 1970) return '1970年代'
  return '更早'
}

const TOPICS = ['童年','小学','求学','工作','结婚','恋爱','孩子','父母','老家','朋友','退休','旅行']

function getEraFromContent(text) {
  for (const t of TOPICS) {
    if (text.includes(t)) return t
  }
  return '其他'
}
