# -*- coding: utf-8 -*-
"""大脑命令行。Cursor / 脚本用这个，不要直接改 sqlite。"""
from __future__ import print_function

import argparse
import json
import os
import subprocess
import sys
import time

try:
    from urllib.error import HTTPError, URLError
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
except ImportError:
    from urllib import urlencode
    from urllib2 import HTTPError, Request, URLError, urlopen

DEFAULT_URL = os.environ.get("BRAIN_URL", "http://127.0.0.1:18099")
TOKEN = os.environ.get("BRAIN_TOKEN", "").strip()
_START_TRIED = False


def _health_once():
    req = Request(DEFAULT_URL.rstrip("/") + "/health", headers={"Accept": "application/json"})
    resp = urlopen(req, timeout=2)
    try:
        return json.loads(resp.read().decode("utf-8"))
    finally:
        resp.close()


def ensure_server():
    """连不上就拉起 brain/server.py，等到 /health 再返回。同一进程只尝试启动一次。"""
    global _START_TRIED
    try:
        data = _health_once()
        if data.get("ok"):
            return True
    except (HTTPError, URLError, ValueError, OSError):
        pass
    if _START_TRIED:
        return False
    _START_TRIED = True
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(here, "server.py")
    log_dir = os.path.join(here, "data")
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)
    log_handle = open(os.path.join(log_dir, "server.log"), "a")
    kwargs = {
        "cwd": here,
        "stdout": log_handle,
        "stderr": log_handle,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000200 | 0x08000000
    else:
        kwargs["start_new_session"] = True
    sys.stderr.write("大脑未启动，正在拉起 %s\n" % script)
    subprocess.Popen([sys.executable, script], **kwargs)
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            data = _health_once()
            if data.get("ok"):
                sys.stderr.write("大脑已就绪 %s\n" % DEFAULT_URL)
                return True
        except (HTTPError, URLError, ValueError, OSError):
            time.sleep(0.3)
    return False


def load_token():
    if TOKEN:
        return TOKEN
    key_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cursor", "model_api_key.txt")
    if os.path.isfile(key_path):
        with open(key_path, "r") as handle:
            return handle.read().strip()
    return ""


def request(method, path, query=None, body=None, _retry=True):
    url = DEFAULT_URL.rstrip("/") + path
    if query:
        url += "?" + urlencode(query)
    data = None
    headers = {"Accept": "application/json"}
    token = load_token()
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers)
    try:
        req.get_method = lambda: method  # Py3.8
        resp = urlopen(req, timeout=20)
        raw = resp.read().decode("utf-8")
        return json.loads(raw)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        sys.stderr.write("HTTP %s %s\n" % (exc.code, raw))
        sys.exit(1)
    except URLError as exc:
        if _retry and ensure_server():
            return request(method, path, query=query, body=body, _retry=False)
        sys.stderr.write("连不上大脑 %s（%s）。启动失败，看 brain/data/server.log\n" % (DEFAULT_URL, exc.reason))
        sys.exit(2)


def cmd_health(_args):
    print(json.dumps(request("GET", "/health"), ensure_ascii=False, indent=2))


def cmd_remember(args):
    payload = {
        "kind": args.kind,
        "title": args.title,
        "body": args.body,
        "source": args.source or "",
        "tags": args.tags or "",
        "salience": args.salience,
    }
    print(json.dumps(request("POST", "/v1/remember", body=payload), ensure_ascii=False, indent=2))


def cmd_recall(args):
    query = {"q": args.q, "limit": str(args.limit)}
    if args.kind:
        query["kind"] = args.kind
    print(json.dumps(request("GET", "/v1/recall", query=query), ensure_ascii=False, indent=2))


def cmd_context(args):
    pack = request("GET", "/v1/context", query={"task": args.task, "limit": str(args.limit)})
    sys.stdout.write(pack.get("text", "") + "\n")


def cmd_route(args):
    print(json.dumps(request("GET", "/v1/route", query={"intent": args.intent}), ensure_ascii=False, indent=2))


def cmd_skill(args):
    payload = {
        "name": args.name,
        "when_to_use": args.when,
        "how": args.how,
        "hand": args.hand,
    }
    print(json.dumps(request("POST", "/v1/skill", body=payload), ensure_ascii=False, indent=2))


def cmd_success(args):
    print(json.dumps(request("POST", "/v1/skill/success", body={"name": args.name}), ensure_ascii=False, indent=2))


def cmd_reindex(_args):
    print(json.dumps(request("POST", "/v1/reindex", body={}), ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="永久记忆库客户端")
    sub = parser.add_subparsers(dest="cmd")
    sub.required = True

    sub.add_parser("health")

    p_remember = sub.add_parser("remember")
    p_remember.add_argument("--kind", default="common_sense", choices=[
        "common_sense", "fact", "decision", "preference", "pitfall", "episode", "skill", "file_touch", "route",
    ])
    p_remember.add_argument("--title", required=True)
    p_remember.add_argument("--body", required=True)
    p_remember.add_argument("--source", default="")
    p_remember.add_argument("--tags", default="")
    p_remember.add_argument("--salience", type=float, default=1.0)

    p_recall = sub.add_parser("recall")
    p_recall.add_argument("q")
    p_recall.add_argument("--kind")
    p_recall.add_argument("--limit", type=int, default=8)

    p_ctx = sub.add_parser("context")
    p_ctx.add_argument("--task", required=True)
    p_ctx.add_argument("--limit", type=int, default=6)

    p_route = sub.add_parser("route")
    p_route.add_argument("intent")

    p_skill = sub.add_parser("skill")
    p_skill.add_argument("--name", required=True)
    p_skill.add_argument("--when", required=True)
    p_skill.add_argument("--how", required=True)
    p_skill.add_argument("--hand", default="llm")

    p_ok = sub.add_parser("success")
    p_ok.add_argument("name")

    sub.add_parser("reindex")

    args = parser.parse_args()
    {
        "health": cmd_health,
        "remember": cmd_remember,
        "recall": cmd_recall,
        "context": cmd_context,
        "route": cmd_route,
        "skill": cmd_skill,
        "success": cmd_success,
        "reindex": cmd_reindex,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
