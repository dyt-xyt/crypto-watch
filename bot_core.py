# -*- coding: utf-8 -*-
"""盯盘机器人 —— 自动算关键位, 触发时给出方向 + 止损止盈, 推送到手机

用法:
  第一次: python 盯盘机器人.py --init     建立基线(不报警)
  日常:   python 盯盘机器人.py            一直跑
  测试:   python 盯盘机器人.py --test     测推送通道

推送通道(config.json):
  serverchan   Server酱 -> 微信服务号
  wecom        企业微信群机器人
  local        本机弹窗响铃
"""
import ctypes, json, os, sys, time, threading, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "config.json")
STATE = os.path.join(HERE, "state.json")
LOG = os.path.join(HERE, "盯盘日志.txt")
CN = timezone(timedelta(hours=8))

if HERE not in sys.path:
    sys.path.insert(0, HERE)
import journal

TEMPLATE = {
    "channel": "serverchan",
    "serverchan_key": "SCT在这里填你的SendKey",
    "wecom_webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=在这里填你的KEY",
    "interval_sec": 60,
    "cooldown_sec": 1800,
    "symbols": ["BTCUSDT", "SOLUSDT"],
    "watch": {"ma25_4h": True, "ma25_1h": True, "boll_4h": True,
              "swing_4h": True, "rsi_1h": True, "macd_1h": True,
              "vol_spike_15m": True, "funding": True},
    "account_equity": 0,
    "risk_pct": 1.5
}


# ---------- 基础 ----------
def load_cfg():
    if not os.path.exists(CFG):
        with open(CFG, "w", encoding="utf-8") as f:
            json.dump(TEMPLATE, f, ensure_ascii=False, indent=2)
        print(f"[初始化] 已生成 {CFG}")
        sys.exit(0)
    with open(CFG, encoding="utf-8") as f:
        return json.load(f)


def load_state():
    if os.path.exists(STATE):
        try:
            with open(STATE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(s):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


def log(m):
    line = f"[{datetime.now(CN):%m-%d %H:%M:%S}] {m}"
    try:
        print(line)
    except Exception:
        pass
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def http(url, data=None, timeout=20, form=False):
    hd = {"User-Agent": "Mozilla/5.0", "Connection": "close"}
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            hd["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data, ensure_ascii=False).encode()
            hd["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hd)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


BASE = "https://fapi.binance.com"
CLOUD = False


def api(path, n=4):
    p = path
    if CLOUD:
        p = p.replace("/fapi/v1/", "/api/v3/")
    last = None
    for i in range(n):
        try:
            return json.loads(http(BASE + p))
        except Exception as e:
            last = e
            if i == n - 1:
                break
            time.sleep(min(2 ** i, 3))
    raise last


# ---------- 推送 ----------
def push(cfg, title, body):
    ch = cfg.get("channel", "serverchan")
    try:
        if ch == "serverchan":
            k = cfg.get("serverchan_key", "")
            if not k or "在这里填" in k:
                return False, "Server酱 key 未配置"
            r = http(f"https://sctapi.ftqq.com/{k}.send",
                     {"title": title[:32], "desp": body}, form=True)
            return '"code":0' in r.replace(" ", ""), r[:120]
        if ch == "wecom":
            u = cfg.get("wecom_webhook", "")
            r = http(u, {"msgtype": "text", "text": {"content": f"{title}\n{body}"}})
            return '"errcode":0' in r.replace(" ", ""), r[:120]
        if ch == "pushplus":
            k = cfg.get("pushplus_token", "")
            if not k or "在这里填" in k:
                return False, "PushPlus token 未配置"
            r = http("https://www.pushplus.plus/send",
                     {"token": k, "title": title[:100], "content": body, "template": "txt"})
            return '"code":200' in r.replace(" ", ""), r[:120]
        if ch == "wxpusher":
            app = cfg.get("wxpusher_apptoken", "")
            uid = cfg.get("wxpusher_uid", "")
            if not app or not uid or "在这里填" in app:
                return False, "WxPusher 未配置"
            r = http("https://wxpusher.zjiecode.com/api/send/message",
                     {"appToken": app, "content": f"{title}\n\n{body}",
                      "summary": title[:20], "contentType": 1, "uids": [uid]})
            return '"success":true' in r.replace(" ", ""), r[:120]
        if ch == "local":
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                for f, d in ((1300, 200), (1000, 200), (1400, 350)):
                    winsound.Beep(f, d)
            except Exception:
                pass

            def _p(t=title, b=body):
                try:
                    import ctypes as ct
                    ct.windll.user32.MessageBoxW(0, b, t, 0x40 | 0x1000)
                except Exception:
                    pass
            threading.Thread(target=_p, daemon=True).start()
            return True, "本地弹窗"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    return False, f"未知通道 {ch}"


# ---------- 指标 ----------
def sma(x, n):
    return [None if i < n - 1 else sum(x[i - n + 1:i + 1]) / n for i in range(len(x))]


def ema(x, n):
    k, out, p = 2 / (n + 1), [], None
    for v in x:
        p = v if p is None else v * k + p * (1 - k)
        out.append(p)
    return out


def rsi(x, n=14):
    g = [max(x[i] - x[i - 1], 0) for i in range(1, len(x))]
    l = [max(x[i - 1] - x[i], 0) for i in range(1, len(x))]
    if len(g) < n:
        return [50] * (len(x) - 1)
    ag, al = sum(g[:n]) / n, (sum(l[:n]) / n) or 1e-9
    out = [50] * n + [100 - 100 / (1 + ag / al)]
    for i in range(n, len(g)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + l[i]) / n
        out.append(100 - 100 / (1 + ag / (al or 1e-9)))
    return out


def atr(k, n=14):
    h, l, c = k["h"], k["l"], k["c"]
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    if len(tr) < n:
        return [None] * len(c)
    out = [None] * n
    prev = sum(tr[:n]) / n
    out.append(prev)
    for i in range(n, len(tr)):
        prev = (prev * (n - 1) + tr[i]) / n
        out.append(prev)
    return out


def kl(sym, iv, lim):
    raw = api(f"/fapi/v1/klines?symbol={sym}&interval={iv}&limit={lim}")
    return dict(c=[float(k[4]) for k in raw], h=[float(k[2]) for k in raw],
                l=[float(k[3]) for k in raw], v=[float(k[5]) for k in raw])


def boll(c, n=20, k=2.0):
    if len(c) < n:
        return None
    seg = c[-n:]
    m = sum(seg) / n
    sd = (sum((x - m) ** 2 for x in seg) / n) ** 0.5
    return m, m + k * sd, m - k * sd


# ---------- 事件 ----------
def evaluate(cfg, sym, state, quiet=False):
    ev = []
    p = float(api(f"/fapi/v1/ticker/price?symbol={sym}")["price"])
    h4 = kl(sym, "4h", 120)
    h1 = kl(sym, "1h", 200)
    m15 = kl(sym, "15m", 60)
    try:
        fr = float(api(f"/fapi/v1/premiumIndex?symbol={sym}")["lastFundingRate"]) * 100
    except Exception:
        fr = 0.0

    d = 2 if p < 1000 else 0
    a1 = atr(h1)[-1] or (p * 0.01)
    sw_lo1, sw_hi1 = min(h1["l"][-20:]), max(h1["h"][-20:])
    m7_4, m25_4 = sma(h4["c"], 7)[-1], sma(h4["c"], 25)[-1]
    trend4 = 1 if m7_4 > m25_4 else -1
    eq, rp = float(cfg.get("account_equity") or 0), float(cfg.get("risk_pct") or 1.5)

    def fmt(v):
        return f"{v:,.{d}f}"

    def plan(side, reason="", max_risk=2.5):
        """side: 1 多 / -1 空 / 0 不建议追"""
        if side == 0:
            return ("⏸ 方向：现在不追\n"
                    f"观察位：站上 {fmt(sw_hi1)} 转多 / 跌破 {fmt(sw_lo1)} 转空\n"
                    "极端位置硬做，是给市场送钱。", None)
        bb = boll(h4["c"])
        m99_4 = sma(h4["c"], 99)[-1]
        sw_lo4, sw_hi4 = min(h4["l"][-30:-1]), max(h4["h"][-30:-1])
        ups = [(v, n) for v, n in ((m25_4, "4H MA25"), (m99_4, "4H MA99"),
               (bb[1] if bb else None, "4H布林上轨"), (sw_hi4, "4H前高")) if v and v > p]
        dns = [(v, n) for v, n in ((m25_4, "4H MA25"), (m99_4, "4H MA99"),
               (bb[2] if bb else None, "4H布林下轨"), (sw_lo4, "4H前低")) if v and v < p]
        if side > 0:
            raw = sw_lo1
            if (p - raw) / p * 100 > max_risk:
                return (f"⏸ 不做：止损放不下\n"
                        f"最近结构低点在 {fmt(raw)}，距现价 {(p-raw)/p*100:.2f}%\n"
                        f"这类信号最多只能承受 {max_risk:g}% 止损\n"
                        f"硬做就是赌，等结构靠近了再说。", None)
            if p - raw > 2.2 * a1:
                sl = p - 1.8 * a1
            elif p - raw < 0.6 * a1:
                sl = p - 0.9 * a1
            else:
                sl = raw - 0.15 * a1
            risk = p - sl
            tp1, tag = p + 2 * risk, "2R"
            if ups:
                v, n = min(ups)
                if p + 0.8 * risk < v < tp1:
                    tp1, tag = v - 0.1 * a1, f"遇 {n}"
            tp2 = p + 3 * risk
            lines = [f"📈 方向：偏多（{reason}）",
                     f"止损：{fmt(sl)}（{(sl/p-1)*100:+.2f}%）",
                     f"止盈1：{fmt(tp1)}（{(tp1/p-1)*100:+.2f}%，{tag}）",
                     f"止盈2：{fmt(tp2)}（{(tp2/p-1)*100:+.2f}%，3R）"]
        else:
            raw = sw_hi1
            if (raw - p) / p * 100 > max_risk:
                return (f"⏸ 不做：止损放不下\n"
                        f"最近结构高点在 {fmt(raw)}，距现价 {(raw-p)/p*100:.2f}%\n"
                        f"这类信号最多只能承受 {max_risk:g}% 止损\n"
                        f"硬做就是赌，等结构靠近了再说。", None)
            if raw - p > 2.2 * a1:
                sl = p + 1.8 * a1
            elif raw - p < 0.6 * a1:
                sl = p + 0.9 * a1
            else:
                sl = raw + 0.15 * a1
            risk = sl - p
            tp1, tag = p - 2 * risk, "2R"
            if dns:
                v, n = max(dns)
                if p - 0.8 * risk < v < tp1:
                    tp1, tag = v + 0.1 * a1, f"遇 {n}"
            tp2 = p - 3 * risk
            lines = [f"📉 方向：偏空（{reason}）",
                     f"止损：{fmt(sl)}（{(sl/p-1)*100:+.2f}%）",
                     f"止盈1：{fmt(tp1)}（{(tp1/p-1)*100:+.2f}%，{tag}）",
                     f"止盈2：{fmt(tp2)}（{(tp2/p-1)*100:+.2f}%，3R）"]
        rr = abs(tp1 - p) / risk
        lines.append(f"止损空间 {risk/p*100:.2f}%   止盈1盈亏比 {rr:.1f} : 1")
        if eq > 0:
            qty = eq * rp / 100 / risk
            lines.append(f"按 {rp:g}% 风险（{eq:,.0f}U）：{qty:.3g} 币，名义 {qty*p:,.0f}U"
                         f"，20x 占用 {qty*p/20:,.0f}U")
        same = (side > 0 and trend4 > 0) or (side < 0 and trend4 < 0)
        if rr >= 2 and same:
            lines.append("✅ 顺4H趋势 + 盈亏比达标，符合规则，可做")
        elif rr >= 2:
            lines.append("⚠️ 逆4H趋势：仓位砍半，只打止盈1，到了就走")
        else:
            lines.append("❌ 盈亏比不足 2:1，按规则不该进场，等更好位置")
        meta = {"side": side, "entry": p, "stop": sl, "tp1": tp1, "tp2": tp2,
                "risk_pct": risk / p * 100, "rr": rr, "ok": (rr >= 2)}
        return "\n".join(lines), meta

    def fire(key, active, title, body, cd=None, side=None, reason=""):
        for suf, flag in ((".ma25_4h", "ma25_4h"), (".ma25_1h", "ma25_1h"),
                          (".boll_", "boll_4h"), (".swing_", "swing_4h"),
                          (".rsi_", "rsi_1h"), (".macd_1h", "macd_1h"),
                          (".macd_4h", "macd_4h"), (".ma_15m", "ma_15m"),
                          (".vol", "vol_spike_15m"), (".funding", "funding")):
            if suf in key and not cfg.get("watch", {}).get(flag, True):
                return
        cool = cfg.get("cooldown_sec", 1800) if cd is None else cd
        now = time.time()
        rec = state.get(key)
        if isinstance(rec, dict):
            on, ts = bool(rec.get("on")), float(rec.get("ts") or 0)
        else:
            on, ts = bool(rec), float(rec or 0)
        if active and not on:
            if now - ts >= cool and not quiet:
                if key.endswith(".vol"):
                    mr = 0.8          # 15分钟信号, 只配小止损
                elif key.endswith(".ma_15m"):
                    mr = 1.0          # 15分钟均线
                elif key.endswith("_1h") or ".rsi_" in key:
                    mr = 1.5          # 1小时信号
                else:
                    mr = 2.5          # 4小时信号
                ptext, pmeta = plan(side, reason, mr)
                ev.append((key, title, body + "\n\n" + ptext, pmeta, reason))
                state[key] = {"on": True, "ts": now}
            else:
                state[key] = {"on": True, "ts": ts}
        elif not active:
            state[key] = {"on": False, "ts": ts}

    # 1) 4H MA25
    s25 = sma(h4["c"], 25)[-1]
    if p > s25:
        fire(f"{sym}.ma25_4h", True, f"{sym} 上穿4H MA25",
             f"现价 {fmt(p)}  MA25 {fmt(s25)}", side=1, reason="站上中期均线")
    else:
        fire(f"{sym}.ma25_4h", False, "", "", side=-1)

    # 2) 1H MA25
    s1 = sma(h1["c"], 25)[-1]
    if p > s1:
        fire(f"{sym}.ma25_1h", True, f"{sym} 上穿1H MA25",
             f"现价 {fmt(p)}  MA25 {fmt(s1)}", side=1, reason="短线转强")
    else:
        fire(f"{sym}.ma25_1h", False, "", "", side=-1)

    # 3) 4H 布林
    b = boll(h4["c"])
    if b:
        m, u, lo = b
        if p > u:
            fire(f"{sym}.boll_up", True, f"{sym} 触及4H布林上轨",
                 f"现价 {fmt(p)}  上轨 {fmt(u)}\n超买≠要跌，强趋势会沿上轨走",
                 cd=2400, side=0)
        else:
            fire(f"{sym}.boll_up", False, "", "", side=0)
        if p < lo:
            fire(f"{sym}.boll_dn", True, f"{sym} 触及4H布林下轨",
                 f"现价 {fmt(p)}  下轨 {fmt(lo)}\n超卖≠要涨，接刀的人已经排到楼下",
                 cd=2400, side=0)
        else:
            fire(f"{sym}.boll_dn", False, "", "", side=0)

    # 4) 结构突破
    hi4, lo4 = max(h4["h"][-21:-1]), min(h4["l"][-21:-1])
    if p > hi4:
        fire(f"{sym}.swing_hi", True, f"{sym} 突破20根4H新高",
             f"现价 {fmt(p)}  前高 {fmt(hi4)}", cd=3600, side=1, reason="结构向上突破")
    else:
        fire(f"{sym}.swing_hi", False, "", "", side=1)
    if p < lo4:
        fire(f"{sym}.swing_lo", True, f"{sym} 跌破20根4H新低",
             f"现价 {fmt(p)}  前低 {fmt(lo4)}", cd=3600, side=-1, reason="结构向下破位")
    else:
        fire(f"{sym}.swing_lo", False, "", "", side=-1)

    # 5) RSI
    r = rsi(h1["c"])[-1]
    if r > 75:
        fire(f"{sym}.rsi_hi", True, f"{sym} 1H RSI 超买 {r:.0f}",
             f"现价 {fmt(p)}", cd=2400, side=0)
    else:
        fire(f"{sym}.rsi_hi", False, "", "", side=0)
    if r < 25:
        fire(f"{sym}.rsi_lo", True, f"{sym} 1H RSI 超卖 {r:.0f}",
             f"现价 {fmt(p)}", cd=2400, side=0)
    else:
        fire(f"{sym}.rsi_lo", False, "", "", side=0)

    # 6) MACD
    dif = [x - y for x, y in zip(ema(h1["c"], 12), ema(h1["c"], 26))]
    dea = ema(dif, 9)
    up = dif[-1] > dea[-1]
    if up:
        fire(f"{sym}.macd_1h", True, f"{sym} 1H MACD 金叉",
             f"DIF {dif[-1]:.2f} DEA {dea[-1]:.2f} 柱 {2*(dif[-1]-dea[-1]):+.2f}"
             f"（{'零轴上' if dif[-1]>0 else '零轴下'}）", cd=2400, side=1, reason="动能转多")
    else:
        fire(f"{sym}.macd_1h", False, "", "", side=-1)

    # 7) 15M 放量
    av = sum(m15["v"][-21:-1]) / 20
    ratio = m15["v"][-1] / av if av else 0
    if ratio > 3:
        upbar = m15["c"][-1] >= m15["c"][-2]
        fire(f"{sym}.vol", True, f"{sym} 15M 放量 {ratio:.1f} 倍",
             f"现价 {fmt(p)}  量 {m15['v'][-1]:,.0f} / 均量 {av:,.0f}\n"
             + ("放量上涨，多头在抢" if upbar else "放量下跌，有人在砸"),
             cd=900, side=1 if upbar else -1,
             reason="放量" + ("阳线" if upbar else "阴线"))
    else:
        fire(f"{sym}.vol", False, "", "", side=0)

    # 9) 4H MACD
    dif4 = [x - y for x, y in zip(ema(h4["c"], 12), ema(h4["c"], 26))]
    dea4 = ema(dif4, 9)
    if dif4[-1] > dea4[-1]:
        fire(f"{sym}.macd_4h", True, f"{sym} 4H MACD 金叉",
             f"DIF {dif4[-1]:.1f} DEA {dea4[-1]:.1f} 柱 {2*(dif4[-1]-dea4[-1]):+.1f}"
             f"（{'零轴上' if dif4[-1]>0 else '零轴下'}）",
             cd=7200, side=1, reason="4H动能转多")
    else:
        fire(f"{sym}.macd_4h", False, "", "", side=-1)

    # 10) 15M 均线交叉
    m7_15 = sma(m15["c"], 7)[-1]
    m25_15 = sma(m15["c"], 25)[-1]
    if m7_15 > m25_15:
        fire(f"{sym}.ma_15m", True, f"{sym} 15M MA7 上穿 MA25",
             f"现价 {fmt(p)}  MA7 {fmt(m7_15)} MA25 {fmt(m25_15)}",
             cd=1800, side=1, reason="短线转多")
    else:
        fire(f"{sym}.ma_15m", False, "", "", side=-1)

    # 8) 资金费率
    if abs(fr) > 0.05:
        fire(f"{sym}.funding", True, f"{sym} 资金费率异常 {fr:+.4f}%",
             f"{'多头拥挤，追多危险' if fr>0 else '空头拥挤，追空危险'}",
             cd=7200, side=0)
    else:
        fire(f"{sym}.funding", False, "", "", side=0)

    return ev, p


def main():
    cfg = load_cfg()
    if "--test" in sys.argv:
        ok, info = push(cfg, "✅ 盯盘机器人测试", "收到这条说明推送通道已通。\n方向+止损止盈已启用。")
        print("推送:", "成功" if ok else f"失败 -> {info}")
        return

    base, once = "--init" in sys.argv, "--once" in sys.argv
    state = load_state()
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    except Exception:
        pass

    log(f"盯盘启动 通道={cfg.get('channel')} 品种={','.join(cfg['symbols'])} "
        f"间隔={cfg.get('interval_sec', 60)}s" + ("  [基线]" if base else ""))

    if base:
        for s in cfg["symbols"]:
            for _ in range(3):
                try:
                    _, p = evaluate(cfg, s, state, quiet=True)
                    log(f"  基线 {s} @ {p:,.2f}")
                    break
                except Exception as e:
                    log(f"  基线重试 {s}: {type(e).__name__}")
                    time.sleep(3)
        save_state(state)
        log("基线完成，之后只在状态变化时提醒。")
        if once:
            return

    while True:
        for s in cfg["symbols"]:
            ev, p = [], 0.0
            for attempt in range(3):
                try:
                    ev, p = evaluate(cfg, s, state)
                    break
                except Exception as e:
                    if attempt == 2:
                        log(f"  {s} 出错(已重试): {type(e).__name__}: {e}")
                    else:
                        time.sleep(3)
            if p:
                for item in ev:
                    k, t, b = item[0], item[1], item[2]
                    pmeta = item[3] if len(item) > 3 else None
                    preason = item[4] if len(item) > 4 else ""
                    ok, info = push(cfg, f"🔔 {t}", b + f"\n\n{datetime.now(CN):%m-%d %H:%M}")
                    log(f"  触发 {t} @ {p:,.2f} -> {'成功' if ok else '失败:'+info}")
                    if ok and pmeta:
                        journal.record(s, t, preason, pmeta)
                        log(f"    已记账 {t} 入场 {pmeta['entry']:,.2f} "
                            f"止损 {pmeta['stop']:,.2f} 止盈 {pmeta['tp1']:,.2f}")
                if not ev:
                    log(f"  {s} {p:,.2f}  无新信号")
        # 回测上次推送的 30m/1h/4h/12h/24h 表现
        try:
            if time.time() - float(state.get("_journal_upd", 0)) > 300:
                n = journal.update()
                state["_journal_upd"] = time.time()
                if n:
                    log(f"  纸面交易: 新结算 {n} 个周期")
        except Exception as e:
            log(f"  账本更新失败: {type(e).__name__}: {e}")
        # 每天 0 点发日报
        try:
            nowd = datetime.now(CN)
            if nowd.hour < 6 and state.get("_daily") != nowd.strftime("%Y-%m-%d"):
                k = nowd.strftime("%Y-%m-%d")
                if state.get("_daily") != k:
                    txt = journal.daily_report()
                    if txt:
                        ok, info = push(cfg, "📊 盯盘日报", txt)
                        log(f"  日报推送 -> {'成功' if ok else '失败:'+info}")
                    state["_daily"] = k
        except Exception as e:
            log(f"  日报失败: {type(e).__name__}: {e}")
        save_state(state)
        if once:
            break
        time.sleep(int(cfg.get("interval_sec", 60)))


if __name__ == "__main__":
    main()
