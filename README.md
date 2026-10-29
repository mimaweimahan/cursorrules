# 先做什么

这是 Cursor 规则、配置和大脑的每日备份。密钥不会进这个仓库。

## 同一账号，换一台电脑

1. 安装 Git，SSH 能访问 `git@github.com:mimaweimahan/cursorrules.git`
2. 对 Cursor 说信号命令：**脑同步**
3. 或自己执行：

```
git clone git@github.com:mimaweimahan/cursorrules.git C:\benji\cursorrules
python C:\benji\cursorrules\brain\sync_cursorrules.py pull
```

pull 会把大脑放到 `C:\benji\brain`，把规则放到 `%USERPROFILE%\.cursor\rules`，把 code-profile 放到 `C:\benji\cursor-profiles`。在 Cursor 里用 Profiles: Import 导入该文件。

## 不同账号

把 `cursor/user-rules/` 里的 `.mdc` 拷进 `%USERPROFILE%\.cursor\rules`，然后对 Cursor 说 **脑同步**。规则会要求先拉大脑，再开始别的工作。

## 每天

本机计划任务 `BenjiBrainSync` 在 23:50 执行 `sync_cursorrules.py push`。电脑当时关着的话，下次登录会补跑。
