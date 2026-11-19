// 查拼音
Page({
  data: {
    queryText: '',
    result: null,
    searched: false
  },

  onInput(e) {
    this.setData({ queryText: e.detail.value })
  },

  doLookup() {
    const text = this.data.queryText.trim()
    if (!text) return

    const firstChar = text[0]
    const result = this.lookupInDict(firstChar)

    this.setData({ result, searched: true })
  },

  lookupInDict(char) {
    // 内置常用字拼音字典（四年级常见字）
    const dict = {
      '的': { pinyin: 'de', analysis: 'd + e → de（轻声）', similars: [], example: '我的书' },
      '了': { pinyin: 'le', analysis: 'l + e → le（轻声）', similars: ['子 (zi)'], example: '吃完了' },
      '是': { pinyin: 'shì', analysis: 'sh + ì → shì（整体认读音节）', similars: ['四 (sì)','十 (shí)'], example: '这是我的书包' },
      '不': { pinyin: 'bù', analysis: 'b + ù → bù', similars: ['布 (bù)','步 (bù)'], example: '我不知道' },
      '我': { pinyin: 'wǒ', analysis: 'w + ǒ → wǒ（整体认读音节）', similars: ['你 (nǐ)','他 (tā)'], example: '我是小学生' },
      '大': { pinyin: 'dà', analysis: 'd + à → dà', similars: ['太 (tài)','天 (tiān)'], example: '一个大苹果' },
      '人': { pinyin: 'rén', analysis: 'r + én → rén', similars: ['入 (rù)','八 (bā)'], example: '一个人' },
      '中': { pinyin: 'zhōng', analysis: 'zh + ōng → zhōng', similars: ['钟 (zhōng)','终 (zhōng)'], example: '中国' },
      '上': { pinyin: 'shàng', analysis: 'sh + àng → shàng', similars: ['让 (ràng)','尚 (shàng)'], example: '上学' },
      '下': { pinyin: 'xià', analysis: 'x + ià → xià', similars: ['吓 (xià)','夏 (xià)'], example: '下雨了' },
      '来': { pinyin: 'lái', analysis: 'l + ái → lái', similars: ['去 (qù)','菜 (cài)'], example: '快来' },
      '去': { pinyin: 'qù', analysis: 'q + ù → qù', similars: ['出 (chū)','趣 (qù)'], example: '去学校' },
      '好': { pinyin: 'hǎo', analysis: 'h + ǎo → hǎo', similars: ['号 (hào)','耗 (hào)'], example: '好朋友' },
      '看': { pinyin: 'kàn', analysis: 'k + àn → kàn', similars: ['着 (zhe)','见 (jiàn)'], example: '看电视' },
      '有': { pinyin: 'yǒu', analysis: 'y + ǒu → yǒu（整体认读音节）', similars: ['又 (yòu)','由 (yóu)'], example: '我有一个梦想' },
      '和': { pinyin: 'hé', analysis: 'h + é → hé', similars: ['合 (hé)','河 (hé)','喝 (hē)'], example: '我和你' },
      '你': { pinyin: 'nǐ', analysis: 'n + ǐ → nǐ', similars: ['我 (wǒ)','您 (nín)'], example: '你好' },
      '他': { pinyin: 'tā', analysis: 't + ā → tā', similars: ['她 (tā)','它 (tā)','地 (de)'], example: '他是我的朋友' },
      '它': { pinyin: 'tā', analysis: 't + ā → tā', similars: ['他 (tā)','她 (tā)'], example: '它是一只猫' },
      '她': { pinyin: 'tā', analysis: 't + ā → tā', similars: ['他 (tā)','它 (tā)'], example: '她是我的妈妈' },
      '山': { pinyin: 'shān', analysis: 'sh + ān → shān', similars: ['三 (sān)','扇 (shàn)'], example: '一座大山' },
      '水': { pinyin: 'shuǐ', analysis: 'sh + uǐ → shuǐ', similars: ['睡 (shuì)','谁 (shuí)'], example: '喝水' },
      '火': { pinyin: 'huǒ', analysis: 'h + uǒ → huǒ', similars: ['伙 (huǒ)','或 (huò)'], example: '灭火' },
      '风': { pinyin: 'fēng', analysis: 'f + ēng → fēng', similars: ['丰 (fēng)','封 (fēng)'], example: '刮风了' },
      '花': { pinyin: 'huā', analysis: 'h + uā → huā', similars: ['华 (huá)','画 (huà)'], example: '一朵花' },
      '月': { pinyin: 'yuè', analysis: '整体认读音节 yuè', similars: ['乐 (yuè/lè)','越 (yuè)'], example: '月亮' },
      '日': { pinyin: 'rì', analysis: '整体认读音节 rì', similars: ['四 (sì)','目 (mù)'], example: '生日' },
      '学': { pinyin: 'xué', analysis: 'x + ué → xué', similars: ['雪 (xuě)','血 (xuè)','写 (xiě)'], example: '学习' },
    }

    return dict[char] || null
  }
})
