// AI采访页面 - 支持语音朗读 + 语音输入
const app = getApp()

// API 基础地址
const API_BASE = app.globalData.apiBase || 'https://yuanaikang.cn/api'

Page({
  data: {
    messages: [],
    inputText: '',
    isThinking: false,
    voicePress: false,
    voiceCancel: false,
    hasConversation: false,
    isSaving: false
  },

  // 语音播放器实例
  _audioCtx: null,
  _playingIndex: -1,  // 当前播放的消息索引

  // 录音管理器（状态由全局单例统一管理）
  _startY: 0,
  _isRecording: false,
  _recordTimer: null,

  onLoad() {
    // 初始化音频播放器
    this._audioCtx = wx.createInnerAudioContext()
    this._audioCtx.onEnded(() => {
      // 播放结束，更新 UI
      const idx = this._playingIndex
      if (idx >= 0) {
        const msgs = [...this.data.messages]
        msgs[idx] = { ...msgs[idx], ttsPlaying: false }
        this.setData({ messages: msgs })
        this._playingIndex = -1
      }
    })
    this._audioCtx.onError((err) => {
      console.error('语音播放失败:', err)
      wx.showToast({ title: '语音播放失败', icon: 'none' })
      // 重置状态
      const idx = this._playingIndex
      if (idx >= 0) {
        const msgs = [...this.data.messages]
        msgs[idx] = { ...msgs[idx], ttsPlaying: false }
        this.setData({ messages: msgs })
        this._playingIndex = -1
      }
    })

    // 初始化录音：全部走全局单例录音器（与首页共用，杜绝多实例互扰）
    // 本页注册回调：全局 onStop 会把识别/发送动作接在这里
    app.registerRecorder({
      onStop: (res) => {
        this._isRecording = false
        clearTimeout(this._recordTimer)
        this.setData({ voicePress: false, voiceCancel: false })
        if (res.duration < 500) {
          wx.showToast({ title: '录音时间太短', icon: 'none' })
          return
        }
        // 录音太短不算取消；正常转文字
        this._uploadAudio(res.tempFilePath)
      },
      onError: () => {
        this._isRecording = false
        clearTimeout(this._recordTimer)
        this.setData({ voicePress: false, voiceCancel: false })
        wx.showToast({ title: '录音失败，请重试', icon: 'none' })
      }
    })

    // 预申请录音权限：进入页面就授权好，避免按住说话时才弹授权（授权晚到会导致录音状态卡住）
    wx.getSetting({
      success: (res) => {
        if (!res.authSetting['scope.record']) {
          wx.authorize({
            scope: 'scope.record',
            fail: () => { console.warn('录音权限未授权(采访页)') }
          })
        }
      }
    })

    // 发送开场白
    this.sendInitialGreeting()
  },

  onHide() {
    // 离开页面：强制停录音并清理页面回调，防止录音键/声音残留
    app.forceStopRecord()
    app.unregisterRecorder()
  },
  onUnload() {
    app.forceStopRecord()
    app.unregisterRecorder()
    // 页面卸载时停止播放
    if (this._audioCtx) {
      this._audioCtx.stop()
      this._audioCtx.destroy()
    }
  },

  sendInitialGreeting() {
    const greeting = '您好呀！我是您的回忆采访者。今天想跟我聊聊哪段往事呢？不用着急，随便从哪里说起都行 😊'
    this.setData({
      messages: [{ role: 'ai', content: greeting, ttsUrl: '', ttsLoading: false, ttsPlaying: false }]
    })
    // 自动生成并播放开场白的语音
    this._fetchTTS(0, greeting)
  },

  onInput(e) {
    this.setData({ inputText: e.detail.value })
  },

  // ============= 发送消息 =============

  sendMessage() {
    const text = this.data.inputText.trim()
    if (!text || this.data.isThinking) return

    // 添加用户消息
    const messages = [...this.data.messages, { role: 'user', content: text }]
    this.setData({ messages, inputText: '', isThinking: true, hasConversation: true })

    // 调用AI接口
    app.aiInterview(text, this.data.messages.slice(0, -1)).then(res => {
      const reply = res.reply
      const msgs = [...this.data.messages, { role: 'ai', content: reply, ttsUrl: '', ttsLoading: false, ttsPlaying: false }]
      this.setData({ messages: msgs, isThinking: false })
      
      // 自动生成并播放 AI 回复的语音
      const lastIdx = msgs.length - 1
      this._fetchTTS(lastIdx, reply)
    }).catch(() => {
      // AI不可用时使用模拟回复
      const lastUserMsg = this.data.messages[this.data.messages.length - 1]
      const mockReply = this.getMockReply(lastUserMsg ? lastUserMsg.content : text)
      const msgs = [...this.data.messages, { role: 'ai', content: mockReply, ttsUrl: '', ttsLoading: false, ttsPlaying: false }]
      this.setData({ messages: msgs, isThinking: false })
      
      // 自动生成并播放语音
      const lastIdx = msgs.length - 1
      this._fetchTTS(lastIdx, mockReply)
    })
  },

  sendSuggestion(e) {
    const text = e.currentTarget.dataset.text
    this.setData({ inputText: text })
    this.sendMessage()
  },

  // ============= 保存本次采访为回忆 =============

  saveAsStory() {
    if (this.data.isSaving) return
    // 只取用户说过的内容作为正文（排除开场白和AI回复）
    const userMsgs = this.data.messages.filter(m => m.role === 'user').map(m => m.content)
    if (userMsgs.length === 0) {
      wx.showToast({ title: '还没有采访内容', icon: 'none' })
      return
    }

    this.setData({ isSaving: true })

    // 从用户说的内容里提取主题标签
    const era = getEraFromContent(userMsgs.join(' '))

    // 正文：把问答串起来，保留访谈的完整感
    const qa = this.data.messages
      .filter(m => m.content && (m.role === 'user' || m.role === 'ai'))
      .map(m => (m.role === 'user' ? '我：' : 'AI：') + m.content)
      .join('\n')

    const story = {
      id: 'iv' + Date.now().toString(),
      date: getTodayDate(),
      era,
      content: qa,
      type: 'interview',
      createdAt: new Date().toISOString()
    }

    // 本地保存（采访不是实时存，这里一次性落地）
    const stories = wx.getStorageSync('localStories') || []
    stories.unshift(story)
    wx.setStorageSync('localStories', stories.slice(0, 100))

    wx.showLoading({ title: '正在保存...' })
    wx.request({
      url: `${API_BASE}/stories`,
      method: 'POST',
      data: {
        content: qa,
        date: getTodayDate(),
        era,
        type: 'interview',
        tags: []
      },
      complete: () => {
        wx.hideLoading()
        this.setData({ isSaving: false })
        wx.showToast({ title: '已存为回忆', icon: 'success' })
      }
    })
  },

  // ============= 语音合成（TTS） =============

  _fetchTTS(index, text) {
    // 标记为加载中
    const msgs = [...this.data.messages]
    msgs[index] = { ...msgs[index], ttsLoading: true }
    this.setData({ messages: msgs })

    wx.request({
      url: `${API_BASE}/ai/tts`,
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: { text: text },
      responseType: 'arraybuffer',
      success: (res) => {
        if (res.statusCode === 200) {
          // 将 ArrayBuffer 写入临时文件
          const fsm = wx.getFileSystemManager()
          const tmpPath = `${wx.env.USER_DATA_PATH}/tts_${index}_${Date.now()}.mp3`
          fsm.writeFile({
            filePath: tmpPath,
            data: res.data,
            encoding: 'binary',
            success: () => {
              const msgs = [...this.data.messages]
              msgs[index] = { ...msgs[index], ttsLoading: false, ttsUrl: tmpPath }
              this.setData({ messages: msgs })
              // 自动播放
              this._playTTS(index)
            },
            fail: (err) => {
              console.error('写入临时文件失败:', err)
              const msgs = [...this.data.messages]
              msgs[index] = { ...msgs[index], ttsLoading: false }
              this.setData({ messages: msgs })
            }
          })
        } else {
          // TTS 失败，静默降级（只显示文字）
          console.warn('TTS 请求失败:', res.statusCode)
          const msgs = [...this.data.messages]
          msgs[index] = { ...msgs[index], ttsLoading: false }
          this.setData({ messages: msgs })
        }
      },
      fail: (err) => {
        console.warn('TTS 请求异常:', err.errMsg)
        const msgs = [...this.data.messages]
        msgs[index] = { ...msgs[index], ttsLoading: false }
        this.setData({ messages: msgs })
      }
    })
  },

  _playTTS(index) {
    const msg = this.data.messages[index]
    if (!msg || !msg.ttsUrl) return

    // 停止当前播放
    if (this._playingIndex >= 0 && this._playingIndex !== index) {
      this._audioCtx.stop()
      const oldMsgs = [...this.data.messages]
      if (oldMsgs[this._playingIndex]) {
        oldMsgs[this._playingIndex] = { ...oldMsgs[this._playingIndex], ttsPlaying: false }
      }
      this.setData({ messages: oldMsgs })
    }

    // 如果点击的是正在播放的，暂停
    if (this._playingIndex === index && msg.ttsPlaying) {
      this._audioCtx.pause()
      const msgs = [...this.data.messages]
      msgs[index] = { ...msgs[index], ttsPlaying: false }
      this.setData({ messages: msgs })
      return
    }

    // 播放
    this._audioCtx.src = msg.ttsUrl
    this._audioCtx.play()
    this._playingIndex = index
    const msgs = [...this.data.messages]
    msgs[index] = { ...msgs[index], ttsPlaying: true }
    this.setData({ messages: msgs })
  },

  onPlayTTS(e) {
    const index = e.currentTarget.dataset.index
    this._playTTS(index)
  },

  // ============= 语音输入 =============

  onVoiceStart(e) {
    // 全局互锁：别处（如有）正在录就不录；本页已在录也不重复
    if (app.isRecording() || this._isRecording) return

    this._startY = e.touches[0].clientY
    this._isRecording = true
    this.setData({ voicePress: true, voiceCancel: false })

    if (!app.startRecord({
      format: 'mp3',
      sampleRate: 16000,
      numberOfChannels: 1,
      encodeBitRate: 24000
    })) {
      this._isRecording = false
      this.setData({ voicePress: false })
      wx.showToast({ title: '录音启动失败', icon: 'none' })
      return
    }
    // 录音超时保护（60秒自动停止）
    this._recordTimer = setTimeout(() => {
      if (this._isRecording) {
        this._stopRecording(false)
      }
    }, 60000)
  },

  onVoiceMove(e) {
    if (!this._isRecording) return
    const moveY = e.touches[0].clientY
    const deltaY = this._startY - moveY
    // 上滑超过 50px 显示取消区域
    this.setData({ voiceCancel: deltaY > 50 })
  },

  onVoiceEnd() {
    if (!this._isRecording) return
    const shouldCancel = this.data.voiceCancel
    this._stopRecording(shouldCancel)
  },

  _stopRecording(cancel) {
    this._isRecording = false
    clearTimeout(this._recordTimer)
    // 全局停止（无论是否取消，都停；取消时不转文字）
    if (cancel) {
      app.forceStopRecord()
      this.setData({ voicePress: false, voiceCancel: false })
      wx.showToast({ title: '已取消录音', icon: 'none' })
    } else {
      app.stopRecord() // 正常停止，onStop 回调会转文字+发送
    }
  },

  _uploadAudio(tempFilePath) {
    wx.showLoading({ title: '识别语音中...' })

    wx.uploadFile({
      url: `${API_BASE}/ai/asr`,
      filePath: tempFilePath,
      name: 'audio',
      success: (res) => {
        wx.hideLoading()
        try {
          const data = JSON.parse(res.data)
          if (data.text && data.text !== '(未能识别)') {
            // 识别成功：直接用文字发送（不走 inputText 异步 setData，避免读到旧值发不出）
            this.sendMessageWithText(data.text)
          } else {
            wx.showToast({ title: '未能识别语音内容', icon: 'none' })
          }
        } catch (e) {
          console.error('解析ASR结果失败:', e)
          wx.showToast({ title: '语音识别异常', icon: 'none' })
        }
      },
      fail: (err) => {
        wx.hideLoading()
        console.error('上传录音失败:', err)
        wx.showToast({ title: '上传录音失败', icon: 'none' })
      }
    })
  },

  // 用指定文字发送消息（语音识别专用，避开 inputText 异步 setData 的坑）
  sendMessageWithText(text) {
    const trimmed = (text || '').trim()
    if (!trimmed || this.data.isThinking) return
    // 直接以文字发消息，不依赖 inputText
    const messages = [...this.data.messages, { role: 'user', content: trimmed }]
    this.setData({ messages, isThinking: true, hasConversation: true })
    // 调用AI接口
    app.aiInterview(trimmed, messages.slice(0, -1)).then(res => {
      const reply = res.reply
      const msgs = [...this.data.messages, { role: 'ai', content: reply, ttsUrl: '', ttsLoading: false, ttsPlaying: false }]
      this.setData({ messages: msgs, isThinking: false })
      const lastIdx = msgs.length - 1
      this._fetchTTS(lastIdx, reply)
    }).catch(() => {
      const mockReply = this.getMockReply(trimmed)
      const msgs = [...this.data.messages, { role: 'ai', content: mockReply, ttsUrl: '', ttsLoading: false, ttsPlaying: false }]
      this.setData({ messages: msgs, isThinking: false })
      const lastIdx = msgs.length - 1
      this._fetchTTS(lastIdx, mockReply)
    })
  },

  // ============= 模拟回复 =============

  getMockReply(text) {
    const replies = {
      '童年': '小时候的事儿总是特别清晰呢。您那时候最喜欢跟谁一起玩呀？',
      '学校': '上学的时候总有一些特别难忘的事。您还记得您的第一位老师吗？',
      '工作': '第一份工作总是让人印象深刻的。当时是怎么找到那份工作的呢？',
      '结婚': '结婚那天一定很特别吧？能跟我聊聊那天最难忘的细节吗？',
      '孩子': '孩子是父母最大的牵挂。孩子小时候有没有什么让您特别开心的事？',
      '父母': '说起父母，总让人心里暖暖的。您觉得您最像他们哪一点？',
      '朋友': '老朋友最珍贵了。您跟这位朋友是怎么认识的？',
      '老家': '老家总是充满了回忆。您现在还会经常想起那里的样子吗？',
      'default': '嗯，我在认真听。您能再多说说那段时光吗？那时候您是什么感觉？'
    }
    for (const [key, reply] of Object.entries(replies)) {
      if (text.includes(key)) return reply
    }
    return replies['default']
  }
})

// ============= 工具函数 =============
function getTodayDate() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
}

const IV_TOPICS = ['童年','小学','求学','工作','结婚','恋爱','孩子','父母','老家','朋友','退休','旅行']

function getEraFromContent(text) {
  for (const t of IV_TOPICS) {
    if (text.includes(t)) return t
  }
  return '其他'
}
