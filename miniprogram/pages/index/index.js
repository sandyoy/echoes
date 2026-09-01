// 首页 - 记录回忆
const app = getApp()

Page({
  data: {
    isRecording: false,
    currentMode: 'self',    // self | interview | type
    typeContent: '',
    stories: [],
    showRecordingToast: false,
    transcript: ''
  },

  onLoad() {
    this.loadStories()
    
    // 全局录音器：注册本页回调（本页 focus 时）
    app.registerRecorder({
      onStop: (res) => {
        this.setData({ isRecording: false, showRecordingToast: false })
        // 松手后：超过1秒才识别保存
        if (res.duration > 1000) {
          this.transcript = ''
          this.setData({ transcript: '' })
          this.saveAudioStory(res)
        } else {
          wx.showToast({ title: '说话时间太短', icon: 'none' })
        }
      },
      onError: () => {
        this.setData({ isRecording: false, showRecordingToast: false })
        wx.showToast({ title: '录音失败，请重试', icon: 'none' })
      }
    })
  },

  onShow() {
    this.loadStories()
    // 预申请录音权限：进入页面就授权好，避免按住说话时才弹授权（授权晚到会导致录音状态卡住）
    wx.getSetting({
      success: (res) => {
        if (!res.authSetting['scope.record']) {
          wx.authorize({
            scope: 'scope.record',
            fail: () => {
              // 用户拒绝或未处理：仅记录，不影响页面其他功能
              console.warn('录音权限未授权')
            }
          })
        }
      }
    })
  },
  // 页面离开/卸载时强制停掉全局录音并清回调，防止录音键回主页还亮着
  onHide() {
    app.forceStopRecord()
    app.unregisterRecorder()
  },
  onUnload() {
    app.forceStopRecord()
    app.unregisterRecorder()
  },

  // 加载故事列表（统一从本地读，本地是最终数据源，后端仅作同步）
  loadStories() {
    const local = wx.getStorageSync('localStories') || []
    const list = this.storyCache && this.storyCache.length >= local.length
      ? this.storyCache
      : local
    this.setData({ stories: list.slice(0, 5) })
  },

  // 开始录音（只在自述模式生效）
  startRecording() {
    if (this.data.currentMode !== 'self') return
    // 全局互锁：别处(如采访页)正在录就不录；本页已在录也不重复
    if (app.isRecording() || this.data.isRecording) return
    // 立即刷新 UI（不等 onStart 回调，按下即亮，避免闪烁）
    this.setData({ isRecording: true, showRecordingToast: true })
    const ok = app.startRecord()
    if (!ok) {
      this.setData({ isRecording: false, showRecordingToast: false })
    }
  },

  // 停止录音（松手/取消）
  stopRecording() {
    // 无论全局状态如何都尝试停，确保不残留（app.stopRecord 内部会判断）
    app.stopRecord()
    // UI 复位交给全局 onStop 回调；这里也兜底复位，防极个别回调丢失
    this.setData({ isRecording: false, showRecordingToast: false })
  },
  // 保存录音故事（先转文字，再以文字为主保存；音频尽力上传不影响保存）
  saveAudioStory(res) {
    const { tempFilePath, duration } = res
    const dur = Math.floor(duration / 1000)

    // 第一步：调用语音识别，把语音转成文字
    wx.showLoading({ title: '识别语音中...' })
    this.asrAudio(tempFilePath).then(text => {
      wx.hideLoading()
      const content = (text && text !== '(未能识别)') ? text : `[语音回忆 ${dur}秒]`
      // 第二步：以文字为主保存（后端+本地双保险，绝不因音频上传失败而丢）
      this.uploadTextStory(tempFilePath, content, dur)
    }).catch(() => {
      wx.hideLoading()
      // ASR失败，降级：以占位文字保存（不阻塞用户）
      wx.showToast({ title: '语音识别失败，已按语音保存', icon: 'none' })
      const content = `[语音回忆 ${dur}秒]`
      this.uploadTextStory(tempFilePath, content, dur)
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

  // 以文字为主保存（后端 POST + 本地双保险），音频文件尽力附带上传
  uploadTextStory(tempFilePath, content, dur) {
    const newStory = {
      id: Date.now().toString(),
      date: getTodayDate(),
      era: getEraFromContent(content),
      content,
      type: 'audio',
      audioPath: tempFilePath,
      createdAt: new Date().toISOString()
    }
    // 1) 先本地保存（数据必不丢）
    const stories = wx.getStorageSync('localStories') || []
    stories.unshift(newStory)
    wx.setStorageSync('localStories', stories.slice(0, 100))
    app.globalData.stories = stories
    this.storyCache = stories
    this.loadStories()

    wx.showLoading({ title: '正在保存...' })
    // 2) 后端保存文字版（实测201成功）
    let synced = Promise.reject()
    try {
      synced = new Promise((resolve, reject) => {
        wx.request({
          url: `${app.globalData.apiBase}/stories`,
          method: 'POST',
          data: {
            content,
            date: getTodayDate(),
            era: getEraFromContent(content),
            type: 'audio'
          },
          success: (r) => (r.statusCode === 200 || r.statusCode === 201) ? resolve(r.data) : reject(r),
          fail: reject
        })
      })
    } catch (e) { synced = Promise.reject(e) }

    synced.finally(() => {
      wx.hideLoading()
    })
    // 3) 音频文件尽力上传（失败不影响已保存的文字）
    synced.then(() => {
      try {
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
          fail: () => { /* 音频上传失败静默，文字已保存 */ }
        })
      } catch (e) { /* ignore */ }
      wx.showToast({ title: '回忆已保存', icon: 'success' })
    }).catch(() => {
      // 后端同步失败，本地已保存，仍提示成功
      wx.showToast({ title: '已保存（本地）', icon: 'success' })
    })
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
