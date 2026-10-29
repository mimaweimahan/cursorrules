# 贴进 OpenClaw 工作区（VPS）

把下面整段追加到 `/www/wwwroot/cura/wwwroot/AGENTS.md` 或 `SOUL.md`。

```
永久记忆在本机大脑 http://127.0.0.1:18099 （不要问 Cursor 聊天记录）。
开始任务先：python3 /opt/brain/client.py context --task "用户原话"
给出结论后：python3 /opt/brain/client.py remember --kind decision --title "短标题" --body "结论" --source "openclaw"
选工具先：python3 /opt/brain/client.py route "用户原话"
禁止把 API Key、密码写进大脑。
业务代码在 admin_panel/，不要猜工作区根目录文件。
```
