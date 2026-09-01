// 首页 - 记录回忆
const app = getApp()

Page({
  data: {
    isRecording: false,
    currentMode: 'self',    // self | interview | type
    typeContent: '',
    stories: [],
    showRecordingToast: false,
    transcript: '',
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

  // 加载故事列表（统一从本地读，本地是最终数据源，后端仅作同步）
  loadStories() {
    const local = wx.getStorageSync('localStories') || []
    const list = this.storyCache && this.storyCache.length >= local.length
      ? this.storyCache
      : local
    this.setData({ stories: list.slice(0, 5) })
  },

  // 开始录音
  startRecording() {
    if (this.data.currentMode !== 'self') return
    // 状态锁：防止重复触发 start（异步时序下 authorize 回调晚到会重复启动）
    if (this.data.isRecording) return
    
    const start = () => {
      if (this.data.isRecording) return
      const options = {
        duration: 600000,     // 最长10分钟
        sampleRate: 16000,
        numberOfChannels: 1,
        encodeBitRate: 48000,
        format: 'mp3'
      }
      try {
        this.recorderManager.start(options)
      } catch (e) {
        console.log('start err', e)
      }
    }
    
    // 已授权过就直接开始；未授权先申请
    wx.getSetting({
      success: (res) => {
        if (res.authSetting['scope.record']) {
          start()
        } else {
          wx.authorize({
            scope: 'scope.record',
            success: () => { start() },
            fail: () => {
              wx.showModal({
                title: '需要录音权限',
                content: '请在设置中开启录音权限，才能记录您的声音回忆',
                showCancel: false
              })
            }
          })
        }
      }
    })
  },

  // 停止录音
  stopRecording() {
    // 只有确实在录音时才停止，避免授权时序导致的"空stop晚到"
    if (this.data.isRecording) {
      try {
        this.recorderManager.stop()
      } catch (e) {
        console.log('stop err', e)
      }
    }
  },

  // 页面隐藏/卸载时强制停止，防止返回主页录音器还挂着（修复"返回后自动录音"bug）
  onHide() {
    this.forceStopRecording()
  },
  onUnload() {
    this.forceStopRecording()
  },

  forceStopRecording() {
    if (this.data.isRecording) {
      try { this.recorderManager.stop() } catch (e) {}
      this.setData({ isRecording: false, showRecordingToast: false })
    }
  },

  // 保存录音故事（先转文字，再保存）
  saveAudioStory(res) {
    const { tempFilePath, duration, fileSize } = res
    const dur = Math.floor(duration / 1000)
    
    // 第一步：调用语音识别，把语音转成文字
    wx.showLoading({ title: '识别语音中...' })
    this.asrAudio(tempFilePath).then(text => {
      wx.hideLoading()
      const content = (text && text !== '(未能识别)') ? text : `[语音回忆 ${dur}秒]`
      // 第二步：后端保存（文字+音频），失败则本地保存
      this.uploadStory(tempFilePath, content, dur)
    }).catch(() => {
      wx.hideLoading()
      // ASR失败，降级：以占位文字保存
      const content = `[语音回忆 ${dur}秒]`
      this.uploadStory(tempFilePath, content, dur)
    })
  },

  // 调用语音识别接口
  asrAudio(filePath) {
    return new Promise((resolve, reject) => {
      wx.uploadFile({
        url: `${app.globalData.apiBase}/ai/asr`,
        filePath: filePath,
        name: 'audio',
        success: (res) => {
          try {
            const data = JSON.parse(res.data)
            const text = data.text || ''
            this.setData({ transcript: text || '[未能识别出文字]' })
            resolve(text || '[未能识别出文字]')
          } catch (e) {
            reject(e)
          }
        },
        fail: reject
      })
    })
  },

  // 上传保存（后端优先，本地兜底）
  uploadStory(tempFilePath, content, dur) {
    wx.showLoading({ title: '正在保存...' })
    wx.uploadFile({
      url: `${app.globalData.apiBase}/stories/audio`,
      filePath: tempFilePath,
      name: 'audio',
      formData: {
        type: 'audio',
        content: content,
        era: getEraFromContent(content),
        duration: dur
      },
      success: (resp) => {
        wx.hideLoading()
        if (resp.statusCode === 201 || resp.statusCode === 200) {
          wx.showToast({ title: '回忆已保存', icon: 'success' })
        } else {
          // 后端暂不支持，本地保存
          this.saveLocalStory(tempFilePath, content, dur)
        }
        this.loadStories()
      },
      fail: () => {
        wx.hideLoading()
        // 网络异常，本地保存
        this.saveLocalStory(tempFilePath, content, dur)
        this.loadStories()
      }
    })
  },

  // 本地保存（后端不支持时的降级方案）
  saveLocalStory(tempFilePath, content, dur) {
    const stories = wx.getStorageSync('localStories') || []
    const newStory = {
      id: Date.now().toString(),
      date: getTodayDate(),
      era: getEraFromContent(content),
      content: content,
      type: 'audio',
      audioPath: tempFilePath,
      createdAt: new Date().toISOString()
    }
    stories.unshift(newStory)
    wx.setStorageSync('localStories', stories.slice(0, 100))
    app.globalData.stories = stories
    this.storyCache = stories

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

    // 无论后端是否成功，都先本地保存一份，保证用户数据不丢
    const newStory = {
      id: Date.now().toString(),
      date: getTodayDate(),
      era: getEraFromContent(content),
      content,
      type: 'text',
      createdAt: new Date().toISOString()
    }
    const stories = wx.getStorageSync('localStories') || []
    stories.unshift(newStory)
    wx.setStorageSync('localStories', stories.slice(0, 100))
    app.globalData.stories = stories

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
        // 后端返回 200 / 201 都算保存成功
        if (res.statusCode === 200 || res.statusCode === 201) {
          wx.showToast({ title: '回忆已保存', icon: 'success' })
        } else {
          // 后端返回异常，但本地已保存，仍提示成功
          wx.showToast({ title: '回忆已保存（本地）', icon: 'success' })
        }
        this.setData({ typeContent: '' })
        this.loadStories()
      },
      fail: () => {
        wx.hideLoading()
        // 网络异常，本地已保存，提示成功
        wx.showToast({ title: '回忆已保存（本地）', icon: 'success' })
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
