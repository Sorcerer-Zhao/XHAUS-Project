/** 各 Skill 的自然语言摘要生成（纯格式化，无业务逻辑） */

function summarizeRestaurants(result) {
  const { restaurants = [], count = 0, total, hint, sim_now } = result;
  if (!restaurants.length) {
    return hint || '没有找到符合条件的餐厅，建议放宽区域、菜系或预算。';
  }
  const lines = restaurants.slice(0, 5).map((r, i) => {
    if (r.isOpen === false) {
      const why = r.closedReason || '未营业';
      return `${i + 1}. ${r.name} ⭐${r.rating} 人均¥${r.pricePerPerson} 【${why}】`;
    }
    const wait = r.waitInfo || {};
    const w = wait.currentWait ?? 0;
    const full = r.isFull ? '【已满】' : w === 0 ? '【有位】' : `排队${w}桌`;
    return `${i + 1}. ${r.name} ⭐${r.rating} 人均¥${r.pricePerPerson} ${full}`;
  });
  const head = `为你找到 ${count}${total && total > count ? `/${total}` : ''} 家餐厅` +
    (sim_now ? `（世界时间 ${sim_now}）` : '') + '：';
  const tail = hint ? `提示：${hint}` : '想去哪家？我可以帮你排号。';
  return [head, ...lines, tail].join('\n');
}

function summarizeQueueTake(ticket, data) {
  const t = ticket || {};
  const name = t.restaurant || data.restaurant || '餐厅';
  const code = t.queueCode || data.queue_code;
  const ahead = t.aheadCount ?? data.ahead ?? 0;
  const eta = t.estimatedMinutes ?? data.eta_min ?? 0;
  const call = t.estimatedCallTime || data.estimated_call_time || '';
  return `已在「${name}」取号成功。排队号 ${code}，前面 ${ahead} 桌，预计 ${eta} 分钟${call ? `（约 ${call} 叫号）` : ''}。`;
}

function summarizeQueueStatus(ticket, data) {
  const t = ticket || {};
  const code = t.queueCode || data.queue_code;
  const text = t.statusText || data.status_text || data.status;
  const ahead = t.aheadCount ?? data.ahead;
  const eta = t.estimatedMinutes ?? data.eta_min;
  if (data.status === 'called' || /叫号/.test(String(text))) {
    return `排队号 ${code} 已叫号，请尽快前往「${t.restaurant || data.restaurant}」就座。`;
  }
  if (text && String(text).includes('前面')) {
    return `排队号 ${code}：${text}，预计 ${eta} 分钟。`;
  }
  return `排队号 ${code}：${text || '排队中'}。前面还有 ${ahead} 桌，预计 ${eta} 分钟。`;
}

function summarizeQueueCancel(data) {
  return data.message || `排队号 ${data.queue_code} 已取消。`;
}

function summarizeWeather(w) {
  const cur = w.current || w.summary || {};
  const area = w.area || '全城';
  const temp = cur.temperature_2m ?? w.summary?.temperature;
  const feel = cur.apparent_temperature ?? w.summary?.apparent;
  const label = w.summary?.weather_label || '未知';
  const rain = w.is_raining ? '，正在下雨' : '';
  const sim = w.sim_now ? `（世界时间 ${w.sim_now}）` : '';
  return `${area} 当前${label}，${temp}°C（体感 ${feel}°C）${rain}${sim}。`;
}

function summarizeMobility(plan) {
  if (!plan.success) return plan.error || '出行规划失败';
  if (plan.sameArea) return plan.message || `${plan.from} 与 ${plan.to} 在同一区域，步行即可。`;
  const rec = plan.recommended || plan.plans?.[0]?.mode;
  const dist = plan.distance || '';
  const weather = plan.weatherNote ? ` ${plan.weatherNote}` : '';
  const alt = (plan.plans || []).slice(0, 3).map((p) => `${p.mode} ${p.duration} ${p.cost}`).join('；');
  return `从 ${plan.from} 到 ${plan.to}${dist ? `（${dist}）` : ''}，推荐 ${rec}。${alt}${weather}`;
}

function summarizeEntertainment(result) {
  const { venues = [], count = 0, weatherNote, sim_now } = result;
  if (!venues.length) {
    return result.hint || '没找到合适的娱乐活动，建议放宽时间、预算或换区域。';
  }
  const lines = venues.slice(0, 5).map((v, i) =>
    `${i + 1}. ${v.name} ${v.typeLabel || v.type} ⭐${v.rating} ${v.priceRange || ''}`
  );
  const head = `找到 ${count} 个娱乐活动` + (sim_now ? `（世界时间 ${sim_now}）` : '') + '：';
  const parts = [head, ...lines];
  if (weatherNote) parts.push(`天气提示：${weatherNote}`);
  parts.push('想了解哪家详情或需要我帮你规划过去？');
  return parts.join('\n');
}

module.exports = {
  summarizeRestaurants,
  summarizeQueueTake,
  summarizeQueueStatus,
  summarizeQueueCancel,
  summarizeWeather,
  summarizeMobility,
  summarizeEntertainment,
};
