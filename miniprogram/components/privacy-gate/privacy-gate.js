/**
 * components/privacy-gate/privacy-gate.js —— 隐私授权闸门（2026-11-26 小鲸鱼加）
 *
 * 用法（页面 .json 里 "usingComponents": {"privacy-gate": "/components/privacy-gate/privacy-gate"}）：
 *   this.selectComponent('#pg').check()   // 进页面时查一次，需要同意就自动弹
 *
 * 铁律：
 *   - 不放行也不拦死：老人点「等会儿再说」→ 照样能用「打字」，只是录音/相册要等同意
 *   - 任何 wx API 缺失（低版本基础库）都不许崩，直接当作「不用管」
 */
Component({
  data: { show: false },

  methods: {
    /** 查微信侧是否还缺「同意隐私政策」这一步 */
    check() {
      if (!wx.getPrivacySetting) return;          // 老基础库没这接口 → 不折腾
      wx.getPrivacySetting({
        success: (res) => {
          if (res && res.needAuthorization) {
            this.setData({ show: true });
            this.triggerEvent('need');
          }
        },
        fail: () => {}                            // 查不到就按「不需要」走，绝不挡住老人
      });
    },

    /** 用户点了「同意」——微信已在按钮层记下同意，这里只负责收起 */
    onAgree() {
      this.setData({ show: false });
      this.triggerEvent('agree');
    },

    /** 看看详细说明（微信托管的隐私指引页） */
    onOpenContract() {
      if (wx.openPrivacyContract) {
        wx.openPrivacyContract({ fail: () => {} });
      }
    },

    /**
     * 等会儿再说：收起弹窗。
     * 注意：mustAgree=true（用户此前明确拒绝过）时，不允许静默跳过——
     * 给一句人话告诉他「要录音得先同意」，但仍然可以退出去打字。
     */
    onLater() {
      this.setData({ show: false });
      this.triggerEvent('later');
    },

    noop() {}
  }
});
