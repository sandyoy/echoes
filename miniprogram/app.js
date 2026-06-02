// app.js
const API_BASE = 'https://43.136.31.31/api'

App({
  globalData: {
    userInfo: null,
    token: null,
    stories: [],
    apiBase: API_BASE
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
