// 首页 - 记录回忆
const app = getApp()

Page({
  data: {
    isRecording: false,
    currentMode: 'self',    // self | interview | type
    typeContent: '',
    stories: [],
    showRecordingToast: false
  },

  onLoad() {
    this.loadStories()
    
    // 全局录音器：注册本页回调（本页 focus 时）
    app.registerRecorder({
      onStop: (res) => {
        this.setData({ isRecording: false, showRecordingToast: false })
        // 松手后：超过1秒才进入"确认-编辑-保存"
        if (res.duration > 1000) {
          this.toSaveFromVoice(res)
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
  // 录音结束 → 后台转文字 → 跳"确认·编辑·保存"页
  toSaveFromVoice(res) {
    const { tempFilePath, duration } = res
    const dur = Math.floor(duration / 1000)
    wx.showLoading({ title: '识别语音中...' })
    wx.uploadFile({
      url: `${app.globalData.apiBase}/ai/asr`,
      filePath: tempFilePath,
      name: 'audio',
      success: (r) => {
        wx.hideLoading()
        let text = ''
        try { text = (JSON.parse(r.data).text) || '' } catch (e) { text = '' }
        if (text && text !== '(未能识别)' && text !== '[未能识别出文字]') {
          this.openSavePage(text, tempFilePath, 'voice', dur)
        } else {
          // 转不出来：把未识别也带进保存页，让老人能补字/放弃（绝不静默丢）
          wx.showToast({ title: '没能自动转文字，可手动补写', icon: 'none' })
          this.openSavePage('', tempFilePath, 'voice', dur)
        }
      },
      fail: () => {
        wx.hideLoading()
        wx.showToast({ title: '识别失败，可手动写或重录', icon: 'none' })
        this.openSavePage('', tempFilePath, 'voice', dur)
      }
    })
  },

  // 跳转通用的"确认-编辑-保存"页
  openSavePage(content, audioPath, sourceType, dur) {
    const q = [
      'content=' + encodeURIComponent(content || ''),
      'sourceType=' + (sourceType || 'text'),
      'dur=' + (dur || 0)
    ]
    if (audioPath) q.push('audioPath=' + encodeURIComponent(audioPath))
    wx.navigateTo({ url: '/pages/save/save?' + q.join('&') })
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

  // 打字的"保存"→ 跳到统一"确认·编辑·保存"页（顺带选年份），不再当场静默落库
  submitType() {
    const content = this.data.typeContent.trim()
    if (!content) return
    this.openSavePage(content, '', 'text', 0)
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
