# -*- coding: utf-8 -*-
"""GitHub Actions 单次运行版 —— 跑完就退出, 由 cron 定时触发

环境变量:
  WXPUSHER_APPTOKEN / WXPUSHER_UID   必填(来自仓库 Secrets)
  SYMBOLS        可选, 默认 BTCUSDT,SOLUSDT,ETHUSDT
  COOLDOWN_SEC   可选, 同信号冷却秒数, 默认 1800
"""
import os
import sys
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    spec = importlib.util.spec_from_file_location(
        "bot", os.path.join(HERE, "bot_core.py"))
    bot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bot)

    # GitHub 的美国机房被币安主站封锁(451), 改用官方公开数据节点
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
            "vol_spike_15m": True, "funding": True,
        },
        "account_equity": 0,
        "risk_pct": 1.5,
    }

    if not cfg["wxpusher_apptoken"] or not cfg["wxpusher_uid"]:
        print("缺少 WXPUSHER_APPTOKEN 或 WXPUSHER_UID, 请在仓库 Secrets 里配置")
        sys.exit(1)

    state = bot.load_state()
    first_run = not os.path.exists(bot.STATE)
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
            ok, info = bot.push(cfg, "🔔 " + title, body)
            print(f"  -> {title} {'成功' if ok else '失败:' + info}")
            if ok:
                sent += 1
    bot.save_state(state)
    print(f"本轮共推送 {sent} 条")


if __name__ == "__main__":
    main()
