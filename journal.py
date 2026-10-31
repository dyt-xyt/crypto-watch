# -*- coding: utf-8 -*-
"""信号纸面交易账本 —— 记录每条建议, 并在 30m/1h/4h/12h/24h 后回测结果"""
import json, os, time, urllib.request
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "trades.json")
CN = timezone(timedelta(hours=8))

HORIZONS = [("30m", 1800), ("1h", 3600), ("4h", 14400),
            ("12h", 43200), ("24h", 86400)]


def _load():
    if os.path.exists(FILE):
        try:
            with open(FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save(t):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(t, f, ensure_ascii=False, indent=1)


def _get(url, n=4):
    for i in range(n):
        try:
            r = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                     "Connection": "close"})
            with urllib.request.urlopen(r, timeout=20) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            if i == n - 1:
                raise
            time.sleep(2)


def record(sym, title, reason, meta):
    """把一条带方向的建议写进账本"""
    if not meta:
        return
    t = _load()
    t.append({
        "id": f"{int(time.time()*1000)}-{sym}",
        "ts": int(time.time()),
        "time": datetime.now(CN).strftime("%m-%d %H:%M"),
        "symbol": sym,
        "side": meta["side"],
        "entry": meta["entry"],
        "stop": meta["stop"],
        "tp1": meta["tp1"],
        "tp2": meta["tp2"],
        "risk_pct": meta.get("risk_pct", 0),
        "title": title,
        "reason": reason or "",
        "ret": {}
    })
    _save(t[-400:])


def _price_at(sym, t0, t1):
    """取 t0 之后、t1 之前的 1 分钟 K 线, 用于判断先到止损还是止盈"""
    url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}"
           f"&interval=1m&startTime={int(t0*1000)}&limit=1500")
    try:
        return _get(url)
    except Exception:
        return []


def update(now=None):
    """为到期的持仓计算各周期收益, 返回新完成的条数"""
    now = now or time.time()
    t = _load()
    done = 0
    for tr in t:
        pending = [h for h, _ in HORIZONS
                   if h not in tr["ret"] and now >= tr["ts"] + dict(HORIZONS)[h]]
        if not pending:
            continue
        ks = _price_at(tr["symbol"], tr["ts"], now)
        if not ks:
            continue
        long = tr["side"] > 0
        p0 = tr["entry"]
        for h, sec in HORIZONS:
            if h in tr["ret"] or now < tr["ts"] + sec:
                continue
            cut = tr["ts"] + sec
            stop_hit = tp_hit = None
            last_close = None
            for k in ks:
                ts = int(k[0]) / 1000
                if ts >= cut:
                    break
                hi, lo, cl = float(k[2]), float(k[3]), float(k[4])
                last_close = cl
                if stop_hit is None and tp_hit is None:
                    hit_stop = (lo <= tr["stop"]) if long else (hi >= tr["stop"])
                    hit_tp = (hi >= tr["tp1"]) if long else (lo <= tr["tp1"])
                    if hit_stop and hit_tp:
                        stop_hit = ts          # 同根K线无法判断顺序, 保守算止损
                    elif hit_stop:
                        stop_hit = ts
                    elif hit_tp:
                        tp_hit = ts
            if last_close is None:
                continue
            if stop_hit:
                r = -abs(tr["stop"] - p0) / p0 * 100
                flag = "止损"
            elif tp_hit:
                r = abs(tr["tp1"] - p0) / p0 * 100
                flag = "止盈1"
            else:
                r = (last_close / p0 - 1) * 100 * (1 if long else -1)
                flag = "持有"
            tr["ret"][h] = {"ret": round(r, 2), "flag": flag, "px": round(last_close, 2)}
            done += 1
    if done:
        _save(t)
    return done


def daily_report(hours=24):
    """生成最近 N 小时的汇总"""
    t = _load()
    now = time.time()
    recent = [x for x in t if now - x["ts"] <= hours * 3600]
    if not recent:
        return None
    L = [f"近 {hours} 小时共 {len(recent)} 条带方向信号", ""]
    stat = {h: [] for h, _ in HORIZONS}
    stops = tps = 0
    for x in recent:
        d = "多" if x["side"] > 0 else "空"
        L.append(f"{x['time']} {x['symbol'].replace('USDT','')} {d} @{x['entry']:,.2f}")
        row = []
        for h, _ in HORIZONS:
            v = x["ret"].get(h)
            if not v:
                row.append(f"{h}:—")
                continue
            stat[h].append(v["ret"])
            if v["flag"] == "止损":
                stops += 1
            elif v["flag"] == "止盈1":
                tps += 1
            row.append(f"{h}:{v['ret']:+.2f}%")
        L.append("  " + "  ".join(row))
    L.append("")
    L.append("— 平均收益 —")
    for h, _ in HORIZONS:
        if stat[h]:
            avg = sum(stat[h]) / len(stat[h])
            wins = sum(1 for v in stat[h] if v > 0)
            L.append(f"{h}: 均值 {avg:+.2f}%   胜率 {wins}/{len(stat[h])}")
    L.append("")
    L.append(f"止损 {stops} 次, 止盈 {tps} 次")
    L.append("收益为价格变动%, 20倍杠杆需 ×20")
    return "\n".join(L)
