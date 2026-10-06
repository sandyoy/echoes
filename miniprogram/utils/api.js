/**
 * utils/api.js — 统一请求工具（v2.4 前端）
 *
 * 信封口径（小鲸鱼《接口定义_待认领_v1_20260927》第四节 + 采集接口纠偏单）：
 *   {"ok": true,  "data": {...}}
 *   {"ok": false, "error": "中文人话", "code": "bad_request|unauthorized|forbidden|not_found|..."}
 * 铁律：**前端只认 ok 一个字段**；失败必带中文 error，可直接弹给老人看；
 *       code 只用于程序分支，**不显示给用户**。
 */
const app = getApp();

/** 简单内存缓存：登录后拿到的「有 N 篇故事提到了你」 */
let _mentionedCache = { count: 0, stories: [] };
/** 简单内存缓存：登录总入口返回的 user_id */
let _session = { userId: '', phone: '' };

/** 统一请求：只看 ok，error 直显；code 留给调用方分支 */
function request(path, method, data) {
  return new Promise((resolve, reject) => {
    const base = (app && app.globalData && app.globalData.apiBase) || '';
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
function get(path, params) {
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
  return request(path + qs, 'GET');
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
function clipList(storyId, viewerId) {
  return get(CLIP.LIST, { story_id: storyId, viewer_id: viewerId });
}
/** 取上传地址（对象存储未定前会返 upload_not_configured，属预期） */
function uploadUrl(fileName, fileSize, mime) {
  return post(CLIP.UPLOAD_URL, { file_name: fileName, file_size: fileSize, mime: mime });
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

module.exports = {
  request, get, post,
  CLAIM,
  claimLogin, claimRegister, claimSearch, claimMentioned,
  claimConfirm, claimReject, claimPending,
  getMentionedCache, getSession, setSession,
  LOGIN,
  login, wxLoginCode, loginProfile, loginSetUiMode,
  CLIP,
  clipAudio, clipOriginal, clipVideo, clipTranscribe, clipList, uploadUrl,
  TIMELINE,
  timelineGet, timelinePending, timelineSetTime, timelineAutoPlace
};
