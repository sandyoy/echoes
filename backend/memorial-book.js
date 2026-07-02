// ==========================================
//  Echoes 纪念册生成模块
//  从 stories 数据生成纪念册排版数据
//  ==========================================

const path = require('path');
const fs = require('fs');

/**
 * 从 stories 数据生成纪念册数据
 * @param {Array} stories - 故事列表
 * @param {Object} options - 配置项
 * @returns {Object} - 纪念册数据
 */
function generateBookData(stories, options = {}) {
  const sorted = [...(stories || [])].sort((a, b) => {
    return (a.date || '').localeCompare(b.date || '');
  });

  return {
    title: options.title || '往事可追忆',
    subtitle: 'ECHOES · MEMORY ALBUM',
    author: options.author || '',
    createdAt: new Date().toISOString(),
    totalStories: sorted.length,
    pages: sorted.map(story => ({
      date: story.date || story.ts || '',
      era: story.era || (story.tags && story.tags[0]) || '',
      content: story.content || '',
      type: story.type || 'text',
      photos: story.photos || [],
      tags: story.tags || [],
    })),
  };
}

/**
 * 编码数据为 URL 安全字符串（用于嵌入翻页书页面）
 */
function encodeBookData(bookData) {
  const json = JSON.stringify(bookData);
  return Buffer.from(json).toString('base64');
}

module.exports = { generateBookData, encodeBookData };
