# -*- coding: utf-8 -*-
"""脑同步：每天把大脑和 Cursor 必要配置推进 cursorrules，新机器用 pull 找回。

信号命令：脑同步
  pull  新机器或会话找不到大脑时先做这个
  push  把本机大脑和配置推上 GitHub（每天 23:50 也会做）
"""
from __future__ import print_function

import os
import re
import shutil
import sqlite3
import subprocess
import sys

REPO_URL = "git@github.com:mimaweimahan/cursorrules.git"
REPO = os.environ.get("CURSORRULES_DIR", r"C:\benji\cursorrules")
BRAIN = os.environ.get("BRAIN_HOME", r"C:\benji\brain")
GIT = os.environ.get("GIT_EXE", r"C:\Program Files\Git\cmd\git.exe")
USERPROFILE = os.environ.get("USERPROFILE", "")
APPDATA = os.environ.get("APPDATA", "")
CURSOR_USER = os.path.join(USERPROFILE, ".cursor")
CURSOR_APPDATA = os.path.join(APPDATA, "Cursor", "User")

BRAIN_FILES = (
    "server.py",
    "client.py",
    "keep.py",
    "seed.py",
    "sync_cursorrules.py",
    "brain.service",
    "openclaw-brain.md",
    "deploy_vps.py",
)
SECRET_RE = re.compile(
    r"ghp_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9]{10,}|"
    r"AKIA[0-9A-Z]{16}|BEGIN (OPENSSH |RSA )?PRIVATE KEY|xox[baprs]-"
)


def log(msg):
    print(msg)
    path = os.path.join(BRAIN, "data", "sync.log")
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "a") as handle:
        handle.write(msg + "\n")


def git(*args, check=True):
    cmd = [GIT, "-C", REPO] + list(args)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.communicate()[0].decode("utf-8", "replace")
    if check and proc.returncode != 0:
        raise RuntimeError(out.strip() or ("git %s failed" % args[0]))
    return out


def ensure_repo():
    if os.path.isdir(os.path.join(REPO, ".git")):
        return
    parent = os.path.dirname(REPO)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    if not os.path.isdir(REPO):
        os.makedirs(REPO)
    subprocess.check_call([GIT, "init", "-b", "main", REPO])
    git("remote", "add", "origin", REPO_URL)
    fetched = git("ls-remote", "--heads", "origin", check=False)
    if "refs/heads/" in fetched:
        git("fetch", "origin")
        git("checkout", "-B", "main", "origin/main")


def backup_db(dest):
    folder = os.path.dirname(dest)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    src_path = os.path.join(BRAIN, "data", "brain.db")
    if not os.path.isfile(src_path):
        raise RuntimeError("missing " + src_path)
    if os.path.isfile(dest):
        os.remove(dest)
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def redact_text(text):
    text = re.sub(r"Bearer\s+\S+", "Bearer REDACTED", text)
    text = SECRET_RE.sub("REDACTED", text)
    return text


def copy_file(src, dest):
    folder = os.path.dirname(dest)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    shutil.copy2(src, dest)


def copy_tree(src, dest):
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    if not os.path.isdir(src):
        return
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.log"))


def reset_dir(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path)


def export_bundle():
    brain_out = os.path.join(REPO, "brain")
    reset_dir(brain_out)
    os.makedirs(os.path.join(brain_out, "data"))
    for name in BRAIN_FILES:
        src = os.path.join(BRAIN, name)
        if os.path.isfile(src):
            copy_file(src, os.path.join(brain_out, name))
    backup_db(os.path.join(brain_out, "data", "brain.db"))

    rules_out = os.path.join(REPO, "cursor", "user-rules")
    copy_tree(os.path.join(CURSOR_USER, "rules"), rules_out)
    workspace_rules = os.path.join(r"C:\benji", ".cursor", "rules")
    copy_tree(workspace_rules, os.path.join(REPO, "cursor", "workspace-rules"))
    copy_tree(os.path.join(CURSOR_USER, "skills"), os.path.join(REPO, "cursor", "skills"))

    cursor_out = os.path.join(REPO, "cursor")
    if not os.path.isdir(cursor_out):
        os.makedirs(cursor_out)
    for name in ("settings.json", "keybindings.json"):
        src = os.path.join(CURSOR_APPDATA, name)
        if os.path.isfile(src):
            copy_file(src, os.path.join(cursor_out, name))
    mcp = os.path.join(CURSOR_USER, "mcp.json")
    if os.path.isfile(mcp):
        with open(mcp, "r", encoding="utf-8") as handle:
            redacted = redact_text(handle.read())
        with open(os.path.join(cursor_out, "mcp.json"), "w", encoding="utf-8") as handle:
            handle.write(redacted)
    template = os.path.join(CURSOR_USER, "mcp.json.template")
    if os.path.isfile(template):
        with open(template, "r", encoding="utf-8") as handle:
            text = redact_text(handle.read())
        with open(os.path.join(cursor_out, "mcp.json.template"), "w", encoding="utf-8") as handle:
            handle.write(text)
    write_readme()
    write_gitignore()


def write_gitignore():
    path = os.path.join(REPO, ".gitignore")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("__pycache__/\n*.pyc\n*.log\nkeep.lock\n")


def write_readme():
    path = os.path.join(REPO, "README.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("""# 先做什么

这是 Cursor 规则、配置和大脑的每日备份。密钥不会进这个仓库。

## 同一账号，换一台电脑

1. 安装 Git，SSH 能访问 `git@github.com:mimaweimahan/cursorrules.git`
2. 对 Cursor 说信号命令：**脑同步**
3. 或自己执行：

```
git clone git@github.com:mimaweimahan/cursorrules.git C:\\benji\\cursorrules
python C:\\benji\\cursorrules\\brain\\sync_cursorrules.py pull
```

pull 会把大脑放到 `C:\\benji\\brain`，把规则放到 `%USERPROFILE%\\.cursor\\rules`，并检查 `http://127.0.0.1:18099`。

## 不同账号

把 `cursor/user-rules/` 里的 `.mdc` 拷进 `%USERPROFILE%\\.cursor\\rules`，然后对 Cursor 说 **脑同步**。规则会要求先拉大脑，再开始别的工作。

## 每天

本机计划任务 `BenjiBrainSync` 在 23:50 执行 `sync_cursorrules.py push`。电脑当时关着的话，下次登录会补跑。
""")


def scan_secrets():
    hits = []
    for root, dirs, files in os.walk(REPO):
        if ".git" in root.split(os.sep):
            continue
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            path = os.path.join(root, name)
            try:
                with open(path, "rb") as handle:
                    raw = handle.read()
            except (IOError, OSError):
                continue
            if SECRET_RE.search(raw.decode("utf-8", "replace")):
                hits.append(path)
    if hits:
        raise RuntimeError("refusing to commit secrets: " + ", ".join(hits))


def commit_and_push():
    git("add", "-A")
    status = git("status", "--porcelain")
    if not status.strip():
        log("nothing to push")
        return
    name = subprocess.check_output(["git", "config", "--global", "--get", "user.name"]).decode().strip()
    email = subprocess.check_output(["git", "config", "--global", "--get", "user.email"]).decode().strip()
    subprocess.check_call(
        [
            GIT, "-C", REPO,
            "-c", "user.name=" + name,
            "-c", "user.email=" + email,
            "commit", "-m", "daily: brain and cursor config",
        ]
    )
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch == "HEAD":
        git("checkout", "-B", "main")
        branch = "main"
    remote = git("ls-remote", "--heads", "origin", branch, check=False)
    if remote.strip():
        git("pull", "--rebase", "origin", branch)
    git("push", "-u", "origin", "HEAD")
    log("pushed " + branch)
    ensure_daily_task()


def push():
    ensure_repo()
    export_bundle()
    scan_secrets()
    commit_and_push()


def copy_into(src, dest):
    if os.path.isdir(src):
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    elif os.path.isfile(src):
        copy_file(src, dest)


def pull():
    ensure_repo()
    remote = git("ls-remote", "--heads", "origin", check=False)
    if "refs/heads/" in remote:
        git("fetch", "origin")
        git("checkout", "-B", "main", "origin/main")
    brain_src = os.path.join(REPO, "brain")
    if not os.path.isdir(brain_src):
        raise RuntimeError("repo has no brain/ yet")
    if not os.path.isdir(BRAIN):
        os.makedirs(BRAIN)
    for name in os.listdir(brain_src):
        if name == "data":
            continue
        src = os.path.join(brain_src, name)
        dest = os.path.join(BRAIN, name)
        if os.path.isfile(src):
            if os.path.abspath(src) != os.path.abspath(dest):
                copy_file(src, dest)
    db_src = os.path.join(brain_src, "data", "brain.db")
    db_dest = os.path.join(BRAIN, "data", "brain.db")
    if os.path.isfile(db_src):
        if not os.path.isdir(os.path.dirname(db_dest)):
            os.makedirs(os.path.dirname(db_dest))
        local_newer = os.path.isfile(db_dest) and os.path.getmtime(db_dest) > os.path.getmtime(db_src)
        if not local_newer:
            copy_file(db_src, db_dest)
            log("restored brain.db")
        else:
            log("kept newer local brain.db")
    copy_into(os.path.join(REPO, "cursor", "user-rules"), os.path.join(CURSOR_USER, "rules"))
    copy_into(os.path.join(REPO, "cursor", "skills"), os.path.join(CURSOR_USER, "skills"))
    workspace = os.path.join(r"C:\benji", ".cursor", "rules")
    copy_into(os.path.join(REPO, "cursor", "workspace-rules"), workspace)
    if not os.path.isdir(CURSOR_APPDATA):
        os.makedirs(CURSOR_APPDATA)
    for name in ("settings.json", "keybindings.json"):
        src = os.path.join(REPO, "cursor", name)
        if os.path.isfile(src):
            copy_file(src, os.path.join(CURSOR_APPDATA, name))
    mcp_dest = os.path.join(CURSOR_USER, "mcp.json")
    mcp_src = os.path.join(REPO, "cursor", "mcp.json")
    if os.path.isfile(mcp_src) and not os.path.isfile(mcp_dest):
        copy_file(mcp_src, mcp_dest)
        log("wrote redacted mcp.json; fill tokens locally")
    ensure_daily_task()
    try:
        if BRAIN not in sys.path:
            sys.path.insert(0, BRAIN)
        import keep
        keep.ensure_task()
    except Exception as exc:
        log("keep task: " + str(exc))
    log("pull done")


def ensure_daily_task():
    if os.name != "nt":
        return
    query = subprocess.call(
        ["schtasks", "/Query", "/TN", "BenjiBrainSync"],
        stdout=open(os.devnull, "w"),
        stderr=subprocess.STDOUT,
    )
    if query == 0:
        return
    who = "%s\\%s" % (os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", ""))
    python = sys.executable
    if python.lower().endswith("pythonw.exe"):
        python = python[:-11] + "python.exe"
    script = os.path.join(BRAIN, "sync_cursorrules.py")
    xml_path = os.path.join(BRAIN, "data", "BenjiBrainSync.task.xml")
    if not os.path.isdir(os.path.dirname(xml_path)):
        os.makedirs(os.path.dirname(xml_path))
    xml = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-10-29T23:50:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal>
      <UserId>%s</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
  </Settings>
  <Actions>
    <Exec>
      <Command>%s</Command>
      <Arguments>%s push</Arguments>
      <WorkingDirectory>%s</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
""" % (who, python, script, BRAIN)
    with open(xml_path, "wb") as handle:
        handle.write(xml.encode("utf-16"))
    code = subprocess.call(["schtasks", "/Create", "/TN", "BenjiBrainSync", "/XML", xml_path, "/F"])
    log("BenjiBrainSync create exit=%s" % code)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "push"
    if cmd == "push":
        push()
    elif cmd == "pull":
        pull()
    else:
        sys.stderr.write("usage: sync_cursorrules.py pull|push\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
