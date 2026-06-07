#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态模拟沙盒后端 · 一键演示客户端 (demo_client.py)

把"活着的世界"演给评委看：顺序调用关键端点，讲一条完整故事——
  加速时钟 → 搜餐厅(看当前有位) → 取号 → 注入下雨
  → 轮询事件流(看连锁: 公园关 / 打车涨 / 餐厅满)
  → 轮询排队进度(看 ahead 自己递减到剩 N 桌 / 叫号)
  → 查出行 ETA(看雨天联动后变化) → 一键复位

仅依赖 Python 标准库 (urllib)，无需 pip 安装任何东西。
先确保后端已在 8787 启动，再运行：
    cd dynamic-sandbox && python3 demo_client.py

可选参数：
    --base   后端地址 (默认 http://127.0.0.1:8787)
    --scale  世界倍速 (默认 30)
    --no-reset  跑完不重置世界
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ── 终端配色（无色终端会自动忽略转义，不影响内容）──
C_TITLE = "\033[1;36m"   # 青色加粗：章节标题
C_NARR = "\033[0;33m"    # 黄色：旁白
C_KEY = "\033[1;32m"     # 绿色：关键数据
C_DIM = "\033[2m"        # 暗色：原始 JSON 摘要
C_ERR = "\033[1;31m"     # 红色：错误
C_RST = "\033[0m"


def c(color: str, text: str) -> str:
    return f"{color}{text}{C_RST}"


class Sandbox:
    """对沙盒后端的极简 HTTP 客户端（标准库实现）。"""

    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def _request(self, method: str, path: str, params=None, body=None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                return {"_http_status": e.code, **json.loads(raw)}
            except Exception:
                return {"_http_status": e.code, "_raw": raw}
        except urllib.error.URLError as e:
            raise SystemExit(
                c(C_ERR, f"\n[连接失败] 无法连到 {url}\n"
                         f"  原因: {e.reason}\n"
                         f"  请先启动后端: bash run.sh  (端口 8787)\n")
            )

    def get(self, path, **params):
        return self._request("GET", path, params=params or None)

    def post(self, path, body=None):
        return self._request("POST", path, body=body or {})


# ── 输出小工具 ──
def section(n, title):
    print()
    print(c(C_TITLE, f"━━━ 第 {n} 幕 · {title} ━━━"))


def narrate(text):
    print(c(C_NARR, f"  💬 {text}"))


def kv(label, value):
    print(f"     {label}: {c(C_KEY, str(value))}")


def dim_json(obj, limit=3):
    """打印一个对象的精简摘要（避免刷屏）。"""
    s = json.dumps(obj, ensure_ascii=False)
    if len(s) > 300:
        s = s[:300] + " …"
    print(c(C_DIM, f"     ↳ {s}"))


def poll(label, n, interval):
    """打印轮询进度提示，并 sleep。"""
    print(c(C_DIM, f"     ⏳ {label}（第 {n} 次轮询，{interval}s 后再看世界）"))
    time.sleep(interval)


def main():
    ap = argparse.ArgumentParser(description="动态沙盒后端 · 一键演示客户端")
    ap.add_argument("--base", default="http://127.0.0.1:8787", help="后端地址")
    ap.add_argument("--scale", type=float, default=30.0, help="世界倍速 (默认 30)")
    ap.add_argument("--no-reset", action="store_true", help="跑完不重置世界")
    args = ap.parse_args()

    sb = Sandbox(args.base)

    print(c(C_TITLE, "\n╔══════════════════════════════════════════════════╗"))
    print(c(C_TITLE,   "║   全天候私人管家 · 动态沙盒  一键故事演示          ║"))
    print(c(C_TITLE,   "╚══════════════════════════════════════════════════╝"))

    # ── 第 0 幕：确认世界在线 + 后台时钟在跑 ──
    section(0, "确认世界在线（后台时钟应在自己跳动）")
    root = sb.get("/")
    narrate("先 ping 一下世界，确认它是『活的』。")
    kv("服务", root.get("service", "?"))
    kv("世界时间 sim_now", root.get("sim_now", "?"))
    kv("初始 tick_count", root.get("tick_count", "?"))
    kv("当前天气", root.get("weather", {}))
    t1 = root.get("tick_count", 0)
    time.sleep(2)
    t2 = sb.get("/").get("tick_count", 0)
    if t2 > t1:
        narrate(f"2 秒后 tick_count 从 {t1} 涨到了 {t2} —— 后台时钟确实在主动推进世界（E2）。")
    else:
        narrate("（tick_count 暂未增长，可能世界被暂停了，继续演示。）")

    # ── 第 1 幕：加速时钟 ──
    section(1, "加速时钟：30 秒看完 10 分钟演化")
    narrate(f"把世界提速到 {args.scale}x，让 10 分钟的演化在几十秒内看完。")
    r = sb.post("/admin/clock", {"time_scale": args.scale})
    kv("time_scale", r.get("time_scale"))
    kv("说明", r.get("note", ""))

    # ── 第 2 幕：搜餐厅 ──
    section(2, "搜餐厅：看望京现在哪家有位")
    narrate("用户说想在望京吃饭，按等位排序看看。")
    res = sb.get("/restaurants", area="望京", sort="wait", limit=5)
    kv("命中家数", f"{res.get('count')} / 共 {res.get('total', res.get('count'))}")
    target_id = None
    for item in res.get("restaurants", []):
        wait = item.get("waitInfo", {})
        full = item.get("isFull")
        line = (f"{item.get('name')}  评分{item.get('rating')}  "
                f"人均¥{item.get('pricePerPerson')}  "
                f"排队{wait.get('currentWait')}桌/约{wait.get('avgWaitMinutes')}分  "
                f"{'【已满】' if full else '【有位】'}")
        print(f"     • {c(C_KEY, line)}")
        # 优先挑 r004（海底捞）当取号目标；否则挑第一个
        if item.get("id") == "r004":
            target_id = "r004"
    if not target_id and res.get("restaurants"):
        target_id = res["restaurants"][0]["id"]
    target_id = target_id or "r004"
    narrate(f"就帮用户在『{target_id}』取个号（热门火锅，最能体现排队演化）。")

    # ── 第 3 幕：取号 ──
    section(3, "取号：拿到排队票，后台会自己推进它")
    take = sb.post("/queue/take", {"restaurant_id": target_id, "people": 2, "customer_name": "宋先生"})
    queue_code = take.get("queue_code")
    if not take.get("success", True) or not queue_code:
        narrate(f"取号失败：{take.get('error', take)}，改用 r004 再试。")
        take = sb.post("/queue/take", {"restaurant_id": "r004", "people": 2, "customer_name": "宋先生"})
        queue_code = take.get("queue_code")
    kv("排队号 queue_code", queue_code)
    kv("餐厅", take.get("restaurant"))
    kv("前面还有", f"{take.get('ahead')} 桌")
    kv("预计等待", f"{take.get('eta_min')} 分钟")
    kv("预计叫号时间", take.get("estimated_call_time"))
    for tip in take.get("tips", []):
        print(c(C_DIM, f"       {tip}"))

    # ── 第 4 幕：注入下雨（E6 连锁的导火索）──
    section(4, "注入下雨：一条命令引发全世界连锁反应（E6）")
    narrate("演示控场：让天立刻下雨，看世界各模块如何联动。")
    before_events = sb.get("/events", since=0, limit=1)
    last_seq = before_events.get("latest_seq", 0)
    rain = sb.post("/admin/inject", {"kind": "rain"})
    kv("下雨注入", "成功" if rain.get("success") else rain.get("error"))
    wx = sb.get("/weather", area="望京")
    cur = wx.get("current", {})
    kv("当前 weather_code", cur.get("weather_code"))
    kv("is_raining", wx.get("is_raining"))
    kv("气温", f"{cur.get('temperature_2m')}℃（体感 {cur.get('apparent_temperature')}℃）")

    # ── 第 5 幕：轮询事件流，看连锁 ──
    section(5, "轮询事件流：看世界自己产生连锁事件（任务③）")
    narrate(f"管家心跳从 seq>{last_seq} 增量拉取事件，看下雨引发了什么。")
    seen_types = set()
    for i in range(1, 7):
        ev = sb.get("/events", since=last_seq, limit=50)
        for e in ev.get("events", []):
            seen_types.add(e.get("type"))
            sev = e.get("severity", "info")
            mark = {"alert": "🚨", "notice": "🔔", "info": "·"}.get(sev, "·")
            print(f"     {mark} [{c(C_KEY, e.get('type'))}] {e.get('message')}")
        last_seq = ev.get("latest_seq", last_seq)
        # 攒够典型连锁就提前结束
        if {"weather.changed", "venue.closed", "mobility.surge"} <= seen_types:
            narrate("已看到连锁：下雨 → 公园关 → 打车加价（再等等还会有餐厅满座）。")
            # 再多看一轮，争取抓到 restaurant.full
            poll("等热门店被雨天挤满", i, 3)
            ev = sb.get("/events", since=last_seq, limit=50)
            for e in ev.get("events", []):
                sev = e.get("severity", "info")
                mark = {"alert": "🚨", "notice": "🔔", "info": "·"}.get(sev, "·")
                print(f"     {mark} [{c(C_KEY, e.get('type'))}] {e.get('message')}")
            last_seq = ev.get("latest_seq", last_seq)
            break
        poll("等世界演化出更多事件", i, 3)

    # ── 第 6 幕：轮询排队进度，看 ahead 自己递减 ──
    section(6, "轮询排队进度：ahead 由后台 tick 主动递减")
    narrate(f"不手动改，纯靠世界自己推进，看『{queue_code}』排到剩几桌。")
    threshold_hit = False
    for i in range(1, 9):
        st = sb.get("/queue/status", queue_code=queue_code)
        if not st.get("success", True):
            narrate(f"查询排队失败：{st.get('error')}")
            break
        status = st.get("status")
        ahead = st.get("ahead")
        eta = st.get("eta_min")
        print(f"     第{i}次 → 状态={c(C_KEY, str(status))}  前面={c(C_KEY, str(ahead))}桌  "
              f"预计{c(C_KEY, str(eta))}分  「{st.get('status_text', '')}」")
        if status == "called":
            narrate("🔔 已叫号！管家此刻应主动通知用户『可以就座了』（任务③闭环）。")
            break
        if isinstance(ahead, int) and ahead <= 5 and not threshold_hit:
            threshold_hit = True
            narrate("⚠️ 前面只剩 ≤5 桌！这正是 queue.threshold 事件，管家该提醒/叫车了。")
        poll("等后台把排队往前推", i, 3)
    else:
        narrate("（轮询结束仍在排队中，可用 /admin/inject queue_called 现场强制叫号兜底。）")

    # ── 第 7 幕：查出行 ETA，看雨天联动 ──
    section(7, "查出行 ETA：雨天打车加价 + ETA 变长（E6）")
    narrate("用户要从望京去三里屯，看雨天对出行方案的真实影响。")
    plan = sb.get("/mobility/plan", **{"from": "望京", "to": "三里屯"})
    if plan.get("success", True):
        kv("距离", plan.get("distance"))
        kv("推荐", plan.get("recommended"))
        if plan.get("weatherNote"):
            kv("天气提示", plan.get("weatherNote"))
        for p in plan.get("plans", []):
            extra = ""
            if p.get("surge"):
                extra = c(C_ERR, f"  加价{p.get('surge')}x")
            print(f"     • {c(C_KEY, p.get('mode'))}  {p.get('duration')}  {p.get('cost')}{extra}")
    else:
        narrate(f"出行查询失败：{plan.get('error')}")

    # ── 第 8 幕：复位 ──
    section(8, "一键复位：便于反复演示")
    if args.no_reset:
        narrate("已加 --no-reset，保留当前世界状态，可去 /docs 继续把玩。")
    else:
        rs = sb.post("/admin/reset", {"seed": 42})
        kv("复位", "成功" if rs.get("success") else rs)
        kv("新 sim_now", rs.get("sim_now"))
        narrate("世界已回到初始（seed=42，可复现同一随机世界）。可以再演一遍。")

    print(c(C_TITLE, "\n✅ 演示故事讲完。世界一直在后台自己运行——你只是去观测了它几次。\n"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(c(C_ERR, "\n[已中断]"))
        sys.exit(130)
