# -*- coding: utf-8 -*-
"""本机/VPS 永久记忆库。标准库 + SQLite FTS5，不依赖向量库。"""
from __future__ import print_function

import json
import os
import sqlite3
import time
from datetime import datetime

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from urlparse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("BRAIN_DB", os.path.join(ROOT, "data", "brain.db"))
HOST = os.environ.get("BRAIN_HOST", "127.0.0.1")
PORT = int(os.environ.get("BRAIN_PORT", "18099"))
TOKEN = os.environ.get("BRAIN_TOKEN", "").strip()

KINDS = (
    "common_sense",
    "fact",
    "decision",
    "preference",
    "pitfall",
    "episode",
    "skill",
    "file_touch",
    "route",
)

HANDS = {
    "cursor": "改代码、读仓库、Cursor Agent",
    "openclaw": "Telegram / 远程工作区对话与执行",
    "graphify": "代码结构图、谁调谁、path/explain",
    "codebase-memory": "已索引仓的符号/调用链 MCP",
    "ale": "接口映射 Frontend→Route→Backend→Model",
    "shell": "本机或 VPS 运维命令",
    "llm": "纯推理、写文案、不碰文件",
}


def now_iso():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def connect():
    directory = os.path.dirname(DB_PATH)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            source TEXT DEFAULT '',
            tags TEXT DEFAULT '',
            salience REAL DEFAULT 1.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            title, body, tags, content='memories', content_rowid='id'
        );
        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, title, body, tags)
            VALUES (new.id, new.title, new.body, new.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, title, body, tags)
            VALUES('delete', old.id, old.title, old.body, old.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, title, body, tags)
            VALUES('delete', old.id, old.title, old.body, old.tags);
            INSERT INTO memories_fts(rowid, title, body, tags)
            VALUES (new.id, new.title, new.body, new.tags);
        END;
        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            when_to_use TEXT NOT NULL,
            how TEXT NOT NULL,
            hand TEXT NOT NULL,
            success_count INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    seed_skills(conn)


def seed_skills(conn):
    defaults = [
        (
            "改业务代码",
            "改 PHP/Vue/Java 业务、修 bug、加功能",
            "先 recall 相关 pitfall/decision，再用 Cursor 读实现后改。金额用 bcmath/BigDecimal。",
            "cursor",
        ),
        (
            "追接口链路",
            "前端请求、API 路径、后端控制器、字段对齐",
            "codebase-memory 定位符号后，按 ALE 输出 Linkage Snapshot，必要时 /map。",
            "ale",
        ),
        (
            "问谁调谁",
            "调用链、模块关系、结构图、graphify",
            "有图谱用 search_graph/trace_path；需要持久结构图再用 graphify。",
            "codebase-memory",
        ),
        (
            "Telegram远程干活",
            "手机/Telegram 让机器人读仓或跑命令",
            "OpenClaw 工作区在 /www/wwwroot/cura/wwwroot，业务在 admin_panel/。先 /new 短会话。",
            "openclaw",
        ),
        (
            "模型与网关",
            "18088、qwen36、上下文撑爆、Featurize 推理",
            "先查记忆里的网关/ctx 结论，再动 systemd/脚本。不要用加卡当唯一答案。",
            "shell",
        ),
    ]
    ts = now_iso()
    for name, when, how, hand in defaults:
        conn.execute(
            "INSERT OR IGNORE INTO skills(name, when_to_use, how, hand, success_count, updated_at) "
            "VALUES (?,?,?,?,0,?)",
            (name, when, how, hand, ts),
        )
    conn.commit()


def row_mem(row):
    return {
        "id": row["id"],
        "kind": row["kind"],
        "title": row["title"],
        "body": row["body"],
        "source": row["source"],
        "tags": row["tags"],
        "salience": row["salience"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def remember(conn, payload):
    kind = (payload.get("kind") or "fact").strip()
    if kind not in KINDS:
        kind = "fact"
    title = (payload.get("title") or "").strip()
    body = (payload.get("body") or "").strip()
    if not title or not body:
        raise ValueError("title 和 body 必填")
    source = (payload.get("source") or "").strip()
    tags = (payload.get("tags") or "").strip()
    salience = float(payload.get("salience") or 1.0)
    ts = now_iso()
    cur = conn.execute(
        "INSERT INTO memories(kind, title, body, source, tags, salience, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (kind, title, body, source, tags, salience, ts, ts),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM memories WHERE id=?", (cur.lastrowid,)).fetchone()
    return row_mem(row)


def recall(conn, query, limit=8, kind=None):
    limit = max(1, min(int(limit), 30))
    query = (query or "").strip()
    if not query:
        sql = "SELECT * FROM memories ORDER BY salience DESC, id DESC LIMIT ?"
        args = [limit]
        if kind:
            sql = "SELECT * FROM memories WHERE kind=? ORDER BY salience DESC, id DESC LIMIT ?"
            args = [kind, limit]
        rows = conn.execute(sql, args).fetchall()
        return [row_mem(r) for r in rows]
    sql = (
        "SELECT m.* FROM memories m JOIN memories_fts f ON m.id=f.rowid "
        "WHERE memories_fts MATCH ? "
    )
    args = [query]
    if kind:
        sql += "AND m.kind=? "
        args.append(kind)
    sql += "ORDER BY m.salience DESC, m.id DESC LIMIT ?"
    args.append(limit)
    try:
        rows = conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        rows = []
    if not rows:
        like = "%" + query + "%"
        extra = " AND kind=?" if kind else ""
        like_args = [like, like, like]
        if kind:
            like_args.append(kind)
        like_args.append(limit)
        rows = conn.execute(
            "SELECT * FROM memories WHERE (title LIKE ? OR body LIKE ? OR tags LIKE ?)%s "
            "ORDER BY salience DESC, id DESC LIMIT ?" % extra,
            like_args,
        ).fetchall()
    return [row_mem(r) for r in rows]


def upsert_skill(conn, payload):
    name = (payload.get("name") or "").strip()
    when = (payload.get("when_to_use") or "").strip()
    how = (payload.get("how") or "").strip()
    hand = (payload.get("hand") or "llm").strip()
    if not name or not when or not how:
        raise ValueError("name / when_to_use / how 必填")
    if hand not in HANDS:
        hand = "llm"
    ts = now_iso()
    conn.execute(
        "INSERT INTO skills(name, when_to_use, how, hand, success_count, updated_at) "
        "VALUES (?,?,?,?,0,?) "
        "ON CONFLICT(name) DO UPDATE SET "
        "when_to_use=excluded.when_to_use, how=excluded.how, hand=excluded.hand, "
        "updated_at=excluded.updated_at",
        (name, when, how, hand, ts),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM skills WHERE name=?", (name,)).fetchone()
    return dict(row)


def route(conn, intent, limit=3):
    intent = (intent or "").strip()
    skills = []
    if intent:
        like = "%" + intent + "%"
        skills = conn.execute(
            "SELECT * FROM skills WHERE name LIKE ? OR when_to_use LIKE ? OR how LIKE ? "
            "ORDER BY success_count DESC LIMIT ?",
            (like, like, like, limit),
        ).fetchall()
    if not skills:
        skills = conn.execute(
            "SELECT * FROM skills ORDER BY success_count DESC, id LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for row in skills:
        item = dict(row)
        item["hand_meaning"] = HANDS.get(row["hand"], "")
        out.append(item)
    return {"intent": intent, "hands": out}


def bump_skill(conn, name):
    conn.execute(
        "UPDATE skills SET success_count=success_count+1, updated_at=? WHERE name=?",
        (now_iso(), name),
    )
    conn.commit()


def context_pack(conn, task, limit=6):
    memories = recall(conn, task, limit=limit)
    if not memories:
        memories = recall(conn, task, limit=limit, kind="common_sense")
    routed = route(conn, task, limit=3)
    lines = ["[BRAIN CONTEXT]", "任务: " + (task or "(无)")]
    if routed["hands"]:
        lines.append("建议调用:")
        for hand in routed["hands"]:
            lines.append(
                "- %s / %s：%s" % (hand["hand"], hand["name"], hand["how"][:160])
            )
    if memories:
        lines.append("相关记忆:")
        for mem in memories:
            lines.append("- [%s] %s — %s" % (mem["kind"], mem["title"], mem["body"][:220]))
    else:
        lines.append("相关记忆: （空，这是新问题，做完后 remember）")
    return {"text": "\n".join(lines), "memories": memories, "route": routed}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s" % (time.strftime("%H:%M:%S"), fmt % args))

    def _auth_ok(self):
        if not TOKEN:
            return True
        header = self.headers.get("Authorization") or ""
        if header == "Bearer " + TOKEN:
            return True
        qs = parse_qs(urlparse(self.path).query)
        token = (qs.get("token") or [""])[0]
        return token == TOKEN

    def _send(self, code, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        if not raw:
            return {}
        return json.loads(raw)

    def do_GET(self):
        if not self._auth_ok():
            return self._send(401, {"error": "unauthorized"})
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)
        conn = connect()
        try:
            if path == "/health":
                n = conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"]
                return self._send(200, {"ok": True, "memories": n, "db": DB_PATH})
            if path == "/v1/recall":
                items = recall(
                    conn,
                    (qs.get("q") or [""])[0],
                    limit=(qs.get("limit") or ["8"])[0],
                    kind=(qs.get("kind") or [None])[0] or None,
                )
                return self._send(200, {"items": items})
            if path == "/v1/context":
                pack = context_pack(conn, (qs.get("task") or [""])[0], limit=(qs.get("limit") or ["6"])[0])
                return self._send(200, pack)
            if path == "/v1/route":
                return self._send(200, route(conn, (qs.get("intent") or [""])[0]))
            if path == "/v1/skills":
                rows = conn.execute("SELECT * FROM skills ORDER BY success_count DESC").fetchall()
                return self._send(200, {"items": [dict(r) for r in rows]})
            return self._send(404, {"error": "not found"})
        finally:
            conn.close()

    def do_POST(self):
        if not self._auth_ok():
            return self._send(401, {"error": "unauthorized"})
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        conn = connect()
        try:
            payload = self._body()
            if path == "/v1/remember":
                return self._send(200, remember(conn, payload))
            if path == "/v1/skill":
                return self._send(200, upsert_skill(conn, payload))
            if path == "/v1/skill/success":
                name = (payload.get("name") or "").strip()
                if not name:
                    raise ValueError("name 必填")
                bump_skill(conn, name)
                return self._send(200, {"ok": True, "name": name})
            return self._send(404, {"error": "not found"})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        except Exception as exc:
            return self._send(500, {"error": str(exc)})
        finally:
            conn.close()


def main():
    conn = connect()
    init_db(conn)
    conn.close()
    httpd = HTTPServer((HOST, PORT), Handler)
    print("brain listening on http://%s:%s  db=%s" % (HOST, PORT, DB_PATH), flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
