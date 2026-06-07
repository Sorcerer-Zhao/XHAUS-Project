/**
 * 对话历史存储服务
 * 文件存储位置: wx.env.USER_DATA_PATH + '/history/'
 * 文件名格式: YYYY-MM-DD_HH-mm-ss.json
 * 文件内容: { agent, agentName, summary, messages, endedAt }
 */

const HISTORY_DIR = 'history';

let _fs = null;
function getFs() {
  if (!_fs) {
    try {
      _fs = wx.getFileSystemManager();
    } catch (e) {
      console.warn('history: FileSystemManager not available', e);
      return null;
    }
  }
  return _fs;
}

function ensureDir() {
  const fs = getFs();
  if (!fs) return false;
  try {
    fs.accessSync(`${wx.env.USER_DATA_PATH}/${HISTORY_DIR}`);
    return true;
  } catch (e) {
    try {
      fs.mkdirSync(`${wx.env.USER_DATA_PATH}/${HISTORY_DIR}`, true);
      return true;
    } catch (e2) {
      return false;
    }
  }
}

function pad2(n) {
  return n < 10 ? '0' + n : '' + n;
}

function formatFileName(date) {
  const d = date || new Date();
  const Y = d.getFullYear();
  const M = pad2(d.getMonth() + 1);
  const D = pad2(d.getDate());
  const h = pad2(d.getHours());
  const m = pad2(d.getMinutes());
  const s = pad2(d.getSeconds());
  return `${Y}-${M}-${D}_${h}-${m}-${s}.json`;
}

/**
 * 保存一段对话到文件
 * @param {Object} param
 * @param {string} param.agent      - agent id (如 "main", "hausmeister")
 * @param {string} param.agentName  - agent 显示名 (如 "Shade", "Franziska")
 * @param {Array}  param.messages   - [{role, content}, ...]
 * @param {string} param.summary    - 对话摘要（首条用户消息）
 * @returns {string} fileName       - 保存的文件名
 */
function saveConversation({ agent, agentName, messages, summary }) {
  const fs = getFs();
  if (!fs) return null;
  if (!ensureDir()) return null;

  const msgs = (messages || []).filter(
    (m) => m.role && m.content && m.content.trim()
  );
  if (msgs.length === 0) return null;

  const now = new Date();
  const fileName = formatFileName(now);
  const filePath = `${wx.env.USER_DATA_PATH}/${HISTORY_DIR}/${fileName}`;

  const data = {
    agent: agent || 'unknown',
    agentName: agentName || agent || 'unknown',
    summary: summary || msgs[0]?.content?.slice(0, 60) || '空会话',
    messages: msgs,
    endedAt: now.toISOString(),
  };

  try {
    fs.writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf8');
    return fileName;
  } catch (err) {
    console.error('history_save_failed', err);
    return null;
  }
}

/**
 * 获取所有历史记录列表（按结束时间倒序，最新在上）
 * @returns {Array<{fileName, agent, agentName, summary, endedAt}>}
 */
function getHistoryList() {
  const fs = getFs();
  if (!fs) return [];
  if (!ensureDir()) return [];

  try {
    const files = fs.readdirSync(`${wx.env.USER_DATA_PATH}/${HISTORY_DIR}`);
    const jsonFiles = files.filter((f) => f.endsWith('.json')).sort().reverse();

    const list = [];
    for (const fileName of jsonFiles) {
      try {
        const raw = fs.readFileSync(
          `${wx.env.USER_DATA_PATH}/${HISTORY_DIR}/${fileName}`,
          'utf8'
        );
        const data = JSON.parse(raw);
        list.push({
          fileName,
          agent: data.agent || 'unknown',
          agentName: data.agentName || data.agent || 'unknown',
          summary: data.summary || '空会话',
          endedAt: data.endedAt || '',
          messageCount: (data.messages || []).length,
        });
      } catch (e) {
        // skip corrupted files
      }
    }

    return list;
  } catch (err) {
    console.error('history_list_failed', err);
    return [];
  }
}

/**
 * 加载某条历史记录的完整消息
 * @param {string} fileName
 * @returns {{ agent, agentName, messages, summary, endedAt } | null}
 */
function loadConversation(fileName) {
  const fs = getFs();
  if (!fs) return null;
  if (!ensureDir()) return null;

  try {
    const raw = fs.readFileSync(
      `${wx.env.USER_DATA_PATH}/${HISTORY_DIR}/${fileName}`,
      'utf8'
    );
    return JSON.parse(raw);
  } catch (err) {
    console.error('history_load_failed', err);
    return null;
  }
}

/**
 * 删除一条历史记录
 * @param {string} fileName
 */
function deleteConversation(fileName) {
  const fs = getFs();
  if (!fs) return false;
  try {
    fs.unlinkSync(`${wx.env.USER_DATA_PATH}/${HISTORY_DIR}/${fileName}`);
    return true;
  } catch (err) {
    console.error('history_delete_failed', err);
    return false;
  }
}

/**
 * 删除所有历史记录
 */
function clearAll() {
  const fs = getFs();
  if (!fs) return;
  if (!ensureDir()) return;
  try {
    const files = fs.readdirSync(`${wx.env.USER_DATA_PATH}/${HISTORY_DIR}`);
    for (const f of files) {
      try {
        fs.unlinkSync(`${wx.env.USER_DATA_PATH}/${HISTORY_DIR}/${f}`);
      } catch (e) {
        // skip
      }
    }
  } catch (err) {
    console.error('history_clear_failed', err);
  }
}

module.exports = {
  saveConversation,
  getHistoryList,
  loadConversation,
  deleteConversation,
  clearAll,
};
