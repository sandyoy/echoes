// 确认·编辑·保存页 —— 一段回忆落地（含年份归轴 / 原声双份 / 后端同步）
const app = getApp()
const API_BASE = app.globalData.apiBase || 'https://yuanaikang.cn/api'

Page({
  data: {
    content: '',
    audioPath: '',      // 语音来源的原声（可回放）
    sourceType: 'text', // text | voice | single(采访单句)
    sourceDur: 0,
    playing: false,
    yearStr: '',        // 选定的年份，存为 YYYY
    currYear: '',
    yearQuickList: [],
    curYearLabel: '',   // 当前选中的快捷标签（"今年"/"近年"等）
    saving: false
  },

  _audioCtx: null,

  onLoad(query) {
    // 听众：语音单句原样带入
    let content = decodeURIComponent(query.content || '')
    let audioPath = query.audioPath || ''
    let sourceType = query.sourceType || 'text'
    let dur = parseInt(query.dur || '0', 10)

    // 口语式来源：无声给占位壳，让老人补字或放弃
    if ((sourceType === 'voice' || sourceType === 'single') && !content.trim() && audioPath) {
      content = dur > 0 ? `[一段语音回忆${dur}秒]` : '[一段语音回忆]'
    }

    const now = new Date()
    const year = now.getFullYear()
    const quick = []
    const last2 = []
    for (let i = 0; i < 3; i++) last2.push(`${year - i}年`)
    quick.push('今年', ...last2, '50年前/更早', '记不清年份')

    this._audioCtx = wx.createInnerAudioContext()
    this._audioCtx.onEnded(() => this.setData({ playing: false }))
    this._audioCtx.onError(() => { this.setData({ playing: false }); wx.showToast({ title: '无法播放', icon: 'none' }) })

    this.setData({
      content,
      audioPath,
      sourceType,
      sourceDur: dur,
      yearStr: String(year),
      currYear: String(year),
      yearQuickList: quick,
      curYearLabel: '今年'
    })
  },

  onUnload() {
    if (this._audioCtx) { this._audioCtx.stop(); this._audioCtx.destroy() }
  },

  onContentInput(e) {
    this.setData({ content: e.detail.value })
  },

  // 快捷年份标签
  pickYearLabel(e) {
    const label = e.currentTarget.dataset.year
    const nowY = parseInt(this.data.currYear, 10)
    let y = nowY
    if (label === '今年') y = nowY
    else if (label.startsWith('50年前')) y = nowY - 50
    else {
      const m = label.match(/^(\d{4})年$/)
      if (m) y = parseInt(m[1], 10)
    }
    this.setData({ yearStr: String(y), curYearLabel: /^(\d{4})年$/.test(label) || label === '今年' ? label : (label === '记不清年份' ? nowY : label) })
    if (label === '记不清年份') this.setData({ curYearLabel: '记不清年份' })
  },

  // 自定义picker年份
  onYearPick(e) {
    const v = e.detail.value || ''
    const y = v.substring(0, 4)
    if (!y) return
    this.setData({ yearStr: y, curYearLabel: '' })
    if (y === String(this.data.currYear)) this.setData({ curYearLabel: '今年' })
  },

  // 回放原声
  togglePlayAudio() {
    if (!this.data.audioPath) return
    if (this.data.playing) { this._audioCtx.pause(); this.setData({ playing: false }) }
    else {
      this._audioCtx.stop()
      this._audioCtx.src = this.data.audioPath
      this._audioCtx.play()
      this.setData({ playing: true })
    }
  },

  cancel() {
    if (this.data.saving) return
    wx.navigateBack({ fail: () => wx.switchTab({ url: '/pages/index/index' }) })
  },

  // 真正落库
  saveAll() {
    const text = this.data.content.trim()
    if (!text || this.data.saving) return
    this.setData({ saving: true })

    const year = this.data.yearStr || String(this.data.currYear)
    // date 语义 = 事件所属年份（编辑可以改，不再恒等于今天），让时光轴正确按年归组
    const date = `${year}-01-01`
    const type = this.data.sourceType === 'voice' ? 'audio'
      : (this.data.sourceType === 'single' ? 'interview' : 'text')
    const dur = this.data.sourceDur
    const audioPath = this.data.audioPath

    const story = {
      id: Date.now().toString(),
      date,
      recalledInYear: String(this.data.currYear), // 记录是"今年"整理入册的
      era: getEraFromContent(text) || '其他',
      content: text,
      type,
      audioPath,
      durationSec: dur,
      createdAt: new Date().toISOString()
    }

    // 1) 本地必落(最终数据源，绝不丢)
    const stories = wx.getStorageSync('localStories') || []
    stories.unshift(story)
    wx.setStorageSync('localStories', stories.slice(0, 150))

    // 2) 后端同步(尽力，失败不阻塞)
    let synced = Promise.resolve()
    try {
      synced = new Promise((ok, no) => wx.request({
        url: `${API_BASE}/stories`,
        method: 'POST',
        data: {
          content: text, date, era: story.era, type,
          tags: []
        },
        success: (r) => ((r.statusCode === 200 || r.statusCode === 201) ? ok() : no(r)),
        fail: no
      }))
    } catch (e) { synced = Promise.resolve() }

    // 3) 语音原声尽力上传
    synced.then(() => {
      if (audioPath) {
        try {
          wx.uploadFile({
            url: `${API_BASE}/stories/audio`,
            filePath: audioPath,
            name: 'audio',
            formData: { type, content: text, era: story.era, year, duration: String(dur || 0) },
            fail: () => {}
          })
        } catch (e) { /* ignore */ }
      }
      done(this)
    }).catch(() => done(this)) // 后端失败也不阻塞，本地已存

    function done(ctx) {
      ctx.setData({ saving: false })
      wx.showToast({ title: '已存进时光轴', icon: 'success' })
      setTimeout(() => wx.navigateBack({ fail: () => wx.switchTab({ url: '/pages/timeline/timeline' }) }), 600)
    }
  }
})

// 主题标签辅助
const TOPICS = ['童年', '小学', '求学', '工作', '结婚', '恋爱', '孩子', '父母', '老家', '朋友', '退休', '旅行']
function getEraFromContent(text) {
  for (const t of TOPICS) if (text.includes(t)) return t
  return '其他'
}
