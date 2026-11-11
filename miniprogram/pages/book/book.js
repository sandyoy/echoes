/**
 * pages/book/book.js —— 成书页（v3.0 §八：两筐素材装书）
 *
 * 派单：docs/派单/派单_小龙虾_成书接口_20261011.md
 * 后端：backend/book_api.py（selftest_book_api.py 28/28 全绿，形状已冻结）
 *
 * 一页两态（不建两个页面，减少跳转，老人不迷路）：
 *   ① 取材态：进页面调 POST /book/source，摆两筐——
 *        · own    = 「你的记录（自动收录）」：不可取消勾选（需求书：自己的自动装）
 *        · public = 「别人提到的（点选加入）」：可勾，勾了才装
 *      点「生成」→ POST /book/generate（带勾选的 picked_public_ids）
 *   ② 成书态：点【我的书】调 GET /book/ebook 渲染章节；
 *        引用段（is_quote==true）渲染成引用块 + quote_label，**不给编辑按钮**（editable=false）。
 *
 * 三条铁律（前端必须守）：
 *   1) 两筐分清 —— own 不可取消；public 点选才装
 *   2) 引用段只读 —— is_quote==true 只展示，不出编辑按钮
 *   3) 活文档 —— 再点生成时回传上次 ebook_id = 覆盖刷新（不新建）
 *
 * 本页只做「取材/生成/展示」，不自己算章节、不自己排时间（排序在后端）。
 */
const api = require('../../utils/api.js');
const app = getApp();

/* ============================================================
   ★ 目录化（11-08 sandy 真机实测：「我的故事」=原料碎片直倒 → 废掉重做）
   要求形态：像一本书的目录 —— 分段 / 标题 / 年份，另有一个「待整理区」。
   做法：
     · 有年份的碎片 → 按年份归段，每段内按时间排；段标题 =「1978年」这种
     · 没有年份的 → 全进「待整理区」，不放正文里（等老人补时间再归位）
   这一层只做「分组」，不改任何碎片内容（碎片原文照留，点进去才看）。
   ============================================================ */

/** 从一条素材里抠年份（1978 / 一九七八 都认），抠不到返回 0 */
function pickYear(item) {
  const cands = [
    item && item.time_label,
    item && item.time_raw,
    item && item.time_sort_key
  ];
  for (let i = 0; i < cands.length; i++) {
    const v = cands[i];
    if (!v && v !== 0) continue;
    if (typeof v === 'number' && v > 1000 && v < 3000) return v;
    const m = String(v).match(/(1[89]\d{2}|20\d{2})/);
    if (m) return parseInt(m[1], 10);
    // 中文年份「一九七八」
    const cn = String(v).match(/([一二三四五六七八九〇零]{4})年/);
    if (cn) {
      const map = { '〇': 0, '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
                    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9 };
      const digits = cn[1].split('').map((c) => map[c]);
      if (digits.every((d) => d !== undefined)) {
        const y = parseInt(digits.join(''), 10);
        if (y > 1800 && y < 2100) return y;
      }
    }
  }
  return 0;
}

/**
 * ★ 11-10 sandy 真机实测：「我的故事这里头，还是写的是一堆一条一个一句话……会太多」
 * 病根：标题取正文前 12 字 + 摘要取前 40 字 → 同一段话在同一行显示两遍，
 *       一眼看过去就是"一堆一条一句"，目录感全无。
 * 改法：标题【不再是正文截断】，改成能认人的"这段讲的是什么"——
 *       优先用它自己的话里的时间点（如"1968 年"）+ 人物/主题词，都没有就按序编号。
 *       摘要只在标题明显过短时才给，且不与标题重复。
 */

/** 从正文里挑一个"这段讲的是什么"的短标签（时间点/人物/主题词），挑不到返回 '' */
function pickTag(text) {
  const t = String(text || '').trim();
  if (!t) return '';
  // ① 先找时间点：「1968年」「那年我18岁」「五十年代」
  let m = t.match(/((?:19|20)\d{2})\s*年/);
  if (m) return m[1] + ' 年';
  m = t.match(/([一二三四五六七八九十]{1,3})\s*十\s*年代/);
  if (m) return m[1] + '十年代';
  m = t.match(/那年我\s*(\d{1,2})\s*岁/);
  if (m) return '那年 ' + m[1] + ' 岁';
  // ② 再找人物/场景词（老人叙述里最常出现的"抓手"）
  const keys = ['老伴', '父亲', '母亲', '爸爸', '妈妈', '爷爷', '奶奶', '外婆', '外公',
    '老师', '部队', '当兵', '上学', '高考', '结婚', '生孩子', '搬家', '工作', '退休',
    '生病', '去世', '老家', '工厂', '下乡', '插队'];
  for (let i = 0; i < keys.length; i++) {
    if (t.indexOf(keys[i]) >= 0) return keys[i];
  }
  return '';
}

/** 列表标题：优先"讲的是什么"，其次序号，绝不整句照搬正文 */
function shortTitle(item, seq) {
  const t = (item && item.text ? String(item.text) : '').trim();
  const tag = pickTag(t);
  if (tag) return tag;
  if (t) return '第 ' + (seq || 1) + ' 段';
  return '（还没说话）';
}

/** 摘要：只有标签订不出来时，才给一段短的、且明确是"开头是……" */
function shortSummary(item, title) {
  const t = (item && item.text ? String(item.text) : '').trim();
  if (!t) return '';
  if (!title || title.indexOf('第 ') === 0) {
    return t.length > 34 ? t.slice(0, 34) + '…' : t;
  }
  return '';
}

/** 有年份的碎片 → 按年份成段（段内按时间升序） */
function buildSections(list) {
  const byYear = {};
  (list || []).forEach((item) => {
    const y = pickYear(item);
    if (!y) return;
    if (!byYear[y]) byYear[y] = [];
    byYear[y].push(item);
  });
  const years = Object.keys(byYear).map(Number).sort((a, b) => a - b);
  return years.map((y) => ({
    year: y,
    year_label: y + '年',
    count: byYear[y].length,
    items: byYear[y].map((it, i) => {
      const tt = shortTitle(it, i + 1);
      return {
        clip_id: it.clip_id,
        title: tt,
        summary: shortSummary(it, tt),
        time_label: it.time_label || ''
      };
    })
  }));
}

/** 没年份的碎片 → 待整理区 */
function buildTidy(list) {
  return (list || [])
    .filter((item) => !pickYear(item))
    .map((it, i) => {
      const tt = shortTitle(it, i + 1);
      return {
        clip_id: it.clip_id,
        title: tt,
        summary: shortSummary(it, tt),
        time_label: it.time_label || ''
      };
    });
}

Page({
  data: {
    uiMode: 'standard',   // 'standard' | 'large'
    tab: 'source',        // 'source'=取材页 | 'ebook'=我的书
    loading: true,
    generating: false,
    error: '',            // 网络/后端错误（中文人话，可直接显示）

    ownerId: '',
    actorId: '',

    // —— 取材态 ——
    own: [],              // 筐①：自己的（自动装，不可取消）
    public: [],           // 筐②：别人公开的（点选加入）
    ownCount: 0,
    publicCount: 0,
    sourceEmpty: false,   // 一条故事都没有（后端 empty=true）
    // public 筐的勾选态：以 clip_id 为键（Object 便于 wxml 判）
    checked: {},          // { clip_id: true }
    checkedCount: 0,

    // ★ 目录化（11-08 定）：own 筐不再是碎片平铺，而是「按年份分段 + 待整理区」
    ownSections: [],      // [{year, year_label, count, items:[{clip_id,title,summary,time_label}]}]
    ownToTidy: [],        // 没年份的碎片 → 待整理区

    // 书名（空则由后端取昵称/「我的一生」）
    title: '',

    // —— 成书态 ——
    locked: false,        // §九 收费闸门：这本书锁着（进页先查 lock_state）
    lockInfo: null,       // {product?,price?,hint?} —— 锁着时显示预览+解锁引导
    ebookEmpty: true,     // 还没成书（**不是错误**）
    ebookId: '',          // 上次成书的 id（活文档：刷新时回传）
    bookTitle: '',
    chapters: [],         // [{story_id,story_title,time_label,entries[]}]
    contributors: [],     // ['李婶', ...]
    clipCount: 0,
    storyCount: 0
  },

  onLoad() {
    const g = app.globalData;
    // owner_id = 书的主人。本机联调默认看自己；真机由登录态/入口带入。
    const ownerId = this.options && this.options.owner_id
      ? this.options.owner_id
      : (g.userId || '');
    this.setData({
      uiMode: app.getUiMode(),
      ownerId: ownerId,
      actorId: g.userId || ownerId
    });
    if (!ownerId) {
      // 未登录 → 取材态空（不报错，不吓老人）
      this.setData({ loading: false, sourceEmpty: true, tab: 'source' });
      return;
    }
    this.loadSource();
  },

  onShow() {
    // 回到前台同步界面模式（v2.4 §3.2 全局可切）
    this.setData({ uiMode: app.getUiMode() });
  },

  onPullDownRefresh() {
    const done = this.data.tab === 'ebook' ? this.loadEbook() : this.loadSource();
    done.then(() => wx.stopPullDownRefresh());
  },

  // ===================== 取材（两筐） =====================

  /** 取材：把两筐素材摆出来。own 自动装；public 点选装 */
  loadSource() {
    const d = this.data;
    if (!d.ownerId) return Promise.resolve();
    this.setData({ loading: true, error: '' });
    return api.bookSource(d.ownerId, d.actorId)
      .then((data) => {
        const dd = data || {};
        // 默认勾选态清空（每次取材重新点；own 不需要勾选，永远装）
        this.setData({
          loading: false,
          own: dd.own || [],
          public: dd.public || [],
          ownCount: dd.own_count || 0,
          publicCount: dd.public_count || 0,
          sourceEmpty: !!dd.empty,
          checked: {},
          checkedCount: 0,
          // ★ 目录化：碎片不再平铺直倒，按年份归段（无年份 → 待整理区）
          ownSections: buildSections(dd.own || []),
          ownToTidy: buildTidy(dd.own || [])
        });
      })
      .catch((err) => {
        this.setData({ loading: false, error: (err && err.message) || '没取到素材，请稍后再试' });
      });
  },

  /** 公共筐点选/取消（own 筐不可点，wxml 里 own 卡片没有 bindtap） */
  onTogglePublic(e) {
    const cid = e.currentTarget.dataset.clipId;
    if (!cid) return;
    const checked = Object.assign({}, this.data.checked);
    if (checked[cid]) {
      delete checked[cid];
    } else {
      checked[cid] = true;
    }
    const ids = Object.keys(checked);
    this.setData({ checked: checked, checkedCount: ids.length });
  },

  onTitleInput(e) {
    this.setData({ title: (e.detail && e.detail.value) || '' });
  },

  /** ★ 点目录里的一条 → 展开看这段的原文（碎片原文一点没改，只是先收进目录里） */
  onOpenClip(e) {
    const cid = e.currentTarget.dataset.clipId;
    if (!cid) return;
    const all = (this.data.own || []).concat(this.data.public || []);
    const hit = all.filter((x) => x.clip_id === cid)[0];
    if (!hit) return;
    wx.showModal({
      title: (hit.time_label || '这段') ,
      content: (hit.text || '（这段还没有文字）'),
      showCancel: false,
      confirmText: '看完了'
    });
  },

  /** 切换到「我的书」：读已生成的电子书 */
  onTabEbook() {
    this.setData({ tab: 'ebook' });
    this.loadEbook();
  },

  /** 切回「取材」 */
  onTabSource() {
    this.setData({ tab: 'source' });
    this.loadSource();
  },

  /**
   * 点【生成】→ POST /book/generate。
   * 活文档：若已有一本（ebookId），回传之 = 覆盖刷新（不新建）。
   */
  onGenerate() {
    const d = this.data;
    if (d.generating) return;
    if (!d.ownerId) {
      wx.showToast({ title: '还没登录呢', icon: 'none' });
      return;
    }
    const picked = Object.keys(d.checked);
    this.setData({ generating: true });
    api.bookGenerate(d.ownerId, {
      actorId: d.actorId,
      title: d.title,
      pickedPublicIds: picked,
      ebookId: d.ebookId || ''      // 有则覆盖刷新（活文档）
    })
      .then((res) => {
        const r = res || {};
        this.setData({ generating: false, tab: 'ebook' });
        // 落成书态数据
        this.applyBook({
          ebook_id: r.ebook_id,
          title: r.title,
          story_count: r.story_count,
          chapters: r.chapters || [],
          contributors: r.contributors || []
        }, r.clip_count);
        wx.showToast({ title: '书做好了', icon: 'none' });
      })
      .catch((err) => {
        this.setData({ generating: false });
        const msg = (err && err.message) || '生成失败，请再试一次';
        // 空书/无素材：后端明确拒绝（no_stories/empty_book）——如实回话，不假装成功
        wx.showToast({ title: msg, icon: 'none', duration: 2500 });
      });
  },

  // ===================== 我的书 =====================

  /** 取我的电子书（进「我的书」时读）
   *  P0-2 · A 组：先调 /book/lock_state（§九 收费闸门），locked=true 就停在这里显示预览+解锁，
   *  不直接请求 ebook 撞锁（后端提示原文写在 book_lock_state 的 docstring 里）。 */
  loadEbook() {
    const d = this.data;
    if (!d.ownerId) return Promise.resolve();
    this.setData({ loading: true, error: '' });
    return api.bookLockState(d.ownerId)
      .then((ls) => {
        const state = ls || {};
        this.setData({
          locked: !!state.locked,
          lockInfo: state.locked ? state : null
        });
        if (state.locked) {
          this.setData({ loading: false, ebookEmpty: false });
          return null;
        }
        return api.bookEbook(d.ownerId, d.actorId)
          .then((data) => {
            const dd = data || {};
            if (dd.empty || !dd.book) {
              this.setData({ loading: false, ebookEmpty: true });
              return;
            }
            this.applyBook(dd.book, (dd.book && dd.book.clip_count));
          });
      })
      .catch((err) => {
        this.setData({ loading: false, error: (err && err.message) || '没取到书，请稍后再试' });
      });
  },

  /** 统一把 book 数据灌进 data（生成/取书两条路共用） */
  applyBook(book, clipCount) {
    const b = book || {};
    this.setData({
      loading: false,
      error: '',
      ebookEmpty: false,
      ebookId: b.ebook_id || '',
      bookTitle: b.title || '我的书',
      storyCount: b.story_count || 0,
      chapters: b.chapters || [],
      contributors: b.contributors || [],
      clipCount: clipCount !== undefined ? clipCount : (b.clip_count || 0)
    });
  },

  /** 空书态引导：去说说 */
  onTapGoCapture() {
    wx.navigateTo({
      url: '/pages/capture/capture?type=voice',
      fail: () => { /* 采集页未就绪时静默 */ }
    });
  },

  /** 取材态空引导：去时间轴看看 / 说说（★ timeline 在 tabBar 里 → switchTab） */
  onTapGoTimeline() {
    wx.switchTab({
      url: '/pages/timeline/timeline',
      fail: () => {
        wx.showToast({ title: '没打开，请再点一次', icon: 'none' });
      }
    });
  },

  /** ★ 做成一张图：把整本书画成一张卡（kind=book，target_id=owner_id） */
  onOpenCard() {
    const d = this.data;
    const target = d.ownerId || d.actorId;
    if (!target) {
      wx.showToast({ title: '还没登录呢', icon: 'none' });
      return;
    }
    const t = encodeURIComponent(d.bookTitle || '我的书');
    wx.navigateTo({
      url: `/pages/card/card?kind=book&target_id=${encodeURIComponent(target)}&title=${t}`,
      fail: () => { /* 卡片页未就绪时静默 */ }
    });
  }
});
