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
    barging: false,         // ★ 底部圆圈按住中（按住=打断 AI，松手=AI 接着问）

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

    // ★11-06 真录音（按住说话）：老人松手 → 上传 → 转文字 → 上屏 → 自动接下一问
    recording: false,
    recSec: 0,
    answerBusy: false,      // 上传/转写中
    answerStatus: '',       // 给老人看的进度话（正在听/正在转字）
    typeAnswer: false,      // 兜底：设备录不了音时才露出打字入口

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
    // ★ 链③ 补传：录音页「说」完的那句落在 storage 的 last_answer，
    //   采访页每次回到前台取一次，取到就清，避免同一句被反复当回答提交。
    let said = '';
    try { said = wx.getStorageSync('last_answer') || ''; } catch (e) {}
    if (said) {
      try { wx.removeStorageSync('last_answer'); } catch (e) {}
      this.setData({ lastAnswer: said });
    }
  },

  onUnload() {
    this.stopTts();      // 离页必停播，别让声音跟着走
    this.clearClassifyTimer();
    // ★11-06：离页别把录音留在后台（否则下次进页面麦克风是占着的）
    clearInterval(this._secTimer);
    this._secTimer = null;
    if (this.data.recording) {
      this._recDiscard = true;
      const rm = wx.getRecorderManager && wx.getRecorderManager();
      if (rm) rm.stop();
    }
  },

  // ============ 采访主流程 ============

  /** 开始采访：AI 主动出第一问（优先问人生锚点） */
  startInterview() {
    this.setData({ loading: true, error: '' });
    // ★11-06：先把"筐"建好（story_id）。不建的话老人每句录音都没处挂，
    //   收尾复述也写不回任何一条故事 → 录音=白录。
    return this.ensureStory()
      .then(() => api.interviewStart(this.data.ownerId, this.data.viewerId))
      .then((data) => {
        this.setData({ loading: false });
        this.showQuestion(data);
      })
      .catch((err) => {
        this.setData({ loading: false, error: (err && err.message) || '现在没能开始，请稍后再试' });
      });
  },

  /**
   * ★11-06 保证有一段"故事"可挂：采访成品、每句录音都挂在它上面。
   *   已有 storyId 直接用；没有就建一条（标题留空，收尾复述时后端会写自述体）。
   *   建不出来也**不挡住采访**——宁可暂时录音不落库，也不能让老人对着屏幕干等。
   */
  ensureStory() {
    if (this.data.storyId) return Promise.resolve(this.data.storyId);
    if (this._storyPending) return this._storyPending;
    const uid = this.data.ownerId || this.data.viewerId || '';
    if (!uid) return Promise.resolve('');
    this._storyPending = api.storyCreate({ ownerId: uid, actorId: this.data.viewerId || uid, title: '' })
      .then((d) => {
        const sid = (d && (d.story_id || (d.story && d.story.story_id))) || '';
        if (sid) this.setData({ storyId: sid });
        this._storyPending = null;
        return sid;
      })
      .catch(() => { this._storyPending = null; return ''; });
    return this._storyPending;
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

  /**
   * TTS 播放问句：真出声（11-04 改）
   *   旧版是「等一会儿假装在读」的占位计时器 —— 老人实际什么也听不到，打断也没意义。
   *   现在：向 /api/echoes/tts/speak 要一段 mp3（腾讯云音色），InnerAudioContext 真播；
   *   合成/播放失败一律退化为原占位时长，**不卡住流程**（铁律：绝不卡住老人）。
   */
  speak(text, done) {
    if (!text) { if (done) done(); return; }
    this.setData({ speaking: true });
    this._readingText = text;
    this._ttsStopped = false;      // ★每句重置：否则打断过一次就永久哑了
    // 兜底时长：合成回不来时按字数估，保证一定会走到 done
    const fakeMs = Math.min(6000, 60 * text.length + 800);
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      if (this._ttsFallbackTimer) { clearTimeout(this._ttsFallbackTimer); this._ttsFallbackTimer = null; }
      this.setData({ speaking: false });
      if (done) done();
    };
    this._ttsFallbackTimer = setTimeout(finish, fakeMs + 4000);

    api.ttsSpeak(this.data.ownerId, text, 'interview_host', this.data.storyId)
      .then((d) => {
        if (this._ttsStopped) return;                 // 老人已经打断，别又响起来
        const url = api.absUrl((d && d.media_url) || '');
        if (!url) return finish();                    // 没拿到地址 → 只显字，不假装有声音
        this.stopAudioOnly();
        const ctx = wx.createInnerAudioContext();
        this._ttsCtx = ctx;
        ctx.src = url;
        ctx.onEnded(() => finish());
        ctx.onError(() => { this.stopAudioOnly(); finish(); });
        ctx.play();
      })
      .catch(() => finish());                          // TTS 不可用 → 退化，不报错弹窗
  },

  /** 停 TTS（barge_in → stop_tts=true 时立刻调；真机须 1 秒内停） */
  stopTts() {
    this._ttsStopped = true;
    if (this._ttsFallbackTimer) { clearTimeout(this._ttsFallbackTimer); this._ttsFallbackTimer = null; }
    this.stopAudioOnly();
    if (this.data.speaking) this.setData({ speaking: false });
  },

  /** 只停音频上下文（不置 _ttsStopped，供换语句时复用） */
  stopAudioOnly() {
    const ctx = this._ttsCtx;
    this._ttsCtx = null;
    if (ctx) { try { ctx.stop(); ctx.destroy(); } catch (e) { /* 已销毁 */ } }
  },

  /** 开始收声（★11-06：真录音，老人按住说话；录不了音的设备才退化成打字） */
  startListening() {
    this.setData({ listening: true, answerBusy: false, answerStatus: '', lastAnswer: '' });
  },

  // ============ ★11-06 按住说话（真录音 → 转文字 → 自动接话） ============

  /** 按住：开录。录音期间把 TTS 停掉（别让自己的声音录进去） */
  onHoldStart() {
    if (this.data.answerBusy) return;
    const rm = wx.getRecorderManager && wx.getRecorderManager();
    if (!rm) {
      this.setData({ typeAnswer: true });
      wx.showToast({ title: '这台设备录不了音，用打字说', icon: 'none' });
      return;
    }
    this.stopTts();
    this._recStart = Date.now();
    this._recStopped = false;
    this._recDiscard = false;
    this.setData({ recording: true, recSec: 0, error: '', bargeTip: '' });
    if (wx.vibrateShort) wx.vibrateShort();
    // 秒数跳动：老人得看见"它在听"
    clearInterval(this._secTimer);
    this._secTimer = setInterval(() => {
      const s = Math.floor((Date.now() - this._recStart) / 1000);
      this.setData({ recSec: s });
    }, 500);

    this._onStop = (res) => this._handleRecStop(res);
    rm.onStop(this._onStop);
    rm.start({
      duration: 5 * 60 * 1000,        // 一次回答最长 5 分钟，够了
      sampleRate: 16000, numberOfChannels: 1,
      encodeBitRate: 48000, format: 'mp3'
    });
  },

  /** 松开：停录（真正处理在 onStop 回调） */
  onHoldEnd() {
    if (!this.data.recording) return;
    this.setData({ recording: false });
    clearInterval(this._secTimer);
    this._secTimer = null;
    // 误碰（<0.6 秒）→ 丢掉，不算一次回答
    if (this._recStart && Date.now() - this._recStart < 600) {
      this._recDiscard = true;
      this._recStart = 0;
      const rm = wx.getRecorderManager && wx.getRecorderManager();
      if (rm) rm.stop();
      wx.showToast({ title: '按住多说一会儿', icon: 'none' });
      return;
    }
    const rm = wx.getRecorderManager && wx.getRecorderManager();
    if (rm) rm.stop();
  },

  /** 触摸被系统打断（来电等）→ 当作松开处理，别让录音卡在"正在录" */
  onHoldCancel() {
    if (!this.data.recording) return;
    this._recDiscard = true;
    this.onHoldEnd();
  },

  /** 录完 → 上传 + 登记（后端当场转写）→ 字上屏 → 自动接下一问 */
  _handleRecStop(res) {
    if (this._recDiscard) { this._recDiscard = false; return; }
    if (this._recStopped) return;       // 一次按住只处理一次
    this._recStopped = true;

    const path = (res && res.tempFilePath) || '';
    const size = (res && res.fileSize) || 0;
    const duration = (res && res.duration ? res.duration / 1000 : 0) || 0;
    if (!path) {
      this.setData({ answerBusy: false });
      wx.showToast({ title: '没录上，再按一次', icon: 'none' });
      return;
    }

    this.setData({ answerBusy: true, answerStatus: '正在听…' });
    // ★11-06 安卓坑：wx.uploadFile 的临时文件名经常没后缀（tmp_xxx），
    //   所以文件名统一按录制格式给，别用路径里那个。
    const name = 'voice.mp3';
    const mime = 'audio/mpeg';

    this._uploadAnswer(path, name, size, mime, duration)
      .then((d) => {
        const said = ((d && d.transcript) || '').trim();
        if (!said) {
          // 转不出字：原声已存，请老人再说一遍（不弹红叉，不骂人）
          this.setData({ answerBusy: false, answerStatus: '' });
          wx.showToast({ title: '这句没听清，再说一遍', icon: 'none' });
          this.startListening();
          return;
        }
        // 字上屏 → 立刻接下一问
        this.setData({ lastAnswer: said, answerStatus: '', answerBusy: false });
        wx.showToast({ title: '听到了', icon: 'none' });
        this.onFinishAnswer();
      })
      .catch((e) => {
        this.setData({ answerBusy: false, answerStatus: '' });
        const msg = (e && e.message) || '';
        if (e && e.code === 'upload_not_configured') {
          this.setData({ typeAnswer: true });
          wx.showToast({ title: '录音通道没开，先用打字', icon: 'none' });
          return;
        }
        // 网络等失败 → 让老人再说一次，不丢页面
        wx.showToast({ title: msg || '没传上，再按一次', icon: 'none' });
      });
  },

  /** 上传 + 登记两步（与采集页同一条链：upload_url → wx.uploadFile → storage/confirm） */
  _uploadAnswer(filePath, fileName, fileSize, mime, durationSec) {
    const actorId = this.data.viewerId || this.data.ownerId || '';
    let key = '';
    return api.uploadUrl(fileName, fileSize, mime, actorId, 'audio')
      .then((up) => {
        key = (up && up.key) || '';
        const url = api.absUrl((up && up.upload_url) || '');
        if (!url) return Promise.reject(new Error('上传通道还没开'));
        return new Promise((resolve, reject) => {
          wx.uploadFile({
            url: url, filePath: filePath, name: (up && up.form_field) || 'file',
            success: (r) => {
              let body = r.data;
              try { body = typeof body === 'string' ? JSON.parse(body) : body; } catch (err) {}
              if (r.statusCode && (r.statusCode < 200 || r.statusCode >= 300)) {
                reject(new Error((body && body.error) || '上传失败，再按一次')); return;
              }
              if (body && body.ok === false) {
                const e = new Error(body.error || '上传失败，再按一次');
                e.code = body.code; reject(e); return;
              }
              resolve();
            },
            fail: () => reject(new Error('网络不太好，再按一次'))
          });
        });
      })
      .then(() => api.storageConfirm({
        actorId: actorId,
        key: key,
        kind: 'audio',
        storyId: this.data.storyId,
        ownerId: this.data.ownerId || actorId,
        duration: durationSec || 0,
        fileName: fileName, fileSize: fileSize, mime: mime,
        visibility: 'private'
      }))
      .then((d) => {
        const out = Object.assign({}, d || {});
        if (!out.transcript) out.transcript = '';
        return out;
      });
  },

  /** 兜底：切打字/切回来 */
  onToggleTypeAnswer() {
    this.setData({ typeAnswer: !this.data.typeAnswer });
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

  /**
   * ★ 底部圆圈：按住 = 打断 AI（把 AI 的嘴闭上，让老人能说）
   *              松手 = AI 接着问
   * 老人只需要记一件事：「想说就按住它」。
   *
   * ⚠️ 复用页面已有的真录音链路 onHoldStart/onHoldEnd，不另起一套（否则录音状态打架）。
   *    顺序：先打断 AI（闭麦）→ 再开录（让老人说）。
   */
  onCircleStart() {
    this.setData({ barging: true });
    this.stopTts();                       // 立刻本地停播，不等接口
    const p = this.onBargeIn({ currentTarget: { dataset: { energy: -10 } } });
    this.onHoldStart();                   // 开录（内部自己管 recording/秒表/上传）
    return p;
  },

  /** 松手 → 停录（内容由 _handleRecStop 上传转写并接下一问），AI 接着问 */
  onCircleEnd() {
    if (!this.data.barging) return;
    this.setData({ barging: false });
    return this.onHoldEnd();
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

  /**
   * ★11-06 收声区不再靠打字：老人按住说话 → 松手转文字 → 自动接下一问。
   *   原来的 onAnswerInput / onFinishAnswer 保留：前者给"录不了音的兜底打字"用，
   *   后者是录音转出文字后的统一出口（也兼容打字点「说完了」）。
   */
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
