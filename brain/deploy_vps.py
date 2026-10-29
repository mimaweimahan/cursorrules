# -*- coding: utf-8 -*-
"""把大脑装到 VPS。密码只读环境变量 VPS_SSH_PASSWORD，不写进仓库。"""
from __future__ import print_function

import os
import posixpath
import sys

import paramiko

VPS_HOST = os.environ.get("VPS_HOST", "72.62.244.212")
VPS_PORT = int(os.environ.get("VPS_PORT", "22456"))
VPS_USER = os.environ.get("VPS_USER", "root")
REMOTE_DIR = "/opt/brain"
FILES = ("server.py", "client.py", "seed.py", "brain.service", "openclaw-brain.md")


def main():
    password = os.environ.get("VPS_SSH_PASSWORD")
    if not password:
        sys.stderr.write("请先设置环境变量 VPS_SSH_PASSWORD\n")
        sys.exit(1)
    here = os.path.dirname(os.path.abspath(__file__))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        VPS_HOST,
        port=VPS_PORT,
        username=VPS_USER,
        password=password,
        timeout=45,
        allow_agent=False,
        look_for_keys=False,
    )
    sftp = client.open_sftp()
    for cmd in (
        "mkdir -p /opt/brain /var/lib/brain",
        "test -f /etc/brain.env || echo BRAIN_TOKEN= > /etc/brain.env",
    ):
        client.exec_command(cmd)
    for name in FILES:
        local = os.path.join(here, name)
        remote = posixpath.join(REMOTE_DIR, name)
        sftp.put(local, remote)
        print("uploaded", remote)
    cmds = [
        "chmod 755 /opt/brain/server.py /opt/brain/client.py /opt/brain/seed.py",
        "cp /opt/brain/brain.service /etc/systemd/system/brain.service",
        "python3 /opt/brain/seed.py",
        "systemctl daemon-reload",
        "systemctl enable --now brain.service",
        "systemctl --no-pager --full status brain.service | head -n 20",
        "python3 /opt/brain/client.py health",
    ]
    for cmd in cmds:
        print("$", cmd)
        stdin, stdout, stderr = client.exec_command(cmd)
        sys.stdout.write(stdout.read().decode("utf-8", "replace"))
        sys.stderr.write(stderr.read().decode("utf-8", "replace"))
    sftp.close()
    client.close()
    print("VPS 大脑已监听 127.0.0.1:18099。OpenClaw 直接用；本机 Cursor 请 SSH 转发该端口。")


if __name__ == "__main__":
    main()
