// 拼音闪卡
Page({
  data: {
    cards: [],
    currentIndex: 0,
    totalCards: 0,
    flipped: false,
    progressPercent: 0,
    correctCount: 0,
    wrongList: [],
    sessionDone: false,
    elapsedSeconds: 0,
    currentCard: {},
    startTime: 0,
    timer: null
  },

  onLoad(options) {
    const type = options.type || 'hunhe'
    const cards = this.getCardsByType(type)
    
    // 打乱顺序
    const shuffled = this.shuffle(cards)
    
    this.setData({
      cards: shuffled,
      totalCards: shuffled.length,
      currentCard: shuffled[0] || {},
      startTime: Date.now()
    })

    // 开始计时
    this.data.timer = setInterval(() => {
      if (!this.data.sessionDone) {
        this.setData({
          elapsedSeconds: Math.floor((Date.now() - this.data.startTime) / 1000)
        })
      }
    }, 1000)
  },

  onUnload() {
    if (this.data.timer) {
      clearInterval(this.data.timer)
    }
  },

  flipCard() {
    if (!this.data.sessionDone) {
      this.setData({ flipped: !this.data.flipped })
    }
  },

  markCorrect() {
    if (this.data.sessionDone) return
    this.nextCard(false)
  },

  markWrong() {
    if (this.data.sessionDone) return
    
    const wrongList = [...this.data.wrongList, this.data.currentCard]
    this.nextCard(true, wrongList)
  },

  nextCard(isWrong, wrongList) {
    const nextIndex = this.data.currentIndex + 1
    
    if (nextIndex >= this.data.totalCards) {
      // 本轮结束
      clearInterval(this.data.timer)
      
      const seconds = Math.floor((Date.now() - this.data.startTime) / 1000)
      
      this.setData({
        currentIndex: nextIndex,
        flipped: false,
        progressPercent: 100,
        sessionDone: true,
        elapsedSeconds: seconds,
        correctCount: isWrong ? this.data.correctCount : this.data.correctCount + 1,
        wrongList: wrongList || this.data.wrongList
      })

      // 记录学习时间
      this.recordStudyTime(seconds)
      return
    }

    this.setData({
      currentIndex: nextIndex,
      currentCard: this.data.cards[nextIndex],
      flipped: false,
      progressPercent: (nextIndex / this.data.totalCards) * 100,
      correctCount: isWrong ? this.data.correctCount : this.data.correctCount + 1,
      wrongList: wrongList || this.data.wrongList
    })
  },

  restartSession() {
    const shuffled = this.shuffle(this.data.cards)
    this.setData({
      cards: shuffled,
      currentIndex: 0,
      currentCard: shuffled[0],
      totalCards: shuffled.length,
      flipped: false,
      progressPercent: 0,
      correctCount: 0,
      wrongList: [],
      sessionDone: false,
      startTime: Date.now(),
      elapsedSeconds: 0
    })

    if (this.data.timer) clearInterval(this.data.timer)
    this.data.timer = setInterval(() => {
      if (!this.data.sessionDone) {
        this.setData({
          elapsedSeconds: Math.floor((Date.now() - this.data.startTime) / 1000)
        })
      }
    }, 1000)
  },

  reviewWrong() {
    const wrongCards = this.data.wrongList
    const shuffled = this.shuffle(wrongCards)
    this.setData({
      cards: shuffled,
      currentIndex: 0,
      currentCard: shuffled[0],
      totalCards: shuffled.length,
      flipped: false,
      progressPercent: 0,
      correctCount: 0,
      wrongList: [],
      sessionDone: false,
      startTime: Date.now(),
      elapsedSeconds: 0
    })

    if (this.data.timer) clearInterval(this.data.timer)
    this.data.timer = setInterval(() => {
      if (!this.data.sessionDone) {
        this.setData({
          elapsedSeconds: Math.floor((Date.now() - this.data.startTime) / 1000)
        })
      }
    }, 1000)
  },

  recordStudyTime(seconds) {
    const stat = wx.getStorageSync('pinyinStat') || {}
    const today = getTodayDateStr()
    
    if (stat.date === today) {
      stat.minutes = (stat.minutes || 0) + Math.ceil(seconds / 60)
    } else {
      stat.date = today
      stat.minutes = Math.ceil(seconds / 60)
    }
    
    wx.setStorageSync('pinyinStat', stat)

    // 也更新学习首页的统计
    const learnStats = wx.getStorageSync('todayLearnStats') || {}
    learnStats.date = today
    learnStats.pinyin = (learnStats.pinyin || 0) + Math.ceil(seconds / 60)
    learnStats.minutes = (learnStats.minutes || 0) + Math.ceil(seconds / 60)
    wx.setStorageSync('todayLearnStats', learnStats)
  },

  // 拼音数据
  getCardsByType(type) {
    const allData = {
      shengmu: [
        { pinyin: 'b', read: '玻', examples: ['八','白','笔','不'], confuseWith: 'd', memo: '像广播天线，肚子在右边' },
        { pinyin: 'p', read: '坡', examples: ['怕','跑','片','平'], confuseWith: 'q', memo: '泼水泼出去' },
        { pinyin: 'm', read: '摸', examples: ['妈','猫','马','木'], memo: '两扇门，摸摸看' },
        { pinyin: 'f', read: '佛', examples: ['发','飞','饭','风'], memo: '像拐杖' },
        { pinyin: 'd', read: '得', examples: ['大','打','到','东'], confuseWith: 'b', memo: '像个大肚子，肚子在左边' },
        { pinyin: 't', read: '特', examples: ['他','太','天','头'], confuseWith: 'f' },
        { pinyin: 'n', read: '讷', examples: ['那','你','年','牛'], confuseWith: 'l', memo: '嘴巴闭一下才出声' },
        { pinyin: 'l', read: '勒', examples: ['拉','老','里','来'], confuseWith: 'n', memo: '舌头抵上颚，气流从两边走' },
        { pinyin: 'g', read: '哥', examples: ['哥','高','国','干'], confuseWith: 'd' },
        { pinyin: 'k', read: '科', examples: ['看','快','口','开'], confuseWith: 'h' },
        { pinyin: 'h', read: '喝', examples: ['哈','好','和','红'], memo: '像张嘴哈气' },
        { pinyin: 'j', read: '鸡', examples: ['家','见','叫','今'], confuseWith: 'q' },
        { pinyin: 'q', read: '七', examples: ['七','前','去','请'], confuseWith: 'p', memo: '像数字9，拐弯在右边' },
        { pinyin: 'x', read: '西', examples: ['下','小','学','想'], confuseWith: 's' },
        { pinyin: 'zh', read: '知', examples: ['这','中','长','只'], confuseWith: 'z', memo: '翘舌，舌尖卷上去' },
        { pinyin: 'ch', read: '吃', examples: ['吃','出','车','成'], confuseWith: 'c', memo: '翘舌+用力吐气' },
        { pinyin: 'sh', read: '诗', examples: ['是','上','水','说'], confuseWith: 's', memo: '翘舌，气流从缝里出来' },
        { pinyin: 'r', read: '日', examples: ['人','热','然','让'], memo: '翘舌，声带振动' },
        { pinyin: 'z', read: '资', examples: ['在','做','走','字'], confuseWith: 'zh', memo: '平舌，舌尖抵下牙' },
        { pinyin: 'c', read: '次', examples: ['从','才','村','猜'], confuseWith: 'ch', memo: '平舌+吐气' },
        { pinyin: 's', read: '丝', examples: ['三','四','送','算'], confuseWith: 'sh', memo: '平舌，像蛇吐信子' },
        { pinyin: 'y', read: '衣', examples: ['一','有','也','又'] },
        { pinyin: 'w', read: '屋', examples: ['我','为','王','问'] }
      ],
      yunmu: [
        { pinyin: 'a', read: '啊', examples: ['阿','大','妈','拉'] },
        { pinyin: 'o', read: '喔', examples: ['哦','我','窝','破'], memo: '嘴巴圆圆的像鸡蛋' },
        { pinyin: 'e', read: '鹅', examples: ['鹅','得','了','哥'], memo: '嘴巴扁扁的' },
        { pinyin: 'i', read: '衣', examples: ['一','里','几','七'] },
        { pinyin: 'u', read: '乌', examples: ['五','不','路','书'], confuseWith: 'ü', memo: '嘴巴往前突出' },
        { pinyin: 'ü', read: '迂', examples: ['女','绿','去','鱼'], confuseWith: 'u', memo: '嘴巴像吹口哨' },
        { pinyin: 'ai', read: '爱', examples: ['爱','白','来','开'], memo: 'a→i 快速滑过去' },
        { pinyin: 'ei', read: '欸', examples: ['北','每','飞','黑'], confuseWith: 'ai' },
        { pinyin: 'ui', read: '威', examples: ['回','会','水','对'], memo: 'u→i 快速滑' },
        { pinyin: 'ao', read: '奥', examples: ['好','少','老','早'], memo: 'a→o 张大嘴到圆嘴' },
        { pinyin: 'ou', read: '欧', examples: ['走','口','后','楼'] },
        { pinyin: 'iu', read: '优', examples: ['六','有','久','秋'] },
        { pinyin: 'ie', read: '耶', examples: ['写','别','姐','谢'] },
        { pinyin: 'üe', read: '约', examples: ['学','月','绝','雪'] },
        { pinyin: 'er', read: '儿', examples: ['二','儿','耳','而'], memo: '舌头卷起来，独一无二' },
        { pinyin: 'an', read: '安', examples: ['安','看','半','饭'] },
        { pinyin: 'en', read: '恩', examples: ['很','人','门','文'], confuseWith: 'eng', memo: '舌头抵上牙，不卷' },
        { pinyin: 'in', read: '因', examples: ['今','心','近','林'], confuseWith: 'ing', memo: '舌头抵上牙' },
        { pinyin: 'un', read: '温', examples: ['春','论','村','困'] },
        { pinyin: 'ün', read: '晕', examples: ['云','军','群','训'] },
        { pinyin: 'ang', read: '昂', examples: ['让','方','长','忙'], confuseWith: 'an', memo: '嘴巴张大，舌头后缩' },
        { pinyin: 'eng', read: '亨', examples: ['风','能','冷','成'], confuseWith: 'en', memo: '舌头后缩，鼻子出气' },
        { pinyin: 'ing', read: '英', examples: ['听','明','星','行'], confuseWith: 'in', memo: '舌头后缩' },
        { pinyin: 'ong', read: '轰', examples: ['红','中','空','龙'], memo: '嘴巴圆，舌头后缩' }
      ],
      zhengtiren: [
        { pinyin: 'zhi', read: '知', examples: ['知','只','之','纸'] },
        { pinyin: 'chi', read: '吃', examples: ['吃','尺','迟','翅'] },
        { pinyin: 'shi', read: '师', examples: ['师','十','是','时'] },
        { pinyin: 'ri', read: '日', examples: ['日','热','柔','染'] },
        { pinyin: 'zi', read: '资', examples: ['资','子','字','自'] },
        { pinyin: 'ci', read: '次', examples: ['次','词','此','刺'] },
        { pinyin: 'si', read: '丝', examples: ['丝','四','死','思'] },
        { pinyin: 'yi', read: '衣', examples: ['一','医','已','意'] },
        { pinyin: 'wu', read: '屋', examples: ['五','无','午','物'] },
        { pinyin: 'yu', read: '鱼', examples: ['鱼','雨','语','玉'] },
        { pinyin: 'ye', read: '耶', examples: ['也','夜','叶','爷'] },
        { pinyin: 'yue', read: '月', examples: ['月','越','乐','阅'] },
        { pinyin: 'yuan', read: '圆', examples: ['圆','远','院','原'] },
        { pinyin: 'yin', read: '音', examples: ['音','因','印','银'] },
        { pinyin: 'yun', read: '云', examples: ['云','运','孕','韵'] },
        { pinyin: 'ying', read: '英', examples: ['英','影','应','迎'] }
      ]
    }

    if (type === 'hunhe') {
      // 混合：从所有类别中挑出易混淆的
      const confuseCards = []
      const allTypes = ['shengmu','yunmu','zhengtiren']
      allTypes.forEach(t => {
        allData[t].forEach(c => {
          if (c.confuseWith || t === 'shengmu') confuseCards.push(c)
        })
      })
      return confuseCards
    }

    return allData[type] || allData.shengmu
  },

  shuffle(arr) {
    const copy = [...arr]
    for (let i = copy.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [copy[i], copy[j]] = [copy[j], copy[i]]
    }
    return copy
  }
})

function getTodayDateStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
}
