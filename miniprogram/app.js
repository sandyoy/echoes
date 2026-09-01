// app.js
const API_BASE = 'https://yuanaikang.cn/api'

// ===== 全局录音单例锁（根治多页面录音状态互扰）=====
// 所有页面共用这一个录音管理器 + 一个全局录制标志，杜绝
// "录音键卡住/一直亮/打字时录音键闪/返回主页还在录音" 等状态泄漏。
let _recorder = null            // wx.getRecorderManager 单例
let _recording = false          // 全局"正在录音"标�志
const _recCallbacks = {}        // 各页面注册的 onStop / onError

function getRecorder() {
  if (!_recorder) {
    _recorder = wx.getRecorderManager()
    // 统一的 onStop：复位全局标志，再通知当前注册的页面回调
    _recorder.onStop((res) => {
      _recording = false
      if (_recCallbacks.onStop) _recCallbacks.onStop(res)
    })
    _recorder.onError((err) => {
      _recording = false
      if (_recCallbacks.onError) _recCallbacks.onError(err)
    })
    _recorder.onStart(() => {
      _recording = true
    })
  }
  return _recorder
}

App({
  globalData: {
    userInfo: null,
    token: null,
    stories: [],
    apiBase: API_BASE
  },

  // ===== 录音全局 API =====

  // 注册当前页面的录音回调（每次进入录音流程前调用）
  registerRecorder(cb) {
    _recCallbacks.onStop = cb.onStop || null
    _recCallbacks.onError = cb.onError || null
  },
  // 清理当前页面的回调
  unregisterRecorder() {
    _recCallbacks.onStop = null
    _recCallbacks.onError = null
  },
  // 全局是否正在录音
  isRecording() {
    return _recording
  },
  // 开始录音（options 缺省用微信默认参数）
  startRecord(opts) {
    if (_recording) return false
    const rec = getRecorder()
    const options = Object.assign({
      duration: 600000,
      sampleRate: 16000,
      numberOfChannels: 1,
      encodeBitRate: 48000,
      format: 'mp3'
    }, opts || {})
    rec.start(options)
    return true
  },
  // 停止录音
  stopRecord() {
    if (_recording) {
      getRecorder().stop()
      // onStop 回调里会复位 _recording
    }
  },
  // 强制复位（页面隐藏/卸载/切换时调用，防止残留）
  forceStopRecord() {
    if (_recording) {
      try { getRecorder().stop() } catch (e) {}
      _recording = false
    }
  },

  onLaunch() {
    // 获取本地存储的登录信息
    const token = wx.getStorageSync('token')
    const userInfo = wx.getStorageSync('userInfo')
    if (token && userInfo) {
      this.globalData.token = token
      this.globalData.userInfo = userInfo
    }
  },

  // 微信登录
  login() {
    return new Promise((resolve, reject) => {
      wx.login({
        success: (res) => {
          if (res.code) {
            wx.request({
              url: `${API_BASE}/auth/wechat`,
              method: 'POST',
              data: { code: res.code },
              success: (resp) => {
                if (resp.data && resp.data.success) {
                  const { user, token } = resp.data
                  this.globalData.userInfo = user
                  this.globalData.token = token
                  wx.setStorageSync('token', token)
                  wx.setStorageSync('userInfo', user)
                  resolve(user)
                } else {
                  reject('登录失败')
                }
              },
              fail: reject
            })
          } else {
            reject('获取code失败')
          }
        },
        fail: reject
      })
    })
  },

  // 获取故事列表
  getStories() {
    return new Promise((resolve, reject) => {
      wx.request({
        url: `${API_BASE}/stories`,
        success: (res) => {
          if (res.statusCode === 200) {
            this.globalData.stories = res.data
            resolve(res.data)
          } else {
            reject('获取故事失败')
          }
        },
        fail: reject
      })
    })
  },

  // AI采访
  aiInterview(message, history) {
    return new Promise((resolve, reject) => {
      wx.request({
        url: `${API_BASE}/ai/interview`,
        method: 'POST',
        data: { message, history },
        success: (res) => {
          if (res.statusCode === 200) {
            resolve(res.data)
          } else {
            reject('AI采访失败')
          }
        },
        fail: reject
      })
    })
  }
})
