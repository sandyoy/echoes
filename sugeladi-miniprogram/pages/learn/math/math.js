// 数学运算律 - 苏格拉底式对话学习
Page({
  data: {
    showDialog: false,
    currentTopic: '',
    dialogMessages: [],
    dialogInput: '',
    aiThinking: false,
    quickAnswers: []
  },

  startTopic(e) {
    const topic = e.currentTarget.dataset.topic
    const dialogScripts = this.getDialogScript(topic)

    this.setData({
      showDialog: true,
      currentTopic: topic,
      dialogMessages: dialogScripts,
      quickAnswers: dialogScripts.length > 0 ? dialogScripts[0].answers || [] : []
    })
  },

  closeDialog() {
    this.setData({ showDialog: false })
  },

  onDialogInput(e) {
    this.setData({ dialogInput: e.detail.value })
  },

  sendDialogMessage() {
    const text = this.data.dialogInput.trim()
    if (!text || this.data.aiThinking) return

    this.addUserMessage(text)
    this.processResponse(text)
  },

  sendQuickAnswer(e) {
    const answer = e.currentTarget.dataset.answer
    if (!answer || this.data.aiThinking) return

    this.addUserMessage(answer)
    this.processResponse(answer)
  },

  addUserMessage(text) {
    const messages = [...this.data.dialogMessages, { role: 'user', content: text }]
    this.setData({ dialogMessages: messages, dialogInput: '', quickAnswers: [], aiThinking: true })
  },

  processResponse(text) {
    const topic = this.data.currentTopic
    const responses = this.getResponses(topic)

    // 找到匹配的回复
    let matched = null
    for (const [keywords, response] of Object.entries(responses)) {
      const keywordList = keywords.split('|')
      if (keywordList.some(k => text.includes(k))) {
        matched = response
        break
      }
    }

    // 默认回复
    if (!matched) {
      matched = this.getDefaultResponse(topic)
    }

    // 模拟AI思考延迟
    setTimeout(() => {
      const messages = [...this.data.dialogMessages, { role: 'ai', content: matched.text }]
      this.setData({
        dialogMessages: messages,
        aiThinking: false,
        quickAnswers: matched.answers || []
      })
    }, 1000)
  },

  // 苏格拉底式对话脚本
  getDialogScript(topic) {
    const scripts = {
      'jiaohuan': [
        { role: 'ai', content: '🧐 我考考你：3 + 5 等于多少？', answers: ['8','等于8'] },
        { role: 'ai', content: '那 5 + 3 呢？', answers: ['也是8','8'] },
        { role: 'ai', content: '🤔 有意思吧？3+5和5+3结果一样。那你猜猜这是为什么？', answers: ['因为它们是一样的','因为交换了位置','不知道'] },
        { role: 'ai', content: '你说得对！交换了位置但结果不变。这就是我们今天要学的——加法交换律。

📝 **加法交换律**：两个数相加，交换加数的位置，和不变。

用字母表示就是：**a + b = b + a**', answers: ['明白了','举个例子','和我想的一样'] },
        { role: 'ai', content: '🎯 来试一个：23 + 45，如果交换位置变成 45 + 23，结果一样吗？', answers: ['一样','都是68','不一样'] }
      ],
      'fenpei': [
        { role: 'ai', content: '🍰 假设你请两个好朋友吃蛋糕，每人要吃5小块。

你需要准备多少小块蛋糕？', answers: ['10块','2×5=10','10'] },
        { role: 'ai', content: '没错！2个人 × 5块 = 10块。

但现在问题来了——你的朋友小明说他要巧克力和草莓两种口味，每种都要5块。那你需要准备多少块？', answers: ['10块','5+5=10','10'] },
        { role: 'ai', content: '对！巧克力5块 + 草莓5块 = 10块。

那如果是 **3个朋友**，每个人都要巧克力和草莓各5块呢？', answers: ['30块','3×10=30','3×(5+5)=30'] },
        { role: 'ai', content: '🎯 很好！3 × (5+5) = 3 × 10 = 30

也可以拆开算：3×5 + 3×5 = 15 + 15 = 30

两个算法结果一样！这就是**乘法分配律**！

📝 **(a+b)×c = a×c + b×c**

分配律就像发糖果——你可以先混在一起再分，也可以分开算再加起来。', answers: ['明白了','举个例子吧','好像有点懂了'] },
        { role: 'ai', content: '来挑战一个：💪 (10 + 2) × 5 = ？

两种方法算一下看看～', answers: ['先算10+2=12再×5=60','10×5+2×5=50+10=60','60'] }
      ]
    }
    return scripts[topic] || scripts['jiaohuan']
  },

  getResponses(topic) {
    const allResponses = {
      'jiaohuan': {
        '8|等于8': { text: '✅ 对！那如果我说 123 + 456 和 456 + 123，你觉得结果一样吗？', answers: ['一样','不一样','试试看'] },
        '明白了|懂了|知道': { text: '🎉 太好了！来个小挑战：用交换律，25 + 78 + 75 怎么算最方便？

💡 提示：看看哪两个数加在一起是整百？', answers: ['25+75=100再+78','100+78=178','不知道'] },
        '100|178': { text: '✅ 太棒了！25+75=100，再加78=178。用交换律把25和75凑在一起，算起来就快多了！', answers: ['再来一题','明白了'] },
        '68|都是68': { text: '🎯 完全正确！23+45=68，45+23=68。交换位置，和不变。这就是加法交换律。', answers: ['明白了','举个例子'] },
        '不一样': { text: '🤔 要不咱们验证一下？23+45=？ 45+23=？', answers: ['68','都是68'] }
      },
      'fenpei': {
        '30|30块|60|60块|3×10|3×(5+5)': { text: '✅ 非常棒！那换个角度：3个人各要5块巧克力 + 3个人各要5块草莓 = 3×5 + 3×5 = 15+15=30，结果一样！

这就是分配律的妙处——两条路都能走到终点。', answers: ['再试一题','有点意思'] },
        '10|10块|5+5': { text: '对！那如果是3个朋友呢？每个人都要两种口味各5块，一共多少？', answers: ['30块','3×10=30','3×(5+5)'] },
        '60|先算10+2=12再×5=60|10×5+2×5=50+10=60': { text: '🎯 完全正确！两种方法：
① (10+2)×5 = 12×5 = 60
② 10×5 + 2×5 = 50 + 10 = 60

结果一样！乘法分配律就是这么用的。', answers: ['再来一题','我试试难的'] }
      }
    }
    return allResponses[topic] || {}
  },

  getDefaultResponse(topic) {
    const defaults = {
      'jiaohuan': { text: '🤔 你再说说看，你觉得交换律为什么成立？举个例子试试～', answers: ['3+5=5+3','123+456=456+123'] },
      'chengfa-jiaohuan': { text: '🤔 想想看，2×3是2个3相加，3×2是3个2相加，结果都是6，对吧？那如果是7×8和8×7呢？', answers: ['都是56','不一样'] },
      'jiehe': { text: '🤔 (2+3)+7 = 5+7 = 12，2+(3+7) = 2+10 = 12，结果一样。你来解释一下为什么？', answers: ['因为加法顺序不影响结果','只是括号位置变了'] },
      'chengfa-jiehe': { text: '🤔 (2×3)×5 和 2×(3×5) 结果一样吗？', answers: ['一样，都是30','不一样'] },
      'fenpei': { text: '🤔 别着急，慢慢想。分配律其实就是"分别乘"再"加起来"。举个例子：妈妈给你和弟弟各买了3支笔和2个本子，你们每人花了多少钱？', answers: ['(3+2)×2=10','3×2+2×2=10'] }
    }
    return defaults[topic] || defaults['jiaohuan']
  }
})
