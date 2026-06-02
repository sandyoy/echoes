// AI采访页面
const app = getApp()

Page({
  data: {
    messages: [],
    inputText: '',
    isThinking: false
  },

  onLoad() {
    // 如果是从首页直接进入，发送开场白
    this.sendInitialGreeting()
  },

  sendInitialGreeting() {
    const greeting = '您好呀！我是您的回忆采访者。今天想跟我聊聊哪段往事呢？不用着急，随便从哪里说起都行 😊'
    this.setData({
      messages: [{ role: 'ai', content: greeting }]
    })
  },

  onInput(e) {
    this.setData({ inputText: e.detail.value })
  },

  sendMessage() {
    const text = this.data.inputText.trim()
    if (!text || this.data.isThinking) return

    // 添加用户消息
    const messages = [...this.data.messages, { role: 'user', content: text }]
    this.setData({ messages, inputText: '', isThinking: true })

    // 调用AI接口
    app.aiInterview(text, this.data.messages.slice(0, -1)).then(res => {
      const msgs = [...this.data.messages, { role: 'ai', content: res.reply }]
      this.setData({ messages: msgs, isThinking: false })
    }).catch(() => {
      // AI不可用时使用模拟回复
      const mockReply = this.getMockReply(text)
      const msgs = [...this.data.messages, { role: 'ai', content: mockReply }]
      this.setData({ messages: msgs, isThinking: false })
    })
  },

  sendSuggestion(e) {
    const text = e.currentTarget.dataset.text
    this.setData({ inputText: text })
    this.sendMessage()
  },

  startVoiceInput() {
    wx.showToast({ title: '语音输入开发中', icon: 'none' })
  },

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
