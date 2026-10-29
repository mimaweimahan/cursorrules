# -*- coding: utf-8 -*-
"""用户级钩子：会话开始注入大脑，每轮记下原文，stop 时写入并蒸馏。失败不阻断会话。"""
from __future__ import print_function

import json
import os
import re
import sys

try:
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
except ImportError:
    from urllib import urlencode
    from urllib2 import Request, urlopen

BRAIN = os.environ.get("BRAIN_HOME", r"C:\benji\brain")
BASE = os.environ.get("BRAIN_URL", "http://127.0.0.1:18099").rstrip("/")
SESSION_DIR = os.path.join(BRAIN, "data", "sessions")
CURRENT = os.path.join(SESSION_DIR, "current.txt")
SECRET_RE = re.compile(
    r"ghp_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9]{10,}|"
    r"AKIA[0-9A-Z]{16}|BEGIN (OPENSSH |RSA )?PRIVATE KEY|Bearer\s+\S+"
)


def emit(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")


def log(msg):
    try:
        if not os.path.isdir(os.path.join(BRAIN, "data")):
            os.makedirs(os.path.join(BRAIN, "data"))
        with open(os.path.join(BRAIN, "data", "hook.log"), "a", encoding="utf-8") as handle:
            handle.write(msg + "\n")
    except Exception:
        pass


def read_input():
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def redact(text):
    text = text or ""
    return SECRET_RE.sub("REDACTED", text)


def http_json(method, path, body=None, timeout=8):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(BASE + path, data=data, headers=headers)
    req.get_method = lambda: method
    resp = urlopen(req, timeout=timeout)
    try:
        return json.loads(resp.read().decode("utf-8"))
    finally:
        resp.close()


def session_id(payload):
    for key in ("session_id", "conversation_id", "composer_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def ensure_dir():
    if not os.path.isdir(SESSION_DIR):
        os.makedirs(SESSION_DIR)


def current_id():
    try:
        with open(CURRENT, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except Exception:
        return ""


def set_current(sid):
    ensure_dir()
    with open(CURRENT, "w", encoding="utf-8") as handle:
        handle.write(sid)


def state_path(sid):
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", sid)[:80]
    return os.path.join(SESSION_DIR, safe + ".json")


def load_state(sid):
    path = state_path(sid)
    if not os.path.isfile(path):
        return {"id": sid, "prompts": [], "responses": []}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        data = {"id": sid, "prompts": [], "responses": []}
    data.setdefault("prompts", [])
    data.setdefault("responses", [])
    return data


def save_state(state):
    ensure_dir()
    path = state_path(state["id"])
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False)


def clip(text, limit):
    text = redact(text).strip()
    if len(text) > limit:
        return text[:limit]
    return text


def on_start(payload):
    sid = session_id(payload) or "session"
    set_current(sid)
    save_state({"id": sid, "prompts": [], "responses": []})
    text = ""
    try:
        pack = http_json("GET", "/v1/context?" + urlencode({"task": "", "limit": "4"}))
        text = pack.get("text") or ""
    except Exception as exc:
        text = "大脑暂时连不上（%s）。有仓库就执行：python C:\\benji\\brain\\sync_cursorrules.py pull" % exc
    extra = (
        "永久记忆在本机大脑。上面是已有常识。本场会话结束会自动写入，不要把密钥写进记忆。"
        "用户说「脑同步」时先 pull 再 push。"
    )
    emit({"additional_context": (text + "\n" + extra).strip()})


def on_prompt(payload):
    sid = session_id(payload) or current_id() or "session"
    prompt = payload.get("prompt") or payload.get("text") or ""
    if isinstance(prompt, str) and prompt.strip():
        state = load_state(sid)
        state["prompts"].append(clip(prompt, 1500))
        state["prompts"] = state["prompts"][-30:]
        save_state(state)
        set_current(sid)
    emit({"continue": True})


def on_response(payload):
    sid = session_id(payload) or current_id() or "session"
    text = payload.get("text") or ""
    if isinstance(text, str) and text.strip():
        state = load_state(sid)
        state["responses"].append(clip(text, 1500))
        state["responses"] = state["responses"][-30:]
        save_state(state)
    emit({})


def on_stop(payload):
    if payload.get("status") not in (None, "", "completed"):
        emit({})
        return
    sid = session_id(payload) or current_id()
    if not sid:
        emit({})
        return
    state = load_state(sid)
    if not state["prompts"] and not state["responses"]:
        emit({})
        return
    try:
        http_json("POST", "/v1/session", {
            "session_id": sid,
            "prompts": state["prompts"],
            "responses": state["responses"],
        }, timeout=15)
    except Exception as exc:
        log("stop failed: " + str(exc))
    emit({})


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = read_input()
    try:
        if event == "sessionStart":
            on_start(payload)
        elif event == "prompt":
            on_prompt(payload)
        elif event == "response":
            on_response(payload)
        elif event == "stop":
            on_stop(payload)
        else:
            emit({})
    except Exception as exc:
        log(event + " error: " + str(exc))
        if event == "prompt":
            emit({"continue": True})
        else:
            emit({})
    return 0


if __name__ == "__main__":
    sys.exit(main())
