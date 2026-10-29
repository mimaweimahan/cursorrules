# -*- coding: utf-8 -*-
"""本机/VPS 永久记忆库。标准库 + SQLite FTS5。

模糊召回用可重建的向量索引（中文双字加英文词，按文档频率加权）。
本机 Python 自带 SQLite 3.32，加载不了需要 3.41+ 的 sqlite-vec。
向量只是索引，原文仍在 memories 表，删掉 memory_vec 会按原文重建。
"""
from __future__ import print_function

import hashlib
import json
import math
import os
import sqlite3
import struct
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
VEC_DIM = 256
VEC_KEEP = 0.55

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
        CREATE TABLE IF NOT EXISTS memory_vec (
            id INTEGER PRIMARY KEY,
            vec BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS brain_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TRIGGER IF NOT EXISTS memories_vec_ad AFTER DELETE ON memories BEGIN
            DELETE FROM memory_vec WHERE id=old.id;
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
    ensure_vectors(conn)


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


def memory_tokens(text):
    """英文词整段保留；中文切成双字。路径、IP、文件名因此仍是完整词。"""
    text = (text or "").lower()
    toks = []
    buf = []

    def flush():
        if len(buf) >= 2:
            toks.append("".join(buf))
        del buf[:]

    chars = []
    for ch in text:
        if ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch in "._/+-:":
            buf.append(ch)
            continue
        flush()
        if "\u4e00" <= ch <= "\u9fff":
            chars.append(ch)
    flush()
    for i in range(len(chars) - 1):
        toks.append(chars[i] + chars[i + 1])
    if len(chars) == 1:
        toks.append(chars[0])
    return toks


def embed_tokens(toks, weights, default=1.0):
    vec = [0.0] * VEC_DIM
    if not toks:
        return vec
    for tok in toks:
        weight = weights.get(tok, default) if weights else 1.0
        if weight == 0:
            continue
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "little") % VEC_DIM
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[bucket] += sign * weight
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def pack_vec(vec):
    return struct.pack("<%df" % len(vec), *vec)


def unpack_vec(blob):
    count = len(blob) // 4
    return struct.unpack("<%df" % count, blob)


def dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def reindex_vectors(conn):
    """按当前原文重建全部向量和词权重。索引可丢，原文不丢。"""
    rows = conn.execute("SELECT id, title, body FROM memories").fetchall()
    docs = []
    df = {}
    for row in rows:
        text = ((row["title"] or "") + "\n") * 3 + (row["body"] or "")
        toks = memory_tokens(text)
        docs.append((row["id"], toks))
        for tok in set(toks):
            df[tok] = df.get(tok, 0) + 1
    n = len(docs)
    weights = {}
    for tok, freq in df.items():
        weights[tok] = math.log((n + 1.0) / (freq + 1.0)) + 1.0
    default = math.log(n + 1.0) + 1.0
    conn.execute("DELETE FROM memory_vec")
    for mid, toks in docs:
        blob = pack_vec(embed_tokens(toks, weights, default))
        conn.execute("INSERT INTO memory_vec(id, vec) VALUES (?, ?)", (mid, sqlite3.Binary(blob)))
    conn.execute(
        "INSERT INTO brain_meta(key, value) VALUES('idf', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (json.dumps({"w": weights, "d": default}, ensure_ascii=False),),
    )
    conn.commit()
    return {"ok": True, "count": n, "dim": VEC_DIM}


def ensure_vectors(conn):
    memories = conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"]
    vectors = conn.execute("SELECT COUNT(*) AS c FROM memory_vec").fetchone()["c"]
    if memories != vectors:
        reindex_vectors(conn)


def load_weights(conn):
    row = conn.execute("SELECT value FROM brain_meta WHERE key='idf'").fetchone()
    if not row:
        return {}, 1.0
    data = json.loads(row["value"])
    return data.get("w") or {}, float(data.get("d") or 1.0)


def vector_hits(conn, query, limit):
    weights, default = load_weights(conn)
    if not weights:
        return []
    query_vec = embed_tokens(memory_tokens(query), weights, default)
    if not any(query_vec):
        return []
    scored = []
    for row in conn.execute("SELECT id, vec FROM memory_vec"):
        scored.append((row["id"], dot(query_vec, unpack_vec(row["vec"]))))
    scored.sort(key=lambda item: item[1], reverse=True)
    if not scored or scored[0][1] <= 0:
        return []
    best = scored[0][1]
    kept = []
    for mid, score in scored:
        if score < best * VEC_KEEP:
            break
        kept.append((mid, score))
        if len(kept) >= limit:
            break
    return kept


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


def upsert_memory(conn, kind, title, body, source, salience=1.0, tags=""):
    title = (title or "").strip()
    body = (body or "").strip()
    source = (source or "").strip()
    if not title or not body:
        raise ValueError("title 和 body 必填")
    if kind not in KINDS:
        kind = "episode"
    ts = now_iso()
    row = None
    if source:
        row = conn.execute(
            "SELECT id FROM memories WHERE kind=? AND source=?",
            (kind, source),
        ).fetchone()
    if row:
        conn.execute(
            "UPDATE memories SET title=?, body=?, tags=?, salience=?, updated_at=? WHERE id=?",
            (title[:180], body[:8000], tags, float(salience), ts, row["id"]),
        )
        conn.commit()
        reindex_vectors(conn)
        saved = conn.execute("SELECT * FROM memories WHERE id=?", (row["id"],)).fetchone()
        return row_mem(saved)
    return remember(conn, {
        "kind": kind,
        "title": title[:180],
        "body": body[:8000],
        "source": source,
        "tags": tags,
        "salience": salience,
    })


def record_session(conn, payload):
    """一场会话的原文档案，外加一条可复用短句。同一 session 反复调用会覆盖，不堆重复。"""
    sid = (payload.get("session_id") or "").strip() or "unknown"
    prompts = [p.strip() for p in (payload.get("prompts") or []) if isinstance(p, str) and p.strip()]
    responses = [p.strip() for p in (payload.get("responses") or []) if isinstance(p, str) and p.strip()]
    if not prompts and not responses:
        return {"ok": True, "skipped": True}
    lines = []
    turns = max(len(prompts), len(responses))
    for i in range(turns):
        if i < len(prompts):
            lines.append("用户: " + prompts[i][:1500])
        if i < len(responses):
            lines.append("回复: " + responses[i][:1500])
    body = "\n".join(lines)[:8000]
    title = (prompts[0] if prompts else "会话 " + sid[:8])[:80]
    episode = upsert_memory(
        conn, "episode", title, body, "session:" + sid, salience=1.0, tags="session",
    )
    distilled = None
    last = responses[-1] if responses else ""
    if prompts and len(last) >= 40 and len(prompts[0]) >= 4:
        kind = "decision"
        if "坑" in last[:80] or "不要" in last[:40]:
            kind = "pitfall"
        elif last.startswith("常识"):
            kind = "common_sense"
        distilled = upsert_memory(
            conn,
            kind,
            title,
            last[:700],
            "distill:" + sid,
            salience=2.0,
            tags="distill",
        )
    return {"ok": True, "episode_id": episode["id"], "distill_id": distilled["id"] if distilled else None}


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
    reindex_vectors(conn)
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
    found = [row_mem(r) for r in rows]
    seen = set(item["id"] for item in found)
    if len(found) < limit:
        for mid, _score in vector_hits(conn, query, limit):
            if mid in seen:
                continue
            if kind:
                row = conn.execute(
                    "SELECT * FROM memories WHERE id=? AND kind=?", (mid, kind)
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM memories WHERE id=?", (mid,)).fetchone()
            if not row:
                continue
            found.append(row_mem(row))
            seen.add(mid)
            if len(found) >= limit:
                break
    bump_ids = [item["id"] for item in found if item["kind"] != "episode"]
    if bump_ids:
        marks = ",".join("?" for _ in bump_ids)
        conn.execute(
            "UPDATE memories SET salience=MIN(5.0, salience+0.1), updated_at=? "
            "WHERE id IN (%s) AND kind!='episode'" % marks,
            [now_iso()] + bump_ids,
        )
        conn.commit()
    return found


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
                v = conn.execute("SELECT COUNT(*) AS c FROM memory_vec").fetchone()["c"]
                return self._send(200, {"ok": True, "memories": n, "vectors": v, "db": DB_PATH})
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
            if path == "/v1/session":
                return self._send(200, record_session(conn, payload))
            if path == "/v1/reindex":
                return self._send(200, reindex_vectors(conn))
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
