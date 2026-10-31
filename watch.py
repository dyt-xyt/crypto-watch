# -*- coding: utf-8 -*-
"""GitHub Actions 单次运行版 —— 与本地共享"已推送"记录, 谁先发现谁推

环境变量:
  WXPUSHER_APPTOKEN / WXPUSHER_UID   必填(仓库 Secrets)
  GITHUB_TOKEN / GITHUB_REPOSITORY   Actions 自动注入
  SYMBOLS / COOLDOWN_SEC             可选
"""
import os
import sys
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cloudstate


def main():
    spec = importlib.util.spec_from_file_location(
        "bot", os.path.join(HERE, "bot_core.py"))
    bot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bot)

    # GitHub 美国机房访问币安主站被 451, 改用官方公开数据节点
    bot.BASE = os.environ.get("BINANCE_BASE", "https://data-api.binance.vision").strip()
    bot.CLOUD = True
    print(f"数据源: {bot.BASE}")

    cfg = {
        "channel": "wxpusher",
        "wxpusher_apptoken": os.environ.get("WXPUSHER_APPTOKEN", "").strip(),
        "wxpusher_uid": os.environ.get("WXPUSHER_UID", "").strip(),
        "interval_sec": 300,
        "cooldown_sec": int(os.environ.get("COOLDOWN_SEC", "1800")),
        "symbols": [s.strip() for s in
                    os.environ.get("SYMBOLS", "BTCUSDT,SOLUSDT,ETHUSDT").split(",")
                    if s.strip()],
        "watch": {
            "ma25_4h": True, "ma25_1h": True, "boll_4h": True,
            "swing_4h": True, "rsi_1h": True, "macd_1h": True,
            "macd_4h": True, "ma_15m": True,
            "vol_spike_15m": True,
            "funding": False,          # 现货数据源没有资金费率
        },
        "account_equity": 0,
        "risk_pct": 1.5,
    }

    if not cfg["wxpusher_apptoken"] or not cfg["wxpusher_uid"]:
        print("缺少 WXPUSHER_APPTOKEN 或 WXPUSHER_UID")
        sys.exit(1)

    state, sha = cloudstate.load()
    first_run = not state
    if first_run:
        print("首次运行: 只建立基线, 不推送")

    sent = 0
    for sym in cfg["symbols"]:
        try:
            ev, p = bot.evaluate(cfg, sym, state, quiet=first_run)
        except Exception as e:
            print(f"{sym} 获取失败: {type(e).__name__}: {e}")
            continue
        print(f"{sym} {p:,.2f}  触发 {len(ev)} 条")
        for item in ev:
            key, title, body = item[0], item[1], item[2]
            meta = item[3] if len(item) > 3 else None
            if not (meta and meta.get("ok")):
                print(f"  -> {title} 盈亏比/止损不达标, 静默")
                continue
            if cloudstate.already_pushed(state, key, cfg["cooldown_sec"]):
                print(f"  -> {title} 已被另一台设备推送, 跳过")
                continue
            ok, info = bot.push(cfg, "🔔 " + title, body)
            print(f"  -> {title} {'成功' if ok else '失败:' + info}")
            if ok:
                cloudstate.mark(state, key)
                sent += 1
    ok = cloudstate.save(state, sha)
    print(f"本轮推送 {sent} 条, 共享状态写回{'成功' if ok else '失败'}")


if __name__ == "__main__":
    main()
