/**
 * 世界事件 → 用户提醒文案（管家心跳）
 * 仅格式化，不含业务逻辑
 */

const WATCHED_TYPES = new Set([
  'queue.threshold',
  'queue.called',
  'restaurant.full',
  'weather.changed',
  'venue.closed',
  'mobility.surge',
]);

function buildReminder(event) {
  const type = event.type;
  const subj = event.subject || {};
  const payload = event.payload || {};
  const base = event.message || '';

  switch (type) {
    case 'queue.threshold':
      return {
        text: base || `⏳ 排队号 ${payload.queue_code || subj.id} 前面只剩 ${payload.ahead ?? '?'} 桌，预计 ${payload.eta_min ?? '?'} 分钟。`,
        suggestedAction: '主动提醒用户准备出发；可询问是否帮忙规划出行（mobility-plan）或设进一步提醒。',
        urgency: 'high',
      };
    case 'queue.called':
      return {
        text: base || `🔔 排队号 ${payload.queue_code || subj.id} 已叫号，请尽快前往「${subj.name || '餐厅'}」就座！`,
        suggestedAction: '立即通知用户就座，语气简短紧迫。',
        urgency: 'critical',
      };
    case 'restaurant.full':
      return {
        text: base || `🍲「${subj.name || '餐厅'}」已满座${payload.queue_waiting != null ? `，当前排队 ${payload.queue_waiting} 桌` : ''}。`,
        suggestedAction: '建议改荐同区域其他餐厅（search-restaurants --sort wait）。',
        urgency: 'medium',
      };
    case 'weather.changed':
      if (payload.is_raining) {
        return {
          text: base || '🌧️ 天气变化：开始下雨了。',
          suggestedAction: '建议改室内娱乐（entertainment-query），出行优先地铁；打车可能加价。',
          urgency: 'high',
        };
      }
      return {
        text: base || '🌤️ 天气转晴，户外场所恢复可选。',
        suggestedAction: '可重新推荐户外公园等娱乐场所。',
        urgency: 'low',
      };
    case 'venue.closed':
      return {
        text: base || `🌿「${subj.name || '场所'}」因${payload.reason === 'rain' ? '降雨' : '运营调整'}暂不推荐。`,
        suggestedAction: '若用户原计划去此处，主动提供室内替代方案。',
        urgency: 'medium',
      };
    case 'mobility.surge':
      return {
        text: base || `🚕 打车需求上升，当前加价约 ${payload.surge ?? '?'}x。`,
        suggestedAction: '建议用户改乘地铁或预留更长的打车等待时间（mobility-plan）。',
        urgency: 'medium',
      };
    default:
      return null;
  }
}

function remindersFromEvents(events) {
  return events
    .filter((e) => WATCHED_TYPES.has(e.type))
    .map((e) => {
      const r = buildReminder(e);
      if (!r) return null;
      return {
        seq: e.seq,
        id: e.id,
        type: e.type,
        severity: e.severity,
        sim_time: e.sim_time,
        subject: e.subject,
        payload: e.payload,
        ...r,
      };
    })
    .filter(Boolean);
}

function summarizePoll({ newCount, reminders, latestSeq, since }) {
  if (newCount === 0) {
    return `管家心跳：无新事件（since=${since}，latest_seq=${latestSeq}）。无需主动打扰用户。`;
  }
  if (reminders.length === 0) {
    return `管家心跳：收到 ${newCount} 条世界事件，但无需要推送的类型（已更新 last_seq=${latestSeq}）。`;
  }
  const lines = reminders.map((r) => r.text);
  return [
    `管家心跳：发现 ${reminders.length} 条需主动提醒的事件（latest_seq=${latestSeq}）：`,
    ...lines,
    '请根据 suggestedAction 决定是否推送用户或调用其他 Skill。',
  ].join('\n');
}

module.exports = { WATCHED_TYPES, buildReminder, remindersFromEvents, summarizePoll };
