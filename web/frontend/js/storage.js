/* ========================================
   Echoes · 往事可追忆
   数据存储模块 (localStorage + 云端同步预备)
   ======================================== */

const Storage = {
  // 本地存储键名
  KEY: 'echoes_data',

  // 初始化
  init() {
    if (!localStorage.getItem(this.KEY)) {
      const defaultData = {
        stories: [],
        albums: [],
        user: null,
        settings: {
          elderMode: false
        }
      };
      this.save(defaultData);
    }

    // 添加演示数据（首次使用时）
    const data = this.load();
    if (data.stories.length === 0 && !localStorage.getItem('echoes_sample_loaded')) {
      this.loadSampleData();
      localStorage.setItem('echoes_sample_loaded', 'true');
    }
  },

  // 加载数据
  load() {
    try {
      return JSON.parse(localStorage.getItem(this.KEY)) || this.getDefault();
    } catch {
      return this.getDefault();
    }
  },

  // 保存数据
  save(data) {
    localStorage.setItem(this.KEY, JSON.stringify(data));
  },

  // 默认数据结构
  getDefault() {
    return {
      stories: [],
      albums: [],
      user: null,
      settings: { elderMode: false }
    };
  },

  // === 故事管理 ===

  getAllStories() {
    return this.load().stories;
  },

  getStory(id) {
    return this.load().stories.find(s => s.id === id);
  },

  addStory(story) {
    const data = this.load();
    const newStory = {
      id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
      date: story.date || new Date().toISOString().split('T')[0],
      era: story.era || '',
      content: story.content || '',
      type: story.type || 'self', // self | interview | text
      photos: story.photos || [],
      audioUrl: story.audioUrl || null,
      parentStory: story.parentStory || null,
      isSubStory: story.isSubStory || false,
      tags: story.tags || [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    data.stories.unshift(newStory);
    this.save(data);
    return newStory;
  },

  updateStory(id, updates) {
    const data = this.load();
    const idx = data.stories.findIndex(s => s.id === id);
    if (idx === -1) return null;
    data.stories[idx] = { ...data.stories[idx], ...updates, updatedAt: new Date().toISOString() };
    this.save(data);
    return data.stories[idx];
  },

  deleteStory(id) {
    const data = this.load();
    data.stories = data.stories.filter(s => s.id !== id);
    this.save(data);
  },

  getStoriesByEra(era) {
    return this.load().stories.filter(s => s.era === era);
  },

  getSubStories(parentId) {
    return this.load().stories.filter(s => s.parentStory === parentId);
  },

  // === 画册管理 ===

  getAlbums() {
    return this.load().albums;
  },

  createAlbum(name) {
    const data = this.load();
    const album = {
      id: Date.now().toString(36),
      name: name || '我的回忆画册',
      pages: [],
      createdAt: new Date().toISOString()
    };
    data.albums.push(album);
    this.save(data);
    return album;
  },

  generateAlbumFromStories(storyIds) {
    const data = this.load();
    const selectedStories = data.stories.filter(s => storyIds.includes(s.id));
    selectedStories.sort((a, b) => a.date.localeCompare(b.date));

    const pages = selectedStories.map(story => ({
      storyId: story.id,
      photo: story.photos[0] || null,
      text: story.content,
      date: story.date,
      era: story.era
    }));

    const album = {
      id: Date.now().toString(36),
      name: '我的回忆画册',
      pages,
      createdAt: new Date().toISOString()
    };
    data.albums.push(album);
    this.save(data);
    return album;
  },

  // === 设置 ===

  getSetting(key) {
    return this.load().settings[key];
  },

  setSetting(key, value) {
    const data = this.load();
    data.settings[key] = value;
    this.save(data);
  },

  // === 演示数据 ===
  loadSampleData() {
    const samples = [
      {
        date: '1965-09-01',
        era: '童年',
        content: '记得我六岁那年的夏天，和小伙伴们在村口的大榕树下捉迷藏。那棵榕树好大好大，树荫能遮住半个院子。我们光着脚丫在泥地里跑，浑身脏兮兮的，但那时候真开心啊。',
        type: 'self',
        tags: ['童年', '小伙伴']
      },
      {
        date: '1978-06-15',
        era: '求学',
        content: '高考那天早上，我妈给我煮了两个鸡蛋一根油条，说是能考100分。我到现在还记得她站在门口目送我走出去的样子。那时候觉得理所当然，现在想起来，眼眶都是热的。',
        type: 'self',
        tags: ['高考', '母亲']
      },
      {
        date: '1985-03-20',
        era: '工作',
        content: '第一天上班，紧张得连路都不会走了。分到一个老车间，师傅姓王，是个很严肃的人。但他教了我很多，到现在我工作中很多习惯都是那时候养成的。',
        type: 'interview',
        tags: ['第一份工作', '师傅']
      },
      {
        date: '1989-10-01',
        era: '成家',
        content: '结婚那天，她穿着红色的旗袍，在酒店门口等我。我紧张得差点把戒指掉在地上。三十年过去了，现在每天看到她还是觉得很幸福。',
        type: 'self',
        tags: ['结婚', '感情']
      },
      {
        date: '2000-08-12',
        era: '养育',
        content: '送女儿去大学报到，帮她铺好床铺，整理好行李。要走的时候她突然拉住我的手说"爸，我会想你的"。我转身快步走出宿舍，泪就下来了。',
        type: 'interview',
        tags: ['女儿', '大学']
      }
    ];

    samples.forEach(s => this.addStory(s));
  }
};
