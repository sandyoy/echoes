/**
 * pages/interview/interview.js —— 采访页（AI 记者对话流 + 可打断 + 归类弹层）
 *
 * 依据：docs/事卷/接口定义_采访引导v1_20261008.md（小鲸鱼 10-08 v1，6 handler / 自测 37/37）
 *       docs/需求书_往事可追忆_另起炉灶版_v2.4_20260923.md §七（采访引导·含可打断）+ §5.3（人生锚点）
 *
 * 四条铁律（接口定义 §四，前端必须守）：
 *   1) 打断要快 —— 出声 → stop_tts 就停 TTS（延迟须真机测，不许凭印象承诺）
 *   2) 打断不丢话题 —— next 回填 interrupted_question，先接回再接别的
 *   3) AI 主动让路 —— 每问完留 wait_ms，不连珠炮
 *   4) 任何反应都不算错 —— 含糊/超时/重问耗尽 → 一律默认新建，绝不卡住老人
 *
 * 本页只做「播放问句 / 收声 / 调接口」，不自己判定打断、不自己归类（判定全在后端）。
 * ⚠️ 真机录音/播放切换的「1 秒打断延迟」本层不承诺，须真机实测（需求书 §7.2）。
 */
const api = require('../../utils/api.js');
const app = getApp();

// 归类弹层：5 秒无反应 → 浮大字按钮（接口定义 §二.4 fallback_buttons_after_ms）
const CLASSIFY_FALLBACK_MS = 5000;

Page({
  data: {
    uiMode: 'standard',     // 'standard' | 'large'
    loading: true,
    error: '',              // 中文人话，可直接给老人看
    ownerId: '',
    viewerId: '',

    question: null,         // {kind, anchor_type?, anchor_label?, text, follow_up?, audio_hint?}
    state: '',              // asking | resumed
    waitMs: 0,              // AI 主动让路：问完留的等待
    speaking: false,        // TTS 正在播
    listening: false,       // 正在收声
    lastAnswer: '',         // 上一句老人答的（提交 next 用）

    // ★打断链路：当前正在问的句子（供 barge_in 后回填 interrupted_question）
    currentQuestionText: '',
    interrupted: false,
    interruptCount: 0,
    bargeTip: '',           // 「您说，我听着」提示语

    // ★ 收尾确认（P0-2 · D 组 recap_confirm，§7.6 C 方案）
    qaPairs: [],            // [{"q":..,"a":..}] 本轮一问一答，收尾时交给后端理顺
    storyId: '',            // 收尾写回哪条故事（空 = 后端按 qa 新建）
    recapAsk: false,        // 收尾弹层（「我这样记，对不对？」）
    recapText: '',          // 后端给的复述稿（老人只读）
    recapBusy: false,
    finished: false,        // 采访已收尾
    recapRetry: 0,          // 复述被否的次数（透传给后端 retry_used）

    // 归类弹层
    classifyAsk: false,     // ask_classify 返回是否要问
    classifyQ: null,        // {text, buttons[], fallback_buttons_after_ms, safe_default}
    classifyButtonsShown: false, // 5 秒后浮出大字按钮
    classifyStoryId: '',
    mutedAsk: false,

    submitting: false
  },

  onLoad() {
    const g = app.globalData;
    const ownerId = (this.options && this.options.owner_id) ? this.options.owner_id : (g.userId || '');
    const viewerId = g.userId || ownerId;
    this.setData({ uiMode: app.getUiMode(), ownerId: ownerId, viewerId: viewerId });
    if (!ownerId) {
      this.setData({ loading: false, error: '' });  // 未登录 → 空态，不报错
      return;
    }
    this.startInterview();
  },

  onShow() {
    this.setData({ uiMode: app.getUiMode() });
  },

  onUnload() {
    this.stopTts();      // 离页必停播，别让声音跟着走
    this.clearClassifyTimer();
  },

  // ============ 采访主流程 ============

  /** 开始采访：AI 主动出第一问（优先问人生锚点） */
  startInterview() {
    this.setData({ loading: true, error: '' });
    return api.interviewStart(this.data.ownerId, this.data.viewerId)
      .then((data) => {
        this.setData({ loading: false });
        this.showQuestion(data);
      })
      .catch((err) => {
        this.setData({ loading: false, error: (err && err.message) || '现在没能开始，请稍后再试' });
      });
  },

  /** 展示一问：存下当前问句 → TTS 播 → 播完等 wait_ms → 收声（铁律 3） */
  showQuestion(data) {
    const q = (data && data.question) || null;
    const text = (q && q.text) || '';
    this.setData({
      question: q,
      state: (data && data.state) || '',
      waitMs: (data && data.wait_ms) || 0,
      currentQuestionText: text,     // ★存下来，供打断后回填
      interrupted: false,
      bargeTip: ''
    });
    this.speak(text, () => {
      // 播完留 wait_ms 再开始听（AI 主动让路，别连珠炮）
      const ms = this.data.waitMs || 0;
      setTimeout(() => { this.startListening(); }, ms);
    });
  },

  /** TTS 播放问句（用系统语音合成；真机可换后端音频，audio_hint 提示「只用听」） */
  speak(text, done) {
    if (!text) { if (done) done(); return; }
    this.setData({ speaking: true });
    // 用微信同声传译插件不是必须；这里用 InnerAudioContext 播后端音频留位，
    // 本机联调无音频源 → 退化为「读一会儿」的占位时长，不假装有 1 秒打断能力。
    const fakeMs = Math.min(6000, 60 * text.length + 800);
    this._ttsTimer = setTimeout(() => {
      this.setData({ speaking: false });
      if (done) done();
    }, fakeMs);
    this._readingText = text;
  },

  /** 停 TTS（barge_in → stop_tts=true 时立刻调；真机这里应 stop InnerAudioContext） */
  stopTts() {
    if (this._ttsTimer) { clearTimeout(this._ttsTimer); this._ttsTimer = null; }
    if (this.data.speaking) this.setData({ speaking: false });
  },

  /** 开始收声（真机接录音；本机联调用「说完了」按钮模拟一句回答） */
  startListening() {
    this.setData({ listening: true });
  },

  /** 老人出声 → 调 barge_in（铁律 1/2）：停 TTS + 存下当前问句 + 计入打断次数 */
  onBargeIn(e) {
    const energy = (e && e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.energy);
    const body = { ownerId: this.data.ownerId, energyDb: energy === undefined ? -10 : Number(energy) };
    return api.interviewBargeIn(body.ownerId, body.energyDb, '')
      .then((data) => {
        const d = data || {};
        if (d.stop_tts) this.stopTts();     // 停 TTS（真机此处压到 1 秒内，须真机测）
        this.setData({
          listening: false,
          interrupted: true,                // ★记住刚才问被打断了
          interruptCount: this.data.interruptCount + 1,
          bargeTip: '您说，我听着'
        });
      })
      .catch(() => { /* 打断失败也别卡住老人：本地先停播 */ this.stopTts(); });
  },

  /** 老人说完/点了「说完了」→ 调 next（打断则回填 interrupted_question，先接回再接别的） */
  onFinishAnswer() {
    const answer = this.data.lastAnswer || '';
    const interruptedQ = this.data.interrupted ? this.data.currentQuestionText : '';
    const q = this.data.currentQuestionText || '';
    this.setData({ listening: false, submitting: true });
    return api.interviewNext(this.data.ownerId, this.data.viewerId, answer,
                             interruptedQ, this.data.interruptCount)
      .then((data) => {
        // ★ 把这一组问答存下来，收尾时一并交给 recap_confirm 理顺成一段话
        const pairs = this.data.qaPairs.slice();
        if (q || answer) pairs.push({ q: q, a: answer });
        this.setData({ submitting: false, lastAnswer: '', interruptCount: 0, qaPairs: pairs });
        this.showQuestion(data);            // state=resumed 时会原样接回刚才那问
      })
      .catch((err) => {
        this.setData({ submitting: false, error: (err && err.message) || '刚才没接上，请再说一次' });
      });
  },

  // ============ 收尾确认（P0-2 · D 组：/interview/recap_confirm） ============
  //  §7.6 C 方案：复述 + 归属一次问完；含糊/超时 → 安全默认，绝不卡住老人。
  //  前端只负责「把 qa 交给后端、把后端给的复述稿读给老人、把答话回传」，不自己写复述、不自己判归属。

  /** 点「聊完了」→ 第一次调用只出复述稿（answer_key 空），让老人确认 */
  onFinishInterview() {
    if (this.data.recapBusy) return;
    this.stopTts();
    if (!this.data.qaPairs.length) {
      wx.showToast({ title: '还没聊呢，先说两句', icon: 'none' });
      return;
    }
    this.setData({ recapBusy: true, error: '' });
    api.interviewRecapConfirm({
      ownerId: this.data.ownerId,
      viewerId: this.data.viewerId,
      storyId: this.data.storyId,
      qaPairs: this.data.qaPairs
    }).then((d) => {
      const dd = d || {};
      // 屏幕显示：复述稿原文（polished_text）；老人口头听：recap_speech（复述+归属问句）
      const text = dd.polished_text
        || ((dd.recap_points || []).length ? (dd.recap_points || []).join('。') + '。' : '');
      this.setData({
        recapBusy: false,
        recapAsk: true,
        recapText: text,
        storyId: dd.story_id || this.data.storyId
      });
      if (dd.recap_speech) this.speak(dd.recap_speech);
    }).catch((err) => {
      this.setData({ recapBusy: false, error: (err && err.message) || '刚才没整理好，请稍后再试' });
    });
  },

  /** 老人说「对」→ accept + apply=true，写回故事 */
  onRecapAccept() {
    this.submitRecap({ answerKey: 'accept', apply: true });
  },

  /**
   * 老人说「不对」→ reject（不落库）。
   * 后端返回 decision=rejected / need_revise=true → 收回复述，让他重说，
   * 不写半成品、不硬记（✅ §7.6「宁可重来，不留错账」）。
   */
  onRecapReject() {
    const retry = (this.data.recapRetry || 0) + 1;
    this.setData({ recapRetry: retry });
    this.submitRecap({ answerKey: 'reject', retryUsed: retry, apply: false });
  },

  /** 老人含糊/又补了内容 → 语音原话回传，后端并进自述体并判定 */
  onRecapSpoken(e) {
    const text = ((e.detail && e.detail.value) || '').trim();
    if (!text) return;
    this.submitRecap({ answerText: text, apply: false });
  },

  /** 超时不答 → timeout（后端安全默认接受，绝不卡住老人） */
  onRecapTimeout() {
    this.submitRecap({ answerKey: 'timeout', apply: false });
  },

  /**
   * 统一提交复述确认。
   * 后端判定字段：decision = accepted / rejected（空 = 还在复述阶段）
   * apply=true 时才写回；写回失败后端给 applied=false + apply_error，不回滚成假成功。
   */
  submitRecap(o) {
    const opt = o || {};
    if (this.data.recapBusy) return;
    this.setData({ recapBusy: true });
    api.interviewRecapConfirm({
      ownerId: this.data.ownerId,
      viewerId: this.data.viewerId,
      storyId: this.data.storyId,
      qaPairs: this.data.qaPairs,
      polishedText: this.data.recapText,
      answerKey: opt.answerKey || '',
      answerText: opt.answerText || '',
      retryUsed: opt.retryUsed || 0,
      apply: !!opt.apply
    }).then((d) => {
      const dd = d || {};
      const decision = (dd.decision || '').trim();
      const text = dd.polished_text || this.data.recapText;

      // ① 老人说要改 → 收回复述稿，回到说话状态，重说一遍（不留半成品）
      if (decision === 'rejected') {
        this.setData({ recapBusy: false, recapAsk: false, recapText: '', storyId: dd.story_id || this.data.storyId });
        wx.showToast({ title: '好，您再说一遍', icon: 'none' });
        this.startListening();
        return;
      }

      // ② 还在复述阶段（没听懂/重报）→ 后端给了新 script，继续读
      if (!decision) {
        const say = dd.recap_speech || text;
        this.setData({
          recapBusy: false,
          recapRetry: dd.retry_used || this.data.recapRetry,
          recapText: dd.polished_text || this.data.recapText
        });
        if (say) this.speak(say);
        return;
      }

      // ③ accepted → 收尾
      this.setData({ recapBusy: false, recapAsk: false, finished: true });
      if (dd.applied === false) {
        // 话听完了但没写进故事：诚实告知，不假装成功
        wx.showToast({ title: dd.apply_error || '话记好了，但没存进故事', icon: 'none' });
      } else {
        wx.showToast({ title: '记下来了', icon: 'none' });
      }
    }).catch((err) => {
      this.setData({ recapBusy: false });
      wx.showToast({ title: (err && err.message) || '没记上，稍后再试', icon: 'none' });
    });
  },

  /** 收尾后回首页 */
  onBackHome() {
    wx.switchTab({
      url: '/pages/index/index',
      fail: () => wx.reLaunch({ url: '/pages/index/index' })
    });
  },

  /** 模拟输入一句回答（本机联调；真机由语音识别填入） */
  onAnswerInput(e) {
    this.setData({ lastAnswer: (e.detail && e.detail.value) || '' });
  },

  // ============ 归类弹层（自述页保存后 → 要不要弹） ============

  /** 触发归类问：ask_classify（含频率保护，别烦老人） */
  onAskClassify(e) {
    const sid = (e && e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.storyId) || this.data.classifyStoryId || '';
    return api.interviewAskClassify(this.data.ownerId, this.data.viewerId, sid)
      .then((data) => {
        const d = data || {};
        if (!d.ask) {
          // single_in_year / muted → 不问，静默回列表
          this.setData({ classifyAsk: false, mutedAsk: d.reason === 'muted' ? true : this.data.mutedAsk });
          return;
        }
        this.setData({
          classifyAsk: true,
          classifyQ: d.question || null,
          classifyStoryId: sid,
          classifyButtonsShown: false
        });
        // ★5 秒无反应 → 浮大字按钮 + 安全默认（后端 fallback_buttons_after_ms，缺省 5000）
        const fb = (d.question && d.question.fallback_buttons_after_ms) || CLASSIFY_FALLBACK_MS;
        this._classifyTimer = setTimeout(() => {
          this.setData({ classifyButtonsShown: true });
        }, fb);
      })
      .catch(() => { this.setData({ classifyAsk: false }); });
  },

  clearClassifyTimer() {
    if (this._classifyTimer) { clearTimeout(this._classifyTimer); this._classifyTimer = null; }
  },

  /** 老人点归类按钮 → classify_answer（new / existing） */
  onTapClassifyButton(e) {
    const key = e.currentTarget.dataset.key;
    this.submitClassify({ answerKey: key });
  },

  /** 老人语音回答（真机）；含糊/超时一律由后端安全兜底为「新建」 */
  onClassifySpoken(e) {
    const text = (e.detail && e.detail.value) || '';
    this.submitClassify({ answerText: text });
  },

  /** 5 秒无反应 → 提交 timeout，后端默认新建（铁律 4，绝不卡老人） */
  onClassifyTimeout() {
    this.submitClassify({ answerKey: 'timeout' });
  },

  submitClassify(o) {
    const opts = o || {};
    this.clearClassifyTimer();
    return api.interviewClassifyAnswer({
      ownerId: this.data.ownerId, viewerId: this.data.viewerId,
      newStoryId: this.data.classifyStoryId,
      answerText: opts.answerText || '', answerKey: opts.answerKey || '', retryUsed: 0
    })
      .then((data) => {
        const d = data || {};
        if (d.retry) {
          // 「没听清」→ 重问（最多 2 次），不换题
          this.setData({ classifyButtonsShown: true });
          wx.showToast({ title: '没听清，您再说一次', icon: 'none' });
          return;
        }
        // decision new / existing（含糊/超时都已安全默认 new）
        this.setData({ classifyAsk: false, classifyQ: null, classifyButtonsShown: false });
        if (d.decision === 'existing') {
          // need_pick_story → 前端再让老人选哪一件（此处回时间轴让他选，不硬编）
          wx.showToast({ title: '好，您说的是上面某一件', icon: 'none' });
        }
      })
      .catch(() => { this.setData({ classifyAsk: false, classifyButtonsShown: false }); });
  },

  onCloseClassify() {
    this.clearClassifyTimer();
    this.setData({ classifyAsk: false, classifyQ: null, classifyButtonsShown: false });
  },

  /** 弹层遮罩吞掉点击（防止点穿到底下的按钮） */
  noop() {},

  // ============ 「别问了」开关 ============

  onMuteAsk() {
    return api.interviewPref(this.data.ownerId, { mutedAsk: true })
      .then(() => {
        this.setData({ mutedAsk: true, classifyAsk: false });
        wx.showToast({ title: '好，以后不问了', icon: 'none' });
      })
      .catch(() => { /* 静默 */ });
  },

  onTapBack() {
    wx.navigateBack({ fail: () => wx.redirectTo({ url: '/pages/index/index' }) });
  }
});
