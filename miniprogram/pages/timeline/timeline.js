/**
 * pages/timeline/timeline.js —— 时间轴页（第2期「能排对」验收面）
 *
 * 依据：docs/事卷/往事可追忆_第2期前端设计预案_时间轴与改时间_小龙虾_20261006.md §1/§2
 * 接口：docs/事卷/接口定义_时间轴v1_20261006.md（小鲸鱼 10-06 v1，自测 33/33）
 *
 * 四条铁律（接口定义 §三，前端必须守）：
 *   1) 排序只在后端 —— 拿 nodes 顺序渲染，前端绝不重排（含 pending 单列）
 *   2) 只显示 time_label —— 不把「1970年代（老人说的）」加工成「1975年3月」
 *   3) 【时间待定】单列到底部灰点 —— 不塞进 nodes 参与排序
 *   4) 改过的不许被覆盖 —— 覆盖判断在后端；前端只管提交 set_time
 *
 * 本页只做「展示 + 改时间提交」，不自己解析时间、不自己算排序键。
 */
const api = require('../../utils/api.js');
const app = getApp();

Page({
  data: {
    uiMode: 'standard',   // 'standard' | 'large'
    loading: true,
    error: '',            // 网络/后端错误（中文人话，可直接显示）
    ownerId: '',
    viewerId: '',
    nodes: [],            // 后端已正序：每节 {node_id,time_sort_key,label,count,stories[]}
    pending: [],          // 【时间待定】区，永远排最后
    stats: { total: 0, placed: 0, pending: 0, node_count: 0 },
    // 改时间弹层
    editing: false,
    editNode: null,       // 当前改的节
    editReading: '',      // 回读串「这段是 X，对吗？」＝ time_label
    editChoice: false,    // 是否切到「自己选」年份滚轮
    yearRange: [],        // 大字号年份滚轮候选
    pickedYear: 0,
    pickerIndex: 0,       // picker 当前选中下标
    submitting: false
  },

  onLoad() {
    const g = app.globalData;
    // owner_id = 书的主人。第2期本机联调：默认看自己的书；真机由登录态/书入口带入。
    const ownerId = this.options && this.options.owner_id
      ? this.options.owner_id
      : (g.userId || '');
    const viewerId = g.userId || ownerId;
    this.setData({ uiMode: app.getUiMode(), ownerId: ownerId, viewerId: viewerId });
    this.loadTimeline();
  },

  onShow() {
    // 页面回到前台时同步界面模式（v2.4 §3.2 全局可切）
    this.setData({ uiMode: app.getUiMode() });
  },

  onPullDownRefresh() {
    this.loadTimeline().then(() => wx.stopPullDownRefresh());
  },

  /** N1：取整本时间轴。nodes 顺序原样用，不重排 */
  loadTimeline() {
    const d = this.data;
    if (!d.ownerId) {
      // 未登录/无书 → 空态（不报错）
      this.setData({ loading: false, nodes: [], pending: [], error: '' });
      return Promise.resolve();
    }
    this.setData({ loading: true, error: '' });
    return api.timelineGet(d.ownerId, d.viewerId)
      .then((data) => {
        const dd = data || {};
        this.setData({
          loading: false,
          nodes: dd.nodes || [],
          pending: dd.pending || [],
          stats: dd.stats || { total: 0, placed: 0, pending: 0, node_count: 0 }
        });
      })
      .catch((err) => {
        this.setData({ loading: false, error: (err && err.message) || '没取到时间轴，请稍后再试' });
      });
  },

  /** 点故事卡 = 展开看故事（§1.3-4：点是"看故事"、不是"改时间"） */
  onTapStory(e) {
    const sid = e.currentTarget.dataset.storyId;
    wx.navigateTo({
      url: '/pages/capture/capture?story_id=' + encodeURIComponent(sid),
      fail: () => { /* 采集页未就绪时静默，不打断 */ }
    });
  },

  /** 点「改时间」三字 → 打开弹层（§2：语音第一 + 回读当前时间） */
  onTapSetTime(e) {
    const node = (this.data.nodes || []).find(
      (n) => String(n.time_sort_key) === String(e.currentTarget.dataset.sortKey)
    );
    if (!node) return;
    this.openEditor(node);
  },

  /** 长按该节 = 改时间（辅入口，熟手功能，大字版不提示） */
  onLongPressNode(e) {
    const node = (this.data.nodes || []).find(
      (n) => String(n.time_sort_key) === String(e.currentTarget.dataset.sortKey)
    );
    if (node) this.openEditor(node);
  },

  /** 待定区「改时间」：取第一条待定的故事，回读「时间待定」 */
  onTapSetPending() {
    const first = (this.data.pending || [])[0];
    if (!first) return;
    this.openEditor({
      time_sort_key: 0,
      label: first.time_label || '时间待定',
      stories: [first]
    });
  },

  /** 打开改时间弹层：回读当前时间（time_label 原样，不加工） */
  openEditor(node) {
    // 回读串取该节 label；被用户确认过的那条优先（后端已处理 nodes[].label）
    const reading = (node && node.label) || '';
    const stories = (node && node.stories) || [];
    const anchorStory = stories[0] || {};
    const storyId = anchorStory.story_id || '';
    const years = [];
    for (let y = 2026; y >= 1900; y--) years.push(y);
    this.setData({
      editing: true,
      editNode: { sortKey: node.time_sort_key, label: reading, storyId: storyId },
      editReading: reading,
      editChoice: false,
      yearRange: years,
      pickedYear: (node && node.time_sort_key) || 2020,
      pickerIndex: Math.max(0, years.indexOf((node && node.time_sort_key) || 2020))
    });
    // §2.2-1 语音第一：打开弹层自动播放问句（TTS 未接入前不阻塞，只在有音频时播）
    if (this._askAudioUrl) {
      const audio = wx.createInnerAudioContext();
      audio.src = this._askAudioUrl;
      audio.play();
    }
  },

  /** 切到「自己选」大字号年份滚轮（§2.2-2 底线，始终可选） */
  onChooseBySelf() {
    this.setData({ editChoice: true });
  },

  onPickYear(e) {
    // picker selector 返回的是 range 下标，需映射回年份
    const idx = Number(e.detail.value) || 0;
    const year = this.data.yearRange[idx];
    this.setData({ pickedYear: Number(year) || this.data.pickedYear });
  },

  closeEditor() {
    this.setData({ editing: false, editNode: null, editReading: '', editChoice: false, submitting: false });
  },
  /**
   * N3 提交改时间。
   *  - 走「自己选」→ new_time_text = "NNNN年"
   *  - 走「按住说」→ 由语音识别结果填入（TODO(语音)：真机接入识别后回填 editSpeakingText）
   */
  submitSetTime() {
    const d = this.data;
    if (d.submitting) return;
    let text = '';
    if (d.editChoice) {
      text = d.pickedYear ? (d.pickedYear + '年') : '';
    } else {
      text = (this._spokenText || '').trim();
    }
    if (!text) {
      wx.showToast({ title: '请说一个时间', icon: 'none' });
      return;
    }
    const storyId = d.editNode && d.editNode.storyId;
    if (!storyId) {
      wx.showToast({ title: '这条故事没找到', icon: 'none' });
      return;
    }
    this.setData({ submitting: true });
    api.timelineSetTime(storyId, d.viewerId || d.ownerId, text)
      .then((res) => {
        const r = res || {};
        this.setData({ submitting: false, editing: false });
        // placed=false ⇒ 进了「时间待定」，照用户原话回读、不瞎猜（§5.5 第3条）
        const say = r.placed
          ? ('给您挪到' + (r.node_hint || r.time && r.time.time_label || text) + '了，对吗？')
          : ('这段先放「时间待定」，等您再想想');
        wx.showToast({ title: say, icon: 'none', duration: 2500 });
        return this.loadTimeline();   // 重新拉，nodes 顺序由后端给
      })
      .catch((err) => {
        this.setData({ submitting: false });
        wx.showToast({ title: (err && err.message) || '没改成，请再试一次', icon: 'none' });
      });
  }
});
