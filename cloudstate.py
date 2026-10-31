# -*- coding: utf-8 -*-
"""本地与云端共享的"已推送"记录 —— 存在 GitHub 仓库的 state.json

谁先发现信号谁推送, 另一方读到后就不再重复推。
网络不通时本地自动失效(推不出去), 云端照常工作。
"""
import base64
import json
import os
import subprocess
import time
import urllib.request

GH_EXE = os.environ.get(
    "GH_EXE", r"C:\Users\19592\OneDrive\Desktop\百倍计划\bin\bin\gh.exe")
REPO = os.environ.get("GH_REPO", "dyt-xyt/crypto-watch")
PATH = "state.json"
_HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE = os.path.join(_HERE, ".ghtoken")


def _token():
    t = os.environ.get("GITHUB_TOKEN")
    if t:
        return t
    if os.path.exists(_CACHE):
        try:
            v = open(_CACHE, encoding="utf-8").read().strip()
            if v:
                return v
        except Exception:
            pass
    for exe in (GH_EXE, "gh"):
        try:
            out = subprocess.run([exe, "auth", "token"], capture_output=True,
                                 text=True, timeout=15)
            v = (out.stdout or "").strip()
            if v.startswith("gh"):
                try:
                    open(_CACHE, "w", encoding="utf-8").write(v)
                except Exception:
                    pass
                return v
        except Exception:
            continue
    return ""


def _req(method, url, body=None, token="", timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "crypto-watch",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def load():
    """返回 (state_dict, sha)。失败时返回 ({}, None)，调用方照常工作。"""
    tok = _token()
    if not tok:
        return {}, None
    url = f"https://api.github.com/repos/{REPO}/contents/{PATH}"
    try:
        r = _req("GET", url, token=tok)
        raw = base64.b64decode(r["content"]).decode("utf-8")
        return json.loads(raw or "{}"), r.get("sha")
    except Exception:
        return {}, None


def save(state, sha=None):
    tok = _token()
    if not tok:
        return False
    url = f"https://api.github.com/repos/{REPO}/contents/{PATH}"
    body = {"message": "update state",
            "content": base64.b64encode(json.dumps(state, ensure_ascii=False).encode()).decode()}
    if sha:
        body["sha"] = sha
    try:
        _req("PUT", url, body, tok)
        return True
    except Exception:
        return False


def already_pushed(state, key, cooldown=1800):
    """另一台机器是否已经在冷却期内推过这个信号"""
    rec = state.get(key)
    if not isinstance(rec, dict) or not rec.get("on"):
        return False
    return (time.time() - float(rec.get("ts") or 0)) < cooldown


def mark(state, key):
    state[key] = {"on": True, "ts": time.time()}
