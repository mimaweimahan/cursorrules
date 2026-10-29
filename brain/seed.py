# -*- coding: utf-8 -*-
"""把已有 .cursor 记忆灌进大脑，只灌一次（按 title 去重）。"""
from __future__ import print_function

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server  # noqa: E402


SEEDS = [
    {
        "kind": "fact",
        "title": "现网推理与入口",
        "body": "GPU 在 Featurize 单卡 4090 48G；对外 OpenAI 兼容 http://VPS:18088/v1；别名 qwen36。OpenClaw 在 VPS，Telegram 机器人，工作区 /www/wwwroot/cura/wwwroot，业务代码在 admin_panel/。",
        "source": "project_context.md",
        "tags": "infra,openclaw,cursor",
        "salience": 3,
    },
    {
        "kind": "pitfall",
        "title": "48GB 显存不等于长上下文",
        "body": "权重占显存大头。Cursor Agent 全工具极易打满窗口。本地改代码优先中小模型+更长 n_ctx，不要用加卡当唯一答案。",
        "source": "project_context.md",
        "tags": "llm,ctx",
        "salience": 3,
    },
    {
        "kind": "pitfall",
        "title": "Cursor 检查后端失败原因",
        "body": "不是没巡检脚本，是 Input token limit exceeded（400）。当时窗口不够装系统提示+工具+历史。",
        "source": "MEMORY_LOCAL_LLM_AGENT.md",
        "tags": "cursor,ctx",
        "salience": 2.5,
    },
    {
        "kind": "decision",
        "title": "当前默认模型",
        "body": "Qwen2.5-Coder-14B-Instruct-abliterated Q4_K_M，n_ctx=65536。网关和 OpenClaw contextWindow 已对齐 65536。标准 Coder-14B 与 35B uncensored 保留可回滚。",
        "source": "MEMORY_LOCAL_LLM_AGENT.md",
        "tags": "model",
        "salience": 3,
    },
    {
        "kind": "pitfall",
        "title": "OpenClaw 读目录常失败",
        "body": "业务不在工作区根而在 admin_panel/；模型爱乱猜路径并用 exec。跟进短句易空转。要用明确路径 + /new 短会话。",
        "source": "MEMORY_LOCAL_LLM_AGENT.md",
        "tags": "openclaw",
        "salience": 2.5,
    },
    {
        "kind": "preference",
        "title": "用户要的是跨软件永久大脑",
        "body": "改过的、看过的、和智能体聊过的必须入库。关电脑、删 Cursor 不能归零。不要微调当进化；进化=记忆+技能树+路由器。库放 VPS，软件只是手和脚。",
        "source": "chat-2026-10-22",
        "tags": "brain,product",
        "salience": 4,
    },
    {
        "kind": "decision",
        "title": "Graphify 不替代 /map",
        "body": "Graphify 管结构底图。ALE /map 管 Frontend→Route→Backend→Model。接口任务仍走 ALE；结构追调用可叠 Graphify 或 codebase-memory MCP。",
        "source": "chat-2026-10-22",
        "tags": "graphify,ale",
        "salience": 2,
    },
]


def main():
    conn = server.connect()
    server.init_db(conn)
    added = 0
    for item in SEEDS:
        exists = conn.execute(
            "SELECT id FROM memories WHERE title=?", (item["title"],)
        ).fetchone()
        if exists:
            continue
        server.remember(conn, item)
        added += 1
        print("seeded:", item["title"])
    print("done, added", added)
    conn.close()


if __name__ == "__main__":
    main()
