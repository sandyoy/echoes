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
/** 简单内存缓存：登录总入口返回的 user_id（本机登录态未接前的过渡） */
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

module.exports = {
  request, get, post,
  CLAIM,
  claimLogin, claimRegister, claimSearch, claimMentioned,
  claimConfirm, claimReject, claimPending,
  getMentionedCache, getSession, setSession
};
