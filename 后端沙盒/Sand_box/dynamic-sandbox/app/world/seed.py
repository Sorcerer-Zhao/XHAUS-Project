# -*- coding: utf-8 -*-
"""种子数据 —— 构造一个"活"的初始世界。

在现有 3 份 mock JSON 基础上扩充，保证字段名 100% 对齐现有 skill 读法：
  - 餐厅：望京/三里屯/朝阳大悦城/国贸等商圈，含人均/标签/营业时间/highlights，
    并配演化隐藏状态（capacity/seats_free/base_popularity/turnover），让饭点能"涨满"。
  - 娱乐：电影场次 shows / 酒吧今晚活动 tonightEvent / 密室·剧本杀主题 themes /
    KTV 套餐 packages / 健身团课 classes / 公园(户外，雨天联动关闭)。
  - 区域：15 个商圈坐标 + 地铁站（与 mock-areas.json 一致，补全缺的）。
  - 天气：傍晚多云初值 + 3 日预报，trend=stable。

注意：本模块被 state.py 末尾 import；构造时 state.py 的 dataclass 已定义完毕，
不会循环依赖（build_world 在运行期才被调用）。
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime

from app import config


def _restaurants() -> dict:
    """餐厅种子（10 家来自现有 mock + 4 家扩充，覆盖多商圈与热门梯度）。

    每家附演化隐藏态：capacity 总桌数、seats_free 初始空桌、queue_waiting 初始排队、
    turnover_min_per_table 翻台分钟、base_popularity 热门度(0~1)。
    热门高 popularity 的店在饭点更易"有位→已满"，撑起 E3。
    """
    from app.world.state import Restaurant
    data = [
        # id, name, cuisine, area, address, rating, price, tags, openHours, phone, highlights,
        #   capacity, seats_free, queue_waiting, turnover_min, popularity
        ("r001", "金鲷居酒屋", "日料", "望京", "望京街9号望京国际商业中心B1", 4.7, 128,
         ["居酒屋", "刺身", "清酒"], "11:30-14:00, 17:00-22:00", "010-6471-XXXX",
         ["招牌三文鱼刺身拼盘", "自酿梅酒", "深夜食堂氛围"], 32, 8, 2, 9.0, 0.6),
        ("r002", "松子日本料理", "日料", "望京", "望京SOHO T1-B1-1205", 4.8, 168,
         ["omakase", "寿司", "会席料理"], "11:00-14:00, 17:00-21:30", "010-8472-XXXX",
         ["主厨 omakase 套餐", "北海道空运食材", "安静包间"], 20, 4, 5, 12.0, 0.7),
        ("r003", "村上一屋", "日料", "望京", "望京西园四区416号楼底商", 4.5, 82,
         ["拉面", "定食", "性价比"], "10:30-22:00", "010-6478-XXXX",
         ["豚骨拉面量大实惠", "午市定食套餐 58 元", "不用等位"], 40, 12, 0, 6.0, 0.35),
        ("r004", "海底捞火锅(望京店)", "火锅", "望京", "望京街10号望京SOHO T2-5F", 4.6, 135,
         ["火锅", "服务好", "夜宵"], "10:00-次日07:00", "010-6470-XXXX",
         ["服务体验天花板", "番茄锅底绝了", "生日有惊喜"], 60, 6, 12, 7.0, 0.92),
        ("r005", "西贝莜面村(望京凯德店)", "西北菜", "望京", "望京南湖东园122号凯德MALL 4F", 4.4, 95,
         ["西北菜", "亲子", "家常菜"], "10:30-21:30", "010-8472-XXXX",
         ["莜面鱼鱼必点", "儿童餐免费", "适合家庭聚餐"], 45, 10, 3, 6.5, 0.5),
        ("r006", "绿茶餐厅(三里屯店)", "杭帮菜", "三里屯", "三里屯路19号三里屯太古里南区S2-31", 4.3, 75,
         ["杭帮菜", "网红", "性价比"], "10:30-22:00", "010-6417-XXXX",
         ["绿茶烤鸡经典必点", "面包诱惑甜品", "排队名店"], 50, 5, 8, 6.0, 0.8),
        ("r007", "局气(三里屯店)", "北京菜", "三里屯", "工体北路8号院三里屯SOHO 5号商场B1", 4.5, 110,
         ["北京菜", "老北京", "创意菜"], "11:00-14:00, 17:00-22:00", "010-6501-XXXX",
         ["蜂窝煤炒饭出片", "铜锅涮肉地道", "京味儿十足"], 40, 9, 4, 7.5, 0.55),
        ("r008", "太二酸菜鱼(大悦城店)", "川菜", "朝阳大悦城", "朝阳北路101号朝阳大悦城7F", 4.4, 88,
         ["酸菜鱼", "排队王", "年轻人"], "10:30-22:00", "010-8558-XXXX",
         ["酸菜鱼只做一种", "超级下饭", "不拼桌不加位"], 48, 3, 15, 5.5, 0.9),
        ("r009", "喜茶·黑金店", "茶饮甜品", "三里屯", "三里屯太古里西区W7号", 4.2, 35,
         ["奶茶", "甜品", "下午茶"], "10:00-22:00", "010-6416-XXXX",
         ["多肉葡萄永远的神", "黑金店限定款", "拍照打卡"], 30, 8, 6, 4.0, 0.65),
        ("r010", "四季民福烤鸭(望京店)", "北京菜", "望京", "望京阜通东大街6号方恒购物中心4F", 4.7, 145,
         ["烤鸭", "北京必吃", "聚餐"], "11:00-14:30, 16:30-21:30", "010-8471-XXXX",
         ["烤鸭皮脆肉嫩", "可以看到长城的景观位", "芥末鸭掌开胃"], 44, 7, 7, 8.0, 0.78),
        # —— 扩充：覆盖国贸 / 中关村 / 簋街 / 五道口 ——
        ("r011", "鼎泰丰(国贸店)", "淮扬菜", "国贸", "国贸商城地下二层", 4.6, 160,
         ["小笼包", "精致", "商务"], "11:00-21:30", "010-8535-XXXX",
         ["黄金18褶小笼包", "服务细致", "商务宴请首选"], 38, 5, 6, 8.0, 0.72),
        ("r012", "胡大饭馆(簋街总店)", "川菜", "簋街", "东直门内大街233号", 4.5, 130,
         ["小龙虾", "夜宵", "麻辣"], "11:00-次日04:00", "010-6405-XXXX",
         ["麻辣小龙虾招牌", "深夜爆满", "啤酒小龙虾绝配"], 70, 4, 18, 6.0, 0.95),
        ("r013", "海归小馆(中关村店)", "融合菜", "中关村", "中关村大街11号e世界A座", 4.3, 78,
         ["创意菜", "聚会", "性价比"], "10:30-22:00", "010-8266-XXXX",
         ["孜然羊肉饭抢手", "适合学生聚会", "分量大"], 42, 11, 2, 6.0, 0.45),
        ("r014", "枣糕王·桃酥(五道口店)", "中式糕点", "五道口", "成府路华清嘉园底商", 4.4, 28,
         ["糕点", "排队", "伴手礼"], "08:00-20:00", "010-6277-XXXX",
         ["现烤枣糕排长队", "桃酥酥到掉渣", "学生最爱"], 20, 6, 5, 3.5, 0.7),
    ]
    out: dict = {}
    for (rid, name, cuisine, area, addr, rating, price, tags, hours, phone, hl,
         cap, free, qw, turnover, pop) in data:
        out[rid] = Restaurant(
            id=rid, name=name, cuisine=cuisine, area=area, address=addr,
            rating=rating, pricePerPerson=price, tags=tags, openHours=hours,
            phone=phone, highlights=hl, shows=None,
            capacity=cap, seats_free=free, queue_waiting=qw,
            turnover_min_per_table=turnover, is_full=(free == 0),
            base_popularity=pop,
        )
    return out


def _venues() -> dict:
    """娱乐场所种子（15 个，沿用 mock-entertainment.json 字段名）。

    park 类标记 is_outdoor=True，雨天联动关闭/降权；其余室内。
    rating_effective 初值 = rating（晴天）。
    """
    from app.world.state import Venue

    raw = [
        {
            "id": "e001", "name": "万达影城(三里屯店)", "type": "movie", "typeLabel": "🎬 电影",
            "area": "三里屯", "address": "三里屯路19号太古里北区N4-B1", "rating": 4.5,
            "priceRange": "55-128", "openHours": "09:00-次日01:00",
            "tags": ["IMAX", "杜比全景声", "夜场"],
            "shows": [
                {"movie": "星际迷航：新纪元", "time": "19:20", "endTime": "21:30", "price": 68, "hall": "IMAX厅", "rating": 8.7},
                {"movie": "疯狂动物城2", "time": "19:45", "endTime": "21:35", "price": 55, "hall": "3号厅", "rating": 8.2},
                {"movie": "流浪地球3", "time": "20:10", "endTime": "22:40", "price": 78, "hall": "杜比厅", "rating": 9.1},
                {"movie": "星际迷航：新纪元", "time": "21:50", "endTime": "00:00", "price": 58, "hall": "5号厅", "rating": 8.7},
                {"movie": "默杀2", "time": "22:00", "endTime": "23:50", "price": 48, "hall": "7号厅", "rating": 7.5},
            ],
        },
        {
            "id": "e002", "name": "Blue Note Beijing", "type": "bar", "typeLabel": "🎵 爵士酒吧",
            "area": "三里屯", "address": "三里屯南路27号", "rating": 4.7,
            "priceRange": "150-300", "openHours": "19:00-次日02:00",
            "tags": ["爵士", "现场演出", "鸡尾酒", "约会"],
            "highlights": ["每晚现场爵士乐演出", "招牌Old Fashioned", "氛围感拉满"],
            "tonightEvent": {"name": "Jazz Night — Trio Session", "time": "20:30", "coverCharge": 100},
        },
        {
            "id": "e003", "name": "唱吧麦颂(三里屯店)", "type": "ktv", "typeLabel": "🎤 KTV",
            "area": "三里屯", "address": "工体北路8号三里屯SOHO B1", "rating": 4.3,
            "priceRange": "80-200/人", "openHours": "12:00-次日06:00",
            "tags": ["KTV", "欢唱", "团建", "夜场"],
            "packages": [
                {"name": "欢唱2小时（小包）", "capacity": "2-4人", "price": 168, "period": "18:00-23:00"},
                {"name": "欢唱2小时（中包）", "capacity": "4-8人", "price": 268, "period": "18:00-23:00"},
                {"name": "夜场通宵（小包）", "capacity": "2-4人", "price": 298, "period": "23:00-06:00"},
            ],
        },
        {
            "id": "e004", "name": "CGV影城(望京店)", "type": "movie", "typeLabel": "🎬 电影",
            "area": "望京", "address": "望京阜通东大街6号方恒购物中心5F", "rating": 4.6,
            "priceRange": "50-120", "openHours": "09:30-次日00:30",
            "tags": ["4DX", "ScreenX", "杜比"],
            "shows": [
                {"movie": "流浪地球3", "time": "19:00", "endTime": "21:30", "price": 85, "hall": "4DX厅", "rating": 9.1},
                {"movie": "疯狂动物城2", "time": "19:30", "endTime": "21:20", "price": 50, "hall": "2号厅", "rating": 8.2},
                {"movie": "星际迷航：新纪元", "time": "20:00", "endTime": "22:10", "price": 60, "hall": "ScreenX厅", "rating": 8.7},
                {"movie": "默杀2", "time": "21:00", "endTime": "22:50", "price": 45, "hall": "4号厅", "rating": 7.5},
            ],
        },
        {
            "id": "e005", "name": "星聚会KTV(望京店)", "type": "ktv", "typeLabel": "🎤 KTV",
            "area": "望京", "address": "望京街9号望京国际商业中心3F", "rating": 4.4,
            "priceRange": "70-180/人", "openHours": "11:00-次日06:00",
            "tags": ["KTV", "网红", "高品质音响"],
            "packages": [
                {"name": "欢唱3小时（小包）", "capacity": "2-4人", "price": 198, "period": "18:00-23:00"},
                {"name": "欢唱3小时（中包）", "capacity": "4-8人", "price": 328, "period": "18:00-23:00"},
                {"name": "通宵畅唱（小包）", "capacity": "2-4人", "price": 258, "period": "23:00-06:00"},
            ],
        },
        {
            "id": "e006", "name": "X密室逃脱(三里屯旗舰店)", "type": "escape_room", "typeLabel": "🔐 密室逃脱",
            "area": "三里屯", "address": "工体北路甲2号盈科中心B1", "rating": 4.8,
            "priceRange": "128-198/人", "openHours": "10:00-23:00",
            "tags": ["密室", "沉浸式", "恐怖", "推理"],
            "themes": [
                {"name": "末日危途", "difficulty": "⭐⭐⭐⭐", "duration": "70分钟", "players": "4-6人", "price": 168, "genre": "科幻冒险", "availableSlots": ["19:00", "20:30"]},
                {"name": "午夜博物馆", "difficulty": "⭐⭐⭐", "duration": "60分钟", "players": "2-4人", "price": 138, "genre": "悬疑推理", "availableSlots": ["19:30", "21:00"]},
                {"name": "盗墓笔记·云顶天宫", "difficulty": "⭐⭐⭐⭐⭐", "duration": "90分钟", "players": "4-8人", "price": 198, "genre": "探险恐怖", "availableSlots": ["20:00"]},
            ],
        },
        {
            "id": "e007", "name": "望京公园", "type": "park", "typeLabel": "🌿 公园",
            "area": "望京", "address": "望京阜安西路", "rating": 4.2,
            "priceRange": "免费", "openHours": "06:00-22:00",
            "tags": ["散步", "免费", "夜景", "遛弯"],
            "highlights": ["湖边步道适合饭后散步", "夜间有灯光", "安静舒适"],
            "is_outdoor": True,
        },
        {
            "id": "e008", "name": "百丽宫影城(国贸店)", "type": "movie", "typeLabel": "🎬 电影",
            "area": "国贸", "address": "建国门外大街1号国贸商城B1", "rating": 4.7,
            "priceRange": "80-168", "openHours": "09:00-次日01:00",
            "tags": ["奢华", "真皮座椅", "VIP厅"],
            "shows": [
                {"movie": "流浪地球3", "time": "19:15", "endTime": "21:45", "price": 128, "hall": "VIP厅", "rating": 9.1},
                {"movie": "星际迷航：新纪元", "time": "20:30", "endTime": "22:40", "price": 98, "hall": "1号厅", "rating": 8.7},
                {"movie": "疯狂动物城2", "time": "21:00", "endTime": "22:50", "price": 80, "hall": "3号厅", "rating": 8.2},
            ],
        },
        {
            "id": "e009", "name": "猫眼剧本杀(望京店)", "type": "board_game", "typeLabel": "🎲 剧本杀",
            "area": "望京", "address": "望京西园三区310号底商", "rating": 4.5,
            "priceRange": "88-158/人", "openHours": "13:00-次日01:00",
            "tags": ["剧本杀", "推理", "社交", "沉浸式"],
            "themes": [
                {"name": "年轮", "difficulty": "⭐⭐⭐", "duration": "4小时", "players": "5-6人", "price": 128, "genre": "情感本"},
                {"name": "古木吟", "difficulty": "⭐⭐⭐⭐", "duration": "5小时", "players": "6-7人", "price": 158, "genre": "恐怖本"},
                {"name": "入梦", "difficulty": "⭐⭐", "duration": "3小时", "players": "4-5人", "price": 88, "genre": "欢乐本"},
            ],
        },
        {
            "id": "e010", "name": "SPARK PLUS酒吧", "type": "bar", "typeLabel": "🍸 酒吧",
            "area": "国贸", "address": "建外SOHO东区B座底商", "rating": 4.4,
            "priceRange": "100-250", "openHours": "18:00-次日02:00",
            "tags": ["鸡尾酒", "精酿", "氛围", "小酌"],
            "highlights": ["手工鸡尾酒", "露台位夜景很好", "适合小聚"],
            "tonightEvent": {"name": "Ladies Night 特调半价", "time": "21:00", "coverCharge": 0},
        },
        {
            "id": "e011", "name": "金逸影城(朝阳大悦城店)", "type": "movie", "typeLabel": "🎬 电影",
            "area": "朝阳大悦城", "address": "朝阳北路101号朝阳大悦城9F", "rating": 4.3,
            "priceRange": "45-98", "openHours": "09:00-次日00:00",
            "tags": ["性价比", "悦城会员折扣"],
            "shows": [
                {"movie": "流浪地球3", "time": "19:30", "endTime": "22:00", "price": 65, "hall": "巨幕厅", "rating": 9.1},
                {"movie": "疯狂动物城2", "time": "20:00", "endTime": "21:50", "price": 45, "hall": "1号厅", "rating": 8.2},
                {"movie": "默杀2", "time": "21:30", "endTime": "23:20", "price": 42, "hall": "5号厅", "rating": 7.5},
            ],
        },
        {
            "id": "e012", "name": "超级猩猩(朝阳大悦城店)", "type": "fitness", "typeLabel": "💪 健身",
            "area": "朝阳大悦城", "address": "朝阳北路101号朝阳大悦城4F", "rating": 4.6,
            "priceRange": "69-109/次", "openHours": "07:00-22:00",
            "tags": ["团课", "搏击", "瑜伽", "单次付费"],
            "classes": [
                {"name": "搏击操", "time": "19:30", "duration": "50分钟", "price": 89, "spotsLeft": 5},
                {"name": "瑜伽流", "time": "20:30", "duration": "60分钟", "price": 69, "spotsLeft": 8},
            ],
        },
        {
            "id": "e013", "name": "三里屯太古里", "type": "shopping", "typeLabel": "🛍️ 逛街",
            "area": "三里屯", "address": "三里屯路19号", "rating": 4.5,
            "priceRange": "免费（逛街）", "openHours": "10:00-22:00",
            "tags": ["购物", "网红", "拍照", "免费逛"],
            "highlights": ["潮牌聚集地", "网红打卡点多", "夜景氛围好"],
        },
        {
            "id": "e014", "name": "奇遇台球(望京店)", "type": "billiards", "typeLabel": "🎱 台球",
            "area": "望京", "address": "望京SOHO T1-B1-1108", "rating": 4.3,
            "priceRange": "50-80/小时", "openHours": "12:00-次日02:00",
            "tags": ["台球", "休闲", "小聚"],
            "highlights": ["环境好", "桌台新", "适合朋友小聚"],
        },
        {
            "id": "e015", "name": "朝阳公园", "type": "park", "typeLabel": "🌿 公园",
            "area": "朝阳公园", "address": "朝阳公园南路1号", "rating": 4.4,
            "priceRange": "¥5（门票）", "openHours": "06:00-21:00",
            "tags": ["户外", "湖景", "散步", "适合傍晚"],
            "highlights": ["湖边漫步", "夕阳很美", "大草坪可以坐坐"],
            "is_outdoor": True,
        },
    ]

    out: dict = {}
    for r in raw:
        v = Venue(
            id=r["id"], type=r["type"], typeLabel=r["typeLabel"], name=r["name"],
            area=r["area"], address=r["address"], rating=r["rating"],
            priceRange=r["priceRange"], openHours=r["openHours"], tags=r["tags"],
            shows=r.get("shows"), packages=r.get("packages"), themes=r.get("themes"),
            classes=r.get("classes"), highlights=r.get("highlights"),
            tonightEvent=r.get("tonightEvent"),
            is_outdoor=r.get("is_outdoor", False),
        )
        v.rating_effective = v.rating
        out[r["id"]] = v
    return out


def _areas() -> dict:
    """15 区域坐标 + 地铁站（对齐 mock-areas.json，补全 798）。"""
    from app.world.state import Area, Station

    raw = {
        "望京": (39.997, 116.474, [("望京站", ["14号线", "15号线"]), ("望京西站", ["13号线", "15号线"])]),
        "三里屯": (39.934, 116.454, [("团结湖站", ["10号线"]), ("东大桥站", ["6号线"])]),
        "朝阳大悦城": (39.924, 116.513, [("青年路站", ["6号线"])]),
        "国贸": (39.909, 116.461, [("国贸站", ["1号线", "10号线"]), ("大望路站", ["1号线", "14号线"])]),
        "中关村": (39.982, 116.311, [("中关村站", ["4号线"]), ("海淀黄庄站", ["4号线", "10号线"])]),
        "五道口": (39.993, 116.338, [("五道口站", ["13号线"])]),
        "朝阳公园": (39.942, 116.480, [("朝阳公园站", ["14号线"])]),
        "798": (39.983, 116.493, [("望京南站", ["14号线"])]),
        "簋街": (39.942, 116.418, [("北新桥站", ["5号线"]), ("雍和宫站", ["2号线", "5号线"])]),
        "前门": (39.900, 116.398, [("前门站", ["2号线"])]),
        "西单": (39.912, 116.375, [("西单站", ["1号线", "4号线"])]),
        "王府井": (39.915, 116.411, [("王府井站", ["1号线", "8号线"])]),
        "交通大学": (39.953, 116.340, [("西直门站", ["2号线", "4号线", "13号线"]), ("国家图书馆站", ["4号线", "9号线", "16号线"])]),
        "国际会议中心": (39.9937, 116.3893, [("奥林匹克公园站", ["8号线", "15号线"])]),
        "国家会议中心": (39.9937, 116.3893, [("奥林匹克公园站", ["8号线", "15号线"])]),
    }
    out: dict = {}
    for name, (lat, lon, stations) in raw.items():
        out[name] = Area(
            name=name, lat=lat, lon=lon,
            stations=[Station(name=sn, lines=sl) for sn, sl in stations],
        )
    return out


def _weather(rng: random.Random, sim_now: datetime) -> object:
    """天气初值：傍晚多云(code=2)，温度 ~24℃，trend=stable，3 日预报。"""
    from app.world.state import WeatherState

    code = 2  # 多云
    temp = 24.0
    humidity = 58
    wind = 12.0
    apparent = temp - 0.5
    d0 = sim_now.date()
    daily = []
    base_max, base_min, codes = [27.0, 29.0, 26.0], [19.0, 20.0, 18.0], [2, 80, 0]
    for i in range(3):
        day = d0.fromordinal(d0.toordinal() + i)
        daily.append({
            "date": day.isoformat(),
            "max": base_max[i],
            "min": base_min[i],
            "code": codes[i],
        })
    return WeatherState(
        temperature=temp, apparent_temperature=apparent, humidity=humidity,
        wind_speed=wind, weather_code=code, is_raining=(code in config.RAINY_CODES),
        daily=daily, trend="stable",
    )


def randomize_restaurant_states(world) -> None:
    """重置后为每家餐厅随机初始排队/空桌/临时打烊（rng 可 seed，同 seed 可复现）。"""
    wangjing = []
    for r in world.restaurants.values():
        pop = r.base_popularity
        r.temporarily_closed = world.rng.random() < config.RESTAURANT_TEMP_CLOSED_P

        p_full = config.RESTAURANT_INITIAL_FULL_P_BASE + pop * config.RESTAURANT_INITIAL_FULL_P_POP
        if world.rng.random() < p_full:
            r.seats_free = 0
            r.is_full = True
        else:
            cap_hi = max(1, int(r.capacity * (0.2 + (1.0 - pop) * 0.8)))
            r.seats_free = world.rng.randint(0, cap_hi)
            r.is_full = r.seats_free == 0

        if r.is_full:
            lo = max(1, int(2 + pop * 6))
            hi = int(5 + pop * config.RESTAURANT_QUEUE_MAX_MULT)
            r.queue_waiting = world.rng.randint(lo, max(lo, hi))
        else:
            r.queue_waiting = world.rng.randint(0, max(0, int(1 + pop * 14)))

        r._release_carry = 0.0
        if r.area == "望京":
            wangjing.append(r)

    # 望京至少 N 家有排队，避免演示时全是 0
    open_wj = [r for r in wangjing if not r.temporarily_closed]
    with_queue = [r for r in open_wj if r.queue_waiting > 0]
    need = config.WANGJING_MIN_QUEUE_RESTAURANTS - len(with_queue)
    if need > 0:
        candidates = [r for r in open_wj if r.queue_waiting == 0]
        world.rng.shuffle(candidates)
        for r in candidates[:need]:
            r.queue_waiting = world.rng.randint(4, 16)
            r.seats_free = 0
            r.is_full = True


def build_world(seed: int | None = None, randomize: bool | None = None):
    """构造并返回一个全新的 WorldState。

    seed: 传入则用确定性随机种子（同 seed 复盘同一随机世界，供 /admin/reset 复现 demo）。
    randomize: 是否为餐厅随机初始排队/营业态；默认读 config.RANDOMIZE_RESTAURANTS_ON_RESET。
    """
    from app.world.state import WorldState

    rng = random.Random(seed)
    sim_now = datetime.fromisoformat(config.SIM_START_ISO)
    do_randomize = config.RANDOMIZE_RESTAURANTS_ON_RESET if randomize is None else randomize

    w = WorldState(
        lock=asyncio.Lock(),
        rng=rng,
        sim_now=sim_now,
        time_scale=config.DEFAULT_TIME_SCALE,
        tick_seconds=config.TICK_SECONDS,
        tick_count=0,
        paused=False,
        restaurants=_restaurants(),
        venues=_venues(),
        areas=_areas(),
        weather=_weather(rng, sim_now),
        queue={},
        next_seq_per_rest={},
        events=[],
        event_seq=0,
        scripted_overrides={},
    )
    if do_randomize:
        randomize_restaurant_states(w)
    return w
