/**
 * utils/api.js — 统一请求工具（v2.4 前端）
 *
 * 信封口径（小鲸鱼《接口定义_待认领_v1_20260927》第四节 + 采集接口纠偏单）：
 *   {"ok": true,  "data": {...}}
 *   {"ok": false, "error": "中文人话", "code": "bad_request|unauthorized|forbidden|not_found|..."}
 * 铁律：**前端只认 ok 一个字段**；失败必带中文 error，可直接弹给老人看；
 *       code 只用于程序分支，**不显示给用户**。
 */
// ⚠️ 不能在模块顶层调 getApp()：app.js 里 require('./utils/api.js') 时 App() 还没执行，
//    此时 getApp() 返回 undefined，const app 被永久钉成 undefined → 所有请求 url 变成 '/api/...' 相对路径
//    → wx.request 直接 fail('网络不太好，请稍后再试')，且 7ms 内就返回（请求根本没发出）。
//    改为每次请求时现取。
function getApp_() { return getApp(); }

/** 简单内存缓存：登录后拿到的「有 N 篇故事提到了你」 */
let _mentionedCache = { count: 0, stories: [] };
/** 简单内存缓存：登录总入口返回的 user_id */
let _session = { userId: '', phone: '' };

/** 统一请求：只看 ok，error 直显；code 留给调用方分支 */
function request(path, method, data) {
  return new Promise((resolve, reject) => {
    const base = (getApp_() && getApp_().globalData && getApp_().globalData.apiBase) || '';
    wx.request({
      url: base + path,
      method: method || 'GET',
      data: data || {},
      success: (res) => {
        const body = (res && res.data) || {};
        if (body.ok) return resolve(body.data || {});
        const err = new Error(body.error || '操作失败，请重试');
        err.code = body.code;              // 仅供调用方分支，不外显
        reject(err);
      },
      fail: () => reject(new Error('网络不太好，请稍后再试'))
    });
  });
}

/** 便捷方法 */
function _qs(params) {
  let qs = '';
  if (params) {
    const parts = [];
    Object.keys(params).forEach((k) => {
      if (params[k] !== undefined && params[k] !== null && params[k] !== '') {
        parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(params[k]));
      }
    });
    if (parts.length) qs = '?' + parts.join('&');
  }
  return qs;
}

/** 拼完整 URL（给 wx.downloadFile / 需要拿到地址的接口用） */
function buildUrl(path, params) {
  const base = (getApp_() && getApp_().globalData && getApp_().globalData.apiBase) || '';
  return base + path + _qs(params);
}

function get(path, params) {
  return request(path + _qs(params), 'GET');
}
function post(path, data) { return request(path, 'POST', data); }

// ============ 待认领/认领 线（小鲸鱼 09-27 接口 v1，形状已冻结） ============
const CLAIM = {
  REGISTER: '/api/echoes/claim/register',
  LOGIN: '/api/echoes/claim/login',
  MENTIONED: '/api/echoes/claim/mentioned',
  SEARCH: '/api/echoes/claim/search',
  CONFIRM: '/api/echoes/claim/confirm',
  REJECT: '/api/echoes/claim/reject',
  PENDING: '/api/echoes/claim/pending'
};

/**
 * 登录总入口（前端最常用）
 * @param {string} userId
 * @param {string} phone  已归一化或原始皆可，归一化在后端
 * @returns {Promise<{owners,claimed_claims,claimed_members,mentioned_count}>}
 */
function claimLogin(userId, phone) {
  return post(CLAIM.LOGIN, { user_id: userId, phone: phone }).then((data) => {
    _session.userId = userId;
    _session.phone = phone || '';
    const count = Number(data.mentioned_count || 0);
    _mentionedCache = { count: count, stories: [] };
    return data;
  });
}

/** 写故事时把人登记成待认领（手机号优先；对方没账号也能先写进去） */
function claimRegister(ownerId, org) {
  const o = org || {};
  return post(CLAIM.REGISTER, {
    owner_id: ownerId,
    phone: o.phone || '',
    display_name: o.displayName || o.display_name || '',
    story_id: o.storyId || o.story_id || ''
  });
}

/**
 * 按名字搜索候选。返回的只是**候选**，必须等写故事的人确认才生效（防重名冒领）。
 * @returns {Promise<{count,hint,candidates}>}
 */
function claimSearch(displayName) {
  return get(CLAIM.SEARCH, { display_name: displayName });
}

/** 「有 N 篇故事提到了你」+ 列表 */
function claimMentioned(userId) {
  return get(CLAIM.MENTIONED, { user_id: userId }).then((data) => {
    _mentionedCache = {
      count: Number(data.count || 0),
      stories: data.stories || []
    };
    return data;
  });
}

/** 登记人确认 / 否认（只有 owner_id 本人能确认，否则后端返回 forbidden） */
function claimConfirm(claimId, ownerId, userId) {
  return post(CLAIM.CONFIRM, { claim_id: claimId, owner_id: ownerId, user_id: userId });
}
function claimReject(claimId, ownerId) {
  return post(CLAIM.REJECT, { claim_id: claimId, owner_id: ownerId });
}
/** 我还有哪些人没被认领 */
function claimPending(ownerId) {
  return get(CLAIM.PENDING, { owner_id: ownerId });
}

function getMentionedCache() { return _mentionedCache; }
function getSession() { return _session; }
function setSession(userId, phone) {
  _session = { userId: userId || '', phone: phone || '' };
}

// ============ 登录态 线（小鲸鱼 09-29 接口 v1，形状已冻结）============
// 铁律（小鲸鱼《接口定义_登录态v1_20260929》）：user_id = 微信 openid，
//   后续采集 6 类 + 认领 7 个接口**统一用它**，前端**不许再写死假 id**。
//   - profile.ui_mode 决定渲染标准版/大字版（User 级持久，前端不自己存业务态）
//   - 联调传 force_stub:true（本机无 appid/secret）；session_from 会写明走 stub 还是 wechat，
//     **不静默假装成功** —— 生产不传该字段。
const LOGIN = {
  LOGIN: '/api/echoes/login',
  PROFILE: '/api/echoes/login/profile',
  UI_MODE: '/api/echoes/login/ui_mode'
};

/**
 * 登录（进小程序第一件事）：wx.login() code → user_id，一次拿齐
 *   「我是谁 + 我有哪些书 + 有几篇提到了我」
 * @param {object} opts {code, phone?, nickName?, avatarUrl?, forceStub?}
 * @returns {Promise<{user_id,is_new_user,profile,owners,count_stories,mentioned_count,session_from}>}
 */
function login(opts) {
  const o = opts || {};
  const body = { code: o.code || '' };
  if (o.nickName) body.nick_name = o.nickName;
  if (o.avatarUrl) body.avatar_url = o.avatarUrl;
  if (o.phone) body.phone = o.phone;
  if (o.forceStub) body.force_stub = true;      // 联调专用；生产不传
  return post(LOGIN.LOGIN, body).then((data) => {
    _session.userId = data.user_id || '';
    _session.phone = o.phone || '';
    _mentionedCache = {
      count: Number(data.count_stories || data.mentioned_count || 0),
      stories: []
    };
    return data;
  });
}

/** wx.login() 包成 Promise（拿临时 code） */
function wxLoginCode() {
  return new Promise((resolve, reject) => {
    wx.login({
      success: (res) => (res && res.code) ? resolve(res.code) : reject(new Error('没拿到登录凭证，请重试')),
      fail: () => reject(new Error('微信登录没成功，请重试'))
    });
  });
}

/** 读资料（切页/冷启动拉状态，含 ui_mode） */
function loginProfile(userId) {
  return get(LOGIN.PROFILE, { user_id: userId });
}

/**
 * 双界面切换（v2.4 第9条）：ui_mode 是 User 级持久设置，切一次下次进来 profile 就是 large。
 * 后端兼容 senior / big / 大字版 等别名，统一归一化。
 */
function loginSetUiMode(userId, uiMode) {
  return post(LOGIN.UI_MODE, { user_id: userId, ui_mode: uiMode });
}

// ============ 采集 线（小鲸鱼 09-26 文字/图片 + 09-28 v1.1 语音/原声/视频）============
// 信封完全同形（{ok,data,error,code} / 成功可带 notice），一套解析复用 request()。
// 铁律（v2.4 §六）：
//   - 语音 keep_original_voice 恒 true → 前端**不许传**该字段
//   - 转写失败 ≠ 采集失败 → transcribe_failed 用灰/黄提示，**不弹红叉、不提示重录**
//   - audio_path 是本机路径 → 前端**不许传**
const CLIP = {
  TEXT: '/api/echoes/clip/text',
  PHOTO: '/api/echoes/clip/photo',
  AUDIO: '/api/echoes/clip/audio',
  ORIGINAL: '/api/echoes/clip/original',
  VIDEO: '/api/echoes/clip/video',
  TRANSCRIBE: '/api/echoes/clip/transcribe',
  LIST: '/api/echoes/clip/list',
  UPLOAD_URL: '/api/echoes/upload/url'
};

/** 挂语音：保留原声 + 尽量转文字（不传 keep_original_voice / audio_path） */
function clipAudio(storyId, actorId, media) {
  const m = media || {};
  return post(CLIP.AUDIO, {
    story_id: storyId, actor_id: actorId, media_url: m.mediaUrl || '',
    file_name: m.fileName || '', file_size: m.fileSize || 0,
    mime: m.mime || '', duration: m.duration || 0, caption: m.caption || '',
    do_transcribe: m.doTranscribe === false ? false : true
  });
}
/** 挂原声：刻意不转写（保方言/语气） */
function clipOriginal(storyId, actorId, media) {
  const m = media || {};
  return post(CLIP.ORIGINAL, {
    story_id: storyId, actor_id: actorId, media_url: m.mediaUrl || '',
    file_name: m.fileName || '', file_size: m.fileSize || 0,
    mime: m.mime || '', duration: m.duration || 0, caption: m.caption || ''
  });
}
/** 挂视频 */
function clipVideo(storyId, actorId, media) {
  const m = media || {};
  return post(CLIP.VIDEO, {
    story_id: storyId, actor_id: actorId, media_url: m.mediaUrl || '',
    cover_url: m.coverUrl || '', file_name: m.fileName || '',
    file_size: m.fileSize || 0, duration: m.duration || 0,
    mime: m.mime || '', caption: m.caption || ''
  });
}
/** 给已有语音补转写（幂等；原声素材会返回 original_not_transcribable，属预期） */
function clipTranscribe(clipId, actorId) {
  return post(CLIP.TRANSCRIBE, { clip_id: clipId, actor_id: actorId });
}
/** 取素材筐（已按 sort_order 排好，直接渲染） */
/**
 * 这条故事下的素材列表。
 * owner_id 必须带：后端拿它做权限判定的根，缺了会判成「看不到」返回空。
 * viewer_id 缺省 = owner 自己。
 */
function clipList(storyId, viewerId, ownerId) {
  return get(CLIP.LIST, {
    story_id: storyId,
    viewer_id: viewerId || ownerId || '',
    owner_id: ownerId || viewerId || ''
  });
}
/** 取上传地址（10-24 改：真机传素材必须带 actor_id + kind，旧 /upload/url 缺 actor_id 会被后端拒） */
function uploadUrl(fileName, fileSize, mime, actorId, kind) {
  return post('/api/echoes/storage/upload_url', {
    actor_id: actorId || '', kind: kind || 'image',
    file_name: fileName, file_size: fileSize, mime: mime
  });
}

/**
 * 登记（10-24 新增）：字节传完后必须调 /storage/confirm，否则素材不算入库。
 * 返回 {clip_id, media_url, visibility, kind, key}
 */
function storageConfirm(opt) {
  const o = opt || {};
  return post('/api/echoes/storage/confirm', {
    actor_id: o.actorId || '', key: o.key, kind: o.kind || 'image',
    story_id: o.storyId || '', file_name: o.fileName || '',
    file_size: o.fileSize || 0, mime: o.mime || '',
    visibility: o.visibility || 'private', duration: o.duration || 0
  });
}

/** 把后端给的对象地址（/media/...）拼成可直接回显/播放的绝对地址 */
function absUrl(u) {
  const s = u || '';
  if (!s || /^https?:\/\//i.test(s) || /^wxfile:\/\//i.test(s)) return s;
  const base = (getApp_() && getApp_().globalData && getApp_().globalData.apiBase) || '';
  return base + (s.charAt(0) === '/' ? s : '/' + s);
}

// ============ 时间轴 线（小鲸鱼 10-06 接口 v1，形状已冻结）============
// 定义：docs/事卷/接口定义_时间轴v1_20261006.md（后端 backend/timeline_api.py，自测 33/33）
// 四条铁律（前端必须守，接口定义 §三）：
//   1) 排序只在后端 —— 拿 nodes 顺序渲染，前端不重排
//   2) 只显示 time_label —— 别把「1970年代（老人说的）」加工成「1975年3月」
//   3) 【时间待定】单列 —— 用 pending 渲到底部灰点，不塞进 nodes 排序
//   4) 改过的不许被覆盖 —— 覆盖判断在后端，前端只管提交 set_time
const TIMELINE = {
  GET: '/api/echoes/timeline',            // N1 节数组 + N2 待定区
  GROUPED: '/api/echoes/timeline/grouped',// 同义（兼容旧命名）
  PENDING: '/api/echoes/timeline/pending',// N2 只取待定区
  SET_TIME: '/api/echoes/timeline/set_time',   // N3 改时间
  AUTO_PLACE: '/api/echoes/timeline/auto_place'// 自动归位（保存即触发，可选）
};

/**
 * N1 取整本时间轴：nodes 已正序 + pending 待定区 + stats
 * @param {string} ownerId 书的主人（讲述人）
 * @param {string} [viewerId] 谁在看（默认＝ownerId）。家人看整本；故事成员只看命中那篇；外人空轴
 * @returns {Promise<{owner_id,nodes,pending,stats}>}
 */
function timelineGet(ownerId, viewerId) {
  return get(TIMELINE.GET, { owner_id: ownerId, viewer_id: viewerId });
}

/** N2 只取【时间待定】区 */
function timelinePending(ownerId, viewerId) {
  return get(TIMELINE.PENDING, { owner_id: ownerId, viewer_id: viewerId });
}

/**
 * N3 ★「改时间」：用户说/选一个时间，后端解析归位（改过后不再被自动覆盖）
 * @param {string} storyId 要改的那条
 * @param {string} actorId 谁改的（主人 或 已认领家人）
 * @param {string} newTimeText 用户原话，如「1980年5月」「七几年」
 * @param {object} [opts] {anchors, forceRaw}
 * @returns {Promise<{story_id,placed,time,node_hint,evidence,confidence}>}
 *   placed=false ⇒ 进「时间待定」，前端据此回读提示
 */
function timelineSetTime(storyId, actorId, newTimeText, opts) {
  const o = opts || {};
  const body = { story_id: storyId, actor_id: actorId, new_time_text: newTimeText };
  if (o.anchors) body.anchors = o.anchors;
  if (o.forceRaw) body.force_raw = o.forceRaw;
  return post(TIMELINE.SET_TIME, body);
}

/**
 * 自动归位（保存即触发，可选）。用户手改过的会自动 skipped=true，绝不覆盖。
 * @returns {Promise<{story_id,placed,skipped,reason,time}>}
 */
function timelineAutoPlace(storyId) {
  return post(TIMELINE.AUTO_PLACE + '?story_id=' + encodeURIComponent(storyId));
}

// ============ 采访引导 线（小鲸鱼 10-08 接口 v1，形状已冻结）============
// 定义：docs/事卷/接口定义_采访引导v1_20261008.md（后端 backend/interview_api.py，自测 37/37；
//       6 条路由已由小龙虾本机 uvicorn 实测 30/30）
// 四条铁律（前端必须守，接口定义 §四）：
//   1) 打断要快 —— 出声 → stop_tts 就停 TTS（延迟须真机测，不许凭印象承诺）
//   2) 打断不丢话题 —— next 回填 interrupted_question，先接回再接别的
//   3) AI 主动让路 —— 每问完留 wait_ms，不连珠炮
//   4) 任何反应都不算错 —— 含糊/超时/重问耗尽 → 一律默认新建，绝不卡住老人
const INTERVIEW = {
  START: '/api/echoes/interview/start',            // ?owner_id=&viewer_id=
  NEXT: '/api/echoes/interview/next',
  BARGE_IN: '/api/echoes/interview/barge_in',
  ASK_CLASSIFY: '/api/echoes/interview/ask_classify',
  CLASSIFY_ANSWER: '/api/echoes/interview/classify_answer',
  PREF: '/api/echoes/interview/pref'
};

/** 开始采访：AI 主动出第一问（优先问人生锚点） */
function interviewStart(ownerId, viewerId) {
  return post(INTERVIEW.START + '?owner_id=' + encodeURIComponent(ownerId || '') +
              (viewerId ? '&viewer_id=' + encodeURIComponent(viewerId) : ''));
}

/**
 * 答完出下一问；若上一问被打断，回填 interrupted_question（铁律 2 不丢话题）
 * @returns {Promise<{question,state,wait_ms,follow_digression}>} state=resumed 表示接回原问
 */
function interviewNext(ownerId, viewerId, lastAnswer, interruptedQuestion, interruptCount) {
  return post(INTERVIEW.NEXT, {
    owner_id: ownerId, viewer_id: viewerId || '',
    last_answer: lastAnswer || '', interrupted_question: interruptedQuestion || '',
    interrupt_count: interruptCount || 0
  });
}

/** ★老人打断判定：出声 → stop_tts 就该 1 秒内停 TTS（延迟须真机测） */
function interviewBargeIn(ownerId, energyDb, assumingNorm) {
  const body = { owner_id: ownerId || '' };
  if (energyDb !== undefined && energyDb !== null) body.energy_db = energyDb;
  if (assumingNorm) body.assuming_norm = assumingNorm;
  return post(INTERVIEW.BARGE_IN, body);
}

/** 自述页保存后：要不要弹归类问（含频率保护，防烦） */
function interviewAskClassify(ownerId, viewerId, newStoryId) {
  return post(INTERVIEW.ASK_CLASSIFY, {
    owner_id: ownerId, viewer_id: viewerId || '', new_story_id: newStoryId || ''
  });
}

/**
 * 老人对归类问的回答 → new / existing（安全兜底：含糊=新建）
 * @param {object} o {ownerId, viewerId, newStoryId, answerText, answerKey, retryUsed}
 */
function interviewClassifyAnswer(o) {
  const d = o || {};
  return post(INTERVIEW.CLASSIFY_ANSWER, {
    owner_id: d.ownerId || '', viewer_id: d.viewerId || '', new_story_id: d.newStoryId || '',
    answer_text: d.answerText || '', answer_key: d.answerKey || '', retry_used: d.retryUsed || 0
  });
}

/** 「别问了」开关 + 打断灵敏度档位（内部档 low/normal/high） */
function interviewPref(ownerId, opts) {
  const o = opts || {};
  const body = { owner_id: ownerId || '' };
  if (o.mutedAsk !== undefined && o.mutedAsk !== null) body.muted_ask = !!o.mutedAsk;
  if (o.sensitivity) body.sensitivity = o.sensitivity;
  return post(INTERVIEW.PREF, body);
}

// ============ 成书 线（小鲸鱼 10-11 接口，v3.0 §八，形状已冻结）============
// 后端：backend/book_api.py（selftest_book_api.py 28/28 全绿）
// 派单：docs/派单/派单_小龙虾_成书接口_20261011.md
// 三条铁律（前端必须守）：
//   1) 两筐分清 —— own（自己，自动装，不可取消）；public（别人公开的，点选才装）
//   2) 引用段只读 —— entry.is_quote==true → 渲染引用块 + quote_label，不给编辑按钮
//   3) 谁成书谁是「我」—— 一律以 owner_id 为准；空书明确拒绝（no_stories/empty_book），不静默成功
const BOOK = {
  SOURCE: '/api/echoes/book/source',       // 取材：算两筐
  GENERATE: '/api/echoes/book/generate',   // 生成/刷新电子书
  EBOOK: '/api/echoes/book/ebook'          // 取我的电子书
};

/**
 * 取材：把两筐素材摆出来。
 * @returns {Promise<{own:[], public:[], own_count, public_count, empty?, hint?}>}
 *   own    = 筐①自己的（自动装、不可取消勾选）
 *   public = 筐②别人公开提我的（点选加入、可勾）
 *   empty=true 时表示一条故事都没有（前端显示引导，不当报错）
 */
function bookSource(ownerId, actorId) {
  return post(BOOK.SOURCE, { owner_id: ownerId || '', actor_id: actorId || ownerId || '' });
}

/**
 * 生成 / 刷新电子书。
 * @param {string} ownerId 书的主人（=点成书的「我」）
 * @param {object} o {actorId, title, pickedPublicIds, ebookId}
 *   pickedPublicIds = 从公共筐点选要装的素材 id 列表（[] 表示一件都不装）
 *   ebookId         = 传上次的 ebook_id → 覆盖刷新（§8.4 活文档）
 * @returns {Promise<{ebook_id,title,chapters,story_count,clip_count,contributors,generated_at}>}
 *   chapters[].entries[] 里 is_quote==true 的 = 引用段（渲染引用块，不给编辑按钮）
 */
function bookGenerate(ownerId, o) {
  const d = o || {};
  return post(BOOK.GENERATE, {
    owner_id: ownerId || '',
    actor_id: d.actorId || ownerId || '',
    title: d.title || '',
    picked_public_ids: d.pickedPublicIds || [],
    ebook_id: d.ebookId || ''
  });
}

/**
 * 取这本书（owner）已生成的电子书。
 * @returns {Promise<{empty:boolean, book:{ebook_id,title,story_count,status,chapters,contributors}|null}>}
 *   empty=true 表示还没成书（前端显示「还没成书」空态，**不是错误**）
 */
function bookEbook(ownerId, viewerId) {
  return get(BOOK.EBOOK, { owner_id: ownerId, viewer_id: viewerId });
}

// ============ 加入链路「我也加进来」 线（小鲸鱼 10-15 接口 v1，路由 61~63，形状已冻结）============
// 后端：backend/join_api.py（selftest_join_api.py 32/32；小龙虾本机 uvicorn 实测 23/24，1 项为口径 note）
// 需求书 v3.0 §8之二.5：看完 → 篇末「这是<owner>的故事，里面提到了你 [我也加进来]」→ 登录 → 默认加入"这一篇"
// 三条安全闸门（前端必须守，任务单 §三条）：
//   1) 只加这一篇 —— 加入后 granted_via=story、只看这一篇，同书别的私有篇照样看不到
//   2) 必须先有可见关系才能加 —— 非被提及者且无既有关系 → not_mentioned（不许凭 token 塞进私有篇）
//   3) 登录态才调 —— 无 user_id → login_required（不许无登录偷偷加人）
const JOIN = {
  TARGET: '/api/echoes/join/target',   // GET  篇末那一块（未登录也返文案）
  STORY: '/api/echoes/join/story',     // POST ★点「我也加进来」→ 默认加入这一篇
  MINE: '/api/echoes/join/mine'        // GET  我加入了哪些书/哪些篇
};

/**
 * 篇末那一块要显示什么（看完分享篇后调）。
 * @param {string} shareToken 分享令牌（无登录读用的同一把钥匙）
 * @param {string} [userId]   登录后传 → 才能知道"我加没加过"；未登录传空
 * @returns {Promise<{story_id,title,owner_display_name,headline,need_login,already_joined,can_join,join_granularity,reason?,reason_code?}>}
 */
function joinTarget(shareToken, userId) {
  return get(JOIN.TARGET, { share_token: shareToken, user_id: userId || '' });
}

/**
 * ★点【我也加进来】→ 默认加入"这一篇"（幂等；重复点 already_joined=true，Member 不翻倍）。
 * @param {string} shareToken  分享令牌
 * @param {string} userId      必填（登录态才调；调用方应先确保已登录）
 * @param {object} [opts] {displayName, phone}
 * @returns {Promise<{story_id,owner_id,owner_display_name,member_id,granted_via,granted_scope,visible_story_ids,visible_count,already_joined}>}
 */
function joinByShare(shareToken, userId, opts) {
  const o = opts || {};
  const body = { share_token: shareToken, user_id: userId || '' };
  if (o.displayName) body.display_name = o.displayName;
  if (o.phone) body.phone = o.phone;
  return post(JOIN.STORY, body);
}

/**
 * 我加入了哪些书（families 看整本）/ 哪些篇（story_memberships 只看这几篇）。
 * @param {string} userId 必填
 * @returns {Promise<{families,story_memberships,family_count,story_count}>}
 */
function joinMine(userId) {
  return get(JOIN.MINE, { user_id: userId });
}

// ============================================================
// ★ 加家人（小鲸鱼 10-16，路由 4 条；需求书 §2.2/§2.3）
//   家人 = 看整本（granted_scope=book），与「我也加进来」的单篇关系并存不互斥。
// 铁律：owner_id 必传（权限判定的根，缺了后端直接拒，绝不退化放行）；
//      手机号一律脱敏回显（phone_masked），前端不拿手机号做匹配。
// ============================================================
const FAMILY = {
  SEARCH: '/api/echoes/family/search',   // GET  按名字找人（只回 user_id/显示名，不返手机号）
  ADD: '/api/echoes/family/add',         // POST 加家人 → 看整本（幂等，不许加自己）
  LIST: '/api/echoes/family/list',       // GET  我的家人（已认领 family / 待认领 pending）
  REMOVE: '/api/echoes/family/remove'    // POST 移出名单 → 不再能看整本（不动单篇关系）
};

/**
 * 按名字找家人（§2.3 对方已在小程序，直接选名字加入）。
 * @param {string} ownerId 书的主人（必传）
 * @param {string} name    要找的名字
 * @returns {Promise<{candidates:[{user_id,display_name,already_family,relation}],count}>}
 */
function familySearch(ownerId, name) {
  return get(FAMILY.SEARCH, { owner_id: ownerId, name: name });
}

/**
 * 加一个家人 → 他能看整本书。
 * @param {string} ownerId  书的主人（必传）
 * @param {object} o        {userId, phone, displayName, relation}
 *                          userId（对方已在小程序）与 phone（还没上过）二选一
 * @returns {Promise<{member_id,owner_id,user_id,display_name,relation,phone_masked,
 *                    granted_via,granted_scope,claimed,book_story_count,already_family}>}
 */
function familyAdd(ownerId, o) {
  const opt = o || {};
  const body = { owner_id: ownerId || '' };
  if (opt.userId) body.user_id = opt.userId;
  if (opt.phone) body.phone = opt.phone;
  if (opt.displayName) body.display_name = opt.displayName;
  if (opt.relation) body.relation = opt.relation;
  return post(FAMILY.ADD, body);
}

/**
 * 我的家人名单（两栏：已认领 / 待认领；手机号脱敏）。
 * @param {string} ownerId 必传
 * @returns {Promise<{family, pending, family_count, pending_count}>}
 */
function familyList(ownerId) {
  return get(FAMILY.LIST, { owner_id: ownerId });
}

/**
 * 把一位家人移出名单 → 不再能看整本。只动家人名单，不动单篇关系。
 * @param {string} ownerId  必传
 * @param {string} memberId 名单里那条记录的 id（不是 user_id）
 * @returns {Promise<{removed:boolean,member_id}>}
 */
function familyRemove(ownerId, memberId) {
  return post(FAMILY.REMOVE, { owner_id: ownerId || '', member_id: memberId || '' });
}

// ============================================================
// ★ 做成一张图（小鲸鱼 10-18，路由 2 条；卡片出图通道）
//   只画公开素材：整篇全私有 → not_shareable，不出含私有内容的图。
// 两条路：
//   ① cardRender → 直接拿 PNG 二进制（wx.downloadFile / wx.request responseType=arraybuffer）
//   ② cardPreview → 只回元信息（宽高/字节/底部留白/越界），给前端先排版 + 自测自证
// ============================================================
const CARD = {
  RENDER: '/api/echoes/card/render',     // GET  PNG 二进制（kind=story|book）
  PREVIEW: '/api/echoes/card/preview'    // POST 只量不出图（宽高/字节/留白）
};

/**
 * 出卡片图的下载地址（给 wx.downloadFile 用）。
 * @param {string} kind     'story' | 'book'
 * @param {string} targetId story_id（kind=story）或 owner_id（kind=book）
 * @param {string} actorId  当前登录人（必传，缺了后端拒）
 * @returns {string} 完整 URL
 */
function cardRenderUrl(kind, targetId, actorId) {
  return buildUrl(CARD.RENDER, { kind: kind, target_id: targetId || '', actor_id: actorId || '' });
}

/**
 * 卡片图体检（不出图，只量）。前端先调它决定排版；自测靠它自证。
 * @param {object} o {actorId, kind, targetId}
 * @returns {Promise<{width,height,ink_bottom_gap_px,overflow,line_found}>}
 */
function cardPreview(o) {
  const opt = o || {};
  return post(CARD.PREVIEW, {
    actor_id: opt.actorId || '',
    kind: opt.kind || 'story',
    target_id: opt.targetId || ''
  });
}

// ============================================================
// ★ P0-2（小鲸鱼 10-22 活地图）：后端已就绪、前端原先未接的 4 组接口
//   一律「后端有、前端原无」，本次按活地图顺序 A→B→C→D 补接。
//   明确不接：pay/* 支付、print/* 印刷、share/* 分享、storage/media_url、tts/*、group/*
// ============================================================

// —— A 成书的读：我的书列表 / 读某一本 / 锁状态 / 续添 ——
const BOOK_EXTRA = {
  MY: '/api/echoes/book/my',               // GET  user_id      → 我有哪些书
  VIEW: '/api/echoes/book/view',           // GET  owner_id      → 读某一本（scroll/paged/photobook）
  LOCK_STATE: '/api/echoes/book/lock_state', // GET owner_id    → 锁没锁、锁了买哪个（§九 收费闸门）
  APPEND: '/api/echoes/book/append'        // POST owner_id      → 往书里续添故事
};

/**
 * 我有哪些书。
 * @param {string} userId 必填
 * @returns {Promise<{books:[]}>}
 */
function bookMy(userId) {
  return get(BOOK_EXTRA.MY, { user_id: userId });
}

/**
 * 读某一本书（§8.6 三种形态）。
 * @param {string} ownerId  书的主人（必填）
 * @param {object} [o] {viewerId, form:'scroll'|'paged'|'photobook', bookSpec:'A5'}
 * @returns {Promise<{book:{...}}>}
 */
function bookView(ownerId, o) {
  const opt = o || {};
  return get(BOOK_EXTRA.VIEW, {
    owner_id: ownerId || '',
    viewer_id: opt.viewerId || '',
    form: opt.form || 'scroll',
    book_spec: opt.bookSpec || 'A5'
  });
}

/**
 * 这本书锁不锁（进「我的书」页先调它；locked=true 显示预览+解锁按钮，别直接请求 view 撞锁）。
 * @param {string} ownerId 必填
 * @returns {Promise<{locked,price?,product?,hint?}>}
 */
function bookLockState(ownerId) {
  return get(BOOK_EXTRA.LOCK_STATE, { owner_id: ownerId || '' });
}

/**
 * 往书里续添故事（空数组 = 自动补进尚无的故事）。
 * @param {string} ownerId 必填
 * @param {object} [o] {actorId, storyIds:[]}
 * @returns {Promise<{ebook_id,added_count,story_count}>}
 */
function bookAppend(ownerId, o) {
  const opt = o || {};
  return post(BOOK_EXTRA.APPEND, {
    owner_id: ownerId || '',
    actor_id: opt.actorId || ownerId || '',
    story_ids: opt.storyIds || []
  });
}

// —— B 故事详情 / 列表 / 新建 / 删除 ——
const STORY = {
  DETAIL: '/api/echoes/story/detail',      // GET  story_id, owner_id, viewer_id
  LIST: '/api/echoes/story/list',          // GET  owner_id, viewer_id, limit, offset
  CREATE: '/api/echoes/story/create',      // POST owner_id, actor_id, title, raw_content...
  DELETE: '/api/echoes/story/delete'       // POST story_id, owner_id, actor_id
};

/**
 * 一条故事的详情。
 * @param {string} storyId 必填
 * @param {string} ownerId 书的主人（权限的根）
 * @param {string} [viewerId] 看的人；空 = 主人本人
 */
function storyDetail(storyId, ownerId, viewerId) {
  return get(STORY.DETAIL, {
    story_id: storyId || '',
    owner_id: ownerId || '',
    viewer_id: viewerId || ''
  });
}

/**
 * 一个人的故事列表。
 * @param {string} ownerId 必填
 * @param {object} [o] {viewerId, limit:200, offset:0}
 * @returns {Promise<{stories:[],total}>}
 */
function storyList(ownerId, o) {
  const opt = o || {};
  return get(STORY.LIST, {
    owner_id: ownerId || '',
    viewer_id: opt.viewerId || '',
    limit: opt.limit || 200,
    offset: opt.offset || 0
  });
}

/**
 * 新建一条故事。
 * @param {object} o {ownerId, actorId, title, rawContent, summary, timeRaw, peopleMentioned, storyId}
 *   storyId 传了则幂等返回（弱网重试防重建）
 */
function storyCreate(o) {
  const d = o || {};
  return post(STORY.CREATE, {
    owner_id: d.ownerId || '',
    actor_id: d.actorId || d.ownerId || '',
    title: d.title || '',
    raw_content: d.rawContent || '',
    summary: d.summary || '',
    time_raw: d.timeRaw || '',
    people_mentioned: d.peopleMentioned || [],
    story_id: d.storyId || ''
  });
}

/**
 * 删一条故事（软删，真删在后端；前端只传 id）。
 * @param {string} storyId 必填
 * @param {string} ownerId 必填
 * @param {string} [actorId]
 */
function storyDelete(storyId, ownerId, actorId) {
  return post(STORY.DELETE + '?story_id=' + encodeURIComponent(storyId || ''), {
    story_id: storyId || '',
    owner_id: ownerId || '',
    actor_id: actorId || ownerId || ''
  });
}

// —— C 素材可见性（§1.2：默认私有，提供人主动公开；权限模型的核心） ——
const CLIP_VISIBILITY = '/api/echoes/clip/visibility';

/**
 * 把一条素材设为公开/私有。
 * @param {string} clipId   必填
 * @param {string} actorId  操作人（必须是提供人/书主人）
 * @param {string} visibility 'public' | 'private'
 */
function clipSetVisibility(clipId, actorId, visibility) {
  return post(CLIP_VISIBILITY, {
    clip_id: clipId || '',
    actor_id: actorId || '',
    visibility: visibility || 'private'
  });
}

// —— D 采访收尾：复述确认（§7.4/§7.5/§7.6 C 方案） ——
const RECAP_CONFIRM = '/api/echoes/interview/recap_confirm';

/**
 * 采访收尾「确认这段记下来」。answer_key 空 = 只出复述脚本；
 * accept + apply=true → 写回 Story.polished_content。
 * @param {object} o {ownerId, viewerId, storyId, qaPairs, polishedText, answerKey, answerText, retryUsed, apply}
 */
function interviewRecapConfirm(o) {
  const d = o || {};
  return post(RECAP_CONFIRM, {
    owner_id: d.ownerId || '',
    viewer_id: d.viewerId || '',
    story_id: d.storyId || '',
    qa_pairs: d.qaPairs || null,
    polished_text: d.polishedText || '',
    answer_key: d.answerKey || '',
    answer_text: d.answerText || '',
    retry_used: d.retryUsed || 0,
    apply: !!d.apply
  });
}

// ============ 九个九付费链路（2026-10-31 新增 · §9.6 五修） ============
// 铁律：价格一律不在前端写死，全部从 /pay/plans 或本模块返回里取；
//       按钮文案也不在前端编，用后端给的 label（老人看到的措辞不能各端各写一套）。
const PAY = {
  IDENTITY: '/api/echoes/pay/identity',
  CHOICES: '/api/echoes/pay/choices',
  CHOOSE: '/api/echoes/pay/choose',
  ACCEPT_GIFT: '/api/echoes/pay/accept_gift',
  PRINT_ELIGIBILITY: '/api/echoes/pay/print_eligibility',
  PLANS: '/api/echoes/pay/plans'
};

/** 我是谁 → 我这一本册子现在什么状态（有没有书、归谁、付到哪一档） */
function payIdentity(userId) {
  return get(PAY.IDENTITY, { user_id: userId || '' });
}
/** 付完 9.9 之后的两个按钮（没到账 → bought=false，前端不给按钮） */
function payChoices(userId) {
  return get(PAY.CHOICES, { user_id: userId || '' });
}
/** self_first=我自己先说 / gift_to_elder=转给爸妈 */
function payChoose(userId, choice) {
  return post(PAY.CHOOSE, { user_id: userId || '', choice: choice || '' });
}
/** 老人/家人点开邀请卡后接受 → 接受的人成为书主人 */
function payAcceptGift(token, newOwnerId) {
  return post(PAY.ACCEPT_GIFT, { token: token || '', new_owner_id: newOwnerId || '' });
}
/** 299 实体书：答够页数才解锁 */
function payPrintEligibility(ownerId) {
  return get(PAY.PRINT_ELIGIBILITY, { owner_id: ownerId || '' });
}
/** 后台配的价格（前端只读展示，不写死） */
function payPlans() {
  return get(PAY.PLANS);
}

module.exports = {
  request, get, post, buildUrl,
  CLAIM,
  claimLogin, claimRegister, claimSearch, claimMentioned,
  claimConfirm, claimReject, claimPending,
  getMentionedCache, getSession, setSession,
  LOGIN,
  login, wxLoginCode, loginProfile, loginSetUiMode,
  CLIP,
  clipAudio, clipOriginal, clipVideo, clipTranscribe, clipList,
  uploadUrl, storageConfirm, absUrl,
  TIMELINE,
  timelineGet, timelinePending, timelineSetTime, timelineAutoPlace,
  INTERVIEW,
  interviewStart, interviewNext, interviewBargeIn,
  interviewAskClassify, interviewClassifyAnswer, interviewPref,
  BOOK,
  bookSource, bookGenerate, bookEbook,
  JOIN,
  joinTarget, joinByShare, joinMine,
  FAMILY,
  familySearch, familyAdd, familyList, familyRemove,
  CARD,
  cardRenderUrl, cardPreview,
  // P0-2（10-22）：A 成书读 / B 故事 / C 素材可见性 / D 采访收尾
  BOOK_EXTRA,
  bookMy, bookView, bookLockState, bookAppend,
  STORY,
  storyDetail, storyList, storyCreate, storyDelete,
  clipSetVisibility,
  interviewRecapConfirm,
  // 九个九付费链路（10-31）
  PAY,
  payIdentity, payChoices, payChoose, payAcceptGift,
  payPrintEligibility, payPlans
};
