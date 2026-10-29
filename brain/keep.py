# -*- coding: utf-8 -*-
"""本机大脑看门狗。计划任务拉起后一直转：端口不在就启动 server.py，退出就再拉。"""
from __future__ import print_function

import os
import subprocess
import sys
import time

try:
    from urllib.request import urlopen
except ImportError:
    from urllib2 import urlopen

try:
    import msvcrt
except ImportError:
    msvcrt = None

ROOT = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(ROOT, "server.py")
LOG_DIR = os.path.join(ROOT, "data")
LOCK_PATH = os.path.join(LOG_DIR, "keep.lock")
LOG_PATH = os.path.join(LOG_DIR, "keep.log")
HEALTH = os.environ.get("BRAIN_URL", "http://127.0.0.1:18099").rstrip("/") + "/health"
PYTHON = os.environ.get("BRAIN_PYTHON", sys.executable)
if PYTHON.lower().endswith("pythonw.exe"):
    PYTHON = PYTHON[:-11] + "python.exe"


def log(msg):
    if not os.path.isdir(LOG_DIR):
        os.makedirs(LOG_DIR)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a") as handle:
        handle.write("%s %s\n" % (stamp, msg))


def hold_lock():
    if msvcrt is None:
        return None
    if not os.path.isdir(LOG_DIR):
        os.makedirs(LOG_DIR)
    handle = open(LOCK_PATH, "a+")
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except (IOError, OSError):
        handle.close()
        return None
    return handle


def ensure_task():
    """新电脑拷来这份目录后，登录时自动拉起看门狗。已有任务则不动。"""
    if os.name != "nt":
        return
    query = subprocess.call(
        ["schtasks", "/Query", "/TN", "BenjiBrain"],
        stdout=open(os.devnull, "w"),
        stderr=subprocess.STDOUT,
    )
    if query == 0:
        return
    who = "%s\\%s" % (os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", ""))
    pythonw = PYTHON
    if pythonw.lower().endswith("python.exe"):
        pythonw = pythonw[:-10] + "pythonw.exe"
    xml_path = os.path.join(LOG_DIR, "BenjiBrain.task.xml")
    if not os.path.isdir(LOG_DIR):
        os.makedirs(LOG_DIR)
    xml = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><UserId>%s</UserId></LogonTrigger>
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
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions>
    <Exec>
      <Command>%s</Command>
      <Arguments>%s</Arguments>
      <WorkingDirectory>%s</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
""" % (who, who, pythonw, os.path.join(ROOT, "keep.py"), ROOT)
    with open(xml_path, "wb") as handle:
        handle.write(xml.encode("utf-16"))
    code = subprocess.call(["schtasks", "/Create", "/TN", "BenjiBrain", "/XML", xml_path, "/F"])
    log("ensure task BenjiBrain exit=%s" % code)


def healthy():
    try:
        resp = urlopen(HEALTH, timeout=2)
        raw = resp.read()
        resp.close()
        return b'"ok"' in raw
    except Exception:
        return False


def main():
    lock = hold_lock()
    if lock is None and msvcrt is not None:
        return 0
    log("watcher start pid=%s" % os.getpid())
    ensure_task()
    child = None
    misses = 0
    while True:
        if healthy():
            misses = 0
            time.sleep(5)
            continue
        if child is not None and child.poll() is None:
            time.sleep(2)
            continue
        misses += 1
        log("health down, starting server (miss %s)" % misses)
        server_log = open(os.path.join(LOG_DIR, "server.log"), "a")
        child = subprocess.Popen(
            [PYTHON, SERVER],
            cwd=ROOT,
            stdout=server_log,
            stderr=server_log,
        )
        time.sleep(min(3 * misses, 15))
    return 0


if __name__ == "__main__":
    sys.exit(main())
