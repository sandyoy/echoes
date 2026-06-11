// AI采访页面 - 支持语音朗读 + 语音输入
const app = getApp()

// API 基础地址
const API_BASE = app.globalData.apiBase || 'https://43.136.31.31/api'

Page({
  data: {
    messages: [],
    inputText: '',
    isThinking: false,
    voicePress: false,
    voiceCancel: false
  },

  // 语音播放器实例
  _audioCtx: null,
  _playingIndex: -1,  // 当前播放的消息索引

  // 录音管理器
  _recorderManager: null,
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

    // 初始化录音管理器
    this._recorderManager = wx.getRecorderManager()
    this._recorderManager.onStop((res) => {
      if (res.duration < 500) {
        wx.showToast({ title: '录音时间太短', icon: 'none' })
        return
      }
      this._uploadAudio(res.tempFilePath)
    })
    this._recorderManager.onError((err) => {
      console.error('录音失败:', err)
      wx.showToast({ title: '录音失败，请重试', icon: 'none' })
    })

    // 发送开场白
    this.sendInitialGreeting()
  },

  onUnload() {
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
    this.setData({ messages, inputText: '', isThinking: true })

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
    this._startY = e.touches[0].clientY
    this._isRecording = true
    this.setData({ voicePress: true, voiceCancel: false })

    // 开启录音
    this._recorderManager.start({
      format: 'mp3',
      sampleRate: 16000,
      numberOfChannels: 1,
      encodeBitRate: 24000
    })

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
    if (deltaY > 50) {
      this.setData({ voiceCancel: true })
    } else {
      this.setData({ voiceCancel: false })
    }
  },

  onVoiceEnd() {
    if (!this._isRecording) return
    const shouldCancel = this.data.voiceCancel
    this._stopRecording(shouldCancel)
  },

  _stopRecording(cancel) {
    this._isRecording = false
    clearTimeout(this._recordTimer)
    
    this.setData({ voicePress: false })

    if (cancel) {
      this._recorderManager.stop()
      wx.showToast({ title: '已取消录音', icon: 'none' })
      return
    }

    this._recorderManager.stop()
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
            // 识别成功，填入输入框
            this.setData({ inputText: data.text })
            // 自动发送
            this.sendMessage()
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
